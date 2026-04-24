from src.tts.router import TTSRouter


def test_router_moves_dialogue_primary_to_front_for_dialogue_text():
    r = TTSRouter()
    r.chain = ["google_chirp", "silero_local"]
    r.dialogue_primary = "gemini_tts"

    dialogue = "Рассказчик: Он вошёл.\nГерой: — Привет.\nРассказчик: Она молчала.\n"
    plain = "Он вошёл и увидел, что свет всё ещё горел."

    assert r._ordered(dialogue)[0] == "gemini_tts"
    assert r._ordered(plain) == ["google_chirp", "silero_local"]


def test_router_deduplicates_if_dialogue_primary_already_in_chain():
    r = TTSRouter()
    r.chain = ["gemini_tts", "google_chirp"]
    r.dialogue_primary = "gemini_tts"

    dialogue = "Рассказчик: Он вошёл.\nГерой: — Привет.\n"
    order = r._ordered(dialogue)
    assert order.count("gemini_tts") == 1
    assert order[0] == "gemini_tts"
    assert "google_chirp" in order
