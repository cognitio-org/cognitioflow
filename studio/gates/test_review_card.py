from review_card import build_review_card, render_markdown


def main():
    game_meta = {"title": "Test Quest"}

    passing_gates = [
        {
            "name": "content",
            "passed": True,
            "mandatory": True,
            "detail": "Content checks passed",
        },
        {
            "name": "balance",
            "passed": True,
            "mandatory": True,
            "detail": "Balance checks passed",
        },
    ]
    passing_card = build_review_card(game_meta, passing_gates)
    assert passing_card["overall_pass"] is True
    assert passing_card["blocking_failures"] == []

    failed_gates = [
        {
            "name": "content",
            "passed": True,
            "mandatory": True,
            "detail": "Content checks passed",
        },
        {
            "name": "balance",
            "passed": False,
            "mandatory": True,
            "detail": "Balance checks failed",
        },
    ]
    failed_card = build_review_card(game_meta, failed_gates)
    assert failed_card["overall_pass"] is False
    assert failed_card["blocking_failures"] == ["balance"]

    advisory_gates = [
        {
            "name": "content",
            "passed": True,
            "mandatory": True,
            "detail": "Content checks passed",
        },
        {
            "name": "style",
            "passed": False,
            "mandatory": False,
            "detail": "Style is advisory",
        },
    ]
    advisory_card = build_review_card(game_meta, advisory_gates)
    assert advisory_card["overall_pass"] is True

    markdown = render_markdown(failed_card)
    assert "Test Quest" in markdown
    assert "❌" in markdown
    for gate in failed_gates:
        assert gate["name"] in markdown

    print("OK")


if __name__ == "__main__":
    main()
