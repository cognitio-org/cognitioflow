"""CF Game Studio, Phase 2, docket adapter.

Part 1 (slice S3): pure projections from a finished docket game to the inputs the quality gates read.
No gate imports, no I/O, no model calls.

Part 2 (slice S4, below the projections): `gate_docket(...)` runs every gate fail-closed through
`harness.run_gate` and returns a schema-valid review card dict (never raises); `block_message(card)`
turns a failing card into the error prefix S8 counts. Gate modules are imported lazily by `_gates()`,
so importing this module still needs only `docketgen` and the stdlib.

Selection rule (design section 2): a wrong option is wrong on purpose, so its `text` and `story` never
reach the terminology gate or doctrine pass 1; they go only to doctrine pass 2 (distractors_for_review).
Every option's `teaching` IS checked everywhere, because teaching states the law. The same holds for
produce kinds: only the answer key is projected, never the taxonomy, decoys or unused bank/elements.

The verdict's IRAC rules are one extra unit ("verdict"), not mapped to rounds: the writer's schema does
not tie IRAC entries to rounds, and a game may carry one IRAC entry for three rounds.

Every item is {"id", "kind", "cites", "source_text", "generated_text"}. An item that cites nothing carries
ALL sources in its `source_text` (the doctrine reviewer then sees everything). The S4 terminology gate does
NOT use that: an uncited item fails terminology as "uncited", and a cited item is checked against each cited
source's whole text on its own (no cut: the v2 writer reads passages from anywhere in a file), never against a
join that one source's synonym can silence.

Structural check (S4 fix rounds 4-5): `content_problems(final)` walks the gated player-visible fields of the raw game
(title, questions, every option's text on its own and never through its story, teaching, story, outcome titles,
produce answer items, round and verdict IRAC, takeaway; its docstring lists them and the ungated narrative chrome)
and lists the ones with no real word (see `has_real_word`). Terminology and doctrine both fail on it before any lexicon or reviewer work; their own per-pass
"no text to check" checks stay behind it as defence in depth.
"""
import copy
import hashlib
import importlib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from types import SimpleNamespace

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
            # The key is on the correct answer and the wrong options' teachings say so, so the judge never has to
            # guess which option is the right one (p5 c2 q2: a correct B was judged "presented as a wrong option").
            parts += [f"CORRECT ANSWER ({o.get('key', '?')}): {o.get('text', '')}" for o in opts if o.get("correct") is True]
            parts += [f"TEACHING ({o.get('key', '?')}{'' if o.get('correct') is True else ', wrong option'}): {o['teaching']}"
                      for o in opts if str(o.get("teaching") or "").strip()]
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
            # S4: review_distractor takes the option and its teaching separately (same strings as generated_text).
            item["option_text"] = _join([f"OPTION: {o.get('text', '')}" if str(o.get("text") or "").strip() else "",
                                         f"STORY: {o.get('story', '')}" if str(o.get("story") or "").strip() else ""])
            item["teaching"] = str(o.get("teaching") or "")
            item["option"] = o.get("text") if isinstance(o.get("text"), str) else ""   # raw, without the story
            out.append(item)
    return out


# ================================================================================================= part 2 (S4)
# gate_docket(...) runs every gate over a finished docket game and returns the review card; it never raises.
# Brief: ~/reports/cf-studio-s4-brief.md. Owner decisions applied on top of the brief:
#   * gates whose driver is not merged yet (playability: S6, accessibility: S7, polish: S6 screenshot) appear
#     on the card as advisory "not wired" gates (mandatory False, not_wired True): they never block and are
#     never in `enforced`. A runtime that supplies the probe (tests now, S6/S7 later) wires them back in as
#     design-mandatory gates, so they become enforceable once S6/S7 land with no change here.
#   * course -> lexicon by LEXICON_ALIASES (eu -> eu-law, prop -> property, pil -> pil), overridable per id/slug
#     with CF_STUDIO_LEXICON_MAP="id_or_slug=file,...".

CARD_SCHEMA = "studio-card/1"
CARD_MAX_BYTES = 32_768          # what the review JSONB column may hold per card
DETAIL_MAX = 2_000               # every gate detail starts at most this long
DOCTRINE_SOURCE_CAP = 32_000     # chars of source per doctrine item (env CF_STUDIO_DOCTRINE_SOURCE_CAP)
DOCTRINE_CHUNK = 2_000           # relevance-window chunk size, nudged to the nearest paragraph break
DOCTRINE_BUDGET_S = 1500.0       # doctrine wall-clock budget (env CF_STUDIO_DOCTRINE_BUDGET_S)
GAP = "\n[…]\n"                  # marks omitted source between two kept, non-adjacent chunks
_GAP_MARK = GAP.strip()

GATE_ORDER = ("terminology", "doctrine", "retrieval", "self_contained", "citations", "reviewer_high",
              "playability", "accessibility", "polish")
ADVISORY_GATES = frozenset({"polish"})                    # never blocks, by design
DESIGN_MANDATORY = tuple(g for g in GATE_ORDER if g not in ADVISORY_GATES)
GATE_ALIASES = {"a11y": "accessibility"}
LEXICON_ALIASES = {"eu": "eu-law", "prop": "property", "pil": "pil"}
DEFAULT_REQUIRED_SELECTORS = ("#app", "#stage")
NOT_WIRED_DETAIL = {"playability": "not wired: needs S6 driver (advisory until S6 lands)",
                    "accessibility": "not wired: needs S7 probe (advisory until S7 lands)",
                    "polish": "not wired: needs S6 screenshot (advisory)"}

_STUDIO_DIR = Path(__file__).resolve().parent
_GATES_DIR = _STUDIO_DIR / "gates"
PLAYER_DIR = _STUDIO_DIR.parent / "play" / "player"
_GATE_MODULES = ("harness", "terminology_lock", "doctrinal_review", "retrieval_density", "self_contained",
                 "playability", "a11y", "aesthetic_judge")
_ENGINE_EXT = (".js", ".html", ".css")
_ENGINE_SKIP = ("vendor-", "assets-", "fonts-")

_loaded = None
_bundle_cache: dict = {}


def _gates() -> SimpleNamespace:
    """Import the gate modules (bare imports, so studio/gates goes on sys.path) and studio.runtime, once.
    Appended, not prepended, so nothing in studio/gates can shadow an app module; a gate module that still
    resolves somewhere else is refused rather than silently used."""
    global _loaded
    if _loaded is None:
        gdir = str(_GATES_DIR)
        if gdir not in sys.path:
            sys.path.append(gdir)
        mods = {name: importlib.import_module(name) for name in _GATE_MODULES}
        for name, mod in mods.items():
            if Path(getattr(mod, "__file__", "") or ".").resolve().parent != _GATES_DIR:
                raise ImportError(f"gate module {name!r} resolved outside studio/gates: {mod.__file__}")
        mods["runtime"] = importlib.import_module("studio.runtime")
        _loaded = SimpleNamespace(**mods)
    return _loaded


