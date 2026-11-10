import json
import re
from dataclasses import dataclass
from pathlib import Path


PROTECTED_SYNONYMS: dict[str, list[str]] = {
    "void": ["voidable", "invalid", "unenforceable"],
    "intent": ["motive", "purpose"],
    "liable": ["responsible", "at fault"],
    "jurisdiction": ["venue"],
    "negligence": ["carelessness"],
    "offer": ["invitation to treat"],
    "duty": ["obligation"],
    "breach": ["violation"],
    "damages": ["compensation", "fine"],
    "mens rea": ["intent"],
    "actus reus": ["act"],
    "voidable": ["void"],
}


@dataclass
class Violation:
    protected_term: str
    found_synonym: str
    context: str


def check_terminology(
    source_text: str,
    generated_text: str,
    lexicon: dict[str, list[str]] | None = None,
) -> list[Violation]:
    if lexicon is None:
        lexicon = PROTECTED_SYNONYMS

    violations = []
    for protected_term, synonyms in lexicon.items():
        protected_pattern = rf"\b{re.escape(protected_term)}\b"
        if not re.search(protected_pattern, source_text, re.IGNORECASE):
            continue

        for synonym in synonyms:
            synonym_pattern = rf"\b{re.escape(synonym)}\b"
            if re.search(synonym_pattern, source_text, re.IGNORECASE):
                continue
            for match in re.finditer(synonym_pattern, generated_text, re.IGNORECASE):
                start = max(0, match.start() - 30)
                end = min(len(generated_text), match.end() + 30)
                violations.append(
                    Violation(
                        protected_term=protected_term,
                        found_synonym=synonym,
                        context=generated_text[start:end],
                    )
                )

    return violations


def passes(
    source_text: str,
    generated_text: str,
    lexicon: dict[str, list[str]] | None = None,
) -> bool:
    return not check_terminology(source_text, generated_text, lexicon)


LEXICON_DIR = Path(__file__).resolve().parent.parent / "lexicons"


def load_lexicon(
    course_code: str, base_dir: Path | None = None
) -> tuple[dict[str, list[str]], str]:
    """Return (lexicon, lexicon_version) for a course.

    Missing file -> (PROTECTED_SYNONYMS, "fallback"). A present but malformed
    file raises ValueError (fail-closed): a broken lexicon must never silently
    pass every draft.
    """
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", course_code or ""):
        raise ValueError(f"bad course code: {course_code!r}")
    path = (base_dir or LEXICON_DIR) / f"{course_code}.json"
    if not path.exists():
        return dict(PROTECTED_SYNONYMS), "fallback"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"lexicon {path.name} unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"lexicon {path.name}: top level must be an object")
    version = data.get("version")
    terms = data.get("terms")
    if not isinstance(version, str) or not version:
        raise ValueError(f"lexicon {path.name}: missing version")
    if not isinstance(terms, dict) or not terms:
        raise ValueError(f"lexicon {path.name}: terms must be a non-empty object")
    for term, syns in terms.items():
        if not isinstance(term, str) or not term.strip():
            raise ValueError(f"lexicon {path.name}: empty term")
        if (
            not isinstance(syns, list)
            or not syns
            or not all(isinstance(s, str) and s.strip() for s in syns)
        ):
            raise ValueError(f"lexicon {path.name}: term {term!r} needs >=1 synonym")
    return {t: list(s) for t, s in terms.items()}, version
