"""The cost log (approved 2026-09-30): every AI call leaves one ai_calls row of counts and names, never text,
and the weekly spend line adds them up without guessing at the ones whose cost is unknown."""
import time
from types import SimpleNamespace as NS
import unittest.mock as mock

import llm
import run

SECRET = "Article 3:84 BW and the student's own note on it"


def _msg(cost=None, model="claude-haiku-4-5", tin=120, tout=30):
    u = NS(input_tokens=tin, output_tokens=tout, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    if cost is not None:
        u.cost = cost
    return NS(model=model, usage=u, content=[NS(type="text", text='[{"front": "f", "back": "b"}]')], stop_reason="end_turn")


def _client(m):
    return NS(messages=NS(create=lambda **kw: m))


def _rows(pg):
    from psycopg.rows import dict_row
    return pg.cursor(row_factory=dict_row).execute("SELECT * FROM ai_calls ORDER BY at").fetchall()


def test_ask_model_writes_one_row_of_counts_and_no_text(pg):
    with mock.patch.object(run, "client", return_value=_client(_msg(cost=0.0021))):
        run.ask_model(run.STRONG_MODEL, task="cards", max_tokens=10, messages=[{"role": "user", "content": SECRET}])
    r = _rows(pg)
    assert len(r) == 1
    row = r[0]
    assert (row["feature"], row["input_tokens"], row["output_tokens"], row["cost_usd"]) == ("cards", 120, 30, 0.0021)
    assert SECRET not in " ".join(str(v) for v in row.values())


def test_unknown_cost_stays_null_never_a_guess(pg, monkeypatch):
    monkeypatch.setattr(llm, "_provider", lambda: "openrouter")
    with mock.patch.object(run, "client", return_value=_client(_msg(cost=None))):
        run.ask_model(run.STRONG_MODEL, max_tokens=10, messages=[{"role": "user", "content": "q"}])
    assert _rows(pg)[0]["cost_usd"] is None


def test_a_failing_log_never_fails_the_call(monkeypatch):
    def broken(_): raise RuntimeError("db down")
    monkeypatch.setattr(llm, "SINKS", [broken])
    with mock.patch.object(run, "client", return_value=_client(_msg(cost=0.01))):
        assert run.ask_model(run.STRONG_MODEL, max_tokens=10, messages=[]).model == "claude-haiku-4-5"


def test_the_sink_survives_a_reload_of_llm():
    import importlib
    importlib.reload(llm)
    assert run._log_call in llm.SINKS


def test_a_request_records_its_path_and_user(client, pg):
    cid = client.post("/api/courses", json={"name": "Cost Law"}).json()["id"]
    nid = client.post(f"/api/courses/{cid}/notes", json={"title": "Week 1 — Ownership", "body": "Rule. " * 50}).json()["id"]
    with mock.patch.object(run, "client", return_value=_client(_msg(cost=0.004))):
        assert client.post(f"/api/courses/{cid}/cards/generate", json={"note_id": nid, "count": 1}).status_code == 200
    row = _rows(pg)[-1]
    assert row["feature"] and row["user_id"] and row["cost_usd"] == 0.004


def test_week_adds_up_and_counts_the_unpriced(client, pg):
    now = time.time()
    for i, (cost, at) in enumerate([(0.5, now - 3600), (None, now - 7200), (0.25, now - 86400 * 2), (9.0, now - 86400 * 9)]):
        pg.execute("INSERT INTO ai_calls(id,at,feature,model,input_tokens,output_tokens,cost_usd) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                   (f"c{i}", at, "tutor" if i < 2 else "cards", "m", 100, 10, cost))
    pg.commit()
    w = client.get("/api/spend/week").json()
    assert (w["calls"], w["cost"], w["unpriced"], w["tokens"]) == (3, 0.75, 1, 330)
    assert {f["feature"] for f in w["features"]} == {"tutor", "cards"}
