# bot.py — UPDATED (fixes massive "missing" issue)
from __future__ import annotations

import time
import requests
from datetime import datetime, timezone, timedelta
from dateutil import tz, parser

from config import *
from odds_provider import get_events, get_event_odds_multi_book
from storage import init_db, was_sent_recently, mark_sent
from gates import quality_gates
from probability import (
    implied_prob_american,
    expected_value,
    kelly_fraction,
    consensus_probability_from_probs,
    fair_prob_two_way_no_vig,
)
from scorer import select_top


SPORT_MARKETS = {
    "basketball_nba": "player_points,player_threes,player_points_rebounds_assists",
    "americanfootball_nfl": "player_receptions,player_reception_yds,player_pass_yds,player_anytime_td",
    "baseball_mlb": "pitcher_strikeouts,batter_hits,batter_total_bases,batter_home_runs",
    "icehockey_nhl": "player_shots_on_goal,player_points,player_goals,player_goal_scorer_anytime",
    "soccer_epl": "player_shots,player_shots_on_target,player_goal_scorer_anytime,player_assists",
    "soccer_usa_mls": "player_shots,player_shots_on_target,player_goal_scorer_anytime,player_assists",
}


def send_telegram(msg: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "disable_web_page_preview": True
    }, timeout=30)


def is_today_et(t: str) -> bool:
    eastern = tz.gettz("America/New_York")
    dt = parser.isoparse(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(eastern).date() == datetime.now(eastern).date()


def is_pregame_ok(t: str) -> bool:
    dt = parser.isoparse(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= datetime.now(timezone.utc) + timedelta(minutes=PREGAME_BUFFER_MINUTES)


def normalize_to_candidates(event, odds_data):
    out = []
    by_key = {}

    for bm in odds_data.get("bookmakers", []):
        bk = bm["key"].lower()
        for m in bm.get("markets", []):
            for o in m.get("outcomes", []):
                k = (m["key"], o.get("description") or o["name"], o.get("point"))
                by_key.setdefault(k, {}).setdefault(bk, {})[o["name"]] = o["price"]

    for (market, player, line), books in by_key.items():
        probs = []
        for sides in books.values():
            if "Over" in sides and "Under" in sides:
                po = implied_prob_american(sides["Over"])
                pu = implied_prob_american(sides["Under"])
                probs.append(fair_prob_two_way_no_vig(po, pu))

        if not probs:
            continue

        p_model = consensus_probability_from_probs(probs)

        odds_map = {
            b: books[b][list(books[b].keys())[0]]
            for b in TARGET_BOOKS
            if b in books
        }

        out.append({
            "sport": event["sport_key"],
            "event": f"{event['away_team']} @ {event['home_team']}",
            "market": market,
            "player": player,
            "side": list(books[next(iter(books))].keys())[0],
            "line": line,
            "p_model": p_model,
            "books_count": len(probs),
            "target_odds_by_book": odds_map,
        })

    return out


def main():
    init_db()
    approved = []

    for sport in SPORTS:
        events = get_events(sport)
        today = [e for e in events if is_today_et(e["commence_time"]) and is_pregame_ok(e["commence_time"])]
        for ev in today[:EVENTS_PER_SPORT]:
            odds = get_event_odds_multi_book(sport, ev["id"], SPORT_MARKETS.get(sport, ""))
            for c in normalize_to_candidates(ev, odds):

                if len(c["target_odds_by_book"]) < 1:
                    continue

                best = None
                for book, odds_val in c["target_odds_by_book"].items():
                    if odds_val < MIN_ODDS or odds_val > MAX_ODDS:
                        continue
                    evv = expected_value(c["p_model"], odds_val)
                    if not best or evv > best[0]:
                        best = (evv, book, odds_val)

                if not best:
                    continue

                c["ev"], c["target_book_used"], c["target_odds"] = best
                edge = c["p_model"] - implied_prob_american(c["target_odds"])

                if (
                    c["books_count"] >= MIN_BOOKS_FOR_CONSENSUS and
                    c["p_model"] >= MIN_P_FAIR and
                    edge >= MIN_EDGE and
                    c["ev"] >= MIN_EV_DOLLARS
                ):
                    c["kelly_frac"] = min(kelly_fraction(c["p_model"], c["target_odds"]), KELLY_CAP)
                    approved.append(c)

    if not approved:
        send_telegram("ℹ️ BEST MODE — No A+ picks today. Best move is no bet.")
        return

    picks = select_top(approved, MAX_SINGLES)

    lines = ["✅ BEST MODE — A+ PICKS ONLY", ""]
    for p in picks:
        key = f"{p['event']}|{p['player']}|{p['market']}|{p['target_odds']}"
        if was_sent_recently(key, COOLDOWN_MINUTES):
            continue
        mark_sent(key)
        lines += [
            f"• {p['player']} — {p['market']} ({p['target_odds']:+d})",
            f"  {p['event']} | Book={p['target_book_used']}",
            f"  p_fair={p['p_model']:.3f} | EV=${p['ev']:.3f} | Kelly={p['kelly_frac']*100:.2f}%",
            ""
        ]

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()