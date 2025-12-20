from __future__ import annotations
from typing import List, Dict
from probability import expected_value

def score_pick(pick: Dict) -> float:
    # prioritize EV, then big payout
    ev = pick.get("ev")
    odds = pick.get("target_odds")
    if not isinstance(ev, float):
        return -999
    score = ev * 100  # EV dominates
    if isinstance(odds, int) and odds > 0:
        score += 0.5
        if 200 <= odds <= 900:
            score += 0.5
    return score

def select_top(picks: List[Dict], n: int) -> List[Dict]:
    ranked = sorted(picks, key=score_pick, reverse=True)
    return ranked[:n]

def build_parlays(picks: List[Dict]) -> List[List[Dict]]:
    """
    2-leg cross-game parlays from approved picks.
    Hittable = one anchor-ish leg + one upside leg, or two moderate plus legs.
    """
    anchors = [p for p in picks if isinstance(p.get("target_odds"), int) and -200 <= p["target_odds"] <= -110]
    upsides = [p for p in picks if isinstance(p.get("target_odds"), int) and 100 <= p["target_odds"] <= 350]

    def different_game(a: Dict, b: Dict) -> bool:
        return a.get("event") != b.get("event")

    parlays: List[List[Dict]] = []

    # Parlay 1: anchor + upside
    for a in anchors:
        for b in upsides:
            if different_game(a, b):
                parlays.append([a, b])
                break
        if len(parlays) >= 1:
            break

    # Parlay 2: two upsides
    for i in range(len(upsides)):
        for j in range(i + 1, len(upsides)):
            if different_game(upsides[i], upsides[j]):
                parlays.append([upsides[i], upsides[j]])
                break
        if len(parlays) >= 2:
            break

    return parlays
