"""The fourth seam: every model call goes through here, and the environment picks the backend.

`LLM_PROVIDER=anthropic` (default) is today's behaviour byte for byte — `anthropic.Anthropic()`
with the ids from `.env` untouched. `LLM_PROVIDER=openrouter` points the same SDK at OpenRouter's
Anthropic Messages endpoint, which speaks the same protocol, so prompts, `max_tokens`, system
arrays, `cache_control` placement and streaming are all unchanged. `run.py` imports `client`,
`resolve`, `usage`, `PROVIDER` and `catalogue` and never imports `anthropic` itself.

Routing Claude through OpenRouter saves nothing — it is list price plus a hop. The saving is in
the cheap tier, where a Flash-class model does the bulk work (drafts, garble, cards) for about a
seventh of Haiku. That is the reason this seam exists.

`openrouter/*` router ids are refused everywhere: they pick by community spend and can land on
Fable, and CLAUDE.md is explicit that auto-routing must never select it. The app's own ROUTE table
stays the router.
"""
from __future__ import annotations

import os

PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
PROVIDERS = ("anthropic", "openrouter", "gateway")

OPENROUTER_BASE = "https://openrouter.ai/api"
#: `LLM_PROVIDER=gateway`: the LiteLLM gateway's Anthropic Messages endpoint (2026-09-30: the Anthropic
#: credit ran out and Matej moved the app off the paid Anthropic API). Same SDK, same streaming and
#: cache_control blocks, tested end to end on gpt-6-luna. docs/privacy-gateway.md is the GDPR record.
GATEWAY_BASE = os.environ.get("CF_PROVIDER_GATEWAY_BASE", "https://litellm.augment-code.support")
GATEWAY_MODEL = "gpt-6-luna"
#: What the picker offers on the gateway provider (CF_PICKER_MODELS overrides). All run on the gateway;
#: OpenRouter's :free models are NOT offered for the tutor chat (they may train on prompts; decided
#: 2026-09-30, they stay limited to the redacted bulk lane). Probed live 2026-09-30: luna 1.7 s,
#: gpt-5-nano 8.7 s, local-qwen-mlx 36 s (free; another machine's GPU, so it can be slow or offline).
DEFAULT_PICKER = "gpt-6-luna,gpt-5-nano,local-qwen-mlx"
#: Never offered, whatever CF_PICKER_MODELS says: $2-50 per Mtok on a shared key with a $30/month cap.
import re as _re
EXPENSIVE = _re.compile(r"claude|opus|sonnet|haiku|fable|astra|gpt-6-sol|-pro\b|gpt-5\.5-pro", _re.I)

#: Claude ids as the app spells them, and as OpenRouter does. OpenRouter uses dots where the
#: Anthropic API uses hyphens, so the same .env works on either backend.
CLAUDE_IDS = {
    "claude-haiku-4-5": "anthropic/claude-haiku-4.5",
    "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
    "claude-sonnet-5": "anthropic/claude-sonnet-5",
    "claude-sonnet-5-5": "anthropic/claude-sonnet-5.5",
    "claude-opus-5": "anthropic/claude-opus-5",
    "claude-fable-5-1": "anthropic/claude-fable-5.1",
}

#: USD per million tokens: (input, cache read, cache write, output). Anthropic bills cache reads at
#: 0.1x input and cache writes at 1.25x. Only used on the anthropic backend — OpenRouter returns the
#: real cost of each call, which is always better than a table that can drift.
PRICES = {
    "claude-haiku-4-5": (1.00, 0.10, 1.25, 5.00),
    "claude-sonnet-4-6": (3.00, 0.30, 3.75, 15.00),
    "claude-sonnet-5": (2.00, 0.20, 2.50, 10.00),
    "claude-sonnet-5-5": (2.00, 0.20, 2.50, 10.00),
    "claude-opus-5": (5.00, 0.50, 6.25, 25.00),
    "claude-fable-5-1": (10.00, 1.00, 12.50, 50.00),
    # the gateway's /model/info list price; no cache discount is assumed, so cached input counts in full
    "gpt-6-luna": (0.10, 0.10, 0.10, 0.50),
}

