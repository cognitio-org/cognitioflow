"""Calibration harness for the ingest quality Assessor.

Measures whether a quality "assessor" catches deliberately-injected errors in legal study notes —
the EVIDENCE that the quality gate works before we trust it. Hands-free card-generation unlocks
only at 100% catch-rate (and 0% false-holds) on the real per-course calibration set.

The assessor is a pluggable callable so the real one (citecheck + LLM council vs course materials)
wires in later:  assess(note_text: str, materials: str) -> {"verdict": "PASS"|"REVISE"|"HOLD", "issues": [...]}

Pure standard library; runs anywhere.
"""
from __future__ import annotations
import re

# --- error injectors: f(text) -> (mutated_text, description). Return ("","") if the pattern isn't present. ---
_WRONG_CASES = ["Marshall v Southampton", "Brasserie du Pecheur", "Keck and Mithouard", "Nold v Commission"]


def inject_wrong_case_name(text):
    """Swap a 'X v Y' case citation for a plausible but wrong one."""
    m = re.search(r"\b([A-Z][\w.\-]+(?:\s+[A-Z][\w.\-]+){0,3})\s+v\.?\s+([A-Z][\w.\-]+(?:\s+[A-Z][\w.\-]+){0,3})\b", text)
    if not m:
        return "", ""
    wrong = next((w for w in _WRONG_CASES if w.lower() not in text.lower()), "Nold v Commission")
    return text[:m.start()] + wrong + text[m.end():], f"case '{m.group(0)}' -> '{wrong}'"


def inject_wrong_article(text):
    """Bump an article/section number so a cited provision is wrong."""
    m = re.search(r"\b([Aa]rt(?:icle)?\.?\s*)(\d{1,3})\b", text)
    if not m:
        return "", ""
    orig = int(m.group(2))
    return text[:m.start()] + m.group(1) + str(orig + 9) + text[m.end():], f"article {orig} -> {orig + 9}"


def inject_fake_holding(text):
    """Append a fabricated holding not supported by the materials."""
    fake = " The Court held that national courts may disapply EU law whenever domestic policy so requires."
    return text.rstrip() + fake, "appended a fabricated holding"


INJECTORS = {
    "wrong_case_name": inject_wrong_case_name,
    "wrong_article": inject_wrong_article,
    "fake_holding": inject_fake_holding,
}


def run_calibration(samples, assessor):
    """Run the assessor over each clean sample (expect PASS) and over each injected error (expect HOLD/REVISE)."""
    per = {k: {"ran": 0, "caught": 0} for k in INJECTORS}
    clean_pass = clean_total = 0
    for s in samples:
        clean_total += 1
        if (assessor(s["clean_text"], s.get("materials", "")) or {}).get("verdict", "PASS") == "PASS":
            clean_pass += 1
        for name, inj in INJECTORS.items():
            bad, _desc = inj(s["clean_text"])
            if not bad or bad == s["clean_text"]:
                continue  # pattern absent in this sample -> skip (NOT counted as a miss)
            per[name]["ran"] += 1
            if (assessor(bad, s.get("materials", "")) or {}).get("verdict", "PASS") in ("HOLD", "REVISE"):
                per[name]["caught"] += 1
    ran = sum(p["ran"] for p in per.values())
    caught = sum(p["caught"] for p in per.values())
    return {
        "catch_rate": (caught / ran) if ran else None,
        "caught": caught, "injected": ran,
        "false_hold_rate": ((clean_total - clean_pass) / clean_total) if clean_total else None,
        "clean_pass": clean_pass, "clean_total": clean_total,
        "per_injector": per,
    }


def print_report(r):
    print("=== Assessor calibration ===")
    cr = r["catch_rate"]
    print(f"catch-rate: {cr*100:.0f}%  ({r['caught']}/{r['injected']} injected errors caught)"
          if cr is not None else "catch-rate: n/a (no errors injected)")
    fh = r["false_hold_rate"]
    if fh is not None:
        print(f"false-hold-rate: {fh*100:.0f}%  ({r['clean_total']-r['clean_pass']}/{r['clean_total']} clean notes wrongly held)")
    for name, p in r["per_injector"].items():
        if p["ran"]:
            print(f"  {name:16s}: {p['caught']}/{p['ran']} caught")
    gate = (cr == 1.0 and (fh or 0) == 0.0)
    print(f"\nHANDS-FREE GATE: {'PASS -> safe to auto-generate cards' if gate else 'FAIL -> keep cards a manual tap'}")
    return gate


if __name__ == "__main__":
    # Stub assessor ONLY to prove the harness runs end-to-end. The REAL assessor = citecheck + an LLM
    # council judging the note against the course's human-provenance materials (built next, server-side in CF).
    def stub_assessor(note, materials):
        bad = ("national courts may disapply EU law whenever domestic policy" in note
               or re.search(r"[Aa]rticle 276\b", note) or "Marshall v Southampton" in note)
        return {"verdict": "HOLD" if bad else "PASS", "issues": []}

    samples = [{
        "name": "sample-eu",
        "clean_text": ("In Van Gend en Loos the Court established direct effect; Costa v ENEL confirmed the "
                       "supremacy of EU law. See Article 267 TFEU on the preliminary reference procedure."),
        "materials": "Van Gend en Loos; Costa v ENEL; Article 267 TFEU; direct effect; supremacy.",
    }]
    print_report(run_calibration(samples, stub_assessor))
