"""Tests for studio/runtime.py (slice S5) — stdlib only, no network beyond 127.0.0.1.

Run:  python3 studio/test_runtime.py      (or: python3 -m pytest -q studio/test_runtime.py)

A fake OpenAI-compatible server on 127.0.0.1:<ephemeral> plays every reply shape the real
M4 servers can produce, so the refusal, timeout and fail-closed paths are exercised for real.
"""
import base64
import json
import os
import socket
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir))
sys.path.insert(0, os.path.join(HERE, "gates"))

from studio import runtime  # noqa: E402
from studio.runtime import GateConfigError, GateInfraError, m4_reviewer, m4_vlm  # noqa: E402
import aesthetic_judge  # noqa: E402

# 1x1 transparent PNG
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


def _reply(content, finish="stop", model="mlx-community/Qwen3-30B-A3B-Thinking-2507-4bit"):
    return {"model": model, "choices": [{"index": 0, "finish_reason": finish,
                                         "message": {"role": "assistant", "content": content}}]}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep test output clean
        pass

    def do_POST(self):
        srv = self.server
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        srv.requests.append((self.path, json.loads(body or b"{}")))
        mode = self.path.split("/")[1]       # /<mode>/v1/chat/completions
        if mode == "slow":
            time.sleep(1.5)
            return self._json(_reply('{"ok": true, "issues": []}'))
        if mode == "e500":
            self.send_response(500); self.end_headers(); self.wfile.write(b'{"error": "generation thread died"}')
            return
        if mode == "garbage":
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
            self.wfile.write(b"<html>not json</html>")
            return
        if mode == "redirect":
            self.send_response(302); self.send_header("Location", "http://evil.example/v1/chat/completions")
            self.end_headers()
            return
        replies = {
            "ok": _reply('{"ok": true, "issues": []}'),
            "think": _reply('<think>scratch: {"ok": true, "issues": []}</think>\n{"ok": false, "issues": ["x"]}'),
            "orphan_close": _reply('scratch: {"ok": true, "issues": []}\n</think>\n\n{"ok": false, "issues": ["y"]}'),
            "length": _reply('{"ok": tr', finish="length"),
            "unterminated": _reply('<think>{"ok": true, "issues": []} still thinking'),
            "reasoning_only": {"model": "m", "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": None, "reasoning_content": '{"ok": true, "issues": []}'}}]},
            "nochoices": {"model": "m", "choices": []},
            "claude": _reply('{"ok": true, "issues": []}', model="claude-x"),
            "vlm": _reply('{"score": 0.8, "notes": "ok"}', model="mlx-community/Qwen2.5-VL-7B-Instruct-4bit"),
        }
        self._json(replies.get(mode, _reply("unknown mode")))

    def _json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


@contextmanager
def fake_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    srv.requests = []
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown(); srv.server_close()


@contextmanager
def env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    except Exception as e:  # noqa: BLE001
        raise AssertionError(f"expected {exc.__name__}, got {type(e).__name__}: {e}")
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


# ------------------------------------------------------------------------------------------ tests

def test_error_types_are_distinct():
    assert not issubclass(GateConfigError, GateInfraError)
    assert not issubclass(GateInfraError, GateConfigError)
    print("  error types distinct: PASS")


def test_reviewer_happy_path_and_request_shape():
    with fake_server() as (srv, base):
        r = m4_reviewer(base=f"{base}/ok/v1", model="mlx-community/Qwen3-30B-A3B-Thinking-2507-4bit",
                        timeout=5, max_tokens=123)
        assert r("PROMPT") == '{"ok": true, "issues": []}'
        path, body = srv.requests[-1]
        assert path == "/ok/v1/chat/completions"
        assert body["model"] == "mlx-community/Qwen3-30B-A3B-Thinking-2507-4bit"
        assert body["max_tokens"] == 123 and body["temperature"] == 0
        assert body["messages"] == [{"role": "user", "content": "PROMPT"}]
    print("  reviewer happy path: PASS")


def test_think_block_stripped_and_truncation_fails_closed():
    with fake_server() as (_, base):
        out = m4_reviewer(base=f"{base}/think/v1", timeout=5)("p")
        assert out == '{"ok": false, "issues": ["x"]}', out     # scratch {"ok": true} never reaches parse_verdict
        out = m4_reviewer(base=f"{base}/orphan_close/v1", timeout=5)("p")
        assert out == '{"ok": false, "issues": ["y"]}', out     # template-injected <think>: only </think> in reply
        for mode in ("length", "unterminated", "reasoning_only", "nochoices"):
            _raises(GateInfraError, m4_reviewer(base=f"{base}/{mode}/v1", timeout=5), "p")
    print("  think stripped (closed + orphan </think>); length/unterminated/reasoning-only/no-choices -> GateInfraError: PASS")


