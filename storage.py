"""
Storage seam — the only module that touches the bytes of user content (uploaded files, lecture audio).

Backend is chosen by STORAGE:
  local  files under STORAGE_LOCAL_ROOT (default ./data), same key layout as the bucket
  gcs    GCS_BUCKET via Application Default Credentials; STORAGE_EMULATOR_HOST points it at fake-gcs

Key layout: courses/{cid}/files/{fid}/{name} and notes/{nid}/audio/{rid}.webm.
run.py never builds a filesystem path to user content and never imports google.cloud.storage.
"""
import datetime
import os
import re
import shutil
from pathlib import Path
from typing import BinaryIO, Iterator, Optional, Union
from urllib.parse import quote

CHUNK = 1024 * 1024
Data = Union[bytes, BinaryIO]


class NotFound(Exception):
    """No object under this key (or the key is not a valid storage key)."""


def safe_name(name: str, limit: int = 180) -> str:
    """Turn a user-supplied filename or title into one key segment: no separators, control chars or leading dots."""
    s = re.sub(r"[\x00-\x1f/\\]+", "_", name or "").strip().lstrip(".").strip()
    if len(s) > limit:
        stem, dot, ext = s.rpartition(".")
        s = (stem[: limit - len(ext) - 1] + "." + ext) if dot and len(ext) <= 10 else s[:limit]
    return s or "file"


def content_disposition(filename: str) -> str:
    """attachment header that survives non-ASCII names and can't smuggle header breaks."""
    plain = re.sub(r'[\x00-\x1f"\\]', "", filename.encode("ascii", "ignore").decode()) or "download"
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(filename)}"


def _read_range(f: BinaryIO, start: int, end: Optional[int]) -> Iterator[bytes]:
    with f:
        f.seek(start)
        left = None if end is None else end - start + 1
        while left is None or left > 0:
            b = f.read(CHUNK if left is None else min(CHUNK, left))
            if not b:
                break
            if left is not None:
                left -= len(b)
            yield b


class LocalStorage:
    def __init__(self, root: Union[str, Path]):
        self.root = Path(root).expanduser().resolve()

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not key or key.startswith("/") or self.root not in p.parents:
            raise NotFound(key)
        return p

    def put(self, key: str, data: Data, content_type: str = "application/octet-stream") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        with open(tmp, "wb") as f:
            if isinstance(data, (bytes, bytearray, memoryview)):
                f.write(data)
            else:
                shutil.copyfileobj(data, f, CHUNK)
        os.replace(tmp, p)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            raise NotFound(key)

    def size(self, key: str) -> int:
        p = self._path(key)
        if not p.is_file():
            raise NotFound(key)
        return p.stat().st_size

    def stream(self, key: str, start: int = 0, end: Optional[int] = None) -> Iterator[bytes]:
        """Chunks of the object from byte `start` to `end` inclusive. Opens eagerly so a missing key fails before any response starts."""
        try:
            f = open(self._path(key), "rb")
        except (FileNotFoundError, IsADirectoryError):
            raise NotFound(key)
        return _read_range(f, start, end)

    def url(self, key: str, expires_s: int = 3600, filename: Optional[str] = None,
            content_type: Optional[str] = None) -> Optional[str]:
        return None  # nothing to sign locally; the app streams the object itself

    def delete(self, key: str) -> None:
        try:
            p = self._path(key)
        except NotFound:
            return
        p.unlink(missing_ok=True)
        d = p.parent  # prune empty key folders so deletes don't leave a trail of directories
        while d != self.root and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            d = d.parent

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).is_file()
        except NotFound:
            return False


