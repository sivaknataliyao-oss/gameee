"""YouTube advertiser-friendly pre-filter.

Calls Gemini with a cheap classification prompt BEFORE we spend on TTS/images.
Blocks stories likely to get demonetized per YouTube's Advertiser-Friendly
Content Guidelines (violence, self-harm, hate, drugs, adult content, harmful
acts, tragedies).

Fail-open policy: if the LLM is unavailable or returns garbage, we let the
story through — the nsfw/quality filters remain the safety net.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from src.core import config, costs
from src.core.resilience import CircuitBreaker, retry

log = logging.getLogger(__name__)

_breaker = CircuitBreaker("gemini_monetization", threshold=5, cooldown_sec=600)
# Very cheap: classification uses a few tokens in/out.
_IN_PER_1M = 0.30
_OUT_PER_1M = 2.50


@dataclass
class Verdict:
    friendly: bool
    risk_category: str     # one of: violence|self_harm|hate|drugs|adult|tragedy|none|error
    confidence: float
    explanation: str


SYSTEM = """You are a content-policy classifier for YouTube's Advertiser-Friendly
Content Guidelines. Given a story, return a JSON verdict:

{
  "friendly": bool,              # true if safe for monetization
  "risk_category": str,          # violence | self_harm | hate | drugs | adult | tragedy | none | other
  "confidence": 0.0..1.0,
  "explanation": str             # <= 120 chars, in Russian
}

Be strict about: graphic violence, sexual content, self-harm, hate speech,
illegal drug use, tragedies with identifiable victims, harmful/dangerous acts.
Crime stories, petty revenge, relationship drama, embarrassment, weird
situations — OK.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "friendly": {"type": "boolean"},
        "risk_category": {"type": "string"},
        "confidence": {"type": "number"},
        "explanation": {"type": "string"},
    },
    "required": ["friendly", "risk_category", "confidence", "explanation"],
}


def classify(text: str, title: str = "") -> Verdict:
    key = config.env("GEMINI_API_KEY")
    if not key:
        # Fail-open, but flag in verdict so callers can treat this stricter if needed.
        return Verdict(True, "error", 0.0, "no GEMINI_API_KEY")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return Verdict(True, "error", 0.0, "google-genai not installed")

    client = genai.Client(api_key=key)
    sample = (text or "").strip()
    if len(sample) > 4000:
        sample = sample[:4000] + "..."

    @_breaker
    @retry(attempts=2, initial=1.0, factor=2.0)
    def _call():
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Title: {title}\n\nStory:\n{sample}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=SCHEMA,
                temperature=0.0,
                max_output_tokens=256,
            ),
        )

    try:
        resp = _call()
    except Exception as exc:
        log.warning("monetization classifier failed: %s", exc)
        return Verdict(True, "error", 0.0, f"gemini_error: {exc}")

    raw = resp.text or "{}"
    try:
        data = json.loads(_extract_json(raw))
    except Exception as exc:
        log.warning("monetization classifier returned non-JSON: %r", raw[:160])
        return Verdict(True, "error", 0.0, f"parse_error: {exc}")

    try:
        usage = getattr(resp, "usage_metadata", None)
        if usage:
            costs.track("gemini_monetization", "in_tokens",
                        float(usage.prompt_token_count or 0),
                        _IN_PER_1M / 1_000_000, {"model": "gemini-2.5-flash"})
            costs.track("gemini_monetization", "out_tokens",
                        float(getattr(usage, "candidates_token_count", 0) or 0),
                        _OUT_PER_1M / 1_000_000, {"model": "gemini-2.5-flash"})
    except Exception:
        pass

    return Verdict(
        friendly=bool(data.get("friendly", True)),
        risk_category=str(data.get("risk_category") or "none"),
        confidence=float(data.get("confidence") or 0.0),
        explanation=str(data.get("explanation") or ""),
    )


def _extract_json(raw: str) -> str:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    return m.group(0) if m else raw
