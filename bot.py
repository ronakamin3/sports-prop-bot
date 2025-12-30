from __future__ import annotations

import time
import requests
from datetime import datetime, timezone
from dateutil import tz, parser

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    SPORTS, EVENTS_PER_SPORT,
    MAX_SINGLES, COOLDOWN_MINUTES,
    STRICT_MODE, EV_THRESHOLD, KELLY_CAP,
    TARGET_BOOKS, NHL_REQUIRE_CONFIRMED_GOALIE,
    MIN_BOOKS_FOR_CONSENSUS, MIN_ODDS, MAX_ODDS,
    ENABLE_PARLAYS, ENABLE_SGP, ENABLE_LOTTERY,
    SGP_DECIMAL_CAP, LOTTERY_DECIMAL_CAP
)

from odds_provider import get_events, get_event_odds_multi_book
from storage import init_db, was_sent_recently, mark_sent
from gates import quality_gates
from probability import (
    implied_prob_american,
    expected_value,
    kelly_fraction,
    consensus_probability_from_probs,
    fair_prob_two_way_no_vig
)
from scorer import (
    select_top,
    build_best_builder,
    build_controlled_sgp,
    build_lottery
)


# =======================
# MARKETS PER SPORT
# =======================
SPORT_MARKETS = {
    "basketball_nba": "player_points,player_threes,player_points_rebounds_assists",
    "americanfootball_nfl": "player_receptions,player_reception_yds,player_pass_yds,player_anytime_td",
    "baseball_mlb": "pitcher_strikeouts,batter_hits,batter_total_bases,batter_home_runs",
    "icehockey_nhl": "player_shots_on_goal,player_points,player_goals,player_goal_scorer_anytime",
    "soccer_epl": "player_shots,player_shots_on_target,player_goal_scorer_anytime,player_assists",
    "soccer_usa_mls": "player_shots,player_shots_on_target,player_goal_scorer_anytime,player_assists",
}


