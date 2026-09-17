"""
Phase 6 acceptance helper: EU Drill transcript before/after on a fixed question.
"before" = the original hand-written EU prompt (prompts/eu_law.md); "after" = the compiled EU brief (prompts/eu_law.json).
System blocks are built exactly as run.chat() builds them, with no course files ticked. CF_MODEL only, temperature 0, 2 calls.

    python3 scripts/drill_compare_eu.py            # writes data/phase6-drill/eu-before.md and eu-after.md
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
os.environ.setdefault("CF_WHISPER_PRELOAD", "0")

import anthropic  # noqa: E402
import course_brief as cb  # noqa: E402
import run  # noqa: E402

QUESTION = "Drill me on the Art 34 scope test."
out = ROOT / "data" / "phase6-drill"; out.mkdir(parents=True, exist_ok=True)
prompts = {"before": run.EU_PROMPT, "after": cb.compile_prompt(cb.load_seed_brief("eu_law"), "European Law")}
client = anthropic.Anthropic()
for label, course_prompt in prompts.items():
    system = [{"type": "text", "text": run.BASE_PROMPT + "\n" + course_prompt + "\n" + run.MODES["drill"]},
              {"type": "text", "text": "COURSE FILES: none selected. Say so if the question needs them."}]
    m = client.messages.create(model=run.MODEL, max_tokens=2000, temperature=0, system=system,
                               messages=[{"role": "user", "content": QUESTION}])
    reply = "".join(b.text for b in m.content if b.type == "text")
    (out / f"eu-{label}.md").write_text(
        f"# EU Drill transcript — {label}\n\nmodel: {m.model} · temperature 0 · no files ticked · "
        f"tokens in {m.usage.input_tokens} / out {m.usage.output_tokens}\n\n## Course prompt\n\n```\n{course_prompt}\n```\n\n"
        f"## User\n\n{QUESTION}\n\n## Tutor\n\n{reply}\n", encoding="utf-8")
    print(f"==== {label}\n{reply}\n")
print(f"Saved to {out}")
