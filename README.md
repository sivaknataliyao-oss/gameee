# News Video Pipeline

Автоматический пайплайн: **политическая новость → сценарий → видео → YouTube**.

Каждый день находит топовую политическую новость, генерирует сценарий (5-7 мин),
озвучивает, рендерит видео с картинками и публикует на YouTube.

## Стек

| Стадия | Инструмент |
|--------|-----------|
| Новости | RSS (BBC, Reuters, Al Jazeera, Guardian, NPR) |
| Сценарий | Playwright + ChatGPT (через браузер) |
| Озвучка | Google Cloud TTS (WaveNet) |
| Изображения | Pexels API (бесплатные стоки) |
| Видео | FFmpeg (слайдшоу + текстовые оверлеи) |
| Обложка | Pillow (авто-генерация) |
| Публикация | YouTube Data API v3 (OAuth) |

## Установка

```bash
pip install -r requirements.txt

# FFmpeg (нужен для рендера)
# Ubuntu/WSL:
sudo apt install ffmpeg
# Mac:
brew install ffmpeg
```

## Настройка

1. **Pexels** — получи бесплатный API ключ: https://www.pexels.com/api/
   ```bash
   export PEXELS_API_KEY="твой_ключ"
   ```

2. **YouTube** — создай OAuth credentials в Google Cloud Console:
   - Создай проект → Включи YouTube Data API v3 → OAuth 2.0 (Desktop app)
   - Скачай `client_secret.json` в корень проекта

3. **Google Cloud TTS** — настрой credentials:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="path/to/service-account.json"
   ```

4. **Playwright + ChatGPT** — подключи свой скрипт в `src/scriptwriter.py`

## Запуск

```bash
# Полный пайплайн
python -m src.pipeline

# Тестовый прогон (без публикации на YouTube)
python -m src.pipeline --dry-run

# Только конкретный шаг
python -m src.pipeline --step fetch     # только сбор новостей
python -m src.pipeline --step script    # до генерации сценария
python -m src.pipeline --step render    # до рендера видео

# С кастомным конфигом
python -m src.pipeline --config config/sources.yaml
```

## Структура проекта

```
├── config/
│   └── sources.yaml        # Источники, фильтры, настройки
├── src/
│   ├── pipeline.py          # Главный оркестратор (7 шагов)
│   ├── fetcher.py           # Сбор RSS-новостей
│   ├── parser.py            # Очистка HTML
│   ├── filters.py           # Фильтрация по ключевым словам
│   ├── scriptwriter.py      # Генерация сценария (Playwright+ChatGPT)
│   ├── tts.py               # Озвучка (Google Cloud TTS / edge-tts)
│   ├── assets.py            # Сбор изображений (Pexels)
│   ├── renderer.py          # Рендер видео (FFmpeg)
│   ├── thumbnail.py         # Генерация обложки (Pillow)
│   ├── uploader.py          # Загрузка на YouTube
│   └── storage.py           # Сохранение данных
├── runs/                    # Артефакты каждого прогона (auto)
│   └── 2026-04-14/
│       └── run_070000Z/
│           ├── story.json
│           ├── script.json
│           ├── narration.mp3
│           ├── thumbnail.jpg
│           ├── video.mp4
│           └── upload.json
├── requirements.txt
└── README.md
```

## Автозапуск (ежедневно)

**Linux/WSL (cron):**
```bash
crontab -e
# Добавить:
0 7 * * * cd /path/to/project && python -m src.pipeline >> logs/pipeline.log 2>&1
```

**OpenClaw:**
```bash
openclaw cron add \
  --name "Daily News Video" \
  --cron "0 7 * * *" \
  --session isolated \
  --message "Run the news-video-pipeline skill" \
  --tools exec,read
```

## Лицензия

MIT
