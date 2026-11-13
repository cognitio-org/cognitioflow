"""Gate D — Polish / "feels AAA" (VLM aesthetic judge).

The VLM is injected as a callable `(image_path: str) -> str` that returns the
model's raw JSON text `{"score": 0..1, "notes": "..."}`. The gate parses that
text fail-closed: anything it cannot confidently read as an in-range score →
ok False. The acceptance test injects a fake callable and needs no real image
or VLM.

Fail-closed rules (adopted from the Gemini design pass):
- Unparseable / no JSON object / non-dict parse → ok False.
- Missing or non-numeric score → ok False.
- bool is rejected explicitly (isinstance(True, int) is True in Python).
- NaN / Infinity / out-of-range score → ok False (no clamping — an
  out-of-bounds score signals a hallucination, not a near-miss).
- The injected callable raising or returning a non-str → ok False.
- On any failure: score=0.0, notes carries the reason, raw is always kept
  (even "" or the exception text) so the review card can show what happened.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class AestheticVerdict:
    ok: bool
    score: float
    notes: str
    raw: str


def _extract_json(text: str) -> dict | None:
    """Best-effort fail-closed extraction of one JSON object from VLM text.

    Tries: raw parse → strip a ```json fence → first-'{'-to-last-'}' slice.
    Returns a dict, or None if nothing parses to a dict.
    """
    candidates: list[str] = [text]

    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1))

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(text[first : last + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def judge_aesthetics(
    screenshot_path: str,
    vlm: Callable[[str], str],
    polish_floor: float = 0.6,
) -> AestheticVerdict:
    """Score a screenshot with an injected VLM, fail-closed.

    `vlm` is called with `screenshot_path` and must return raw JSON text
    `{"score": 0..1, "notes": "..."}`. ok = score >= polish_floor.
    """
    # The injected call is the dominant real-world failure point.
    try:
        raw = vlm(screenshot_path)
    except Exception as exc:
        return AestheticVerdict(
            ok=False, score=0.0, notes=f"vlm call raised: {exc}", raw=""
        )

    if not isinstance(raw, str):
        return AestheticVerdict(
            ok=False,
            score=0.0,
            notes=f"vlm returned non-str: {type(raw).__name__}",
            raw="",
        )

    parsed = _extract_json(raw)
    if parsed is None:
        return AestheticVerdict(
            ok=False, score=0.0, notes="no parseable JSON object in VLM output", raw=raw
        )

    if "score" not in parsed:
        return AestheticVerdict(
            ok=False, score=0.0, notes="VLM output missing 'score'", raw=raw
        )

    score = parsed["score"]
    # bool is an int subclass — reject it so {"score": true} never reads as 1.0.
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return AestheticVerdict(
            ok=False,
            score=0.0,
            notes=f"'score' is not numeric: {score!r}",
            raw=raw,
        )

    score = float(score)
    if not math.isfinite(score) or not (0.0 <= score <= 1.0):
        return AestheticVerdict(
            ok=False,
            score=0.0,
            notes=f"'score' out of range [0,1] (no clamping): {score!r}",
            raw=raw,
        )

    notes = parsed.get("notes", "")
    if not isinstance(notes, str):
        return AestheticVerdict(
            ok=False,
            score=0.0,
            notes=f"'notes' present but not a string: {notes!r}",
            raw=raw,
        )

    ok = score >= polish_floor
    return AestheticVerdict(ok=ok, score=score, notes=notes, raw=raw)
