from __future__ import annotations

import time
import requests
from datetime import datetime, timezone, timedelta
from dateutil import tz, parser

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    SPORTS, EVENTS_PER_SPORT, PREGAME_BUFFER_MINUTES,
    STRICT_MODE, MIN_BOOKS_FOR_CONSENSUS, MIN_P_FAIR, MIN_EDGE, MIN_EV_DOLLARS,
    MIN_ODDS, MAX_ODDS, KELLY_CAP, MAX_SINGLES, COOLDOWN_MINUTES,
    TARGET_BOOKS, NHL_REQUIRE_CONFIRMED_GOALIE,
    ENABLE_PARLAYS, BUILDER_LEGS, BUILDER_MIN_DEC, BUILDER_MAX_DEC,
    LINE_TOLERANCE, VERIFY_BEFORE_SEND, MAX_VERIFY_EVENTS, MAX_ODDS_MOVE_ABS,
    MAX_EDGE_CAP, ONE_PICK_PER_GAME,
    NHL_SHOTS_UNDER_MIN_BOOKS, NHL_LINE_TOLERANCE,
    LIVE_ENABLE, LIVE_MAX_EVENTS_PER_SPORT, LIVE_LOOKBACK_MINUTES, LIVE_MARKETS,
    LIVE_MIN_BOOKS, LIVE_MIN_EDGE, LIVE_MIN_EV_DOLLARS,
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


# Player-prop heavy sports
SPORT_MARKETS_PREGAME = {
    "basketball_nba": "player_points,player_threes,player_points_rebounds_assists",
    "americanfootball_nfl": "player_receptions,player_reception_yds,player_pass_yds,player_anytime_td",
    "baseball_mlb": "pitcher_strikeouts,batter_hits,batter_total_bases,batter_home_runs",
    "icehockey_nhl": "player_shots_on_goal,player_points,player_goals,player_goal_scorer_anytime",
    "soccer_epl": "player_shots,player_shots_on_target,player_goal_scorer_anytime,player_assists",
    "soccer_usa_mls": "player_shots,player_shots_on_target,player_goal_scorer_anytime,player_assists",
}

# College: team markets only (as you requested)
SPORT_MARKETS_COLLEGE = {
    "americanfootball_ncaaf": "h2h,spreads,totals",
    "basketball_ncaab": "h2h,spreads,totals",
}

TEAM_MARKETS_DEFAULT = "h2h,spreads,totals"


def send_telegram(msg: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "disable_web_page_preview": True}
    for delay in (0, 2, 5, 10):
        try:
            if delay:
                time.sleep(delay)
            r = requests.post(url, json=payload, timeout=35)
            if r.status_code == 429 or 500 <= r.status_code < 600:
                continue
            r.raise_for_status()
            return
        except Exception:
            continue
    print("⚠️ Telegram send failed:\n", msg)


def is_today_et(commence_time: str) -> bool:
    eastern = tz.gettz("America/New_York")
    today_et = datetime.now(tz=eastern).date()
    dt = parser.isoparse(commence_time)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(eastern).date() == today_et


def parse_time_utc(commence_time: str) -> datetime:
    dt = parser.isoparse(commence_time)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_pregame_ok(commence_time: str) -> bool:
    dt = parse_time_utc(commence_time)
    return dt >= datetime.now(timezone.utc) + timedelta(minutes=PREGAME_BUFFER_MINUTES)


def is_live_ok(commence_time: str) -> bool:
    # "Live" window = started but not too old (we don’t know if finished)
    start = parse_time_utc(commence_time)
    now = datetime.now(timezone.utc)
    if start > now:
        return False
    return (now - start) <= timedelta(minutes=LIVE_LOOKBACK_MINUTES)


def market_label(market_key: str) -> str:
    return market_key.replace("_", " ").title()


def bet_label(side: str, line) -> str:
    if line is None:
        return side
    return f"{side} {line}"


def format_pick(p: dict) -> str:
    return f"{p['player']} — {bet_label(p['side'], p.get('line'))} {market_label(p['market'])} ({p['target_odds']:+d})"


