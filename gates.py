from dataclasses import dataclass

@dataclass
class GateResult:
    ok: bool
    reason: str = ""

# Markets we allow by default (keep tight for accuracy)
ALLOWED_MARKETS = {
    # NBA
    "player_points",
    "player_threes",
    "player_points_rebounds_assists",

    # NFL
    "player_receptions",
    "player_reception_yds",
    "player_pass_yds",
    "player_anytime_td",

    # MLB
    "pitcher_strikeouts",
    "batter_hits",
    "batter_total_bases",
    "batter_home_runs",

    # NHL
    "player_shots_on_goal",
    "player_points",
    "player_goals",
    "player_goal_scorer_anytime",

    # Soccer
    "player_shots",
    "player_shots_on_target",
    "player_goal_scorer_anytime",
    "player_assists",
}

def quality_gates(c: dict, strict_mode: bool, nhl_require_confirmed_goalie: bool) -> GateResult:
    """
    Keep this gate about data integrity, not "trying to predict the sport".
    The EV/no-vig + multi-book checks already handle pricing quality.
    """

    # Must have sport/event/market/player/side
    for k in ("sport", "event", "market", "player", "side"):
        if not c.get(k):
            return GateResult(False, f"missing_{k}")

    market = c.get("market")
    if strict_mode and market not in ALLOWED_MARKETS:
        return GateResult(False, "market_not_allowed")

    # For O/U props, a numeric line is required
    if c.get("side") in ("Over", "Under"):
        if c.get("line") is None:
            return GateResult(False, "missing_line")

    # NHL goalie gate (only if you actually implement goalie confirmation elsewhere)
    if nhl_require_confirmed_goalie and c.get("sport") == "icehockey_nhl":
        if not c.get("goalie_confirmed"):
            return GateResult(False, "goalie_unconfirmed")

    return GateResult(True, "ok")
