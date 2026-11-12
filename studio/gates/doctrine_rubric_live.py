"""Live check of the doctrine-judge rubric on the real reviewer (the M4 Thinker). Not a unit test.

    python3 studio/gates/doctrine_rubric_live.py [--repeat N] [--system-brief]

Sends each fixture in doctrine_rubric_fixtures.json (synthetic / public-treaty text, no course content) through
review_doctrine(require_quotes=True) with runtime.m4_reviewer() and prints got vs expected per fixture. Exit 1 if
any fixture disagrees. The caller is responsible for the M4 load rules (studio lock, memory floor).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

from studio import runtime  # noqa: E402
from studio.gates.doctrinal_review import JUDGE_RUBRIC_VERSION, review_doctrine  # noqa: E402

HERE = os.path.dirname(__file__)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--system-brief", action="store_true", help="send studio/brief.md as the system message")
    a = ap.parse_args(argv)
    system = open(os.path.join(HERE, os.pardir, "brief.md")).read() if a.system_brief else None
    reviewer = runtime.m4_reviewer(system=system)
    fixtures = json.load(open(os.path.join(HERE, "doctrine_rubric_fixtures.json")))["fixtures"]
    wrong = 0
    print(f"rubric {JUDGE_RUBRIC_VERSION} model {reviewer.model} brief={'yes' if system else 'no'}")
    for f in fixtures:
        for r in range(a.repeat):
            v = review_doctrine(f["source"], f["generated"], reviewer, require_quotes=True)
            agree = v.ok is f["expect"]
            wrong += not agree
            print(f"{'OK  ' if agree else 'MISS'} {f['id']:<26} run{r + 1} expect={f['expect']} got={v.ok} "
                  f"issues={v.issues[:2]}", flush=True)
    print(f"{wrong} disagreement(s)")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