FORBIDDEN_IDS = ["claude-sonnet-4", "CLAUDE", "fable-1", "us.anthropic.claude-x", "gpt-6-luna", "opus",
                 "anthropic/claude-3-haiku", "Sonnet-5"]


def test_forbidden_model_ids_refused_at_factory_time():
    for factory, env_name in ((m4_reviewer, "CF_STUDIO_REVIEW_MODEL"), (m4_vlm, "CF_STUDIO_VLM_MODEL")):
        for mid in FORBIDDEN_IDS:
            _raises(GateConfigError, factory, base="http://127.0.0.1:1/v1", model=mid)
            with env(**{env_name: mid}):
                _raises(GateConfigError, factory, base="http://127.0.0.1:1/v1")
        _raises(GateConfigError, factory, base="http://127.0.0.1:1/v1", model="  ")
    print("  claude/fable/anthropic/luna ids refused (arg + env, both factories): PASS")


def test_server_reporting_forbidden_model_is_refused():
    with fake_server() as (_, base):
        _raises(GateConfigError, m4_reviewer(base=f"{base}/claude/v1", timeout=5), "p")
    print("  reply from a claude-* model refused: PASS")


BAD_BASES = ["http://localhost:8082/v1", "http://100.64.0.3.evil.com/v1", "http://127.0.0.1@evil.com/v1",
             "http://user:pw@127.0.0.1:8082/v1", "https://router.kernal.one/v1", "ftp://127.0.0.1/",
             "http://0x7f.0.0.1/v1", "http://[::1]:8082/v1", "", "127.0.0.1:8082/v1", "http://127.0.0.1:99999/v1"]


def test_host_allow_list():
    for factory, env_name in ((m4_reviewer, "CF_STUDIO_REVIEW_BASE"), (m4_vlm, "CF_STUDIO_VLM_BASE")):
        for b in BAD_BASES:
            if b:
                _raises(GateConfigError, factory, base=b)
                with env(**{env_name: b}):
                    _raises(GateConfigError, factory)
        # allowed hosts: factory only, no network call
        assert factory(base="http://127.0.0.1:8082/v1/").url == "http://127.0.0.1:8082/v1/chat/completions"
        assert factory(base="http://100.64.0.3:8082/v1").url == "http://100.64.0.3:8082/v1/chat/completions"
    _raises(GateConfigError, runtime.check_base_url, "")
    print("  host allow-list (localhost, look-alikes, userinfo, router, ftp refused): PASS")


def test_bad_timeout_config_refused():
    for t in ("abc", "0", "-1", "nan", "inf"):
        with env(CF_STUDIO_REVIEW_TIMEOUT=t):
            _raises(GateConfigError, m4_reviewer, base="http://127.0.0.1:1/v1")
    print("  non-positive/non-finite timeout refused: PASS")


def test_timeout_raises_gate_infra_error():
    with fake_server() as (_, base):
        t0 = time.monotonic()
        e = _raises(GateInfraError, m4_reviewer(base=f"{base}/slow/v1", timeout=0.3), "p")
        assert time.monotonic() - t0 < 1.4, "client must give up at its timeout, not wait for the server"
        assert "time" in str(e).lower(), e
    print("  timeout -> GateInfraError: PASS")


def test_connection_refused_raises_gate_infra_error():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    _raises(GateInfraError, m4_reviewer(base=f"http://127.0.0.1:{port}/v1", timeout=2), "p")
    _raises(GateInfraError, m4_vlm(base=f"http://127.0.0.1:{port}/v1", timeout=2), _png_path())
    print("  connection refused -> GateInfraError: PASS")


def test_http_500_and_garbage_raise_gate_infra_error():
    with fake_server() as (_, base):
        e = _raises(GateInfraError, m4_reviewer(base=f"{base}/e500/v1", timeout=5), "p")
        assert "500" in str(e)
        _raises(GateInfraError, m4_reviewer(base=f"{base}/garbage/v1", timeout=5), "p")
    print("  HTTP 500 / non-JSON body -> GateInfraError: PASS")


