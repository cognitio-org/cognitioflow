"""What gets spoken, and what must never be."""
import os

import pytest

import tts


@pytest.fixture(autouse=True)
def _reset_kokoro_cache(monkeypatch):
    """The kokoro engine is memoised at module scope (loading it costs ~1s), so every test that
    touches KOKORO_* env vars needs a clean slate or it would see a previous test's cached result."""
    monkeypatch.setattr(tts, "_kokoro_instance", None, raising=False)
    monkeypatch.setattr(tts, "_kokoro_checked", False, raising=False)
    monkeypatch.delenv("KOKORO_MODEL_PATH", raising=False)
    monkeypatch.delenv("KOKORO_VOICES_PATH", raising=False)


def test_provenance_tags_are_not_read_aloud():
    said = tts.speakable("Dassonville [LECTURE] is the test [OUTSIDE FILES] here.")
    assert "LECTURE" not in said and "OUTSIDE FILES" not in said
    assert "Dassonville" in said and "is the test" in said


def test_markdown_is_not_read_aloud():
    assert tts.speakable("**Keck** says `selling arrangements` are #outside") == "Keck says selling arrangements are outside"


def test_a_spoken_turn_is_capped_so_a_paid_voice_cannot_run_away():
    assert len(tts.speakable("word " * 5000)) <= tts.MAX_CHARS


def test_sentences_split_so_the_first_can_play_while_the_rest_is_written():
    assert tts.sentences("Yes. But why? Because Cassis says so!") == ["Yes.", "But why?", "Because Cassis says so!"]


def test_empty_text_is_never_sent_to_a_paid_api():
    assert tts.say("   ") is None
    assert tts.sentences("") == []


def test_browser_backend_asks_the_page_to_speak_for_itself():
    assert tts.BACKEND == "browser", "the default must cost nothing"
    assert tts.available() is False
    assert tts.describe()["server"] is False


def test_kokoro_degrades_to_browser_when_model_files_are_absent(monkeypatch):
    """No KOKORO_MODEL_PATH/VOICES_PATH set (the default on a machine that never downloaded the
    model): this must behave exactly like a missing ElevenLabs key — quietly unavailable, not a
    crash, so the browser voice picks it up instead."""
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    assert tts.available() is False
    assert tts.say("hello") is None
    assert tts.describe() == {"backend": "kokoro", "server": False, "language": tts.LANGUAGE}


def test_kokoro_degrades_when_paths_are_set_but_files_do_not_exist(monkeypatch):
    """Paths configured but pointing nowhere (a typo, an unfinished download) must fail the same
    quiet way as no paths at all — never an unhandled exception reaching the caller."""
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    monkeypatch.setenv("KOKORO_MODEL_PATH", "/nonexistent/model.onnx")
    monkeypatch.setenv("KOKORO_VOICES_PATH", "/nonexistent/voices.bin")
    assert tts.available() is False
    assert tts.say("hello") is None


def test_kokoro_engine_load_failure_is_cached_not_retried(monkeypatch, tmp_path):
    """A real path that fails to load as a model (corrupt file, wrong format) must not be retried on
    every single call — that would make every request pay the failed-load cost forever."""
    bad_model = tmp_path / "model.onnx"; bad_model.write_bytes(b"not a real model")
    bad_voices = tmp_path / "voices.bin"; bad_voices.write_bytes(b"not real voices either")
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    monkeypatch.setenv("KOKORO_MODEL_PATH", str(bad_model))
    monkeypatch.setenv("KOKORO_VOICES_PATH", str(bad_voices))
    assert tts.available() is False
    assert tts._kokoro_checked is True
    # A second call must not re-attempt the load — flip _kokoro_checked back and confirm nothing
    # tries to import kokoro_onnx again (it isn't installed in this environment, so a retry
    # would raise ModuleNotFoundError instead of returning cleanly).
    assert tts.available() is False


_REAL_MODEL = os.path.join(os.environ.get("TMPDIR", "/tmp"), "kokoro-models", "kokoro-v1.0.onnx")
_REAL_VOICES = os.path.join(os.environ.get("TMPDIR", "/tmp"), "kokoro-models", "voices-v1.0.bin")

try:
    import kokoro_onnx  # noqa: F401
    _KOKORO_INSTALLED = True
except ImportError:
    _KOKORO_INSTALLED = False


@pytest.mark.skipif(
    not (_KOKORO_INSTALLED and os.path.exists(_REAL_MODEL) and os.path.exists(_REAL_VOICES)),
    reason="kokoro-onnx package and/or its ~350MB model files are not present on this machine",
)
def test_kokoro_actually_synthesises_when_installed(monkeypatch):
    """When the package and model files are genuinely present, prove real audio comes out — not
    just that the plumbing avoids crashing."""
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    monkeypatch.setenv("KOKORO_MODEL_PATH", _REAL_MODEL)
    monkeypatch.setenv("KOKORO_VOICES_PATH", _REAL_VOICES)
    assert tts.available() is True
    out = tts.say("Nailed it. Van Gend en Loos is correctly cited.")
    assert out is not None
    audio, media_type = out
    assert media_type == "audio/mpeg"
    assert len(audio) > 1000  # a real MP3, not an empty stub
