from __future__ import annotations
import requests
from datetime import datetime
from dateutil import tz

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
from probability import consensus_probability_from_odds, expected_value, kelly_fraction
from scorer import select_top


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

def pick_target_odds(prices_by_book: dict[str, int]) -> tuple[int | None, str | None]:
    for tb in TARGET_BOOKS:
        if tb in prices_by_book:
            return prices_by_book[tb], tb
    return None, None

def normalize_to_candidates(event: dict, odds_data: dict) -> list[dict]:
    sport = event.get("sport_key")
    away = event.get("away_team", "")
    home = event.get("home_team", "")
    event_name = f"{away} @ {home}".strip(" @")

    by_key: dict[tuple, dict[str, int]] = {}

    for bm in odds_data.get("bookmakers", []):
        bm_key = (bm.get("key") or "").lower()
        for m in bm.get("markets", []):
            market_key = m.get("key")
            for o in m.get("outcomes", []):
                player = o.get("description") or o.get("name")
                side = o.get("name")  # Over/Under/Yes/No etc.
                line = o.get("point")  # may be None (e.g., anytime TD)
                price = o.get("price")
                if not player or not market_key or not side:
                    continue
                if not isinstance(price, int):
                    continue

                k = (market_key, player, side, line)
                by_key.setdefault(k, {})
                by_key[k][bm_key] = price

    candidates: list[dict] = []
    for (market_key, player, side, line), prices_by_book in by_key.items():
        target_odds, target_book_used = pick_target_odds(prices_by_book)

        all_odds = [v for v in prices_by_book.values() if isinstance(v, int)]
        books_count = len(all_odds)

        p_model = None
        if books_count >= MIN_BOOKS_FOR_CONSENSUS:
            p_model = consensus_probability_from_odds(all_odds)

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

def format_pick(p: dict) -> str:
    odds = p["target_odds"]
    line = p.get("line")
    s = f"{p['player']} — {p['market']} — {p['side']}"
    if line is not None:
        s += f" {line}"
    s += f" ({odds:+d})"
    return s

def main():
    init_db()

    all_candidates: list[dict] = []
    total_event_calls = 0
    total_odds_calls = 0

    for sport in SPORTS:
        markets = SPORT_MARKETS.get(sport, "")
        if not markets:
            continue

        events = get_events(sport)
        total_event_calls += 1

        for event in events[:EVENTS_PER_SPORT]:
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

        # Require strong consensus coverage
        if c.get("books_count", 0) < MIN_BOOKS_FOR_CONSENSUS:
            continue

        ev = expected_value(c["p_model"], c["target_odds"])
        if ev < EV_THRESHOLD:
            continue

        k = kelly_fraction(c["p_model"], c["target_odds"])
        c["ev"] = ev
        c["kelly_frac"] = min(k, KELLY_CAP)

        approved.append(c)

    if not approved:
        # Quiet by design (accuracy mode)
        return

    top = select_top(approved, DAILY_PROP_COUNT)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    lines = [
        "✅ ACCURATE MODE — +EV (Process Quality)",
        f"{now}",
        f"API calls: events={total_event_calls}, event-odds={total_odds_calls}",
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

    lines.append("🔎 Not guarantees — guaranteed process quality (multi-book consensus +EV + bankroll cap).")
    send_telegram("\n".join(lines))

if __name__ == "__main__":
    main()
