"""Run the game-studio quality-gate test scripts as part of `make test`, so CI gates on them.

`make test` (and so the `fast` CI job that automerge waits on) only collects `tests/`. The studio
gate tests live beside their code in `studio/gates/test_*.py` and `studio/test_runtime.py`, and are
plain scripts with their own runner (a `main()`, `if __name__ == "__main__"` block, or a bare call
at import time). Until this file, nothing on GitHub ran them: they passed only because agents ran
them by hand. Once a gate is wired to the real game writer, a broken gate would merge silently.

Each script runs exactly as it would by hand (`python studio/gates/test_x.py` from the repo root):
a subprocess with this interpreter, cwd at the repo root, and a per-file timeout. Exit code 0 is a
pass; anything else fails that one parametrised test and prints the script's output. Discovery is a
glob, so a new `studio/**/test_*.py` script is picked up with no edit here.

All of them are stdlib-only and offline (test_runtime.py talks to a fake server it starts on
127.0.0.1). None needs network, the M4, a browser or secrets, so nothing is skipped. If a future
script does, add it to SKIP with the reason rather than letting it flake.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "studio"
TIMEOUT_S = 120

SCRIPTS = sorted(p for p in STUDIO.rglob("test_*.py") if "__pycache__" not in p.parts)

# repo-relative path -> reason. Empty: every script is hermetic today.
SKIP: dict[str, str] = {}


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _child_env() -> dict:
    """The parent env minus the studio's M4 endpoint/model overrides, so a developer shell that points
    CF_STUDIO_* at the real M4 can never make these tests reach it. PYTHONDONTWRITEBYTECODE keeps
    __pycache__ out of studio/; PYTHONUNBUFFERED makes a timed-out script show how far it got."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CF_STUDIO_") and k not in ("PYTHONOPTIMIZE", "PYTHONINSPECT")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def test_studio_scripts_discovered():
    """Guard the glob: if studio/ moves or is renamed, this fails instead of the suite going quietly empty."""
    assert any(p.parent == STUDIO / "gates" for p in SCRIPTS), f"no studio/gates/test_*.py found under {STUDIO}"
    assert (STUDIO / "test_runtime.py") in SCRIPTS, f"studio/test_runtime.py not found under {STUDIO}"


@pytest.mark.parametrize("script", SCRIPTS, ids=_rel)
def test_studio_script(script: Path):
    rel = _rel(script)
    if rel in SKIP:
        pytest.skip(SKIP[rel])
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            env=_child_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as e:
        out = e.output.decode(errors="replace") if isinstance(e.output, bytes) else (e.output or "")
        pytest.fail(f"{rel} did not finish within {TIMEOUT_S}s. Output so far:\n{out}", pytrace=False)
    if proc.returncode != 0:
        pytest.fail(f"{rel} exited {proc.returncode}. Output:\n{proc.stdout}", pytrace=False)
