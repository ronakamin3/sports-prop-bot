from __future__ import annotations

import time
import requests
from datetime import datetime, timezone, timedelta
from dateutil import tz, parser

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    SPORTS, EVENTS_PER_SPORT, PREGAME_BUFFER_MINUTES,
    STRICT_MODE, MIN_BOOKS_FOR_CONSENSUS,
    MIN_P_FAIR, MIN_EDGE, MIN_EV_DOLLARS,
    MIN_ODDS, MAX_ODDS, KELLY_CAP,
    MAX_SINGLES, WATCHLIST_COUNT, COOLDOWN_MINUTES,
    TARGET_BOOKS, NHL_REQUIRE_CONFIRMED_GOALIE,
    ENABLE_PARLAYS, BUILDER_LEGS, BUILDER_MIN_DEC, BUILDER_MAX_DEC,
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

# scorer.select_top exists; builder uses our own function below to stay reliable
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
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "disable_web_page_preview": True}

    backoff = [0, 2, 5, 10, 20]
    last_err = None

    for delay in backoff:
        try:
            if delay:
                time.sleep(delay)
            r = requests.post(url, json=payload, timeout=40)
            if r.status_code == 429 or 500 <= r.status_code < 600:
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


def is_today_et(commence_time: str) -> bool:
    eastern = tz.gettz("America/New_York")
    today_et = datetime.now(tz=eastern).date()
    dt = parser.isoparse(commence_time)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(eastern).date() == today_et


def is_pregame_ok(commence_time: str) -> bool:
    start = parser.isoparse(commence_time)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return start >= (now + timedelta(minutes=PREGAME_BUFFER_MINUTES))


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
        f"(edge={edge:+.3f}), EV=${p['ev']:.3f}/$1, books={p['books_count']}, "
        f"Kelly~{p['kelly_frac']*100:.2f}%"
    )


def american_to_decimal(odds: int) -> float:
    if odds > 0:
        return 1.0 + (odds / 100.0)
    return 1.0 + (100.0 / abs(odds))


def build_big_builder(high_hit: list[dict]) -> dict | None:
    """Build a 2–3 leg builder from HIGH-HIT picks only, targeting a payout window."""
    if len(high_hit) < BUILDER_LEGS:
        return None

    # greedy: sort by best EV first, then take first N that don't duplicate same player/market
    used = set()
    legs = []
    for p in sorted(high_hit, key=lambda x: x.get("ev", 0), reverse=True):
        sig = (p["player"], p["market"])
        if sig in used:
            continue
        used.add(sig)
        legs.append(p)
        if len(legs) == BUILDER_LEGS:
            break

    if len(legs) != BUILDER_LEGS:
        return None

    dec = 1.0
    for l in legs:
        dec *= american_to_decimal(l["target_odds"])

    if not (BUILDER_MIN_DEC <= dec <= BUILDER_MAX_DEC):
        return None

    return {"legs": legs, "dec_odds": dec}


def normalize_to_candidates(event: dict, odds_data: dict) -> list[dict]:
    sport = event.get("sport_key")
    event_name = f"{event.get('away_team','')} @ {event.get('home_team','')}".strip(" @")

    by_key = {}

    for bm in odds_data.get("bookmakers", []):
        bk = (bm.get("key") or "").lower()
        for m in bm.get("markets", []):
            market_key = m.get("key")
            for o in m.get("outcomes", []):
                player = o.get("description") or o.get("name")
                side = o.get("name")
                line = o.get("point")
                price = o.get("price")

                if not player or not market_key or not side or not isinstance(price, int):
                    continue

                k = (market_key, player, line)
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
            odds_map = {b: books[b][side] for b in TARGET_BOOKS if b in books and side in books[b]}
            probs = (fair_over if side == "Over" else fair_under) if is_ou else implied.get(side, [])
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


