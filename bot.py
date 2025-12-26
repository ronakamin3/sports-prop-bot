from __future__ import annotations
import requests
from datetime import datetime, timezone
from dateutil import tz, parser

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    SPORTS, EVENTS_PER_SPORT,
    DAILY_PROP_COUNT, COOLDOWN_MINUTES,
    STRICT_MODE, EV_THRESHOLD, KELLY_CAP,
    TARGET_BOOKS, NHL_REQUIRE_CONFIRMED_GOALIE,
    MIN_BOOKS_FOR_CONSENSUS, MIN_ODDS, MAX_ODDS,
)
from odds_provider import get_events, get_event_odds_multi_book
from storage import init_db, was_sent_recently, mark_sent
from gates import quality_gates
from probability import (
    implied_prob_american, expected_value, kelly_fraction,
    consensus_probability_from_probs, fair_prob_two_way_no_vig
)
from scorer import select_top, build_parlays


SPORT_MARKETS = {
    "basketball_nba": "player_points,player_threes,player_points_rebounds_assists",
    "americanfootball_nfl": "player_receptions,player_reception_yds,player_pass_yds,player_anytime_td",
    "baseball_mlb": "pitcher_strikeouts,batter_hits,batter_total_bases,batter_home_runs",
    "icehockey_nhl": "player_shots_on_goal,player_points,player_goals,player_goal_scorer_anytime",
    "soccer_epl": "player_shots,player_shots_on_target,player_goal_scorer_anytime,player_assists",
    "soccer_usa_mls": "player_shots,player_shots_on_target,player_goal_scorer_anytime,player_assists",
}

def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "disable_web_page_preview": True}
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()

def is_today_et(commence_time: str) -> bool:
    eastern = tz.gettz("America/New_York")
    today_et = datetime.now(tz=eastern).date()

    dt = parser.isoparse(commence_time)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(eastern).date() == today_et

def pick_target_odds(prices_by_book: dict[str, dict]) -> tuple[int | None, str | None]:
    """
    prices_by_book[bk] holds dict like {"Over": int, "Under": int, "Yes": int, ...}
    Return DK (or target) odds for the 'side' we’re evaluating later.
    We pick later per-side; this helper is not used anymore for selection.
    """
    return None, None

def format_pick(p: dict) -> str:
    odds = p["target_odds"]
    line = p.get("line")
    s = f"{p['player']} — {p['market']} — {p['side']}"
    if line is not None:
        s += f" {line}"
    s += f" ({odds:+d})"
    return s

def normalize_to_candidates(event: dict, odds_data: dict) -> list[dict]:
    """
    Build per-prop candidates with no-vig consensus when Over/Under exists at same line.
    Keyed by (market, player, line).
    """
    sport = event.get("sport_key")
    away = event.get("away_team", "")
    home = event.get("home_team", "")
    event_name = f"{away} @ {home}".strip(" @")

    # key -> book -> {side: odds}
    by_key: dict[tuple, dict[str, dict[str, int]]] = {}

    for bm in odds_data.get("bookmakers", []):
        bm_key = (bm.get("key") or "").lower()
        for m in bm.get("markets", []):
            market_key = m.get("key")
            for o in m.get("outcomes", []):
                player = o.get("description") or o.get("name")
                side = o.get("name")  # Over/Under/Yes/No etc.
                line = o.get("point")  # may be None for yes/no markets
                price = o.get("price")

                if not player or not market_key or not side:
                    continue
                if not isinstance(price, int):
                    continue

                k = (market_key, player, line)
                by_key.setdefault(k, {})
                by_key[k].setdefault(bm_key, {})
                by_key[k][bm_key][side] = price

    candidates: list[dict] = []

    for (market_key, player, line), book_sides in by_key.items():
        # Identify if this looks like a two-way O/U market
        is_ou = any("Over" in sides or "Under" in sides for sides in book_sides.values())

        # Build consensus fair probs per side
        fair_probs_over: list[float] = []
        fair_probs_under: list[float] = []

        # Also keep fallback implied probs for non-O/U markets
        implied_probs_by_side: dict[str, list[float]] = {}

        for bk, sides in book_sides.items():
            # For O/U: compute no-vig if both exist
            if "Over" in sides and "Under" in sides and isinstance(sides["Over"], int) and isinstance(sides["Under"], int):
                p_over = implied_prob_american(sides["Over"])
                p_under = implied_prob_american(sides["Under"])
                fair_over = fair_prob_two_way_no_vig(p_over, p_under)
                fair_under = 1.0 - fair_over
                fair_probs_over.append(fair_over)
                fair_probs_under.append(fair_under)

            # For any market: store implied for each available side (fallback)
            for side_name, odd in sides.items():
                if isinstance(odd, int):
                    implied_probs_by_side.setdefault(side_name, []).append(implied_prob_american(odd))

        # Build one candidate per side we might bet
        for side in ["Over", "Under"] if is_ou else list(implied_probs_by_side.keys()):
            # Determine target odds from DK/target books for this side
            target_odds = None
            target_book_used = None
            for tb in TARGET_BOOKS:
                if tb in book_sides and side in book_sides[tb] and isinstance(book_sides[tb][side], int):
                    target_odds = book_sides[tb][side]
                    target_book_used = tb
                    break

            # Consensus p_model
            if is_ou and side in ("Over", "Under"):
                probs = fair_probs_over if side == "Over" else fair_probs_under
                p_model = consensus_probability_from_probs(probs)
                books_count = len(probs)  # number of books with both sides (stronger)
            else:
                probs = implied_probs_by_side.get(side, [])
                p_model = consensus_probability_from_probs(probs)
                books_count = len(probs)

            candidates.append({
                "sport": sport,
                "event": event_name,
                "market": market_key,
                "player": player,
                "side": side,
                "line": line,
                "target_odds": target_odds,
                "target_book_used": target_book_used,
                "p_model": p_model,
                "books_count": books_count,
                "goalie_confirmed": None,
            })

    return candidates

