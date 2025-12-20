import requests
from datetime import datetime
from dateutil import tz

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    SPORTS,
    DAILY_PROP_COUNT,
    COOLDOWN_MINUTES
)
from odds_provider import get_events, get_event_props
from storage import init_db, was_sent_recently, mark_sent
from scorer import select_top

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "disable_web_page_preview": True
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()

def normalize_props(event, odds_data):
    props = []
    for book in odds_data.get("bookmakers", []):
        for market in book.get("markets", []):
            for o in market.get("outcomes", []):
                props.append({
                    "event": f"{event['away_team']} @ {event['home_team']}",
                    "player": o.get("description") or o.get("name"),
                    "market": market["key"],
                    "line": o.get("point"),
                    "odds": o.get("price"),
                    "time": event["commence_time"]
                })
    return props

def main():
    init_db()
    all_props = []

    for sport in SPORTS:
        events = get_events(sport)[:8]
        markets = (
            "player_points,player_threes"
            if "nba" in sport else
            "player_anytime_td,player_reception_yds"
        )

        for event in events:
            odds = get_event_props(sport, event["id"], markets)
            all_props.extend(normalize_props(event, odds))

    picks = select_top(all_props, DAILY_PROP_COUNT)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    lines = [f"🔥 PROP WATCHLIST (FanDuel)\n{now}\n"]

    for p in picks:
        key = f"{p['event']}|{p['player']}|{p['market']}|{p['line']}|{p['odds']}"
        if was_sent_recently(key, COOLDOWN_MINUTES):
            continue
        mark_sent(key)

        line = f"{p['player']} — {p['market']}"
        if p["line"] is not None:
            line += f" {p['line']}"
        line += f" ({p['odds']:+d})"
        line += f"\n{p['event']}\n"
        lines.append(line)

    if len(lines) > 1:
        send_telegram("\n".join(lines))

if __name__ == "__main__":
    main()
