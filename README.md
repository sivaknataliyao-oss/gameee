# News Pipeline

Пайплайн для сбора, обработки и хранения новостей из различных источников.

## Возможности

- Сбор новостей из RSS-лент
- Парсинг и очистка контента
- Фильтрация по ключевым словам
- Сохранение в JSON / SQLite
- Запуск по расписанию

## Установка

```bash
pip install -r requirements.txt
```

## Использование

```bash
# Запуск пайплайна
python -m src.pipeline

# Запуск с конкретным конфигом
python -m src.pipeline --config config/sources.yaml
```

## Структура проекта

```
├── config/
│   └── sources.yaml        # Источники новостей (RSS-ленты)
├── src/
│   ├── __init__.py
│   ├── pipeline.py          # Главный модуль пайплайна
│   ├── fetcher.py           # Сбор данных из RSS
│   ├── parser.py            # Парсинг и очистка контента
│   ├── storage.py           # Сохранение результатов
│   └── filters.py           # Фильтрация новостей
├── tests/
│   └── test_pipeline.py
├── requirements.txt
└── README.md
```

## Лицензия

MIT