#: Non-Claude ids offered on the openrouter backend. The cheap tier default is the point of the
#: phase: DeepSeek V4.1 Flash is about 7x under Haiku with a 1M context.
DEFAULT_EXTRA_MODELS = "deepseek/deepseek-v4.1-flash,google/gemini-3.8-flash,google/gemini-3.1-flash-lite"

DEFAULT_MAIN = "claude-sonnet-5-5"
DEFAULT_CHEAP = {"anthropic": "claude-haiku-4-5", "openrouter": "deepseek/deepseek-v4.1-flash", "gateway": GATEWAY_MODEL}
DEFAULT_MAIN_BY = {"gateway": GATEWAY_MODEL}   # the gateway serves no Claude on this key's budget


class ConfigError(RuntimeError):
    """The environment asks for something this seam will not do."""


def _provider() -> str:
    if PROVIDER not in PROVIDERS:
        raise ConfigError(f"LLM_PROVIDER={PROVIDER!r} is not one of {', '.join(PROVIDERS)}")
    return PROVIDER


def is_router(model_id: str) -> bool:
    """`openrouter/auto` and friends pick a model by community spend and can land on Fable."""
    return str(model_id or "").strip().lower().startswith("openrouter/")


def key_name() -> str:
    return {"openrouter": "OPENROUTER_KEY", "gateway": "LITELLM_API_KEY"}.get(_provider(), "ANTHROPIC_API_KEY")


def has_key() -> bool:
    return bool(os.environ.get(key_name()))


def resolve(model_id: str) -> str:
    """The id to put on the wire. Identity on anthropic; Claude ids get OpenRouter's spelling on
    openrouter. An id that already carries a vendor prefix passes through untouched."""
    model_id = str(model_id or "").strip()
    if is_router(model_id):
        raise ConfigError(f"{model_id} is a router id: it can select any model, including Fable. "
                          "Pick a concrete model; the app's ROUTE table is the router.")
    if _provider() in ("anthropic", "gateway") or "/" in model_id:
        return model_id
    return CLAUDE_IDS.get(model_id, model_id)


def catalogue() -> list[str]:
    """Ids a client may ask for. `pick_model` checks against this, so it is also the allow-list."""
    if _provider() == "anthropic":
        return list(CLAUDE_IDS)
    if _provider() == "gateway":   # the picker offers only what this budget runs on, never Claude via the gateway
        out = [default_model("main")]
        for m in (x.strip() for x in os.environ.get("CF_PICKER_MODELS", DEFAULT_PICKER).split(",")):
            if m and m not in out and "/" not in m and not is_router(m) and not EXPENSIVE.search(m):
                out.append(m)
        return out
    extra = os.environ.get("CF_EXTRA_MODELS", DEFAULT_EXTRA_MODELS)
    out = [CLAUDE_IDS[c] for c in CLAUDE_IDS]
    for m in (x.strip() for x in extra.split(",")):
        if m and not is_router(m) and m not in out:
            out.append(m)
    return out


def label(model_id: str) -> str:
    """What the dropdown shows: no vendor prefix, no `claude-`."""
    return str(model_id or "").split("/")[-1].replace("claude-", "")


def _tier(value: str, where: str) -> str:
    """A tier may never be a router id. resolve() and catalogue() already refuse them, but a tier
    read straight from the environment reached neither, so CF_CHEAP_MODEL=openrouter/auto would have
    been handed out unchecked — and openrouter/auto can select Fable, which CLAUDE.md forbids
    auto-routing to. Found by augmentcode[bot] on PR #76."""
    if is_router(value):
        raise ConfigError(f"{where}={value} is a router id: it can select any model, including Fable. "
                          "Name a concrete model; the app's ROUTE table is the router.")
    return value


def default_model(tier: str = "main") -> str:
    p = _provider()
    if tier == "cheap":
        return _tier(os.environ.get("CF_CHEAP_MODEL") or DEFAULT_CHEAP[p], "CF_CHEAP_MODEL")
    main = _tier(os.environ.get("CF_MODEL") or DEFAULT_MAIN_BY.get(p, DEFAULT_MAIN), "CF_MODEL")
    if tier == "strong":
        return _tier(os.environ.get("CF_STRONG_MODEL") or main, "CF_STRONG_MODEL")
    return main


