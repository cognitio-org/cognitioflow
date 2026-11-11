"""The automerge workflow (.github/workflows/automerge.yml) arms GitHub auto-merge only on a fresh
`automerge` label at an unchanged head, and DISARMS on a push, a hold label, label removal or draft.
#200 merged code the council never reviewed because a push re-armed auto-merge; these tests run the
workflow's real job condition and real shell script against a fake `gh` for each event.

No database needed: run alone with `pytest --noconftest tests/test_automerge_workflow.py`."""
import json
import os
import re
import shutil
import subprocess
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
WF = open(os.path.join(ROOT, ".github", "workflows", "automerge.yml")).read()
HEAD, NEW_HEAD = "a" * 40, "b" * 40

needs_tools = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")), reason="needs bash + jq")


# ---- the job's `if:` and concurrency group, evaluated for each event ----------------------------
def _job_if():
    m = re.search(r"\n    if: >-\n((?:      .*\n)+)", WF)
    return " ".join(l.strip() for l in m.group(1).splitlines())


def _group_expr():
    m = re.search(r"\n      group: \$\{\{ (.*) \}\}\n", WF)
    return m.group(1)


def _contains(hay, needle):
    """Actions contains(): substring for strings, membership for arrays; case-insensitive."""
    if isinstance(hay, str):
        return needle.lower() in hay.lower()
    return any(str(h).lower() == needle.lower() for h in hay)


def _eval(expr, action, label=None, number=7, run_id=999):
    """Evaluate a GitHub expression the way Actions does (== on strings is case-insensitive, so we
    lower-case everything; && / || return operands like Python's and / or)."""
    expr = expr.replace("''", "\\'")                # '' is an escaped quote inside an Actions string
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr)
    expr = expr.replace("fromJSON(", "_fromjson(").replace("contains(", "_contains(").replace("format(", "_format(")
    expr = expr.replace("github.event.action", "_action").replace("github.event.label.name", "_label")
    expr = expr.replace("github.event.pull_request.number", "_number").replace("github.run_id", "_run_id")
    expr = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", lambda m: repr(m.group(1).replace("\\'", "'").lower()), expr)
    ns = {"_fromjson": json.loads, "_contains": _contains, "_action": action.lower(),
          "_label": (label or "").lower(), "_number": number, "_run_id": run_id,
          "_format": lambda f, *a: f.format(*a)}
    return eval(expr, {"__builtins__": {}}, ns)


def job_runs(action, label=None):
    return bool(_eval(_job_if(), action, label))


def group_of(action, label=None, run_id=999):
    return _eval(_group_expr(), action, label, run_id=run_id)


# council_merge.py's hold set, copied verbatim (_norm_label + HOLD_LABELS): the workflow must agree.
COUNCIL_HOLD_LABELS = {"hold", "on-hold", "do-not-merge", "dont-merge", "don't-merge"}


def council_norm_label(name):
    return re.sub(r"[\s_]+", "-", (name or "").strip().lower())


HOLD_SPELLINGS = ["hold", "Hold", "on-hold", "On Hold", "on_hold", "do-not-merge", "do not merge",
                  "do-not merge", "Do_Not-Merge", "DO  NOT__MERGE", "dont-merge", "don't merge", " hold "]
NOT_HOLD = ["bug", "on - hold", "household", "merge-conflict", "no-hold-needed"]


def test_spellings_match_the_council():
    assert all(council_norm_label(s) in COUNCIL_HOLD_LABELS for s in HOLD_SPELLINGS)
    assert not any(council_norm_label(s) in COUNCIL_HOLD_LABELS for s in NOT_HOLD)


def test_the_job_starts_for_every_event_that_can_arm_or_disarm():
    assert job_runs("synchronize") and job_runs("converted_to_draft")
    assert job_runs("labeled", "automerge") and job_runs("unlabeled", "automerge")
    for hold in HOLD_SPELLINGS:                      # every spelling the council treats as a hold
        assert job_runs("labeled", hold), hold
    assert not job_runs("labeled", "bug")
    assert not job_runs("unlabeled", "hold")         # lifting a hold does not arm by itself
    assert not job_runs("opened") and not job_runs("reopened") and not job_runs("ready_for_review")