# ---------------------------------------------------------------------------------------------- small helpers

def _safe(x) -> str:
    try:
        return str(x)
    except Exception:  # noqa: BLE001
        return "<unprintable>"


def _short(x, n: int = 200) -> str:
    s = x if isinstance(x, str) else _safe(x)
    return s if len(s) <= n else s[:max(n - 1, 0)] + "…"


def _rt(runtime, name: str):
    """One field of the test-seam runtime (dict or object); None when absent."""
    if runtime is None:
        return None
    if isinstance(runtime, dict):
        return runtime.get(name)
    return getattr(runtime, name, None)


def _env_positive(name: str, default, cast, warnings: list):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
        if not (value > 0) or value == float("inf"):
            raise ValueError(raw)
        return value
    except (TypeError, ValueError, OverflowError):
        warnings.append(f"{name}={_short(raw, 40)!r} is not a positive number; using {default}")
        return default


def _known_keys(keys, keyed: dict) -> list:
    known = []
    for k in keys or []:
        k = docketgen._cite_key(k)
        if k and k in keyed and k not in known:
            known.append(k)
    return known


def _has_source(keys, keyed: dict) -> bool:
    """At least one known cited key with non-blank text (a "[S1] name" header alone is not a source)."""
    return any(str((keyed[k] or {}).get("text") or "").strip() for k in _known_keys(keys, keyed))


# ---------------------------------------------------------------------------- doctrine source relevance windows

_STOP = frozenset("""a an and are as at be been being but by can could did do does for from had has have he her
his if in into is it its may might must no nor not of on or our shall she should so such than that the their them
then there these they this those to under was we were what when where which who whom why will with would you your
question correct answer teaching irac rule option story facts""".split())
_WORD = re.compile(r"[a-z0-9]+")


def _words(text) -> set:
    return {w for w in _WORD.findall(str(text).lower()) if len(w) > 1 and w not in _STOP}


# The adapter's own projection labels, at line start. TEACHING's parenthetical is game-controlled (an option key), so it
# goes whole: a key like "opt1" must not count as a word of content.
_LABEL = re.compile(r"^[ \t]*(?:QUESTION|CORRECT ANSWER(?:[ \t]*\([^)\n]*\))?|TEACHING(?:[ \t]*\([^)\n]*\))?|FACTS|IRAC RULE|OPTION|STORY)"
                    r"[ \t]*:", re.M)
# Characters that render as nothing. The Hangul fillers are category Lo (letters!), so they are named; every other
# format character (Cf: zero-width space/joiners, word joiner, BOM, soft hyphen, tag characters) goes by category.
_FILLERS = frozenset("\u3164\u115f\u1160\uffa0\u200b\u200c\u200d\u2060\ufeff")


def _visible(text: str) -> str:
    return "".join(c for c in text if c not in _FILLERS and unicodedata.category(c) != "Cf")


# Citation shorthand (Matej, 2026-11-11: the word rule is STRICT). A whole token, any case, with an optional dot and
# the page locator that follows it ("pp. 4-7", "Id. at 5", "ibid., 34", "op. cit., p. 12"): none of it is content.
_LOCATOR = r"(?:[ \t]*,?[ \t]*(?:at[ \t]+)?\d+(?:[ \t]*[-\u2013\u2014][ \t]*\d+)?(?:[ \t]*(?:ff?|et[ \t]+seqq?)(?!\w)\.?)?)*"
_SHORTHAND = re.compile(r"(?<!\w)(?:pp|p|id|ibid|ibidem|op\.?[ \t]*cit|loc\.?[ \t]*cit|et[ \t]+seqq?|cf|supra|infra|ff)(?!\w)\.?"
                        + _LOCATOR, re.I)


def has_real_word(text) -> bool:
    """True when `text` (a str; anything else is wordless) holds a real word once invisible/filler characters, cite
    markers ([S1], [S1 p.4]), citation shorthand with its page locator (pp., p., Id., ibid(em), op. cit., loc. cit.,
    cf., supra, infra, et seq., ff.) and the adapter's projection labels are removed. A real word is a run of >= 2
    Unicode letters (category L*; combining marks inside a run neither break nor count), or a number: a run of decimal
    digits with no letter directly before or after it. So '1957', 'C-6/90', '§ 4', '34 (2)' and 'Art. 28' count
    (the STRICT rule, Matej 2026-11-11), while '[S1]', '[S1] pp. 4', 'Id.', 'ibid', 'a', 'a b', '?', a row of U+3164
    and a raw id such as 'e1' (its digit is glued to a letter) do not."""
    if not isinstance(text, str):
        return False
    s = _SHORTHAND.sub(" ", _LABEL.sub(" ", docketgen._CITE.sub(" ", _visible(text))))
    run, prev = 0, ""
    n = len(s)
    i = 0
    while i < n:
        c = s[i]
        cat = unicodedata.category(c)
        if cat == "Nd":
            j = i
            while j < n and unicodedata.category(s[j]) == "Nd":
                j += 1
            before = unicodedata.category(s[i - 1])[0] if i else ""
            after = unicodedata.category(s[j])[0] if j < n else ""
            if before != "L" and after != "L" and not (before == "M" and run):
                return True
            run, i = 0, j
            continue
        if cat[0] == "L":
            run += 1
            if run >= 2:
                return True
        elif not (cat[0] == "M" and run):
            run = 0
        i += 1
    return False


def _no_words(text) -> bool:
    """The per-pass pre-check (terminology; doctrine pass 1; each distractor's option and teaching in doctrine
    pass 2), kept as defence in depth behind content_problems: True when the projected `text` has no real word."""
    return not has_real_word(text if isinstance(text, str) else str(text or ""))


def _absent(v) -> bool:
    """What the player treats as no value at all: None or '' (play/player/data.js str(): v == null ? '' : String(v),
    then plain JS truthiness in quiz.js). Anything else renders, including whitespace or filler only."""
    return v is None or (isinstance(v, str) and v == "")


def _shown_label(x) -> object:
    """What the player renders for an answer item: its label, else its id (play/player/data.js: label || id)."""
    if not isinstance(x, dict):
        return None
    label = x.get("label")
    return label if isinstance(label, str) and label else x.get("id")


