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
PROVIDERS = ("anthropic", "openrouter")

OPENROUTER_BASE = "https://openrouter.ai/api"

#: Claude ids as the app spells them, and as OpenRouter does. OpenRouter uses dots where the
#: Anthropic API uses hyphens, so the same .env works on either backend.
CLAUDE_IDS = {
    "claude-haiku-4-5": "anthropic/claude-haiku-4.5",
    "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
    "claude-sonnet-5": "anthropic/claude-sonnet-5",
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
    "claude-opus-5": (5.00, 0.50, 6.25, 25.00),
    "claude-fable-5-1": (10.00, 1.00, 12.50, 50.00),
}

#: Non-Claude ids offered on the openrouter backend. The cheap tier default is the point of the
#: phase: DeepSeek V4.1 Flash is about 7x under Haiku with a 1M context.
DEFAULT_EXTRA_MODELS = "deepseek/deepseek-v4.1-flash,google/gemini-3.8-flash,google/gemini-3.1-flash-lite"

DEFAULT_MAIN = "claude-sonnet-5"
DEFAULT_CHEAP = {"anthropic": "claude-haiku-4-5", "openrouter": "deepseek/deepseek-v4.1-flash"}


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
    return "OPENROUTER_KEY" if _provider() == "openrouter" else "ANTHROPIC_API_KEY"


def has_key() -> bool:
    return bool(os.environ.get(key_name()))


def resolve(model_id: str) -> str:
    """The id to put on the wire. Identity on anthropic; Claude ids get OpenRouter's spelling on
    openrouter. An id that already carries a vendor prefix passes through untouched."""
    model_id = str(model_id or "").strip()
    if is_router(model_id):
        raise ConfigError(f"{model_id} is a router id: it can select any model, including Fable. "
                          "Pick a concrete model; the app's ROUTE table is the router.")
    if _provider() == "anthropic" or "/" in model_id:
        return model_id
    return CLAUDE_IDS.get(model_id, model_id)


def catalogue() -> list[str]:
    """Ids a client may ask for. `pick_model` checks against this, so it is also the allow-list."""
    if _provider() == "anthropic":
        return list(CLAUDE_IDS)
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
    main = _tier(os.environ.get("CF_MODEL") or DEFAULT_MAIN, "CF_MODEL")
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
    return {"provider": _provider(), "model": model_id, "task": task, "cost": cost, **tokens}


def describe() -> dict:
    """For `/api/config` and the startup banner."""
    return {
        "provider": _provider(),
        "has_key": has_key(),
        "models": [{"id": m, "label": label(m)} for m in catalogue()],
    }
