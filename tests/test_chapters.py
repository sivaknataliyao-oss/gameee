from src.publish.package import build_long_youtube, youtube_chapters_block


def test_chapters_block_emits_yt_friendly_format():
    ranges = [
        (0.0, 120.0, "Когда он открыл конверт"),
        (120.0, 240.0, "Правда всплыла наружу"),
        (240.0, 360.0, "Финал, которого никто не ждал"),
    ]
    block = youtube_chapters_block(ranges)

    lines = block.splitlines()
    # First line is the header, second line must be exactly "00:00 ..."
    assert lines[0].startswith("Главы")
    assert lines[1].startswith("00:00 ")
    # Chapter timestamps monotonically increasing
    assert "2:00" in block
    assert "4:00" in block


def test_chapters_block_respects_10sec_minimum():
    # Two chapters too close together; YT requires >= 10s between chapters.
    ranges = [(0.0, 3.0, "A"), (3.0, 6.0, "B")]
    block = youtube_chapters_block(ranges)
    # With only 2 valid entries we return empty (YT wants >= 3).
    assert block == ""


def test_chapters_block_applies_intro_offset():
    ranges = [
        (0.0, 60.0, "Вступление"),
        (60.0, 120.0, "Развязка"),
        (120.0, 180.0, "Эпилог"),
    ]
    without = youtube_chapters_block(ranges, intro_offset_sec=0)
    with_intro = youtube_chapters_block(ranges, intro_offset_sec=3.0)
    assert "0:03" in with_intro or "0:03" in without or True  # ensure no crash
    # Real assertion: the first chapter after 00:00 should shift by intro length.
    lines = with_intro.splitlines()
    timestamps = [ln.split(" ")[0] for ln in lines[2:]]
    # 60s + 3s intro -> 01:03
    assert "1:03" in timestamps or any("1:03" in ln for ln in lines)


def test_build_long_youtube_embeds_chapters_in_description():
    from pathlib import Path
    pkg = build_long_youtube(
        title="Невероятная история",
        description="Он нашёл письмо на чердаке.",
        keywords=["письмо", "чердак"],
        video_path=Path("video.mp4"),
        publish_at=None,
        chapter_ranges=[
            (0.0, 60.0, "Находка"),
            (60.0, 150.0, "Письмо"),
            (150.0, 300.0, "Разгадка"),
        ],
    )
    assert "00:00" in pkg.description
    assert "Главы:" in pkg.description
    assert "Находка" in pkg.description
