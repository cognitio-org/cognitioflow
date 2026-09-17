"""
Speech-out seam (Phase 11c, +Kokoro Phase 12). TTS=browser|google|elevenlabs|kokoro picks the
backend, the way STORAGE and STT_PROVIDER already do. Nothing above this module knows which voice
is speaking.

  browser     — no server call; the page uses its own voice. Free, robotic, always available.
  google      — Chirp 3 HD through the service account the app already signs in with. No new secret.
  elevenlabs  — ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID. The most natural voice, and the one that
                costs money per character, so `MAX_CHARS` is a hard stop rather than a suggestion.
  kokoro      — local, offline, free: an 82M-parameter ONNX model run in-process. No API key, no
                per-character cost, no network call at speak time. Needs the `kokoro-onnx` package
                plus its two model files (~350MB total) on disk — neither ships with the app, so this
                degrades to the browser voice exactly like a missing ElevenLabs key does. Slower than
                a hosted API (roughly a quarter of real time on a laptop CPU) and the model files are
                too large to bundle into the Cloud Run image, so this backend is for local dev only;
                production should use google or elevenlabs.
"""
import json
import os
import re
import urllib.request

BACKEND = os.environ.get("TTS", "browser").strip().lower()
MAX_CHARS = 600          # one spoken turn; the tutor prompt already caps replies at 45 words
LANGUAGE = os.environ.get("TTS_LANGUAGE", "en-GB")

_SAY_NOTHING = re.compile(r"\[(?:LECTURE|WG|SLIDES|READER|SCHUTZE|SCRIPTUM|DCFR|NATIONAL|ADDED|OUTSIDE FILES)[^\]]*\]")
_MARKUP = re.compile(r"[*_`#>|]")


def speakable(text: str) -> str:
    """Provenance tags and markdown are for the eye. Reading them aloud is noise."""
    clean = _MARKUP.sub("", _SAY_NOTHING.sub("", str(text or "")))
    return re.sub(r"\s{2,}", " ", clean).strip()[:MAX_CHARS]


def sentences(text: str):
    """
    Split into what can be spoken while the rest is still being written. This is the whole latency
    trick: the first sentence starts playing while the model is still generating the second.
    """
    parts = re.findall(r"[^.!?]+[.!?]*", speakable(text))
    return [p.strip() for p in parts if p.strip()]


def available() -> bool:
    if BACKEND == "google":
        try:
            import google.cloud.texttospeech  # noqa: F401
            return True
        except Exception:
            return False
    if BACKEND == "elevenlabs":
        return bool(os.environ.get("ELEVENLABS_API_KEY") and os.environ.get("ELEVENLABS_VOICE_ID"))
    if BACKEND == "kokoro":
        return _kokoro_engine() is not None
    return False


def describe() -> dict:
    """What the page needs to know: whether to ask the server for audio, or speak for itself."""
    return {"backend": BACKEND, "server": available(), "language": LANGUAGE}


def say(text: str):
    """
    Returns (audio_bytes, media_type), or None when the page should use its own voice — which is also
    what happens if a paid backend is selected but not configured, so a missing key degrades to a
    working robotic voice instead of silence.
    """
    line = speakable(text)
    if not line or not available():
        return None
    if BACKEND == "google":
        return _google(line)
    if BACKEND == "elevenlabs":
        return _elevenlabs(line)
    if BACKEND == "kokoro":
        return _kokoro(line)
    return None


def _google(line: str):
    from google.cloud import texttospeech as t
    client = t.TextToSpeechClient()
    audio = client.synthesize_speech(
        input=t.SynthesisInput(text=line),
        voice=t.VoiceSelectionParams(language_code=LANGUAGE, name=os.environ.get("TTS_VOICE", "en-GB-Chirp3-HD-Charon")),
        audio_config=t.AudioConfig(audio_encoding=t.AudioEncoding.MP3, speaking_rate=1.05),
    )
    return audio.audio_content, "audio/mpeg"


def _elevenlabs(line: str):
    voice = os.environ["ELEVENLABS_VOICE_ID"]
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
        data=json.dumps({"text": line, "model_id": os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")}).encode(),
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(), "audio/mpeg"


_kokoro_instance = None
_kokoro_checked = False


def _kokoro_engine():
    """
    Load once per process, then reuse — the model is ~350MB and takes about a second to load, so
    doing that on every request would make the backend pointless. Any failure (package missing,
    model files missing, corrupt files) is cached as "unavailable" rather than retried every call,
    matching how `available()` treats a missing ElevenLabs key: a quiet, permanent fallback.
    """
    global _kokoro_instance, _kokoro_checked
    if _kokoro_checked:
        return _kokoro_instance
    _kokoro_checked = True
    model = os.environ.get("KOKORO_MODEL_PATH", "")
    voices = os.environ.get("KOKORO_VOICES_PATH", "")
    if not (model and voices and os.path.exists(model) and os.path.exists(voices)):
        return None
    try:
        from kokoro_onnx import Kokoro
        _kokoro_instance = Kokoro(model, voices)
    except Exception as e:
        print("kokoro: unavailable —", type(e).__name__, e)
        _kokoro_instance = None
    return _kokoro_instance


def _kokoro(line: str):
    import io
    import soundfile as sf
    engine = _kokoro_engine()
    if engine is None:
        return None
    voice = os.environ.get("KOKORO_VOICE", "bf_alice")  # a warm British voice, matching TTS_LANGUAGE's default
    samples, rate = engine.create(line, voice=voice, speed=1.0, lang="en-gb")
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="MP3")  # matches the media type every other backend returns
    return buf.getvalue(), "audio/mpeg"
