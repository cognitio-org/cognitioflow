"""
Transcription seam (Phase 3). Hosted Speech-to-Text only; the provider does the work, job state lives in the
jobs table (run.py owns the database, per the db() seam).

  check_ready()            raises ProviderError when transcription can't run in this environment
  submit(audio_key, lang)  -> provider operation id
  poll(op_id)              -> ("running" | "done" | "failed", segments | None, language or error detail)
  format_capture(segs, rid) -> the Live capture lines the note renderer and audio anchors depend on

Provider chosen by STT_PROVIDER (google).
"""
import os
from typing import List, Tuple, TypedDict


class Segment(TypedDict):
    start: float
    text: str


class ProviderError(Exception):
    """A permanent provider failure: the job is marked failed with this (readable) message."""


def _provider():
    name = os.environ.get("STT_PROVIDER", "google")
    if name == "google":
        from transcribe.providers import google
        return google
    raise ProviderError(f"Unknown STT_PROVIDER={name!r} (expected google).")


def check_ready() -> None:
    _provider().check_ready()


def submit(audio_key: str, language: str) -> str:
    return _provider().submit(audio_key, language)


def poll(op_id: str):
    return _provider().poll(op_id)


def group_words(words: List[Tuple[float, str]], max_span: float = 30.0) -> List[Segment]:
    """Timed words -> short segments: a new one after sentence-ending punctuation or every ~30 s,
    so each [mm:ss] anchor stays close to what it labels."""
    segments, current, start = [], [], None
    for t, word in words:
        word = word.strip()
        if not word:
            continue
        if start is None:
            start = t
        current.append(word)
        if word.endswith((".", "?", "!")) or t - start >= max_span:
            segments.append({"start": start, "text": " ".join(current)})
            current, start = [], None
    if current:
        segments.append({"start": start, "text": " ".join(current)})
    return segments


def format_capture(segments: List[Segment], rid: str) -> str:
    """Byte-for-byte the laptop build's format: [mm:ss] text <!--r:{rid}:{secs}--> (minutes may exceed 59)."""
    lines = []
    for s in segments:
        t = int(s["start"])
        lines.append(f"[{t//60:02d}:{t%60:02d}] {s['text'].strip()} <!--r:{rid}:{t}-->")
    return "\n".join(lines)
