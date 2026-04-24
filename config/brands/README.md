# Brand overlays

Каждый подкаталог здесь — отдельный бренд/канал. Он может содержать частичные
overlay-файлы, которые накладываются поверх дефолтов из `../config/*.yaml`.

Пример: `config/brands/horror/channel.yaml` переопределит только те ключи,
которые в нём есть, остальное возьмётся из `config/channel.yaml`.

Активировать:

```bash
GAMEEE_BRAND=horror python -m src.cli run
# или
python -m src.cli --brand=horror run
```

В дефолтном режиме (`GAMEEE_BRAND=default` или не установлен) берутся только
базовые YAML без overlay'ев.

Типичные overlay-файлы:
- `channel.yaml` — handle/url/brand colors/watermark
- `sources.yaml` — тематические сабреддиты/аккаунты
- `voices.yaml` — другой голос
- `audio.yaml` — другой music_dir
- `images.yaml` — другой style.prefix для единого визуального стиля канала