# =======================
# TELEGRAM (SAFE SEND)
# =======================
def send_telegram(msg: str) -> None:
    """
    Robust Telegram sender:
    - Retries on network/429/5xx errors
    - NEVER crashes the workflow
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "disable_web_page_preview": True
    }

    backoff = [0, 2, 5, 10]  # seconds
    last_err = None

    for delay in backoff:
        try:
            if delay:
                time.sleep(delay)

            r = requests.post(url, json=payload, timeout=25)

            if r.status_code in (429,) or 500 <= r.status_code < 600:
                last_err = RuntimeError(f"Telegram HTTP {r.status_code}")
                continue

            r.raise_for_status()
            return

        except Exception as e:
            last_err = e
            continue

    print("⚠️ Telegram send failed — message printed below")
    print(msg)
    print("Error:", repr(last_err))


# =======================
# HELPERS
# =======================
def is_today_et(commence_time: str) -> bool:
    eastern = tz.gettz("America/New_York")
    today_et = datetime.now(tz=eastern).date()
    dt = parser.isoparse(commence_time)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(eastern).date() == today_et


def is_blocked_reception_over(c: dict) -> bool:
    return (
        c.get("sport") == "americanfootball_nfl"
        and c.get("market") == "player_receptions"
        and c.get("side") == "Over"
    )


def format_pick(p: dict) -> str:
    s = f"{p['player']} — {p['market']} — {p['side']}"
    if p.get("line") is not None:
        s += f" {p['line']}"
    s += f" ({p['target_odds']:+d})"
    return s


def why_line(p: dict) -> str:
    imp = implied_prob_american(p["target_odds"])
    edge = p["p_model"] - imp
    return (
        f"WHY: p_fair={p['p_model']:.3f} vs implied={imp:.3f} "
        f"(edge={edge:+.3f}), EV=${p['ev']:.3f}/$1, "
        f"books={p['books_count']}, Kelly~{p['kelly_frac']*100:.2f}%"
    )


# =======================
# NORMALIZATION
# =======================
def normalize_to_candidates(event: dict, odds_data: dict) -> list[dict]:
    sport = event.get("sport_key")
    event_name = f"{event.get('away_team','')} @ {event.get('home_team','')}".strip(" @")

    by_key = {}

    for bm in odds_data.get("bookmakers", []):
        bk = (bm.get("key") or "").lower()
        for m in bm.get("markets", []):
            for o in m.get("outcomes", []):
                player = o.get("description") or o.get("name")
                side = o.get("name")
                line = o.get("point")
                price = o.get("price")

                if not player or not side or not isinstance(price, int):
                    continue

                k = (m.get("key"), player, line)
                by_key.setdefault(k, {}).setdefault(bk, {})[side] = price

    out = []

    for (market, player, line), books in by_key.items():
        is_ou = any("Over" in s and "Under" in s for s in books.values())
        fair_over, fair_under = [], []
        implied = {}

        for sides in books.values():
            if "Over" in sides and "Under" in sides:
                po = implied_prob_american(sides["Over"])
                pu = implied_prob_american(sides["Under"])
                fo = fair_prob_two_way_no_vig(po, pu)
                fair_over.append(fo)
                fair_under.append(1 - fo)

            for s, o in sides.items():
                implied.setdefault(s, []).append(implied_prob_american(o))

        sides = ["Over", "Under"] if is_ou else implied.keys()

        for side in sides:
            odds_map = {
                b: books[b][side]
                for b in TARGET_BOOKS
                if b in books and side in books[b]
            }

            probs = (
                fair_over if side == "Over" else fair_under
            ) if is_ou else implied.get(side, [])

            p_model = consensus_probability_from_probs(probs)

            out.append({
                "sport": sport,
                "event": event_name,
                "market": market,
                "player": player,
                "side": side,
                "line": line,
                "target_odds_by_book": odds_map,
                "p_model": p_model,
                "books_count": len(probs),
                "goalie_confirmed": None,
            })

    return out


# =======================
# MAIN
# =======================
def main():
    init_db()

    all_candidates = []
    blocked_gate = blocked_missing = blocked_window = blocked_books = blocked_ev = blocked_rec = 0
    event_calls = odds_calls = today_used = 0

    for sport in SPORTS:
        events = get_events(sport)
        event_calls += 1

        today = [e for e in events if e.get("commence_time") and is_today_et(e["commence_time"])]
        today_used += min(len(today), EVENTS_PER_SPORT)

        for ev in today[:EVENTS_PER_SPORT]:
            odds = get_event_odds_multi_book(sport, ev["id"], SPORT_MARKETS.get(sport, ""))
            odds_calls += 1
            all_candidates += normalize_to_candidates(ev, odds)

    approved = []

    for c in all_candidates:
        if is_blocked_reception_over(c):
            blocked_rec += 1
            continue

        gate = quality_gates(c, STRICT_MODE, NHL_REQUIRE_CONFIRMED_GOALIE)
        if not gate.ok or c.get("p_model") is None:
            blocked_gate += 1
            continue

        best = None
        for book, odds in c["target_odds_by_book"].items():
            if odds < MIN_ODDS or odds > MAX_ODDS:
                blocked_window += 1
                continue
            ev = expected_value(c["p_model"], odds)
            if best is None or ev > best[0]:
                best = (ev, book, odds)

        if not best:
            blocked_missing += 1
            continue

        c["ev"], c["target_book_used"], c["target_odds"] = best
        if c["books_count"] < MIN_BOOKS_FOR_CONSENSUS:
            blocked_books += 1
            continue
        if c["ev"] < EV_THRESHOLD:
            blocked_ev += 1
            continue

        c["kelly_frac"] = min(kelly_fraction(c["p_model"], c["target_odds"]), KELLY_CAP)
        approved.append(c)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    if not approved:
        send_telegram(
            f"ℹ️ ACCURATE MODE — Today Only\n{now}\n"
            f"No qualified picks today.\n"
            f"Blocked: gate={blocked_gate}, missing={blocked_missing}, "
            f"window={blocked_window}, books={blocked_books}, ev={blocked_ev}, rec={blocked_rec}"
        )
        return

    singles = select_top(approved, MAX_SINGLES)
    lines = [f"✅ ACCURATE MODE — Today Only\n{now}\n"]

    for p in singles:
        key = f"{p['event']}|{p['player']}|{p['market']}|{p['side']}|{p['target_odds']}"
        if was_sent_recently(key, COOLDOWN_MINUTES):
            continue
        mark_sent(key)
        lines += [
            f"• {format_pick(p)}",
            f"  {p['event']}",
            f"  Book={p['target_book_used']}",
            f"  {why_line(p)}\n"
        ]

    if ENABLE_PARLAYS:
        bb = build_best_builder(singles)
        if bb:
            lines.append("🔵 BEST BUILDER PARLAY")
            for l in bb["legs"]:
                lines.append(f"- {format_pick(l)}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()