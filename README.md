# gameee

Pipeline: истории из **Reddit / Twitter(X) / Threads** → **русская озвучка** →
длинное видео (слайдшоу + «пишущая машинка») → нарезка в **YouTube Shorts / TikTok** с
CTA на твой канал.

## Что делает

1. **Scan** — собирает кандидатов из Reddit (asyncpraw), Twitter (twscrape),
   Threads (Playwright). Считает «скорость роста» и потенциал длинной формы.
2. **Filter** — язык (ru/en), NSFW, длина, PII-редакция, дедуп.
3. **Rights** — permission-first шлюз: без согласия автора в продакшн не идёт
   (есть `--research` режим для внутренних прогонов).
4. **Script** — Gemini 2.5 Flash генерирует: перевод EN→RU, цепляющий заголовок, маркеры
   `[HOOK]/[CHAPTER_N]/[CLIFFHANGER_N]/[OUTRO]`, ключевые слова + промпты для картинок.
5. **TTS** — Google **Chirp 3 HD** (русский) как основной для нарратива; для
   сегментов с диалогами автоматически включается **Gemini 2.5 TTS multi-speaker**
   (рассказчик + герой — разные голоса). Silero v5 локально, OpenAI `gpt-4o-mini-tts`
   и Edge TTS — fallback-цепочка. Кеш в `.data/tts_cache`.
6. **Images** — цепочка провайдеров: `pexels → flux_replicate → openai_images →
   chatgpt_playwright → imagefx_playwright → local_flux`. Первый, кто вернул
   результат — выигрывает. Кеш в `.data/img_cache`.
7. **Audio post** — LUFS-мастеринг голоса, SFX-акценты на `[CLIFFHANGER_N]`,
   амбиентная музыка с **sidechain ducking** (голос автоматически «проваливает»
   музыку во время речи).
8. **Video** — ffmpeg-рендер слайдшоу с Ken-Burns + накладка «печатной
   машинки» (PNG sequence с прозрачностью) + watermark канала. Длинное 16:9
   и вертикальное 9:16 с размытым фоном.
9. **Thumbnail** — авто-генерация 1280×720 из самой «драматичной» AI-картинки
   + крупный заголовок с контуром + цветной акцент-бар.
10. **Clipper** — нарезает 9:16 видео по **реальным границам глав** (не
    равномерно), добавляет CTA-баннер и end-card «Полная история на канале @handle».
11. **Scheduler** — раскидывает публикации во времени (длинное YT — раз в
    неделю, Shorts/TikTok — раз в день), а не шлёпает 6 шортсов залпом.
12. **Publish** — YouTube Data API (upload + schedule), Instagram Reels (Graph
    API), TikTok — «пакет под ручную загрузку».
13. **Cost tracker** — каждый платный API-вызов логируется в `.data/costs.jsonl`,
    провайдеры сами отключаются, если месячный cap превышен.
14. **Resilience** — retry + circuit breaker на все сетевые вызовы; хрупкие
    Playwright-провайдеры блокируются на час после 3 подряд фейлов.

## Установка

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # для Threads + UI-провайдеров картинок
cp .env.example .env                  # заполни ключи
```

FFmpeg обязателен:
```bash
# Ubuntu/WSL
sudo apt install -y ffmpeg
# macOS
brew install ffmpeg
```

## Настройка провайдеров

| Для чего | Что нужно |
|---|---|
| Reddit | Создать OAuth-приложение на https://www.reddit.com/prefs/apps и заполнить `REDDIT_*` в `.env` |
| Twitter | Залогиниться через `twscrape add_accounts …` (файл БД в `TWSCRAPE_DB`) |
| Threads | `python -m src.images.setup_auth --provider threads` |
| Google Chirp 3 HD | Service Account JSON в `secrets/gcp-sa.json`, `Text-to-Speech API` включен |
| Gemini (редактор + перевод + заголовки) | `GEMINI_API_KEY` (получить на https://aistudio.google.com/apikey — есть бесплатный тир) |
| OpenAI (TTS/images) | `OPENAI_API_KEY` |
| Replicate (Flux) | `REPLICATE_API_TOKEN` |
| Pexels | `PEXELS_API_KEY` |
| ChatGPT UI (Playwright) | `python -m src.images.setup_auth --provider chatgpt` |
| ImageFX / Google Labs | `python -m src.images.setup_auth --provider imagefx` |
| YouTube upload | OAuth client secrets в `secrets/client_secret.json` |
| Instagram Reels | `META_ACCESS_TOKEN` + `META_IG_USER_ID` |

## Канальный брендинг

Правь `config/channel.yaml`:

```yaml
channel:
  handle: "@твой_канал"
  youtube_url: "https://youtube.com/@твой_канал"
  ...
```

Положи `assets/channel/watermark.png` (прозрачный PNG, ~400×400),
`assets/channel/endcard_template.png` и шрифты в `assets/fonts/`.

## Использование

```bash
# собрать кандидатов (или одну платформу)
python -m src.cli scan --source all --limit 100
python -m src.cli scan --source reddit --limit 50

# топ-кандидатов по скорости роста
python -m src.cli rank --limit 20

# инициировать запрос разрешения у автора
python -m src.cli ask reddit:abc123 --lang ru
# получили ответ — записать согласие
python -m src.cli grant reddit:abc123 --text "Yes, I give permission"

