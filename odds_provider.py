import time
import requests
from config import ODDS_API_KEY, REGION

BASE = "https://api.the-odds-api.com/v4"

TIMEOUT = 12


def _get(url: str, params: dict):
    last_err = None
    for delay in (0, 1, 2):
        try:
            if delay:
                time.sleep(delay)

            r = requests.get(url, params=params, timeout=TIMEOUT)

            # IMPORTANT: print useful info for debugging
            if r.status_code >= 400:
                print(f"[ODDS_API] HTTP {r.status_code} url={r.url}")
                print(f"[ODDS_API] body={r.text[:500]}")

            # Retry on rate limit or server errors
            if r.status_code == 429 or (500 <= r.status_code < 600):
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                continue

            r.raise_for_status()
            return r.json()

        except Exception as e:
            last_err = str(e)

    raise RuntimeError(f"Odds API request failed after retries: {last_err}")


def get_events(sport_key: str):
    if not ODDS_API_KEY:
        raise RuntimeError("Missing ODDS_API_KEY secret")
    url = f"{BASE}/sports/{sport_key}/events"
    return _get(url, {"apiKey": ODDS_API_KEY})


def get_event_odds_multi_book(sport_key: str, event_id: str, markets: str):
    if not ODDS_API_KEY:
        raise RuntimeError("Missing ODDS_API_KEY secret")
    url = f"{BASE}/sports/{sport_key}/events/{event_id}/odds"
    return _get(
        url,
        {
            "apiKey": ODDS_API_KEY,
            "regions": REGION,
            "markets": markets,
            "oddsFormat": "american",
        },
    )