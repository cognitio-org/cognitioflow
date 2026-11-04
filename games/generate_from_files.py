#!/usr/bin/env python3
"""Regenerate the law games from Matej's REAL course materials — course-aware.

Source = the text extracted from his Brightspace files (_ingest/<course>/txt): working-group
MODEL ANSWERS, seminar/lecture slides, practice-exam answers. Each course draws from its own
_ingest/<course>/txt and writes its own content pack (content/<out>.json) for both games.

Pipeline per source:
  his source text ──▶ M4 Qwen3-30B (local, free, private) extracts up to N propositions the
  material actually turns on, each as {prop, ground, cite, why} PLUS a plausible flawed
  misstatement ──▶ CURATE: keep a proposition ONLY if its `cite` (an article/section/case)
  literally appears in the source text. The model may summarise; it may not invent an authority.
  ──▶ write the games' content JSON.

Why: CF never uses the Anthropic API; generation runs on the M4 over the mesh. The model is
unreliable on legal facts from memory, so it is pinned to his own authoritative text and every
citation is checked back against that text. Citation grammar is per-course: EU = TFEU/TEU/Charter
articles + C-…/… cases; Property/civil = BW/BGB/§/section articles + case names.

Run:  python3 games/generate_from_files.py --course eu --dry
      python3 games/generate_from_files.py --course prop        # writes content/property-law.json
"""
from __future__ import annotations
import argparse, json, os, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GAMES = Path(__file__).resolve().parent
M4_BASE = os.environ.get("CF_GEN_BASE", "http://100.64.0.3:8080")
M4_MODEL = os.environ.get("CF_GEN_MODEL", "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-DWQ")
STATIONS = ["Claimant's table", "Respondent's table", "The bench",
            "Witness box", "Clerk's desk", "The rostrum"]

# ---- course config: each draws from _ingest/<dir>/txt, writes content/<out>.json ----
COURSES = {
    "eu": {
        "name": "European Law", "dir": "eu", "cites": "eu", "out": "eu-law.json",
        "docket_title": "The Docket — spot the flaws (your EU Law WG material)",
        "objection_title": "Objection! — your EU Law exam topics",
        "sources": [
            ("Week 2 · Free movement", "5954373_wk2_model.txt"),
            ("Week 3 · Establishment & services", "5969842_wk3_model.txt"),
            ("Week 4 · Citizenship & fundamental rights", "5977423_wk4_model.txt"),
            ("Week 5 · Competition law", "5984748_wk5_assignment_model.txt"),
            ("Week 6 · Enforcement", "6002541_wk6_model.txt"),
            ("Week 1 · Foundations", "5924795_wk1_model.txt"),
        ],
    },
    "prop": {
        "name": "Property Law", "dir": "prop", "cites": "prop", "out": "property-law.json",
        "docket_title": "The Docket — spot the flaws (your Property Law material)",
        "objection_title": "Objection! — your Property Law topics",
        "sources": [
            ("Week 2 · Zimmermann", "564706_wk2_zimmermann.txt"),
            ("Week 3 · Zimmermann", "564706_wk3_zimmermann.txt"),
            ("Week 4 · Transfer of claims", "564706_wk4_transfer_claims.txt"),
            ("Week 5 · Ouyang", "564706_wk5_ouyang.txt"),
            ("Week 6 · Hoops", "564706_wk6_hoops.txt"),
            ("Week 2 · Materials", "564706_wk2_content.txt"),
            ("Week 3 · Materials", "564706_wk3_content.txt"),
            ("Week 4 · Materials", "564706_wk4_content.txt"),
            ("Week 5 · Materials", "564706_wk5_content.txt"),
            ("Week 6 · Materials", "564706_wk6_content.txt"),
        ],
    },
    "intleu": {
        "name": "International & European Law", "dir": "intleu", "cites": "eu", "out": "intl-eu-law.json",
        "docket_title": "The Docket — spot the flaws (Intro to International & European Law)",
        "objection_title": "Objection! — International & European Law",
        "sources": [
            ("Week 1", "470358_week1_answers.txt"),
            ("Week 2", "470358_week2_answers.txt"),
            ("Week 3", "470358_week3_answers.txt"),
            ("Week 4", "470358_week4_answers.txt"),
            ("Week 5", "470358_week5_answers.txt"),
            ("Week 6", "470358_week6_answers.txt"),
            ("Exam answers", "470358_exam2024_answers.txt"),
            ("Model answers", "470358_model_answers_mc.txt"),
        ],
    },
}

