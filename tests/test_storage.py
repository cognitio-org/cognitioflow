"""Tests: storage.py seam — local backend always, GCS backend when the fake-gcs emulator is running."""
import io
import os

import pytest

import storage


@pytest.fixture(params=["local", "gcs"])
def backend(request, tmp_path):
    if request.param == "local":
        return storage.LocalStorage(tmp_path)
    if not os.environ.get("STORAGE_EMULATOR_HOST"):
        pytest.skip("fake-gcs not configured (docker compose --profile gcs up -d, STORAGE_EMULATOR_HOST=http://localhost:4443)")
    b = storage.GCSStorage("cf-test-unit")
    if not b.bucket.exists():
        b.client.create_bucket(b.bucket.name)
    return b


def test_put_get_exists_size(backend):
    key = "courses/c1/files/f1/week 1 — slides.pdf"
    backend.put(key, b"%PDF-bytes", "application/pdf")
    assert backend.exists(key)
    assert backend.get(key) == b"%PDF-bytes"
    assert backend.size(key) == len(b"%PDF-bytes")


def test_put_file_object(backend):
    backend.put("notes/n1/audio/r1.webm", io.BytesIO(b"x" * 3000), "audio/webm")
    assert backend.get("notes/n1/audio/r1.webm") == b"x" * 3000


def test_stream_full_and_range(backend):
    data = bytes(range(256)) * 10
    backend.put("k/range.bin", data)
    assert b"".join(backend.stream("k/range.bin")) == data
    assert b"".join(backend.stream("k/range.bin", 10, 19)) == data[10:20]
    assert b"".join(backend.stream("k/range.bin", 2550)) == data[2550:]


def test_missing_key_raises_not_found(backend):
    with pytest.raises(storage.NotFound):
        backend.get("nope/missing")
    with pytest.raises(storage.NotFound):
        backend.stream("nope/missing")  # before iteration, so no response has started
    with pytest.raises(storage.NotFound):
        backend.size("nope/missing")
    assert not backend.exists("nope/missing")


def test_delete_is_idempotent(backend):
    backend.put("k/del.txt", b"bye")
    backend.delete("k/del.txt")
    backend.delete("k/del.txt")
    assert not backend.exists("k/del.txt")


@pytest.mark.parametrize("key", ["../escape.txt", "courses/../../escape.txt", "/etc/passwd", ""])
def test_local_rejects_keys_outside_root(tmp_path, key):
    s = storage.LocalStorage(tmp_path / "root")
    with pytest.raises(storage.NotFound):
        s.put(key, b"x")
    assert not s.exists(key)
    s.delete(key)  # no-op, never touches anything outside the root


def test_local_delete_prunes_empty_folders(tmp_path):
    s = storage.LocalStorage(tmp_path)
    s.put("courses/c1/files/f1/a.txt", b"a")
    s.delete("courses/c1/files/f1/a.txt")
    assert list(tmp_path.iterdir()) == []


def test_local_url_is_none(tmp_path):
    assert storage.LocalStorage(tmp_path).url("courses/c/files/f/a.pdf") is None


def test_safe_name():
    escaped = storage.safe_name("../../etc/passwd")
    assert "/" not in escaped and not escaped.startswith(".")
    assert storage.safe_name("Week 2 – Schütze.pdf") == "Week 2 – Schütze.pdf"
    assert storage.safe_name("") == "file"
    assert storage.safe_name(".hidden") == "hidden"
    long = storage.safe_name("a" * 300 + ".pptx")
    assert len(long) <= 180 and long.endswith(".pptx")


def test_content_disposition_handles_unicode_and_header_breaks():
    h = storage.content_disposition('Schütze "ch 3"\r\nX-Evil: 1.pdf')
    assert "\r" not in h and "\n" not in h
    assert "filename*=UTF-8''Sch%C3%BCtze" in h


def test_backend_selection(monkeypatch):
    try:
        monkeypatch.setenv("STORAGE", "bogus"); storage.reset()
        with pytest.raises(RuntimeError):
            storage.backend()
        monkeypatch.setenv("STORAGE", "gcs"); monkeypatch.delenv("GCS_BUCKET", raising=False); storage.reset()
        with pytest.raises(RuntimeError):
            storage.backend()
    finally:
        monkeypatch.undo(); storage.reset()