_PRODUCE_ITEMS = {"spot": "issues", "order": "sequence", "slot": "key"}
_PRODUCE_LISTS = ("issues", "taxonomy", "bank", "facts", "elements")
_IRAC_PARTS = ("issue", "rule", "application", "conclusion")


def _labels_by_id(items) -> dict:
    """id -> shown label for the answer items the player keeps (data.js drops an item with no id)."""
    out = {}
    for x in items if isinstance(items, list) else []:
        if isinstance(x, dict) and not _absent(x.get("id")):
            out.setdefault(str(x.get("id")), _shown_label(x))
    return out


def content_problems(final) -> list:
    """The gated player-visible fields of the game, from the raw dict, that have no real word (see has_real_word), as
    "<where>:<field>: no words"; plus structural holes ("game: no rounds", "qN:options: no wrong option",
    "qN:options: no correct option", "qN:answer: no items", "qN:kind: unknown kind"). Empty when clean.

    Required (must have a word): the game title; each round's question (and prompt, if present); every option's
    text, correct and wrong, checked on its own and never through its story; every wrong option's teaching; a
    produce round's teaching, a spot round's fact text and every answer item the player sees (issues, taxonomy,
    bank, facts, elements, plus each order sequence id and slot key fact/element the player shows as a raw id because
    no bank/fact/element label resolves it); every verdict IRAC rule.
    Optional (skipped only when the player treats it as absent, None or ''; any other value, whitespace- or
    filler-only included, needs a word, because quiz.js renders it on plain truthiness): a correct option's teaching,
    any option's story and outcome_title, each round's IRAC issue/rule/application/conclusion, the verdict IRAC
    issue/application/conclusion, the verdict takeaway and the game-level takeaway. Hand-authored games leave the
    correct option's teaching and story ''.
    Narrative chrome (strict review of #201), gated the way play/player/data.js keeps it: the logline and
    learning_goal (optional); each case_file entry, scene action line (a scalar action is one line), removed entry
    and checks claim that is not absent; each scene title that is not absent (data.js shows 'Scene N' instead); each
    dialogue line that is not absent (data.js drops the rest) and that line's speaker if not absent; each source's
    file (a string value is the file), kind and note if not absent; each scene slug part (int_ext, place, time; a
    string slug is the place) if not absent; the verdict outcome when quiz.js shows it (more
    than two whitespace-separated tokens). The verdict IRAC is read as data.js reads it: a list, else any truthy
    value as one entry. Not gated: ids, set, phase, shot fields (camera directions), source keys, bible,
    coordinator_notes (none is shown as text). Pure, stdlib + docketgen only; never raises on a malformed game."""
    out = []

    def need(where, v):
        if not has_real_word(v):
            out.append(f"{where}: no words")

    def optional(where, v):
        if not _absent(v):
            need(where, v)

    def irac_parts(where, irac, required=()):
        for part in _IRAC_PARTS:
            (need if part in required else optional)(f"{where}.{part}", irac.get(part) if isinstance(irac, dict) else None)

    def each(where, items):
        items = items if isinstance(items, list) else ([items] if items else [])
        for i, v in enumerate(items):
            optional(f"{where}[{i}]", v)

    g = final if isinstance(final, dict) else {}
    need("game:title", g.get("title"))
    optional("game:takeaway", g.get("takeaway"))
    optional("game:logline", g.get("logline"))
    optional("game:learning_goal", g.get("learning_goal"))
    each("game:case_file", g.get("case_file") if isinstance(g.get("case_file"), list) else [])
    each("game:removed", g.get("removed") if isinstance(g.get("removed"), list) else [])
    for i, c in enumerate(g.get("checks") if isinstance(g.get("checks"), list) else []):
        optional(f"game:checks[{i}].claim", c.get("claim") if isinstance(c, dict) else None)
    sources = g.get("sources")
    for k, v in (sources.items() if isinstance(sources, dict) else ()):
        where = f"game:sources[{_short(k, 20)}]"
        if isinstance(v, dict):
            optional(f"{where}.file", v.get("file") or v.get("name"))
            optional(f"{where}.kind", v.get("kind"))
            optional(f"{where}.note", v.get("note"))
        else:
            optional(f"{where}.file", v)
    for n, sc in enumerate(g.get("scenes") if isinstance(g.get("scenes"), list) else [], 1):
        if not isinstance(sc, dict):
            continue
        sid = _short(sc.get("id") or f"s{n}", 40)
        if sc.get("title"):                                # data.js: title || `Scene ${i + 1}`
            need(f"{sid}:title", sc.get("title"))
        slug = sc.get("slug")                              # main.js slugText: the title card's location line
        if isinstance(slug, dict):
            for part in ("int_ext", "place", "time"):
                optional(f"{sid}:slug.{part}", slug.get(part))
        elif slug:
            optional(f"{sid}:slug.place", slug)
        each(f"{sid}:action", sc.get("action"))
        for i, d in enumerate(sc.get("dialogue") if isinstance(sc.get("dialogue"), list) else []):
            line = d.get("line") if isinstance(d, dict) else None
            if not _absent(line):                          # data.js drops a dialogue entry with no line
                need(f"{sid}:dialogue[{i}].line", line)
                if d.get("speaker"):
                    need(f"{sid}:dialogue[{i}].speaker", d.get("speaker"))
    rounds = list(_rounds(final))
    if not rounds:
        out.append("game: no rounds")
    for s, q in rounds:
        qid = _short(_qid(s, q), 40)
        kind = _kind(q)
        need(f"{qid}:question", q.get("question"))
        if "prompt" in q:
            need(f"{qid}:prompt", q.get("prompt"))
        if kind == "mcq":
            opts = _options(q)
            if not any(o.get("correct") is True for o in opts):
                out.append(f"{qid}:options: no correct option")
            if not any(o.get("correct") is not True for o in opts):
                out.append(f"{qid}:options: no wrong option")
            for i, o in enumerate(opts, 1):
                k = f"{qid}:{_short(o.get('key') or f'option{i}', 20)}"
                need(f"{k}.text", o.get("text"))
                (optional if o.get("correct") is True else need)(f"{k}.teaching", o.get("teaching"))
                optional(f"{k}.story", o.get("story"))
                optional(f"{k}.outcome_title", o.get("outcome_title"))
        elif kind in _PRODUCE_ITEMS:
            ans = q.get("answer") if isinstance(q.get("answer"), dict) else {}
            need(f"{qid}:teaching", q.get("teaching"))
            if kind == "spot":
                need(f"{qid}:text", q.get("text"))
            if not ans.get(_PRODUCE_ITEMS[kind]):
                out.append(f"{qid}:answer: no items")
            for coll in _PRODUCE_LISTS:
                items = ans.get(coll)
                for i, x in enumerate(items if isinstance(items, list) else []):
                    need(f"{qid}:{coll}[{i}].label", _shown_label(x))
            if kind == "order":                       # quiz.js: an empty bank, or an id not in it, shows the raw id
                bank = _labels_by_id(ans.get("bank"))
                seq = ans.get("sequence")
                for i, x in enumerate(seq if isinstance(seq, list) else []):
                    if _absent(x) or str(x) not in bank:
                        need(f"{qid}:sequence[{i}]", x)
            elif kind == "slot":                      # quiz.js model key: fact/element label, else the raw id
                facts, elems = _labels_by_id(ans.get("facts")), _labels_by_id(ans.get("elements"))
                key = ans.get("key")
                for f, e in (key.items() if isinstance(key, dict) else ()):
                    if str(f) not in facts:
                        need(f"{qid}:key[{_short(f, 20)}].fact", f)
                    if _absent(e) or str(e) not in elems:
                        need(f"{qid}:key[{_short(f, 20)}].element", e)
        else:
            out.append(f"{qid}:kind: unknown kind")
        irac_parts(f"{qid}:irac", q.get("irac"))
    verdict = g.get("verdict")
    if isinstance(verdict, dict):
        irac = verdict.get("irac")
        if not isinstance(irac, list):                             # data.js: a list, else any truthy value as [x]
            irac = [irac] if (irac or isinstance(irac, dict)) else []
        for i, r in enumerate(irac if isinstance(irac, list) else []):
            irac_parts(f"verdict:irac[{i}]", r, required=("rule",))
        optional("verdict:takeaway", verdict.get("takeaway"))
        outcome = verdict.get("outcome")
        if isinstance(outcome, str) and outcome and len(re.split(r"\s+", outcome)) > 2:   # quiz.js shows it only then
            need("verdict:outcome", outcome)
    return out


