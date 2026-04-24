"""Convert a ProcessedStory into ordered TTS segments with timing anchors."""
from __future__ import annotations

from dataclasses import dataclass

from src.core.models import ProcessedStory


@dataclass
class Segment:
    kind: str       # hook | chapter | cliffhanger | outro
    index: int      # chapter number the segment belongs to (0 for hook/outro)
    text: str


def segments(story: ProcessedStory) -> list[Segment]:
    out: list[Segment] = []
    if story.hook:
        out.append(Segment("hook", 0, story.hook))
    for ch in story.chapters:
        out.append(Segment("chapter", ch.index, ch.body))
        if ch.cliffhanger:
            out.append(Segment("cliffhanger", ch.index, ch.cliffhanger))
    tail = story.script_with_markers.split("[OUTRO]", 1)
    if len(tail) == 2:
        outro = tail[1].strip()
        if outro:
            out.append(Segment("outro", 0, outro))
    return out
