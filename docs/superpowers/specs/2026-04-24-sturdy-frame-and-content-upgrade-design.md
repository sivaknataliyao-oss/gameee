# Design: Прочный каркас + Контент-ап

**Status:** draft
**Date:** 2026-04-24
**Branch:** `claude/design-framework-structure-ZCQBr`
**Scope:** реструктуризация `src/pipeline.py` в stage-based runner + 5 контентных улучшений (LLM self-critique, thumbnail A/B, per-platform metadata, pattern-interrupt, active-speaker coloring).

---

## 0. Общие принципы

- **Один источник правды — `Context`.** Все stage читают/пишут в него, ничего не возвращают «кроме того». Всё остальное в функциях — мелкие хелперы.
- **Stage = module + `run(ctx) → ctx`.** Идемпотентность через контент-адресуемый кеш артефактов. Каждый stage тестируем отдельно.
- **Fail loud inside stages, fail graceful между ними.** `except Exception` выживает только на границе stage-runner'а, куда всё структурно логируется.

---

## 1. Architecture foundation

### 1.1 `src/core/context.py`

Pydantic-модель `Context` — вся артефактная информация по одной истории:

```python
class Context(BaseModel):
    run_id: int
    story_id: str
    brand: str = "default"
    run_dir: Path
    story: Story
    opts: RunOptions

    # Progressively filled by stages:
    processed: ProcessedStory | None = None
    critique: CritiqueResult | None = None           # from self-critique stage
    segments_audio: list[SegmentAudio] | None = None
    chapter_ranges: list[ChapterRange] | None = None
    narration_final: Path | None = None
    images: list[Path] | None = None
    long_video: Path | None = None
    intro_offset_sec: float = 0.0
    thumbnail_variants: list[Path] = []               # [0] = default, [1..n] = A/B
    shorts: list[Path] = []
    ab_short_variants: list[tuple[str, Path]] = []
    platform_metadata: PlatformMetadata | None = None # per-platform titles/captions
    packages: list[Path] = []
```

`SegmentAudio`, `ChapterRange`, `CritiqueResult`, `PlatformMetadata` — маленькие pydantic-модели рядом.

### 1.2 `src/pipeline/stages/base.py`

```python
class Stage(Protocol):
    name: str                # "script_llm", "tts_segments", ...
    def run(self, ctx: Context) -> Context: ...
    def is_cached(self, ctx: Context) -> bool: ...
    def clear(self, ctx: Context) -> None: ...
```

`is_cached` проверяет существует ли ожидаемый артефакт в `run_dir` и совпадает ли хеш входа. Если да — stage возвращает `ctx` без работы.

### 1.3 `src/pipeline/runner.py`

```python
STAGES: list[Stage] = [
    FilterRightsStage(),
    ScriptLLMStage(),
    ScriptCritiqueStage(),   # NEW — опционально
    TTSSegmentsStage(),
    AudioFinalizeStage(),
    ImagesFetchStage(),
    VideoComposeStage(),
    ThumbnailStage(),        # теперь 3 варианта
    ShortsClippingStage(),   # включает loop-hook + A/B
    PublishScheduleStage(),
]

def run(ctx, *, from_stage=None, to_stage=None, force: set[str] = frozenset()) -> Context:
    for stage in _slice(STAGES, from_stage, to_stage):
        log = bind_log(story_id=ctx.story_id, stage=stage.name, brand=ctx.brand)
        if stage.name in force:
            stage.clear(ctx)
        if stage.is_cached(ctx):
            log.info("cache_hit")
            continue
        t0 = time.monotonic()
        try:
            ctx = stage.run(ctx)
            log.info("stage_ok", duration_ms=int((time.monotonic()-t0)*1000))
        except Exception as exc:
            log.error("stage_failed", error=repr(exc), duration_ms=int((time.monotonic()-t0)*1000))
            finish_run(ctx.run_id, "failed", f"{stage.name}: {exc}")
            raise
    finish_run(ctx.run_id, "ok")
    return ctx
```