def _chunk_bounds(text: str, size: int = DOCTRINE_CHUNK) -> list:
    """Contiguous (start, end) offsets covering `text`, ~`size` long, each end nudged to the nearest
    paragraph break within +-20% of the target."""
    n, out, start, slack = len(text), [], 0, max(size // 5, 1)
    while start < n:
        target = start + size
        if target >= n:
            out.append((start, n))
            break
        lo, hi = max(start + 1, target - slack), min(n, target + slack)
        end, best = target, None
        i = text.find("\n\n", lo)
        while i != -1 and i + 2 <= hi:
            d = abs(i + 2 - target)
            if best is None or d < best:
                best, end = d, i + 2
            i = text.find("\n\n", i + 1)
        out.append((start, end))
        start = end
    return out


def _assemble(text: str, bounds: list, keep) -> str:
    """Kept chunks in source order: adjacent ones joined verbatim, GAP only where text was left out."""
    parts, prev = [], None
    for i in sorted(keep):
        s, e = bounds[i]
        if prev is not None and s != prev:
            parts.append(GAP)
        parts.append(text[s:e])
        prev = e
    return "".join(parts)


def _window(text: str, gen_words: set, budget: int):
    """(body, windowed): the whole text if it fits `budget`, else the best-scoring chunks that fit."""
    if len(text) <= budget:
        return text, False
    bounds = _chunk_bounds(text)
    score = [len(_words(text[s:e]) & gen_words) for s, e in bounds]
    order = sorted(range(len(bounds)), key=lambda i: (-score[i], bounds[i][0]))
    keep = []
    for i in order:
        if len(_assemble(text, bounds, keep + [i])) <= budget:
            keep.append(i)
    if not keep:                                   # share smaller than one chunk: the best chunk's head
        s, e = bounds[order[0]]
        return text[s:min(e, s + max(budget, 0))], True
    return _assemble(text, bounds, keep), True


def _doctrine_source(keys, keyed: dict, generated_text: str, cap: int):
    known = _known_keys(keys, keyed)
    if not known or cap <= 0:
        return "", []
    share, gen_words = max(cap // len(known), 1), _words(generated_text)
    parts, windowed = [], []
    for k in known:
        header = f"[{k}] {keyed[k].get('name', '')}\n"
        text = str(keyed[k].get("text") or "")         # whole: the v2 writer reads past FILE_CHARS too
        body, cut = _window(text, gen_words, max(share - len(header) - 2, 0))
        if cut:
            windowed.append(k)
        parts.append(header + body)
    return "\n\n".join(parts), windowed


def doctrine_source_text(keys, keyed: dict, generated_text: str, cap: int = DOCTRINE_SOURCE_CAP) -> str:
    """The source the doctrine reviewer reads for one item: one "[KEY] name" block per known cited key, in
    cite order, deduplicated. Each key gets an equal share of `cap`; a key whose whole text fits
    its share goes in whole, otherwise its ~2k-char chunks with the most word overlap with `generated_text`
    are kept (ties: earlier offset) and emitted in source order. Deterministic, stdlib only."""
    return _doctrine_source(keys, keyed, generated_text, cap)[0]


def _source_bodies(keys, keyed: dict) -> list:
    """Terminology's sources: (key, text) for every known cited key, whole, with no header line (a file name is
    not source text), no S3 per-key cap and no FILE_CHARS cut: the v2 writer (ranked_sources_block) reads
    passages from anywhere in a longer file, and a lexicon scan is cheap."""
    return [(k, str(keyed[k].get("text") or "")) for k in _known_keys(keys, keyed)]


def _split_doctrine_source(src: str):
    """doctrinal_review's split_sources hook for the adapter's doctrine source: the default "[Sn] name" header
    split (each key's body on its own), then each body cut at the GAP joiner, so a quote verifies only inside
    one gap-free segment. A real "[…]" elision inside a segment (no surrounding newlines) stays verifiable."""
    bodies, headers = _gates().doctrinal_review.split_source_headers(src)
    return [seg for b in bodies for seg in b.split(GAP)], headers


# ---------------------------------------------------------------------------------------- config: lexicon, flags

def _lexicon_map(warnings: list) -> dict:
    raw = os.environ.get("CF_STUDIO_LEXICON_MAP", "")
    out = {}
    for part in raw.split(","):
        if not part.strip():
            continue
        key, sep, val = part.partition("=")
        key, val = key.strip(), val.strip()
        if not sep or not key or not val:
            warnings.append(f"CF_STUDIO_LEXICON_MAP malformed at {_short(part.strip(), 60)!r}; map ignored")
            return {}
        out[key] = val
    return out


def lexicon_code(course, warnings: list) -> str:
    """The lexicon file stem for a course: CF_STUDIO_LEXICON_MAP, then LEXICON_ALIASES, each looked up by the
    course id first (seed ids are fixed; slugs are editable), then its slug. No mapping: the slug itself."""
    c = course if isinstance(course, dict) else {}
    cid, slug = _safe(c.get("id") or "").strip(), _safe(c.get("slug") or "").strip()
    for table in (_lexicon_map(warnings), LEXICON_ALIASES):
        for key in (cid, slug):
            if key and key in table:
                return table[key]
    return slug


def _lexicon_status(code: str, tl) -> str:
    """The lexicon file's `status` (load_lexicon does not return it). Never fatal."""
    try:
        path = tl.LEXICON_DIR / f"{code}.json"
        if path.exists():
            status = json.loads(path.read_text(encoding="utf-8")).get("status", "")
            return _short(status, 200) if isinstance(status, str) else ""
    except Exception:  # noqa: BLE001
        pass
    return ""


def enforce_set(raw, wired, warnings: list) -> list:
    """The gates that block, from CF_STUDIO_ENFORCE_GATES. Unset/empty -> every wired design-mandatory gate.
    An unknown token -> all (fail closed) + warning. polish and not-wired gates are dropped with a warning.
    Never empty: if nothing is left after dropping, all wired design-mandatory gates + warning."""
    eligible = [g for g in DESIGN_MANDATORY if g in wired]
    tokens = [GATE_ALIASES.get(t, t) for t in (t.strip().lower() for t in _safe(raw or "").split(",")) if t]
    if not tokens:
        return eligible
    unknown = [t for t in tokens if t not in GATE_ORDER]
    if unknown:
        warnings.append("CF_STUDIO_ENFORCE_GATES: unknown gate(s) "
                        + ", ".join(repr(_short(t, 40)) for t in unknown[:10]) + "; enforcing all gates")
        return eligible
    chosen = []
    for t in tokens:
        if t in ADVISORY_GATES:
            warnings.append(f"CF_STUDIO_ENFORCE_GATES: {t} is advisory and never blocks; dropped")
        elif t not in wired:
            warnings.append(f"CF_STUDIO_ENFORCE_GATES: {t} is not wired yet (advisory until S6/S7); dropped")
        elif t not in chosen:
            chosen.append(t)
    if not chosen:
        warnings.append("CF_STUDIO_ENFORCE_GATES left no enforceable gate; enforcing all gates")
        return eligible
    return [g for g in DESIGN_MANDATORY if g in chosen]


# ------------------------------------------------------------------------------------------- engine hash, bundle

def _player_files(exts) -> list:
    return sorted((p for p in PLAYER_DIR.iterdir()
                   if p.is_file() and p.suffix in exts and not p.name.startswith(_ENGINE_SKIP)),
                  key=lambda p: p.name)


def engine_hash() -> str:
    """sha256 over the sorted relative paths and bytes of play/player/*.js, *.html, *.css (not vendor-*,
    assets-*, fonts-*). Changes on uncommitted edits too; needs no git."""
    files = _player_files(_ENGINE_EXT)
    if not files:
        raise FileNotFoundError(f"no player files in {PLAYER_DIR}")
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(PLAYER_DIR).as_posix().encode("utf-8") + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def player_bundle_text(ehash: str = "") -> str:
    """play/player/*.js + index.html as text (what ships to the browser), cached per engine hash."""
    if ehash:
        cached = _bundle_cache.get(ehash)            # one lookup: another thread may clear() in between
        if cached is not None:
            return cached
    files = _player_files((".js",)) + [PLAYER_DIR / "index.html"]
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in files)
    if ehash:
        _bundle_cache.clear()
        _bundle_cache[ehash] = text
    return text


# --------------------------------------------------------------------------------------------------- gate bodies
# Each body takes the run context and returns (passed, detail). Module-level so a test can monkeypatch one to
# raise; gate_docket looks them up by name at call time.

def _g_terminology(ctx):
    problems = content_problems(ctx.final)              # structural: no lexicon, no reviewer
    if problems:
        return False, "; ".join(problems)
    if ctx.lexicon_error is not None:
        raise ctx.lexicon_error
    items = items_for_terminology(ctx.final, ctx.keyed)
    if not any(it["kind"] != "verdict" for it in items):  # an IRAC verdict alone is not a game
        return False, "no items to check (the game has no rounds)"
    problems = []
    for it in items:
        if _no_words(it["generated_text"]):              # blank, or only cite markers: nothing to check
            problems.append(f"{it['id']}: no text to check")
            continue
        if not it["cites"]:                               # never checked against everything: that silences swaps
            problems.append(f"{it['id']}: uncited")
            continue
        if not _has_source(it["cites"], ctx.keyed):
            problems.append(f"{it['id']}: no source text")
            continue
        seen = set()
        for _k, body in _source_bodies(it["cites"], ctx.keyed):   # per source: one cannot silence another
            for v in ctx.g.terminology_lock.check_terminology(body, it["generated_text"], ctx.lexicon):
                swap = f"{v.protected_term}->{v.found_synonym}"
                if swap not in seen:
                    seen.add(swap)
                    problems.append(f"{it['id']}: {swap}")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(items)} items, no dangerous term swaps (lexicon {ctx.lexicon_version})"


