"""Phase 8: the tutor dictation relay (transcribe/live.py) with a fake Live session, socket and clock. Never reaches Vertex."""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import pytest

from transcribe import live


class FakeSocket:
    def __init__(self, frames):
        self.frames, self.sent, self.closed = list(frames), [], None

    async def receive(self):
        await asyncio.sleep(0)
        return self.frames.pop(0) if self.frames else {"type": "websocket.disconnect"}

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000):
        self.closed = code


def msg(interim=None, final=None):
    return NS(server_content=NS(interim_input_transcription=NS(text=interim) if interim else None,
                                input_transcription=NS(text=final) if final else None))


class FakeSession:
    """Emits scripted messages as audio arrives; the stream end releases the last final and ends the receive loop."""
    def __init__(self, on_audio, on_end):
        self.on_audio, self.on_end, self.queue, self.audio, self.ended = list(on_audio), list(on_end), asyncio.Queue(), [], False

    async def send_realtime_input(self, audio=None, audio_stream_end=None):
        if audio is not None:
            self.audio.append(audio)
            if self.on_audio:
                await self.queue.put(self.on_audio.pop(0))
        if audio_stream_end:
            self.ended = True
            for m in self.on_end:
                await self.queue.put(m)
            await self.queue.put(None)

    async def receive(self):
        while (m := await self.queue.get()) is not None:
            yield m


def connector(session, seen=None):
    @asynccontextmanager
    async def connect(terms):
        if seen is not None:
            seen.append(terms)
        yield session
    return connect


PCM = b"\x00\x01" * 1600  # 100 ms


def run(coro):
    return asyncio.run(coro)


def test_interim_then_final_then_done():
    session = FakeSession(on_audio=[msg(interim="Article"), msg(interim="Article 34 prohib")], on_end=[msg(final="Article 34 prohibits MEQRs.")])
    sock = FakeSocket([{"bytes": PCM}, {"bytes": PCM}, {"text": json.dumps({"stop": True})}])
    seen = []
    summary = run(live.relay(sock, ["Dassonville"], connect=connector(session, seen)))
    assert sock.sent == [{"interim": "Article"}, {"interim": "Article 34 prohib"}, {"final": "Article 34 prohibits MEQRs."},
                         {"done": "Article 34 prohibits MEQRs.", "seconds": 0.2, "cost_usd": summary["cost_usd"]}]
    assert sock.closed == 1000 and session.ended and len(session.audio) == 2 and seen == [["Dassonville"]]
    assert session.audio[0].mime_type == "audio/pcm;rate=16000"
    assert summary["text"] == "Article 34 prohibits MEQRs." and summary["error"] == ""


def test_finals_accumulate_and_interims_show_the_whole_text():
    session = FakeSession(on_audio=[msg(final="Dassonville."), msg(interim="Then Cassis")], on_end=[msg(final="Then Cassis de Dijon.")])
    sock = FakeSocket([{"bytes": PCM}, {"bytes": PCM}, {"text": '{"stop": true}'}])
    run(live.relay(sock, [], connect=connector(session)))
    assert {"interim": "Dassonville. Then Cassis"} in sock.sent
    assert sock.sent[-1]["done"] == "Dassonville. Then Cassis de Dijon."


def test_closing_the_tab_ends_quietly():
    session = FakeSession(on_audio=[msg(final="Keck.")], on_end=[])
    sock = FakeSocket([{"bytes": PCM}])  # then the fake socket reports a disconnect
    summary = run(live.relay(sock, [], connect=connector(session)))
    assert not any("done" in m for m in sock.sent) and summary["seconds"] == 0.1


def test_vertex_failure_tells_the_browser_and_closes():
    @asynccontextmanager
    async def refused(terms):
        raise PermissionError("aiplatform.endpoints.predict denied")
        yield
    sock = FakeSocket([{"bytes": PCM}])
    summary = run(live.relay(sock, [], connect=refused))
    assert sock.sent == [{"error": summary["error"]}] and sock.closed == 1011
    assert "unavailable" in summary["error"] and "denied" not in summary["error"]  # no provider internals in the UI


def test_time_limit_stops_and_still_delivers_the_text():
    ticks = iter([0.0, 0.0, 0.0, 0.0, live.MAX_SECONDS + 1] + [live.MAX_SECONDS + 10] * 50)
    session = FakeSession(on_audio=[msg(interim="long answer")], on_end=[msg(final="long answer.")])
    sock = FakeSocket([{"bytes": PCM}, {"bytes": PCM}])
    run(live.relay(sock, [], connect=connector(session), clock=lambda: next(ticks)))
    assert {"limit": True} in sock.sent and sock.sent[-1]["done"] == "long answer."


def test_vocabulary_is_deduplicated_and_capped():
    terms = ["Keck", " Keck ", ""] + [f"Case C-{i}/19" for i in range(150)]
    cfg = live.live_config(terms)
    vocab = cfg.input_audio_transcription.custom_vocabulary
    assert vocab[0] == "Keck" and len(vocab) == live.MAX_VOCABULARY and vocab.count("Keck") == 1
    assert cfg.input_audio_transcription.language_codes == ["en-GB"] and cfg.response_modalities == ["TEXT"]


def test_available_needs_a_project_and_can_be_switched_off(monkeypatch):
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    assert live.available() is False
    monkeypatch.setenv("GCP_PROJECT", "vigilant-axis-483119-r8")
    assert live.available() is True
    monkeypatch.setenv("VOICE_GEMINI", "off")
    assert live.available() is False


# ---------------------------------------------------------------- the /api/voice/live route
from starlette.websockets import WebSocketDisconnect


def test_route_closes_when_gemini_is_not_available(client, monkeypatch):
    monkeypatch.setenv("VOICE_GEMINI", "off")
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/api/voice/live"):
            pass
    assert e.value.code == 4404


def test_route_relays_with_the_course_glossary(client, monkeypatch):
    import run
    monkeypatch.setenv("GCP_PROJECT", "vigilant-axis-483119-r8")
    monkeypatch.delenv("VOICE_GEMINI", raising=False)
    monkeypatch.setattr(run, "_glossary", lambda cid, limit=220: ["Dassonville", "Keck"] if cid == "eu" else [])
    seen = {}
    async def fake_relay(websocket, terms, **kw):
        seen["terms"] = terms
        await websocket.send_json({"done": "Dassonville?", "seconds": 1.0, "cost_usd": 0.00015})
        await websocket.close()
    monkeypatch.setattr(run.voice, "relay", fake_relay)
    with client.websocket_connect("/api/voice/live?course=eu") as ws:
        assert ws.receive_json()["done"] == "Dassonville?"
    assert seen["terms"] == ["Dassonville", "Keck"]


def test_config_reports_whether_gemini_dictation_is_offered(client, monkeypatch):
    monkeypatch.setenv("GCP_PROJECT", "vigilant-axis-483119-r8")
    monkeypatch.delenv("VOICE_GEMINI", raising=False)
    assert client.get("/api/config").json()["voice"] == {"gemini": True}
    monkeypatch.setenv("VOICE_GEMINI", "off")
    assert client.get("/api/config").json()["voice"] == {"gemini": False}
