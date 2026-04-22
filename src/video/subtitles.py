"""Word-level subtitle timing via faster-whisper (forced alignment on synthesized TTS).

Returns list of WordTiming entries which typewriter.py consumes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class WordTiming:
    text: str
    start: float
    end: float


def align(audio_path: Path, text: str | None = None, model: str = "small") -> list[WordTiming]:
    """Transcribe + extract word timestamps.

    We run STT on our own TTS output to get word-level timing (TTS providers
    rarely return it directly). `text` is kept for signature symmetry; not used
    unless we implement true forced alignment.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.warning("faster-whisper not installed; subtitles will fall back to cps-estimate")
        return []

    whisper = WhisperModel(model, device="auto", compute_type="auto")
    segments, _info = whisper.transcribe(
        str(audio_path), language="ru", word_timestamps=True, vad_filter=True,
    )
    words: list[WordTiming] = []
    for seg in segments:
        for w in (seg.words or []):
            words.append(WordTiming(text=w.word.strip(), start=float(w.start), end=float(w.end)))
    return words


def to_ass(words: list[WordTiming], out_path: Path,
           font: str = "Manrope Bold", size: int = 64,
           primary: str = "&H00FFFFFF", outline: str = "&H00000000",
           line_chars: int = 28) -> Path:
    """Dump word timings to an ASS file, 2-line wrapping for vertical 9:16.

    Used when typewriter PNG-seq is disabled (fallback caption mode).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\nPlayResY: 1920\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},{primary},&H000000FF,{outline},&H64000000,"
        "-1,0,0,0,100,100,0,0,1,4,2,2,60,60,220,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines: list[str] = []

    # Group words into chunks up to `line_chars` characters.
    chunk: list[WordTiming] = []
    chunk_len = 0
    for w in words:
        if chunk_len + len(w.text) + 1 > line_chars and chunk:
            lines.append(_event(chunk))
            chunk, chunk_len = [], 0
        chunk.append(w)
        chunk_len += len(w.text) + 1
    if chunk:
        lines.append(_event(chunk))

    out_path.write_text(header + "\n".join(lines), encoding="utf-8")
    return out_path


def _event(chunk: list[WordTiming]) -> str:
    start, end = chunk[0].start, chunk[-1].end
    text = " ".join(w.text for w in chunk)
    return f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{text}"


def _ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:01d}:{m:02d}:{s:05.2f}"
