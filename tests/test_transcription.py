"""Tests: Phase 3 — transcription as a durable job in the jobs table; the provider is mocked."""
import io
import re
import types
from datetime import timedelta

import pytest
from google.api_core import exceptions as gexc
from google.cloud.speech_v2 import types as st
from google.longrunning import operations_pb2
from google.rpc import status_pb2

import transcribe
from transcribe import ProviderError
from transcribe.providers import google as g


def _recording(client, audio=b"webm-bytes"):
    cid = client.get("/api/courses").json()[0]["id"]
    nid = client.post(f"/api/courses/{cid}/notes", json={"title": "Lecture 4", "body": "# Lecture 4\nBase notes"}).json()["id"]
    rid = client.post(f"/api/notes/{nid}/recordings/start").json()["id"]
    r = client.post(f"/api/recordings/{rid}/finish", files={"audio": ("r.webm", io.BytesIO(audio), "audio/webm")}, data={"seconds": "75", "auto": "0"})
    assert r.status_code == 200, r.text
    return nid, rid


class FakeProvider:
    def __init__(self):
        self.submits, self.polls, self.script = [], 0, []

    def check_ready(self):
        pass

    def submit(self, key, language):
        self.submits.append((key, language))
        return f"op-{len(self.submits)}"

    def poll(self, op):
        self.polls += 1
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def provider(monkeypatch):
    fp = FakeProvider()
    monkeypatch.setattr(transcribe, "_provider", lambda: fp)
    return fp


# ---------------------------------------------------------------- formatting
def test_format_capture_matches_the_laptop_build():
    segs = [{"start": 5.9, "text": " The Court held "}, {"start": 3725.2, "text": "Keck."}]
    old = "\n".join(f"[{int(s['start'])//60:02d}:{int(s['start'])%60:02d}] {s['text'].strip()} <!--r:r1:{int(s['start'])}-->" for s in segs)
    assert transcribe.format_capture(segs, "r1") == old == "[00:05] The Court held <!--r:r1:5-->\n[62:05] Keck. <!--r:r1:3725-->"


def test_group_words_splits_on_sentences_and_every_30_seconds():
    words = [(0.0, "The"), (0.4, "Court"), (0.8, "held."), (1.2, "Then"), (10.0, "a"), (31.5, "long"), (32.0, "clause")]
    assert transcribe.group_words(words) == [{"start": 0.0, "text": "The Court held."}, {"start": 1.2, "text": "Then a long"}, {"start": 32.0, "text": "clause"}]


# ---------------------------------------------------------------- job flow
def test_double_post_returns_the_same_job(client, provider):
    nid, rid = _recording(client)
    a = client.post(f"/api/recordings/{rid}/transcribe").json()
    b = client.post(f"/api/recordings/{rid}/transcribe").json()
    assert a["id"] == b["id"] and a["status"] == "running" and a["executor"] == "hosted"
    assert provider.submits == [(f"notes/{nid}/audio/{rid}.webm", "en-GB")]


def test_poll_state_machine_appends_exactly_one_block(client, provider, pg, monkeypatch):
    import run
    monkeypatch.setattr(run, "clean_text", lambda cid, text: text.replace("Keck", "*Keck*"))
    nid, rid = _recording(client)
    provider.script = [("running", None, ""),
                       ("done", [{"start": 1.2, "text": "Keck narrows Dassonville."}, {"start": 65.0, "text": "Selling arrangements."}], "en-gb")]
    client.post(f"/api/recordings/{rid}/transcribe")
    assert pg.execute("SELECT status FROM jobs WHERE ref_id=%s", (rid,)).fetchone()[0] == "submitted"
    s1 = client.get(f"/api/recordings/{rid}/transcribe").json()
    assert (s1["status"], s1["stage"]) == ("running", "transcribing")
    assert pg.execute("SELECT status FROM jobs WHERE ref_id=%s", (rid,)).fetchone()[0] == "running"
    s2 = client.get(f"/api/recordings/{rid}/transcribe").json()
    assert s2["status"] == "done" and s2["cleaned"] is True and s2["language"] == "en-gb" and s2.get("collected") is True
    body = client.get(f"/api/notes/{nid}").json()["body"]
    assert re.fullmatch(r"# Lecture 4\nBase notes\n\n## Live capture — transcript \d{2} \w{3} \d{2}:\d{2} \(cleaned\)\n"
                        rf"\[00:01\] \*Keck\* narrows Dassonville\. <!--r:{rid}:1-->\n\[01:05\] Selling arrangements\. <!--r:{rid}:65-->", body), body
    s3 = client.get(f"/api/recordings/{rid}/transcribe").json()
    assert s3["status"] == "done" and provider.polls == 2 and "collected" not in s3  # only the collecting request says so
    assert client.get(f"/api/notes/{nid}").json()["body"].count("## Live capture") == 1