def test_only_arm_runs_share_a_group_so_no_event_can_supersede_a_disarm():
    assert group_of("labeled", "automerge") == group_of("labeled", "Automerge", run_id=1) == "automerge-arm-pr-7"
    for action, label in [("synchronize", None), ("converted_to_draft", None), ("unlabeled", "automerge"),
                          ("labeled", "hold"), ("labeled", "merge-conflict"), ("labeled", "bug")]:
        g1, g2 = group_of(action, label, run_id=1), group_of(action, label, run_id=2)
        assert g1 != g2 and "arm-pr" not in g1, (action, label)


def test_workflow_shape_is_fork_safe():
    assert "pull_request_target:" in WF
    assert "types: [labeled, unlabeled, synchronize, converted_to_draft]" in WF
    assert "actions/checkout" not in WF                       # never checks out PR code with a write token
    assert "${{ github.event.pull_request.title" not in WF and "head.ref" not in WF
    assert "cancel-in-progress: true" in WF and "timeout-minutes:" in WF
    perms = WF[WF.index("permissions:"):WF.index("jobs:")]
    assert "contents: write" in perms and "pull-requests: write" in perms and perms.count(":") == 3


# ---- the step's shell script, run against a fake gh ---------------------------------------------
FAKE_GH = r"""#!/usr/bin/env bash
# Fake gh: state lives in $STATE (the REST pull JSON); every call is logged to $LOG with its token.
# Failure injection: FAIL_READS=N fails the first N state reads (N=99: always); FAIL_DISABLE_FOR /
# FAIL_ARM_FOR fail every call made with that token (ALL: every token); ARM_TAKES_EFFECT_BUT_FAILS
# arms but exits 1; STALE_ARMED_AFTER=N reports auto_merge null on every read after the Nth; FAIL_READS_AFTER=N fails every read after the Nth; FAIL_DELETE fails label removal.
who=GITHUB_TOKEN; [ "${GH_TOKEN:-}" = "pat-secret" ] && who=PAT
echo "$who $*" >> "$LOG"
bump() { local n; n=$(cat "$STATE.$1" 2>/dev/null || echo 0); echo $((n + 1)) > "$STATE.$1"; echo $((n + 1)); }
if [ "$1" = api ] && [ "$2" = "-X" ]; then             # DELETE a label
  [ -n "${FAIL_DELETE:-}" ] && exit 1
  lbl="${4##*/}"; jq --arg l "$lbl" '.labels |= map(select(.name != $l))' "$STATE" > "$STATE.t" && mv "$STATE.t" "$STATE"; exit 0
elif [ "$1" = api ]; then
  n="$(bump reads)"
  if [ "$n" -le "${FAIL_READS:-0}" ]; then echo "HTTP 502" >&2; exit 1; fi
  if [ -n "${FAIL_READS_AFTER:-}" ] && [ "$n" -gt "$FAIL_READS_AFTER" ]; then echo "HTTP 502" >&2; exit 1; fi
  if [ -n "${STALE_ARMED_AFTER:-}" ] && [ "$n" -gt "$STALE_ARMED_AFTER" ] && ! [ -f "$STATE.disarmed" ]; then
    jq '.auto_merge = null' "$STATE" | jq -r "$4"; exit 0
  fi
  jq -r "$4" "$STATE"; exit 0
elif [ "$1 $2" = "pr merge" ] && [ "$3" = "--disable-auto" ]; then
  [ -n "${FAIL_DISABLE_FOR:-}" ] && [ "$who" = "$FAIL_DISABLE_FOR" ] && exit 1
  jq '.auto_merge = null' "$STATE" > "$STATE.t" && mv "$STATE.t" "$STATE"; touch "$STATE.disarmed"; exit 0
elif [ "$1 $2" = "pr merge" ]; then
  [ -n "${FAIL_ARM_FOR:-}" ] && { [ "$who" = "$FAIL_ARM_FOR" ] || [ "$FAIL_ARM_FOR" = ALL ]; } && exit 1
  if [ -n "${ARM_TAKES_EFFECT_BUT_FAILS:-}" ]; then
    jq --arg w "$who" '.auto_merge = {"by": $w}' "$STATE" > "$STATE.t" && mv "$STATE.t" "$STATE"; exit 1
  fi
  jq --arg w "$who" '.auto_merge = {"by": $w}' "$STATE" > "$STATE.t" && mv "$STATE.t" "$STATE"
  # RACE_AFTER_ARM: simulate a concurrent change landing while arming (jq filter on the state).
  if [ -n "${RACE_AFTER_ARM:-}" ]; then jq "$RACE_AFTER_ARM" "$STATE" > "$STATE.t" && mv "$STATE.t" "$STATE"; fi
  exit 0
fi
echo "fake gh: unhandled $*" >&2; exit 2
"""


