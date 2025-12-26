from statistics import median

def implied_prob_american(odds: int) -> float:
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return (-odds) / ((-odds) + 100.0)

def profit_per_1(odds: int) -> float:
    if odds > 0:
        return odds / 100.0
    return 100.0 / (-odds)

def expected_value(p: float, odds: int) -> float:
    prof = profit_per_1(odds)
    return p * prof - (1 - p) * 1.0

def kelly_fraction(p: float, odds: int) -> float:
    b = profit_per_1(odds)
    q = 1 - p
    f = (b * p - q) / b
    return max(0.0, f)

def consensus_probability_from_probs(probs: list[float]) -> float | None:
    vals = [p for p in probs if isinstance(p, float) and 0.001 < p < 0.999]
    if not vals:
        return None
    return float(median(vals))

def fair_prob_two_way_no_vig(p_a: float, p_b: float) -> float:
    """
    Remove vig by normalizing the two implied probabilities so they sum to 1.
    Returns fair probability for outcome A.
    """
    s = p_a + p_b
    if s <= 0:
        return p_a
    return p_a / s
