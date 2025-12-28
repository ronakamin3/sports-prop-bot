from __future__ import annotations

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
    fair_prob_two_way_no_vig,
)
from scorer import select_top, build_best_builder, build_controlled_sgp, build_lottery


# Markets we request per sport (keep to a curated set for accuracy)
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
    r = requests.post(url, json=payload, timeout=25)
    r.raise_for_status()


def is_today_et(commence_time: str) -> bool:
    eastern = tz.gettz("America/New_York")
    today_et = datetime.now(tz=eastern).date()
    dt = parser.isoparse(commence_time)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(eastern).date() == today_et


def is_blocked_reception_over(c: dict) -> bool:
    # Block NFL reception OVERS (your preference: reduce "miss by 1" variance)
    return (
        c.get("sport") == "americanfootball_nfl"
        and c.get("market") == "player_receptions"
        and c.get("side") == "Over"
    )


def format_pick(p: dict) -> str:
    odds = p["target_odds"]
    line = p.get("line")
    s = f"{p['player']} — {p['market']} — {p['side']}"
    if line is not None:
        s += f" {line}"
    s += f" ({odds:+d})"
    return s


def why_line(p: dict) -> str:
    odds = p["target_odds"]
    p_model = p["p_model"]
    p_implied = implied_prob_american(odds)
    edge = p_model - p_implied
    return (
        f"WHY: p_fair={p_model:.3f} vs implied={p_implied:.3f} (edge={edge:+.3f}), "
        f"EV=${p['ev']:.3f}/$1, books={p['books_count']}, Kelly~{p['kelly_frac']*100:.2f}%"
    )


def normalize_to_candidates(event: dict, odds_data: dict) -> list[dict]:
    """
    Convert API response into candidate props.
    Key behavior:
      - Build a market-level consensus probability (no-vig for O/U where possible)
      - Collect odds from *all* TARGET_BOOKS (draftkings, fanduel, fanatics)
      - Do NOT choose a book here; we pick best book by EV later.
    """
    sport = event.get("sport_key")
    away = event.get("away_team", "")
    home = event.get("home_team", "")
    event_name = f"{away} @ {home}".strip(" @")

    # (market, player, line) -> book -> {side: odds}
    by_key: dict[tuple, dict[str, dict[str, int]]] = {}

    for bm in odds_data.get("bookmakers", []):
        bm_key = (bm.get("key") or "").lower()
        for m in bm.get("markets", []):
            market_key = m.get("key")
            for o in m.get("outcomes", []):
                player = o.get("description") or o.get("name")
                side = o.get("name")  # Over/Under/Yes/No
                line = o.get("point")  # None for some yes/no markets
                price = o.get("price")

                if not player or not market_key or not side:
                    continue
                if not isinstance(price, int):
                    continue

                k = (market_key, player, line)
                by_key.setdefault(k, {})
                by_key[k].setdefault(bm_key, {})
                by_key[k][bm_key][side] = price

    candidates: list[dict] = []

    for (market_key, player, line), book_sides in by_key.items():
        # detect 2-way O/U where both sides exist at same line
        is_ou = any(("Over" in sides and "Under" in sides) for sides in book_sides.values())

        fair_probs_over: list[float] = []
        fair_probs_under: list[float] = []
        implied_probs_by_side: dict[str, list[float]] = {}

        for bk, sides in book_sides.items():
            # For O/U: use only books that offer both sides at same line -> true no-vig
            if "Over" in sides and "Under" in sides:
                p_over = implied_prob_american(sides["Over"])
                p_under = implied_prob_american(sides["Under"])
                fair_over = fair_prob_two_way_no_vig(p_over, p_under)
                fair_under = 1.0 - fair_over
                fair_probs_over.append(fair_over)
                fair_probs_under.append(fair_under)

            # For yes/no etc: use implied probs as a fallback consensus (less pure than no-vig)
            for side_name, odd in sides.items():
                implied_probs_by_side.setdefault(side_name, []).append(implied_prob_american(odd))

        sides_to_emit = ["Over", "Under"] if is_ou else list(implied_probs_by_side.keys())

        for side in sides_to_emit:
            # Gather odds for ALL target books (DK + FD + Fanatics)
            target_odds_by_book: dict[str, int] = {}
            for tb in TARGET_BOOKS:
                if tb in book_sides and side in book_sides[tb] and isinstance(book_sides[tb][side], int):
                    target_odds_by_book[tb] = book_sides[tb][side]

            # Consensus probability
            if is_ou and side in ("Over", "Under"):
                probs = fair_probs_over if side == "Over" else fair_probs_under
                p_model = consensus_probability_from_probs(probs)
                books_count = len(probs)  # only books with both sides at same line
            else:
                probs = implied_probs_by_side.get(side, [])
                p_model = consensus_probability_from_probs(probs)
                books_count = len(probs)

            candidates.append({
                "sport": sport,
                "event": event_name,
                "market": market_key,
                "player": player,
                "side": side,
                "line": line,
                "target_odds_by_book": target_odds_by_book,
                "p_model": p_model,
                "books_count": books_count,
                "goalie_confirmed": None,
            })

    return candidates


