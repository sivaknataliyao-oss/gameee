from src.core.models import Chapter, LengthProfile, ProcessedStory
from src.script.llm import _parse_chapters
from src.script.segmenter import segments


def test_parse_chapters_from_markers():
    script = (
        "[HOOK] Начало\n"
        "[CHAPTER_1] Первая часть. Детали.\n[CLIFFHANGER_1] Но тут...\n"
        "[CHAPTER_2] Вторая часть.\n[CLIFFHANGER_2] Шок.\n"
        "[OUTRO] Подпишись."
    )
    chapters = _parse_chapters(script)
    assert len(chapters) == 2
    assert chapters[0].index == 1
    assert "Первая часть" in chapters[0].body
    assert "Но тут" in chapters[0].cliffhanger


def test_segmenter_order():
    processed = ProcessedStory(
        story_id="x",
        title_variants=["a"],
        selected_title="a",
        hook="Начало.",
        cleaned_text="t",
        script_with_markers="[HOOK] Начало.\n[CHAPTER_1] body\n[CLIFFHANGER_1] cliff\n[OUTRO] подпишись",
        chapters=[Chapter(index=1, hook="Начало.", body="body", cliffhanger="cliff")],
        keywords=[],
        image_prompts=[],
        profile=LengthProfile.SHORT,
    )
    segs = segments(processed)
    kinds = [s.kind for s in segs]
    assert kinds == ["hook", "chapter", "cliffhanger", "outro"]