CLI: `cli run --from script_critique` перезапускает со stage'а; `--force tts_segments` чистит его кеш.

### 1.4 Вынос из старого `pipeline.py`

Файл `src/pipeline.py` исчезает. 388 строк становятся 9 файлов по 30–80 строк в `src/pipeline/stages/` + тонкий `runner.py` + `cli.py::run` вызывает `runner.run(...)`.

Старый `process_one()` остаётся как тонкий wrapper с deprecation warning на 1 релиз, чтобы ничего не ломало снаружи.

---

## 2. Structured logging

### 2.1 `src/core/logging.py`

```python
def setup(level="INFO"):
    root = logging.getLogger()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root.handlers = [h]
    root.setLevel(level)

def bind_log(**kv) -> logging.LoggerAdapter:
    """logger that injects {story_id, stage, brand, provider, ...} into every record."""
```

### 2.2 Формат

```json
{"ts":"2026-04-24T09:15:01.234Z","level":"INFO","story_id":"reddit:abc",
 "stage":"script_llm","brand":"default","provider":"gemini-2.5-flash",
 "msg":"stage_ok","duration_ms":2340,"tokens_in":1200,"tokens_out":2400}
```

### 2.3 Где подключаем

- `setup()` в `cli.py::_setup_logging`.
- `bind_log` используют stage-runner и критические места (TTS router, image router, публикация). Остальной код — обычный `logging.getLogger(__name__)`, поля добавляются автоматически через `LoggerAdapter.extra`.

---

## 3. Config validation

### 3.1 `src/core/configs.py` (новое, заменит `src/core/config.py` постепенно)

```python
class SourcesConfig(BaseModel):
    reddit: RedditSourceConfig
    twitter: TwitterSourceConfig
    threads: ThreadsSourceConfig

class VoicesRouter(BaseModel):
    primary: str
    fallback_chain: list[str]
    dialogue_primary: str | None = None

class VoicesConfig(BaseModel):
    router: VoicesRouter
    voices: dict[str, dict]    # still flexible per-provider
    cache: CacheConfig

class AppConfig(BaseModel):
    sources: SourcesConfig
    filters: FiltersConfig
    voices: VoicesConfig
    images: ImagesConfig
    channel: ChannelConfig
    audio: AudioConfig

    @classmethod
    def load(cls, brand: str = "default") -> "AppConfig":
        base = {k: _read(f"{k}.yaml") for k in ("sources","filters","voices","images","channel","audio")}
        overlay = {k: _read_overlay(brand, f"{k}.yaml") for k in base}
        merged = {k: _deep_merge(base[k], overlay[k]) for k in base}
        try:
            return cls(**merged)
        except ValidationError as e:
            raise ConfigError(_pretty(e)) from e
```

### 3.2 Когда валидация

- При старте любой CLI-команды: `AppConfig.load(brand)` → если опечатка → жирное сообщение с путём до ключа.
- Старые `config.sources()` / `.filters()` / `.voices()` остаются как dict-доступ (делегируют в `AppConfig.model_dump()`), чтобы не переписывать все 50+ мест разом.

### 3.3 Pre-commit guard

`tests/test_configs_validate.py` загружает `default` + все `config/brands/*/` и падает на любой опечатке — CI ловит до merge.

---

## 4. Scheduler lock

### 4.1 Проблема

Файл: `src/publish/scheduler.py`. Две `enqueue()` гонки: оба читают `last_planned` = T, обе пишут slot = T+Δ → collision.

### 4.2 Решение

SQLite не умеет `SELECT FOR UPDATE`, но умеет `BEGIN IMMEDIATE`:

```python
def enqueue(...) -> ScheduledPostRow:
    with session() as s:
        s.connection().execute(text("BEGIN IMMEDIATE"))
        slot = _next_slot(platform, cadence, s)   # read within tx
        row = ScheduledPostRow(..., planned_for=slot)
        s.add(row)
        # commit on context exit
    return row
```

`_next_slot` принимает session — одна транзакция на чтение+запись. Второй enqueue будет ждать на lock'е → увидит первый row и посчитает корректный следующий слот.