def test_redirect_refused_and_not_followed():
    with fake_server() as (srv, base):
        _raises(GateConfigError, m4_reviewer(base=f"{base}/redirect/v1", timeout=5), "p")
        assert len(srv.requests) == 1          # only the first request; evil.example never contacted
    print("  redirect -> GateConfigError, not followed: PASS")


def test_proxy_env_ignored():
    # urllib reads proxy env when an opener is BUILT (module import), so the proxy must be set before
    # studio.runtime is imported: run the call in a fresh interpreter with a dead proxy in its env.
    import subprocess
    dead = socket.socket(); dead.bind(("127.0.0.1", 0)); dport = dead.getsockname()[1]; dead.close()
    proxy = f"http://127.0.0.1:{dport}"
    child_env = {k: v for k, v in os.environ.items() if k.lower() != "no_proxy"}
    child_env.update(http_proxy=proxy, HTTP_PROXY=proxy, https_proxy=proxy, HTTPS_PROXY=proxy)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from studio.runtime import m4_reviewer; "
            "print(m4_reviewer(base=sys.argv[2], timeout=5)('p'))")
    with fake_server() as (srv, base):
        out = subprocess.run([sys.executable, "-c", code, os.path.join(HERE, os.pardir), f"{base}/ok/v1"],
                             env=child_env, capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr[-500:]
        assert out.stdout.strip() == '{"ok": true, "issues": []}', out.stdout
        assert len(srv.requests) == 1          # it reached the server directly, not via the dead proxy
    print("  http_proxy env ignored (fresh interpreter): PASS")


def _png_path():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "shot.png")
    with open(p, "wb") as fh:
        fh.write(PNG)
    return p


def test_vlm_happy_path_and_aesthetic_gate():
    png = _png_path()
    with fake_server() as (srv, base):
        vlm = m4_vlm(base=f"{base}/vlm/v1", timeout=5)
        assert vlm(png) == '{"score": 0.8, "notes": "ok"}'
        _, body = srv.requests[-1]
        assert body["model"] == runtime.DEFAULT_VLM_MODEL
        parts = body["messages"][0]["content"]
        assert parts[0]["type"] == "text" and "score" in parts[0]["text"]
        url = parts[1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,") and base64.b64decode(url.split(",", 1)[1]) == PNG
        verdict = aesthetic_judge.judge_aesthetics(png, vlm)
        assert verdict.ok is True and verdict.score == 0.8, verdict
        # the gate stays fail-closed when the runtime raises
        down = aesthetic_judge.judge_aesthetics(png, m4_vlm(base=f"{base}/e500/v1", timeout=5))
        assert down.ok is False
    print("  vlm happy path + aesthetic gate end-to-end: PASS")


def test_vlm_bad_images():
    vlm = m4_vlm(base="http://127.0.0.1:1/v1", timeout=1)
    _raises(FileNotFoundError, vlm, "/nonexistent/shot.png")
    d = tempfile.mkdtemp()
    gif = os.path.join(d, "x.gif"); open(gif, "wb").write(b"GIF89a")
    _raises(ValueError, vlm, gif)
    empty = os.path.join(d, "e.png"); open(empty, "wb").close()
    _raises(ValueError, vlm, empty)
    print("  vlm missing/unsupported/empty image -> error: PASS")


def test_env_defaults_read_at_call_time():
    names = ["CF_STUDIO_REVIEW_BASE", "CF_STUDIO_REVIEW_MODEL", "CF_STUDIO_REVIEW_TIMEOUT",
             "CF_STUDIO_REVIEW_MAX_TOKENS", "CF_STUDIO_VLM_BASE", "CF_STUDIO_VLM_MODEL", "CF_STUDIO_VLM_TIMEOUT"]
    with env(**{n: None for n in names}):
        r = m4_reviewer()
        assert r.url == "http://100.64.0.3:8082/v1/chat/completions"
        assert r.model == "mlx-community/Qwen3-30B-A3B-Thinking-2507-4bit" and r.timeout == 180.0
        v = m4_vlm()
        assert v.url == "http://100.64.0.3:8083/v1/chat/completions" and v.timeout == 60.0
    with env(CF_STUDIO_REVIEW_BASE="http://127.0.0.1:9/v1", CF_STUDIO_REVIEW_MODEL="qwen-x",
             CF_STUDIO_REVIEW_TIMEOUT="7"):
        r = m4_reviewer()
        assert (r.url, r.model, r.timeout) == ("http://127.0.0.1:9/v1/chat/completions", "qwen-x", 7.0)
    print("  env read at factory call time, defaults correct: PASS")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  {t.__name__}: FAIL — {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