class GCSStorage:
    def __init__(self, bucket: str, project: Optional[str] = None):
        from google.cloud import storage as gcs
        self.emulated = bool(os.environ.get("STORAGE_EMULATOR_HOST"))
        self.client = gcs.Client(project=project)
        self.bucket = self.client.bucket(bucket)
        self._creds = None

    def put(self, key: str, data: Data, content_type: str = "application/octet-stream") -> None:
        blob = self.bucket.blob(key)
        if isinstance(data, (bytes, bytearray, memoryview)):
            blob.upload_from_string(bytes(data), content_type=content_type)
        else:
            blob.upload_from_file(data, content_type=content_type)

    def get(self, key: str) -> bytes:
        from google.api_core.exceptions import NotFound as GoogleNotFound
        try:
            return self.bucket.blob(key).download_as_bytes()
        except GoogleNotFound:
            raise NotFound(key)

    def size(self, key: str) -> int:
        blob = self.bucket.get_blob(key)
        if blob is None:
            raise NotFound(key)
        return blob.size

    def stream(self, key: str, start: int = 0, end: Optional[int] = None) -> Iterator[bytes]:
        size = self.size(key)  # raises NotFound before any bytes are promised
        end = size - 1 if end is None else min(end, size - 1)
        blob = self.bucket.blob(key)

        def chunks():
            pos = start
            while pos <= end:
                stop = min(pos + CHUNK - 1, end)
                yield blob.download_as_bytes(start=pos, end=stop)
                pos = stop + 1
        return chunks()

    def url(self, key: str, expires_s: int = 3600, filename: Optional[str] = None,
            content_type: Optional[str] = None) -> Optional[str]:
        """V4 signed GET URL, signed through the IAM signBlob API as the ADC service account —
        Cloud Run's SA in cloud; locally `gcloud auth application-default login --impersonate-service-account …`."""
        if self.emulated:
            return None  # fake-gcs can't verify signatures; the app streams instead
        import google.auth
        from google.auth.transport.requests import Request
        if self._creds is None:
            self._creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not self._creds.valid:
            self._creds.refresh(Request())
        sa = getattr(self._creds, "service_account_email", None)
        if not sa or sa == "default":
            raise RuntimeError("Signed URLs need a service-account identity. Locally run: gcloud auth application-default login "
                               "--impersonate-service-account cognitioflow-run@<project>.iam.gserviceaccount.com")
        extra = {}
        if filename:
            extra["response_disposition"] = content_disposition(filename)
        if content_type:
            extra["response_type"] = content_type
        return self.bucket.blob(key).generate_signed_url(
            version="v4", expiration=datetime.timedelta(seconds=expires_s), method="GET",
            service_account_email=sa, access_token=self._creds.token, **extra)

    def delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound as GoogleNotFound
        try:
            self.bucket.blob(key).delete()
        except GoogleNotFound:
            pass

    def exists(self, key: str) -> bool:
        return self.bucket.blob(key).exists()


_backend = None


def backend():
    """The configured backend, built from STORAGE on first use."""
    global _backend
    if _backend is None:
        kind = os.environ.get("STORAGE", "local")
        if kind == "local":
            _backend = LocalStorage(os.environ.get("STORAGE_LOCAL_ROOT", "./data"))
        elif kind == "gcs":
            if not os.environ.get("GCS_BUCKET"):
                raise RuntimeError("STORAGE=gcs needs GCS_BUCKET")
            _backend = GCSStorage(os.environ["GCS_BUCKET"], os.environ.get("GCP_PROJECT"))
        else:
            raise RuntimeError(f"Unknown STORAGE={kind!r} (expected local or gcs)")
    return _backend


def reset() -> None:
    """Forget the cached backend so the next call re-reads the environment (tests)."""
    global _backend
    _backend = None


def put(key: str, data: Data, content_type: str = "application/octet-stream") -> None:
    backend().put(key, data, content_type)


def get(key: str) -> bytes:
    return backend().get(key)


def size(key: str) -> int:
    return backend().size(key)


def stream(key: str, start: int = 0, end: Optional[int] = None) -> Iterator[bytes]:
    return backend().stream(key, start, end)


def url(key: str, expires_s: int = 3600, filename: Optional[str] = None, content_type: Optional[str] = None) -> Optional[str]:
    """Signed URL on real GCS; None when the app should stream the object itself (local, emulator)."""
    return backend().url(key, expires_s, filename, content_type)


def delete(key: str) -> None:
    backend().delete(key)


def exists(key: str) -> bool:
    return backend().exists(key)
