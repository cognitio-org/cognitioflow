"""CF Game Studio, Phase 2, adapter part 1 (slice S3): pure projections from a finished docket game
to the inputs the quality gates read. No gate imports, no I/O, no model calls. Part 2 (S4) runs the gates.

Selection rule (design section 2): a wrong option is wrong on purpose, so its `text` and `story` never
reach the terminology gate or doctrine pass 1; they go only to doctrine pass 2 (distractors_for_review).
Every option's `teaching` IS checked everywhere, because teaching states the law. The same holds for
produce kinds: only the answer key is projected, never the taxonomy, decoys or unused bank/elements.

The verdict's IRAC rules are one extra unit ("verdict"), not mapped to rounds: the writer's schema does
not tie IRAC entries to rounds, and a game may carry one IRAC entry for three rounds.

Every item is {"id", "kind", "cites", "source_text", "generated_text"}. An item that cites nothing is
checked against ALL sources (the fail-closed direction: more protected terms, more for the reviewer).
"""
import docketgen

SOURCE_CAP = 12_000          # chars of cited source text per item


def _keys_in(text) -> list:
    """The source keys cited inline as [S1] or [S1 p.4], in order of appearance."""
    return [m.group(1) for m in docketgen._CITE.finditer(str(text or ""))]


def _add_keys(out: list, keys) -> None:
    for k in keys or []:
        k = docketgen._cite_key(k)
        if k and k not in out:
            out.append(k)


def _join(parts) -> str:
    return "\n".join(str(p).strip() for p in parts if str(p or "").strip())


def _rounds(game: dict):
    """(scene, quiz) for every examination round, in play order."""
    for s in (game.get("scenes") if isinstance(game, dict) else None) or []:
        if isinstance(s, dict) and isinstance(s.get("quiz"), dict):
            yield s, s["quiz"]


def _qid(s: dict, q: dict) -> str:
    return str(q.get("id") or s.get("id") or "q")


def _kind(q: dict) -> str:
    return str(q.get("kind") or "mcq").lower()


def _options(q: dict) -> list:
    opts = q.get("options")
    return [o for o in opts if isinstance(o, dict)] if isinstance(opts, list) else []


def _answer_lines(q: dict) -> list:
    """The correct answer of a produce-kind round as plain lines. Taxonomy, decoys, bank items outside
    the sequence and elements no fact maps to are distractors and are left out."""
    ans = q.get("answer") if isinstance(q.get("answer"), dict) else {}
    kind = _kind(q)
    if kind == "spot":
        return [str(it.get("label") or it.get("id") or "") for it in ans.get("issues") or [] if isinstance(it, dict)]
    if kind == "order":
        bank = {str(b.get("id")): str(b.get("label") or b.get("id")) for b in ans.get("bank") or [] if isinstance(b, dict)}
        return [f"{i}. {bank.get(str(x), str(x))}" for i, x in enumerate(ans.get("sequence") or [], 1)]
    if kind == "slot":
        facts = {str(f.get("id")): str(f.get("label") or f.get("id")) for f in ans.get("facts") or [] if isinstance(f, dict)}
        elems = {str(e.get("id")): str(e.get("label") or e.get("id")) for e in ans.get("elements") or [] if isinstance(e, dict)}
        key = ans.get("key") if isinstance(ans.get("key"), dict) else {}
        return [f"{facts.get(str(f), str(f))} -> {elems.get(str(e), str(e))}" for f, e in key.items()]
    return []


def _round_cites(q: dict, generated: str) -> list:
    out = []
    _add_keys(out, q.get("cites"))
    for o in _options(q):
        _add_keys(out, o.get("cites"))
    _add_keys(out, _keys_in(generated))
    return out


def _irac_rules(game: dict) -> list:
    irac = (game.get("verdict") or {}).get("irac") if isinstance(game.get("verdict"), dict) else None
    return [str(r.get("rule") or "") for r in irac or [] if isinstance(r, dict) and str(r.get("rule") or "").strip()]


