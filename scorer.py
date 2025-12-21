from typing import List, Dict

def score_pick(p: Dict) -> float:
    ev = p.get("ev")
    books = p.get("books_count", 0)
    odds = p.get("target_odds")

    if not isinstance(ev, float) or not isinstance(books, int):
        return -999

    # EV dominates; more books boosts confidence; slight bonus for plus-money
    score = ev * 100.0 + min(books, 10) * 0.5
    if isinstance(odds, int) and odds > 0:
        score += 0.2
    return score

def select_top(picks: List[Dict], n: int) -> List[Dict]:
    ranked = sorted(picks, key=score_pick, reverse=True)
    return ranked[:n]
