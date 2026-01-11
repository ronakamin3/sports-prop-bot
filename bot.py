from __future__ import annotations

import time
import requests
from datetime import datetime, timezone, timedelta
from dateutil import tz, parser

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    SPORTS, EVENTS_PER_SPORT, PREGAME_BUFFER_MINUTES,
    TARGET_BOOKS, COOLDOWN_MINUTES,
    MAX_EDGE_CAP, ONE_PICK_PER_GAME,
    VERIFY_BEFORE_SEND, MAX_VERIFY_EVENTS, MAX_ODDS_MOVE_ABS,
    LINE_TOLERANCE,

    SHARP_MAX_SINGLES, SHARP_MIN_BOOKS, SHARP_MIN_P, SHARP_MIN_EDGE, SHARP_MIN_EV, SHARP_MIN_ODDS, SHARP_MAX_ODDS,
    ENABLE_SHARP_BUILDER, BUILDER_LEGS, BUILDER_MIN_DEC, BUILDER_MAX_DEC,

    ENABLE_LOTTO_3LEG, LOTTO_LEGS, LOTTO_MIN_ODDS, LOTTO_MAX_ODDS, LOTTO_MIN_BOOKS, LOTTO_MIN_EDGE, LOTTO_MIN_EV, LOTTO_MAX_TOTAL_DEC,

    ENABLE_PLUS_SHOTS, PLUS_MAX_PICKS, PLUS_MIN_ODDS, PLUS_MAX_ODDS, PLUS_MIN_BOOKS, PLUS_MIN_EDGE, PLUS_MIN_EV,

    ENABLE_HIGHVAR_3LEG, HIGHVAR_LEGS, HIGHVAR_MIN_ODDS, HIGHVAR_MAX_ODDS, HIGHVAR_MIN_TOTAL_DEC, HIGHVAR_MAX_TOTAL_DEC,
)

from odds_provider import get_events, get_event_odds_multi_book
from storage import init_db, was_sent_recently, mark_sent
from probability import implied_prob_american, expected_value, kelly_fraction, consensus_probability_from_probs, fair_prob_two_way_no_vig


# HARD DISABLE NHL (safety)
SPORTS = [s for s in SPORTS if s != "icehockey_nhl"]


SPORT_MARKETS_PREGAME = {
    "basketball_nba": "player_points,player_threes,player_points_rebounds_assists,spreads,h2h,totals",
    "americanfootball_nfl": "player_receptions,player_reception_yds,player_pass_yds,player_anytime_td,spreads,h2h,totals",
    "baseball_mlb": "pitcher_strikeouts,batter_hits,batter_total_bases,batter_home_runs,spreads,h2h,totals",
    "soccer_epl": "player_shots,player_shots_on_target,player_goal_scorer_anytime,player_assists,spreads,h2h,totals",
    "soccer_usa_mls": "player_shots,player_shots_on_target,player_goal_scorer_anytime,player_assists,spreads,h2h,totals",
    "americanfootball_ncaaf": "h2h,spreads,totals",
    "basketball_ncaab": "h2h,spreads,totals",
}


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
    print("⚠️ Telegram send failed")


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


def american_to_decimal(odds: int) -> float:
    if odds > 0:
        return 1.0 + (odds / 100.0)
    return 1.0 + (100.0 / abs(odds))


