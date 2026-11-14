"""Guard the public landing page against overclaims that the code does not back up."""
from pathlib import Path

LANDING = (Path(__file__).resolve().parent.parent / "static" / "landing.html").read_text(encoding="utf-8")

REMOVED_OVERCLAIMS = [
    "never guesses",
    "Privacy-first",
    "IRAC throughout",
    "verified against your files",
    "Speech uses Google Cloud in the EU",
    "stays inside your syllabus",
    "getting harder exactly",
]


def test_removed_overclaims_absent():
    present = [p for p in REMOVED_OVERCLAIMS if p.lower() in LANDING.lower()]
    assert not present, f"overclaims back on the landing page: {present}"


def test_not_affiliated_line_present():
    assert "not affiliated with or endorsed by the University of Groningen" in LANDING


def test_citation_check_scope_stated():
    assert "Cases cited by name only, and national-law citations, are not checked." in LANDING
    assert "found in your selected sources" not in LANDING


# ---- wave 5 (frozen definition of 8, landing) -------------------------------------------------
import html as _html
import re as _re

ROOT = Path(__file__).resolve().parent.parent
PRIVACY = (ROOT / "static" / "privacy.html").read_text(encoding="utf-8")
APP_INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
PACK_HTML = (ROOT / "static" / "pack.html").read_text(encoding="utf-8")
AI_LABEL = "AI-generated. Verify every case, article and year against your own materials."
MORE_OVERCLAIMS = [
    "3D courtroom", "walkable 3D", "Every claim is tagged", "found in your selected sources",
    "how exams are marked", "reasons from your files only",
]


def _visible(src: str) -> str:
    src = _re.sub(r"(?s)<(script|style).*?</\1>", " ", src)
    return _re.sub(r"\s+", " ", _html.unescape(_re.sub(r"<[^>]+>", " ", src)))


def test_more_overclaims_absent():
    present = [p for p in MORE_OVERCLAIMS if p.lower() in LANDING.lower()]
    assert not present, present


def test_identity_line_in_ident_about_and_footer():
    line = "not affiliated with or endorsed by the University of Groningen"
    assert _visible(LANDING).count(line) >= 3
    assert "Made by an LLB student at the University of Groningen" in _visible(LANDING)


def test_article_precision_copy():
    assert "Article numbers are matched without the treaty or act name." in _visible(LANDING)


def test_hero_mock_uses_the_app_warning_string():
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "'Not in your materials: '" in app_js and "' — check before you rely on it.'" in app_js
    assert "Not in your materials: C-999/97 &mdash; check before you rely on it." in LANDING
    assert "verified" not in _visible(LANDING).lower().replace("unverified", "")


def test_no_third_party_requests_or_storage():
    assert not _re.search(r"""(src|href)=["']https?://(?!cognitioflow\.ai|autoriteitpersoonsgegevens)""", LANDING)
    assert "fonts.googleapis" not in LANDING and "localStorage" not in LANDING and "document.cookie" not in LANDING


def test_ai_label_same_string_everywhere():
    assert AI_LABEL in _visible(LANDING)
    assert AI_LABEL in APP_INDEX and APP_INDEX.count("data-ai-label") >= 2
    assert AI_LABEL in PACK_HTML


def test_data_section_is_a_table_with_a_topic_heading():
    assert "<h2>Where your data goes</h2>" in LANDING and "Plainly, today" not in LANDING
    for col in ("What", "Who processes it", "Where", "How long"):
        assert f">{col}</th>" in LANDING
    assert "OpenRouter" not in LANDING


def test_train_claims_name_providers():
    t = _visible(LANDING)
    for m in _re.finditer(r"[^.]*\btrain\b[^.]*\.", t):
        assert all(n in m.group(0) for n in ("Anthropic", "OpenAI", "Google")), m.group(0)
    assert "stays in the EU" not in t


def test_grounding_claims_carry_the_tick_condition():
    t = _visible(LANDING)
    for m in _re.finditer(r"[^.]*(grounded in|excerpts|show their sources|shows the excerpts)[^.]*\.", t):
        assert "tick" in m.group(0).lower(), m.group(0)


def test_no_paragraph_over_80_words():
    for m in _re.finditer(r"(?s)<p[ >].*?</p>", LANDING):
        assert len(_visible(m.group(0)).split()) <= 80, _visible(m.group(0))[:80]


def test_method_steps_match_code():
    import essay
    assert [l for _, l in essay.LIMBS] == ["Applicability", "Restriction or scope", "Justification and proportionality"]
    t = _visible(LANDING)
    assert "three steps" in t and "Conclusion" not in t and "Print packs list the same three steps" in t


def test_privacy_notice_has_art13_items_and_links():
    assert "/static/privacy.html" in LANDING
    p = _visible(PRIVACY)
    for needle in ("controller", "matej@mgms.eu", "Art. 6(1)(b)", "Anthropic", "OpenAI", "Google Vertex", "router",
                   "europe-west4", "Transfers outside the EEA", "How long it is kept", "Autoriteit Persoonsgegevens",
                   "right to complain", "cf_session", "Neon"):
        assert needle in p, needle


def test_no_openrouter_clause_while_gateway_off():
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "CF_GATEWAY=off" in deploy and "OpenRouter" not in LANDING and "free-tier" not in LANDING


def test_all_content_visible_without_scripts():
    assert ".rise" not in LANDING and "IntersectionObserver" not in LANDING