def test_uncleaned_header_when_auto_clean_is_off(client, provider, monkeypatch):
    monkeypatch.setenv("CF_AUTO_CLEAN", "0")
    nid, rid = _recording(client)
    provider.script = [("done", [{"start": 0.0, "text": "Hello."}], "en-gb")]
    client.post(f"/api/recordings/{rid}/transcribe")
    assert client.get(f"/api/recordings/{rid}/transcribe").json()["cleaned"] is False
    body = client.get(f"/api/notes/{nid}").json()["body"]
    assert re.search(r"## Live capture — transcript \d{2} \w{3} \d{2}:\d{2}\n\[00:00\] Hello\. <!--r:", body) and "(cleaned)" not in body


def test_provider_error_fails_then_retries_until_the_fourth_is_refused(client, provider):
    nid, rid = _recording(client)
    client.post(f"/api/recordings/{rid}/transcribe")
    for attempt in (1, 2, 3):
        provider.script = [ProviderError("Speech-to-Text permission denied: speech.client revoked")]
        s = client.get(f"/api/recordings/{rid}/transcribe").json()
        assert s["status"] == "failed" and "permission denied" in s["error"] and s["attempts"] == attempt
        r = client.post(f"/api/recordings/{rid}/transcribe?retry=1")
        if attempt < 3:
            assert r.status_code == 200 and r.json()["attempts"] == attempt + 1 and r.json()["status"] == "running"
    assert r.status_code == 409 and "failed 3 times" in r.json()["detail"]
    assert len(provider.submits) == 3


def test_transient_poll_error_leaves_the_job_running(client, provider, pg):
    nid, rid = _recording(client)
    provider.script = [RuntimeError("connection reset"), ("running", None, "")]
    client.post(f"/api/recordings/{rid}/transcribe")
    assert client.get(f"/api/recordings/{rid}/transcribe").json()["status"] == "running"
    assert client.get(f"/api/recordings/{rid}/transcribe").json()["status"] == "running"
    assert pg.execute("SELECT status, error FROM jobs WHERE ref_id=%s", (rid,)).fetchone() == ("running", "")


def test_operation_failure_is_recorded(client, provider):
    nid, rid = _recording(client)
    provider.script = [("failed", None, "Speech-to-Text error: audio too short")]
    client.post(f"/api/recordings/{rid}/transcribe")
    s = client.get(f"/api/recordings/{rid}/transcribe").json()
    assert s["status"] == "failed" and s["error"] == "Speech-to-Text error: audio too short"


def test_finish_is_claimed_once(client, provider, monkeypatch):
    import run
    monkeypatch.setenv("CF_AUTO_CLEAN", "0")
    nid, rid = _recording(client)
    client.post(f"/api/recordings/{rid}/transcribe")
    job = run._latest_job(rid)
    segs = [{"start": 3.0, "text": "Once."}]
    run._finish_transcription(job, segs, "en-gb")
    run._finish_transcription(job, segs, "en-gb")  # a second, overlapping poll
    assert client.get(f"/api/notes/{nid}").json()["body"].count("## Live capture") == 1


def test_a_stale_finishing_job_is_collected_again(client, provider, pg, monkeypatch):
    monkeypatch.setenv("CF_AUTO_CLEAN", "0")
    nid, rid = _recording(client)
    client.post(f"/api/recordings/{rid}/transcribe")
    pg.execute("UPDATE jobs SET status='finishing', updated=0 WHERE ref_id=%s", (rid,)); pg.commit()
    provider.script = [("done", [{"start": 0.0, "text": "Recovered."}], "en-gb")]
    assert client.get(f"/api/recordings/{rid}/transcribe").json()["status"] == "done"
    assert "Recovered." in client.get(f"/api/notes/{nid}").json()["body"]