def _script():
    m = re.search(r"\n( +)# --- automerge-reconcile:begin ---\n(.*?)\n +# --- automerge-reconcile:end ---", WF, re.S)
    return textwrap.dedent(m.group(1) + "# begin\n" + m.group(2))


def run_event(tmp_path, action, *, label=None, labels=("automerge",), draft=False, armed=False,
              head=HEAD, event_head=HEAD, pat="pat-secret", **env_extra):
    (tmp_path / "bin").mkdir(exist_ok=True)
    gh = tmp_path / "bin" / "gh"
    gh.write_text(FAKE_GH); gh.chmod(0o755)
    slp = tmp_path / "bin" / "sleep"                   # retries back off with sleep: make it instant
    slp.write_text("#!/bin/sh\necho \"sleep $*\" >> \"$LOG\"\n"); slp.chmod(0o755)
    state = tmp_path / "pr.json"
    for f in tmp_path.glob("pr.json.*"):
        f.unlink()
    state.write_text(json.dumps({"draft": draft, "head": {"sha": head},
                                 "auto_merge": {"by": "x"} if armed else None,
                                 "labels": [{"name": n} for n in labels]}))
    log = tmp_path / "gh.log"; log.write_text("")
    env = {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "STATE": str(state), "LOG": str(log),
           "PAT": pat, "GITHUB_TOKEN": "gh-token", "REPO": "o/r", "PR_NUMBER": "7",
           "PR_URL": "https://github.com/o/r/pull/7", "EVENT_ACTION": action, "EVENT_LABEL": label or "",
           "EVENT_HEAD_SHA": event_head, **env_extra}
    p = subprocess.run(["bash", "-c", _script()], env=env, capture_output=True, text=True)
    s = json.loads(state.read_text())
    return p, s, log.read_text().splitlines()


def _labels(s):
    return [l["name"] for l in s["labels"]]


def _armed_calls(calls):
    return [c for c in calls if "pr merge --auto" in c]


# -- pushes ------------------------------------------------------------------------------------------
@needs_tools
def test_a_push_to_a_labelled_armed_pr_disarms_and_removes_the_label(tmp_path):   # the #200 hole
    p, s, calls = run_event(tmp_path, "synchronize", armed=True, head=NEW_HEAD, event_head=NEW_HEAD)
    assert p.returncode == 0, p.stdout + p.stderr
    assert s["auto_merge"] is None and "automerge" not in _labels(s)
    assert not _armed_calls(calls)                                                 # never re-arms on a push
    assert calls.index(next(c for c in calls if "--disable-auto" in c)) < \
        calls.index(next(c for c in calls if "-X DELETE" in c))                   # disarm before unlabel


@needs_tools
def test_a_push_to_a_labelled_unarmed_pr_still_removes_the_label(tmp_path):
    p, s, calls = run_event(tmp_path, "synchronize", armed=False)
    assert p.returncode == 0, p.stdout + p.stderr
    assert s["auto_merge"] is None and "automerge" not in _labels(s)
    assert not any("pr merge" in c for c in calls)


