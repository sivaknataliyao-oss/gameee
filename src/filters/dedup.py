"""Shingle + simhash dedup over story text to avoid reposting identical content."""
from __future__ import annotations

import hashlib
import re


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower(), flags=re.UNICODE)


def simhash(text: str, k: int = 6) -> int:
    toks = _tokens(text)
    if len(toks) < k:
        toks = toks + [""] * (k - len(toks))
    shingles = [" ".join(toks[i : i + k]) for i in range(len(toks) - k + 1)]
    bits = [0] * 64
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode("utf-8"), digest_size=8).digest(), "big")
        for i in range(64):
            if (h >> i) & 1:
                bits[i] += 1
            else:
                bits[i] -= 1
    out = 0
    for i, b in enumerate(bits):
        if b > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()
