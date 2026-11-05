"""Every game-catalogue entry must resolve to a shipped asset — the audit's ask, and the guard that
catches anyone re-adding a game whose heavy asset is gitignored (e.g. icj's 59MB splat).

Pure filesystem: no DB, no TestClient — runnable standalone (`python3 tests/test_catalogue_resolves.py`)
even where the Postgres-coupled conftest can't collect."""
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAY = os.path.join(HERE, "play")
GAMES = os.path.join(PLAY, "games")


def check_catalogue():
    with open(os.path.join(GAMES, "index.json")) as fh:
        index = json.load(fh)
    with open(os.path.join(GAMES, "courses.json")) as fh:
        courses = json.load(fh)
    problems = []
    for g in index:
        gid = g.get("id", "?")
        has_path, has_url = bool(g.get("path")), bool(g.get("url"))
        if has_path == has_url:
            problems.append(f"{gid}: must have exactly one of `path` (player game) or `url` (standalone)")
            continue
        if g.get("course") not in courses:
            problems.append(f"{gid}: course code {g.get('course')!r} not in courses.json")
        if has_path:
            p = os.path.join(GAMES, g["path"])
            if not os.path.isfile(p):
                problems.append(f"{gid}: path {g['path']} does not exist under play/games/")
            else:
                try:
                    with open(p) as fh:
                        json.load(fh)
                except Exception as e:
                    problems.append(f"{gid}: {g['path']} is not valid JSON: {e}")
        else:
            url = g["url"].split("?")[0]
            if not url.startswith("/play/arcade/"):
                problems.append(f"{gid}: standalone url must be under /play/arcade/, got {url}")
                continue
            fp = os.path.join(HERE, url.lstrip("/"))
            if not os.path.isfile(fp):
                problems.append(f"{gid}: url page {url} does not exist ({fp})")
                continue
            # objection/docket load ../assets/courtroom_web.glb and content/<?course=>.json
            if "objection" in url or "docket" in url:
                glb = os.path.join(os.path.dirname(os.path.dirname(fp)), "assets", "courtroom_web.glb")
                if not os.path.isfile(glb):
                    problems.append(f"{gid}: expected GLB {glb} missing")
                if "?course=" in g["url"]:
                    key = g["url"].split("?course=")[1].split("&")[0]
                    cf = os.path.join(os.path.dirname(fp), "content", key + ".json")
                    if not os.path.isfile(cf):
                        problems.append(f"{gid}: content/{key}.json missing ({cf})")
    return problems


def test_every_catalogue_entry_resolves():
    problems = check_catalogue()
    assert not problems, "catalogue has unresolved entries:\n  " + "\n  ".join(problems)


if __name__ == "__main__":
    probs = check_catalogue()
    print("\n".join("✗ " + p for p in probs) if probs else "✓ all catalogue entries resolve to shipped assets")
    raise SystemExit(1 if probs else 0)
