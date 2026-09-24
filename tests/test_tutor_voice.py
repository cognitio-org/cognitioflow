"""Voice on: Claude opens with a short <speech> block the page speaks at once; the record keeps the written answer.

Until 2026-09-24 the page sent speech: true and the server ignored it, so a spoken reply waited for the
whole written answer and then read all of it aloud.
"""
import io
import json
import os
import unittest.mock as mock

import run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _chat(client, speech, answer="<speech>Direct effect needs a clear, precise, unconditional provision.</speech>"
                                  "**Van Gend en Loos** (Case 26/62) [LECTURE]"):
    cid = client.post("/api/courses", json={"name": "Voice Law"}).json()["id"]
    client.post(f"/api/courses/{cid}/files", files={"file": ("wg1.txt", io.BytesIO(b"Van Gend en Loos, Case 26/62."), "text/plain")})

    class FakeStream:
        text_stream = iter([answer[:20], answer[20:]])
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake = mock.MagicMock()
    fake.messages.stream.return_value = FakeStream()
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post(f"/api/courses/{cid}/chat", json={"message": "direct effect?", "mode": "explain", "speech": speech})
    assert r.status_code == 200 and "[DONE]" in r.text
    return cid, fake.messages.stream.call_args.kwargs["system"], r.text


def test_voice_on_asks_for_a_spoken_opening_after_the_cached_blocks(client):
    _, system, _ = _chat(client, speech=True)
    assert system[-1]["text"] == run.VOICE_RULE and "cache_control" not in system[-1]
    assert any("cache_control" in b for b in system[:-1])   # the file cache still sits before it


def test_voice_off_sends_no_voice_rule(client):
    _, system, _ = _chat(client, speech=False)
    assert all(b["text"] != run.VOICE_RULE for b in system)


def test_the_spoken_part_streams_to_the_page_but_is_not_kept_in_the_record(client):
    cid, _, body = _chat(client, speech=True)
    streamed = "".join(json.loads(l[6:]).get("t", "") for l in body.split("\n\n") if l.startswith("data: {"))
    assert "<speech>" in streamed
    saved = [m["content"] for m in client.get(f"/api/courses/{cid}/messages").json() if m["role"] == "assistant"]
    assert saved == ["**Van Gend en Loos** (Case 26/62) [LECTURE]"]


def test_voice_sockets_are_allowed_an_hour_on_cloud_run():
    # WebSockets obey the service request timeout, which defaults to 5 minutes; dictation expects 9.5 and the live tutor 14
    with open(os.path.join(ROOT, ".github", "workflows", "deploy.yml")) as f:
        assert "--timeout 3600" in f.read()


def _model_used(client, speech, model):
    cid = client.post("/api/courses", json={"name": "Voice Model Law"}).json()["id"]

    class FakeStream:
        text_stream = iter(["<speech>Yes.</speech>ok"])
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake = mock.MagicMock()
    fake.messages.stream.return_value = FakeStream()
    with mock.patch.object(run, "client", return_value=fake):
        client.post(f"/api/courses/{cid}/chat", json={"message": "primacy?", "mode": "explain", "speech": speech, "model": model})
    return fake.messages.stream.call_args.kwargs["model"]


def test_a_spoken_turn_on_auto_uses_the_fast_model(client):
    # measured on the live site: Sonnet's spoken part was ready at 16 s cold, Haiku's at 2.0 s
    assert _model_used(client, True, "auto") == run.llm.resolve(run.CHEAP_MODEL)


def test_a_model_he_picks_still_wins_and_typed_turns_are_unchanged(client):
    assert _model_used(client, True, run.MODEL) == run.llm.resolve(run.MODEL)
    assert _model_used(client, False, "auto") == run.llm.resolve(run.pick_model("explain", "auto", "primacy?"))


def test_the_conversation_so_far_is_cached(client):
    cid, _, _ = _chat(client, speech=True)

    class FakeStream:
        text_stream = iter(["again"])
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake = mock.MagicMock()
    fake.messages.stream.return_value = FakeStream()
    with mock.patch.object(run, "client", return_value=fake):
        client.post(f"/api/courses/{cid}/chat", json={"message": "and primacy?", "mode": "explain"})
    msgs = fake.messages.stream.call_args.kwargs["messages"]
    assert msgs[-2]["content"][0]["cache_control"] == {"type": "ephemeral"}   # the last message before this question
    assert isinstance(msgs[-1]["content"], str)


def test_the_deployed_voice_is_google_and_its_library_ships():
    # Edge TTS is unofficial and measured 1.4-2 s a sentence from europe-west4; Chirp 3 HD measured 0.8-1 s.
    # Without the library the google backend raises on import, say() swallows it, and he hears the robot voice.
    with open(os.path.join(ROOT, ".github", "workflows", "deploy.yml")) as f:
        assert "TTS=google" in f.read()
    with open(os.path.join(ROOT, "requirements.txt")) as f:
        assert "google-cloud-texttospeech" in f.read()
