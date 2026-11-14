def overall_verdict(gate_results: list[dict]) -> bool:
    """Return True only if every mandatory gate has passed."""
    return all(
        gate["passed"]
        for gate in gate_results
        if gate["mandatory"]
    )


def build_review_card(game_meta: dict, gate_results: list[dict]) -> dict:
    """Build a review card from game metadata and gate results."""
    blocking_failures = [
        gate["name"]
        for gate in gate_results
        if gate["mandatory"] and not gate["passed"]
    ]
    return {
        "game": game_meta,
        "overall_pass": overall_verdict(gate_results),
        "gates": gate_results,
        "blocking_failures": blocking_failures,
    }


def render_markdown(card: dict) -> str:
    """Render a human-readable Markdown review card."""
    game_title = card["game"]["title"]
    overall_status = "✅" if card["overall_pass"] else "❌"
    lines = [f"# Review Card: {game_title} {overall_status}"]
    lines.extend([
        "",
        "| Gate | Status | Mandatory | Detail |",
        "|------|--------|-----------|--------|",
    ])

    for gate in card["gates"]:
        status = "PASS" if gate["passed"] else "FAIL"
        mandatory = "Yes" if gate["mandatory"] else "No"
        lines.append(
            f"| {gate['name']} | {status} | {mandatory} | {gate['detail']} |"
        )

    if card["blocking_failures"]:
        lines.extend(["", "Blocking failures:"])
        lines.extend(f"- {failure}" for failure in card["blocking_failures"])

    return "\n".join(lines)
