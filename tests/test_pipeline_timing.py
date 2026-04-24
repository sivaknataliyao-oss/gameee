"""Ensure chapter time ranges follow real segment durations, not even splits."""
from pathlib import Path

from src.pipeline import _chapter_ranges_from_segments
from src.script.segmenter import Segment


def _seg(kind: str, index: int, text: str = "") -> Segment:
    return Segment(kind=kind, index=index, text=text)


def test_chapter_ranges_mirror_durations():
    # Hook(2s) -> Ch1 body(10s) -> Cliff1(2s) -> Ch2 body(15s) -> Cliff2(3s) -> Outro(2s)
    gap = 0.5
    seg_audio = [
        (_seg("hook", 0), Path("h"), 2.0),
        (_seg("chapter", 1), Path("c1"), 10.0),
        (_seg("cliffhanger", 1), Path("cl1"), 2.0),
        (_seg("chapter", 2), Path("c2"), 15.0),
        (_seg("cliffhanger", 2), Path("cl2"), 3.0),
        (_seg("outro", 0), Path("o"), 2.0),
    ]
    ranges = _chapter_ranges_from_segments(seg_audio, gap_sec=gap)
    assert len(ranges) == 2

    (start1, end1, hook1), (start2, end2, hook2) = ranges
    # First chapter starts roughly at t=0 (hook is prepended into ch1 window)
    assert start1 == 0.0
    # Ch1 ends after hook(2) + gap + ch1(10) + gap + cliff(2) = 15
    assert abs(end1 - 15.0) < 0.01
    # Ch2 starts at end1 + gap = 15.5
    assert abs(start2 - 15.5) < 0.01
    # Ch2 ends at 15.5 + 15 + gap + 3 = 34
    assert abs(end2 - 34.0) < 0.01
