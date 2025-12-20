import requests
from datetime import datetime
from dateutil import tz

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    SPORTS,
    DAILY_PROP_COUNT,
    COOLDOWN_MINUTES,
    EVENTS_PER_SPORT,
)
from odds_provider import get_events, get_event_props
from storage import init_db, was_sent_recently, mark_sent
from scorer import select_top, build_parlays, reason_tags


# Markets by sport (The Odds API market keys) :contentReference[oaicite:3]{index=3}
SPORT_MARKETS = {
    "basketball_nba": "player_points,player_threes,player_points_rebounds_assists",
    "americanfootball_nfl": "player_anytime_td,player_reception_yds,player_receptions,player_pass_yds",
    "baseball_mlb": "batter_home_runs,batter_hits,batter_total_bases,pitcher_strikeouts",
    "icehockey_nhl": "player_goals,player_points,player_shots_on_goal,player_goal_scorer_anytime",
    "soccer_epl": "player_goal_scorer_anytime,player_shots,player_shots_on_target,player_assists",
    "soccer_usa_mls": "player_goal_scorer_anytime,player_shots,player_shots_on_target,player_assists",
}

def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secrets.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()

def normalize_props(event: dict, odds_data: dict):
    props = []
    away = event.get("away_team", "")
    home = event.get("home_team", "")
    event_name = f"{away} @ {home}".strip(" @")

    for book in odds_data.get("bookmakers", []):
        for market in book.get("markets", []):
            market_key = market.get("key")
            for o in market.get("outcomes", []):
                player = o.get("description") or o.get("name")
                if not player:
                    continue

                props.append({
                    "sport": event.get("sport_key"),
                    "event": event_name,
                    "player": player,
                    "market": market_key,
                    "line": o.get("point"),
                    "odds": o.get("price"),
                    "time": event.get("commence_time"),
                })
    return props

def format_prop_line(p: dict) -> str:
    market = p.get("market", "prop")
    player = p.get("player", "Player")
    line = p.get("line")
    odds = p.get("odds")

    s = f"{player} — {market}"
    if line is not None:
        s += f" {line}"
    if isinstance(odds, int):
        s += f" ({odds:+d})"
    return s

def main():
    init_db()
    all_props = []

    # Debug-friendly counters
    total_event_calls = 0
    total_odds_calls = 0

    for sport in SPORTS:
        # Pull events (1 request per sport)
        events = get_events(sport)
        total_event_calls += 1

        markets = SPORT_MARKETS.get(sport, "")
        if not markets:
            continue

        # Limit per sport to control API usage
        for event in events[:EVENTS_PER_SPORT]:
            odds = get_event_props(sport, event["id"], markets)
            total_odds_calls += 1
            all_props.extend(normalize_props(event, odds))

    # Build watchlist
    picks = select_top(all_props, DAILY_PROP_COUNT)
    if not picks:
        # Don’t spam if nothing returned
        return

    parlays = build_parlays(picks)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    lines = [
        f"🔥 PROP WATCHLIST (FanDuel)\n{now}",
        f"API calls this run: events={total_event_calls}, event-odds={total_odds_calls}\n",
    ]

    # Add props (dedup + cooldown)
    sent_any = False
    for p in picks:
        key = f"{p.get('sport')}|{p.get('event')}|{p.get('player')}|{p.get('market')}|{p.get('line')}|{p.get('odds')}"
        if was_sent_recently(key, COOLDOWN_MINUTES):
            continue
        mark_sent(key)
        sent_any = True

        lines.append(f"• {format_prop_line(p)}")
        lines.append(f"  {p.get('event','')}")
        lines.append(f"  Tags: {reason_tags(p)}\n")

    if not sent_any:
        return

    # Add “hittable” parlays (ideas)
    if parlays:
        lines.append("🎯 Hittable Parlay Ideas (2-leg)\n")
        for idx, parlay in enumerate(parlays, 1):
            lines.append(f"Parlay {idx}:")
            for leg in parlay:
                lines.append(f"- {format_prop_line(leg)}")
            lines.append("")  # blank line

    lines.append("🔎 These are ideas to look into (not guarantees).")
    send_telegram("\n".join(lines))

if __name__ == "__main__":
    main()
