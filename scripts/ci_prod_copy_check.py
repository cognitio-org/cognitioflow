"""CI check against a Neon branch of production: what `fast` cannot prove on an empty container.

1. Pending migrations apply to production's real rows, and a second run is a no-op.
2. The app starts on the migrated copy and EVERY GET route under /api answers 200 for the owner's real
   data. Routes are read from the app itself, so a new feature is covered without editing this file.
   Path ids ({fid}, {nid}, …) are filled from the lists that hold them; a route whose list is empty is
   reported as skipped, never counted as passed.

Prints status codes and counts only, never content (student data). The full suite is not run here: its
per-test TRUNCATE empties the copy after the first test, and every statement crosses to eu-central-1, so
it took 20-35 minutes to re-prove what `fast` proved in 1-3.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import migrate  # noqa: E402

# They stream uploaded files and audio out of the storage bucket, which a database copy doesn't hold.
STORAGE_ROUTES = {"/api/files/{fid}/raw", "/api/recordings/{rid}/audio", "/api/notes/{nid}/audio/file"}
QUERY = {"/api/courses/{cid}/search": {"q": "law"}}
# Where each path id comes from: (list route, key to read). Ids depend on {cid} or {nid}, filled first.
SOURCES = {
    "fid": "/api/courses/{cid}/files",
    "nid": "/api/courses/{cid}/notes",
    "vid": "/api/notes/{nid}/versions",
    "rid": "/api/notes/{nid}/recordings",
    "qid": "/api/courses/{cid}/mock/papers",
}
GID = {"/api/courses/{cid}/docket/{gid}": "/api/courses/{cid}/docket",
       "/api/courses/{cid}/docket-drafts/{gid}": "/api/courses/{cid}/docket-drafts"}


def first_id(body):
    """The first `id` in a JSON body, however the list is wrapped (a list, {"files": [...]}, weeks…)."""
    if isinstance(body, dict):
        if "id" in body and isinstance(body["id"], (str, int)):
            return body["id"]
        values = body.values()
    elif isinstance(body, list):
        values = body
    else:
        return None
    for v in values:
        if isinstance(v, (dict, list)):
            found = first_id(v)
            if found is not None:
                return found
    return None


def main() -> int:
    url = os.environ["DATABASE_URL"]
    migrate.run(url)
    migrate.run(url)  # must be a no-op

    from fastapi.testclient import TestClient
    import run
    from run import app

    # No model is ever called from here (cost, and student text leaving for a provider). Some GET routes
    # do call one: lawyer-pack writes quiz distractors through ask_model when a course has cards. Those
    # are reported as needing the model, not counted as passed.
    ai_called = []

    def no_ai(*_a, **_k):
        ai_called.append(True)
        raise RuntimeError("model call blocked in the production-copy check")

    run.client = no_ai

    routes = sorted({r.path for r in app.routes
                     if "GET" in (getattr(r, "methods", None) or ()) and r.path.startswith("/api")})
    failures, passed, skipped, needs_ai = [], 0, [], []

    with TestClient(app, raise_server_exceptions=False) as c:
        def get(path, params=None):
            ai_called.clear()
            r = c.get(path, params=params)
            if ai_called:
                return "AI", None
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
            return r.status_code, body

        for path in ("/health", "/"):
            code, _ = get(path)
            print(f"{path} {code}")
            passed += code == 200
            if code != 200:
                failures.append(path)

        code, body = get("/api/courses")
        courses = body.get("courses", body) if isinstance(body, dict) else body
        if code != 200 or not isinstance(courses, list):
            print(f"/api/courses {code}: cannot continue")
            return 1
        print(f"{len(routes)} GET routes, {len(courses)} courses")

        for course in courses:
            ids = {"cid": course["id"]}
            for name in ("nid", "fid", "qid"):
                ids[name] = first_id(get(SOURCES[name].format(**ids))[1])
            if ids["nid"] is not None:
                for name in ("vid", "rid"):
                    ids[name] = first_id(get(SOURCES[name].format(**ids))[1])

            for route in routes:
                if route in STORAGE_ROUTES:
                    continue
                params = set(re.findall(r"{(\w+)}", route))
                if route in GID:
                    ids["gid"] = first_id(get(GID[route].format(**ids))[1])
                missing = sorted(p for p in params if ids.get(p) is None)
                if missing:
                    skipped.append(f"{course['id']} {route} (no {', '.join(missing)})")
                    continue
                if "cid" not in params and course is not courses[0] and not (params - {"cid"}):
                    continue  # course-free routes run once
                code, body = get(route.format(**ids), QUERY.get(route))
                if code == "AI":
                    needs_ai.append(f"{course['id']} {route}")
                    continue
                n = len(body) if isinstance(body, list) else "-"
                print(f"  {code} ({n}) {course['id'] if 'cid' in params else ''} {route}")
                passed += code == 200
                if code != 200:
                    failures.append(f"{route} [{course['id']}] -> {code}")

    for s in skipped:
        print(f"  skip {s}")
    for s in needs_ai:
        print(f"  needs the model, not checked: {s}")
    print(f"not checked here (storage bucket): {', '.join(sorted(STORAGE_ROUTES))}")
    print(f"{passed} passed, {len(failures)} failed, {len(skipped)} skipped (no data to fill the id), "
          f"{len(needs_ai)} need the model")
    for f in failures:
        print(f"FAIL {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
