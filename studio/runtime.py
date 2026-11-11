"""CF Game Studio — real runtimes for the model-backed gates (Phase 2, slice S5).

Two factories build the callables the gates take as injected dependencies:

- ``m4_reviewer()`` -> ``callable(prompt: str) -> str`` for ``doctrinal_review``
  (Qwen3-30B-A3B-Thinking on the M4, OpenAI-compatible ``/chat/completions``).
- ``m4_vlm()`` -> ``callable(image_path: str) -> str`` for ``aesthetic_judge``
  (Qwen3-VL-4B-Instruct on the M4's pinned mlx_vlm.server slot, per the fleet VLM plan; the image goes
  inline as a base64 data URL).

Guards (they are the point of this module, not decoration):

- **Host allow-list.** The base URL's host must be exactly the M4 mesh IP or
  loopback. Anything else (``localhost``, the Kernal router, a look-alike such as
  ``100.64.0.3.evil.com``, userinfo tricks) is refused with ``GateConfigError``.
  Requests go through an opener that ignores ``http_proxy``/``https_proxy`` and
  refuses every redirect, so neither can carry a call off the allow-list.
- **Model refusal.** Any model id containing a Claude/Anthropic/Fable marker (or
  gpt-6-luna, decision D-3) is refused, at factory time and again if the server
  reports such a model in its reply. No gate ever runs on those models.
- **Typed failures.** Transport problems (timeout, refused/reset connection,
  HTTP error status, unreadable body, truncated model output, a Thinking-model reply with no evidence that
  its reasoning was separated from the answer) raise
  ``GateInfraError`` so the adapter can record "Gates unavailable" instead of a
  content block. A refused configuration raises ``GateConfigError``, which is
  deliberately NOT a ``GateInfraError``: a misconfiguration is not an outage.

Env is read inside each factory call, never at import. Stdlib only. Nothing here
is imported by ``run.py`` or shipped in the prod image.
"""
from __future__ import annotations

import base64
import http.client
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable


class GateInfraError(RuntimeError):
    """A transient transport failure: the gate could not get an answer at all."""


class GateConfigError(ValueError):
    """A refused configuration: forbidden model id, host off the allow-list, redirect."""


ALLOWED_HOSTS = frozenset({"100.64.0.3", "127.0.0.1"})   # M4 mesh IP + loopback; exact match only
FORBIDDEN_MODEL_MARKERS = ("claude", "anthropic", "fable", "opus", "sonnet", "haiku", "luna")

# The Thinking model is served by its own mlx_lm.server on :8082 (the Coder owns :8080). Asking :8080 for the
# Thinking model would make that process load a second 30B and evict the Coder, so the default is :8082.
DEFAULT_REVIEW_BASE = "http://100.64.0.3:8082/v1"
DEFAULT_REVIEW_MODEL = "mlx-community/Qwen3-30B-A3B-Thinking-2507-4bit"
DEFAULT_REVIEW_TIMEOUT = 180.0
# Qwen3-30B-A3B-Thinking-2507 model card, "Best Practices": "We recommend using an output length of 32,768 tokens
# for most queries." A lower cap turns long reasoning into finish_reason=length -> GateInfraError, not a verdict.
# Overridable per call (max_tokens=) or by env CF_STUDIO_REVIEW_MAX_TOKENS. The call is non-streaming, so the
# 180 s timeout, not this cap, is what bounds a long generation; calibrate both in shadow runs.
DEFAULT_REVIEW_MAX_TOKENS = 32768
# Same card: "We suggest using Temperature=0.6, TopP=0.95, TopK=20, and MinP=0." Never greedy (temperature 0):
# Qwen3 thinking models loop on greedy decoding, which ends in finish_reason=length and burns the infra retries.
# Field names match mlx_lm.server's request parser (top_k must be an int there).
REVIEW_SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0}

# Fleet VLM plan (memory note fleet-vlm-serving): Qwen3-VL-4B-Instruct-4bit, pinned / non-evictable, on the M4's
# mlx_vlm.server at :8083. It beats the old Qwen2.5-VL-7B at about a third of the RAM. The fleet plan wins over
# spec section 5 (which named the 7B); override with CF_STUDIO_VLM_MODEL / CF_STUDIO_VLM_BASE.
DEFAULT_VLM_BASE = "http://100.64.0.3:8083/v1"
DEFAULT_VLM_MODEL = "mlx-community/Qwen3-VL-4B-Instruct-4bit"
DEFAULT_VLM_TIMEOUT = 60.0
DEFAULT_VLM_MAX_TOKENS = 400

MAX_IMAGE_BYTES = 8 * 1024 * 1024
_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}

VLM_PROMPT = (
    "You are judging the visual polish of a screenshot from an educational web game. "
    "Rate how finished and professional it looks: layout, typography, contrast, consistency, no broken or "
    "overlapping elements. Return STRICT JSON only, exactly in this format: "
    '{"score": <number between 0 and 1>, "notes": "<one short sentence>"}'
)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# ---------------------------------------------------------------------------------------------- validation

