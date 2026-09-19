"""The provider seam. No test calls a real backend."""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import llm as _llm  # noqa: E402


ENV_KEYS = ("LLM_PROVIDER", "CF_EXTRA_MODELS", "CF_MODEL", "CF_CHEAP_MODEL", "CF_STRONG_MODEL",
            "ANTHROPIC_API_KEY", "OPENROUTER_KEY")


@pytest.fixture(autouse=True)
def restore_env():
    """load() clears these, and conftest.py sets ANTHROPIC_API_KEY once for the whole session.

    Without restoring them this file leaks: tests/test_auth.py reads os.environ["ANTHROPIC_API_KEY"]
    directly and sorts after test_llm, so it raised KeyError on a variable this file had deleted —
    a failure with no connection to the code under test, in a file nobody would think to look at.
    """
    saved = {k: os.environ.get(k) for k in ENV_KEYS}
    yield
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    importlib.reload(_llm)


def load(provider=None, **env):
    """Reimport llm with a chosen environment. PROVIDER is read at import, so a reload is the
    honest way to test both backends rather than reaching into module state."""
    for k in ENV_KEYS:
        os.environ.pop(k, None)
    if provider:
        os.environ["LLM_PROVIDER"] = provider
    os.environ.update({k: v for k, v in env.items() if v is not None})
    return importlib.reload(_llm)


class FakeUsage:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class FakeMessage:
    def __init__(self, model, usage):
        self.model, self.usage = model, usage


# ---- provider selection -------------------------------------------------------------------

def test_default_provider_is_anthropic():
    assert load().PROVIDER == "anthropic"


def test_unknown_provider_is_refused():
    llm = load("wat")
    with pytest.raises(llm.ConfigError):
        llm.catalogue()


def test_key_name_follows_provider():
    assert load().key_name() == "ANTHROPIC_API_KEY"
    assert load("openrouter").key_name() == "OPENROUTER_KEY"


# ---- resolve ------------------------------------------------------------------------------

def test_resolve_is_identity_on_anthropic():
    llm = load()
    for app_id in llm.CLAUDE_IDS:
        assert llm.resolve(app_id) == app_id


def test_resolve_maps_every_claude_id_on_openrouter():
    llm = load("openrouter")
    assert llm.resolve("claude-sonnet-4-6") == "anthropic/claude-sonnet-4.6"
    assert llm.resolve("claude-sonnet-5") == "anthropic/claude-sonnet-5"
    assert llm.resolve("claude-haiku-4-5") == "anthropic/claude-haiku-4.5"
    assert llm.resolve("claude-opus-5") == "anthropic/claude-opus-5"
    assert llm.resolve("claude-fable-5-1") == "anthropic/claude-fable-5.1"


def test_slashed_ids_pass_through():
    llm = load("openrouter")
    assert llm.resolve("deepseek/deepseek-v4.1-flash") == "deepseek/deepseek-v4.1-flash"


# ---- router ids are refused everywhere ----------------------------------------------------
# openrouter/auto picks by community spend and can land on Fable. CLAUDE.md: auto-routing must
# never select it.

@pytest.mark.parametrize("provider", ["anthropic", "openrouter"])
def test_router_id_refused_by_resolve(provider):
    llm = load(provider)
    with pytest.raises(llm.ConfigError):
        llm.resolve("openrouter/auto")


def test_router_id_never_enters_the_catalogue():
    llm = load("openrouter", CF_EXTRA_MODELS="openrouter/auto,deepseek/deepseek-v4.1-flash")
    cat = llm.catalogue()
    assert "openrouter/auto" not in cat
    assert "deepseek/deepseek-v4.1-flash" in cat


# ---- catalogue ----------------------------------------------------------------------------

def test_catalogue_is_the_five_claude_ids_on_anthropic():
    assert load().catalogue() == list(_llm.CLAUDE_IDS)


def test_catalogue_adds_extras_on_openrouter():
    cat = load("openrouter").catalogue()
    assert "anthropic/claude-sonnet-5" in cat
    assert "deepseek/deepseek-v4.1-flash" in cat


def test_label_strips_vendor_and_claude():
    llm = load("openrouter")
    assert llm.label("anthropic/claude-sonnet-4.6") == "sonnet-4.6"
    assert llm.label("deepseek/deepseek-v4.1-flash") == "deepseek-v4.1-flash"


