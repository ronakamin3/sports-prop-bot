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
    MAX_SINGLES, COOLDOWN_MINUTES,
    TARGET_BOOKS, NHL_REQUIRE_CONFIRMED_GOALIE,
    ENABLE_PARLAYS, BUILDER_LEGS, BUILDER_MIN_DEC, BUILDER_MAX_DEC,
    LINE_TOLERANCE, REFRESH_BEFORE_SEND,
)

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
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "disable_web_page_preview": True}

    for delay in (0, 2, 5, 10):
        try:
            if delay:
                time.sleep(delay)
            r = requests.post(url, json=payload, timeout=30)
            if r.status_code == 429 or 500 <= r.status_code < 600:
                continue
            r.raise_for_status()
            return
        except Exception:
            continue

    print("⚠️ Telegram send failed. Message:")
    print(msg)


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


def market_label(market: str) -> str:
    # keep it short and bettable
    m = market.replace("_", " ")
    m = m.replace("player ", "")
    return m.title()


def format_pick(p: dict) -> str:
    # ✅ Always prints exact side + exact line if present
    if p.get("line") is None:
        return f"{p['player']} — {p['side']} ({p['target_odds']:+d})"
    return f"{p['player']} — {p['side']} {p['line']} ({p['target_odds']:+d})"


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


def build_big_builder(picks: list[dict]) -> dict | None:
    if len(picks) < BUILDER_LEGS:
        return None

    used = set()
    legs = []
    for p in sorted(picks, key=lambda x: x.get("ev", 0), reverse=True):
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
        dec *= american_to_decimal(int(l["target_odds"]))

    if not (BUILDER_MIN_DEC <= dec <= BUILDER_MAX_DEC):
        return None

    return {"legs": legs, "dec_odds": dec}


def within_tol(a, b, tol: float) -> bool:
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def normalize_event_odds(event: dict, odds_data: dict) -> dict:
    """
    Build a searchable index:
    idx[(market, player, side)] = list of entries
    entry = {book, line, price, has_pair, pair_price}
    """
    idx: dict[tuple, list[dict]] = {}

    for bm in odds_data.get("bookmakers", []):
        book = (bm.get("key") or "").lower()
        for m in bm.get("markets", []):
            market = m.get("key")
            outcomes = m.get("outcomes", [])

            # For O/U markets, we can compute no-vig per book if both sides exist at same line
            # Build a map: (line) -> {"Over": price, "Under": price}
            ou_by_line = {}
            for o in outcomes:
                side = o.get("name")
                line = o.get("point")
                price = o.get("price")
                player = o.get("description") or o.get("name")
                if not player or not market or not side or not isinstance(price, int):
                    continue

                if side in ("Over", "Under") and line is not None:
                    ou_by_line.setdefault((player, line), {})[side] = price

                idx.setdefault((market, player, side), []).append({
                    "book": book,
                    "line": line,
                    "price": price,
                })

            # attach no-vig info to O/U entries
            for (player, line), sides in ou_by_line.items():
                if "Over" in sides and "Under" in sides:
                    po = implied_prob_american(sides["Over"])
                    pu = implied_prob_american(sides["Under"])
                    fo = fair_prob_two_way_no_vig(po, pu)
                    # write fair probs to both sides for this book+line
                    for side in ("Over", "Under"):
                        key = (market, player, side)
                        for e in idx.get(key, []):
                            if e["book"] == book and e["line"] == line and e["price"] == sides[side]:
                                e["fair_prob_in_book"] = fo if side == "Over" else (1 - fo)

    return idx


def compute_consensus_prob(idx: dict, market: str, player: str, side: str, target_line, tol: float) -> tuple[float, int]:
    """
    Consensus p_model using entries whose line is within tolerance of target_line.
    Prefers no-vig fair probs if available for O/U.
    """
    entries = idx.get((market, player, side), [])
    probs = []
    for e in entries:
        line = e.get("line")
        if target_line is None:
            # for yes/no markets (no line), accept only if line is also None
            if line is not None:
                continue
        else:
            if not within_tol(line, target_line, tol):
                continue

        if "fair_prob_in_book" in e:
            probs.append(float(e["fair_prob_in_book"]))
        else:
            probs.append(implied_prob_american(int(e["price"])))

    if not probs:
        return None, 0

    return consensus_probability_from_probs(probs), len(probs)


