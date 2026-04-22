"""End-to-end pipeline orchestrator.

Phases per story:
  1. filter / rights gate
  2. script (title + RU + markers + image prompts)
  3. tts + audio master
  4. image fetch (chain)
  5. video compose (slideshow + typewriter) + vertical reframe
  6. clipper: produce N shorts with CTA
  7. publish packages (YT, TikTok, IG)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.analytics.collector import log_event
from src.audio.postprocess import concat as audio_concat
from src.audio.postprocess import master as audio_master
from src.core import config
from src.core.models import (
    LengthProfile,
    ProcessedStory,
    RenderArtifacts,
    Story,
)
from src.core.storage import block_story, finish_run, mark_used, start_run
from src.filters.pipeline import accept
from src.images.router import ImageRouter
from src.publish import package as pkg_mod
from src.publish import tiktok as tiktok_pub
from src.publish import youtube as yt_pub
from src.rights.manager import is_cleared
from src.script import llm as script_llm
from src.script.segmenter import segments
from src.tts.router import TTSRouter
from src.video.clipper import cut_shorts, plan_from_timings
from src.video.templates.slideshow_typewriter import build as build_template

log = logging.getLogger(__name__)


@dataclass
class RunOptions:
    research_mode: bool = False
    publish_youtube: bool = False
    tiktok_package: bool = True
    profile: LengthProfile = LengthProfile.SHORT


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

        profile = opts.profile if opts.profile is not None else choose_profile(story)
        processed: ProcessedStory = script_llm.process(story, profile=profile)
        (run_dir / "processed.json").write_text(
            processed.model_dump_json(indent=2), encoding="utf-8",
        )

        # --- TTS ---
        tts = TTSRouter()
        seg_audio_paths: list[Path] = []
        for i, seg in enumerate(segments(processed)):
            out = run_dir / f"seg_{i:02d}_{seg.kind}.wav"
            tts.synthesize(seg.text, out)
            seg_audio_paths.append(out)

        audio_raw = run_dir / "narration_raw.wav"
        audio_concat(seg_audio_paths, audio_raw, gap_sec=0.35)
        audio_master_path = run_dir / "narration.wav"
        audio_master(audio_raw, audio_master_path)

        # Target render duration == audio duration plus small tail. Use ffprobe.
        duration_sec = _probe_duration(audio_master_path)

        # --- Images ---
        router = ImageRouter()
        images_per_min = int(config.images().get("slideshow", {}).get("images_per_minute", 2))
        needed = max(4, int((duration_sec / 60.0) * images_per_min))

        img_dir = run_dir / "images"
        img_dir.mkdir(exist_ok=True)
        images: list[Path] = []

        prompts = processed.image_prompts or [", ".join(processed.keywords[:3]) or processed.selected_title]
        per_prompt = max(1, needed // max(1, len(prompts)))
        for pr in prompts:
            imgs = router.generate(pr, per_prompt, "16:9", img_dir)
            images.extend(imgs)
            if len(images) >= needed:
                break

        if not images:
            finish_run(run_id, "failed", "no_images")
            log_event(story.id, "failed_no_images")
            return None
        images = images[:needed]

        # --- Video compose ---
        tpl = build_template(
            audio_path=audio_master_path,
            images=images,
            run_dir=run_dir,
            duration_sec=duration_sec,
        )

        # --- Shorts clipping ---
        chapter_ranges = _chapter_time_ranges(processed, total_sec=duration_sec)
        plans = plan_from_timings(chapter_ranges, max_short_sec=75.0)
        shorts_dir = run_dir / "shorts"
        shorts = cut_shorts(tpl.long_9x16, plans, shorts_dir)

        # --- Package + (optional) publish ---
        packages_dir = run_dir / "packages"
        packages_dir.mkdir(exist_ok=True)

        yt_long_pkg = pkg_mod.build_long_youtube(
            title=processed.selected_title,
            description=f"{processed.hook}\n\n#storytime",
            keywords=processed.keywords,
            video_path=tpl.long_16x9,
            publish_at=None,
        )
        pkg_mod.dump(yt_long_pkg, packages_dir)

        for i, short_mp4 in enumerate(shorts, start=1):
            yt_short = pkg_mod.build_short("youtube_shorts", i, len(shorts),
                                           processed.selected_title,
                                           processed.keywords, short_mp4)
            tt_short = pkg_mod.build_short("tiktok", i, len(shorts),
                                           processed.selected_title,
                                           processed.keywords, short_mp4)
            pkg_mod.dump(yt_short, packages_dir)
            pkg_mod.dump(tt_short, packages_dir)
            if opts.tiktok_package:
                tiktok_pub.export(tt_short, packages_dir / f"tiktok_{i:02d}")

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
            audio_long=str(audio_master_path),
            audio_chapters=[str(p) for p in seg_audio_paths],
            subtitles_ass=str(tpl.subtitles_ass) if tpl.subtitles_ass else None,
            typewriter_png_dir=str(tpl.typewriter_dir),
            slideshow_long_mp4=str(tpl.long_16x9),
            long_video_mp4=str(tpl.long_16x9),
            shorts_mp4=[str(p) for p in shorts],
            tiktok_mp4=[str(p) for p in shorts],
        )
    except Exception as exc:
        log.exception("pipeline error: %s", exc)
        finish_run(run_id, "failed", str(exc))
        log_event(story.id, "failed", {"error": str(exc)})
        return None


def _probe_duration(audio_path: Path) -> float:
    import subprocess

    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        check=True, capture_output=True, text=True,
    )
    return float(r.stdout.strip() or 0)


def _chapter_time_ranges(processed: ProcessedStory, total_sec: float) -> list[tuple[float, float, str]]:
    """Naive mapping: distribute chapters evenly across total duration.

    For precise timing we'd thread per-segment audio durations through. This is
    good enough to produce usable 60–75s shorts.
    """
    n = max(1, len(processed.chapters))
    step = total_sec / n
    out: list[tuple[float, float, str]] = []
    for i, ch in enumerate(processed.chapters):
        out.append((i * step, (i + 1) * step, ch.hook))
    return out