def client():
    """The SDK, pointed at whichever backend the environment names.

    OpenRouter's Anthropic Messages endpoint takes the same body, so the SDK needs no shim — only a
    base_url and a bearer token. `auth_token` is what sends `Authorization: Bearer`.
    """
    import anthropic
    p = _provider()
    key = os.environ.get(key_name())
    if not key:
        raise ConfigError(f"{key_name()} not set — add it to .env and restart.")
    if p == "anthropic":
        return anthropic.Anthropic()
    if p == "gateway":
        return anthropic.Anthropic(base_url=GATEWAY_BASE, auth_token=key)
    return anthropic.Anthropic(
        base_url=OPENROUTER_BASE,
        auth_token=key,
        default_headers={
            "HTTP-Referer": "https://github.com/cognitio-org/cognitioflow",
            "X-OpenRouter-Title": "CognitioFlow",
        },
    )


def _cost(model_id: str, tokens: dict):
    """USD for a call on the anthropic backend, or None when the id is not in PRICES.

    None, never a guess: a cost readout that quietly invents numbers is worse than one that admits
    it does not know.
    """
    price = PRICES.get(model_id) or PRICES.get(_unresolve(model_id))
    if not price:
        return None
    rate_in, rate_cache_read, rate_cache_write, rate_out = price
    return round(
        (tokens["in"] * rate_in
         + tokens["cache_read"] * rate_cache_read
         + tokens["cache_write"] * rate_cache_write
         + tokens["out"] * rate_out) / 1_000_000.0, 6)


def _unresolve(model_id: str) -> str:
    """OpenRouter's spelling back to the app's, so PRICES can be keyed one way."""
    for app_id, or_id in CLAUDE_IDS.items():
        if or_id == model_id:
            return app_id
    return model_id


#: Called with every usage() record, so the app can keep a cost log without this module touching a
#: database. Kept across importlib.reload (the tests reload this module) so a registered log survives.
SINKS: list = globals().get("SINKS", [])


def _emit(record: dict) -> None:
    for fn in list(SINKS):
        try:
            fn(record)
        except Exception:
            pass   # a log line that fails to write must never fail the call it describes


def usage(m, task: str) -> dict:
    """One shape for both backends, from a response or a stream's `get_final_message()`.

    On openrouter `cost` comes from the response — the real figure, including whatever provider
    served it. On anthropic it is computed from PRICES.
    """
    u = getattr(m, "usage", None)

    def n(*names) -> int:
        for name in names:
            v = getattr(u, name, None)
            if isinstance(v, int):
                return v
        return 0

    tokens = {
        "in": n("input_tokens"),
        "cache_read": n("cache_read_input_tokens"),
        "cache_write": n("cache_creation_input_tokens"),
        "out": n("output_tokens"),
    }
    model_id = getattr(m, "model", "") or ""
    cost = getattr(u, "cost", None)
    if not isinstance(cost, (int, float)):
        # On openrouter the billed figure comes from the response. When it is absent, the local
        # table is not what was charged, so reporting it would put a number on screen that does not
        # match the bill — exactly the guess this seam promises not to make. Say unknown instead.
        cost = None if _provider() == "openrouter" else _cost(model_id, tokens)
    provider = getattr(u, "provider", None) or _provider()   # the gateway lane labels its own calls
    record = {"provider": provider, "model": model_id, "task": task, "cost": cost, **tokens}
    _emit(record)
    return record


def describe() -> dict:
    """For `/api/config` and the startup banner."""
    return {
        "provider": _provider(),
        "has_key": has_key(),
        "models": [{"id": m, "label": label(m)} for m in catalogue()],
        # Phase 18: the self-hosted tier is a per-task routing override on the cheap tier, not a
        # catalogue entry the dropdown offers. Reported so a banner or #dot hint can say so.
        "local": {"enabled": local_enabled(),
                   "model": LOCAL_MODEL if local_enabled() else None,
                   "tasks": list(LOCAL_TASKS) if local_enabled() else []},
    }


