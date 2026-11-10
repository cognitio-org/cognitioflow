import re
from dataclasses import dataclass


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
        if re.search(protected_pattern, generated_text, re.IGNORECASE):
            continue

        for synonym in synonyms:
            synonym_pattern = rf"\b{re.escape(synonym)}\b"
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
