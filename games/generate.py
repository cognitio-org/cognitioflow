#!/usr/bin/env python3
"""Wire the first-person law games to real materials.

The games (objection/, docket/) load their submissions from content/<course>.json.
This writes that file from real EU-law material instead of hand-typing it:

  verified anchor proposition  ──(RAG)──▶  real passage from law:eu:3 / law:eu:6
          │                                        (provenance + grounding)
          ▼
    M4 30B (local, free, private) ── phrases a SOUND and a FLAWED courtroom
          │                           submission for each anchor. The model
          ▼                           NEVER states a case/year/article — so its
    curate ── schema, balance,        known unreliability on legal facts can't
          dedupe, verified cites      corrupt a citation. Cites come from the anchor.
          │
          ▼
    content/<course>.json  (both games read it)

Why it is built this way:
- CF never uses the Anthropic API. Generation runs on the M4 Qwen3-30B MoE over the
  mesh (the sanctioned swarm lane), so law material never leaves the fleet.
- The model got "Van Gend en Loos" wrong (said 1960; it is 1963). So the model is
  used only to REPHRASE a verified proposition into natural submissions and to invent
  a plausible MISSTATEMENT of that same rule. Every ground/cite/why is taken from the
  verified anchor, never from the model. Model-named authorities are stripped.
- When your own course files reach the RAG (Brightspace ingest) or the local DB is up,
  add_course_sources() extends ANCHORS from them — the same pipeline, richer sources.

Run:  python3 games/generate.py            # writes games/*/content/eu-law.json
      python3 games/generate.py --dry      # generate + curate, print, don't write
"""
from __future__ import annotations
import argparse, json, os, re, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GAMES = Path(__file__).resolve().parent
RAG_BASES = [u.strip().rstrip("/") for u in
             os.environ.get("CF_RAG_URL", "http://127.0.0.1:8124,http://100.64.0.3:8123").split(",") if u.strip()]
RAG_CORPORA = os.environ.get("CF_RAG_LAW_CORPORA", "law:eu:3,law:eu:6")
M4_BASE = os.environ.get("CF_GEN_BASE", "http://100.64.0.3:8080")
M4_MODEL = os.environ.get("CF_GEN_MODEL", "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-DWQ")

# The six planted stations the Docket game knows (games/docket/index.html SLOTS).
STATIONS = ["Claimant's table", "Respondent's table", "The bench",
            "Witness box", "Clerk's desk", "The rostrum"]

