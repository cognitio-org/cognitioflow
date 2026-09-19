"""What gets spoken, and what must never be."""
import importlib
import importlib.util
import os
import sys
import threading
import time
import types

import pytest

import tts

# Captured at import, before the autouse fixture below clears every KOKORO_* variable.
_REAL_MODEL = os.path.expanduser(os.environ.get("KOKORO_TEST_MODEL_PATH", ""))
_REAL_VOICES = os.path.expanduser(os.environ.get("KOKORO_TEST_VOICES_PATH", ""))


@pytest.fixture(autouse=True)
def _reset_kokoro_cache(monkeypatch):
    """The kokoro engine is memoised at module scope (loading it costs ~1s), so every test that
    touches KOKORO_* env vars needs a clean slate or it would see a previous test's cached result."""
    monkeypatch.setattr(tts, "_kokoro_instance", None)
    monkeypatch.setattr(tts, "_kokoro_checked", False)
    for name in ("KOKORO_MODEL_PATH", "KOKORO_VOICES_PATH", "KOKORO_VOICE"):
        monkeypatch.delenv(name, raising=False)


def _model_files(tmp_path):
    model, voices = tmp_path / "kokoro.onnx", tmp_path / "voices.bin"
    model.write_bytes(b"model"); voices.write_bytes(b"voices")
    return str(model), str(voices)


def _fake_kokoro(monkeypatch, engine_cls, *, with_soundfile=True):
    """Install stand-ins for kokoro_onnx (and soundfile), so the backend's own logic runs without the
    350MB model. The fake soundfile writes a recognisable byte string instead of real MP3."""
    mod = types.ModuleType("kokoro_onnx"); mod.Kokoro = engine_cls
    monkeypatch.setitem(sys.modules, "kokoro_onnx", mod)
    if with_soundfile:
        sf = types.ModuleType("soundfile")
        sf.calls = []
        def write(buf, samples, rate, format):
            sf.calls.append((len(samples), rate, format)); buf.write(b"ID3" + bytes(samples))
        sf.write = write
        monkeypatch.setitem(sys.modules, "soundfile", sf)
        return sf
    monkeypatch.setitem(sys.modules, "soundfile", None)  # "import soundfile" now raises ImportError


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
    """With nothing configured, the voice must cost nothing.

    This asserted tts.BACKEND directly, but tts.py reads TTS from the environment once at
    import, and run.py loads .env.local before importing it. A developer who sets TTS=kokoro
    - the free local voice, which is the point - failed a test about the default and left
    scripts/check.sh red on a setting that is not a defect. Clear the variable and re-read.
    """
    saved = os.environ.pop("TTS", None)
    try:
        fresh = importlib.reload(tts)
        assert fresh.BACKEND == "browser", "the default must cost nothing"
        assert fresh.available() is False
        assert fresh.describe()["server"] is False
    finally:
        if saved is not None:
            os.environ["TTS"] = saved
        importlib.reload(tts)  # hand the module back as this machine actually has it