### 4.3 Заодно

`_next_slot` перепишется, чтобы не шифроваться: если `base + delta < now`, возвращаем `max(now, base + delta).replace(hour=preferred_hour)`, а не текущую «шагай на +1 день» хак-логику.

---

## 5. Health dashboard

### 5.1 `src/core/health.py`

```python
def last_hours(hours: int = 24) -> HealthSnapshot:
    ...
```

`HealthSnapshot` собирается из:

- `RunRow` (SQLite): счётчик run'ов по статусу, ошибки
- `ScheduledPostRow`: pending по платформам, просроченные
- `costs.jsonl`: spend/провайдер за окно
- `events.jsonl`: fallback counts, tts/image provider hit rates
- `VideoMetricsRow`: последние retention/CTR (опционально)

### 5.2 CLI

```
python -m src.cli health
python -m src.cli health --hours 72 --json
```

Rich-table формат: stories scored, rendered, success %, top-3 ошибок, spend по провайдерам, fallback counts, pending schedule, overdue. `--json` даёт машиночитаемый dump (для cron-алертов).

---

## 6. Dedup batch + index

### 6.1 Индекс

`StoryRow.simhash` → `Field(index=True)` в `src/core/storage.py`. Migration: `CREATE INDEX IF NOT EXISTS ix_storyrow_simhash ON storyrow(simhash)` в `storage.engine()` после `create_all`.

### 6.2 Batch lookup

```python
# src/core/storage.py
def has_near_duplicate(
    our_hash: int, *, threshold: int = 4, since_days: int = 60, batch: int = 500
) -> str | None:
    """Return id of similar story, or None. Short-circuits on first match."""
    cutoff = now - timedelta(days=since_days)
    offset = 0
    while True:
        with session() as s:
            rows = list(s.exec(
                select(StoryRow.id, StoryRow.simhash)
                .where(StoryRow.simhash.is_not(None), StoryRow.fetched_at >= cutoff)
                .order_by(StoryRow.fetched_at.desc())
                .offset(offset).limit(batch)
            ))
        if not rows:
            return None
        for sid, h in rows:
            if hamming(our_hash, int(h)) <= threshold:
                return sid
        offset += batch
```

`filters/pipeline.accept()` вызывает `has_near_duplicate(our_hash)` вместо list-iterate по полной истории. Для зрелого install'а: O(N) становится практически O(K) где K — первый совпадающий batch.

---

## 7. LLM self-critique stage

### 7.1 Модуль `src/pipeline/stages/script_critique.py`

Между `ScriptLLMStage` и `TTSSegmentsStage`. Вход: `ctx.processed`. Выход: `ctx.processed` с заменённым `script_with_markers` + `ctx.critique: CritiqueResult`.

### 7.2 Gemini call

```
SYSTEM: Ты — редактор, ищущий слабые места сценария: plot holes, filler, слабые beats, overexplaining, неправдоподобный диалог.
USER:  <draft script with markers>
SCHEMA: {
  "issues": [{"kind": "...", "location": "[CHAPTER_N]", "note": "..."}],
  "revised_script_with_markers": "...",
  "revised_title_variants": ["..."]    // optional; used only if significantly better
}
```

Config: `filters.yaml::critique.enabled: true`, `critique.model: gemini-2.5-flash`.

Cost: +1 call (~1500 tokens in, ~3000 out) ≈ $0.008/история. За месяц при 30 видео — $0.25.

### 7.3 Safety

- Если critique возвращает `issues=[]` — ничего не меняем.
- Если `revised_script` короче оригинала на >40% — пропускаем (возможно галлюцинация усечения).
- В `processed.json` сохраняются обе версии: `script_with_markers` (финальная) + `script_draft` (исходная). Для дебага.

---

## 8. Thumbnail A/B

### 8.1 `src/video/thumbnail.py` расширяется

`render_variants(images, titles, out_dir) → list[Path]`:

