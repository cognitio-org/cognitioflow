"""scripts/pr_worthiness.py: rules, verdicts and the comment. No network; fake secrets are assembled at runtime."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pr_worthiness as pw  # noqa: E402


def diff_for(path: str, added=(), removed=()) -> str:
    body = "".join(f"-{l}\n" for l in removed) + "".join(f"+{l}\n" for l in added)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{body}"


def f(path, additions=1, deletions=0):
    return {"path": path, "additions": additions, "deletions": deletions}


FAKE_ANTHROPIC = "sk-" + "ant-" + "api03-" + "A1b2" * 12
FAKE_NEON = "npg" + "_" + "Q7w8E9r0T1y2"


def test_css_only_change_scores_full_marks():
    assert pw.rules([f("static/index.html", 20, 18)], diff_for("static/index.html", ["  .toast{opacity:1}"])) == (100, [], [])


@pytest.mark.parametrize("line", [f'ANTHROPIC_API_KEY="{FAKE_ANTHROPIC}"', f"DATABASE_URL=postgresql://neondb_owner:{FAKE_NEON}@ep-x.neon.tech/db",
                                  "-----BEGIN " + "PRIVATE KEY-----"])
def test_leaked_credentials_block(line):
    score, _, blocking = pw.rules([f("run.py")], diff_for("run.py", [line]))
    assert blocking and score <= 20


@pytest.mark.parametrize("line", ['os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")',
                                  "postgresql://cf:cf@localhost:5432/cognitioflow",
                                  "postgresql://u:hunter2secret@localhost:1/none",
                                  "postgresql://user:${PASSWORD}@ep-x.neon.tech/db"])
def test_test_fixtures_and_placeholders_are_not_secrets(line):
    assert pw.rules([f("tests/test_x.py")], diff_for("tests/test_x.py", [line]))[2] == []


def test_committed_env_and_data_files_block_but_the_example_does_not():
    assert pw.rules([f(".env")], "")[2]
    assert pw.rules([f("data/cognitioflow.db")], "")[2]
    assert pw.rules([f(".env.local.example")], "")[2] == []


def test_sensitive_areas_lower_the_score():
    score, findings, blocking = pw.rules([f("auth.py"), f("infra/backup.sh")], "")
    assert score == 100 - 12 - 8 and not blocking
    assert [label for _, label in findings] == ["sign-in and sessions", "cloud infrastructure"]


def test_risky_patterns_count_only_when_added():
    wf = ".github/workflows/deploy.yml"
    removed = pw.rules([f(wf)], diff_for(wf, removed=["            --allow-unauthenticated \\"]))
    added = pw.rules([f(wf)], diff_for(wf, added=["            --allow-unauthenticated \\"]))
    # deploy.yml now also trips the CHECKER row (-20) on top of the workflow row (-8),
    # so both drop by 20; the 10-point gap is the point: the risky line counts only when added.
    assert removed[0] == 100 - 20 - 8 and added[0] == 100 - 20 - 8 - 10


def test_verdicts():
    assert pw.decide("success", 90, [], []).verdict == "approve"
    assert pw.decide("failure", 100, [], []).verdict == "hold"
    assert pw.decide("cancelled", 100, [], []).explanation == "Hold: the tests did not run (cancelled)."
    assert pw.decide("success", 74, [(26, "x")], []).verdict == "hold"
    assert pw.decide("success", 75, [(25, "x")], []).verdict == "approve"
    held = pw.decide("success", 95, [], [], {"verdict": "hold", "security": 60, "explanation": "Drops the auth check on /api."})
    assert (held.verdict, held.security, held.explanation) == ("hold", 60, "Drops the auth check on /api.")
    assert pw.decide("success", 20, [], ["it adds .env, which must never be committed"]).explanation.startswith("Hold: it adds .env")


def test_model_reply_parsing():
    assert pw.parse_model('Sure.\n{"verdict": "APPROVE", "security": 140, "explanation": "CSS only."}') == \
        {"verdict": "approve", "security": 100, "explanation": "CSS only."}
    with pytest.raises(Exception):
        pw.parse_model("no json here")


def test_comment_is_short_and_marked():
    a = pw.decide("success", 84, [(8, "the deploy workflow"), (8, "cloud infrastructure")], [])
    body = pw.render(a, "4b9d6e0c0ffee", [f(".github/workflows/deploy.yml", 22), f("infra/backup.sh", 140)])
    assert body.startswith(pw.MARKER) and "✅ **Approve for deployment** · security **84%**" in body
    assert "4b9d6e0 · tests: success · 2 files, +162 −0" in body and len(body.splitlines()) == 4


def test_long_model_explanations_are_trimmed_at_a_word():
    long = "Adds backup and restore with least-privilege IAM, no-overwrite writes and restore safeguards, " * 3
    out = pw.parse_model('{"verdict": "approve", "security": 80, "explanation": "%s"}' % long)["explanation"]
    assert len(out) <= 181 and out.endswith("…") and not out[:-1].endswith(" ")


def test_changes_to_the_checker_are_always_held_for_a_person():
    score, findings, blocking = pw.rules([f("scripts/pr_worthiness.py")], "")
    a = pw.decide("success", score, findings, blocking)
    assert a.verdict == "hold" and "a person has to review it" in a.explanation


class FakeGh:
    def __init__(self, reviews):
        self.reviews, self.calls = reviews, []

    def __call__(self, *args):
        self.calls.append(args)
        return __import__("json").dumps([self.reviews]) if args[:1] == ("api",) and args[1].endswith("/reviews") and len(args) > 2 and args[2] == "--paginate" else "{}"


def test_approve_once_per_commit(monkeypatch):
    a = pw.decide("success", 90, [], [])
    fake = FakeGh([])
    monkeypatch.setattr(pw, "gh", fake)
    assert pw.approve("o/r", 7, "abc123", a) == "approved"
    assert any("event=APPROVE" in c for c in fake.calls[-1])
    fake = FakeGh([{"id": 1, "user": {"login": pw.BOT}, "state": "APPROVED", "commit_id": "abc123"}])
    monkeypatch.setattr(pw, "gh", fake)
    assert pw.approve("o/r", 7, "abc123", a) == "already approved" and len(fake.calls) == 1


def test_hold_withdraws_earlier_bot_approvals_but_not_peoples(monkeypatch):
    fake = FakeGh([{"id": 1, "user": {"login": pw.BOT}, "state": "APPROVED", "commit_id": "old"},
                   {"id": 2, "user": {"login": "TEJ42000"}, "state": "APPROVED", "commit_id": "old"}])
    monkeypatch.setattr(pw, "gh", fake)
    out = pw.approve("o/r", 7, "new", pw.decide("failure", 90, [], []))
    assert out == "not approved, 1 earlier approval(s) withdrawn"
    assert [c for c in fake.calls if "/dismissals" in " ".join(c)][0][3].endswith("/reviews/1/dismissals")


def test_sweep_plan_skips_drafts_pending_tests_and_assessed_commits():
    prs = [{"number": 1, "isDraft": True, "headRefOid": "aaaaaaa1"}, {"number": 2, "isDraft": False, "headRefOid": "bbbbbbb2"},
           {"number": 3, "isDraft": False, "headRefOid": "ccccccc3"}, {"number": 4, "isDraft": False, "headRefOid": "ddddddd4"}]
    todo, skipped = pw.plan(prs, {1: "success", 2: "pending", 3: "success", 4: "failure"}, {3: {"ccccccc"}})
    assert todo == [(4, "failure")]
    assert skipped == {1: "draft", 2: "tests pending", 3: "latest commit already assessed"}
    assert pw.plan(prs, {3: "success"}, {3: {"ccccccc"}}, force=True)[0] == [(3, "success")]



def test_default_model_is_haiku(monkeypatch):
    import importlib
    monkeypatch.delenv("PR_CHECK_MODEL", raising=False)
    assert importlib.reload(pw).MODEL == "claude-haiku-4-5"
    monkeypatch.setenv("PR_CHECK_MODEL", "")
    assert importlib.reload(pw).MODEL == "claude-haiku-4-5"


def test_model_ids_with_a_slash_go_through_openrouter(monkeypatch):
    import types as pytypes
    seen = {}
    class FakeAnthropic:
        def __init__(self, **kw):
            seen.update(kw)
            self.messages = pytypes.SimpleNamespace(create=lambda **k: seen.setdefault("create", k) and pytypes.SimpleNamespace(
                content=[pytypes.SimpleNamespace(text='{"verdict": "approve", "security": 90, "explanation": "Docs only."}')]))
    monkeypatch.setitem(sys.modules, "anthropic", pytypes.SimpleNamespace(Anthropic=FakeAnthropic))
    monkeypatch.setattr(pw, "MODEL", "z-ai/glm-5.3-flash")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    assert pw.model_key_present()
    out, used = pw.model_review("Docs", "", [f("README.md")], diff_for("README.md", ["x"]), [])
    assert out["verdict"] == "approve" and seen["base_url"] == "https://openrouter.ai/api" and seen["auth_token"] == "or-test"
    assert seen["create"]["model"] == "z-ai/glm-5.3-flash" and used == "z-ai/glm-5.3-flash"
    monkeypatch.setattr(pw, "MODEL", "claude-haiku-4-5")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert not pw.model_key_present()


def test_risky_lines_in_docs_and_tests_do_not_count():
    assert pw.rules([f("README.md")], diff_for("README.md", ["AUTH=off signs you in as the first address"]))[0] == 100
    assert pw.rules([f("tests/test_x.py")], diff_for("tests/test_x.py", ["subprocess.run(cmd, shell=True)"]))[0] == 100
    assert pw.rules([f("run.py")], diff_for("run.py", ["subprocess.run(cmd, shell=True)"]))[0] == 92


def test_using_the_public_helper_is_not_a_change_to_public_routes():
    use = pw.rules([f("auth.py")], diff_for("auth.py", ['        if user is None and not _public(scope["path"]):']))
    define = pw.rules([f("auth.py")], diff_for("auth.py", ["def _public(path: str) -> bool:"]))
    assert use[0] == 100 - 12 and define[0] == 100 - 12 - 8


# --- the fallback: when the Anthropic models are used up, another provider finishes the job -------

def _fake_anthropic(monkeypatch, answers):
    """answers: {model_id: Exception to raise | text to return}. Records the order models were tried."""
    import types as pytypes
    tried = []

    class Rate(Exception):
        pass

    class Conn(Exception):
        pass

    def create(**kw):
        model = kw["model"]
        tried.append(model)
        got = answers[model]
        if isinstance(got, BaseException):
            raise got
        return pytypes.SimpleNamespace(content=[pytypes.SimpleNamespace(text=got)])

    class FakeAnthropic:
        def __init__(self, **kw):
            self.messages = pytypes.SimpleNamespace(create=create)

    monkeypatch.setitem(sys.modules, "anthropic", pytypes.SimpleNamespace(
        Anthropic=FakeAnthropic, RateLimitError=Rate, APIConnectionError=Conn))
    return tried, Rate, Conn


APPROVED = '{"verdict": "approve", "security": 90, "explanation": "Docs only."}'


def _both_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setattr(pw, "MODEL", "claude-haiku-4-5")
    monkeypatch.setattr(pw, "FALLBACK_MODEL", "z-ai/glm-5.3-flash")


def test_the_chain_is_the_primary_then_the_fallback(monkeypatch):
    _both_keys(monkeypatch)
    assert pw.model_chain() == ["claude-haiku-4-5", "z-ai/glm-5.3-flash"]


def test_a_model_without_its_key_is_not_in_the_chain(monkeypatch):
    _both_keys(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert pw.model_chain() == ["z-ai/glm-5.3-flash"], "an OpenRouter key alone must still work"
    assert pw.model_key_present()
    _both_keys(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert pw.model_chain() == ["claude-haiku-4-5"], "an Anthropic key alone must still work"


def test_a_fallback_equal_to_the_primary_is_not_tried_twice(monkeypatch):
    _both_keys(monkeypatch)
    monkeypatch.setattr(pw, "FALLBACK_MODEL", "claude-haiku-4-5")
    assert pw.model_chain() == ["claude-haiku-4-5"]


def test_a_used_up_anthropic_model_hands_over_to_openrouter(monkeypatch):
    _both_keys(monkeypatch)
    answers = {}
    tried, Rate, _ = _fake_anthropic(monkeypatch, answers)
    answers.update({"claude-haiku-4-5": Rate("429 rate limited"), "z-ai/glm-5.3-flash": APPROVED})
    out, used = pw.model_review("Docs", "", [f("README.md")], diff_for("README.md", ["x"]), [])
    assert tried == ["claude-haiku-4-5", "z-ai/glm-5.3-flash"], "the primary must be tried first"
    assert out["verdict"] == "approve"
    assert used == "z-ai/glm-5.3-flash", "the footer must name the model that answered"


def test_the_footer_names_the_model_that_answered(monkeypatch):
    a = pw.decide("success", 90, [], [], {"verdict": "approve", "security": 90, "explanation": "ok"},
                  model_name="z-ai/glm-5.3-flash")
    assert a.reviewer == "rules + z-ai/glm-5.3-flash"


def test_a_malformed_request_is_not_retried_on_the_fallback(monkeypatch):
    """A 400 means our own prompt is wrong; the fallback would fail identically."""
    _both_keys(monkeypatch)
    bad = Exception("bad request")
    bad.status_code = 400
    tried, _, _ = _fake_anthropic(monkeypatch, {"claude-haiku-4-5": bad, "z-ai/glm-5.3-flash": APPROVED})
    with pytest.raises(Exception):
        pw.model_review("Docs", "", [f("README.md")], diff_for("README.md", ["x"]), [])
    assert tried == ["claude-haiku-4-5"], "a 400 must not spend the fallback"


def test_worth_another_model_covers_exhaustion_and_unusable_replies_but_not_bad_input(monkeypatch):
    _, Rate, Conn = _fake_anthropic(monkeypatch, {})
    assert pw.worth_another_model(Rate("429"))
    assert pw.worth_another_model(Conn("unreachable"))
    assert pw.worth_another_model(ValueError("model reply had no security score")), \
        "an unusable reply is this model's fault, and another model may answer properly"
    for status, expected in [(429, True), (402, True), (401, True), (529, True), (503, True),
                             (400, False), (404, False), (422, False)]:
        e = Exception("x")
        e.status_code = status
        assert pw.worth_another_model(e) is expected, f"status {status}"


def test_an_unusable_reply_from_the_primary_hands_over_to_the_fallback(monkeypatch):
    """The #38 case, 2026-09-17: GLM answered with something parse_model could not read, and the
    whole model review was skipped — the verdict silently fell back to the rules alone."""
    _both_keys(monkeypatch)
    answers = {}
    tried, _, _ = _fake_anthropic(monkeypatch, answers)
    answers.update({"claude-haiku-4-5": "Sure! Here is my review: it looks fine to me.",
                    "z-ai/glm-5.3-flash": APPROVED})
    out, used = pw.model_review("Docs", "", [f("README.md")], diff_for("README.md", ["x"]), [])
    assert tried == ["claude-haiku-4-5", "z-ai/glm-5.3-flash"], "the unusable reply must not end the review"
    assert out["verdict"] == "approve" and used == "z-ai/glm-5.3-flash"


def test_an_unusable_reply_with_no_fallback_left_still_raises(monkeypatch):
    """Rules-only is the right outcome when nothing else can be asked — it just must not be the
    outcome while a second model is sitting there unused."""
    _both_keys(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    tried, _, _ = _fake_anthropic(monkeypatch, {"claude-haiku-4-5": "no json here"})
    with pytest.raises(ValueError):
        pw.model_review("Docs", "", [f("README.md")], diff_for("README.md", ["x"]), [])
    assert tried == ["claude-haiku-4-5"]


def test_an_openrouter_key_in_the_diff_blocks_the_pr():
    score, findings, blocking = pw.rules(
        [f("run.py")], diff_for("run.py", ["OPENROUTER_API_KEY = 'sk-or-v1-" + "a1b2c3d4" * 8 + "'"]))
    assert blocking, "a committed OpenRouter key must block"
    assert "OpenRouter" in blocking[0]


# --- a run must not stamp its tests result onto a commit that never saw those tests ---------------

def _pr_view_gh(head_sha, calls):
    """gh stub: `pr view` returns a PR at head_sha; everything else is recorded."""
    import json as _json

    def fake(*args):
        calls.append(args)
        if args[:2] == ("pr", "view"):
            return _json.dumps({"title": "t", "body": "", "headRefOid": head_sha, "files": [f("README.md")]})
        if args[:2] == ("pr", "diff"):
            return diff_for("README.md", ["x"])
        return "{}"
    return fake


def test_a_run_whose_commit_is_no_longer_the_head_stands_down(monkeypatch):
    calls = []
    monkeypatch.setattr(pw, "gh", _pr_view_gh("bbbbbbbb", calls))
    monkeypatch.setenv("HEAD_SHA", "aaaaaaaa")  # this run tested aaaaaaaa; the head moved to bbbbbbbb
    out = pw.assess_pr("o/r", 7, "success", use_model=False, do_post=True, do_approve=True)
    assert out is None, "a stale run must not produce a verdict"
    assert not any(c[:2] == ("pr", "diff") for c in calls), "it should stop before doing any work"
    assert not any("event=APPROVE" in " ".join(c) for c in calls), "and must never approve"


def test_a_run_on_the_current_head_still_assesses(monkeypatch):
    calls = []
    monkeypatch.setattr(pw, "gh", _pr_view_gh("aaaaaaaa", calls))
    monkeypatch.setenv("HEAD_SHA", "aaaaaaaa")
    out = pw.assess_pr("o/r", 7, "success", use_model=False, do_post=False, do_approve=False)
    assert out is not None and out.verdict == "approve"


def test_the_sweep_is_unaffected_because_it_sets_no_head_sha(monkeypatch):
    """The sweep reads the tests result from the current head's own checks, so it is already consistent."""
    calls = []
    monkeypatch.setattr(pw, "gh", _pr_view_gh("bbbbbbbb", calls))
    monkeypatch.delenv("HEAD_SHA", raising=False)
    out = pw.assess_pr("o/r", 7, "success", use_model=False, do_post=False, do_approve=False)
    assert out is not None and out.verdict == "approve"
