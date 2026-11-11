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


# ---- the job's `if:` condition, evaluated for each event ---------------------------------------
def _job_if():
    m = re.search(r"\n    if: >-\n((?:      .*\n)+)", WF)
    return " ".join(l.strip() for l in m.group(1).splitlines())


def job_runs(action, label=None):
    """Evaluate the GitHub expression the way Actions does (string == is case-insensitive)."""
    expr = _job_if().lower().replace("''", "\\'")   # '' is an escaped quote inside an Actions string
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr)
    expr = expr.replace("fromjson(", "_fromjson(").replace("contains(", "_contains(")
    expr = expr.replace("github.event.action", "_action").replace("github.event.label.name", "_label")
    ns = {"_fromjson": json.loads, "_action": action.lower(), "_label": (label or "").lower(),
          "_contains": lambda hay, needle: any(str(h).lower() == needle for h in hay)}
    return eval(expr, {"__builtins__": {}}, ns)


def test_the_job_only_starts_for_events_that_arm_or_disarm():
    assert job_runs("synchronize") and job_runs("converted_to_draft")
    assert job_runs("labeled", "automerge") and job_runs("unlabeled", "automerge")
    for hold in ("hold", "Hold", "on-hold", "On Hold", "do-not-merge", "don't-merge"):
        assert job_runs("labeled", hold), hold
    assert not job_runs("labeled", "bug")            # unrelated labels never start (or cancel) a run
    assert not job_runs("unlabeled", "hold")         # lifting a hold does not arm by itself
    assert not job_runs("opened") and not job_runs("reopened") and not job_runs("ready_for_review")


def test_workflow_shape_is_fork_safe_and_serialised_per_pr():
    assert "pull_request_target:" in WF
    assert "types: [labeled, unlabeled, synchronize, converted_to_draft]" in WF
    assert "actions/checkout" not in WF                       # never checks out PR code with a write token
    assert "${{ github.event.pull_request.title" not in WF and "head.ref" not in WF
    assert "group: automerge-pr-${{ github.event.pull_request.number }}" in WF
    assert "cancel-in-progress: true" in WF
    perms = WF[WF.index("permissions:"):WF.index("jobs:")]
    assert "contents: write" in perms and "pull-requests: write" in perms and perms.count(":") == 3


# ---- the step's shell script, run against a fake gh ---------------------------------------------
FAKE_GH = r'''#!/usr/bin/env bash
# Fake gh: state lives in $STATE (the REST pull JSON); every call is logged to $LOG with its token.
who=GITHUB_TOKEN; [ "${GH_TOKEN:-}" = "pat-secret" ] && who=PAT
echo "$who $*" >> "$LOG"
if [ "$1" = api ] && [ "$2" = "-X" ]; then             # DELETE a label
  lbl="${4##*/}"; jq --arg l "$lbl" '.labels |= map(select(.name != $l))' "$STATE" > "$STATE.t" && mv "$STATE.t" "$STATE"; exit 0
elif [ "$1" = api ]; then
  jq -r "$4" "$STATE"; exit 0
elif [ "$1 $2" = "pr merge" ] && [ "$3" = "--disable-auto" ]; then
  [ -n "${FAIL_DISABLE_FOR:-}" ] && [ "$who" = "$FAIL_DISABLE_FOR" ] && exit 1
  jq '.auto_merge = null' "$STATE" > "$STATE.t" && mv "$STATE.t" "$STATE"; exit 0
elif [ "$1 $2" = "pr merge" ]; then
  [ -n "${FAIL_ARM_FOR:-}" ] && [ "$who" = "$FAIL_ARM_FOR" ] && exit 1
  jq --arg w "$who" '.auto_merge = {"by": $w}' "$STATE" > "$STATE.t" && mv "$STATE.t" "$STATE"; exit 0
fi
echo "fake gh: unhandled $*" >&2; exit 2
'''


def _script():
    m = re.search(r"\n( +)# --- automerge-reconcile:begin ---\n(.*?)\n +# --- automerge-reconcile:end ---", WF, re.S)
    return textwrap.dedent(m.group(1) + "# begin\n" + m.group(2))


def run_event(tmp_path, action, *, label=None, labels=("automerge",), draft=False, armed=False,
              head=HEAD, event_head=HEAD, pat="pat-secret", **env_extra):
    (tmp_path / "bin").mkdir(exist_ok=True)
    gh = tmp_path / "bin" / "gh"
    gh.write_text(FAKE_GH); gh.chmod(0o755)
    state = tmp_path / "pr.json"
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