def why_line(p: dict) -> str:
    imp = implied_prob_american(p["target_odds"])
    edge = p["p_model"] - imp
    return (
        f"p_fair={p['p_model']:.3f} vs implied={imp:.3f} "
        f"(edge={edge:+.3f}), EV=${p['ev']:.3f}/$1, books={p['books_count']}, Kelly~{p['kelly_frac']*100:.2f}%"
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
        sig = (p["event"], p["market"], p["player"], p["side"], p.get("line"))
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
    return abs(float(a) - float(b)) <= tol


def normalize_event_index(odds_data: dict) -> dict:
    """
    idx[(market, participant, side)] -> list of {book, line, price, fair_prob_in_book?}
    participant is player for props OR team name for team markets.
    """
    idx = {}
    for bm in odds_data.get("bookmakers", []):
        book = (bm.get("key") or "").lower()
        for m in bm.get("markets", []):
            market = m.get("key")
            outcomes = m.get("outcomes", [])

            ou_pairs = {}
            for o in outcomes:
                participant = o.get("description") or o.get("name")
                side = o.get("name")  # Over/Under OR team name OR Yes/No
                line = o.get("point")
                price = o.get("price")
                if not participant or not market or not side or not isinstance(price, int):
                    continue

                idx.setdefault((market, participant, side), []).append({"book": book, "line": line, "price": price})

                if side in ("Over", "Under") and line is not None:
                    ou_pairs.setdefault((participant, float(line)), {})[side] = price

            for (participant, line), sides in ou_pairs.items():
                if "Over" in sides and "Under" in sides:
                    po = implied_prob_american(sides["Over"])
                    pu = implied_prob_american(sides["Under"])
                    fo = fair_prob_two_way_no_vig(po, pu)
                    for side in ("Over", "Under"):
                        key = (market, participant, side)
                        for e in idx.get(key, []):
                            if e["book"] == book and e["line"] is not None and float(e["line"]) == float(line):
                                e["fair_prob_in_book"] = fo if side == "Over" else (1 - fo)
    return idx


def consensus_prob(idx: dict, market: str, participant: str, side: str, target_line, tol: float):
    entries = idx.get((market, participant, side), [])
    probs = []
    for e in entries:
        line = e.get("line")
        if target_line is None:
            if line is not None:
                continue
        else:
            if line is None or not within_tol(line, target_line, tol):
                continue
        probs.append(float(e.get("fair_prob_in_book")) if "fair_prob_in_book" in e else implied_prob_american(int(e["price"])))
    if not probs:
        return None, 0
    return consensus_probability_from_probs(probs), len(probs)


def verify_refresh(picks: list[dict], blocked: dict) -> list[dict]:
    if not picks or not VERIFY_BEFORE_SEND:
        return picks

    groups = {}
    for p in picks:
        groups.setdefault((p["sport"], p["event_id"]), []).append(p)

    verified = []
    calls = 0

    for (sport, event_id), plist in groups.items():
        if calls >= MAX_VERIFY_EVENTS:
            verified += plist
            continue
        markets = TEAM_MARKETS_DEFAULT if plist[0].get("is_live") else get_pregame_markets(sport)
        try:
            odds = get_event_odds_multi_book(sport, event_id, markets)
            calls += 1
        except Exception:
            verified += plist
            continue

        idx = normalize_event_index(odds)

        for p in plist:
            best = None
            for e in idx.get((p["market"], p["player"], p["side"]), []):
                if e["book"] not in TARGET_BOOKS:
                    continue

                # exact line for betting
                if p.get("line") is None:
                    if e.get("line") is not None:
                        continue
                else:
                    if e.get("line") is None or float(e["line"]) != float(p["line"]):
                        continue

                odds_val = int(e["price"])
                if odds_val < MIN_ODDS or odds_val > MAX_ODDS:
                    continue

                tol = LINE_TOLERANCE
                if sport == "icehockey_nhl" and p["market"] == "player_shots_on_goal":
                    tol = NHL_LINE_TOLERANCE

                p_model, books_count = consensus_prob(idx, p["market"], p["player"], p["side"], p.get("line"), tol)
                if p_model is None:
                    continue

                ev_val = expected_value(p_model, odds_val)
                if best is None or ev_val > best[0]:
                    best = (ev_val, e["book"], odds_val, p_model, books_count)

            if not best:
                continue

            ev_val, book, odds_val, p_model, books_count = best

            if abs(int(odds_val) - int(p["target_odds"])) > MAX_ODDS_MOVE_ABS:
                blocked["moved"] = blocked.get("moved", 0) + 1
                continue

            p["target_book_used"] = book
            p["target_odds"] = int(odds_val)
            p["p_model"] = float(p_model)
            p["books_count"] = int(books_count)
            p["ev"] = float(ev_val)
            p["kelly_frac"] = min(kelly_fraction(p["p_model"], p["target_odds"]), KELLY_CAP)
            verified.append(p)

    return verified


def get_pregame_markets(sport: str) -> str:
    # College = teams only. Others = props where we have them; fallback to team markets.
    if sport in SPORT_MARKETS_COLLEGE:
        return SPORT_MARKETS_COLLEGE[sport]
    return SPORT_MARKETS_PREGAME.get(sport, TEAM_MARKETS_DEFAULT)


def main() -> None:
    init_db()

    blocked = {"gate": 0, "missing": 0, "window": 0, "books": 0, "tier": 0, "live_skip": 0, "api_fail": 0}
    event_calls = odds_calls = today_used = 0

    approved_pregame: list[dict] = []
    approved_live: list[dict] = []

    for sport in SPORTS:
        try:
            events = get_events(sport)  # includes live + pre-match per Odds API events endpoint docs  [oai_citation:0‡Postman](https://www.postman.com/odds-api/the-odds-api-workspace/documentation/my4qrii/the-odds-api?utm_source=chatgpt.com)
            event_calls += 1
        except Exception as e:
            print(f"Events fetch failed sport={sport}: {e}")
            blocked["api_fail"] += 1
            continue

        today_events = [e for e in events if e.get("commence_time") and is_today_et(e["commence_time"])]

        pre = []
        live = []
        for e in today_events:
            if is_pregame_ok(e["commence_time"]):
                pre.append(e)
            elif LIVE_ENABLE and is_live_ok(e["commence_time"]):
                live.append(e)

        today_used += min(len(pre), EVENTS_PER_SPORT)

        # --- PRE-GAME ---
        pre_markets = get_pregame_markets(sport)
        for ev in pre[:EVENTS_PER_SPORT]:
            try:
                odds = get_event_odds_multi_book(sport, ev["id"], pre_markets)
                odds_calls += 1
            except Exception as e:
                print(f"Odds fetch failed pregame sport={sport} event_id={ev.get('id')}: {e}")
                blocked["api_fail"] += 1
                continue

            idx = normalize_event_index(odds)
            event_name = f"{ev.get('away_team','')} @ {ev.get('home_team','')}".strip(" @")

            for (market, participant, side), entries in idx.items():
                # execution best on target books
                best_exec = None
                for e in entries:
                    if e["book"] not in TARGET_BOOKS:
                        continue
                    odds_val = int(e["price"])
                    if odds_val < MIN_ODDS or odds_val > MAX_ODDS:
                        blocked["window"] += 1
                        continue

                    line = e.get("line")
                    tol = LINE_TOLERANCE
                    if sport == "icehockey_nhl" and market == "player_shots_on_goal":
                        tol = NHL_LINE_TOLERANCE

                    p_model, books_count = consensus_prob(idx, market, participant, side, line, tol)
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
                    "event": event_name,
                    "market": market,
                    "player": participant,
                    "side": side,
                    "line": line if line is None else float(line),
                    "p_model": float(p_model),
                    "books_count": int(books_count),
                    "target_book_used": book,
                    "target_odds": int(odds_val),
                    "ev": float(ev_val),
                    "is_live": False,
                }

                gate = quality_gates(cand, STRICT_MODE, NHL_REQUIRE_CONFIRMED_GOALIE)
                if not gate.ok:
                    blocked["gate"] += 1
                    continue

                # clarity: Over/Under needs a line
                if cand["side"] in ("Over", "Under") and cand.get("line") is None:
                    blocked["missing"] += 1
                    continue

                if cand["books_count"] < MIN_BOOKS_FOR_CONSENSUS:
                    blocked["books"] += 1
                    continue

                imp = implied_prob_american(cand["target_odds"])
                edge = cand["p_model"] - imp

                # global sanity cap (all sports)
                if edge > MAX_EDGE_CAP:
                    blocked["tier"] += 1
                    continue

                # NHL shots unders stricter
                if sport == "icehockey_nhl" and market == "player_shots_on_goal" and cand["side"] == "Under":
                    if cand["books_count"] < NHL_SHOTS_UNDER_MIN_BOOKS:
                        blocked["books"] += 1
                        continue

                if not (cand["p_model"] >= MIN_P_FAIR and edge >= MIN_EDGE and cand["ev"] >= MIN_EV_DOLLARS):
                    blocked["tier"] += 1
                    continue

                cand["kelly_frac"] = min(kelly_fraction(cand["p_model"], cand["target_odds"]), KELLY_CAP)
                approved_pregame.append(cand)

        # --- LIVE (team markets only, strict & low volume) ---
        if LIVE_ENABLE and live:
            live_markets = LIVE_MARKETS  # h2h,spreads,totals
            for ev in live[:LIVE_MAX_EVENTS_PER_SPORT]:
                try:
                    odds = get_event_odds_multi_book(sport, ev["id"], live_markets)
                    odds_calls += 1
                except Exception as e:
                    print(f"Odds fetch failed LIVE sport={sport} event_id={ev.get('id')}: {e}")
                    blocked["api_fail"] += 1
                    continue

                idx = normalize_event_index(odds)
                event_name = f"{ev.get('away_team','')} @ {ev.get('home_team','')}".strip(" @")

                for (market, participant, side), entries in idx.items():
                    # only team markets for live
                    if market not in ("h2h", "spreads", "totals"):
                        continue

                    best_exec = None
                    for e in entries:
                        if e["book"] not in TARGET_BOOKS:
                            continue
                        odds_val = int(e["price"])
                        if odds_val < MIN_ODDS or odds_val > MAX_ODDS:
                            continue

                        line = e.get("line")
                        p_model, books_count = consensus_prob(idx, market, participant, side, line, 0.5)
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
                        "event": event_name,
                        "market": market,
                        "player": participant,
                        "side": side,
                        "line": None if line is None else float(line),
                        "p_model": float(p_model),
                        "books_count": int(books_count),
                        "target_book_used": book,
                        "target_odds": int(odds_val),
                        "ev": float(ev_val),
                        "is_live": True,
                    }

                    # live: require more book agreement
                    if cand["books_count"] < LIVE_MIN_BOOKS:
                        continue

                    imp = implied_prob_american(cand["target_odds"])
                    edge = cand["p_model"] - imp

                    if edge > MAX_EDGE_CAP:
                        continue
                    if edge < LIVE_MIN_EDGE or cand["ev"] < LIVE_MIN_EV_DOLLARS:
                        continue

                    cand["kelly_frac"] = min(kelly_fraction(cand["p_model"], cand["target_odds"]), KELLY_CAP)
                    approved_live.append(cand)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    picks = select_top(approved_pregame, MAX_SINGLES)

    # one pick per game (all sports)
    if ONE_PICK_PER_GAME:
        seen = set()
        filtered = []
        for p in picks:
            if p["event"] in seen:
                continue
            seen.add(p["event"])
            filtered.append(p)
        picks = filtered

    # verify before send
    picks = verify_refresh(picks, blocked)

    # live: pick at most 1 best live signal
    live_pick = None
    if approved_live:
        best_live = sorted(approved_live, key=lambda x: x.get("ev", 0), reverse=True)[0]
        live_pick = best_live
        # verify live too
        live_pick_list = verify_refresh([live_pick], blocked)
        live_pick = live_pick_list[0] if live_pick_list else None

    if not picks and not live_pick:
        send_telegram("\n".join([
            "ℹ️ BEST MODE — All Sports (Pre-game + Live team picks)",
            f"{now}",
            "No A+ picks right now. Best move is no bet.",
            "",
            f"API calls: events={event_calls}, event-odds={odds_calls} (today events used={today_used})",
            f"Blocked: gate={blocked['gate']}, missing={blocked['missing']}, window={blocked['window']}, "
            f"books={blocked['books']}, tier={blocked['tier']}, live_skip={blocked['live_skip']}, api_fail={blocked['api_fail']}, moved={blocked.get('moved',0)}",
        ]))
        return

    lines = [
        "✅ BEST MODE — A+ PICKS ONLY (All Sports)",
        f"{now}",
        "",
    ]

    if picks:
        lines += ["🟢 RECOMMENDED SINGLES (pre-game)", "Stake guide: ~0.75–1.0% bankroll each", ""]
        for p in picks:
            key = f"{p['event']}|{p['market']}|{p['player']}|{p['side']}|{p.get('line')}|{p['target_book_used']}|{p['target_odds']}"
            if was_sent_recently(key, COOLDOWN_MINUTES):
                continue
            mark_sent(key)
            lines += [
                f"• {format_pick(p)}",
                f"  {p['event']} | Book={p['target_book_used']}",
                f"  {why_line(p)}",
                "",
            ]

    if live_pick:
        lines += [
            "🟠 LIVE TEAM PICK (high variance)",
            "Stake guide: 0.25–0.50% bankroll (smaller)",
            "",
            f"• {format_pick(live_pick)}",
            f"  {live_pick['event']} | Book={live_pick['target_book_used']}",
            f"  {why_line(live_pick)}",
            "",
        ]

    if ENABLE_PARLAYS and len(picks) >= BUILDER_LEGS:
        bb = build_big_builder(picks)
        if bb:
            lines += [
                f"💰 3-LEG BUILDER (from recommended singles)",
                f"Total decimal ≈ {bb['dec_odds']:.2f} (target {BUILDER_MIN_DEC:.1f}–{BUILDER_MAX_DEC:.1f})",
            ]
            for leg in bb["legs"]:
                lines.append(f"- {format_pick(leg)}")
            lines.append("Stake guide: 0.10–0.25% bankroll (small).")
            lines.append("")

    lines += [
        f"API calls: events={event_calls}, event-odds={odds_calls} (today events used={today_used})",
        f"Blocked: gate={blocked['gate']}, missing={blocked['missing']}, window={blocked['window']}, "
        f"books={blocked['books']}, tier={blocked['tier']}, live_skip={blocked['live_skip']}, api_fail={blocked['api_fail']}, moved={blocked.get('moved',0)}",
    ]

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()