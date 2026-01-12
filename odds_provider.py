import os
import requests
import time

from config import ODDS_API_KEY, REGION

BASE = "https://api.the-odds-api.com/v4"
TIMEOUT = 25


def _get(url: str, params: dict):
    # basic retry for 429/5xx/network
    last = None
    for delay in (0, 2, 5, 10):
        try:
            if delay:
                time.sleep(delay)
            r = requests.get(url, params=params, timeout=TIMEOUT)

            # retry on rate limit / server errors
            if r.status_code == 429 or (500 <= r.status_code < 600):
                last = (r.status_code, r.text[:300])
                continue

            # raise with useful info
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")

            return r.json()

        except Exception as e:
            last = str(e)

    raise RuntimeError(f"Request failed after retries: {last}")


def get_events(sport_key: str):
    if not ODDS_API_KEY:
        raise RuntimeError("Missing ODDS_API_KEY (GitHub secret not set?)")

    url = f"{BASE}/sports/{sport_key}/events"
    params = {"apiKey": ODDS_API_KEY}
    return _get(url, params)


def get_event_odds_multi_book(sport_key: str, event_id: str, markets: str):
    if not ODDS_API_KEY:
        raise RuntimeError("Missing ODDS_API_KEY (GitHub secret not set?)")

    url = f"{BASE}/sports/{sport_key}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGION,
        "markets": markets,
        "oddsFormat": "american",
    }
    return _get(url, params)