# ---------------------------------------------------------------- verified anchors
# Each anchor is a SOUND proposition of EU law with an authority I can stand behind,
# a plain-language `ground` (the rule), a `why`, the `wk` label, and a `rag` query
# used to pull the real supporting passage. These are the backbone of legal accuracy;
# the RAG attaches a real source snippet, the model only phrases submissions.
ANCHORS = [
    dict(wk="Week 3 · Sources",
         prop="A regulation is directly applicable in every Member State and takes effect without any national transposing measure.",
         ground="Art 288 TFEU — a regulation is directly applicable in all Member States; national implementing legislation is in principle prohibited.",
         cite="Art 288 TFEU",
         why="Regulations take effect automatically on entry into force; re-enacting them in national law is forbidden as it can obscure their EU origin.",
         rag="regulation directly applicable all Member States Article 288 without transposition"),
    dict(wk="Week 4 · Direct effect",
         prop="A Treaty provision produces direct effect where it is sufficiently clear, precise and unconditional.",
         ground="Van Gend en Loos (1963) — the conditions for direct effect of a Treaty provision.",
         cite="Van Gend en Loos (1963)",
         why="EU law is a new legal order whose provisions can create rights individuals may enforce in national courts where the conditions are met.",
         rag="direct effect Treaty provision clear precise unconditional individuals rights national court"),
    dict(wk="Week 4 · Direct effect",
         prop="A directive cannot of itself be relied on against another private party.",
         ground="Directives have no horizontal direct effect — they bind the State, not private parties (Marshall 1986; Faccini Dori 1994).",
         cite="Marshall (1986); Faccini Dori (1994)",
         why="A directive is addressed to Member States; it cannot of itself impose obligations on an individual, so only vertical reliance is possible.",
         rag="directive horizontal direct effect cannot impose obligations individual private party"),
    dict(wk="Week 4 · Direct effect",
         prop="After the transposition deadline, an unconditional and sufficiently precise provision of a directive may be relied on against the State.",
         ground="Vertical direct effect of directives after the deadline (Van Duyn 1974; Ratti 1979).",
         cite="Van Duyn (1974); Ratti (1979)",
         why="A State may not rely on its own failure to transpose; once the deadline passes an individual may invoke a clear, unconditional provision against it.",
         rag="directive vertical direct effect transposition deadline unconditional sufficiently precise against State"),
    dict(wk="Week 4 · Emanation of the State",
         prop="A body made responsible for a public service under State control and with special powers counts as the State for vertical direct effect.",
         ground="The Foster test for an emanation of the State (Foster v British Gas 1990).",
         cite="Foster v British Gas (1990)",
         why="Whether a body is 'the State' turns on function and control, not its private-law form, so a directive may be invoked against it.",
         rag="emanation of the State Foster public service special powers control vertical direct effect"),
    dict(wk="Week 5 · Indirect effect",
         prop="A national court must so far as possible interpret national law in conformity with an applicable directive.",
         ground="Duty of consistent interpretation / indirect effect (Von Colson 1984; Marleasing 1990).",
         cite="Von Colson (1984); Marleasing (1990)",
         why="Even without direct effect, national law must be read, so far as possible, to achieve the result the directive pursues.",
         rag="indirect effect consistent interpretation national law conformity directive Marleasing Von Colson"),
    dict(wk="Week 6 · State liability",
         prop="A Member State may be liable in damages to individuals for a sufficiently serious breach of EU law attributable to it.",
         ground="State liability (Francovich 1991; Brasserie du Pêcheur & Factortame 1996).",
         cite="Francovich (1991); Brasserie du Pêcheur (1996)",
         why="Where the rule confers rights, the breach is sufficiently serious and there is a causal link, the State owes reparation.",
         rag="State liability damages individuals sufficiently serious breach EU law Francovich Brasserie"),
    dict(wk="Week 2 · Primacy",
         prop="In case of conflict, EU law takes precedence over a conflicting rule of national law.",
         ground="Primacy of EU law (Costa v ENEL 1964).",
         cite="Costa v ENEL (1964)",
         why="A later or inconsistent national measure cannot override EU law without depriving it of its character as Union law.",
         rag="primacy supremacy EU law precedence conflicting national law Costa ENEL"),
    dict(wk="Week 2 · Primacy",
         prop="A national court must of its own motion disapply national law that conflicts with EU law, without awaiting its prior removal.",
         ground="Simmenthal (1978) — national courts set aside conflicting national law of their own motion.",
         cite="Simmenthal (1978)",
         why="The court need not request or await the setting aside of the national provision by legislation or another constitutional process.",
         rag="Simmenthal disapply conflicting national law own motion national court primacy"),
    dict(wk="Week 7 · Preliminary references",
         prop="A court against whose decisions there is no judicial remedy must refer a question of interpretation unless the point is acte clair or acte éclairé.",
         ground="Art 267(3) TFEU and the CILFIT exceptions (CILFIT 1982).",
         cite="Art 267(3) TFEU; CILFIT (1982)",
         why="The obligation to refer is relaxed only where the correct application is so obvious as to leave no reasonable doubt, or the question is materially identical to one already answered.",
         rag="Article 267(3) obligation to refer last instance court CILFIT acte clair acte eclaire"),
    dict(wk="Week 7 · Preliminary references",
         prop="A lower national court has a discretion whether to refer a question to the Court of Justice.",
         ground="Art 267(2) TFEU — the discretion to refer.",
         cite="Art 267(2) TFEU",
         why="A court whose decisions may still be appealed may, but need not, refer where a decision on the question is necessary to give judgment.",
         rag="Article 267(2) discretion to refer lower court preliminary ruling may request"),
    dict(wk="Week 7 · Preliminary references",
         prop="A national court may not itself declare an act of an EU institution invalid; only the Court of Justice may.",
         ground="Foto-Frost (1987) — the CJEU's exclusive power to declare EU acts invalid.",
         cite="Foto-Frost (1987)",
         why="Uniformity requires that the validity of Union acts be ruled on by one court; national courts may find an act valid but must refer doubts about invalidity.",
         rag="Foto-Frost national court cannot declare EU act invalid exclusive jurisdiction Court of Justice validity"),
    dict(wk="Week 9 · Fundamental rights",
         prop="The Charter of Fundamental Rights binds the Member States only when they are implementing EU law.",
         ground="Art 51(1) Charter; Åkerberg Fransson (2013).",
         cite="Art 51(1) Charter; Åkerberg Fransson (2013)",
         why="The Charter does not extend the Union's competences; it applies to national measures only within the scope of EU law.",
         rag="Charter fundamental rights Article 51 Member States implementing EU law Akerberg Fransson scope"),
    dict(wk="Week 2 · Primacy",
         prop="As a matter of EU law, primacy applies even to a conflicting rule of national constitutional law.",
         ground="Internationale Handelsgesellschaft (1970) — primacy over national constitutional rules.",
         cite="Internationale Handelsgesellschaft (1970)",
         why="The validity of a Union measure cannot be judged by national law, even constitutional law, without undermining the uniformity of EU law.",
         rag="Internationale Handelsgesellschaft primacy over national constitutional law fundamental rights uniform"),
]