def within_tol(a, b, tol: float) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def normalize_event_index(odds_data: dict) -> dict:
    idx = {}
    for bm in odds_data.get("bookmakers", []):
        book = (bm.get("key") or "").lower()
        for m in bm.get("markets", []):
            market = m.get("key")
            outcomes = m.get("outcomes", [])
            ou_pairs = {}
            for o in outcomes:
                participant = o.get("description") or o.get("name")
                side = o.get("name")
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

        markets = SPORT_MARKETS_PREGAME.get(sport, "h2h,spreads,totals")
        try:
            odds = get_event_odds_multi_book(sport, event_id, markets)
            calls += 1
        except Exception:
            blocked["api_fail"] += 1
            verified += plist
            continue

        idx = normalize_event_index(odds)

        for p in plist:
            best = None
            for e in idx.get((p["market"], p["player"], p["side"]), []):
                if e["book"] not in TARGET_BOOKS:
                    continue
                if p.get("line") is None:
                    if e.get("line") is not None:
                        continue
                else:
                    if e.get("line") is None or float(e["line"]) != float(p["line"]):
                        continue

                odds_val = int(e["price"])
                if odds_val < p["min_odds"] or odds_val > p["max_odds"]:
                    continue

                p_model, books_count = consensus_prob(idx, p["market"], p["player"], p["side"], p.get("line"), LINE_TOLERANCE)
                if p_model is None:
                    continue
                ev_val = expected_value(p_model, odds_val)
                if best is None or ev_val > best[0]:
                    best = (ev_val, e["book"], odds_val, p_model, books_count)

            if not best:
                continue

            ev_val, book, odds_val, p_model, books_count = best

            if abs(int(odds_val) - int(p["target_odds"])) > MAX_ODDS_MOVE_ABS:
                blocked["moved"] += 1
                continue

            p["target_book_used"] = book
            p["target_odds"] = int(odds_val)
            p["p_model"] = float(p_model)
            p["books_count"] = int(books_count)
            p["ev"] = float(ev_val)
            p["kelly_frac"] = min(kelly_fraction(p["p_model"], p["target_odds"]), 0.01)
            verified.append(p)

    return verified


def pick_score(p: dict) -> float:
    imp = implied_prob_american(p["target_odds"])
    edge = p["p_model"] - imp
    return (p["ev"] * 100.0) + (edge * 50.0) + (min(p["books_count"], 10) * 0.4)


def select_top_unique_game(picks: list[dict], n: int) -> list[dict]:
    out = []
    seen = set()
    for p in sorted(picks, key=pick_score, reverse=True):
        if ONE_PICK_PER_GAME and p["event"] in seen:
            continue
        seen.add(p["event"])
        out.append(p)
        if len(out) >= n:
            break
    return out


def build_parlay(picks: list[dict], legs: int, min_total_dec: float, max_total_dec: float) -> dict | None:
    if len(picks) < legs:
        return None
    chosen = []
    used_events = set()
    total_dec = 1.0
    for p in sorted(picks, key=pick_score, reverse=True):
        if ONE_PICK_PER_GAME and p["event"] in used_events:
            continue
        used_events.add(p["event"])
        chosen.append(p)
        total_dec *= american_to_decimal(int(p["target_odds"]))
        if len(chosen) == legs:
            break
    if len(chosen) != legs:
        return None
    if not (min_total_dec <= total_dec <= max_total_dec):
        return None
    return {"legs": chosen, "dec": total_dec}


def format_pick(p: dict) -> str:
    odds = f"({p['target_odds']:+d})"
    line = "" if p.get("line") is None else f" {p['line']}"
    return f"{p['player']} — {p['market']} — {p['side']}{line} {odds}"


def why_line(p: dict) -> str:
    imp = implied_prob_american(p["target_odds"])
    edge = p["p_model"] - imp
    return (
        f"WHY: p_fair={p['p_model']:.3f} vs implied={imp:.3f} "
        f"(edge={edge:+.3f}), EV=${p['ev']:.3f}/$1, books={p['books_count']}, Kelly~{p['kelly_frac']*100:.2f}%"
    )