def _g_doctrine(ctx):
    problems = content_problems(ctx.final)              # before the reviewer is even built: content, never infra
    if problems:
        return False, "; ".join(problems)
    rt, dr = ctx.g.runtime, ctx.g.doctrinal_review
    start = ctx.clock()                                  # the budget counts doctrine time only
    p1 = rounds_for_doctrine(ctx.final, ctx.keyed)
    p2 = distractors_for_review(ctx.final, ctx.keyed)
    if not any(it["kind"] != "verdict" for it in p1):    # an IRAC verdict alone is not a game
        return False, "no rounds to review (the game has no rounds)"
    has_mcq = any(it["kind"] == "mcq" for it in p1)
    # The pre-check terminology runs, on each round's ANSWER content (correct answer, teaching, IRAC rule): the
    # doctrine text also carries the question, which alone would let a wordless answer through to an ok reviewer.
    # Both projections walk _rounds in order and append the verdict last, so they pair by position.
    answers = items_for_terminology(ctx.final, ctx.keyed)
    wordless = [len(answers) != len(p1) or _no_words(a["generated_text"]) or _no_words(it["generated_text"])
                for a, it in zip(answers, p1)] + [True] * (len(p1) - len(answers))
    reviewer = _rt(ctx.runtime, "reviewer")
    if reviewer is None:
        try:
            reviewer = rt.m4_reviewer()                  # validates host + model; no network
        except Exception as e:  # noqa: BLE001 — GateConfigError and bad env alike block, loudly
            ctx.warnings.append(f"doctrine reviewer refused: {type(e).__name__}: {_short(e, 200)}")
            raise
    ctx.state["reviewer_model"] = _short(getattr(reviewer, "model", "") or "", 200)

    ok = {1: 0, 2: 0}
    shown, content_failed, infra_stop, config_stop, skipped = [], False, None, False, 0
    work = [(1, it) for it in p1] + [(2, it) for it in p2]
    for idx, (pas, it) in enumerate(work):
        if infra_stop or config_stop:                  # circuit breaker: no more reviewer calls
            skipped = len(work) - idx
            break
        if ctx.clock() - start > ctx.budget_s:
            ctx.state["budget_exhausted"] = True
            infra_stop = "GateInfraError: doctrine budget exhausted"
            skipped = len(work) - idx
            break
        use = it["cites"] or list(ctx.keyed)
        src, windowed = _doctrine_source(use, ctx.keyed, it["generated_text"], ctx.doctrine_cap)
        rec = {"id": _short(it["id"], 80), "pass": pas, "ok": False, "issues": [], "quotes_ok": False,
               "source_chars": len(src), "keys_windowed": windowed, "uncited": not it["cites"], "infra": False}
        ctx.doctrine_items.append(rec)
        if (wordless[idx] if pas == 1                    # p1 comes first in `work`, so idx is the p1 index
                else _no_words(it["option"]) or _no_words(it["teaching"])):  # a distractor needs both; a
                # story never stands in for a wordless option text
            rec["issues"] = ["no text to check"]
            content_failed = True
            shown.append(f"{rec['id']}: no text to check")
            continue
        if not _has_source(use, ctx.keyed):
            rec["issues"] = ["no source text"]
            content_failed = True
            shown.append(f"{rec['id']}: no source text")
            continue
        try:
            ctx.beat()
            ctx.state["reviewer_calls"] += 1
            if pas == 1:
                v = dr.review_doctrine(src, it["generated_text"], reviewer, require_quotes=True,
                                       split_sources=_split_doctrine_source)
            else:
                v = dr.review_distractor(src, it["question"], it["option_text"], it["teaching"], reviewer,
                                         split_sources=_split_doctrine_source)
        except rt.GateInfraError as e:
            rec["infra"] = True
            rec["issues"] = [_short(f"reviewer unavailable: {e}", 200)]
            infra_stop = _short(f"{type(e).__name__}: {e}", 300)
            continue
        except rt.GateConfigError as e:
            ctx.warnings.append(f"doctrine reviewer refused: {_short(e, 200)}")
            rec["issues"] = [_short(f"reviewer refused: {e}", 200)]
            content_failed = config_stop = True
            shown.append(f"{rec['id']}: reviewer refused")
            continue
        except Exception as e:  # noqa: BLE001 — unknown reviewer failure: content-class (strict direction)
            rec["issues"] = [_short(f"reviewer error: {type(e).__name__}: {e}", 200)]
            content_failed = True
            shown.append(f"{rec['id']}: {rec['issues'][0]}")
            continue
        rec["ok"] = v.ok is True
        rec["issues"] = [_short(x, 200) for x in list(v.issues or [])[:3]]
        bad_quotes = dr.unverified_quotes(src, v.quotes or [], split_sources=_split_doctrine_source)
        rec["quotes_ok"] = bool(v.quotes) and not bad_quotes
        quote_rule_failed = v.ok is not True and any(_safe(x).startswith("unverifiable source quote")
                                                     for x in v.issues or [])
        if quote_rule_failed and windowed and any(_GAP_MARK in _safe(q) for q in bad_quotes):
            # it failed because a quote crosses the GAP joiner: it spans text the reviewer never saw
            rec["issues"] = ["quote spans an omitted gap in the windowed source"]
        if rec["ok"]:
            ok[pas] += 1
        else:
            content_failed = True
            shown.append(f"{rec['id']}: {rec['issues'][0] if rec['issues'] else 'failed'}")

    parts = [f"{ok[1]}/{len(p1)} rounds, {ok[2]}/{len(p2)} distractors ok"]
    if has_mcq and not p2:
        content_failed = True
        parts.append("malformed mcq: no distractors found")
    elif not p2:
        parts.append("no distractors (produce-only game)")
    if skipped:
        parts.append(f"{skipped} review(s) skipped")
    if infra_stop:
        parts.append(f"stopped: {infra_stop}")
    parts += shown[:5]
    passed = not content_failed and not infra_stop and ok[1] == len(p1) and ok[2] == len(p2)
    if infra_stop and not content_failed:            # infra only if no content failure came first
        ctx.infra.setdefault("doctrine", infra_stop)
    return passed, "; ".join(parts)


