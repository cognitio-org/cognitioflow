"""
pg_dump / pg_restore at a version that can read the server.

The local binary is used when its major version is new enough; otherwise the tool runs from the postgres image
(CF_PG_IMAGE, default postgres:18) through Docker, with the work folder mounted at /work and localhost rewritten to
host.docker.internal. Error messages never contain the connection string.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

IMAGE = os.environ.get("CF_PG_IMAGE", "postgres:18")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_DOCKER_FALLBACK = "/Applications/Docker.app/Contents/Resources/bin/docker"


def major(version_text: str) -> int:
    m = re.search(r"(\d+)(?:\.\d+)?", version_text or "")
    return int(m.group(1)) if m else 0


def local_major(tool: str) -> int:
    path = shutil.which(tool)
    if not path:
        return 0
    try:
        return major(subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20).stdout)
    except (OSError, subprocess.SubprocessError):
        return 0


def docker() -> str:
    return shutil.which("docker") or (_DOCKER_FALLBACK if os.path.exists(_DOCKER_FALLBACK) else "")


def available(tool: str, need_major: int) -> bool:
    return local_major(tool) >= need_major or bool(docker())


def _docker_url(url: str) -> str:
    parts = urlsplit(url)
    userinfo, at, hostport = parts.netloc.rpartition("@")
    host, sep, port = hostport.partition(":")
    if host in _LOCAL_HOSTS:
        hostport = "host.docker.internal" + sep + port
    return urlunsplit(parts._replace(netloc=userinfo + at + hostport))


def command(tool: str, need_major: int, args, url: str, workdir, connect: bool = True) -> list:
    """argv for `tool args --dbname=url` (no --dbname when connect is False); "{work}" in args is workdir (/work under Docker)."""
    workdir = str(Path(workdir).resolve())
    if 0 < local_major(tool) and local_major(tool) >= need_major:
        return [shutil.which(tool), *[a.replace("{work}", workdir) for a in args], *([f"--dbname={url}"] if connect else [])]
    d = docker()
    if not d:
        raise RuntimeError(f"{tool} {need_major}+ is not installed and Docker is not available to run {IMAGE}")
    uid = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "0:0"
    return [d, "run", "--rm", "--user", uid, "--add-host=host.docker.internal:host-gateway", "-v", f"{workdir}:/work",
            IMAGE, tool, *[a.replace("{work}", "/work") for a in args], *([f"--dbname={_docker_url(url)}"] if connect else [])]


def run(tool: str, need_major: int, args, url: str, workdir, connect: bool = True) -> str:
    argv = command(tool, need_major, args, url, workdir, connect)
    done = subprocess.run(argv, capture_output=True, text=True)
    if done.returncode != 0:
        scrub = lambda s: (s or "").replace(url, "<database-url>").replace(_docker_url(url), "<database-url>")
        raise RuntimeError(f"{tool} failed (exit {done.returncode}): {scrub(done.stderr).strip()[-800:]}")
    return done.stdout


def version(tool: str, need_major: int) -> str:
    """Version line of the tool that command() would run."""
    if 0 < local_major(tool) and local_major(tool) >= need_major:
        return subprocess.run([shutil.which(tool), "--version"], capture_output=True, text=True).stdout.strip()
    return subprocess.run([docker(), "run", "--rm", IMAGE, tool, "--version"], capture_output=True, text=True).stdout.strip()