# ---------------------------------------------------------------- RAG
def rag_passage(query: str, k: int = 3) -> dict | None:
    """Best real passage for an anchor from the shared-knowledge RAG. Returns
    {source, snippet} or None on any error — a down RAG just drops provenance,
    it never blocks generation (the anchor already carries the verified rule)."""
    q = urllib.parse.urlencode({"q": query[:1000], "corpora": RAG_CORPORA, "k": k})
    for base in RAG_BASES:
        try:
            with urllib.request.urlopen(f"{base}/api/rag/ask?{q}", timeout=6) as r:  # local service
                hits = json.loads(r.read().decode()).get("hits", [])
            for h in hits:
                snip = (h.get("snippet") or h.get("text") or "").strip()
                if snip:
                    doc = h.get("doc_id") or h.get("celex") or ""
                    title = (h.get("title") or "")[:90]
                    return {"source": (f"{doc} · {title}".strip(" ·") or "EU law"),
                            "snippet": snip[:600]}
        except Exception as e:  # noqa: BLE001
            print(f"  rag {base}: {type(e).__name__}", file=sys.stderr)
            continue
    return None

# ---------------------------------------------------------------- model (M4 30B)
_AUTHORITY = re.compile(
    r"\b(?:\d{4}|art(?:icle)?\.?\s*\d+|C-\d+/\d+|\bv\.?\s+[A-Z]|ECR|ECLI|TFEU|TEU|CILFIT|Costa|Simmenthal|Francovich|Marshall|Foster|Marleasing|Van\s+Gend|Van\s+Duyn|Ratti|Foto-Frost|Åkerberg|Akerberg)\b",
    re.I)

def _strip_authority(s: str) -> str:
    """Belt-and-braces: if the model named a case/year/article despite instructions,
    the sentence is suspect (it may have invented it). Flag by returning '' so the
    caller drops it and falls back to a deterministic phrasing."""
    return "" if _AUTHORITY.search(s or "") else (s or "").strip()