def _g_retrieval(ctx):
    sc = ctx.g.retrieval_density.score_retrieval({"interactions": docketgen.interactions_from_game(ctx.final)})
    return sc["passes"] is True, f"density={sc['density']:.2f} gen_ratio={sc['generation_ratio']:.2f} n={sc['n']}"


def _g_self_contained(ctx):
    bundle = json.dumps(ctx.final, ensure_ascii=False) + "\n" + player_bundle_text(ctx.ehash)
    v = ctx.g.self_contained.check_self_contained(bundle)
    return v.ok is True, ("no external-AI calls at play-time" if v.ok else "; ".join(v.hits[:10]))


def _g_citations(ctx):
    u = ctx.unverified
    if not isinstance(u, list):
        return False, f"malformed citation check: no citation check result ({type(u).__name__})"
    bad = [i for i, x in enumerate(u) if not isinstance(x, (str, dict))]
    if bad:
        return False, f"malformed citation check: entry {bad[0]} is {type(u[bad[0]]).__name__}"
    if not u:
        return True, "every citation verified"
    return False, f"{len(u)} unverified citation(s): " + "; ".join(_short(x, 200) for x in u[:10])


def _g_reviewer_high(ctx):
    iss = ctx.issues
    if not isinstance(iss, list):
        return False, f"malformed reviewer issues: expected a list, got {type(iss).__name__}"
    for i, e in enumerate(iss):
        if not isinstance(e, dict):
            return False, f"malformed reviewer issues: entry {i} is {type(e).__name__}"
        if not isinstance(e.get("severity"), str) or e["severity"] not in ("high", "low"):
            return False, f"malformed reviewer issues: entry {i} severity {_short(e.get('severity'), 40)!r}"
    high = [e for e in iss if e["severity"] == "high"]
    if high:
        return False, (f"{len(high)} high-severity reviewer issue(s): "
                       + "; ".join(f"{_safe(e.get('where', ''))}: {_safe(e.get('problem', ''))}" for e in high))
    return True, f"no high-severity reviewer issues ({len(iss)} low)"


