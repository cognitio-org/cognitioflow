# Studio exemplars (few-shot games)

Empty on purpose. The model-quality plan (rung 1, item 4) found that **no existing game qualifies**: every game so
far scores generation_ratio 0.00 and the hand-made IIEL games have unknown authorship.

An exemplar is used by `studio/context.load_exemplars` only if ALL of these hold (checked in code, fail closed):

- `author` is `matej` or `local-model+matej-corrected` (never a Claude/GPT/Gemini-written or -assisted game);
- `edit_assisted` is literally `false`;
- `provenance` is `clean` (see the provenance record, `studio/provenance.py`);
- its gate card has `overall_pass: true`;
- its course/week is a **dev** week in `studio/eval/split.json` (never held-out);
- it carries `game` (the writer's intermediate shape) and `mix` (A-D).

At most 3 are used per course, one per round mix first.

To add one: write `exemplars/<id>.json` with those fields and add `{"id", "file", "course"}` to `index.json`.
Bootstrap (plan): one gold game per mix from a dev week, written or corrected by Matej.
