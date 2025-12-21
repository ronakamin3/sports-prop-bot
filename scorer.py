from typing import List, Dict

def score_pick(p: Dict) -> float:
    """
    SUPER MAX: prioritize bigger payout odds, then EV, then books coverage.
    """
    odds = p.get("target_odds")
    ev = p.get("ev", 0.0)
    books = p.get("books_count", 0)

    if not isinstance(odds, int):
        return -999

    score = 0.0

    # bigger odds => "super max"
    if odds > 0:
        score += min(odds / 100.0, 30.0)  # cap effect

    # still reward EV
    if isinstance(ev, float):
        score += ev * 50.0

    # more books = more confidence in consensus
    score += min(books, 10) * 0.5

    return score

def select_top(picks: List[Dict], n: int) -> List[Dict]:
    ranked = sorted(picks, key=score_pick, reverse=True)
    return ranked[:n]

def build_parlays_super_max(picks: List[Dict], min_odds: int, max_odds: int) -> List[List[Dict]]:
    """
    Build 2-leg and 3-leg lotto parlays from longshots.
    Cross-game only.
    """
    longshots = [
        p for p in picks
        if isinstance(p.get("target_odds"), int) and min_odds <= p["target_odds"] <= max_odds
    ]

    def different_game(a: Dict, b: Dict) -> bool:
        return a.get("event") != b.get("event")

    parlays: List[List[Dict]] = []

    # 2-leg super max
    for i in range(len(longshots)):
        for j in range(i + 1, len(longshots)):
            if different_game(longshots[i], longshots[j]):
                parlays.append([longshots[i], longshots[j]])
                break
        if len(parlays) >= 1:
            break

    # 3-leg mega (optional, very low hit rate)
    if len(longshots) >= 3:
        for i in range(len(longshots)):
            for j in range(i + 1, len(longshots)):
                for k in range(j + 1, len(longshots)):
                    a, b, c = longshots[i], longshots[j], longshots[k]
                    if a["event"] != b["event"] and a["event"] != c["event"] and b["event"] != c["event"]:
                        parlays.append([a, b, c])
                        return parlays

    return parlays