def _g_playability(ctx):
    ctx.beat()
    v = ctx.g.playability.check_playability(_rt(ctx.runtime, "page_probe"), list(ctx.required_selectors))
    return v.ok is True, ("plays clean" if v.ok else f"errors={v.errors[:5]} missing={v.missing_selectors[:10]}")


def _g_accessibility(ctx):
    ctx.beat()
    v = ctx.g.a11y.check_accessibility(_rt(ctx.runtime, "a11y_probe"))
    return v.ok is True, ("accessible" if v.ok else "; ".join(v.issues))


def _g_polish(ctx):
    vlm = _rt(ctx.runtime, "vlm") or ctx.g.runtime.m4_vlm()
    outage = []

    def watched(path):                                   # judge_aesthetics folds any vlm exception into ok=False;
        try:                                             # keep the outage so it reaches the card as infra
            return vlm(path)
        except ctx.g.runtime.GateInfraError as e:
            outage.append(e)
            raise

    ctx.beat()
    v = ctx.g.aesthetic_judge.judge_aesthetics(_safe(_rt(ctx.runtime, "screenshot")), watched)
    if outage:
        raise outage[0]
    return v.ok is True, f"polish score={v.score:.2f} ({_short(v.notes, 300)})"


_WIRED_BY = {"playability": "page_probe", "accessibility": "a11y_probe", "polish": "screenshot"}


# ------------------------------------------------------------------------------------------------ card helpers

def card_infra_error(card) -> bool:
    """True only if there is at least one enforced blocking failure and every one of them is infra-only
    (`bool(blocking) and` is load-bearing: all([]) is True). Never raises."""
    try:
        blocking = card.get("blocking_failures")
        if not isinstance(blocking, list) or not blocking:
            return False
        infra = {g.get("name") for g in card.get("gates") or []
                 if isinstance(g, dict) and isinstance(g.get("infra"), str) and g.get("infra")}
        return all(n in infra for n in blocking)
    except Exception:  # noqa: BLE001
        return False


