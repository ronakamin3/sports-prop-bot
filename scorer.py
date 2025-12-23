from typing import List, Dict

def score_pick(p: Dict) -> float:
    ev = p.get("ev")
    books = p.get("books_count", 0)
    odds = p.get("target_odds")

    if not isinstance(ev, float) or not isinstance(books, int):
        return -999

    score = ev * 100.0 + min(books, 10) * 0.5
    if isinstance(odds, int) and odds > 0:
        score += 0.2
    return score

def select_top(picks: List[Dict], n: int) -> List[Dict]:
    ranked = sorted(picks, key=score_pick, reverse=True)
    return ranked[:n]

def build_parlays(picks: List[Dict], max_parlays: int = 2) -> List[List[Dict]]:
    """
    Build 2-leg cross-game parlays from the approved picks.
    Preference: one anchor-ish leg + one mid leg; then mid+mid.
    """
    def different_game(a: Dict, b: Dict) -> bool:
        return a.get("event") != b.get("event")

    anchors = [p for p in picks if isinstance(p.get("target_odds"), int) and -200 <= p["target_odds"] <= -110]
    mids = [p for p in picks if isinstance(p.get("target_odds"), int) and -110 < p["target_odds"] <= 200]

    parlays: List[List[Dict]] = []

    # Parlay 1: anchor + mid
    for a in anchors:
        for b in mids:
            if different_game(a, b):
                parlays.append([a, b])
                break
        if len(parlays) >= max_parlays:
            return parlays

    # Parlay 2: mid + mid
    for i in range(len(mids)):
        for j in range(i + 1, len(mids)):
            if different_game(mids[i], mids[j]):
                parlays.append([mids[i], mids[j]])
                if len(parlays) >= max_parlays:
                    return parlays

    return parlays