@needs_tools
def test_a_push_disarms_even_when_the_label_is_already_gone(tmp_path):
    # Review finding: 'automerge' removed (that run U is superseded/cancelled) then a push. A cancelled
    # run changes nothing, so the push run S sees: no label, still armed. It must disarm.
    p, s, calls = run_event(tmp_path, "synchronize", labels=(), armed=True, head=NEW_HEAD, event_head=NEW_HEAD)
    assert p.returncode == 0, p.stdout + p.stderr
    assert s["auto_merge"] is None
    assert not any("DELETE" in c for c in calls)


# -- arming ------------------------------------------------------------------------------------------
@needs_tools
def test_the_automerge_label_arms_pinned_to_the_labelled_head_with_the_pat(tmp_path):
    p, s, calls = run_event(tmp_path, "labeled", label="automerge")
    assert p.returncode == 0, p.stdout + p.stderr
    assert s["auto_merge"] == {"by": "PAT"}
    assert any(c.startswith("PAT pr merge --auto --squash --match-head-commit " + HEAD) for c in calls)


@needs_tools
def test_arming_falls_back_to_github_token_when_the_pat_fails(tmp_path):
    p, s, _ = run_event(tmp_path, "labeled", label="automerge", FAIL_ARM_FOR="PAT")
    assert p.returncode == 0, p.stdout + p.stderr
    assert s["auto_merge"] == {"by": "GITHUB_TOKEN"} and "falling back to GITHUB_TOKEN" in p.stdout


@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("kw", [
    dict(labels=("automerge", "hold")),
    dict(labels=("automerge", "On Hold")),
    dict(labels=("automerge", "do_not_merge")),
    dict(labels=("automerge", "Do-Not merge")),
    dict(draft=True),
    dict(labels=()),                              # label already removed again before the run started
    dict(head=NEW_HEAD),                          # pushed after the label was added
])
@needs_tools
def test_the_automerge_label_never_leaves_a_held_draft_unlabelled_or_moved_pr_armed(tmp_path, kw, armed):
    # armed=True stands for "this run superseded a disarm run": it must disarm, not just skip arming.
    p, s, calls = run_event(tmp_path, "labeled", label="automerge", armed=armed, **kw)
    assert p.returncode == 0, p.stdout + p.stderr
    assert s["auto_merge"] is None
    assert not _armed_calls(calls)
    if kw.get("head") == NEW_HEAD:
        assert "automerge" not in _labels(s)      # a missed push: the council must re-review


@pytest.mark.parametrize("race", ['.labels += [{"name": "hold"}]', '.draft = true', '.labels = []',
                                  '.head.sha = "%s"' % NEW_HEAD])
@needs_tools
def test_a_change_that_lands_while_arming_disarms_again(tmp_path, race):
    p, s, calls = run_event(tmp_path, "labeled", label="automerge", RACE_AFTER_ARM=race)
    assert p.returncode == 0, p.stdout + p.stderr
    assert _armed_calls(calls) and s["auto_merge"] is None


# -- holds, unlabel, draft ----------------------------------------------------------------------------
@pytest.mark.parametrize("action,label", [("labeled", "hold"), ("labeled", "do-not-merge"),
                                          ("labeled", "do-not merge"), ("labeled", " On_Hold "),
                                          ("unlabeled", "automerge"), ("converted_to_draft", None)])
