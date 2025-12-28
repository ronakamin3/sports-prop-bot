from typing import List, Dict, Optional
from probability import parlay_ev, parlay_decimal_odds

def score_pick(p: Dict) -> float:
    ev = p.get("ev")
    books = p.get("books_count", 0)
    odds = p.get("target_odds")

    if not isinstance(ev, float) or not isinstance(books, int):
        return -999.0

    # EV dominates; books boosts confidence; small bonus for plus money
    score = ev * 100.0 + min(books, 10) * 0.5
    if isinstance(odds, int) and odds > 0:
        score += 0.2
    return score

def select_top(picks: List[Dict], n: int) -> List[Dict]:
    return sorted(picks, key=score_pick, reverse=True)[:n]

def _parlay_package(legs: List[Dict]) -> Dict:
    odds_list = [leg["target_odds"] for leg in legs]
    p_list = [leg["p_model"] for leg in legs]
    dec = parlay_decimal_odds(odds_list)
    ev = parlay_ev(p_list, odds_list)
    p_parlay = 1.0
    for p in p_list:
        p_parlay *= p
    return {"legs": legs, "dec_odds": dec, "ev": ev, "p_parlay": p_parlay}

def build_best_builder(top_singles: List[Dict]) -> Optional[Dict]:
    # 2-leg cross-game, both legs are singles-quality
    for i in range(len(top_singles)):
        for j in range(i + 1, len(top_singles)):
            a, b = top_singles[i], top_singles[j]
            if a.get("event") != b.get("event"):
                return _parlay_package([a, b])
    return None

def _sgp_ok_pair(a: Dict, b: Dict) -> bool:
    # Controlled SGP anti-correlation heuristics
    if a.get("event") != b.get("event"):
        return False
    if a.get("player") == b.get("player"):
        return False
    if a.get("market") == b.get("market"):
        return False
    if a.get("market") == "player_anytime_td" and b.get("market") == "player_anytime_td":
        return False
    return True

def build_controlled_sgp(approved: List[Dict], top_singles: List[Dict], sgp_decimal_cap: float) -> Optional[Dict]:
    # 2-leg same-game; at least one leg must be a top single; payout capped
    if not top_singles:
        return None

    by_event: dict[str, List[Dict]] = {}
    for p in approved:
        by_event.setdefault(p.get("event", ""), []).append(p)

    for anchor in top_singles:
        pool = sorted(by_event.get(anchor.get("event", ""), []), key=score_pick, reverse=True)
        for b in pool:
            if b is anchor:
                continue
            if not _sgp_ok_pair(anchor, b):
                continue
            pkg = _parlay_package([anchor, b])
            if pkg["dec_odds"] <= sgp_decimal_cap:
                return pkg

    return None

def build_lottery(approved: List[Dict], lottery_decimal_cap: float) -> Optional[Dict]:
    # 3-leg cross-game preferred; payout capped
    ranked = sorted(approved, key=score_pick, reverse=True)

    for i in range(len(ranked)):
        for j in range(i + 1, len(ranked)):
            for k in range(j + 1, len(ranked)):
                a, b, c = ranked[i], ranked[j], ranked[k]
                if len({a.get("event"), b.get("event"), c.get("event")}) < 3:
                    continue
                pkg = _parlay_package([a, b, c])
                if pkg["dec_odds"] <= lottery_decimal_cap:
                    return pkg

    return None
