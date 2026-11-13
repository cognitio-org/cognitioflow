"""Seed the public-source EU-law demo course (docs/demo/eu-public-demo-course.json) into a running CognitioFlow.

    python scripts/demo_eu_public.py http://127.0.0.1:8000          # local dev (AUTH=off)
    CF_COOKIE='session=...' python scripts/demo_eu_public.py https://cognitioflow.ai   # a signed-in account

Creates the course with its stated learning objectives (public Ocasys description), applies the 12-week
demo schedule, adds the demo cards and replays their review ratings so readiness has something to read.
Writes only through the public API. It does NOT build the coverage map: press "Build coverage map" on
Progress and save it, so the map shown is the one the app made. Every input is public (see the JSON's _about).
"""
import json
import os
import sys
from pathlib import Path

import httpx

FIX = Path(__file__).resolve().parents[1] / "docs" / "demo" / "eu-public-demo-course.json"


def main(base):
    d = json.loads(FIX.read_text())
    h = {"Cookie": os.environ["CF_COOKIE"]} if os.environ.get("CF_COOKIE") else {}
    c = httpx.Client(base_url=base.rstrip("/") + "/api", headers=h, timeout=60)
    ok = lambda r: (r.raise_for_status(), r.json())[1]
    have = [x for x in ok(c.get("/courses")) if x.get("slug") == d["course"]["slug"]]
    if have:
        sys.exit(f"course {d['course']['slug']} already exists (id {have[0]['id']}); delete it first")
    cid = ok(c.post("/courses", json={**d["course"], "brief": d["brief"]}))["id"]
    ok(c.post(f"/courses/{cid}/syllabus/apply", json=d["syllabus"]))
    for card in d["cards"]:
        kid = ok(c.post(f"/courses/{cid}/cards", json={k: card[k] for k in ("front", "back", "week")}
                        | {"source": "public demo"}))["id"]
        for rating in card.get("reviews", []):
            ok(c.post(f"/cards/{kid}/review", json={"rating": rating}))
    print(json.dumps({"course": cid, "weeks": len(d["syllabus"]["weeks"]), "cards": len(d["cards"])}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")
