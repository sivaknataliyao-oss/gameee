from src.tts.gemini_tts import NARRATOR, _normalize_speakers, has_dialogue


def test_has_dialogue_detects_two_speakers():
    text = (
        "Рассказчик: Он вошёл в комнату.\n"
        "Герой: — Это ты сделал?\n"
        "Рассказчик: Она молчала.\n"
    )
    assert has_dialogue(text)


def test_has_dialogue_false_for_plain_narration():
    text = "Он вошёл в комнату. Там было темно и пахло сыростью."
    assert not has_dialogue(text)


def test_has_dialogue_false_for_single_speaker_only():
    text = "Рассказчик: Просто одна линия от рассказчика.\n"
    assert not has_dialogue(text)


def test_normalize_speakers_collapses_to_narrator_and_hero():
    text = (
        "Рассказчик: И тут появилась Маша.\n"
        "Маша: — Я знаю правду.\n"
        "Петя: — Не может быть.\n"
        "Рассказчик: Они смотрели друг на друга.\n"
    )
    normalized, speakers = _normalize_speakers(text)

    assert {"Маша", "Петя", "Рассказчик"}.issubset(speakers)
    # All non-narrator names collapsed to "Герой"
    assert "Маша:" not in normalized
    assert "Петя:" not in normalized
    assert normalized.count("Герой:") == 2
    # Narrator lines preserved
    assert normalized.count(f"{NARRATOR}:") == 2


def test_normalize_accepts_english_narrator_alias():
    text = "Narrator: cold open line.\nHero: — Line.\n"
    normalized, _ = _normalize_speakers(text)
    assert f"{NARRATOR}:" in normalized
    assert "Герой:" in normalized
