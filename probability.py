from __future__ import annotations
from dataclasses import dataclass
from statistics import median

def implied_prob_american(odds: int) -> float:
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return (-odds) / ((-odds) + 100.0)

def profit_per_1(odds: int) -> float:
    # profit excluding stake, per $1
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

def consensus_probability(odds_list: list[int]) -> float | None:
    """
    Convert multiple books' odds into a robust consensus probability.
    Uses median implied probability (simple + stable).
    """
    vals = []
    for o in odds_list:
        if isinstance(o, int):
            vals.append(implied_prob_american(o))
    if not vals:
        return None
    return float(median(vals))
