"""LLM-driven script preparation.

One Claude call produces everything downstream needs:
  - Russian translation (if source is EN)
  - 3 catchy title variants
  - hook (1-3s opener)
  - cleaned script with [HOOK]/[CHAPTER_N]/[CLIFFHANGER_N]/[OUTRO] markers
  - keywords for image search
  - image prompts for AI-generated slides
  - emotional tone
  - estimated minutes
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.core import config
from src.core.models import Chapter, LengthProfile, ProcessedStory, Story
from src.script.normalizer import normalize

log = logging.getLogger(__name__)


SYSTEM = """Ты — редактор русскоязычного сторителлинг-канала. Работаешь с историями из
Reddit/Twitter/Threads. Задача — подготовить сценарий для озвучки.

Требования:
1. Если текст на английском — переведи на русский, сохраняя интонацию и эмоции.
2. Очисти от мусора: эмодзи, ссылки, спам, перс. данные (имена, телефоны, адреса — заменяй на «[имя]», «[город]» и т.п.).
3. Расставь маркеры:
   [HOOK] — 1–3 секунды в начале, цепляющая фраза (вопрос или шок-факт).
   [CHAPTER_N] ... [CLIFFHANGER_N] — логические части истории. Минимум 3 пары.
   [OUTRO] — короткое завершение + CTA «Подпишись, чтобы не пропустить».
4. Сформулируй 3 варианта заголовка до 60 знаков, в стиле «цепляющий русский YouTube».
5. Верни строгий JSON по схеме (никаких комментариев за пределами JSON).
"""


USER_TMPL = """Source language: {lang}
Source platform: {source}
Title: {title}

Text:
<<<
{text}
>>>

Target profile: {profile} (short=5-10 min, long=15-25 min)

Верни JSON по схеме:
{{
  "translated": <bool>,
  "title_variants": ["...", "...", "..."],
  "selected_title": "...",
  "hook": "...",
  "script_with_markers": "[HOOK] ... [CHAPTER_1] ... [CLIFFHANGER_1] ... [OUTRO] ...",
  "keywords": ["..."],
  "image_prompts": ["...", "..."],
  "tone": "neutral|suspense|funny|shocking|heartwarming",
  "estimated_minutes": 0.0
}}"""


def _parse_chapters(script: str) -> list[Chapter]:
    """Extract (hook, body, cliffhanger) triples from marker-annotated script."""
    chapters: list[Chapter] = []
    # pattern: [CHAPTER_N] ... [CLIFFHANGER_N] (optional; absorbs everything until next [CHAPTER_] or [OUTRO])
    pat = re.compile(
        r"\[CHAPTER_(\d+)\](?P<body>.*?)(?:\[CLIFFHANGER_\1\](?P<cliff>.*?))?(?=\[CHAPTER_\d+\]|\[OUTRO\]|\Z)",
        re.DOTALL,
    )
    for m in pat.finditer(script):
        idx = int(m.group(1))
        body = (m.group("body") or "").strip()
        cliff = (m.group("cliff") or "").strip()
        # first sentence is hook
        hook = re.split(r"(?<=[.!?])\s+", body, maxsplit=1)[0] if body else ""
        chapters.append(Chapter(index=idx, hook=hook, body=body, cliffhanger=cliff))
    return chapters


def _fallback_process(story: Story, profile: LengthProfile) -> ProcessedStory:
    """If no LLM available, produce a minimal ProcessedStory using rules.

    Not great, but lets the rest of the pipeline run for testing without API keys.
    """
    cleaned = normalize(story.text or story.title)
    # Naively split into 3 chapters
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    third = max(1, len(parts) // 3)
    ch1 = " ".join(parts[:third])
    ch2 = " ".join(parts[third : 2 * third])
    ch3 = " ".join(parts[2 * third :])

    title = story.title[:60] or "Невероятная история"
    hook = parts[0] if parts else title
    script = (
        f"[HOOK] {hook}\n"
        f"[CHAPTER_1] {ch1}\n[CLIFFHANGER_1] ...\n"
        f"[CHAPTER_2] {ch2}\n[CLIFFHANGER_2] ...\n"
        f"[CHAPTER_3] {ch3}\n"
        f"[OUTRO] Подпишись, чтобы не пропустить следующую историю."
    )
    return ProcessedStory(
        story_id=story.id,
        title_variants=[title, title + " (продолжение внутри)", "Такое случается нечасто"],
        selected_title=title,
        hook=hook,
        cleaned_text=cleaned,
        script_with_markers=script,
        chapters=_parse_chapters(script),
        keywords=[story.title.split()[0] if story.title else "story"],
        image_prompts=[
            "cinematic moody room at night, warm light, film grain",
            "silhouette of a person by a window, dramatic mood",
            "old diary on a wooden table, candle light",
        ],
        tone="neutral",
        estimated_minutes=max(3.0, len(cleaned) / 900),
        profile=profile,
    )


def process(story: Story, profile: LengthProfile = LengthProfile.SHORT) -> ProcessedStory:
    key = config.env("ANTHROPIC_API_KEY")
    if not key:
        log.warning("ANTHROPIC_API_KEY missing — using rule-based fallback")
        return _fallback_process(story, profile)

    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return _fallback_process(story, profile)

    client = anthropic.Anthropic(api_key=key)
    prompt = USER_TMPL.format(
        lang=story.lang_detected.value,
        source=story.source.value,
        title=story.title,
        text=story.text or story.title,
        profile=profile.value,
    )
    resp = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4096,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    )
    data = _extract_json(raw)

    script = normalize(data["script_with_markers"])
    return ProcessedStory(
        story_id=story.id,
        title_variants=data["title_variants"],
        selected_title=data.get("selected_title") or data["title_variants"][0],
        hook=data["hook"],
        cleaned_text=normalize(data.get("cleaned_text") or script),
        script_with_markers=script,
        chapters=_parse_chapters(script),
        keywords=data.get("keywords", []),
        image_prompts=data.get("image_prompts", []),
        tone=data.get("tone", "neutral"),
        estimated_minutes=float(data.get("estimated_minutes", 0) or 0),
        profile=profile,
    )


def _extract_json(raw: str) -> dict[str, Any]:
    """Tolerate markdown code fences / leading/trailing text around JSON."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError("LLM returned no JSON: " + raw[:200])
    return json.loads(m.group(0))
