"""Virtual E.164 destinations used only by configured SIP forwarding tests."""
import random

COUNTRY_POOLS = {
    "cote_ivoire_mtn": "+22505",
    "cote_ivoire_orange": "+22507",
    "cote_ivoire_moov": "+22501",
    "guinee": "+224",
}


def generate_destination(pool: str, rng: random.Random | None = None) -> str:
    """Generate one test destination with the national length configured by the owner."""
    if pool not in COUNTRY_POOLS:
        raise ValueError(f"Unknown virtual destination pool: {pool}")
    random_source = rng or random.SystemRandom()
    prefix = COUNTRY_POOLS[pool]
    # Côte d'Ivoire has ten national digits after 225; Guinea has nine after 224.
    remaining = 8 if pool.startswith("cote_ivoire_") else 9
    return prefix + "".join(str(random_source.randrange(10)) for _ in range(remaining))


def generate_weighted_destinations(pools: list[dict], count: int, rng: random.Random | None = None) -> list[str]:
    """Generate a per-call destination list from UI pool weights (must total 100)."""
    if count < 1:
        return []
    weights = [int(item.get("weight", 0)) for item in pools]
    if not pools or any(weight < 0 for weight in weights) or sum(weights) != 100:
        raise ValueError("Virtual destination weights must total 100")
    random_source = rng or random.SystemRandom()
    return [generate_destination(random_source.choices([item["pool"] for item in pools], weights=weights, k=1)[0], random_source)
            for _ in range(count)]
