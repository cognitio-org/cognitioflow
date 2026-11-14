"""The pitch proof for a live coverage-map Rebuild: N fresh builds in a row on one course, all must succeed and give the
identical map. Needs docs/pending-protected/blueprint-build.patch applied (it adds ?fresh=1, which bypasses the
input-hash cache — without it the proof would only read the saved map back).

    python scripts/blueprint_proof.py http://127.0.0.1:8000 <course id> [N=20] [log.json]
    CF_COOKIE='session=...' python scripts/blueprint_proof.py https://cognitioflow.ai <course id>

"Identical" is fixed before the run: sha256 of the whole proposal (every topic, week, objective, %, doctrine chip and
note, the counts and the input hash), leaving out only per-call fields (cached, attempts, model, source). A structural
hash (topic names, weeks, objectives, %) is reported beside it, never instead of it. Runs are sequential; one failure
breaks the streak. Writes nothing to the course: extract only proposes.
"""
import hashlib
import json
import os
import sys
import time

import httpx

PER_CALL = ("cached", "attempts", "model", "source")


def digest(b):
    full = {k: v for k, v in b.items() if k not in PER_CALL}
    struct = [(t["topic"], t["weeks"], t["objectives"], t["weight"]) for t in b.get("topics", [])]
    h = lambda x: hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return h(full), h(struct)


def main(base, cid, n=20, log_path=None):
    h = {"Cookie": os.environ["CF_COOKIE"]} if os.environ.get("CF_COOKIE") else {}
    c = httpx.Client(base_url=base.rstrip("/") + "/api", headers=h, timeout=300)
    runs, first = [], None
    for i in range(1, n + 1):
        t0 = time.time()
        r = c.post(f"/courses/{cid}/blueprint/extract", params={"fresh": 1})
        dt = round(time.time() - t0, 2)
        row = {"run": i, "status": r.status_code, "seconds": dt}
        if r.status_code == 200:
            b = r.json()
            if b.get("cached"):
                sys.exit("the server returned a cached map: apply the run.py patch so ?fresh=1 bypasses the cache")
            row.update(zip(("full", "struct"), digest(b)))
            row.update(attempts=b.get("attempts"), topics=len(b.get("topics", [])), model=b.get("model"))
            first = first or b
        else:
            row["error"] = r.text[:300]
        runs.append(row)
        print(json.dumps(row), flush=True)
    ok = [x for x in runs if x["status"] == 200]
    secs = sorted(x["seconds"] for x in runs)
    summary = {"runs": n, "succeeded": len(ok), "distinct_full": len({x["full"] for x in ok}),
               "distinct_struct": len({x["struct"] for x in ok}), "server_retries": sum((x.get("attempts") or 1) - 1 for x in ok),
               "seconds_min": secs[0], "seconds_median": secs[len(secs) // 2], "seconds_max": secs[-1],
               "pass": len(ok) == n and len({x["full"] for x in ok}) == 1}
    print(json.dumps(summary))
    if log_path:
        json.dump({"base": base, "course": cid, "runs": runs, "summary": summary, "map": first}, open(log_path, "w"),
                  indent=1, ensure_ascii=False)
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(main(a[0], a[1], int(a[2]) if len(a) > 2 else 20, a[3] if len(a) > 3 else None))
