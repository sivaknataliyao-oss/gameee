import json
from pathlib import Path

from src.publish import preview


def test_build_html_page(tmp_path):
    run = tmp_path / "reddit_abc123"
    run.mkdir()

    # Minimal artifacts the preview page looks for.
    (run / "long_16x9.mp4").write_bytes(b"\x00\x00\x00 ftypisom")
    (run / "thumbnail.jpg").write_bytes(b"\xff\xd8\xff\xe0")

    shorts = run / "shorts"
    shorts.mkdir()
    (shorts / "short_01.mp4").write_bytes(b"\x00\x00\x00 ftypisom")
    (shorts / "short_02.mp4").write_bytes(b"\x00\x00\x00 ftypisom")

    packages = run / "packages"
    packages.mkdir()
    (packages / "youtube_long.json").write_text(
        json.dumps({"platform": "youtube", "title": "Test"}),
        encoding="utf-8",
    )

    (run / "processed.json").write_text(
        json.dumps({"selected_title": "Тестовая история", "keywords": ["тест"]},
                   ensure_ascii=False),
        encoding="utf-8",
    )

    out = preview.build(run)
    assert out.exists()
    html = out.read_text(encoding="utf-8")

    assert "long_16x9.mp4" in html
    assert "thumbnail.jpg" in html
    assert "short_01.mp4" in html
    assert "short_02.mp4" in html
    assert "Тестовая история" in html
    assert "youtube_long.json" in html


def test_build_html_skips_missing_thumbnail(tmp_path):
    run = tmp_path / "reddit_xyz"
    run.mkdir()
    (run / "long_16x9.mp4").write_bytes(b"\x00")

    out = preview.build(run)
    html = out.read_text(encoding="utf-8")
    assert "Обложка" not in html