def main() -> None:
    init_db()
    blocked = {"window": 0, "books": 0, "tier": 0, "api_fail": 0, "moved": 0}
    event_calls = odds_calls = today_used = 0

    sharp_pool = []
    lotto_pool = []
    plus_pool = []
    highvar_pool = []

    for sport in SPORTS:
        try:
            events = get_events(sport)
            event_calls += 1
        except Exception:
            blocked["api_fail"] += 1
            continue

        today_events = [e for e in events if e.get("commence_time") and is_today_et(e["commence_time"])]
        pre = [e for e in today_events if is_pregame_ok(e["commence_time"])]
        today_used += min(len(pre), EVENTS_PER_SPORT)

        markets = SPORT_MARKETS_PREGAME.get(sport, "h2h,spreads,totals")

        for ev in pre[:EVENTS_PER_SPORT]:
            try:
                odds = get_event_odds_multi_book(sport, ev["id"], markets)
                odds_calls += 1
            except Exception:
                blocked["api_fail"] += 1
                continue

            idx = normalize_event_index(odds)
            event_name = f"{ev.get('away_team','')} @ {ev.get('home_team','')}".strip(" @")

            for (market, participant, side), entries in idx.items():
                best_exec = None
                for e in entries:
                    if e["book"] not in TARGET_BOOKS:
                        continue

                    odds_val = int(e["price"])
                    line = e.get("line")

                    p_model, books_count = consensus_prob(idx, market, participant, side, line, LINE_TOLERANCE)
                    if p_model is None:
                        continue

                    ev_val = expected_value(p_model, odds_val)
                    if best_exec is None or ev_val > best_exec[0]:
                        best_exec = (ev_val, e["book"], odds_val, line, p_model, books_count)

                if not best_exec:
                    continue

                ev_val, book, odds_val, line, p_model, books_count = best_exec
                imp = implied_prob_american(odds_val)
                edge = p_model - imp

                # sanity cap to avoid “too good to be true”
                if edge > MAX_EDGE_CAP:
                    blocked["tier"] += 1
                    continue

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
                    "kelly_frac": min(kelly_fraction(p_model, odds_val), 0.01),
                }

                # require a line for OU
                if cand["side"] in ("Over", "Under") and cand["line"] is None:
                    continue

                # --- SHARP gates (steady) ---
                if SHARP_MIN_ODDS <= odds_val <= SHARP_MAX_ODDS and books_count >= SHARP_MIN_BOOKS and cand["p_model"] >= SHARP_MIN_P and edge >= SHARP_MIN_EDGE and cand["ev"] >= SHARP_MIN_EV:
                    s = dict(cand)
                    s["min_odds"] = SHARP_MIN_ODDS
                    s["max_odds"] = SHARP_MAX_ODDS
                    sharp_pool.append(s)

                # --- LOTTO pool ---
                if ENABLE_LOTTO_3LEG:
                    if LOTTO_MIN_ODDS <= odds_val <= LOTTO_MAX_ODDS and books_count >= LOTTO_MIN_BOOKS and edge >= LOTTO_MIN_EDGE and cand["ev"] >= LOTTO_MIN_EV:
                        l = dict(cand)
                        l["min_odds"] = LOTTO_MIN_ODDS
                        l["max_odds"] = LOTTO_MAX_ODDS
                        lotto_pool.append(l)

                # --- PLUS-MONEY bigger win pool ---
                if ENABLE_PLUS_SHOTS:
                    if PLUS_MIN_ODDS <= odds_val <= PLUS_MAX_ODDS and books_count >= PLUS_MIN_BOOKS and edge >= PLUS_MIN_EDGE and cand["ev"] >= PLUS_MIN_EV:
                        p = dict(cand)
                        p["min_odds"] = PLUS_MIN_ODDS
                        p["max_odds"] = PLUS_MAX_ODDS
                        plus_pool.append(p)

                # --- HIGH-VARIANCE parlay candidates ---
                if ENABLE_HIGHVAR_3LEG:
                    if HIGHVAR_MIN_ODDS <= odds_val <= HIGHVAR_MAX_ODDS and books_count >= max(PLUS_MIN_BOOKS, 4) and edge >= max(PLUS_MIN_EDGE, 0.016) and cand["ev"] >= max(PLUS_MIN_EV, 0.012):
                        hv = dict(cand)
                        hv["min_odds"] = HIGHVAR_MIN_ODDS
                        hv["max_odds"] = HIGHVAR_MAX_ODDS
                        highvar_pool.append(hv)

    # picks
    sharp = verify_refresh(select_top_unique_game(sharp_pool, SHARP_MAX_SINGLES), blocked)

    plus = []
    if ENABLE_PLUS_SHOTS:
        plus = verify_refresh(select_top_unique_game(plus_pool, PLUS_MAX_PICKS), blocked)

    # sharp builder uses sharp only
    sharp_builder = None
    if ENABLE_SHARP_BUILDER and len(sharp) >= BUILDER_LEGS:
        sharp_builder = build_parlay(sharp, BUILDER_LEGS, BUILDER_MIN_DEC, BUILDER_MAX_DEC)

    # lotto builder (optional)
    lotto = None
    if ENABLE_LOTTO_3LEG:
        lotto = build_parlay(select_top_unique_game(lotto_pool, 12), LOTTO_LEGS, 1.01, LOTTO_MAX_TOTAL_DEC)
        if lotto:
            lotto["legs"] = verify_refresh(lotto["legs"], blocked)

    # high-variance 3 leg (built from highvar pool)
    highvar = None
    if ENABLE_HIGHVAR_3LEG:
        highvar = build_parlay(select_top_unique_game(highvar_pool, 18), HIGHVAR_LEGS, HIGHVAR_MIN_TOTAL_DEC, HIGHVAR_MAX_TOTAL_DEC)
        if highvar:
            highvar["legs"] = verify_refresh(highvar["legs"], blocked)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    lines = []
    lines += ["✅ SHARP MODE — Today Only", f"{now}", ""]

    any_sent = False

    def maybe_emit_section(title: str, picks: list[dict], stake_line: str):
        nonlocal any_sent
        if not picks:
            return
        lines.append(title)
        lines.append(stake_line)
        lines.append("")
        for p in picks:
            key = f"{p['event']}|{p['market']}|{p['player']}|{p['side']}|{p.get('line')}|{p['target_book_used']}|{p['target_odds']}"
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
            any_sent = True

    maybe_emit_section("🟢 SHARP SINGLES", sharp, "Stake guide: ~0.75–1.0% bankroll each")

    if sharp_builder:
        lines += ["🟣 SHARP PARLAY BUILDER (from SHARP singles only)", "Stake guide: 0.10–0.25% bankroll (small)", ""]
        lines.append(f"Total decimal ≈ {sharp_builder['dec']:.2f}")
        for leg in sharp_builder["legs"]:
            lines.append(f"- {format_pick(leg)}")
        lines.append("")
        any_sent = True

    maybe_emit_section("🟠 PLUS-MONEY SHOTS (bigger win, higher variance)", plus, "Stake guide: 0.25–0.50% bankroll (smaller)")

    if highvar:
        lines += ["🔥 HIGH-VARIANCE 3-LEG (bigger payout)", "Stake guide: 0.05–0.15% bankroll (tiny)", ""]
        lines.append(f"Total decimal ≈ {highvar['dec']:.2f}")
        for leg in highvar["legs"]:
            lines.append(f"- {format_pick(leg)}")
        lines.append("")
        any_sent = True

    if lotto:
        # keep lotto as “fun” optional
        lines += ["🎲 LOTTO 3-LEG (optional fun)", "Stake guide: 0.05–0.10% bankroll (tiny)", ""]
        dec = 1.0
        for leg in lotto["legs"]:
            dec *= american_to_decimal(int(leg["target_odds"]))
        lines.append(f"Total decimal ≈ {dec:.2f}")
        for leg in lotto["legs"]:
            lines.append(f"- {format_pick(leg)}")
        lines.append("")
        any_sent = True

    if not any_sent:
        lines += ["No SHARP/PLUS picks right now. Best move is no bet.", ""]

    lines += [
        f"API calls: events={event_calls}, event-odds={odds_calls} (today events used={today_used})",
        f"Blocked: window={blocked['window']}, books={blocked['books']}, tier={blocked['tier']}, api_fail={blocked['api_fail']}, moved={blocked['moved']}",
        "🔎 Not guarantees — higher payout = higher variance. Keep stakes small on plus-money/parlays.",
    ]

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