- **Variant A:** bottom-title, accent bar слева (текущий стиль)
- **Variant B:** split layout — левая треть avatar+handle, правые 2/3 — заголовок огромный
- **Variant C:** минималистичный центрированный, текст на затемнённой плашке

Используются разные изображения (`ordered[0]`, `ordered[1]`, `ordered[2]`) + разные заголовки из `title_variants`.

### 8.2 Stage

`ThumbnailStage` генерирует все 3, кладёт в `ctx.thumbnail_variants`. `thumbnail_variants[0]` — основной (для YT upload).

### 8.3 Публикация

`publish/youtube.py::upload()` ставит `thumbnail_variants[0]` при создании.

Новая CLI-команда `cli swap-thumbnail <video_id> B` — вызывает `yt.thumbnails.set(videoId, file=variants[B])` через Data API. Ручной A/B в рамках одного канала. YouTube Studio имеет нативный A/B, но его API не публичный — это осознанный компромисс.

---

## 9. Per-platform metadata

### 9.1 Расширение LLM-вызова

В `script_llm.process()` SCHEMA добавляется:

```json
"platform_metadata": {
  "youtube_long":  {"title":"...", "description":"...", "hashtags":["..."]},
  "youtube_shorts":{"title":"...", "description":"...", "hashtags":["..."]},
  "tiktok":        {"caption":"hook + emoji", "hashtags":["..."]},
  "instagram":     {"caption":"...", "hashtags":["..."]}
}
```

SYSTEM-промпт учит: TikTok — 1–2 предложения + эмодзи + вопрос в конце; YT long — первые 100 знаков ключевые; YT Shorts — 50–80 знаков + hashtag CTA; IG — 3–4 строки + 5–10 хэштегов.

### 9.2 Применение

`publish/package.py::build_short()` и `build_long_youtube()` принимают `platform_metadata` и достают из него title/description/hashtags для соответствующей платформы. Никакой общий шаблон больше не используется.

---

## 10. Pattern-interrupt optimizer

### 10.1 MVP-подход (80% пользы за 10% кода)

Вместо полного анализа пикселей — **жёсткий cap на длительность слайда**.

`src/video/slideshow.py::build()` получает параметр `max_slide_sec` (default 7). Если при расчёте `per_slide = duration / n` получается >max, добавляем дополнительные «копии» текущего слайда с разным Ken-Burns углом в последовательность, чтобы `n' = ceil(duration / max)`.

### 10.2 Extra: zoom-punch на cliffhanger

Когда pipeline знает таймстамп `[CLIFFHANGER_N]`, в `audio/music.py` уже вставляется SFX. Для видео — в `VideoComposeStage` добавить fast zoom (0.15s scale 1.0→1.15→1.0) с `enable=between(t, cliff-0.1, cliff+0.3)`.

Без детектирования «монотонных участков» — этого уже достаточно чтобы ломать залип.

---

## 11. Active-speaker coloring в typewriter

### 11.1 Проблема

`typewriter.render_png_sequence(words: list[WordTiming])` не знает кто говорит.

### 11.2 Решение

Добавить `WordTiming.speaker: str | None`.

В `video/subtitles.py::align()`:

1. Whisper возвращает word-timings без спикеров.
2. Параллельно у нас есть сегменты с префиксами `Рассказчик:` / `Герой:` и их временные окна (из `ctx.chapter_ranges`).
3. Для каждого `word.start` находим, в каком сегменте оно лежит, берём prefix как спикер.

В `typewriter.py`:

- `config/channel.yaml::subtitles.speaker_colors: {Рассказчик: "#FFFFFF", Герой: "#F5D76E"}`
- При рендере кадра — цвет зависит от спикера текущего слова. Переключение плавное (пауза >150мс между сменой цвета).

---

## 12. Testing + migration

### 12.1 Тесты stages

Каждый stage → `tests/pipeline/test_<stage>.py`:

- Мокаются внешние провайдеры.
- Проверяется `is_cached()` true на втором вызове.
- Проверяется что `ctx.<поле>` после `run()` соответствует ожидаемому.

### 12.2 Интеграционный тест

