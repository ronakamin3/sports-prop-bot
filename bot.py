from __future__ import annotations
import requests
from datetime import datetime
from dateutil import tz
from statistics import median

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    SPORTS, EVENTS_PER_SPORT,
    DAILY_PROP_COUNT, COOLDOWN_MINUTES,
    STRICT_MODE, EV_THRESHOLD, KELLY_CAP,
    TARGET_BOOK, NHL_REQUIRE_CONFIRMED_GOALIE
)
from odds_provider import get_events, get_event_odds_multi_book
from storage import init_db, was_sent_recently, mark_sent
from gates import quality_gates
from probability import consensus_probability, expected_value, kelly_fraction
from scorer import select_top, build_parlays


# Market keys (The Odds API)
SPORT_MARKETS = {
    "basketball_nba": "player_points,player_threes,player_points_rebounds_assists",
    "americanfootball_nfl": "player_anytime_td,player_reception_yds,player_receptions,player_pass_yds",
    "baseball_mlb": "batter_home_runs,batter_hits,batter_total_bases,pitcher_strikeouts",
    "icehockey_nhl": "player_goals,player_points,player_shots_on_goal,player_goal_scorer_anytime",
    "soccer_epl": "player_goal_scorer_anytime,player_shots,player_shots_on_target,player_assists",
    "soccer_usa_mls": "player_goal_scorer_anytime,player_shots,player_shots_on_target,player_assists",
}

def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()

def normalize_to_candidates(event: dict, odds_data: dict, target_book: str) -> list[dict]:
    """
    Build candidate props keyed by (market, player, side, line) and collect prices by bookmaker.
    We'll compute:
      - target_odds (FanDuel)
      - consensus p_model (median implied prob across OTHER books)
    """
    sport = event.get("sport_key")
    away = event.get("away_team", "")
    home = event.get("home_team", "")
    event_name = f"{away} @ {home}".strip(" @")

    # key -> {book: odds}
    by_key: dict[tuple, dict[str, int]] = {}

    for bm in odds_data.get("bookmakers", []):
        bm_key = (bm.get("key") or "").lower()
        for m in bm.get("markets", []):
            market_key = m.get("key")
            for o in m.get("outcomes", []):
                # For player props, many APIs use:
                # - o["description"] = player
                # - o["name"] = "Over"/"Under" or the selection
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
        target_odds = prices_by_book.get(target_book)

        # Consensus probability from OTHER books (exclude target book)
        other_odds = [v for bk, v in prices_by_book.items() if bk != target_book and isinstance(v, int)]
        p_model = consensus_probability(other_odds)

        candidates.append({
            "sport": sport,
            "event": event_name,
            "market": market_key,
            "player": player,
            "side": side,
            "line": line,
            "target_odds": target_odds,
            "p_model": p_model,
            "books_count": len(prices_by_book),
            "goalie_confirmed": None,  # placeholder for future NHL feed
        })

    return candidates

def format_pick(p: dict) -> str:
    odds = p["target_odds"]
    line = p.get("line")
    base = f"{p['player']} — {p['market']} — {p['side']}"
    if line is not None:
        base += f" {line}"
    base += f" ({odds:+d})"
    return base

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
            all_candidates.extend(normalize_to_candidates(event, odds_data, TARGET_BOOK))

    approved: list[dict] = []

    for c in all_candidates:
        gate = quality_gates(c, STRICT_MODE, NHL_REQUIRE_CONFIRMED_GOALIE)
        if not gate.ok:
            continue

        ev = expected_value(c["p_model"], c["target_odds"])
        if ev < EV_THRESHOLD:
            continue

        k = kelly_fraction(c["p_model"], c["target_odds"])
        k_capped = min(k, KELLY_CAP)

        c["ev"] = ev
        c["kelly_frac"] = k_capped
        approved.append(c)

    if not approved:
        # nothing qualifies; stay quiet (process quality)
        return

    top = select_top(approved, DAILY_PROP_COUNT)
    parlays = build_parlays(top)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    lines = [
        f"✅ +EV PICKS (Process-Quality) — {TARGET_BOOK.title()}",
        f"{now}",
        f"API calls this run: events={total_event_calls}, event-odds={total_odds_calls}",
        f"Filters: EV≥{EV_THRESHOLD:.2f}, KellyCap={KELLY_CAP:.3f}, Strict={STRICT_MODE}",
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
        lines.append(f"  p_model={p['p_model']:.3f} | EV=${p['ev']:.3f}/$1 | Stake~{p['kelly_frac']*100:.2f}% bankroll")
        lines.append(f"  Books used={p.get('books_count', 0)} (consensus excludes {TARGET_BOOK})")
        lines.append("")

    if not sent_any:
        return

    if parlays:
        lines.append("🎯 Hittable Parlay Ideas (2-leg, cross-game)")
        lines.append("(Built only from approved +EV picks)")
        lines.append("")
        for i, parlay in enumerate(parlays, 1):
            lines.append(f"Parlay {i}:")
            for leg in parlay:
                lines.append(f"- {format_pick(leg)}")
            lines.append("")

    lines.append("🔎 Not guarantees — guaranteed process quality (data gates + EV + bankroll cap).")
    send_telegram("\n".join(lines))

if __name__ == "__main__":
    main()
