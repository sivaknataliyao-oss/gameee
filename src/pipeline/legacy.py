"""End-to-end pipeline orchestrator.

Phases per story:
  1. filter / rights gate
  2. script (title + RU + markers + image scenes)
  3. tts (per-segment) + precise per-chapter timings
  4. image fetch (chain, scene-coherent groups)
  5. audio master + music ducking + cliffhanger SFX
  6. video compose (slideshow + typewriter) + vertical reframe
  7. thumbnail
  8. clipper: shorts cut on REAL chapter boundaries
  9. package + schedule + (optional) publish
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.analytics.collector import log_event
from src.audio import music as music_mod
from src.audio.postprocess import concat as audio_concat
from src.audio.postprocess import master as audio_master
from src.core import config
from src.core.models import (
    LengthProfile,
    ProcessedStory,
    RenderArtifacts,
    Scene,
    Story,
)
from src.core.storage import block_story, finish_run, mark_used, start_run
from src.filters.pipeline import accept
from src.images.router import ImageRouter
from src.publish import package as pkg_mod
from src.publish import scheduler
from src.publish import tiktok as tiktok_pub
from src.publish import youtube as yt_pub
from src.rights.manager import is_cleared
from src.script import llm as script_llm
from src.script.segmenter import Segment, segments
from src.tts.router import TTSRouter
from src.video import intro as intro_mod
from src.video import loop_hook
from src.video import thumbnail as thumb
from src.video.clipper import cut_shorts, plan_from_timings
from src.video.hook_variants import make_ab
from src.video.templates.slideshow_typewriter import build as build_template

log = logging.getLogger(__name__)


# RunOptions moved to src/core/context.py; re-export for backward compatibility.
from src.core.context import RunOptions  # noqa: F401


def choose_profile(story: Story) -> LengthProfile:
    lf = config.filters().get("length_profiles", {}).get("long", {})
    min_pot = float(lf.get("min_long_form_potential", 0.7))
    min_chars = int(lf.get("min_source_chars", 3000))
    if story.long_form_potential >= min_pot and len(story.text) >= min_chars:
        return LengthProfile.LONG
    return LengthProfile.SHORT


def process_one(story: Story, opts: RunOptions) -> RenderArtifacts | None:
    run_dir = config.runs_dir() / datetime.now(timezone.utc).strftime("%Y-%m-%d") / story.id.replace(":", "_")
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = start_run(story.id, run_dir)

    try:
        # --- Gates: filters + rights ---
        ok, reason = accept(story)
        if not ok:
            block_story(story.id, reason)
            finish_run(run_id, "blocked", reason)
            log_event(story.id, "blocked", {"reason": reason})
            return None

        if not is_cleared(story.id, research_mode=opts.research_mode):
            block_story(story.id, "no_permission")
            finish_run(run_id, "blocked", "no_permission")
            log_event(story.id, "blocked_no_rights")
            return None

        # --- Script ---
        profile = opts.profile if opts.profile is not None else choose_profile(story)
        processed: ProcessedStory = script_llm.process(story, profile=profile)
        (run_dir / "processed.json").write_text(
            processed.model_dump_json(indent=2), encoding="utf-8",
        )

        # --- TTS per segment + measure each ---
        tts = TTSRouter()
        seg_list = segments(processed)
        seg_audio: list[tuple[Segment, Path, float]] = []
        for i, seg in enumerate(seg_list):
            out = run_dir / f"seg_{i:02d}_{seg.kind}_{seg.index}.wav"
            tts.synthesize(seg.text, out)
            dur = _probe_duration(out)
            seg_audio.append((seg, out, dur))

        # --- Compose narration audio with gap offsets we control ---
        gap = 0.35
        voice_raw = run_dir / "narration_raw.wav"
        audio_concat([p for _, p, _ in seg_audio], voice_raw, gap_sec=gap)
        voice_master = run_dir / "narration_master.wav"
        audio_master(voice_raw, voice_master)

        # --- Precise chapter time ranges (sum real segment durations + gap) ---
        chapter_ranges = _chapter_ranges_from_segments(seg_audio, gap)

        # --- SFX at cliffhanger boundaries + music bed with ducking ---
        sfx_stamps = [(end - 0.2, "whoosh*") for _, end, _ in chapter_ranges if end > 0]
        voice_sfx = run_dir / "narration_sfx.wav"
        music_mod.overlay_sfx(voice_master, sfx_stamps, voice_sfx)

        narration_final = run_dir / "narration.wav"
        music_mod.mix_with_music(voice_sfx, narration_final)

        duration_sec = _probe_duration(narration_final)

        # --- Images (scene-coherent) ---
        router = ImageRouter()
        images = _generate_scene_images(router, processed, run_dir, duration_sec)
        if not images:
            finish_run(run_id, "failed", "no_images")
            log_event(story.id, "failed_no_images")
            return None

        # --- Video compose ---
        tpl = build_template(
            audio_path=narration_final,
            images=images,
            run_dir=run_dir,
            duration_sec=duration_sec,
        )

        # --- Intro stinger prepended to the long 16:9 (not to shorts) ---
        intro_offset = 0.0
        if opts.intro_stinger:
            try:
                intro_mp4 = intro_mod.build_intro(run_dir / "intro.mp4", ratio="16:9")
                if intro_mp4:
                    with_intro = run_dir / "long_16x9_with_intro.mp4"
                    intro_mod.prepend(tpl.long_16x9, intro_mp4, with_intro)
                    tpl.long_16x9 = with_intro
                    intro_offset = _probe_duration(intro_mp4)
            except Exception as exc:
                log.warning("intro stinger failed: %s", exc)

        # --- Thumbnail ---
        thumb_path = run_dir / "thumbnail.jpg"
        try:
            thumb.render(images, processed.selected_title, thumb_path)
        except Exception as exc:
            log.warning("thumbnail render failed: %s", exc)
            thumb_path = None  # not fatal

        # --- Shorts clipping on REAL boundaries ---
        plans = plan_from_timings(chapter_ranges, max_short_sec=75.0)
        shorts_dir = run_dir / "shorts"
        shorts = cut_shorts(tpl.long_9x16, plans, shorts_dir)

        # --- Loop-hook post-processing (seamless end -> start crossfade) ---
        if opts.loop_hook and shorts:
            looped: list[Path] = []
            for sh in shorts:
                try:
                    out = sh.with_name(sh.stem + "_loop.mp4")
                    loop_hook.make_loopable(sh, out, overlap=0.5)
                    sh.unlink(missing_ok=True)
                    out.rename(sh)
                    looped.append(sh)
                except Exception as exc:
                    log.warning("loop_hook failed on %s: %s", sh.name, exc)
                    looped.append(sh)
            shorts = looped

        # --- A/B variants for the first short (test which hook wins) ---
        ab_variants: list[tuple[str, Path]] = []
        if opts.ab_test_first_short and shorts:
            try:
                ab_variants = make_ab(
                    shorts[0], processed.title_variants, shorts_dir / "ab",
                )
            except Exception as exc:
                log.warning("A/B variants failed: %s", exc)

        # --- Package + schedule + publish ---
        packages_dir = run_dir / "packages"
        packages_dir.mkdir(exist_ok=True)

        yt_long_pkg = pkg_mod.build_long_youtube(
            title=processed.selected_title,
            description=f"{processed.hook}\n\n#storytime",
            keywords=processed.keywords,
            video_path=tpl.long_16x9,
            publish_at=None,
            chapter_ranges=chapter_ranges,
            intro_offset_sec=intro_offset,
        )
        pkg_mod.dump(yt_long_pkg, packages_dir)

        short_packages: list[tuple[str, pkg_mod.Package]] = []
        for i, short_mp4 in enumerate(shorts, start=1):
            yt_short = pkg_mod.build_short(
                "youtube_shorts", i, len(shorts),
                processed.selected_title, processed.keywords, short_mp4,
            )
            tt_short = pkg_mod.build_short(
                "tiktok", i, len(shorts),
                processed.selected_title, processed.keywords, short_mp4,
            )
            pkg_mod.dump(yt_short, packages_dir)
            pkg_mod.dump(tt_short, packages_dir)
            if opts.tiktok_package:
                tiktok_pub.export(tt_short, packages_dir / f"tiktok_{i:02d}")
            short_packages.append(("youtube_shorts", yt_short))
            short_packages.append(("tiktok", tt_short))

        if opts.enqueue_schedule:
            try:
                scheduler.enqueue(
                    story.id, "youtube", tpl.long_16x9,
                    yt_long_pkg.title, yt_long_pkg.description, yt_long_pkg.hashtags,
                )
                for platform, p in short_packages:
                    scheduler.enqueue(
                        story.id, platform, p.video_path,
                        p.title, p.description, p.hashtags,
                    )
                # A/B: enqueue both variants of the first short so the scheduler
                # spaces them out per-platform cadence and we can compare CTR.
                for variant_label, variant_path in ab_variants:
                    for platform in ("youtube_shorts", "tiktok"):
                        variant_title = (
                            (processed.title_variants[0] if variant_label == "A"
                             else (processed.title_variants[1]
                                   if len(processed.title_variants) > 1
                                   else processed.title_variants[0]))
                        )
                        scheduler.enqueue(
                            story.id, platform, variant_path,
                            f"[{variant_label}] " + variant_title[:60],
                            f"Variant {variant_label}. " + processed.hook,
                            processed.keywords + ["shorts", "storytime",
                                                  f"variant_{variant_label.lower()}"],
                        )
            except Exception as exc:
                log.warning("scheduler.enqueue failed: %s", exc)

        if opts.publish_youtube:
            try:
                vid = yt_pub.upload(yt_long_pkg)
                log_event(story.id, "yt_uploaded", {"video_id": vid})
            except Exception as exc:
                log.warning("youtube upload failed: %s", exc)

        mark_used(story.id)
        finish_run(run_id, "ok")

        return RenderArtifacts(
            story_id=story.id,
            audio_long=str(narration_final),
            audio_chapters=[str(p) for _, p, _ in seg_audio],
            subtitles_ass=str(tpl.subtitles_ass) if tpl.subtitles_ass else None,
            typewriter_png_dir=str(tpl.typewriter_dir),
            slideshow_long_mp4=str(tpl.long_16x9),
            long_video_mp4=str(tpl.long_16x9),
            shorts_mp4=[str(p) for p in shorts],
            tiktok_mp4=[str(p) for p in shorts],
            thumbnail=str(thumb_path) if thumb_path else None,
        )
    except Exception as exc:
        log.exception("pipeline error: %s", exc)
        finish_run(run_id, "failed", str(exc))
        log_event(story.id, "failed", {"error": str(exc)})
        return None


# ------------- helpers -------------

def _probe_duration(audio_path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        check=True, capture_output=True, text=True,
    )
    return float(r.stdout.strip() or 0)


def _chapter_ranges_from_segments(
    seg_audio: list[tuple[Segment, Path, float]],
    gap_sec: float,
) -> list[tuple[float, float, str]]:
    """Fold per-segment durations into per-chapter (start, end, hook) windows.

    Hook belongs to chapter 1 (or the first real chapter). Outro is excluded.
    """
    ranges: dict[int, list[float]] = {}   # chapter_index -> [start, end]
    first_chapter_idx: int | None = None
    hook_text = ""
    cursor = 0.0

    for seg, _p, dur in seg_audio:
        segment_start = cursor
        segment_end = cursor + dur
        cursor = segment_end + gap_sec

        if seg.kind == "hook":
            hook_text = seg.text
            # temporarily attach hook to whatever the first chapter turns out to be
            continue
        if seg.kind == "outro":
            continue

        idx = seg.index
        if first_chapter_idx is None:
            first_chapter_idx = idx
            # Prepend hook window to first chapter: extend start backwards by the
            # time we already consumed for the hook + its gap.
            hook_time = next((d for s, _q, d in seg_audio if s.kind == "hook"), 0.0)
            hook_span = hook_time + (gap_sec if hook_time > 0 else 0)
            ranges[idx] = [max(0.0, segment_start - hook_span), segment_end]
        elif idx in ranges:
            ranges[idx][1] = segment_end
        else:
            ranges[idx] = [segment_start, segment_end]

    ordered = sorted(ranges.items(), key=lambda kv: kv[0])
    return [(start, end, hook_text if idx == first_chapter_idx else "")
            for idx, (start, end) in ordered]


def _generate_scene_images(router: ImageRouter, processed: ProcessedStory,
                           run_dir: Path, duration_sec: float) -> list[Path]:
    """Build an image list ordered by chapter, with visually coherent groups."""
    images_per_min = int(config.images().get("slideshow", {}).get("images_per_minute", 2))
    needed = max(4, int((duration_sec / 60.0) * images_per_min))
    img_dir = run_dir / "images"
    img_dir.mkdir(exist_ok=True)

    scenes: list[Scene] = processed.scenes or [
        Scene(label="fallback", chapter_index=0, prompts=processed.image_prompts or []),
    ]
    if not any(s.prompts for s in scenes):
        return []

    # Distribute "needed" across scenes proportionally to their prompt count,
    # but guarantee at least 1 image per scene.
    total_prompts = sum(max(1, len(s.prompts)) for s in scenes)
    per_scene_quota = [
        max(1, round(needed * max(1, len(s.prompts)) / total_prompts)) for s in scenes
    ]

    ordered: list[Path] = []
    for scene, quota in zip(scenes, per_scene_quota):
        per_prompt = max(1, quota // max(1, len(scene.prompts)))
        taken = 0
        for prompt in scene.prompts:
            if taken >= quota:
                break
            imgs = router.generate(prompt, per_prompt, "16:9", img_dir / scene.label)
            ordered.extend(imgs)
            taken += len(imgs)
        if taken < quota and scene.prompts:
            extra = router.generate(scene.prompts[0], quota - taken, "16:9",
                                    img_dir / scene.label)
            ordered.extend(extra)

    if len(ordered) < needed and processed.image_prompts:
        # Top up from the flat list if scenes didn't deliver.
        extra = router.generate(", ".join(processed.keywords[:3]) or processed.selected_title,
                                needed - len(ordered), "16:9", img_dir)
        ordered.extend(extra)

    return ordered[:needed]