def main():
    init_db()

    all_candidates: list[dict] = []
    total_event_calls = 0
    total_odds_calls = 0
    total_today_events_used = 0

    for sport in SPORTS:
        markets = SPORT_MARKETS.get(sport, "")
        if not markets:
            continue

        events = get_events(sport)
        total_event_calls += 1

        today_events = [e for e in events if e.get("commence_time") and is_today_et(e["commence_time"])]
        total_today_events_used += min(len(today_events), EVENTS_PER_SPORT)

        for event in today_events[:EVENTS_PER_SPORT]:
            odds_data = get_event_odds_multi_book(sport, event["id"], markets)
            total_odds_calls += 1
            all_candidates.extend(normalize_to_candidates(event, odds_data))

    approved: list[dict] = []

    for c in all_candidates:
        gate = quality_gates(c, STRICT_MODE, NHL_REQUIRE_CONFIRMED_GOALIE)
        if not gate.ok:
            continue

        o = c.get("target_odds")
        if not isinstance(o, int):
            continue

        # Accuracy odds window
        if o < MIN_ODDS or o > MAX_ODDS:
            continue

        # Require strong consensus coverage (now “books_count” means quality books for that side)
        if c.get("books_count", 0) < MIN_BOOKS_FOR_CONSENSUS:
            continue

        ev = expected_value(c["p_model"], c["target_odds"])
        if ev < EV_THRESHOLD:
            continue

        k = kelly_fraction(c["p_model"], c["target_odds"])
        c["ev"] = ev
        c["kelly_frac"] = min(k, KELLY_CAP)

        approved.append(c)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    if not approved:
        # Send a status message so you know it ran + what happened
        msg = "\n".join([
            "ℹ️ ACCURATE MODE — Today’s Games Only (No-Vig)",
            f"{now}",
            f"No qualified picks today.",
            f"API calls: events={total_event_calls}, event-odds={total_odds_calls} (today events used={total_today_events_used})",
            f"Filters: EV≥{EV_THRESHOLD:.2f}, Books≥{MIN_BOOKS_FOR_CONSENSUS}, OddsRange[{MIN_ODDS},{MAX_ODDS}]",
        ])
        send_telegram(msg)
        return

    top = select_top(approved, DAILY_PROP_COUNT)
    parlays = build_parlays(top, max_parlays=2) if len(top) >= 4 else []

    lines = [
        "✅ ACCURATE MODE — Today’s Games Only (+EV, No-Vig Consensus)",
        f"{now}",
        f"API calls: events={total_event_calls}, event-odds={total_odds_calls} (today events used={total_today_events_used})",
        f"Filters: EV≥{EV_THRESHOLD:.2f}, Books≥{MIN_BOOKS_FOR_CONSENSUS}, OddsRange[{MIN_ODDS},{MAX_ODDS}], KellyCap={KELLY_CAP:.3f}",
        "",
    ]

    sent_any = False
    for p in top:
        key = f"{p['sport']}|{p['event']}|{p['market']}|{p['player']}|{p['side']}|{p.get('line')}|{p['target_odds']}"
        if was_sent_recently(key, COOLDOWN_MINUTES):
            continue
        mark_sent(key)
        sent_any = True

        lines.append(f"• {format_pick(p)}")
        lines.append(f"  {p['event']}")
        lines.append(f"  Book={p.get('target_book_used')} | p_model={p['p_model']:.3f} | EV=${p['ev']:.3f}/$1 | Stake~{p['kelly_frac']*100:.2f}% bankroll")
        lines.append(f"  Books used={p.get('books_count', 0)}")
        lines.append("")

    if not sent_any:
        return

    if parlays:
        lines.append("🎯 Parlay Builder (2-leg, cross-game)")
        lines.append("(Only from today’s approved +EV picks)")
        lines.append("")
        for i, parlay in enumerate(parlays, 1):
            lines.append(f"Parlay {i}:")
            for leg in parlay:
                lines.append(f"- {format_pick(leg)}")
            lines.append("")

    lines.append("🔎 Not guarantees — stronger process quality (no-vig + multi-book consensus +EV + bankroll cap).")
    send_telegram("\n".join(lines))

if __name__ == "__main__":
    main()