def refresh_pick_odds(pick: dict) -> dict | None:
    """
    Re-fetch odds for the event and confirm we can still find the SAME bettable outcome
    on the SAME target book (or another target book if it moved).
    """
    sport = pick["sport"]
    event_id = pick["event_id"]
    markets = SPORT_MARKETS.get(sport, "")

    odds_data = get_event_odds_multi_book(sport, event_id, markets)
    idx = normalize_event_odds({"sport_key": sport}, odds_data)

    market = pick["market"]
    player = pick["player"]
    side = pick["side"]
    line = pick.get("line")

    # find best available odds on target books for this exact side (closest line to original)
    best = None
    for e in idx.get((market, player, side), []):
        if e["book"] not in TARGET_BOOKS:
            continue
        if line is None:
            if e.get("line") is not None:
                continue
            line_ok = True
        else:
            line_ok = within_tol(e.get("line"), line, 0.0001)  # exact line only at refresh
        if not line_ok:
            continue

        odds_val = int(e["price"])
        if odds_val < MIN_ODDS or odds_val > MAX_ODDS:
            continue

        # compute consensus prob around this exact line (line-tolerance for consensus)
        p_model, books_count = compute_consensus_prob(idx, market, player, side, e.get("line"), LINE_TOLERANCE)
        if p_model is None:
            continue

        ev_val = expected_value(p_model, odds_val)
        if best is None or ev_val > best[0]:
            best = (ev_val, e["book"], odds_val, e.get("line"), p_model, books_count)

    if not best:
        return None

    ev_val, book, odds_val, exact_line, p_model, books_count = best
    out = dict(pick)
    out.update({
        "target_book_used": book,
        "target_odds": odds_val,
        "line": exact_line,
        "p_model": p_model,
        "books_count": books_count,
        "ev": ev_val,
    })
    out["kelly_frac"] = min(kelly_fraction(out["p_model"], out["target_odds"]), KELLY_CAP)
    return out


