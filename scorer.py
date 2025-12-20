from typing import List, Dict

def score_prop(prop: Dict) -> float:
    odds = prop.get("odds")
    market = (prop.get("market") or "").lower()

    if not isinstance(odds, int):
        return -999

    score = 0.0

    # Prefer plus money
    if odds > 0:
        score += 2.0
    else:
        score += 0.2  # keep some anchors available

    # Sweet spot for "big but not insane"
    if 200 <= odds <= 900:
        score += 3.0
    elif odds > 900:
        score += 1.0  # lotto

    # Volatility / upside bonuses by market
    if "anytime_td" in market:
        score += 1.2
    if "batter_home_runs" in market:
        score += 1.2
    if "player_goal_scorer_anytime" in market:
        score += 1.2
    if "player_shots_on_goal" in market:
        score += 0.8
    if "player_threes" in market:
        score += 0.8
    if "player_points_rebounds_assists" in market:
        score += 0.5
    if "pitcher_strikeouts" in market:
        score += 0.6

    return score

def select_top(props: List[Dict], n: int) -> List[Dict]:
    ranked = sorted(props, key=score_prop, reverse=True)
    # remove junk/empty
    ranked = [p for p in ranked if score_prop(p) > 0]
    return ranked[:n]

def build_parlays(props: List[Dict]) -> List[List[Dict]]:
    """
    Build 2-leg "hittable parlay ideas" from the watchlist.
    Cross-game only (avoids correlation confusion).
    """
    anchors = [
        p for p in props
        if isinstance(p.get("odds"), int) and -200 <= p["odds"] <= -110
    ]
    upsides = [
        p for p in props
        if isinstance(p.get("odds"), int) and 100 <= p["odds"] <= 350
    ]

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

def reason_tags(prop: Dict) -> str:
    odds = prop.get("odds")
    market = (prop.get("market") or "").lower()
    tags = []

    if isinstance(odds, int) and odds > 0:
        tags.append("PLUS MONEY")
    if isinstance(odds, int) and 200 <= odds <= 900:
        tags.append("HIGH PAYOUT")

    if "anytime_td" in market:
        tags.append("TD UPSIDE")
    if "batter_home_runs" in market:
        tags.append("HR UPSIDE")
    if "player_goal_scorer_anytime" in market:
        tags.append("GOAL UPSIDE")
    if "player_shots_on_goal" in market:
        tags.append("SHOTS VOLUME")
    if "player_threes" in market:
        tags.append("3PT VARIANCE")
    if "pitcher_strikeouts" in market:
        tags.append("K VOLUME")

    return ", ".join(tags) if tags else "WATCH"