def _card_bytes(card: dict) -> int:
    return len(json.dumps(card, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _cut_details(card: dict, n: int) -> bool:
    cut = False
    for g in card["gates"]:
        if len(g["detail"]) > n:
            g["detail"], cut = g["detail"][:n - 1] + "…", True
    return cut


def _cap_card(card: dict) -> dict:
    """Keep the card within CARD_MAX_BYTES (UTF-8 JSON). Never touches overall_pass, blocking_failures,
    infra_error or a gate's name/passed/mandatory."""
    trunc = _cut_details(card, DETAIL_MAX) or bool(card.get("truncated"))

    def over() -> bool:
        return _card_bytes(card) > CARD_MAX_BYTES

    for n in (500, 120):
        if over():
            trunc = _cut_details(card, n) or trunc
    if over():
        for it in card["doctrine_items"]:
            it["issues"] = [_short(s, 80) for s in it["issues"][:1]]
        trunc = True
    if over():
        items = card["doctrine_items"]
        failing = [it for it in items if not it.get("ok")]
        card["doctrine_items"] = failing
        if over():
            card["doctrine_items"] = failing[:20]
        card["doctrine_items_dropped"] = len(items) - len(card["doctrine_items"])
    if over():
        for g in card["gates"]:
            g["detail"] = "(truncated)"
        card["config_warning"] = _short(card["config_warning"], 300)
    if over():
        card["doctrine_items_dropped"] = card.get("doctrine_items_dropped", 0) + len(card["doctrine_items"])
        card["doctrine_items"] = []
    if over():
        raise ValueError(f"review card still over {CARD_MAX_BYTES} bytes after truncation")
    card["truncated"] = trunc
    return card


def _game_meta(final) -> dict:
    try:
        f = final if isinstance(final, dict) else {}
        return {"title": _short(f.get("title") or "", 300), "course": _short(f.get("course") or "", 200),
                "gid": _short(f.get("id") or "", 200)}
    except Exception:  # noqa: BLE001
        return {"title": "", "course": "", "gid": ""}


def _fallback_card(final, mode: str, err, warnings=()) -> dict:
    """The minimal schema-valid failing card for an adapter bug. Not infra: it spends the content quota."""
    try:
        detail = _short(f"adapter error (fail-closed): {type(err).__name__}: {_safe(err)}", 300)
        warning = _short("; ".join(_safe(w) for w in list(warnings) + [detail]), 300)
    except Exception:  # noqa: BLE001
        detail = warning = "adapter error (fail-closed)"
    return {"schema": CARD_SCHEMA, "game": _game_meta(final), "overall_pass": False,
            "gates": [{"name": "adapter", "passed": False, "mandatory": True, "designed_mandatory": True,
                       "detail": detail}],
            "blocking_failures": ["adapter"], "mode": mode, "infra_error": False, "enforced": [], "not_wired": [],
            "config_warning": warning, "lexicon_version": "", "lexicon_status": "", "engine_hash": "",
            "game_sha256": "", "reviewer_model": "", "reviewer_calls": 0, "heartbeat_errors": 0,
            "budget_exhausted": False, "timings_ms": {}, "doctrine_items": [], "texts_count": 0,
            "truncated": False}


# ------------------------------------------------------------------------------------------------ the entry point

def gate_docket(final: dict, keyed: dict, texts: list, course: dict, *,
                issues: list | None = None, unverified: list | None = None,
                mode: str = "shadow", heartbeat=None, runtime=None) -> dict:
    """Run every gate over a finished docket game and return the review card (schema "studio-card/1").

    Never raises (KeyboardInterrupt/SystemExit aside): an adapter bug returns a failing "adapter" card.
    `mode` is only recorded ("shadow" or "enforce"; anything else is recorded as "enforce" with a warning);
    the caller decides what a failing card does. `runtime` is a test seam (dict or object with reviewer, vlm,
    page_probe, a11y_probe, screenshot, required_selectors, clock); None in production."""
    card_mode = "shadow" if isinstance(mode, str) and mode == "shadow" else "enforce"
    warnings: list = []
    try:
        return _gate_docket(final, keyed, texts, course, issues, unverified, mode, card_mode, heartbeat,
                            runtime, warnings)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:  # noqa: BLE001 — the adapter must never take the writer down
        return _fallback_card(final, card_mode, e, warnings)


def _gate_docket(final, keyed, texts, course, issues, unverified, mode, card_mode, heartbeat, runtime,
                 warnings) -> dict:
    t_start = time.monotonic()
    if not (isinstance(mode, str) and mode in ("shadow", "enforce")):
        warnings.append(f"unknown gate mode {_short(repr(mode), 40)}; treated as enforce")
    g = _gates()
    state = {"reviewer_calls": 0, "heartbeat_errors": 0, "budget_exhausted": False, "reviewer_model": ""}

    def beat():
        if heartbeat is None:
            return
        try:
            heartbeat()
        except Exception:  # noqa: BLE001 — a DB blip must never fail a gate
            state["heartbeat_errors"] += 1

    beat()
    try:
        game_sha = hashlib.sha256(json.dumps(final, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
    except Exception as e:  # noqa: BLE001
        game_sha = ""
        warnings.append(f"game not hashable as JSON: {_short(e, 120)}")
    final_c = copy.deepcopy(final)                       # inputs are never mutated
    try:
        keyed_c = dict(keyed)                            # read only; a shallow copy (row wrappers may refuse deepcopy)
    except Exception:  # noqa: BLE001
        keyed_c = {}
        warnings.append(f"source keys unreadable ({type(keyed).__name__}); gating against no sources")
    try:
        ehash = engine_hash()
    except Exception as e:  # noqa: BLE001
        ehash = ""
        warnings.append(f"engine hash unavailable: {_short(e, 120)}")

    code = lexicon_code(course, warnings)
    lexicon, lexicon_version, lexicon_status, lexicon_error = None, "", "", None
    try:
        lexicon, lexicon_version = g.terminology_lock.load_lexicon(code)
        if lexicon_version == "fallback":
            warnings.append(f"no course lexicon for slug {_short(code, 60)!r}; using fallback")
        else:
            lexicon_status = _lexicon_status(code, g.terminology_lock)
    except Exception as e:  # noqa: BLE001 — a broken lexicon blocks (terminology fails), never passes
        lexicon_error = e
        warnings.append(f"course lexicon {_short(code, 60)!r} unusable: {_short(e, 160)}")

    wired = {n for n in GATE_ORDER if n not in _WIRED_BY or _rt(runtime, _WIRED_BY[n])}
    not_wired = [n for n in GATE_ORDER if n not in wired]
    enforced = enforce_set(os.environ.get("CF_STUDIO_ENFORCE_GATES", ""), wired, warnings)
    try:
        texts_count = len(texts) if isinstance(texts, (list, tuple)) else 0
    except Exception:  # noqa: BLE001
        texts_count = 0

    ctx = SimpleNamespace(
        g=g, final=final_c, keyed=keyed_c, issues=issues, unverified=unverified, runtime=runtime,
        beat=beat, warnings=warnings, state=state, infra={}, doctrine_items=[], ehash=ehash,
        lexicon=lexicon, lexicon_version=lexicon_version, lexicon_error=lexicon_error,
        clock=_rt(runtime, "clock") or time.monotonic,
        budget_s=_env_positive("CF_STUDIO_DOCTRINE_BUDGET_S", DOCTRINE_BUDGET_S, float, warnings),
        doctrine_cap=_env_positive("CF_STUDIO_DOCTRINE_SOURCE_CAP", DOCTRINE_SOURCE_CAP, int, warnings),
        required_selectors=_rt(runtime, "required_selectors") or DEFAULT_REQUIRED_SELECTORS,
    )

    results, timings = [], {}
    for name in GATE_ORDER:
        designed = name not in ADVISORY_GATES
        if name in wired:
            body = (lambda f: (lambda: f(ctx)))(globals()[f"_g_{name}"])
        else:
            body = (lambda d: (lambda: (False, d)))(NOT_WIRED_DETAIL[name])

        def fn(body=body, name=name):
            try:
                return body()
            except g.runtime.GateInfraError as e:
                ctx.infra.setdefault(name, _short(f"{type(e).__name__}: {e}", 300))
                raise                                    # run_gate still fails the gate

        t0 = time.monotonic()
        gate = g.harness.run_gate(name, designed and name in enforced, fn)
        timings[name] = int((time.monotonic() - t0) * 1000)
        gate["designed_mandatory"] = designed
        if name not in wired:
            gate["not_wired"] = True
        if not gate["passed"] and name in ctx.infra:
            gate["infra"] = ctx.infra[name]
        results.append(gate)

    seen, uniq = set(), []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    timings["total"] = int((time.monotonic() - t_start) * 1000)
    card = g.harness.build_card(_game_meta(final), results, {
        "schema": CARD_SCHEMA, "mode": card_mode, "infra_error": False, "enforced": enforced,
        "not_wired": not_wired, "config_warning": _short("; ".join(uniq), DETAIL_MAX),
        "lexicon_version": _short(lexicon_version, 120), "lexicon_status": lexicon_status, "engine_hash": ehash,
        "game_sha256": game_sha, "reviewer_model": state["reviewer_model"],
        "reviewer_calls": state["reviewer_calls"], "heartbeat_errors": state["heartbeat_errors"],
        "budget_exhausted": state["budget_exhausted"], "timings_ms": timings,
        "doctrine_items": ctx.doctrine_items, "texts_count": texts_count, "truncated": False,
    })
    card["infra_error"] = card_infra_error(card)
    card = _cap_card(card)
    # _set_docket serialises `review` outside R3's try: prove it serialises (and is plain JSON) here.
    return json.loads(json.dumps(card, ensure_ascii=False, allow_nan=False))


def block_message(card) -> str:
    """The error text for a draft the gates blocked: starts with docketgen.GATE_UNAVAILABLE when every enforced
    blocking failure is an outage, else docketgen.GATE_BLOCKED (S8 counts both). Accepts anything; never
    raises; at most 300 chars."""
    try:
        if not isinstance(card, dict):
            return f"{docketgen.GATE_BLOCKED}: unreadable gate card"
        blocking = card.get("blocking_failures")
        if not isinstance(blocking, list):
            return f"{docketgen.GATE_BLOCKED}: malformed blocking failures"
        names = [_short(n, 80) for n in blocking]
        if card.get("infra_error") is True and names:
            reasons = {}
            for gt in card.get("gates") if isinstance(card.get("gates"), list) else []:
                if isinstance(gt, dict) and isinstance(gt.get("infra"), str):
                    reasons.setdefault(_safe(gt.get("name")), gt["infra"])
            msg = f"{docketgen.GATE_UNAVAILABLE}: " + "; ".join(
                f"{n}: {_short(reasons.get(n, 'unavailable'), 200)}" for n in names)
        elif names:
            msg = f"{docketgen.GATE_BLOCKED}: " + ", ".join(names)
        else:
            msg = f"{docketgen.GATE_BLOCKED}: no enforced gate passed"
        return _short(msg, 300)
    except Exception:  # noqa: BLE001
        return f"{docketgen.GATE_BLOCKED}: unreadable gate card"