def cited_source_text(keys, keyed: dict, cap: int = SOURCE_CAP) -> str:
    """The text of the cited source keys, each under a "[KEY] file" header, in order, without
    duplicates. Each key gets an equal share of `cap` so one long reader cannot crowd out the rest,
    and the whole is cut to `cap`. Keys not in `keyed` are skipped (validate() already rejects them)."""
    known = []
    for k in keys or []:
        k = docketgen._cite_key(k)
        if k and k in keyed and k not in known:
            known.append(k)
    if not known or cap <= 0:
        return ""
    share = max(cap // len(known), 1)
    parts = [f"[{k}] {keyed[k].get('name', '')}\n{str(keyed[k].get('text') or '')[:share]}" for k in known]
    return "\n\n".join(parts)[:cap]


def _item(iid: str, kind: str, cites: list, generated: str, keyed: dict, cap: int) -> dict:
    use = cites or list(keyed)
    return {"id": iid, "kind": kind, "cites": list(cites), "source_text": cited_source_text(use, keyed, cap),
            "generated_text": generated}


def items_for_terminology(game: dict, keyed: dict, cap: int = SOURCE_CAP) -> list:
    """One item per round plus one "verdict" item, for the terminology gate. mcq: the correct option's
    text and every option's teaching (wrong options' text/story excluded). Produce kinds: the teaching
    and the answer-key labels. Verdict: every IRAC rule."""
    out = []
    for s, q in _rounds(game):
        kind = _kind(q)
        if kind == "mcq":
            opts = _options(q)
            parts = [o.get("text", "") for o in opts if o.get("correct") is True] + [o.get("teaching", "") for o in opts]
        else:
            parts = [q.get("teaching", "")] + _answer_lines(q)
        gen = _join(parts)
        out.append(_item(_qid(s, q), kind, _round_cites(q, gen), gen, keyed, cap))
    rules = _irac_rules(game)
    if rules:
        gen = _join(rules)
        cites = []
        _add_keys(cites, _keys_in(gen))
        out.append(_item("verdict", "verdict", cites, gen, keyed, cap))
    return out


def rounds_for_doctrine(game: dict, keyed: dict, cap: int = SOURCE_CAP) -> list:
    """Doctrine pass 1 (support): one item per round plus one "verdict" item. A round carries the
    question, a spot round's fact text (context the reviewer needs), the correct answer and ALL
    teaching. Wrong options' text/story are excluded: the support prompt fails anything the source
    does not support, and a deliberate distractor never is."""
    out = []
    for s, q in _rounds(game):
        kind = _kind(q)
        parts = [f"QUESTION: {q.get('question', '')}"]
        if kind == "spot" and str(q.get("text") or "").strip():
            parts.append(f"FACTS: {q['text']}")
        if kind == "mcq":
            opts = _options(q)
            parts += [f"CORRECT ANSWER: {o.get('text', '')}" for o in opts if o.get("correct") is True]
            parts += [f"TEACHING ({o.get('key', '?')}): {o['teaching']}" for o in opts if str(o.get("teaching") or "").strip()]
        else:
            parts += [f"CORRECT ANSWER: {line}" for line in _answer_lines(q)]
            if str(q.get("teaching") or "").strip():
                parts.append(f"TEACHING: {q['teaching']}")
        gen = _join(parts)
        out.append(_item(_qid(s, q), kind, _round_cites(q, gen), gen, keyed, cap))
    rules = _irac_rules(game)
    if rules:
        gen = _join(f"IRAC RULE: {r}" for r in rules)
        cites = []
        _add_keys(cites, _keys_in(gen))
        out.append(_item("verdict", "verdict", cites, gen, keyed, cap))
    return out


def distractors_for_review(game: dict, keyed: dict, cap: int = SOURCE_CAP) -> list:
    """Doctrine pass 2 (distractors): one item per wrong mcq option, carrying its text, story and
    teaching plus the round's question. Produce kinds have no distractor options and yield nothing."""
    out = []
    for s, q in _rounds(game):
        if _kind(q) != "mcq":
            continue
        for o in _options(q):
            if o.get("correct") is True:
                continue
            gen = _join([f"OPTION: {o.get('text', '')}" if str(o.get("text") or "").strip() else "",
                         f"STORY: {o.get('story', '')}" if str(o.get("story") or "").strip() else "",
                         f"TEACHING: {o.get('teaching', '')}" if str(o.get("teaching") or "").strip() else ""])
            cites = []
            _add_keys(cites, q.get("cites"))
            _add_keys(cites, o.get("cites"))
            _add_keys(cites, _keys_in(gen))
            item = _item(f"{_qid(s, q)}:{o.get('key', '?')}", "distractor", cites, gen, keyed, cap)
            item["round"], item["key"], item["question"] = _qid(s, q), str(o.get("key", "?")), str(q.get("question", ""))
            out.append(item)
    return out
