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

def is_blocked_reception_over(c: dict) -> bool:
    """
    Remove NFL reception OVERS entirely (high variance; common "miss by 1").
    """
    return (
        c.get("sport") == "americanfootball_nfl"
        and c.get("market") == "player_receptions"
        and c.get("side") == "Over"
    )

def format_pick(p: dict) -> str:
    odds = p["target_odds"]
    line = p.get("line")
    s = f"{p['player']} — {p['market']} — {p['side']}"
    if line is not None:
        s += f" {line}"
    s += f" ({odds:+d})"
    return s

def why_line(p: dict) -> str:
    """
    One-line explanation for why a pick qualified.
    """
    dk_odds = p["target_odds"]
    p_model = p["p_model"]
    p_implied = implied_prob_american(dk_odds)
    edge = p_model - p_implied
    return (
        f"WHY: p_fair={p_model:.3f} vs DK_implied={p_implied:.3f} (edge={edge:+.3f}), "
        f"EV=${p['ev']:.3f}/$1, books={p['books_count']}, Kelly~{p['kelly_frac']*100:.2f}%"
    )

def normalize_to_candidates(event: dict, odds_data: dict) -> list[dict]:
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
        # O/U detection
        is_ou = any(("Over" in sides and "Under" in sides) for sides in book_sides.values())

        fair_probs_over: list[float] = []
        fair_probs_under: list[float] = []
        implied_probs_by_side: dict[str, list[float]] = {}

        # For O/U: only count books where both sides exist at same line (stronger)
        for bk, sides in book_sides.items():
            if "Over" in sides and "Under" in sides and isinstance(sides["Over"], int) and isinstance(sides["Under"], int):
                p_over = implied_prob_american(sides["Over"])
                p_under = implied_prob_american(sides["Under"])
                fair_over = fair_prob_two_way_no_vig(p_over, p_under)
                fair_under = 1.0 - fair_over
                fair_probs_over.append(fair_over)
                fair_probs_under.append(fair_under)

            for side_name, odd in sides.items():
                if isinstance(odd, int):
                    implied_probs_by_side.setdefault(side_name, []).append(implied_prob_american(odd))

        sides_to_emit = ["Over", "Under"] if is_ou else list(implied_probs_by_side.keys())

        for side in sides_to_emit:
            # Target odds from DK (or your target list)
            target_odds = None
            target_book_used = None
            for tb in TARGET_BOOKS:
                if tb in book_sides and side in book_sides[tb] and isinstance(book_sides[tb][side], int):
                    target_odds = book_sides[tb][side]
                    target_book_used = tb
                    break

            if is_ou and side in ("Over", "Under"):
                probs = fair_probs_over if side == "Over" else fair_probs_under
                p_model = consensus_probability_from_probs(probs)
                books_count = len(probs)
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

    # Debug counters (helps tune)
    blocked_gate = blocked_target_missing = blocked_odds_window = blocked_books = blocked_ev = blocked_reception_over = 0

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
        if is_blocked_reception_over(c):
            blocked_reception_over += 1
            continue

        gate = quality_gates(c, STRICT_MODE, NHL_REQUIRE_CONFIRMED_GOALIE)
        if not gate.ok:
            blocked_gate += 1
            continue

        o = c.get("target_odds")
        if not isinstance(o, int):
            blocked_target_missing += 1
            continue

        if o < MIN_ODDS or o > MAX_ODDS:
            blocked_odds_window += 1
            continue

        if c.get("books_count", 0) < MIN_BOOKS_FOR_CONSENSUS:
            blocked_books += 1
            continue

        ev = expected_value(c["p_model"], c["target_odds"])
        if ev < EV_THRESHOLD:
            blocked_ev += 1
            continue

        k = kelly_fraction(c["p_model"], c["target_odds"])
        c["ev"] = ev
        c["kelly_frac"] = min(k, KELLY_CAP)

        approved.append(c)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    if not approved:
        msg = "\n".join([
            "ℹ️ ACCURATE MODE — Today’s Games Only (No-Vig)",
            f"{now}",
            "No qualified picks today.",
            f"API calls: events={total_event_calls}, event-odds={total_odds_calls} (today events used={total_today_events_used})",
            f"Filters: EV≥{EV_THRESHOLD:.2f}, Books≥{MIN_BOOKS_FOR_CONSENSUS}, OddsRange[{MIN_ODDS},{MAX_ODDS}]",
            f"Blocked: gate={blocked_gate}, target_missing={blocked_target_missing}, odds_window={blocked_odds_window}, books={blocked_books}, ev={blocked_ev}, rec_over_blocked={blocked_reception_over}",
        ])
        send_telegram(msg)
        return

    top = select_top(approved, DAILY_PROP_COUNT)
    parlays = build_parlays(top, max_parlays=2) if len(top) >= 4 else []

    lines = [
        "✅ ACCURATE MODE — Today’s Games Only (+EV, No-Vig) — DK Target",
        f"{now}",
        f"API calls: events={total_event_calls}, event-odds={total_odds_calls} (today events used={total_today_events_used})",
        f"Filters: EV≥{EV_THRESHOLD:.2f}, Books≥{MIN_BOOKS_FOR_CONSENSUS}, OddsRange[{MIN_ODDS},{MAX_ODDS}], KellyCap={KELLY_CAP:.3f}",
        f"Blocked: gate={blocked_gate}, target_missing={blocked_target_missing}, odds_window={blocked_odds_window}, books={blocked_books}, ev={blocked_ev}, rec_over_blocked={blocked_reception_over}",
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
        lines.append(f"  Book={p.get('target_book_used')} | books={p.get('books_count', 0)}")
        lines.append(f"  {why_line(p)}")
        lines.append("")

    if not sent_any:
        return

    if parlays:
        lines.append("🎯 Parlay Builder (2-leg, cross-game) + EV Estimate")
        lines.append("(Independence estimate; DK parlay pricing may differ. Use as guidance.)")
        lines.append("")
        for i, par in enumerate(parlays, 1):
            legs = par["legs"]
            lines.append(f"Parlay {i}: p≈{par['p_parlay']:.3f} | dec≈{par['dec_odds']:.2f} | EV≈${par['ev']:.3f}/$1")
            for leg in legs:
                lines.append(f"- {format_pick(leg)}")
            lines.append("")

    lines.append("🔎 Not guarantees — improved quality: no-vig fair probs + blocked NFL reception OVERS + clear WHY.")
    send_telegram("\n".join(lines))

if __name__ == "__main__":
    main()
