"""Генерация сценария через Playwright + ChatGPT.

Этот модуль — интерфейс для подключения твоего Playwright-скрипта.
Замени функцию `generate_script_playwright()` на свою реализацию.
"""

import json
import os
from pathlib import Path


# === PROMPT-ШАБЛОН ДЛЯ CHATGPT ===
SCRIPT_PROMPT = """You are a professional news scriptwriter for a YouTube channel.
Write a 5-7 minute video script about the following political news story.

NEWS:
Title: {title}
Summary: {summary}
Source: {source}

REQUIREMENTS:
- Language: English
- Duration: 5-7 minutes (~1000-1500 words when spoken)
- Structure: Hook (15 sec) → Context (1 min) → Main Story (3-4 min) → Analysis (1 min) → Conclusion (30 sec)
- Tone: Professional, engaging, neutral journalism
- Include timestamps for each section
- Mark where images/b-roll should appear with [VISUAL: description]
- End with a call to action (subscribe, comment)

OUTPUT FORMAT (JSON):
{{
  "title": "YouTube video title (clickbait but not misleading, under 70 chars)",
  "description": "YouTube description (2-3 paragraphs, include source links)",
  "tags": ["tag1", "tag2", ...],
  "hook": "First 2 sentences to grab attention",
  "sections": [
    {{
      "timestamp": "0:00",
      "heading": "Section name",
      "text": "Narration text for this section",
      "visuals": ["description of visual 1", "description of visual 2"]
    }}
  ]
}}
"""


def build_prompt(story: dict) -> str:
    """Строит prompt для ChatGPT из выбранной новости."""
    return SCRIPT_PROMPT.format(
        title=story.get("title", ""),
        summary=story.get("summary", ""),
        source=story.get("source", ""),
    )


def generate_script_playwright(story: dict) -> dict:
    """Генерирует сценарий через Playwright + ChatGPT.

    *** ПОДКЛЮЧИ СЮДА СВОЙ PLAYWRIGHT ***

    Эта функция должна:
    1. Открыть ChatGPT через Playwright (с сохранённой сессией)
    2. Отправить prompt
    3. Дождаться ответа
    4. Распарсить JSON из ответа
    5. Вернуть dict со сценарием

    Пока что возвращает заглушку для тестирования остального пайплайна.
    """
    prompt = build_prompt(story)

    # ============================================================
    # TODO: Замени этот блок на свой Playwright код
    # Пример:
    #   from your_playwright_module import send_to_chatgpt
    #   response = send_to_chatgpt(prompt)
    #   return json.loads(response)
    # ============================================================

    print(f"[SCRIPTWRITER] Prompt готов ({len(prompt)} символов)")
    print("[SCRIPTWRITER] ⚠ Используется ЗАГЛУШКА — подключи свой Playwright!")

    # Заглушка для тестирования пайплайна
    return {
        "title": f"Breaking: {story.get('title', 'Political News Update')}",
        "description": f"Today we cover: {story.get('summary', '')}",
        "tags": ["politics", "news", "breaking", "2026"],
        "hook": "What just happened will change everything. Here's what you need to know.",
        "sections": [
            {
                "timestamp": "0:00",
                "heading": "Introduction",
                "text": story.get("summary", "placeholder narration text"),
                "visuals": ["news headline graphic", "world map"],
            },
            {
                "timestamp": "1:00",
                "heading": "The Full Story",
                "text": "This is placeholder text. Connect your Playwright script to generate real content.",
                "visuals": ["relevant political image", "parliament building"],
            },
        ],
    }


def save_script(script: dict, run_dir: str) -> str:
    """Сохраняет сценарий в run-директорию."""
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, "script.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    print(f"[SCRIPTWRITER] Сценарий сохранён: {path}")
    return path