def m4_submissions(anchor: dict) -> dict:
    """Ask the M4 30B to phrase one SOUND and one FLAWED one-sentence submission for
    this anchor, naming no authority. Returns {sound, flawed} (either may be '')."""
    passage = anchor.get("_passage", {}).get("snippet", "")
    sysmsg = ("You write one-sentence oral submissions by counsel for an EU-law study game. "
              "You are given a VERIFIED rule and its plain-language ground. Write two submissions:\n"
              "  sound  — states the rule correctly, as counsel would put it to the court;\n"
              "  flawed — subtly MISSTATES this very rule in a plausible way a student might accept.\n"
              "Hard rules: each is ONE sentence; courtroom register; do NOT name any case, year, "
              "article number, or Treaty; do NOT introduce any other legal rule; the flawed one must "
              "be wrong about THIS rule, not another. Return ONLY JSON: "
              '{"sound":"...","flawed":"..."}')
    usr = f"RULE: {anchor['prop']}\nGROUND: {anchor['ground']}"
    if passage:
        usr += f"\nREAL SOURCE PASSAGE (for grounding, do not quote citations from it):\n{passage[:500]}"
    body = json.dumps({"model": M4_MODEL, "max_tokens": 300, "temperature": 0.6,
                       "messages": [{"role": "system", "content": sysmsg},
                                    {"role": "user", "content": usr}]}).encode()
    try:
        req = urllib.request.Request(f"{M4_BASE}/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = json.loads(r.read().decode())["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        print(f"  m4 call failed: {type(e).__name__} {e}", file=sys.stderr)
        return {"sound": "", "flawed": ""}
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return {"sound": "", "flawed": ""}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {"sound": "", "flawed": ""}
    return {"sound": _strip_authority(d.get("sound", "")),
            "flawed": _strip_authority(d.get("flawed", ""))}

# ---------------------------------------------------------------- build + curate
def build(anchors: list) -> list:
    """One SOUND and one FLAWED item per anchor. ground/cite/why come from the anchor;
    only the `text` is model-phrased (deterministic fallback if the model is unusable)."""
    items = []
    for a in anchors:
        a["_passage"] = rag_passage(a["rag"]) or {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        subs = list(ex.map(m4_submissions, anchors))
    for i, (a, s) in enumerate(zip(anchors, subs)):
        src = a.get("_passage", {}).get("source", "")
        sound_text = s["sound"] or f"Counsel submits that {a['prop'][0].lower()}{a['prop'][1:]}"
        flawed_text = s["flawed"]  # no safe deterministic misstatement; skip if model gave none
        base = dict(cite=a["cite"], wk=a["wk"], why=a["why"], ground=a["ground"], source=src)
        items.append({**base, "text": sound_text, "flawed": False})
        if flawed_text:
            items.append({**base, "text": flawed_text, "flawed": True})
    return items

def curate(items: list) -> list:
    """Drop empties/dupes, keep every cite verified (it is, by construction)."""
    seen, out = set(), []
    for it in items:
        t = (it.get("text") or "").strip()
        key = re.sub(r"\W+", " ", t.lower()).strip()
        if len(t) < 20 or key in seen:
            continue
        seen.add(key)
        out.append(it)
    flawed = sum(1 for it in out if it["flawed"])
    print(f"  curated {len(out)} items — {flawed} flawed / {len(out)-flawed} sound", file=sys.stderr)
    return out

def docket_six(pool: list) -> list:
    """Docket plants one beacon per courtroom station (six). Pick a balanced six — a
    flawed and a sound item alternating where possible — and give each its own station,
    so no two beacons stack and the 'spot the flaws' round stays winnable either way."""
    flawed = [it for it in pool if it["flawed"]]
    sound = [it for it in pool if not it["flawed"]]
    picked = []
    for i in range(len(STATIONS)):
        src = flawed if (i % 2 == 0 and flawed) or not sound else sound
        if not src:
            src = flawed or sound
        it = dict(src.pop(0))          # copy; pool items are shared with objection
        it["station"] = STATIONS[i]
        picked.append(it)
    return picked

def write_packs(items: list, course="European Law"):
    dk = docket_six(items)            # six planted stations, one item each
    docket = {"course": course, "title": "The Docket — spot the flaws in the submissions",
              "items": [{k: it[k] for k in ("text", "flawed", "ground", "cite", "station", "why", "source")} for it in dk]}
    objection = {"course": course, "title": "Objection! — Direct effect, primacy & references",
                 "items": [{k: it[k] for k in ("text", "flawed", "ground", "cite", "wk", "why", "source")} for it in items]}
    for sub, pack in (("docket", docket), ("objection", objection)):
        # games now live under play/arcade/ (served); write their content there, not under games/.
        p = GAMES.parent / "play" / "arcade" / sub / "content" / "eu-law.json"
        if p.exists():
            bak = p.with_suffix(".json.bak")
            if not bak.exists():
                bak.write_text(p.read_text(), encoding="utf-8")
        p.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  wrote {p}  ({len(pack['items'])} items)")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="generate + curate, print, do not write")
    ap.add_argument("--limit", type=int, default=0, help="use only the first N anchors (quick test)")
    args = ap.parse_args()
    anchors = ANCHORS[: args.limit] if args.limit else ANCHORS
    print(f"generating from {len(anchors)} verified anchors · RAG {RAG_CORPORA} · model {M4_MODEL.split('/')[-1]}")
    items = curate(build(anchors))
    withsrc = sum(1 for it in items if it.get("source"))
    print(f"  {withsrc}/{len(items)} items carry a real RAG source snippet")
    for it in items[:4]:
        print(f"   [{'FLAW' if it['flawed'] else 'SOUND'}] {it['text'][:90]}  ⟵ {it['cite']}")
    if args.dry:
        print("  --dry: not writing")
        return
    write_packs(items)

if __name__ == "__main__":
    main()
