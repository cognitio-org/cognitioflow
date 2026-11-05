"""Tag each card to the examined blueprint topic it drills, so exam-readiness counts the right cards
per doctrine instead of guessing by substring.

Pure: it builds the classify prompt and parses the model's reply into {card_id: topic_key}. No network,
no database, no run.py import. The model answers with *topic numbers*, never free text, so a topic the
model invents is structurally impossible — an out-of-range number is simply dropped and that card stays
untagged. A card the model cannot place stays untagged too; readiness falls back to text match for it.
"""
from __future__ import annotations

RULES = (
    "You label law revision flashcards by which examined topic each one drills. "
    "You are given a numbered list of topics and a numbered list of cards. "
    "For each card, reply with the number of the single topic it most directly drills, or 0 if it fits "
    "none of them. Judge by legal substance — the doctrine, rule or authority the card tests — not by "
    "shared words. Return ONLY a JSON object mapping each card number (as a string) to a topic number, "
    'e.g. {"1": 2, "2": 0, "3": 1}. No prose, no extra keys.'
)

# Keep each card line bounded so a big deck can't blow the context on one over-long card.
_CARD_CHARS = 360


def valid_topics(topics):
    """The blueprint topics that can be tagged against — dicts with a non-empty 'topic', in order.

    build_prompt and parse_tags both go through this, so the numbering the model sees and the numbering
    we decode are the same list.
    """
    return [t for t in (topics or []) if isinstance(t, dict) and str(t.get("topic") or "").strip()]


def topic_keys(topics):
    """The ordered topic keys — what gets stored in cards.doctrine."""
    return [str(t["topic"]).strip() for t in valid_topics(topics)]


def batches(cards, size=30):
    """Split the cards into model-sized groups (one call each)."""
    size = max(1, int(size))
    return [cards[i:i + size] for i in range(0, len(cards), size)]


def _card_text(c):
    front = str((c or {}).get("front") or "").strip()
    back = str((c or {}).get("back") or "").strip()
    one = (front + "  //  " + back).strip(" /") if back else front
    one = " ".join(one.split())
    return one[:_CARD_CHARS]


def build_prompt(topics, cards):
    """One user message: the numbered topics (with their doctrines as hints) and the numbered cards."""
    vts = valid_topics(topics)
    tlines = []
    for i, t in enumerate(vts, 1):
        doctrines = ", ".join(str(d).strip() for d in (t.get("doctrines") or []) if str(d).strip())[:200]
        tlines.append(f"{i}. {str(t['topic']).strip()}" + (f" — {doctrines}" if doctrines else ""))
    clines = [f"[{j}] {_card_text(c)}" for j, c in enumerate(cards, 1)]
    return (
        "TOPICS (reply with one of these numbers, or 0 for none):\n"
        + "\n".join(tlines)
        + "\n\nCARDS:\n"
        + "\n".join(clines)
    )


def _as_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_tags(reply, cards, keys):
    """Decode the model reply into {card_id: topic_key}.

    Only a topic number in 1..len(keys) tags a card; 0, out-of-range, missing or unparseable leaves the
    card untagged (absent from the result). Tolerates the two shapes a model drifts to: the asked-for
    {card_no: topic_no} object, or a list of {"card": n, "topic": m} objects.
    """
    n_topics = len(keys)
    if not n_topics or not cards:
        return {}

    pairs = {}  # card_no (int) -> topic_no (int)
    if isinstance(reply, dict):
        for k, v in reply.items():
            cn, tn = _as_int(k), _as_int(v)
            if cn is not None and tn is not None:
                pairs[cn] = tn
    elif isinstance(reply, list):
        for item in reply:
            if isinstance(item, dict):
                cn = _as_int(item.get("card", item.get("id")))
                tn = _as_int(item.get("topic", item.get("t")))
                if cn is not None and tn is not None:
                    pairs[cn] = tn

    out = {}
    for j, c in enumerate(cards, 1):
        tn = pairs.get(j)
        cid = (c or {}).get("id")
        if cid and tn is not None and 1 <= tn <= n_topics:
            out[cid] = keys[tn - 1]
    return out


def stale_tags(used_doctrines, keys):
    """Doctrines in use that are no longer examined topics — e.g. after the blueprint was re-extracted
    with different topic names. These cards still read as untagged in readiness; this just counts them
    so the user knows a re-tag is worthwhile."""
    live = set(keys)
    return sorted({str(d).strip() for d in used_doctrines if str(d).strip() and str(d).strip() not in live})