def test_without_the_real_bucket_transcribe_is_a_clear_400(client):
    nid, rid = _recording(client)
    r = client.post(f"/api/recordings/{rid}/transcribe")
    assert r.status_code == 400 and ("STORAGE=gcs" in r.json()["detail"] or "emulator" in r.json()["detail"])
    rid2 = client.post(f"/api/notes/{nid}/recordings/start").json()["id"]
    r = client.post(f"/api/recordings/{rid2}/finish", files={"audio": ("r.webm", io.BytesIO(b"x"), "audio/webm")}, data={"auto": "1"})
    assert r.status_code == 200 and r.json()["transcribing"] is False  # the recording is still saved


# ---------------------------------------------------------------- Google provider (client mocked)
def _op_done(resp):
    op = operations_pb2.Operation(name="op", done=True)
    op.response.Pack(st.BatchRecognizeResponse.pb(resp))
    return op


def test_google_submit_builds_a_chirp2_batch_request(monkeypatch):
    for k, v in {"STORAGE": "gcs", "GCS_BUCKET": "cognitioflow-user-content", "GCP_PROJECT": "proj"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("STORAGE_EMULATOR_HOST", raising=False); monkeypatch.delenv("STT_REGION", raising=False)
    seen = {}
    class Client:
        def batch_recognize(self, request):
            seen["r"] = request
            return types.SimpleNamespace(operation=types.SimpleNamespace(name="projects/proj/locations/europe-west4/operations/123"))
    monkeypatch.setattr(g, "client", lambda: Client())
    assert g.submit("notes/n/audio/r.webm", "en-GB") == "projects/proj/locations/europe-west4/operations/123"
    r = seen["r"]; pb = st.BatchRecognizeRequest.pb(r)
    assert r.recognizer == "projects/proj/locations/europe-west4/recognizers/_"
    assert r.config.model == "chirp_2" and list(r.config.language_codes) == ["en-GB"]
    assert r.config.features.enable_word_time_offsets and r.config.features.enable_automatic_punctuation
    assert pb.config.HasField("auto_decoding_config") and pb.recognition_output_config.HasField("inline_response_config")
    assert r.files[0].uri == "gs://cognitioflow-user-content/notes/n/audio/r.webm"


def test_google_poll_maps_words_to_segments(monkeypatch):
    word = lambda w, s: st.WordInfo(word=w, start_offset=timedelta(seconds=s))
    resp = st.BatchRecognizeResponse(results={"gs://b/k": st.BatchRecognizeFileResult(inline_result=st.InlineResult(transcript=st.BatchRecognizeResults(results=[
        st.SpeechRecognitionResult(language_code="en-gb", result_end_offset=timedelta(seconds=5), alternatives=[
            st.SpeechRecognitionAlternative(transcript="The Court held. Keck", words=[word("The", 0.5), word("Court", 0.9), word("held.", 1.3), word("Keck", 2.0)])])])))})
    monkeypatch.setattr(g, "client", lambda: types.SimpleNamespace(get_operation=lambda request: _op_done(resp)))
    assert g.poll("op") == ("done", [{"start": 0.5, "text": "The Court held."}, {"start": 2.0, "text": "Keck"}], "en-gb")


def test_google_poll_running_file_error_and_permission_denied(monkeypatch):
    running = operations_pb2.Operation(name="op", done=False)
    monkeypatch.setattr(g, "client", lambda: types.SimpleNamespace(get_operation=lambda request: running))
    assert g.poll("op") == ("running", None, "")
    bad = st.BatchRecognizeResponse(results={"gs://b/k": st.BatchRecognizeFileResult(error=status_pb2.Status(code=3, message="Audio too short"))})
    monkeypatch.setattr(g, "client", lambda: types.SimpleNamespace(get_operation=lambda request: _op_done(bad)))
    state, segs, detail = g.poll("op")
    assert state == "failed" and segs is None and "Audio too short" in detail
    def denied(request):
        raise gexc.PermissionDenied("Permission 'speech.operations.get' denied")
    monkeypatch.setattr(g, "client", lambda: types.SimpleNamespace(get_operation=denied))
    with pytest.raises(ProviderError, match="permission denied"):
        g.poll("op")


def test_google_check_ready_needs_the_real_bucket(monkeypatch):
    monkeypatch.setenv("STORAGE", "local")
    with pytest.raises(ProviderError, match="STORAGE=gcs"):
        g.check_ready()
    monkeypatch.setenv("STORAGE", "gcs"); monkeypatch.setenv("GCS_BUCKET", "b"); monkeypatch.setenv("STORAGE_EMULATOR_HOST", "http://localhost:4443")
    with pytest.raises(ProviderError, match="emulator"):
        g.check_ready()