def main() -> None:
    init_db()

    all_candidates: list[dict] = []
    total_event_calls = 0
    total_odds_calls = 0
    total_today_events_used = 0

    # Debug counters (helps you see exactly what's blocking)
    blocked_gate = 0
    blocked_target_missing = 0
    blocked_odds_window = 0
    blocked_books = 0
    blocked_ev = 0
    blocked_reception_over = 0

    for sport in SPORTS:
        markets = SPORT_MARKETS.get(sport, "")
        if not markets:
            continue

        events = get_events(sport)
        total_event_calls += 1

        today_events = [e for e in events if e.get("commence_time") and is_today_et(e["commence_time"])]
        total_today_events_used += min(len(today_events), EVENTS_PER_SPORT)

        for event in today_events[:EVENTS_PER_SPORT]:
            odds_data = get_event_odds_multi_book(sport, event["id"], markets)
            total_odds_calls += 1
            all_candidates.extend(normalize_to_candidates(event, odds_data))

    approved: list[dict] = []

    for c in all_candidates:
        if is_blocked_reception_over(c):
            blocked_reception_over += 1
            continue

        gate = quality_gates(c, STRICT_MODE, NHL_REQUIRE_CONFIRMED_GOALIE)
        if not getattr(gate, "ok", False):
            blocked_gate += 1
            continue

        # Need a probability estimate
        if c.get("p_model") is None:
            blocked_gate += 1
            continue

        # Choose the best book among TARGET_BOOKS by highest EV, within odds window
        odds_map = c.get("target_odds_by_book") or {}
        best = None  # (ev, book, odds)

        # Note: we track odds_window blocks separately here
        saw_any_odds = False
        saw_any_in_window = False

        for book, odds in odds_map.items():
            if not isinstance(odds, int):
                continue
            saw_any_odds = True
            if odds < MIN_ODDS or odds > MAX_ODDS:
                continue
            saw_any_in_window = True
            ev_tmp = expected_value(c["p_model"], odds)
            if best is None or ev_tmp > best[0]:
                best = (ev_tmp, book, odds)

        if not saw_any_odds:
            blocked_target_missing += 1
            continue
        if not saw_any_in_window:
            blocked_odds_window += 1
            continue
        if best is None:
            blocked_target_missing += 1
            continue

        # Lock in selected book + odds
        c["ev"] = best[0]
        c["target_book_used"] = best[1]
        c["target_odds"] = best[2]

        # Consensus depth gate
        if c.get("books_count", 0) < MIN_BOOKS_FOR_CONSENSUS:
            blocked_books += 1
            continue

        # EV gate
        if c["ev"] < EV_THRESHOLD:
            blocked_ev += 1
            continue

        # Kelly sizing (capped)
        k = kelly_fraction(c["p_model"], c["target_odds"])
        c["kelly_frac"] = min(k, KELLY_CAP)

        approved.append(c)

    eastern = tz.gettz("America/New_York")
    now = datetime.now(tz=eastern).strftime("%a %b %d %I:%M %p ET")

    if not approved:
        msg = "\n".join([
            "ℹ️ ACCURATE MODE — Today’s Games Only (No-Vig) — DK+FD+Fanatics Target",
            f"{now}",
            "No qualified picks today.",
            f"API calls: events={total_event_calls}, event-odds={total_odds_calls} (today events used={total_today_events_used})",
            f"Filters: EV≥{EV_THRESHOLD:.2f}, Books≥{MIN_BOOKS_FOR_CONSENSUS}, OddsRange[{MIN_ODDS},{MAX_ODDS}], KellyCap={KELLY_CAP:.3f}",
            f"Blocked: gate={blocked_gate}, target_missing={blocked_target_missing}, odds_window={blocked_odds_window}, books={blocked_books}, ev={blocked_ev}, rec_over_blocked={blocked_reception_over}",
        ])
        send_telegram(msg)
        return

    # Singles
    top_singles = select_top(approved, MAX_SINGLES)

    # Parlays (built ONLY from approved picks)
    best_builder = build_best_builder(top_singles) if ENABLE_PARLAYS else None
    controlled_sgp = build_controlled_sgp(approved, top_singles, sgp_decimal_cap=SGP_DECIMAL_CAP) if ENABLE_SGP else None
    lottery = build_lottery(approved, lottery_decimal_cap=LOTTERY_DECIMAL_CAP) if ENABLE_LOTTERY else None

    lines = [
        "✅ ACCURATE MODE — Today’s Games Only (+EV, No-Vig) — Best of DK+FD+Fanatics",
        f"{now}",
        f"API calls: events={total_event_calls}, event-odds={total_odds_calls} (today events used={total_today_events_used})",
        f"Filters: EV≥{EV_THRESHOLD:.2f}, Books≥{MIN_BOOKS_FOR_CONSENSUS}, OddsRange[{MIN_ODDS},{MAX_ODDS}], KellyCap={KELLY_CAP:.3f}",
        f"Blocked: gate={blocked_gate}, target_missing={blocked_target_missing}, odds_window={blocked_odds_window}, books={blocked_books}, ev={blocked_ev}, rec_over_blocked={blocked_reception_over}",
        "",
        "🟢 SHARP SINGLES (Stake guide: ~0.75–1.0% bankroll each)",
        "",
    ]

    sent_any = False
    for p in top_singles:
        key = (
            f"{p['sport']}|{p['event']}|{p['market']}|{p['player']}|{p['side']}|"
            f"{p.get('line')}|{p.get('target_book_used')}|{p['target_odds']}"
        )
        if was_sent_recently(key, COOLDOWN_MINUTES):
            continue
        mark_sent(key)
        sent_any = True

        lines.append(f"• {format_pick(p)}")
        lines.append(f"  {p['event']}")
        lines.append(f"  Book={p.get('target_book_used')} | books={p.get('books_count', 0)}")
        lines.append(f"  {why_line(p)}")
        lines.append("")

    if not sent_any:
        # If everything was suppressed by cooldown, don't spam telegram
        return

    # Parlay sections (clearly labeled)
    if best_builder:
        lines.append("🔵 PARLAY #1 — BEST BUILDER (2-leg cross-game)")
        lines.append("Stake guide: ~0.25–0.5% bankroll (optional upside)")
        lines.append(
            f"Est: p≈{best_builder['p_parlay']:.3f} | dec≈{best_builder['dec_odds']:.2f} | "
            f"EV≈${best_builder['ev']:.3f}/$1 (independence est.)"
        )
        for leg in best_builder["legs"]:
            lines.append(f"- {format_pick(leg)}  [{leg['event']}] (Book={leg.get('target_book_used')})")
        lines.append("")

    if controlled_sgp:
        lines.append("🟠 PARLAY #2 — CONTROLLED SGP (2-leg same-game, guarded)")
        lines.append("Stake guide: ~0.10–0.25% bankroll (fun, capped)")
        lines.append(
            f"Est: p≈{controlled_sgp['p_parlay']:.3f} | dec≈{controlled_sgp['dec_odds']:.2f} | "
            f"EV≈${controlled_sgp['ev']:.3f}/$1 (independence est.; correlation risk)"
        )
        for leg in controlled_sgp["legs"]:
            lines.append(f"- {format_pick(leg)} (Book={leg.get('target_book_used')})")
        lines.append("")

    if lottery:
        lines.append("🔴 PARLAY #3 — LOTTERY (3-leg, HIGH VARIANCE)")
        lines.append("Stake guide: ≤0.10% bankroll (expect loss; optional only)")
        lines.append(
            f"Est: p≈{lottery['p_parlay']:.3f} | dec≈{lottery['dec_odds']:.2f} | "
            f"EV≈${lottery['ev']:.3f}/$1 (independence est.)"
        )
        for leg in lottery["legs"]:
            lines.append(f"- {format_pick(leg)}  [{leg['event']}] (Book={leg.get('target_book_used')})")
        lines.append("")

    lines.append(
        "🔎 Not guarantees — accuracy-first structure: no-vig fair probs + multi-book consensus + EV gate + stake caps."
    )

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