# ---- tier defaults ------------------------------------------------------------------------

def test_cheap_tier_default_differs_by_provider():
    assert load().default_model("cheap") == "claude-haiku-4-5"
    assert load("openrouter").default_model("cheap") == "deepseek/deepseek-v4.1-flash"


def test_strong_follows_main_unless_set():
    llm = load(CF_MODEL="claude-sonnet-5")
    assert llm.default_model("strong") == "claude-sonnet-5"
    llm = load(CF_MODEL="claude-sonnet-5", CF_STRONG_MODEL="claude-opus-5")
    assert llm.default_model("strong") == "claude-opus-5"


# ---- usage --------------------------------------------------------------------------------

def test_usage_computes_cost_on_anthropic():
    llm = load()
    m = FakeMessage("claude-sonnet-5", FakeUsage(
        input_tokens=1000, output_tokens=500, cache_read_input_tokens=44000, cache_creation_input_tokens=0))
    u = llm.usage(m, "drill")
    # 1000*2 + 44000*0.20 + 500*10 per million
    assert u["cost"] == pytest.approx((1000 * 2.0 + 44000 * 0.20 + 500 * 10.0) / 1e6)
    assert u["cache_read"] == 44000 and u["task"] == "drill" and u["provider"] == "anthropic"


def test_usage_takes_cost_from_the_response_on_openrouter():
    llm = load("openrouter")
    m = FakeMessage("deepseek/deepseek-v4.1-flash", FakeUsage(
        input_tokens=10, output_tokens=20, cost=0.000123))
    u = llm.usage(m, "cards")
    assert u["cost"] == 0.000123
    assert u["provider"] == "openrouter"


def test_unknown_model_has_no_cost_rather_than_a_guess():
    llm = load()
    m = FakeMessage("some-model-nobody-priced", FakeUsage(input_tokens=10, output_tokens=10))
    assert llm.usage(m, "quiz")["cost"] is None


def test_openrouter_without_a_cost_reports_unknown_not_the_local_table():
    """This test previously asserted the opposite, and the assertion was wrong.

    On openrouter the billed figure comes from the response. Falling back to PRICES would show a
    number that does not match the bill — a guess, which this seam promises not to make.
    augmentcode[bot] caught it on PR #76.
    """
    llm = load("openrouter")
    m = FakeMessage("anthropic/claude-sonnet-5", FakeUsage(input_tokens=1000, output_tokens=0))
    assert llm.usage(m, "drill")["cost"] is None


def test_missing_usage_fields_count_as_zero():
    llm = load()
    u = llm.usage(FakeMessage("claude-sonnet-5", FakeUsage()), "plan")
    assert (u["in"], u["out"], u["cache_read"], u["cache_write"]) == (0, 0, 0, 0)


# ---- a tier may never be a router ----------------------------------------------------------
# resolve() and catalogue() already refused router ids, but a tier read from the environment
# reached neither, so CF_CHEAP_MODEL=openrouter/auto was handed out unchecked.

@pytest.mark.parametrize("var,tier", [
    ("CF_CHEAP_MODEL", "cheap"), ("CF_MODEL", "main"), ("CF_STRONG_MODEL", "strong"),
])
def test_router_id_refused_in_every_tier(var, tier):
    llm = load("openrouter", **{var: "openrouter/auto"})
    with pytest.raises(llm.ConfigError):
        llm.default_model(tier)


def test_a_concrete_tier_is_still_accepted():
    llm = load("openrouter", CF_CHEAP_MODEL="google/gemini-3.8-flash")
    assert llm.default_model("cheap") == "google/gemini-3.8-flash"


# ---- client -------------------------------------------------------------------------------

def test_client_refuses_without_a_key():
    llm = load("openrouter")
    with pytest.raises(llm.ConfigError):
        llm.client()


def test_describe_reports_provider_and_labels():
    d = load("openrouter", OPENROUTER_KEY="x").describe()
    assert d["provider"] == "openrouter" and d["has_key"] is True
    assert {"id": "deepseek/deepseek-v4.1-flash", "label": "deepseek-v4.1-flash"} in d["models"]