@needs_tools
def test_a_push_to_a_labelled_armed_pr_disarms_and_removes_the_label(tmp_path):   # the #200 hole
    p, s, calls = run_event(tmp_path, "synchronize", armed=True, head=NEW_HEAD, event_head=NEW_HEAD)
    assert p.returncode == 0, p.stderr
    assert s["auto_merge"] is None and "automerge" not in _labels(s)
    assert not any("--auto" in c and "--disable-auto" not in c for c in calls)   # never re-arms on a push
    assert calls.index(next(c for c in calls if "--disable-auto" in c)) < \
        calls.index(next(c for c in calls if "-X DELETE" in c))                   # disarm before unlabel


@needs_tools
def test_a_push_to_a_labelled_unarmed_pr_still_removes_the_label(tmp_path):
    p, s, calls = run_event(tmp_path, "synchronize", armed=False)
    assert p.returncode == 0, p.stderr
    assert s["auto_merge"] is None and "automerge" not in _labels(s)
    assert not any("pr merge" in c for c in calls)


@needs_tools
def test_a_push_to_an_unlabelled_pr_leaves_a_human_armed_merge_alone(tmp_path):
    p, s, calls = run_event(tmp_path, "synchronize", labels=(), armed=True)
    assert p.returncode == 0, p.stderr
    assert s["auto_merge"] is not None and not any("pr merge" in c or "DELETE" in c for c in calls)


@needs_tools
def test_the_automerge_label_arms_pinned_to_the_labelled_head_with_the_pat(tmp_path):
    p, s, calls = run_event(tmp_path, "labeled", label="automerge")
    assert p.returncode == 0, p.stderr
    assert s["auto_merge"] == {"by": "PAT"}
    assert any(c.startswith("PAT pr merge --auto --squash --match-head-commit " + HEAD) for c in calls)


@needs_tools
def test_arming_falls_back_to_github_token_when_the_pat_fails(tmp_path):
    p, s, _ = run_event(tmp_path, "labeled", label="automerge", FAIL_ARM_FOR="PAT")
    assert p.returncode == 0, p.stderr
    assert s["auto_merge"] == {"by": "GITHUB_TOKEN"} and "falling back to GITHUB_TOKEN" in p.stdout


@pytest.mark.parametrize("kw", [
    dict(labels=("automerge", "hold")),
    dict(labels=("automerge", "On Hold")),
    dict(labels=("automerge", "do_not_merge")),
    dict(draft=True),
    dict(labels=()),                              # label already removed again before the run started
    dict(head=NEW_HEAD),                          # pushed after the label was added
])
@needs_tools
def test_the_automerge_label_never_arms_a_held_draft_or_moved_pr(tmp_path, kw):
    p, s, calls = run_event(tmp_path, "labeled", label="automerge", **kw)
    assert p.returncode == 0, p.stderr
    assert s["auto_merge"] is None
    assert not any("--auto " in c for c in calls)


@pytest.mark.parametrize("action,label", [("labeled", "hold"), ("labeled", "do-not-merge"),
                                          ("unlabeled", "automerge"), ("converted_to_draft", None)])
@needs_tools
def test_hold_unlabel_and_draft_disarm(tmp_path, action, label):
    labels = ("automerge", label) if action == "labeled" else ()
    p, s, calls = run_event(tmp_path, action, label=label, labels=labels, armed=True)
    assert p.returncode == 0, p.stderr
    assert s["auto_merge"] is None
    assert not any("--auto " in c for c in calls)


@needs_tools
def test_disarm_retries_with_the_pat_and_fails_loudly_if_still_armed(tmp_path):
    p, s, calls = run_event(tmp_path, "labeled", label="hold", labels=("hold",), armed=True,
                            FAIL_DISABLE_FOR="GITHUB_TOKEN")
    assert p.returncode == 0, p.stderr
    assert s["auto_merge"] is None and any(c.startswith("PAT pr merge --disable-auto") for c in calls)

    p, s, _ = run_event(tmp_path, "labeled", label="hold", labels=("hold",), armed=True, pat="",
                        FAIL_DISABLE_FOR="GITHUB_TOKEN")
    assert p.returncode != 0 and "could not disarm" in p.stdout