# selected by main()
TXT = None
SOURCES = None
CITE_MODE = "eu"
COURSE = COURSES["eu"]

# EU authorities: a Treaty article, a CELEX/ECLI, or a Case C-../..
_ART = re.compile(r"\b(?:Art(?:icle)?\.?\s*\d+[a-z]?(?:\(\d+\))?\s*(?:TFEU|TEU|Charter|CFR))\b", re.I)
_CASE = re.compile(r"\bC[-‑]\d+/\d+\b")
# Property/civil authorities: Art 3:84 BW, § 929 BGB, section 2, s 2, plus bare articles.
_ART_PROP = re.compile(r"(?:(?:Art(?:icle|ikel)?\.?|§|sec(?:tion)?\.?|s\.?)\s*\d+[a-z]?(?::\d+)?(?:\s*(?:BW|BGB|DCC|CC))?)", re.I)

def _norm(s: str) -> str:
    """Normalise for citation matching: lowercase, 'article'->'art', drop non-alphanumerics,
    so 'Art 45 TFEU' and 'Article 45 TFEU' compare equal."""
    return re.sub(r"[^a-z0-9]", "", re.sub(r"artikel|article", "art", (s or "").lower()))

def _authority_in(cite: str, src: str) -> bool:
    """True if the cite is grounded in the source text: its article/section/case id appears
    there, or a distinctive multi-word proper-noun chunk of it does."""
    c = (cite or "").strip()
    if not c:
        return False
    nsrc = _norm(src)
    # A case citation (C-xx/yy, optionally followed by a name) must have BOTH its number
    # AND any attached case name present in the source.
    cm = _CASE.search(c)
    if cm:
        if _norm(cm.group(0)) not in nsrc:
            return False
        tail = c[cm.end():].strip(" ,.-")
        name = re.match(r"[A-ZÅÄÖ][\wé.'/-]+", tail)
        if name and name.group(0).lower() not in src.lower():
            return False
        return True
    # an article/section is enough if it appears in the source (grammar depends on the course)
    art_re = _ART_PROP if CITE_MODE == "prop" else _ART
    for m in art_re.finditer(c):
        if _norm(m.group(0)) in nsrc:
            return True
    # otherwise a multi-word proper-noun chunk of the cite appearing verbatim in the source
    for n in re.findall(r"(?:[A-ZÅÄÖ][\wé.'-]+(?:\s+(?:v\.?|and|&|of|the)\s+)?){2,}", c):
        if len(n.strip()) >= 6 and n.strip().lower() in src.lower():
            return True
    return False