def check_base_url(url) -> str:
    """Return the base URL without a trailing slash, or raise GateConfigError if it is off the allow-list."""
    if not isinstance(url, str) or not url.strip():
        raise GateConfigError("gate endpoint base URL is empty")
    try:
        parts = urllib.parse.urlsplit(url.strip())
        host = parts.hostname
        parts.port  # noqa: B018 — a malformed port raises ValueError here
    except ValueError as e:
        raise GateConfigError(f"gate endpoint URL is malformed: {url!r}") from e
    if parts.scheme not in ("http", "https"):
        raise GateConfigError(f"gate endpoint scheme refused: {parts.scheme!r}")
    if parts.username is not None or parts.password is not None:
        raise GateConfigError("gate endpoint URL must not carry credentials/userinfo")
    if host not in ALLOWED_HOSTS:
        raise GateConfigError(f"gate endpoint host {host!r} is not on the allow-list {sorted(ALLOWED_HOSTS)}")
    return url.strip().rstrip("/")


def _forbidden_marker(model: str) -> str | None:
    low = model.lower()
    return next((m for m in FORBIDDEN_MODEL_MARKERS if m in low), None)


def check_model(model) -> str:
    """Return the model id, or raise GateConfigError for an empty or forbidden (Claude/Fable/luna…) id."""
    if not isinstance(model, str) or not model.strip():
        raise GateConfigError("gate model id is empty")
    hit = _forbidden_marker(model)
    if hit:
        raise GateConfigError(f"gate model {model!r} refused: matches forbidden marker {hit!r}")
    return model.strip()


def _env_or(value, env_name: str, default):
    if value is not None:
        return value
    raw = os.environ.get(env_name, "").strip()
    return raw if raw else default


def _positive_number(value, name: str, cast) -> float | int:
    try:
        n = cast(value)
    except (TypeError, ValueError) as e:
        raise GateConfigError(f"{name} is not a number: {value!r}") from e
    if not (math.isfinite(n) and n > 0):
        raise GateConfigError(f"{name} must be > 0, got {value!r}")
    return n


# ---------------------------------------------------------------------------------------------- transport

class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: PLR0913
        raise GateConfigError(f"gate endpoint redirect refused ({code} -> {newurl})")


# No proxies (http_proxy env must not route a gate call elsewhere), no redirects.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirects())


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read()
    except GateConfigError:
        raise
    except urllib.error.HTTPError as e:            # before URLError/OSError: HTTPError subclasses both
        raise GateInfraError(f"gate endpoint HTTP {e.code}") from e
    except urllib.error.URLError as e:             # refused, DNS, and connect-phase timeouts land here
        raise GateInfraError(f"gate endpoint unreachable: {e.reason}") from e
    except TimeoutError as e:                      # read-phase timeout (socket.timeout is TimeoutError)
        raise GateInfraError(f"gate endpoint timed out after {timeout}s") from e
    except (http.client.HTTPException, OSError) as e:  # IncompleteRead, RemoteDisconnected, resets
        raise GateInfraError(f"gate endpoint transport error: {type(e).__name__}: {e}") from e
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as e:
        raise GateInfraError("gate endpoint returned a non-JSON body") from e
    if not isinstance(data, dict):
        raise GateInfraError("gate endpoint returned JSON that is not an object")
    return data


def is_thinking_model(model: str) -> bool:
    """True for reasoning models (Qwen3 *-Thinking-*, *think*) whose replies must show the reasoning was split off."""
    return "think" in model.lower()


def _content_of(data: dict, thinking: bool = False) -> str:
    """Extract the final answer text, fail-closed: never return partial or thinking-only output.

    ``thinking=True`` (the configured model is a reasoning model) additionally requires evidence that the
    reasoning was separated from the answer: either the content carries a ``</think>`` (the text before it is
    dropped), or the server split the reasoning into its own ``reasoning`` / ``reasoning_content`` field (as
    mlx_lm.server 0.31 does). A Thinking reply with neither may be raw reasoning end to end, and the first JSON
    object in it would reach ``parse_verdict`` — so it raises ``GateInfraError`` instead.
    """
    served = data.get("model")
    if isinstance(served, str) and _forbidden_marker(served):
        raise GateConfigError(f"gate endpoint answered as forbidden model {served!r}")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise GateInfraError("gate endpoint reply has no choices")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise GateInfraError("gate model output truncated (finish_reason=length)")
    msg = choice.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    # Deliberately no fallback to "reasoning_content": a scratch {"ok": true} in the reasoning must never pass.
    if not isinstance(content, str):
        raise GateInfraError("gate endpoint reply has no message content")
    if thinking:
        split = any(isinstance(msg.get(k), str) and msg.get(k).strip() for k in ("reasoning", "reasoning_content"))
        if not split and "</think>" not in content.lower():
            raise GateInfraError("thinking-model reply has no </think> and no separate reasoning field: "
                                 "cannot tell the answer from the reasoning")
    content = _THINK_BLOCK.sub("", content)
    # Qwen3 Thinking-2507's chat template pre-injects the opening <think>, so a reply can carry only the
    # closing tag: everything before the last orphan </think> is reasoning and must never reach the parser.
    close = content.lower().rfind("</think>")
    if close != -1:
        content = content[close + len("</think>"):]
    if "<think>" in content.lower():
        raise GateInfraError("gate model output has an unterminated <think> block")
    return content.strip()