@needs_tools
def test_hold_unlabel_and_draft_disarm(tmp_path, action, label):
    labels = ("automerge", label) if action == "labeled" else ()
    p, s, calls = run_event(tmp_path, action, label=label, labels=labels, armed=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert s["auto_merge"] is None
    assert not _armed_calls(calls)


@pytest.mark.parametrize("label", HOLD_SPELLINGS + NOT_HOLD)
@needs_tools
def test_the_script_holds_exactly_what_the_council_holds(tmp_path, label):
    p, s, _ = run_event(tmp_path, "labeled", label=label, labels=("automerge", label), armed=True)
    assert p.returncode == 0, p.stdout + p.stderr
    is_hold = council_norm_label(label) in COUNCIL_HOLD_LABELS
    assert (s["auto_merge"] is None) == is_hold, label


@needs_tools
def test_a_merge_related_label_disarms_a_draft(tmp_path):
    p, s, _ = run_event(tmp_path, "labeled", label="merge-conflict", labels=("automerge", "merge-conflict"),
                        armed=True, draft=True)
    assert p.returncode == 0 and s["auto_merge"] is None


# -- API failures fail closed --------------------------------------------------------------------------
@needs_tools
def test_disarm_retries_with_the_pat_and_fails_loudly_if_still_armed(tmp_path):
    p, s, calls = run_event(tmp_path, "labeled", label="hold", labels=("hold",), armed=True,
                            FAIL_DISABLE_FOR="GITHUB_TOKEN")
    assert p.returncode == 0, p.stdout + p.stderr
    assert s["auto_merge"] is None and any(c.startswith("PAT pr merge --disable-auto") for c in calls)

    p, s, _ = run_event(tmp_path, "labeled", label="hold", labels=("hold",), armed=True, pat="",
                        FAIL_DISABLE_FOR="GITHUB_TOKEN")
    assert p.returncode != 0 and "could not be confirmed off" in p.stdout


@needs_tools
def test_a_transient_read_failure_is_retried(tmp_path):
    p, s, calls = run_event(tmp_path, "synchronize", armed=True, FAIL_READS="2")
    assert p.returncode == 0, p.stdout + p.stderr
    assert s["auto_merge"] is None and "automerge" not in _labels(s)
    assert sum(1 for c in calls if c.startswith("sleep")) == 2


@pytest.mark.parametrize("action,label", [("synchronize", None), ("labeled", "hold"),
                                          ("labeled", "automerge"), ("unlabeled", "automerge")])
@needs_tools
def test_an_unreadable_pr_is_disarmed_blind_and_the_job_fails(tmp_path, action, label):
    p, s, calls = run_event(tmp_path, action, label=label, armed=True, FAIL_READS="99")
    assert p.returncode != 0
    assert s["auto_merge"] is None and not _armed_calls(calls)
    if action == "synchronize":
        assert "automerge" not in _labels(s)


@needs_tools
def test_a_disarm_whose_state_reads_fail_afterwards_still_fails_red(tmp_path):
    # read 1 succeeds (armed), every later read fails: the disarm cannot be confirmed -> red.
    p, s, calls = run_event(tmp_path, "unlabeled", label="automerge", labels=(), armed=True,
                            FAIL_READS_AFTER="1")
    assert p.returncode != 0 and "could not be confirmed off" in p.stdout
    assert s["auto_merge"] is None                     # it did try (with both tokens) — just could not confirm
    assert any(c.startswith("PAT pr merge --disable-auto") for c in calls)


@pytest.mark.parametrize("mode", [dict(FAIL_ARM_FOR="ALL"), dict(ARM_TAKES_EFFECT_BUT_FAILS="1")])
@needs_tools
def test_a_failed_arm_is_confirmed_off_and_goes_red(tmp_path, mode):
    p, s, _ = run_event(tmp_path, "labeled", label="automerge", **mode)
    assert p.returncode != 0
    assert s["auto_merge"] is None


@needs_tools
def test_a_stale_not_armed_read_after_arming_still_disarms(tmp_path):
    # read 1 = pre-arm state; reads after that wrongly say "not armed" while a hold landed meanwhile.
    p, s, calls = run_event(tmp_path, "labeled", label="automerge", STALE_ARMED_AFTER="1",
                            RACE_AFTER_ARM='.labels += [{"name": "hold"}]')
    assert p.returncode == 0, p.stdout + p.stderr
    assert _armed_calls(calls) and s["auto_merge"] is None
    assert any("--disable-auto" in c for c in calls)
