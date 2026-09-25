"""The tutor names, under its answer, every citation it made that none of the ticked files contain.

An invented ECLI reads exactly like a real one, and commercial legal AI tools still invent 17-34% of theirs.
The check runs on the finished answer against the full text of the ticked files.
"""
import io
import json
import unittest.mock as mock

import run


def _ask(client, cid, answer):
    class FakeStream:
        text_stream = iter([answer])
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake = mock.MagicMock()
    fake.messages.stream.return_value = FakeStream()
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post(f"/api/courses/{cid}/chat", json={"message": "explain free movement", "mode": "explain"})
    assert r.status_code == 200 and "[DONE]" in r.text
    events = [json.loads(line[6:]) for line in r.text.split("\n\n") if line.startswith("data: {")]
    return next((e["unverified"] for e in events if "unverified" in e), None)


def _course_with_file(client, text):
    cid = client.post("/api/courses", json={"name": "Citation Check Law"}).json()["id"]
    client.post(f"/api/courses/{cid}/files", files={"file": ("wg3.txt", io.BytesIO(text.encode()), "text/plain")})
    return cid


def test_a_citation_missing_from_the_ticked_files_is_named(client):
    cid = _course_with_file(client, "Dassonville, Case 8/74, and Article 34 TFEU: the MEQR test.")
    assert _ask(client, cid, "Under Art. 34 TFEU, see C-999/21 and ECLI:EU:C:2099:1.") == ["C-999/21", "ECLI:EU:C:2099:1"]


def test_an_answer_citing_only_the_files_is_not_flagged(client):
    cid = _course_with_file(client, "Keck, C-267/91, narrowed Article 34 TFEU.")
    assert _ask(client, cid, "Keck (C-267/91) reads Art. 34 down to product rules.") is None


def test_with_nothing_ticked_nothing_is_flagged(client):
    cid = _course_with_file(client, "Keck, C-267/91.")
    for f in client.get(f"/api/courses/{cid}/files").json():
        client.post(f"/api/files/{f['id']}/toggle")
    assert _ask(client, cid, "See C-999/21.") is None
