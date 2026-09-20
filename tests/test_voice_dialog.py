"""The spoken tutor relay (transcribe/dialog.py) against a fake Live session and socket. Never reaches Vertex."""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import pytest  # noqa: F401

from transcribe import dialog


def run(coro):
    return asyncio.run(coro)


class FakeSocket:
    def __init__(self, frames):
        self.frames, self.sent, self.audio, self.closed = list(frames), [], [], None

    async def receive(self):
        await asyncio.sleep(0)
        return self.frames.pop(0) if self.frames else {"type": "websocket.disconnect"}

    async def send_json(self, data):
        self.sent.append(data)

    async def send_bytes(self, data):
        self.audio.append(data)

    async def close(self, code=1000):
        self.closed = code


def said(text):
    return NS(server_content=NS(interrupted=False, input_transcription=NS(text=text),
                                output_transcription=None, model_turn=None))


def spoke(text, audio=None):
    turn = NS(parts=[NS(inline_data=NS(data=audio))]) if audio else None
    return NS(server_content=NS(interrupted=False, input_transcription=None,
                                output_transcription=NS(text=text), model_turn=turn))


def interrupted():
    return NS(server_content=NS(interrupted=True, input_transcription=None,
                                output_transcription=None, model_turn=None))


class FakeSession:
    def __init__(self, on_audio=(), on_end=()):
        self.on_audio, self.on_end = list(on_audio), list(on_end)
        self.queue, self.audio, self.ended = asyncio.Queue(), [], False

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
    async def connect(system):
        if seen is not None:
            seen.append(system)
        yield session
    return connect


def test_a_spoken_turn_returns_audio_and_both_transcripts():
    session = FakeSession(on_audio=[said("what is article thirty four")],
                          on_end=[spoke("It catches measures with equivalent effect.", audio=b"PCM")])
    sock = FakeSocket([{"bytes": b"\x00" * 3200}, {"text": json.dumps({"stop": True})}])
    out = run(dialog.relay(sock, "system", connect=connector(session), sleep=lambda *_: asyncio.sleep(0)))

    assert sock.audio == [b"PCM"]                       # the tutor's voice reaches the browser as bytes
    assert {"said": "what is article thirty four"} in sock.sent
    assert {"spoke": "It catches measures with equivalent effect."} in sock.sent
    assert out["said"] == "what is article thirty four"
    assert out["spoke"] == "It catches measures with equivalent effect."
    assert out["error"] == "" and sock.closed == 1000
    assert session.ended


def test_an_interruption_is_forwarded_so_playback_can_stop():
    session = FakeSession(on_audio=[interrupted()])
    sock = FakeSocket([{"bytes": b"\x00" * 1600}, {"text": json.dumps({"stop": True})}])
    run(dialog.relay(sock, "system", connect=connector(session), sleep=lambda *_: asyncio.sleep(0)))
    assert {"interrupted": True} in sock.sent


def test_the_course_rules_and_excerpts_are_handed_to_the_session():
    seen = []
    session = FakeSession()
    sock = FakeSocket([{"text": json.dumps({"stop": True})}])
    run(dialog.relay(sock, "RULES and excerpts", connect=connector(session, seen), sleep=lambda *_: asyncio.sleep(0)))
    assert seen == ["RULES and excerpts"]


def test_vertex_refusing_is_one_message_not_a_traceback():
    @asynccontextmanager
    async def refuse(system):
        raise RuntimeError("quota")
        yield  # pragma: no cover

    sock = FakeSocket([{"bytes": b"\x00"}])
    out = run(dialog.relay(sock, "system", connect=refuse))
    assert out["error"].startswith("The spoken tutor is unavailable")
    assert sock.sent and "error" in sock.sent[-1] and sock.closed == 1011


def test_a_closed_tab_ends_the_session_without_an_error():
    session = FakeSession()
    sock = FakeSocket([{"bytes": b"\x00" * 3200}, {"type": "websocket.disconnect"}])
    out = run(dialog.relay(sock, "system", connect=connector(session), sleep=lambda *_: asyncio.sleep(0)))
    assert out["error"] == "" and out["seconds"] == 0.1


def test_it_stays_off_until_a_model_is_named(monkeypatch):
    """An invented model id would fail in the middle of a conversation, so an unset one keeps the
    feature dark and the page falls back to its own listen-answer loop."""
    monkeypatch.setattr(dialog, "MODEL", "")
    monkeypatch.setenv("GCP_PROJECT", "p")
    assert dialog.available() is False
    monkeypatch.setattr(dialog, "MODEL", "some-live-model")
    assert dialog.available() is True
    monkeypatch.setenv("VOICE_DIALOG", "off")
    assert dialog.available() is False