# ---------------------------------------------------------------------------------------------- factories

def m4_reviewer(base=None, model=None, timeout=None, max_tokens=None, system=None) -> Callable[[str], str]:
    """Build the doctrine reviewer callable. Validates host and model now; raises GateConfigError if refused.

    ``system`` (optional) is sent as the system message on every call: the shared STUDIO_BRIEF
    (studio/brief.md), so the reviewer judges by the same aim and terms as the writer (model-quality plan,
    section 4). None = no system message (today's behaviour)."""
    if system is not None and not isinstance(system, str):
        raise GateConfigError("reviewer system prompt must be a str")
    url = check_base_url(_env_or(base, "CF_STUDIO_REVIEW_BASE", DEFAULT_REVIEW_BASE)) + "/chat/completions"
    mdl = check_model(_env_or(model, "CF_STUDIO_REVIEW_MODEL", DEFAULT_REVIEW_MODEL))
    tmo = _positive_number(_env_or(timeout, "CF_STUDIO_REVIEW_TIMEOUT", DEFAULT_REVIEW_TIMEOUT),
                           "CF_STUDIO_REVIEW_TIMEOUT", float)
    mtk = _positive_number(_env_or(max_tokens, "CF_STUDIO_REVIEW_MAX_TOKENS", DEFAULT_REVIEW_MAX_TOKENS),
                           "CF_STUDIO_REVIEW_MAX_TOKENS", int)
    thinking = is_thinking_model(mdl)

    def reviewer(prompt: str) -> str:
        if not isinstance(prompt, str):
            raise TypeError("reviewer prompt must be a str")
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        payload = {"model": mdl, **REVIEW_SAMPLING, "max_tokens": mtk, "messages": msgs}
        data = _post_json(url, payload, tmo)
        reviewer.last_served = data.get("model") if isinstance(data.get("model"), str) else ""
        return _content_of(data, thinking=thinking)

    reviewer.model, reviewer.url, reviewer.timeout, reviewer.max_tokens = mdl, url, tmo, mtk
    reviewer.system, reviewer.last_served = system, ""   # for the review card / logs
    return reviewer


def _image_data_url(image_path: str) -> str:
    ext = os.path.splitext(str(image_path))[1].lower()
    mime = _IMAGE_MIME.get(ext)
    if mime is None:
        raise ValueError(f"unsupported screenshot type {ext!r} (png/jpeg/webp only)")
    size = os.path.getsize(image_path)                # FileNotFoundError for a missing file
    if size == 0 or size > MAX_IMAGE_BYTES:
        raise ValueError(f"screenshot size {size} bytes outside 1..{MAX_IMAGE_BYTES}")
    with open(image_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def m4_vlm(base=None, model=None, timeout=None, max_tokens=None) -> Callable[[str], str]:
    """Build the aesthetic-judge VLM callable. Validates host and model now; raises GateConfigError if refused."""
    url = check_base_url(_env_or(base, "CF_STUDIO_VLM_BASE", DEFAULT_VLM_BASE)) + "/chat/completions"
    mdl = check_model(_env_or(model, "CF_STUDIO_VLM_MODEL", DEFAULT_VLM_MODEL))
    tmo = _positive_number(_env_or(timeout, "CF_STUDIO_VLM_TIMEOUT", DEFAULT_VLM_TIMEOUT),
                           "CF_STUDIO_VLM_TIMEOUT", float)
    mtk = _positive_number(_env_or(max_tokens, "CF_STUDIO_VLM_MAX_TOKENS", DEFAULT_VLM_MAX_TOKENS),
                           "CF_STUDIO_VLM_MAX_TOKENS", int)

    def vlm(image_path: str) -> str:
        data_url = _image_data_url(image_path)
        payload = {"model": mdl, "temperature": 0, "max_tokens": mtk,
                   "messages": [{"role": "user", "content": [
                       {"type": "text", "text": VLM_PROMPT},
                       {"type": "image_url", "image_url": {"url": data_url}},
                   ]}]}
        return _content_of(_post_json(url, payload, tmo))

    vlm.model, vlm.url, vlm.timeout, vlm.max_tokens = mdl, url, tmo, mtk
    return vlm