def main() -> None:
    init_db()

    all_candidates = []
    blocked = {"gate": 0, "missing": 0, "window": 0, "books": 0, "tier": 0, "live": 0}
    event_calls = odds_calls = today_used = 0

    for sport in SPORTS:
        events = get_events(sport)
        event_calls += 1

        today = [e for e in events if e.get("commence_time") and is_today_et(e["commence_time"])]
        pre = []
        for e in today:
            if not is_pregame_ok(e["commence_time"]):
                blocked["live"] += 1
                continue
            pre.append(e)

        today_used += min(len(pre), EVENTS_PER_SPORT)
        markets = SPORT_MARKETS.get(sport, "")

        for ev in pre[:EVENTS_PER_SPORT]:
            try:
                odds = get_event_odds_multi_book(sport, ev["id"], markets)
                odds_calls += 1
            except Exception as e:
                print(f"Odds fetch failed: sport={sport} event_id={ev.get('id')} err={e}")
                continue

            all_candidates += normalize_to_candidates(ev, odds)

    approved_high_hit = []
    watchlist_pool = []

    for c in all_candidates:
        gate = quality_gates(c, STRICT_MODE, NHL_REQUIRE_CONFIRMED_GOALIE)
        if not gate.ok or c.get("p_model") is None:
            blocked["gate"] += 1
            continue

        # Need at least 2 target books posting this exact line to avoid weirdness
        if len(c["target_odds_by_book"]) < 2:
            blocked["missing"] += 1
            continue

        # choose best target odds among target books
        best = None
        for book, odds in c["target_odds_by_book"].items():
            if odds < MIN_ODDS or odds > MAX_ODDS:
                blocked["window"] += 1
                continue
            ev_val = expected_value(c["p_model"], odds)
            if best is None or ev_val > best[0]:
                best = (ev_val, book, odds)

        if not best:
            blocked["missing"] += 1
            continue

        c["ev"], c["target_book_used"], c["target_odds"] = best

        if c["books_count"] < MIN_BOOKS_FOR_CONSENSUS:
            blocked["books"] += 1
            continue

        p_implied = implied_prob_american(c["target_odds"])
        edge = c["p_model"] - p_implied
        c["edge"] = edge

        # Tier 1 HIGH-HIT gate
        if not (c["p_model"] >= MIN_P_FAIR and edge >= MIN_EDGE and c["ev"] >= MIN_EV_DOLLARS):
            watchlist_pool.append(c)
            blocked["tier"] += 1
            continue

        c["kelly_frac"] = min(kelly_fraction(c["p_model"], c["target_odds"]), KELLY_CAP)
        approved_high_hit.append(c)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    lines = [
        "✅ BEST MODE — All Sports (Pre-game only)",
        f"{now}",
        "",
    ]

    # HIGH-HIT SINGLES
    high_hit = select_top(approved_high_hit, MAX_SINGLES)
    if high_hit:
        lines += ["🟢 HIGH-HIT SINGLES (bankroll first)", ""]
        for p in high_hit:
            key = f"{p['event']}|{p['player']}|{p['market']}|{p['side']}|{p['target_odds']}"
            if was_sent_recently(key, COOLDOWN_MINUTES):
                continue
            mark_sent(key)
            lines += [
                f"• {format_pick(p)}",
                f"  {p['event']}",
                f"  Book={p['target_book_used']}",
                f"  {why_line(p)}",
                "",
            ]
    else:
        lines += ["ℹ️ No HIGH-HIT singles today.", ""]

    # BIG-MONEY BUILDER (only from HIGH-HIT pool)
    if ENABLE_PARLAYS:
        bb = build_big_builder(high_hit)
        if bb:
            lines += [
                f"💰 BIG-MONEY BUILDER ({BUILDER_LEGS} legs) — built ONLY from HIGH-HIT",
                f"Target decimal odds: {BUILDER_MIN_DEC:.1f}–{BUILDER_MAX_DEC:.1f} | This one ≈ {bb['dec_odds']:.2f}",
            ]
            for leg in bb["legs"]:
                lines.append(f"- {format_pick(leg)}")
            lines.append("Stake guide: 0.10–0.25% bankroll (small).")
            lines.append("")
        else:
            lines.append("ℹ️ No builder today (need enough HIGH-HIT legs within payout range).")
            lines.append("")

    # WATCHLIST (near-misses)
    watch = sorted(watchlist_pool, key=lambda x: x.get("ev", 0), reverse=True)[:WATCHLIST_COUNT]
    if watch:
        lines += ["🟡 WATCHLIST (near-misses — do NOT treat as picks)", ""]
        for p in watch:
            lines += [
                f"• {format_pick(p)}",
                f"  {p['event']}",
                f"  Book(best)={p['target_book_used']} | books={p['books_count']} | edge={p['edge']:+.3f} | EV=${p['ev']:.3f}/$1",
            ]

    lines += [
        "",
        f"API calls: events={event_calls}, event-odds={odds_calls} (today events used={today_used})",
        f"Blocked: gate={blocked['gate']}, missing={blocked['missing']}, window={blocked['window']}, "
        f"books={blocked['books']}, tier={blocked['tier']}, live_skip={blocked['live']}",
    ]

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