def main() -> None:
    init_db()

    blocked = {"gate": 0, "missing": 0, "window": 0, "books": 0, "tier": 0, "live_skip": 0, "api_fail": 0}
    event_calls = odds_calls = today_used = 0
    approved: list[dict] = []

    for sport in SPORTS:
        try:
            events = get_events(sport)
            event_calls += 1
        except Exception as e:
            print(f"Events fetch failed sport={sport}: {e}")
            blocked["api_fail"] += 1
            continue

        today = [e for e in events if e.get("commence_time") and is_today_et(e["commence_time"])]

        pre = []
        for e in today:
            if not is_pregame_ok(e["commence_time"]):
                blocked["live_skip"] += 1
                continue
            pre.append(e)

        today_used += min(len(pre), EVENTS_PER_SPORT)

        markets = SPORT_MARKETS.get(sport, "")
        for ev in pre[:EVENTS_PER_SPORT]:
            try:
                odds_data = get_event_odds_multi_book(sport, ev["id"], markets)
                odds_calls += 1
            except Exception as e:
                print(f"Odds fetch failed sport={sport} event_id={ev.get('id')}: {e}")
                blocked["api_fail"] += 1
                continue

            idx = normalize_event_odds(ev, odds_data)

            # Iterate over all (market,player,side) keys, but only if at least one target book has an offer
            for (market, player, side), entries in idx.items():
                # choose best “execution” offer among target books
                best_exec = None
                for e in entries:
                    if e["book"] not in TARGET_BOOKS:
                        continue
                    odds_val = int(e["price"])
                    if odds_val < MIN_ODDS or odds_val > MAX_ODDS:
                        continue

                    line = e.get("line")
                    # compute consensus around this line (tolerant)
                    p_model, books_count = compute_consensus_prob(idx, market, player, side, line, LINE_TOLERANCE)
                    if p_model is None:
                        continue

                    ev_val = expected_value(p_model, odds_val)
                    if best_exec is None or ev_val > best_exec[0]:
                        best_exec = (ev_val, e["book"], odds_val, line, p_model, books_count)

                if not best_exec:
                    continue

                ev_val, book, odds_val, line, p_model, books_count = best_exec

                cand = {
                    "sport": sport,
                    "event_id": ev["id"],
                    "event": f"{ev.get('away_team','')} @ {ev.get('home_team','')}".strip(" @"),
                    "market": market,
                    "player": player,
                    "side": side,
                    "line": line,
                    "p_model": p_model,
                    "books_count": books_count,
                    "target_book_used": book,
                    "target_odds": odds_val,
                    "ev": ev_val,
                    "goalie_confirmed": None,
                }

                gate = quality_gates(cand, STRICT_MODE, NHL_REQUIRE_CONFIRMED_GOALIE)
                if not gate.ok or cand.get("p_model") is None:
                    blocked["gate"] += 1
                    continue

                # ✅ Require exact line to be present for bettable clarity (yes/no markets can be None)
                # If it’s an Over/Under style market and line is None, skip.
                if cand["side"] in ("Over", "Under") and cand.get("line") is None:
                    blocked["missing"] += 1
                    continue

                if cand["books_count"] < MIN_BOOKS_FOR_CONSENSUS:
                    blocked["books"] += 1
                    continue

                imp = implied_prob_american(cand["target_odds"])
                edge = cand["p_model"] - imp
                cand["edge"] = edge

                if not (cand["p_model"] >= MIN_P_FAIR and edge >= MIN_EDGE and cand["ev"] >= MIN_EV_DOLLARS):
                    blocked["tier"] += 1
                    continue

                cand["kelly_frac"] = min(kelly_fraction(cand["p_model"], cand["target_odds"]), KELLY_CAP)
                approved.append(cand)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    if not approved:
        send_telegram("\n".join([
            "ℹ️ BEST MODE — All Sports (Pre-game only)",
            f"{now}",
            "No A+ picks today. Best move is no bet.",
            "",
            f"API calls: events={event_calls}, event-odds={odds_calls} (today events used={today_used})",
            f"Blocked: gate={blocked['gate']}, missing={blocked['missing']}, window={blocked['window']}, "
            f"books={blocked['books']}, tier={blocked['tier']}, live_skip={blocked['live_skip']}, api_fail={blocked['api_fail']}",
        ]))
        return

    picks = select_top(approved, MAX_SINGLES)

    # ✅ refresh right before send (prevents “wrong odds” from line movement)
    final_picks = []
    for p in picks:
        if REFRESH_BEFORE_SEND:
            rp = refresh_pick_odds(p)
            if rp is None:
                continue
            p = rp
        final_picks.append(p)

    if not final_picks:
        # everything moved or disappeared
        send_telegram("ℹ️ BEST MODE — Picks moved/expired at refresh. No bet.")
        return

    lines = [
        "✅ BEST MODE — A+ PICKS ONLY (Exact Line + Refreshed)",
        f"{now}",
        "",
    ]

    sent = []
    for p in final_picks:
        key = f"{p['event']}|{p['player']}|{p['market']}|{p['side']}|{p.get('line')}|{p['target_book_used']}|{p['target_odds']}"
        if was_sent_recently(key, COOLDOWN_MINUTES):
            continue
        mark_sent(key)
        sent.append(p)

        lines += [
            f"• {format_pick(p)}",
            f"  {p['event']}",
            f"  Market: {market_label(p['market'])} | Book={p['target_book_used']}",
            f"  {why_line(p)}",
            "",
        ]

    if not sent:
        return

    if ENABLE_PARLAYS and len(sent) >= BUILDER_LEGS:
        bb = build_big_builder(sent)
        if bb:
            lines += [
                f"💰 BIG-MONEY BUILDER ({BUILDER_LEGS} legs) — built only from A+ singles",
                f"Total decimal ≈ {bb['dec_odds']:.2f} (target {BUILDER_MIN_DEC:.1f}–{BUILDER_MAX_DEC:.1f})",
            ]
            for leg in bb["legs"]:
                lines.append(f"- {format_pick(leg)}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()