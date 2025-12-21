from dataclasses import dataclass
from typing import List

@dataclass
class GateResult:
    ok: bool
    reasons: List[str]

def quality_gates(candidate: dict, strict_mode: bool, nhl_require_goalie: bool) -> GateResult:
    reasons: List[str] = []

    needed = ["sport", "event", "market", "player", "side", "target_odds", "p_model", "books_count"]
    missing = [k for k in needed if candidate.get(k) is None]
    if missing:
        reasons.append(f"Missing fields: {', '.join(missing)}")

    if not isinstance(candidate.get("target_odds"), int):
        reasons.append("Target book odds missing/invalid")

    p = candidate.get("p_model")
    if not isinstance(p, float) or not (0.01 <= p <= 0.99):
        reasons.append("Model probability invalid")

    if nhl_require_goalie and candidate.get("sport") == "icehockey_nhl":
        if candidate.get("goalie_confirmed") is not True:
            reasons.append("Goalie not confirmed (gate enabled)")

    if strict_mode:
        return GateResult(ok=(len(reasons) == 0), reasons=reasons)

    hard_blocks = [r for r in reasons if "Target book odds" in r or "Model probability" in r]
    return GateResult(ok=(len(hard_blocks) == 0), reasons=reasons)