def test_a_failing_voice_becomes_no_audio_not_an_error(monkeypatch):
    """A quota or network failure mid-call must not surface as a 500: no audio means the page speaks."""
    monkeypatch.setattr(tts, "BACKEND", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k"); monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
    def broken(line): raise OSError("quota exceeded")
    monkeypatch.setattr(tts, "_elevenlabs", broken)
    assert tts.available() is True
    assert tts.say("Hello there.") is None


def test_kokoro_degrades_to_browser_when_model_files_are_absent(monkeypatch):
    """No KOKORO_* paths (a machine that never downloaded the model): quietly unavailable, like a
    missing ElevenLabs key, so the browser voice takes over."""
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    assert tts.available() is False
    assert tts.say("hello") is None
    assert tts.describe() == {"backend": "kokoro", "server": False, "language": tts.LANGUAGE}


def test_kokoro_degrades_when_paths_point_nowhere(monkeypatch):
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    monkeypatch.setenv("KOKORO_MODEL_PATH", "/nonexistent/model.onnx")
    monkeypatch.setenv("KOKORO_VOICES_PATH", "/nonexistent/voices.bin")
    assert tts.available() is False
    assert tts.say("hello") is None


def test_kokoro_needs_soundfile_too(monkeypatch, tmp_path):
    """Without soundfile the model could load but never encode, so every sentence would fail: better to
    report the backend as unavailable once than to fall back sentence by sentence."""
    class Engine:
        def __init__(self, *a): pass
    _fake_kokoro(monkeypatch, Engine, with_soundfile=False)
    model, voices = _model_files(tmp_path)
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    monkeypatch.setenv("KOKORO_MODEL_PATH", model); monkeypatch.setenv("KOKORO_VOICES_PATH", voices)
    assert tts.available() is False


def test_kokoro_load_failure_is_remembered_not_retried(monkeypatch, tmp_path):
    """A model that fails to load (corrupt file) is tried once; later calls must not pay for the failed
    load again on every request."""
    loads = []
    class Broken:
        def __init__(self, *a):
            loads.append(a); raise RuntimeError("corrupt model")
    _fake_kokoro(monkeypatch, Broken)
    model, voices = _model_files(tmp_path)
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    monkeypatch.setenv("KOKORO_MODEL_PATH", model); monkeypatch.setenv("KOKORO_VOICES_PATH", voices)
    assert tts.available() is False
    assert tts.available() is False
    assert tts.say("hello") is None
    assert len(loads) == 1


def test_kokoro_speaks_in_a_british_voice_as_mp3(monkeypatch, tmp_path):
    loads, calls = [], []
    class Engine:
        def __init__(self, model, voices): loads.append((model, voices))
        def create(self, text, voice, speed, lang):
            calls.append((text, voice, speed, lang)); return [1, 2, 3], 24000
    sf = _fake_kokoro(monkeypatch, Engine)
    model, voices = _model_files(tmp_path)
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    monkeypatch.setenv("KOKORO_MODEL_PATH", model); monkeypatch.setenv("KOKORO_VOICES_PATH", voices)
    assert tts.describe()["server"] is True
    first = tts.say("Nailed it [LECTURE]. **Van Gend** is right.")
    second = tts.say("Next question.")
    assert first == (b"ID3" + bytes([1, 2, 3]), "audio/mpeg") and second is not None
    assert loads == [(model, voices)]                     # loaded once, reused
    assert calls[0] == ("Nailed it . Van Gend is right.", "bf_alice", 1.0, "en-gb")
    assert sf.calls[0] == (3, 24000, "MP3")


def test_kokoro_voice_is_configurable(monkeypatch, tmp_path):
    voices_used = []
    class Engine:
        def __init__(self, *a): pass
        def create(self, text, voice, speed, lang):
            voices_used.append(voice); return [0], 24000
    _fake_kokoro(monkeypatch, Engine)
    model, voices = _model_files(tmp_path)
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    monkeypatch.setenv("KOKORO_MODEL_PATH", model); monkeypatch.setenv("KOKORO_VOICES_PATH", voices)
    monkeypatch.setenv("KOKORO_VOICE", "bm_george")
    tts.say("Hello there.")
    assert voices_used == ["bm_george"]


def test_a_request_that_arrives_mid_load_waits_instead_of_falling_back(monkeypatch, tmp_path):
    """The model takes about a second to load. A second request in that window used to see "not checked
    yet → checked, nothing loaded" and fall back to the browser voice; it must wait for the load instead."""
    loads = []
    class Slow:
        def __init__(self, *a):
            loads.append(a); time.sleep(0.3)
    _fake_kokoro(monkeypatch, Slow)
    model, voices = _model_files(tmp_path)
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    monkeypatch.setenv("KOKORO_MODEL_PATH", model); monkeypatch.setenv("KOKORO_VOICES_PATH", voices)
    seen = []
    threads = [threading.Thread(target=lambda: seen.append(tts.available())) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert seen == [True] * 5
    assert len(loads) == 1


_REAL_KOKORO = bool(importlib.util.find_spec("kokoro_onnx") and importlib.util.find_spec("soundfile")
                    and os.path.isfile(_REAL_MODEL) and os.path.isfile(_REAL_VOICES))


@pytest.mark.skipif(not _REAL_KOKORO, reason="set KOKORO_TEST_MODEL_PATH / KOKORO_TEST_VOICES_PATH and install "
                                             "kokoro-onnx + soundfile to run real synthesis")
def test_kokoro_actually_synthesises_real_audio(monkeypatch):
    """With the real package and model present, prove real MP3 audio comes out, not just plumbing."""
    monkeypatch.setattr(tts, "BACKEND", "kokoro")
    monkeypatch.setenv("KOKORO_MODEL_PATH", _REAL_MODEL)
    monkeypatch.setenv("KOKORO_VOICES_PATH", _REAL_VOICES)
    assert tts.available() is True
    out = tts.say("Nailed it. Van Gend en Loos is correctly cited.")
    assert out is not None
    audio, media_type = out
    assert media_type == "audio/mpeg"
    assert len(audio) > 2000
    assert audio[:3] == b"ID3" or audio[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")  # an MP3 header, not WAV or noise


# ---------------------------------------------------------------- EdgeTTS (Phase 12)
def _fake_edge(monkeypatch, chunks=None, fail=None):
    """A stand-in edge_tts: records what was asked for and streams the given chunks (or raises)."""
    calls = []
    mod = types.ModuleType("edge_tts")
    class Communicate:
        def __init__(self, text, voice, rate="+0%"):
            calls.append((text, voice, rate))
        async def stream(self):
            if fail:
                raise fail
            for c in chunks or []:
                yield c
    mod.Communicate = Communicate
    monkeypatch.setitem(sys.modules, "edge_tts", mod)
    monkeypatch.setattr(tts, "BACKEND", "edge")
    return calls


def test_edge_speaks_mp3_in_a_british_voice(monkeypatch):
    calls = _fake_edge(monkeypatch, [{"type": "audio", "data": b"\xff\xf3ab"},
                                     {"type": "WordBoundary", "offset": 1, "text": "Keck"},
                                     {"type": "audio", "data": b"cd"}])
    assert tts.describe()["server"] is True
    assert tts.say("**Keck** narrows *Dassonville* [LECTURE].") == (b"\xff\xf3abcd", "audio/mpeg")
    assert calls == [("Keck narrows Dassonville .", "en-GB-SoniaNeural", "+0%")]


def test_edge_voice_and_rate_are_configurable(monkeypatch):
    calls = _fake_edge(monkeypatch, [{"type": "audio", "data": b"x"}])
    monkeypatch.setenv("EDGE_VOICE", "en-GB-RyanNeural"); monkeypatch.setenv("EDGE_RATE", "+10%")
    tts.say("Hello.")
    assert calls == [("Hello.", "en-GB-RyanNeural", "+10%")]


def test_edge_network_failure_falls_back_to_the_browser(monkeypatch):
    _fake_edge(monkeypatch, fail=ConnectionError("no route to speech.platform.bing.com"))
    assert tts.say("Hello.") is None


def test_edge_with_no_audio_falls_back_to_the_browser(monkeypatch):
    _fake_edge(monkeypatch, [{"type": "WordBoundary", "offset": 0, "text": "Hello"}])
    assert tts.say("Hello.") is None


def test_edge_not_installed_is_simply_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "edge_tts", None)
    monkeypatch.setattr(tts, "BACKEND", "edge")
    assert tts.available() is False and tts.say("Hello.") is None


@pytest.mark.skipif(os.environ.get("EDGE_TTS_LIVE") != "1" or not importlib.util.find_spec("edge_tts"),
                    reason="set EDGE_TTS_LIVE=1 (and install edge-tts) to call Microsoft's service for real")
def test_edge_actually_synthesises_real_audio(monkeypatch):
    monkeypatch.setattr(tts, "BACKEND", "edge")
    out = tts.say("Van Gend en Loos: Article 30 has direct effect, erga omnes.")
    assert out is not None and out[1] == "audio/mpeg" and len(out[0]) > 2000
    assert out[0][:3] == b"ID3" or out[0][:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
