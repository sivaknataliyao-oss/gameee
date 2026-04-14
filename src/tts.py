"""Text-to-Speech через Google Cloud TTS (WaveNet).

У тебя это работает через OpenClaw — подключи свой вызов
или используй этот модуль напрямую с Google Cloud credentials.
"""

import os
import subprocess


def synthesize_google_cloud(text: str, output_path: str, voice: str = "en-US-Wavenet-D",
                            language_code: str = "en-US") -> str:
    """Синтез речи через Google Cloud TTS WaveNet.

    Требует: GOOGLE_APPLICATION_CREDENTIALS в env
    или `gcloud auth application-default login`

    *** ЕСЛИ У ТЕБЯ РАБОТАЕТ ЧЕРЕЗ OPENCLAW — ЗАМЕНИ ЭТУ ФУНКЦИЮ ***
    """
    try:
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechClient()

        # Разбиваем на куски по 5000 байт (лимит Google Cloud TTS)
        chunks = _split_text(text, max_bytes=4800)
        audio_parts = []

        for i, chunk in enumerate(chunks):
            synthesis_input = texttospeech.SynthesisInput(text=chunk)
            voice_params = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice,
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=0.95,
                pitch=0.0,
            )

            response = client.synthesize_speech(
                input=synthesis_input, voice=voice_params, audio_config=audio_config
            )

            part_path = output_path.replace(".mp3", f"_part{i:03d}.mp3")
            with open(part_path, "wb") as f:
                f.write(response.audio_content)
            audio_parts.append(part_path)
            print(f"[TTS] Часть {i+1}/{len(chunks)} готова")

        # Склеиваем части через FFmpeg
        if len(audio_parts) == 1:
            os.rename(audio_parts[0], output_path)
        else:
            _concat_audio(audio_parts, output_path)
            for part in audio_parts:
                os.remove(part)

        print(f"[TTS] Аудио сохранено: {output_path}")
        return output_path

    except ImportError:
        print("[TTS] ⚠ google-cloud-texttospeech не установлен")
        print("[TTS] Используется fallback: edge-tts")
        return synthesize_edge_tts(text, output_path)


def synthesize_edge_tts(text: str, output_path: str,
                        voice: str = "en-US-GuyNeural") -> str:
    """Бесплатный fallback через edge-tts (Microsoft)."""
    try:
        import edge_tts
        import asyncio

        async def _run():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)

        asyncio.run(_run())
        print(f"[TTS] Аудио сохранено (edge-tts): {output_path}")
        return output_path

    except ImportError:
        print("[TTS] ⚠ edge-tts не установлен, создаю тишину как заглушку")
        return _create_silent_placeholder(output_path, duration=300)


def _split_text(text: str, max_bytes: int = 4800) -> list[str]:
    """Разбивает текст на куски, не ломая предложения."""
    sentences = text.replace("\n", " ").split(". ")
    chunks = []
    current = ""

    for sentence in sentences:
        candidate = f"{current}. {sentence}" if current else sentence
        if len(candidate.encode("utf-8")) > max_bytes:
            if current:
                chunks.append(current.strip())
            current = sentence
        else:
            current = candidate

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text]


def _concat_audio(parts: list[str], output_path: str) -> None:
    """Склеивает MP3-файлы через FFmpeg."""
    list_file = output_path + ".list.txt"
    with open(list_file, "w") as f:
        for part in parts:
            f.write(f"file '{os.path.abspath(part)}'\n")

    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
         "-c", "copy", output_path],
        capture_output=True,
    )
    os.remove(list_file)


def _create_silent_placeholder(output_path: str, duration: int = 300) -> str:
    """Создаёт тихий MP3 как заглушку."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono",
         "-t", str(duration), "-c:a", "libmp3lame", output_path],
        capture_output=True,
    )
    return output_path


def script_to_narration(script: dict) -> str:
    """Извлекает текст озвучки из сценария."""
    parts = []
    for section in script.get("sections", []):
        text = section.get("text", "")
        if text:
            parts.append(text)
    return " ".join(parts)
