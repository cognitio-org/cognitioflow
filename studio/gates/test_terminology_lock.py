import json
import tempfile
from pathlib import Path

from terminology_lock import PROTECTED_SYNONYMS, check_terminology, load_lexicon, passes


def run_tests():
    source = "The contract is void."

    violations = check_terminology(source, "The contract is voidable.")
    assert len(violations) == 1
    assert violations[0].protected_term == "void"
    assert violations[0].found_synonym == "voidable"
    assert not passes(source, "The contract is voidable.")

    assert check_terminology(source, "The contract is void.") == []
    assert passes(source, "The contract is void.")

    # Suppression hole (Gemini G7): the protected term appearing elsewhere in the
    # item no longer silences a synonym that the source never used.
    v = check_terminology(source, "The contract is void, though another clause is voidable.")
    assert [x.found_synonym for x in v] == ["voidable"]
    assert not passes(source, "The contract is void, though another clause is voidable.")

    # A synonym the source itself uses is not a violation.
    both = "The contract is void; the other clause is voidable."
    assert check_terminology(both, "The contract is void and the clause voidable.") == []

    # Design-doc acceptance: duty/obligation shape with the term also present.
    custom = {"shall": ["may"]}
    assert check_terminology("The party shall pay.", "The party shall pay and may refuse.", custom)
    assert check_terminology("The party shall pay.", "The party shall pay.", custom) == []

    assert check_terminology("", "") == []
    assert passes("", "")

    # Lexicon loader
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        lex, ver = load_lexicon("pil", base)
        assert ver == "fallback" and lex == PROTECTED_SYNONYMS
        (base / "pil.json").write_text(json.dumps({"version": "v1", "terms": {"treaty": ["agreement"]}}))
        lex, ver = load_lexicon("pil", base)
        assert ver == "v1" and lex == {"treaty": ["agreement"]}
        for bad in ["{not json", "[]", json.dumps({"terms": {"a": ["b"]}}),
                    json.dumps({"version": "v", "terms": {}}),
                    json.dumps({"version": "v", "terms": {"a": []}}),
                    json.dumps({"version": "v", "terms": {"a": [""]}})]:
            (base / "pil.json").write_text(bad)
            try:
                load_lexicon("pil", base)
            except ValueError:
                pass
            else:
                raise AssertionError(f"malformed lexicon accepted: {bad!r}")
        for code in ["../etc", "PIL", "", "a/b"]:
            try:
                load_lexicon(code, base)
            except ValueError:
                pass
            else:
                raise AssertionError(f"bad course code accepted: {code!r}")

    # The shipped PIL seed loads.
    lex, ver = load_lexicon("pil")
    assert ver == "pil-draft-1" and "treaty" in lex

    print("OK")


if __name__ == "__main__":
    run_tests()
