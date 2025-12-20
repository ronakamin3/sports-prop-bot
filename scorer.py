def score_prop(prop):
    odds = prop.get("odds")
    market = prop.get("market", "").lower()

    if odds is None:
        return 0

    score = 0

    # Favor plus money
    if odds > 0:
        score += 2

    # Sweet spot for upside
    if 200 <= odds <= 900:
        score += 3

    # Market volatility bonuses
    if "three" in market or "3" in market:
        score += 1
    if "touchdown" in market or "td" in market:
        score += 1
    if "points" in market:
        score += 0.5
    if "receiving" in market:
        score += 0.5

    return score

def select_top(props, n):
    ranked = sorted(props, key=score_prop, reverse=True)
    return ranked[:n]