def m4_props(label: str, text: str, n: int = 3) -> list:
    sysmsg = (
        f"You build items for a {COURSE['name']} exam game from the student's own course material "
        "(a working-group model answer, seminar/lecture slides, or syllabus). "
        f"Extract up to {n} distinct legal propositions this material actually turns on. "
        "For each return: prop (the rule, one sentence, courtroom register, NO citation inside it), "
        "ground (plain-language why, may name the authority), cite (the EXACT article, section or case "
        "AS WRITTEN in the source — e.g. 'Art 45 TFEU', 'C-55/94 Gebhard', 'Art 3:84 BW', '§ 929 BGB'; "
        "if the source names no authority for it, use \"\"), why (one more sentence of explanation), and "
        "flawed (a one-sentence submission that subtly MISSTATES this same rule, naming no authority). "
        "Use ONLY what the source supports. Do NOT invent article numbers, section numbers, case names or years. "
        'Return ONLY JSON: {"items":[{"prop":"","ground":"","cite":"","why":"","flawed":""}]}')
    body = json.dumps({"model": M4_MODEL, "max_tokens": 1500, "temperature": 0.3,
                       "messages": [{"role": "system", "content": sysmsg},
                                    {"role": "user", "content": f"TOPIC: {label}\n\nSOURCE:\n{text[:12000]}"}]}).encode()
    try:
        req = urllib.request.Request(f"{M4_BASE}/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.loads(r.read().decode())["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        print(f"  [{label}] m4 failed: {type(e).__name__} {e}", file=sys.stderr)
        return []
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return []
    try:
        items = json.loads(m.group(0)).get("items", [])
    except Exception:
        return []
    kept = []
    for it in items:
        prop, cite = (it.get("prop") or "").strip(), (it.get("cite") or "").strip()
        if len(prop) < 20 or not _authority_in(cite, text):
            continue
        kept.append(dict(wk=label, prop=prop, ground=(it.get("ground") or "").strip(),
                         cite=cite, why=(it.get("why") or "").strip(),
                         flawed_text=(it.get("flawed") or "").strip(), source=src_name(label)))
    print(f"  [{label}] {len(items)} proposed, {len(kept)} grounded-kept", file=sys.stderr)
    return kept

_SRCMAP = {}
def src_name(label):
    return _SRCMAP.get(label, "")

def build(limit=0):
    srcs = SOURCES[:limit] if limit else SOURCES
    jobs = []
    for label, fn in srcs:
        p = TXT / fn
        if not p.exists():
            print(f"  missing {fn}", file=sys.stderr); continue
        _SRCMAP[label] = fn
        jobs.append((label, p.read_text(encoding="utf-8")))
    allp = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        for kept in ex.map(lambda j: m4_props(*j), jobs):
            allp.extend(kept)
    items = []
    for pr in allp:
        base = dict(ground=pr["ground"], cite=pr["cite"], wk=pr["wk"], why=pr["why"], source=pr["source"])
        items.append({**base, "text": pr["prop"], "flawed": False})
        if len(pr["flawed_text"]) >= 20:
            items.append({**base, "text": pr["flawed_text"], "flawed": True})
    seen, out = set(), []
    for it in items:
        k = re.sub(r"\W+", " ", it["text"].lower()).strip()
        if k in seen:
            continue
        seen.add(k); out.append(it)
    f = sum(1 for it in out if it["flawed"])
    print(f"  built {len(out)} items — {f} flawed / {len(out)-f} sound", file=sys.stderr)
    return out

def docket_six(pool):
    fl = [it for it in pool if it["flawed"]]; so = [it for it in pool if not it["flawed"]]
    picked = []
    for i in range(len(STATIONS)):
        src = fl if (i % 2 == 0 and fl) or not so else so
        if not src: src = fl or so
        if not src: break
        it = dict(src.pop(0)); it["station"] = STATIONS[i]; picked.append(it)
    return picked

def write_packs(items):
    dk = docket_six(items)
    docket = {"course": COURSE["name"], "title": COURSE["docket_title"],
              "items": [{k: it[k] for k in ("text","flawed","ground","cite","station","why","source")} for it in dk]}
    obj = {"course": COURSE["name"], "title": COURSE["objection_title"],
           "items": [{k: it[k] for k in ("text","flawed","ground","cite","wk","why","source")} for it in items]}
    for sub, pack in (("docket", docket), ("objection", obj)):
        p = GAMES / sub / "content" / COURSE["out"]
        bak = p.with_suffix(".json.generic.bak")
        if p.exists() and not bak.exists():
            bak.write_text(p.read_text(), encoding="utf-8")
        p.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  wrote {p} ({len(pack['items'])} items)")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", default="eu", choices=list(COURSES))
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    global TXT, SOURCES, CITE_MODE, COURSE
    COURSE = COURSES[a.course]; CITE_MODE = COURSE["cites"]
    TXT = GAMES / "_ingest" / COURSE["dir"] / "txt"
    SOURCES = COURSE["sources"]
    print(f"generating {COURSE['name']} ({a.course}) from {len(SOURCES[:a.limit] if a.limit else SOURCES)} sources · {M4_MODEL.split('/')[-1]}")
    items = build(a.limit)
    for it in items:
        print(f"   [{'FLAW' if it['flawed'] else 'SOUND'}] ({it['wk']}) {it['text'][:85]}  ⟵ {it['cite']}")
    if a.dry:
        print("  --dry: not writing"); return
    if len(items) < 6:
        print("  too few grounded items — not overwriting packs", file=sys.stderr); return
    write_packs(items)

if __name__ == "__main__":
    main()
