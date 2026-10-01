"""Daily drill check (asked for 2026-10-02, the plan to exam day): every morning, on a Neon branch of production,
open what he drills with - for each course: Today, the due cards, a quiz build, one rating, and the mock papers.

Read-only towards production: it runs on a throwaway branch (the workflow creates and deletes it), and the one
write it makes - rating a due card, to prove the review path end to end - lands on that branch only. No model is
ever called; a quiz that would need new distractors written is reported as needing the model, not as broken.
Prints counts and status codes only, never content (student data). Exits 1 when anything he drills with fails,
which makes the workflow open an issue.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import migrate
    migrate.run(os.environ["DATABASE_URL"])   # the branch is production; main's pending migrations, if any, apply to the copy

    from fastapi.testclient import TestClient
    import run

    model_called = []

    def no_model(*_a, **_k):
        model_called.append(True)
        raise RuntimeError("model call blocked in the drill check")

    run.client = no_model
    failures, notes = [], []

    with TestClient(run.app, raise_server_exceptions=False) as c:
        def call(method, path, **kw):
            model_called.clear()
            r = getattr(c, method)(path, **kw)
            return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else None), bool(model_called)

        status, today, _ = call("get", "/api/today")
        if status != 200:
            failures.append(f"Today: {status}")
            today = {"courses": []}
        status, courses, _ = call("get", "/api/courses")
        if status != 200 or not courses:
            failures.append(f"courses: {status}")
            courses = []
        for course in courses:
            cid = course["id"]
            line = [cid]
            if not any(t.get("id") == cid for t in (today or {}).get("courses", [])):
                failures.append(f"{cid}: missing from Today")
            status, due, _ = call("get", f"/api/courses/{cid}/cards", params={"due": 1})
            if status != 200 or not isinstance(due, list):
                failures.append(f"{cid}: due cards {status}")
                due = []
            line.append(f"{len(due)} due")
            status, quiz, needed = call("post", f"/api/courses/{cid}/quiz", json={"count": 4})
            if status == 200 and isinstance(quiz, list):
                line.append(f"quiz {len(quiz)} questions")
            elif needed:
                notes.append(f"{cid}: the quiz needs new distractors written (model blocked here), not a fault")
                line.append("quiz needs the model")
            else:
                failures.append(f"{cid}: quiz {status}")
            if due:
                status, rated, _ = call("post", f"/api/cards/{due[0]['id']}/review", json={"rating": 2})
                if status != 200 or not (rated or {}).get("due"):
                    failures.append(f"{cid}: rating a card {status}")
                else:
                    line.append("rating saved")
            status, papers, _ = call("get", f"/api/courses/{cid}/mock/papers")
            if status != 200 or not isinstance(papers, dict):
                failures.append(f"{cid}: mock papers {status}")
            else:
                n = len(papers.get("papers", []))
                q = sum(len(p.get("questions", [])) for p in papers.get("papers", []))
                line.append(f"mock {n} papers / {q} questions")
                if not n and papers.get("exam_files"):
                    notes.append(f"{cid}: {papers['exam_files']} past paper file(s) not prepared as mocks yet")
            print("  " + " · ".join(line))

    for n in notes:
        print("  note: " + n)
    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    print(f"OK: {len(courses)} course(s), drill and mock open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
