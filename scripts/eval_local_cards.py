#!/usr/bin/env python3
"""Phase 18 eval harness: self-hosted Qwen2.5-7B (grounded) card output vs the cloud cheap tier.

It generates flashcards from a few short law passages with each model and scores them on two axes that
matter for a law card:

  faithfulness  — did the card invent law? Every legal reference on a card (article number, case name,
                  ECJ case number, directive/regulation) must appear in the source passage. A card with
                  a reference the source does not contain is an invented one. Score = fraction of cards
                  with zero invented references. This is the failure mode a grounded local model must
                  avoid, and it is checkable without a judge.
  usefulness    — is the card a well-formed, specific, non-duplicate Q/A? Score = fraction passing.

The sample is deliberately tiny (built-in public-law passages, no student content) so it runs on battery.
A fuller eval — a frozen gold set, judging against the user's own edited cards, and an LLM judge — is
listed at the bottom and needs wall power + the live DB.

Usage:
    # local only (Ollama must be up; model pulled):
    python scripts/eval_local_cards.py
    # also run the cloud cheap tier as the baseline (needs a provider key in the env):
    python scripts/eval_local_cards.py --cloud
    # options:
    python scripts/eval_local_cards.py --count 5 --base-url http://127.0.0.1:11434/v1 --model qwen2.5:7b-instruct

No student content is used; all passages are public EU-law doctrine. The harness goes through the model
seam (llm.py) — it imports no model SDK and does not touch the database.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import llm  # noqa: E402

# A copy of run.py's local-card system prompt (run.py is the source of truth; kept here so the harness
# needs no database to import). Grounding + abstention is the whole point of the local path.
GROUNDING_RULES = (
    "You write flashcards for a Groningen LLB law exam, grounded strictly in the material you are given.\n"
    "Rules:\n"
    "1. Use ONLY what is in the material. Every rule, case name, citation and article number on a card "
    "must appear in the text below.\n"
    "2. Never invent or 'recall from memory' law that is not in the material. If you are not sure a "
    "point is supported by the text, leave it out.\n"
    "3. One precise, testable point per card.\n"
    "4. If the material is thin, write FEWER cards — only what the text actually supports, even none.\n"
    "Return ONLY the JSON array, nothing else."
)

# Public EU-law doctrine. Each passage names its own authorities, so faithfulness is checkable against it.
SAMPLES = [
    {
        "name": "Direct effect — Van Gend en Loos",
        "text": (
            "Direct effect was established in Van Gend en Loos (Case 26/62). The Court of Justice held "
            "that the then Article 12 EEC, which prohibited new customs duties, produced direct effect: "
            "it conferred rights on individuals that national courts must protect. The conditions are that "
            "the provision is clear and precise, unconditional, and requires no further national "
            "implementing measure. The Treaty is more than an agreement between states; its subjects are "
            "the nationals of the Member States as well."
        ),
    },
    {
        "name": "Supremacy — Costa v ENEL",
        "text": (
            "In Costa v ENEL (Case 6/64) the Court established the primacy of EU law over conflicting "
            "national law, even law adopted later. A Member State cannot, by a subsequent unilateral "
            "measure, override the obligations it accepted under the Treaty. The executive force of "
            "Community law cannot vary from one state to another. Primacy was later extended to national "
            "constitutional law in Internationale Handelsgesellschaft (Case 11/70)."
        ),
    },
    {
        "name": "Free movement of goods — Dassonville and Cassis de Dijon",
        "text": (
            "In Dassonville (Case 8/74) the Court defined measures having equivalent effect to a "
            "quantitative restriction as all trading rules capable of hindering, directly or indirectly, "
            "actually or potentially, intra-Community trade. In Cassis de Dijon (Case 120/78) the Court "
            "held that goods lawfully produced and marketed in one Member State must in principle be "
            "admitted to the others (mutual recognition), subject to mandatory requirements such as the "
            "effectiveness of fiscal supervision and consumer protection. Article 34 TFEU prohibits such "
            "measures between Member States."
        ),
    },
]

# ---- reference extraction (the faithfulness proxy) -----------------------------------------
_REF_PATTERNS = [
    re.compile(r"\bArticle\s+\d+[a-zA-Z0-9:().\-]*", re.I),     # Article 34 TFEU, Article 5:1 BW
    re.compile(r"\bArt\.?\s*\d+[a-zA-Z0-9:().\-]*", re.I),      # Art. 12 EEC
    re.compile(r"\bCase\s+\d+/\d+", re.I),                       # Case 26/62
    re.compile(r"\bC-\d+/\d+"),                                  # C-26/62
    re.compile(r"\b(?:Directive|Regulation)\s+\d+[/\d]*", re.I),
    # X v Y — the run before "v" must be Capitalised tokens only, so a question fragment like
    # "What does the Costa v ENEL ...?" matches "Costa v ENEL", not "What does the Costa v ENEL".
    re.compile(r"(?:[A-Z][A-Za-zÀ-ÿ.]*\s+){0,3}[A-Z][A-Za-zÀ-ÿ.]*\s+v\.?\s+[A-Z][A-Za-zÀ-ÿ.]*"),
    # Named cases without a "v" that these passages use:
    re.compile(r"Van Gend en Loos|Cassis de Dijon|Dassonville|Internationale Handelsgesellschaft"),
]
_CASE_NUM = re.compile(r"\d+/\d+")


def _norm(s: str) -> str:
    """Lowercase, article→art, digits and letters only — so 'Art. 34 TFEU' == 'Article 34 TFEU'."""
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("article", "art"))


def _refs(text: str) -> list[str]:
    out, seen = [], set()
    for pat in _REF_PATTERNS:
        for m in pat.findall(text or ""):
            r = m.strip(" .,:;")
            if r and r.lower() not in seen:
                seen.add(r.lower()); out.append(r)
    return out


def _grounded(ref: str, source_norm: str, source_nums: set[str]) -> bool:
    nums = _CASE_NUM.findall(ref)
    if nums:   # a case/directive number: its digit core must be in the source
        return all(n.replace("/", "") in source_nums for n in nums)
    return _norm(ref) in source_norm


def faithfulness(cards: list[dict], source: str) -> dict:
    source_norm = _norm(source)
    source_nums = {n.replace("/", "") for n in _CASE_NUM.findall(source)}
    invented, grounded_cards = [], 0
    for c in cards:
        refs = _refs(f"{c.get('front','')} {c.get('back','')}")
        bad = [r for r in refs if not _grounded(r, source_norm, source_nums)]
        if bad:
            invented.extend(bad)
        else:
            grounded_cards += 1
    score = grounded_cards / len(cards) if cards else 0.0
    return {"score": score, "grounded_cards": grounded_cards, "invented": invented}


def usefulness(cards: list[dict]) -> dict:
    good, fronts = 0, set()
    for c in cards:
        f, b = (c.get("front") or "").strip(), (c.get("back") or "").strip()
        ok = (8 <= len(f) <= 300 and 10 <= len(b) <= 600 and f.lower() != b.lower()
              and f.lower() not in fronts)
        fronts.add(f.lower())
        good += bool(ok)
    return {"score": good / len(cards) if cards else 0.0, "well_formed": good}


# ---- generation through the seam -----------------------------------------------------------
def _parse_cards(text: str) -> list[dict]:
    text = (text or "").strip().strip("`")
    if text.startswith("json"):
        text = text[4:]
    try:
        items = json.loads(text)
    except Exception:
        s = min([i for i in (text.find("["), text.find("{")) if i >= 0] or [-1])
        e = max(text.rfind("]"), text.rfind("}"))
        if s >= 0 and e > s:
            try:
                items = json.loads(text[s:e + 1])
            except Exception:
                return []
        else:
            return []
    if isinstance(items, dict):
        items = [items]
    return [c for c in items if isinstance(c, dict) and c.get("front") and c.get("back")]


def gen_local(sample, count):
    prompt = (f"From the course material below, write up to {count} exam flashcards, grounded only in "
              "this text. Return ONLY a JSON array of objects with keys 'front' and 'back'.\n\n" + sample["text"])
    t = time.time()
    m = llm.local_create(system=GROUNDING_RULES, messages=[{"role": "user", "content": prompt}], max_tokens=3000)
    return _parse_cards(m.content[0].text), time.time() - t


def gen_cloud(sample, count):
    # The current cheap-tier behaviour: run.py's exact prompt, no grounding system block.
    prompt = (f"From the material below, write {count} flashcards for a law exam: precise, one testable "
              "point each, case names and article numbers where present. Return ONLY a JSON array of "
              "objects with keys 'front' and 'back'.\n\n" + sample["text"])
    t = time.time()
    m = llm.client().messages.create(model=llm.resolve(llm.default_model("cheap")), max_tokens=3000,
                                     messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
    return _parse_cards(text), time.time() - t


def run_side(label, gen, samples, count):
    """Quality (faithfulness, usefulness) is scored over the cards a side PRODUCED — an empty return is
    not 0/0 quality, it is a separate robustness signal (a thin source abstained, or a 7B returned
    malformed/empty JSON). So empties are excluded from the quality average and reported on their own,
    alongside the yield (cards produced vs requested)."""
    rows, fsum, usum, q, produced, empties = [], 0.0, 0.0, 0, 0, 0
    for s in samples:
        try:
            cards, secs = gen(s, count)
        except Exception as e:
            print(f"  ! {label} failed on {s['name']}: {type(e).__name__}: {e}")
            empties += 1
            continue
        produced += len(cards)
        if not cards:
            empties += 1
            print(f"  {label:6}  {s['name'][:38]:38}  cards= 0  (empty — abstained or unparseable)  {secs:4.1f}s")
            rows.append({"sample": s["name"], "cards": 0, "faithfulness": None, "usefulness": None, "secs": round(secs, 1)})
            continue
        fa, us = faithfulness(cards, s["text"]), usefulness(cards)
        rows.append({"sample": s["name"], "cards": len(cards), "faithfulness": fa["score"],
                     "usefulness": us["score"], "invented": fa["invented"], "secs": round(secs, 1)})
        fsum += fa["score"]; usum += us["score"]; q += 1
        inv = f", invented: {fa['invented']}" if fa["invented"] else ""
        print(f"  {label:6}  {s['name'][:38]:38}  cards={len(cards):2}  faith={fa['score']:.2f}  "
              f"useful={us['score']:.2f}  {secs:4.1f}s{inv}")
    avg = {"faithfulness": round(fsum / q, 3) if q else None, "usefulness": round(usum / q, 3) if q else None,
           "quality_samples": q, "empty_samples": empties, "cards_produced": produced,
           "yield": round(produced / (count * len(samples)), 3) if samples else None}
    return {"rows": rows, "avg": avg}


def main():
    ap = argparse.ArgumentParser(description="Phase 18 eval: local Qwen2.5-7B (grounded) vs cloud cheap tier.")
    ap.add_argument("--count", type=int, default=5, help="cards per passage (default 5)")
    ap.add_argument("--n", type=int, default=0, help="limit the number of passages (0 = all)")
    ap.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    ap.add_argument("--model", default="qwen2.5:7b-instruct")
    ap.add_argument("--cloud", action="store_true", help="also run the cloud cheap tier (needs a provider key)")
    ap.add_argument("--out", default="", help="write the JSON report to this path")
    args = ap.parse_args()

    samples = SAMPLES[: args.n] if args.n else SAMPLES

    # Point the seam's local tier at the endpoint for this run (no env needed).
    if not llm.local_enabled():
        llm.LOCAL_BASE_URL = args.base_url.strip()
    llm.LOCAL_MODEL = args.model
    llm.LOCAL_TASKS = ("cards",)

    print(f"\nPhase 18 card eval — {len(samples)} passage(s), up to {args.count} cards each")
    print(f"local: {llm.LOCAL_MODEL} @ {llm.LOCAL_BASE_URL}")
    report = {"when": time.strftime("%Y-%m-%d %H:%M"), "count": args.count,
              "local_model": llm.LOCAL_MODEL, "sides": {}}

    print("\nLOCAL (grounded):")
    report["sides"]["local"] = run_side("local", gen_local, samples, args.count)

    if args.cloud:
        if llm.has_key():
            print(f"\nCLOUD cheap tier ({llm.default_model('cheap')} via {llm.PROVIDER}):")
            report["sides"]["cloud"] = run_side("cloud", gen_cloud, samples, args.count)
        else:
            print(f"\nCLOUD skipped: no {llm.key_name()} in the environment.")
    else:
        print("\nCLOUD skipped: pass --cloud with a provider key set to run the baseline.")

    print("\n=== averages (quality over produced cards) ===")
    for side, data in report["sides"].items():
        a = data["avg"]
        print(f"  {side:6}  faithfulness={a['faithfulness']}  usefulness={a['usefulness']}  "
              f"(quality n={a['quality_samples']}, empty={a['empty_samples']}, "
              f"cards={a['cards_produced']}, yield={a['yield']})")

    print("\nA fuller eval (needs wall power + the live DB):")
    print("  - a frozen gold set of the user's own ticked files, not these 3 public passages;")
    print("  - judge each card against his EDITED cards (the real feedback signal captured in card_gen_samples);")
    print("  - an LLM judge for nuance (soundness, exam relevance) beyond the citation-grounding proxy;")
    print("  - more cards per passage and several Qwen tags, before flipping 'cards' to local by default.")

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