`tests/integration/test_full_pipeline.py`:

- `FakeTTSProvider`, `FakeImageProvider`, `FakeLLM`.
- Фиктивная history → полный проход 10 stages → проверяем что `ctx.packages` не пустой и все MP4 пути существуют (мок-файлы).
- Запускается за <5 секунд.

### 12.3 Миграции

- Schema: `src/core/storage.py::engine()` после `create_all()` выполняет `CREATE INDEX IF NOT EXISTS` для simhash.
- Data: существующие `StoryRow` без simhash останутся `NULL` → они просто не участвуют в дедупе, новые истории будут с хешем.
- `src/pipeline.py` с deprecation на 1 релиз.
- `src/core/config.*()` dict-getters остаются, но внутри делегируют в `AppConfig`.

### 12.4 Порядок выполнения (sprints)

**Sprint 1 — foundation (не ломаем)**

1. `src/core/context.py`, `src/core/logging.py`, `src/core/configs.py` с валидацией
2. `src/pipeline/stages/base.py`, `src/pipeline/runner.py` — но stages пока wrapping вокруг текущего `process_one`
3. `src/publish/scheduler.py` → `BEGIN IMMEDIATE` transaction
4. `src/core/storage.py::has_near_duplicate` + index
5. `src/cli.py health`
6. Все существующие тесты должны проходить как были

**Sprint 2 — stage extraction**

7–15. Вынести каждую из 9 фаз в свой stage-модуль, по одному в PR. После каждого — `pytest` зелёный + старый `process_one` удаляется.

**Sprint 3 — content upgrades**

16. `ScriptCritiqueStage` + тесты
17. `ThumbnailStage` с 3 вариантами + `swap-thumbnail` CLI
18. Per-platform metadata в LLM + packages
19. Pattern-interrupt (`max_slide_sec` + zoom-punch)
20. Active-speaker coloring в typewriter

Каждый commit ≤ 1 stage или ≤ 1 фича. `main` всегда green.

---

## Open questions (требуют решения до старта)

### OQ-1. Глубина LLM self-critique

Предложен один лишний Gemini call (~$0.008/история). Альтернатива — два прохода (draft → critique → rewrite → second-critique): качество ↑, стоимость ×2.

**Рекомендация:** один проход на старте, метрика «retention первых 30 сек» через 2 недели; если плато — добавить второй проход.

### OQ-2. Thumbnail A/B механика

Текущий план — ручной `swap-thumbnail`. Альтернатива — автоматическая ротация scheduler'ом каждые 48ч.

**Trade-off:** автомат удобнее, но cumulative analytics YT смешивается; ручной — точные данные, но забывается.

**Рекомендация:** старт ручной, через месяц добавить optional `--auto-rotate-thumbnails 48h` в scheduler.

### OQ-3. Pattern-interrupt глубина

MVP — cap на длину слайда. Полный pixel-diff анализ — ×3 сложности, ×1.2 польза.

**Рекомендация:** только MVP. Pixel-diff не делать без данных о retention drop'ах.

---

## Out of scope (осознанно не делаем в этом цикле)

- **Полная замена `config.py`** dict-API. `AppConfig` валидирует, но 50+ call-sites продолжают звать `config.sources()`. Миграция call-sites — отдельный PR после стабилизации.
- **Перенос JSONL в SQLite.** `costs.jsonl` / `events.jsonl` остаются как есть; health-dashboard читает их streaming. Миграция — когда файлы перевалят 100MB.
- **Distributed scheduler.** `BEGIN IMMEDIATE` решает single-node гонки. Multi-node lock через Redis/Postgres advisory — когда появится второй worker.
- **YouTube native A/B Testing API.** Не публичный. Если Google откроет — отдельная фича.
- **Pixel-diff pattern-interrupt.** См. OQ-3.
- **Whisper diarization** для speaker-coloring. Используем сегментные префиксы (мы их и так знаем) — diarization избыточна.
- **Web UI для health-dashboard.** CLI + JSON dump достаточно; web — когда будет ≥3 человека в команде.
