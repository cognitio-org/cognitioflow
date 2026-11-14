def classify_interaction(interaction: dict) -> str:
    """Classify an interaction as generation or recognition."""
    options = interaction.get("options")
    if isinstance(options, list) and len(options) >= 2:
        return "recognition"
    return "generation"


def is_retrieval(interaction: dict) -> bool:
    """Return False only for passive reading with no answer or options."""
    return bool(interaction.get("answer") or interaction.get("options"))


def score_retrieval(
    game_spec: dict,
    density_floor: float = 0.5,
    generation_floor: float = 0.4,
) -> dict:
    """Score retrieval density and the share of retrieval items requiring generation."""
    interactions = game_spec.get("interactions", [])
    n = len(interactions)
    n_retrieval = sum(1 for interaction in interactions if is_retrieval(interaction))
    density = n_retrieval / n if n else 0.0

    generation_count = sum(
        1
        for interaction in interactions
        if is_retrieval(interaction)
        and classify_interaction(interaction) == "generation"
    )
    generation_ratio = generation_count / n_retrieval if n_retrieval else 0.0

    return {
        "density": density,
        "generation_ratio": generation_ratio,
        "n": n,
        "n_retrieval": n_retrieval,
        "passes": density >= density_floor
        and generation_ratio >= generation_floor,
    }
