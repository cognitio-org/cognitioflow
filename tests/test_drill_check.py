"""The daily drill check (scripts/drill_check.py): it opens Today, the due cards, a quiz, one rating and the mock
papers for every course with model calls blocked, passes when they open, and fails loudly when one does not."""
import importlib
import os
import sys

import pytest

import run

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
drill_check = importlib.import_module("drill_check")


@pytest.fixture
def course(client):
    cid = client.post("/api/courses", json={"name": "Drill Law"}).json()["id"]
    for i in range(3):
        client.post(f"/api/courses/{cid}/cards", json={"front": f"Q{i}", "back": f"A{i}", "week": "1"})
    return cid


def test_it_passes_when_the_drill_opens_and_never_calls_a_model(course, monkeypatch, capsys):
    monkeypatch.setattr(run, "client", run.client)   # the script blocks it; put it back afterwards
    assert drill_check.main() == 0
    out = capsys.readouterr().out
    assert f"{course} · 3 due" in out and "rating saved" in out and out.strip().endswith("drill and mock open")
    assert "Q0" not in out and "A0" not in out   # counts only, never content


def test_it_fails_when_something_he_drills_with_breaks(course, monkeypatch, capsys):
    monkeypatch.setattr(run, "client", run.client)
    def broken(*a, **k): raise RuntimeError("boom")
    monkeypatch.setattr(run.schedule, "next_review", broken)
    assert drill_check.main() == 1
    assert "rating a card 500" in capsys.readouterr().out


def test_the_workflow_runs_daily_on_a_throwaway_branch_and_opens_an_issue():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".github", "workflows", "drill-check.yml")
    wf = open(path).read()
    assert 'cron: "0 4 * * *"' in wf and "workflow_dispatch" in wf
    assert "Create Neon branch of production" in wf and "python scripts/drill_check.py" in wf
    tail = wf[wf.index("- name: Delete Neon branch"):]
    assert "if: always()" in tail and "-X DELETE" in tail and "- name:" not in tail[10:]   # deleting is the last step, always
    assert "gh issue create" in wf and "issues: write" in wf and "contents: read" in wf
    assert "::add-mask::" in wf                                                             # the URI never prints