# ---------------------------------------------------------------- the local tier (Phase 18)
# A self-hosted, OpenAI-compatible endpoint (Ollama in dev, vLLM later) for the cheap/bulk tier.
# Why it exists: privacy (student text never leaves our servers) + owning/fine-tuning the model + the
# pitch — NOT cost (the Phase-9 cheap tier is already near-free). See docs/phases/PHASE-18-selfhosted-
# generation.md and ~/reports/cf-phaseA-decisions.md.
#
# Default OFF: with CF_LOCAL_BASE_URL unset, local_allows() is always False, nothing below is reached,
# and the cheap tier stays exactly as Phase 9 left it — byte for byte. Only the NON-STREAMING path is
# bridged: the bulk tasks (cards first) do not stream, and the one streaming call (tutor chat) is MAIN
# tier and stays cloud. The seam still speaks Anthropic-Messages to run.py; this translates to/from the
# endpoint's OpenAI chat-completions format and hands back the same shape run.py already reads.
LOCAL_BASE_URL = os.environ.get("CF_LOCAL_BASE_URL", "").strip()
LOCAL_MODEL = os.environ.get("CF_LOCAL_MODEL", "qwen2.5:7b-instruct").strip()
#: Which named bulk tasks may run on the local model. Each task flips to local on its own, once it has
#: cleared the eval bar (docs/phases/PHASE-18). The list starts at `cards` — the proof of concept.
LOCAL_TASKS = tuple(t.strip() for t in os.environ.get("CF_LOCAL_TASKS", "cards").split(",") if t.strip())
LOCAL_TIMEOUT = float(os.environ.get("CF_LOCAL_TIMEOUT", "300"))   # a 7B on a laptop can take a while
#: Low by default: the bulk tasks are grounded extraction (cards from the ticked text), where a 7B at a
#: high temperature invents law and returns malformed JSON. A caller may still override per call.
LOCAL_TEMPERATURE = float(os.environ.get("CF_LOCAL_TEMPERATURE", "0.2"))


def local_enabled() -> bool:
    """On only when an endpoint is named. Unset → the cheap tier is untouched (today's behaviour)."""
    return bool(LOCAL_BASE_URL)


def local_allows(task: str) -> bool:
    """Whether this bulk task should run on the local model rather than the configured cloud tier."""
    return bool(task) and local_enabled() and task in LOCAL_TASKS


class _LocalBlock:
    """One text block, in the shape run.py reads (`b.type == "text"`, `b.text`)."""
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _LocalUsage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0
        self.cost = 0            # own hardware: the honest figure is zero, not unknown (Phase-9 rule 8)
        self.provider = "local"  # usage() labels the ai_calls row provider=local


class _LocalMessage:
    """A local reply dressed as an Anthropic Messages response: `content[].text`, `model`,
    `stop_reason`, `usage`. Enough for the bulk call sites and `usage()`; images/streaming are not."""
    def __init__(self, text: str, model: str, stop_reason: str, usage: _LocalUsage):
        self.content = [_LocalBlock(text)]
        self.model = model
        self.stop_reason = stop_reason
        self.usage = usage


