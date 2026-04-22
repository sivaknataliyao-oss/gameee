"""LLM-driven script preparation via Gemini.

One call to Gemini 2.5 Flash produces everything downstream needs:
  - Russian translation (if source is EN)
  - 3 catchy title variants
  - hook (1–3s opener)
  - cleaned script with [HOOK]/[CHAPTER_N]/[CLIFFHANGER_N]/[OUTRO] markers
  - keywords for image search
  - image prompts for AI-generated slides
  - emotional tone
  - estimated minutes

Gemini's `response_mime_type="application/json"` gives us strict JSON with no
markdown fencing to strip — simpler and more reliable than regex extraction.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.core import config, costs
from src.core.models import Chapter, LengthProfile, ProcessedStory, Scene, Story
from src.core.resilience import CircuitBreaker, retry
from src.script.normalizer import normalize

log = logging.getLogger(__name__)

_breaker = CircuitBreaker("gemini", threshold=5, cooldown_sec=600)
# Gemini 2.5 Flash approx: $0.30/1M input + $2.50/1M output tokens.
# We track only an estimate — real billing comes from Google Console.
_IN_PER_1M = 0.30
_OUT_PER_1M = 2.50


SYSTEM = """Ты — редактор русскоязычного сторителлинг-канала. Работаешь с историями из
Reddit/Twitter/Threads. Задача — подготовить сценарий для озвучки.

Требования:
1. Если текст на английском — переведи на русский, сохраняя интонацию и эмоции.
   Не калькируй буквально: используй живой разговорный русский.
2. Очисти от мусора: эмодзи, ссылки, спам, перс. данные (имена → «[имя]»,
   адреса → «[город]», телефоны → «[номер]» и т.п.).
3. Расставь маркеры:
   [HOOK] — 1–3 секунды в начале, цепляющая фраза (вопрос или шок-факт).
   [CHAPTER_N] ... [CLIFFHANGER_N] — логические части. Минимум 3 пары.
   [OUTRO] — короткое завершение + CTA «Подпишись, чтобы не пропустить».
4. 3 варианта заголовка до 60 знаков в стиле «цепляющий русский YouTube»:
   «Он сделал X — и тут началось…», «Вы не поверите, что было дальше», и т.п.
5. `scenes` — список визуально связных сцен (одна сцена на главу + сцена для
   HOOK). В каждой сцене 3-4 промпта на английском: один и тот же сюжетный
   объект/локация под разными углами/светом. Атмосферные, без людей в фокусе,
   в кино-стиле (moody, film grain, 35mm, warm tones).
   `label` — короткий идентификатор сцены (kebab-case).
   `chapter_index` — номер главы (0 для HOOK/OUTRO).
6. `image_prompts` — плоский список всех промптов из scenes, для обратной совместимости.
"""


SCHEMA = {
    "type": "object",
    "properties": {
        "translated": {"type": "boolean"},
        "title_variants": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
        "selected_title": {"type": "string"},
        "hook": {"type": "string"},
        "cleaned_text": {"type": "string"},
        "script_with_markers": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "chapter_index": {"type": "integer"},
                    "prompts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 5,
                    },
                },
                "required": ["label", "prompts"],
            },
        },
        "image_prompts": {"type": "array", "items": {"type": "string"}},
        "tone": {
            "type": "string",
            "enum": ["neutral", "suspense", "funny", "shocking", "heartwarming"],
        },
        "estimated_minutes": {"type": "number"},
    },
    "required": [
        "title_variants", "selected_title", "hook",
        "script_with_markers", "keywords", "scenes", "image_prompts",
    ],
}


USER_TMPL = """Source language: {lang}
Source platform: {source}
Title: {title}

Text:
<<<
{text}
>>>

Target profile: {profile} (short = 5–10 min, long = 15–25 min)