# прогнать конкретную историю end-to-end (без публикации)
python -m src.cli run --story-id reddit:abc123

# с публикацией на YouTube (длинное)
python -m src.cli run --story-id reddit:abc123 --publish

# выбрать автоматически лучшую историю из очереди
python -m src.cli run --profile auto

# исследовательский прогон (без прав), только артефакты
python -m src.cli run --research

# вечный цикл: скан + рендер
python -m src.cli loop --interval-sec 180 --max-renders 3

# бюджет: сколько потратили за этот месяц (по провайдерам)
python -m src.cli costs

# очередь запланированных публикаций
python -m src.cli schedule

# опубликовать то, у чего уже наступил `planned_for`
python -m src.cli dispatch --limit 5
python -m src.cli dispatch --dry-run

# подтянуть YT Analytics по загруженным видео и пересчитать веса тем
python -m src.cli pull-analytics --days 28

# топ-ключевых слов, которые работают на канале
python -m src.cli analytics

# бренд-канал (overlay поверх дефолтов из config/brands/<name>/)
python -m src.cli --brand=horror run
GAMEEE_BRAND=horror python -m src.cli loop
```

## Мульти-канал / бренды

Клади overlay-YAML-ы в `config/brands/<название>/`:

```
config/brands/horror/
├── channel.yaml      # своё handle, цвета, watermark
├── sources.yaml      # свой whitelist сабреддитов
└── audio.yaml        # своя папка с музыкой
```

Каждый overlay deep-merge'ит только те ключи, которые в нём указаны,
остальное берётся из базового `config/*.yaml`. Runs раскладываются в
`runs/<brand>/YYYY-MM-DD/...`, БД общая.

## Многоголосая озвучка для диалогов

Gemini инструктируется расставлять префиксы спикеров (`Рассказчик:`,
`Герой:`/`Героиня:` и т.п.) в script_with_markers. TTS-роутер детектит их
и для таких сегментов автоматически вызывает Gemini 2.5 TTS в
multi-speaker-режиме (2 голоса: нарратор + герой). Сегменты без диалогов
идут по обычной цепочке (Chirp 3 HD → Silero → ...).

Все имена персонажей, кроме `Рассказчик`, схлопываются на одну роль
`Герой` — Gemini TTS поддерживает максимум 2 голоса за запрос.

Вырубить: убрать `dialogue_primary: gemini_tts` из `config/voices.yaml`.

## A/B тест хуков

Для первого Short пайплайн автоматически делает две версии (A и B) с
разными заголовками-открывашками из `title_variants`. Scheduler
разносит их по времени, после сбора статистики через `pull-analytics`
смотрим, какой вариант выиграл (он добавит свои keyword'ы в веса).

## Музыка / SFX

Pipeline автоматически подмешивает амбиентную музыку с side-chain ducking
и воспроизводит SFX (`whoosh`/`boom`) перед `[CLIFFHANGER_N]`. Файлы не
коммитятся в репо — добавь свои:

```
assets/music/ambient_01.mp3     # любой подходящий трек с правильной лицензией
assets/sfx/whoosh.wav
assets/sfx/boom.wav
```

Если папки пустые — мешаем без музыки, это нормально для MVP.

## Cost cap

`config/images.yaml` -> `router.per_month_cap_usd` — жёсткий месячный лимит.
Превышение → платные провайдеры изображений автоматически пропускаются,
pipeline падает на Pexels/локальные альтернативы.

Посмотреть что потрачено: `python -m src.cli costs`.

## Структура

```
src/
  core/       models, storage, scoring, config
  sources/    reddit, twitter (twscrape), threads (playwright)
  filters/    language, nsfw, dedup (simhash), quality, pipeline
  rights/     manager, templates, ledger (append-only JSONL)
  script/     llm (Claude), segmenter, normalizer
  tts/        google_chirp, silero_local, openai_tts, edge_tts, router, cache
  audio/      postprocess (LUFS + HPF + compressor via ffmpeg)
  images/     pexels, flux_replicate, openai_images, chatgpt_playwright,
              imagefx_playwright, local_flux, router, cache, setup_auth
  video/      subtitles, typewriter, slideshow, renderer, clipper,
              templates/slideshow_typewriter.py
  publish/    package, youtube, instagram, tiktok
  analytics/  collector
  cli.py      typer CLI
  pipeline.py оркестратор
config/       sources, filters, voices, images, channel (YAML)
assets/       fonts, bg (cache), channel (watermark/endcard), sfx
runs/         артефакты на каждую историю (в .gitignore)
```

## Тесты

```bash
pytest -q
```

Тесты покрывают скоринг, фильтры, парсинг маркеров сценария и plan clipper.
Компоненты с внешними вызовами (Reddit/LLM/TTS/ffmpeg/YouTube) — мокаются или
пропускаются, когда ключи не заданы.

## Важные замечания

- **Permission-first**: без `grant` или `--research` пайплайн ничего не рендерит.
  Это снижает риск copyright-жалоб и reused-content демонетизации на YouTube.
- **TikTok** — только «пакет под ручную загрузку». Direct Post API требует
  аудита и не предназначен для репабликации чужого контента.
- **Playwright-провайдеры** (ChatGPT/ImageFX) — серая зона ToS. Используй
  только если готова починить DOM-селекторы и жить с возможным баном аккаунта.
  В цепочке они стоят после более надёжных путей.

## Лицензия

MIT