def _flatten_content(content) -> str:
    """Anthropic content is a string or a list of blocks; the bulk tasks use text only. Non-text
    blocks (e.g. images) are dropped — the local tier serves text-only bulk tasks for now."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return "\n\n".join(p for p in parts if p)
    return str(content or "")


def _to_openai_messages(system, messages) -> list:
    """Anthropic (system + messages) → OpenAI chat-completions messages. A system prompt — string or
    the cached-block array — becomes a single system message at the front."""
    out = []
    if system:
        out.append({"role": "system", "content": _flatten_content(system)})
    for msg in messages or []:
        out.append({"role": msg.get("role", "user"), "content": _flatten_content(msg.get("content", ""))})
    return out


def local_create(*, messages, max_tokens=1024, system=None, temperature=None, **_ignored) -> _LocalMessage:
    """One non-streaming call to the local endpoint, returned in the Anthropic shape run.py reads.

    Uses stdlib urllib so the seam gains no dependency. Raises on any transport error; `local_call`
    turns that into a fall-back to the configured cloud tier. `_ignored` swallows Anthropic-only kwargs
    (e.g. `cache_control` wrappers already flattened, `stop_sequences`) the local endpoint does not take.
    """
    import json as _json
    import urllib.request

    body = {
        "model": LOCAL_MODEL,
        "messages": _to_openai_messages(system, messages),
        "max_tokens": int(max_tokens),
        "stream": False,
    }
    body["temperature"] = float(temperature) if temperature is not None else LOCAL_TEMPERATURE
    url = LOCAL_BASE_URL.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url, data=_json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 # Ollama ignores the bearer; a real OpenAI-compatible server (vLLM) may want one.
                 "Authorization": "Bearer " + (os.environ.get("CF_LOCAL_KEY") or "local")})
    with urllib.request.urlopen(req, timeout=LOCAL_TIMEOUT) as resp:
        data = _json.loads(resp.read().decode("utf-8"))

    choice = (data.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content")) or ""
    finish = choice.get("finish_reason") or ""
    stop_reason = "max_tokens" if finish == "length" else "end_turn"   # so _mark_if_cut / Continue work
    u = data.get("usage") or {}
    usage = _LocalUsage(int(u.get("prompt_tokens", 0) or 0), int(u.get("completion_tokens", 0) or 0))
    return _LocalMessage(text, data.get("model") or LOCAL_MODEL, stop_reason, usage)


def local_call(task, **kw):
    """ask_model's hook: the local result for an allowed task, or None to fall back to the configured
    cloud/gateway tier. Mirrors gateway.call's contract — any trouble (endpoint down, empty answer) is
    a silent fall-back so the job still gets done."""
    if not local_allows(task):
        return None
    try:
        m = local_create(**kw)
    except Exception as e:   # noqa: BLE001 — the job still gets done, on the cloud tier
        import logging
        logging.getLogger("cognitioflow.llm").warning(
            "local %s failed (%s); falling back to the cloud tier", task, type(e).__name__)
        return None
    if not "".join(b.text for b in m.content if getattr(b, "type", "") == "text").strip():
        return None   # a model that spent its budget on nothing, or a 200 with empty content
    return m


#: Seconds to wait for the first words before a second, identical request races the first. The gateway
#: sometimes answers at once and then stalls 10–20 s before the first token (seen live 2026-09-30 in the
#: tutor, 16 s, and in Jarvis). 0 turns hedging off. A duplicate costs only on the slow turns.
HEDGE_S = float(os.environ.get("CF_HEDGE_S", "1.5"))


class _Hedged:
    """What `hedged_stream` returns: `text_stream`, `get_final_message()`, usable as a context manager."""

    def __init__(self, mgr, stream, it, first):
        self._mgr, self._stream, self._it, self._first = mgr, stream, it, first

    @property
    def text_stream(self):
        if self._first is not None:
            yield self._first
        yield from self._it

    def get_final_message(self):
        return self._stream.get_final_message()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self._mgr.__exit__(None, None, None)
        except Exception:
            pass
        return False


def hedged_stream(make_client, hedge_s: float | None = None, **kw) -> _Hedged:
    """`make_client().messages.stream(**kw)`, raced against a second copy if the first words are slow.

    The winner is whichever stream yields text first; the loser is closed as soon as it answers. Errors
    from one copy are ignored while the other can still win; if both fail, the first error is raised.
    """
    import queue
    import threading

    hedge_s = HEDGE_S if hedge_s is None else hedge_s
    q: queue.Queue = queue.Queue()

    def run():
        try:
            mgr = make_client().messages.stream(**kw)
            stream = mgr.__enter__()
            it = iter(stream.text_stream)
            q.put(("ok", mgr, stream, it, next(it, None)))
        except Exception as e:  # noqa: BLE001 - reported to the caller if nothing else wins
            q.put(("err", e))

    threading.Thread(target=run, daemon=True).start()
    started, errors = 1, []
    try:
        got = q.get(timeout=hedge_s) if hedge_s > 0 else q.get()
    except queue.Empty:
        threading.Thread(target=run, daemon=True).start()
        started += 1
        got = q.get()
    while True:
        if got[0] == "ok":
            break
        errors.append(got[1])
        if len(errors) >= started:
            raise errors[0]
        got = q.get()

    def close_losers(remaining):
        for _ in range(remaining):
            other = q.get()
            if other[0] == "ok":
                try:
                    other[1].__exit__(None, None, None)
                except Exception:
                    pass

    remaining = started - 1 - len(errors)
    if remaining > 0:
        threading.Thread(target=close_losers, args=(remaining,), daemon=True).start()
    _, mgr, stream, it, first = got
    return _Hedged(mgr, stream, it, first)