Верни JSON по указанной схеме."""


def _parse_chapters(script: str) -> list[Chapter]:
    """Extract (hook, body, cliffhanger) triples from marker-annotated script."""
    chapters: list[Chapter] = []
    pat = re.compile(
        r"\[CHAPTER_(\d+)\](?P<body>.*?)(?:\[CLIFFHANGER_\1\](?P<cliff>.*?))?"
        r"(?=\[CHAPTER_\d+\]|\[OUTRO\]|\Z)",
        re.DOTALL,
    )
    for m in pat.finditer(script):
        idx = int(m.group(1))
        body = (m.group("body") or "").strip()
        cliff = (m.group("cliff") or "").strip()
        hook = re.split(r"(?<=[.!?])\s+", body, maxsplit=1)[0] if body else ""
        chapters.append(Chapter(index=idx, hook=hook, body=body, cliffhanger=cliff))
    return chapters


def _fallback_process(story: Story, profile: LengthProfile) -> ProcessedStory:
    """Rule-based path when no API key is available; keeps pipeline runnable."""
    cleaned = normalize(story.text or story.title)
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
        title_variants=[title, title + " (что было дальше)", "Такое случается нечасто"],
        selected_title=title,
        hook=hook,
        cleaned_text=cleaned,
        script_with_markers=script,
        chapters=_parse_chapters(script),
        keywords=[story.title.split()[0] if story.title else "story"],
        scenes=[
            Scene(label="moody-interior", chapter_index=1, prompts=[
                "cinematic moody room at night, warm light, film grain",
                "moody interior, curtains, silhouette of a person by a window",
                "dim room, desk lamp, papers scattered, 35mm",
            ]),
            Scene(label="diary-on-desk", chapter_index=2, prompts=[
                "old diary on a wooden table, candle light, cinematic",
                "close-up of handwritten journal pages, sepia, candlelight",
                "vintage pen on an open notebook, warm dramatic light",
            ]),
        ],
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
    key = config.env("GEMINI_API_KEY")
    if not key:
        log.warning("GEMINI_API_KEY missing — using rule-based fallback")
        return _fallback_process(story, profile)

    try:
        from google import genai
        from google.genai import types
    except ImportError:  # pragma: no cover
        log.warning("google-genai not installed — using rule-based fallback")
        return _fallback_process(story, profile)

    client = genai.Client(api_key=key)
    user = USER_TMPL.format(
        lang=story.lang_detected.value,
        source=story.source.value,
        title=story.title,
        text=story.text or story.title,
        profile=profile.value,
    )

    @_breaker
    @retry(attempts=3, initial=2.0, factor=2.0)
    def _gen():
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=SCHEMA,
                temperature=0.8,
                max_output_tokens=8192,
            ),
        )

    try:
        resp = _gen()
        raw = resp.text or ""
        data: dict[str, Any] = json.loads(raw)
    except Exception as exc:
        log.warning("gemini call failed (%s) — falling back to rules", exc)
        return _fallback_process(story, profile)

    # Track approximate cost from usage_metadata when available.
    try:
        usage = getattr(resp, "usage_metadata", None)
        if usage:
            costs.track("gemini", "in_tokens",
                        float(usage.prompt_token_count or 0), _IN_PER_1M / 1_000_000,
                        {"model": "gemini-2.5-flash"})
            costs.track("gemini", "out_tokens",
                        float(usage.candidates_token_count or 0), _OUT_PER_1M / 1_000_000,
                        {"model": "gemini-2.5-flash"})
    except Exception:
        pass

    script = normalize(data["script_with_markers"])
    scenes = [
        Scene(
            label=s.get("label", f"scene_{i}"),
            chapter_index=int(s.get("chapter_index", 0) or 0),
            prompts=list(s.get("prompts", [])),
        )
        for i, s in enumerate(data.get("scenes", []) or [])
    ]
    flat_prompts = data.get("image_prompts") or [p for s in scenes for p in s.prompts]
    return ProcessedStory(
        story_id=story.id,
        title_variants=data["title_variants"],
        selected_title=data.get("selected_title") or data["title_variants"][0],
        hook=data["hook"],
        cleaned_text=normalize(data.get("cleaned_text") or script),
        script_with_markers=script,
        chapters=_parse_chapters(script),
        keywords=data.get("keywords", []),
        scenes=scenes,
        image_prompts=flat_prompts,
        tone=data.get("tone", "neutral"),
        estimated_minutes=float(data.get("estimated_minutes", 0) or 0),
        profile=profile,
    )
