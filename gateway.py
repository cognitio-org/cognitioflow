"""The gateway lane: a few named bulk jobs on a cheap model, privacy-first, falling back to Anthropic.

The tutor never comes here. Only the tasks in CF_GATEWAY_TASKS do (flashcards, concept extraction and
cards, syllabus reading, viva questions): each sends one note or one file's text and gets a JSON list
back. The chat, "notes" mode included, stays on Anthropic, because it carries whole conversations and
every ticked file.

How each GDPR principle is met here (details and open items in docs/privacy-gateway.md):
- Purpose limitation, Art. 5(1)(b): a closed allow-list of tasks; anything else is refused.
- Data minimisation, Art. 5(1)(c): only the text the task needs is sent, with e-mail addresses, phone
  numbers, IBANs and student numbers replaced by placeholders first (pseudonymisation, Art. 4(5)).
- Storage limitation, Art. 5(1)(e): every request asks the gateway not to log it ("no-log").
- Integrity and confidentiality, Art. 5(1)(f) and Art. 32: TLS only; the key lives in Secret Manager.
- Privacy by design and by default, Art. 25: off unless the key AND a spend ceiling are configured;
  CF_GATEWAY=off switches it off without a deploy; any failure falls back to Anthropic.
- Accountability, Art. 5(2): every call is labelled with its provider and model in the usage record.
"""
import logging
import os
import re

log = logging.getLogger("cognitioflow.gateway")

DEFAULT_BASE = "https://litellm.augment-code.support"
DEFAULT_MODEL = "gpt-6-luna"
DEFAULT_TASKS = "cards,concepts,syllabus,oral"
KEY_NAME = "LITELLM_API_KEY"

#: Personal data a study note can carry that no flashcard needs. Replaced, never sent.
_REDACT = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"), "[iban]"),
    (re.compile(r"\b[sSpP]\d{7}\b"), "[student number]"),
]

_tripped = False   # set once the key's spend passes the ceiling; this process then stays on Anthropic


def _tasks() -> set:
    return {t.strip() for t in os.environ.get("CF_GATEWAY_TASKS", DEFAULT_TASKS).split(",") if t.strip()}


def _ceiling():
    try:
        return float(os.environ["CF_GATEWAY_SPEND_CEILING"])
    except (KeyError, ValueError):
        return None


def enabled() -> bool:
    """On only when switched on, keyed, and capped. Without a ceiling there is no way to keep the
    shared key under its monthly budget, so the lane stays off rather than guess."""
    return (os.environ.get("CF_GATEWAY", "on").lower() != "off" and bool(os.environ.get(KEY_NAME))
            and _ceiling() is not None and not _tripped)


def allows(task) -> bool:
    return bool(task) and task in _tasks() and enabled()


#: A phone number: digits with spaces, hyphens or brackets, 9+ digits in all. Dots and slashes never
#: join it, so dates (30.8.2007), case numbers (C-62/88, 44302/02) and citations stay intact.
_PHONE = re.compile(r"(?<![\w./-])\+?\d[\d ()-]{7,}\d(?![\w/-]|\.\d)")


def _phone(m):
    return "[phone]" if sum(ch.isdigit() for ch in m.group(0)) >= 9 else m.group(0)


def minimise(text: str) -> str:
    for pat, placeholder in _REDACT:
        text = pat.sub(placeholder, text)
    return _PHONE.sub(_phone, text)


def _minimise_messages(messages):
    out = []
    for msg in messages:
        c = msg.get("content")
        if isinstance(c, str):
            msg = {**msg, "content": minimise(c)}
        elif isinstance(c, list):
            msg = {**msg, "content": [{**b, "text": minimise(b["text"])} if b.get("type") == "text" else b for b in c]}
        out.append(msg)
    return out


def call(task, **kw):
    """One gateway call for an allowed task, or None to tell the caller to use Anthropic."""
    global _tripped
    if not allows(task):
        return None
    import anthropic
    try:
        client = anthropic.Anthropic(base_url=os.environ.get("CF_GATEWAY_BASE", DEFAULT_BASE), auth_token=os.environ[KEY_NAME], max_retries=1, timeout=120)
        kw = {**kw, "messages": _minimise_messages(kw.get("messages", []))}
        raw = client.messages.with_raw_response.create(model=os.environ.get("CF_GATEWAY_MODEL", DEFAULT_MODEL), extra_body={"no-log": True}, **kw)
        m = raw.parse()
    except Exception as e:   # any gateway trouble: the job still gets done, on Anthropic
        log.warning("gateway %s failed (%s); falling back to Anthropic", task, type(e).__name__)
        return None
    try:
        m.usage.cost = float(raw.headers.get("x-litellm-response-cost") or 0) or None
        m.usage.provider = "gateway"
    except Exception:
        pass
    spend = raw.headers.get("x-litellm-key-spend")
    if spend and _ceiling() is not None and float(spend) >= _ceiling():
        _tripped = True
        log.warning("gateway key spend %.2f reached the ceiling %.2f; staying on Anthropic", float(spend), _ceiling())
    return m
