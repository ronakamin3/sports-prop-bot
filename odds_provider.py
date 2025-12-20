import requests
from config import ODDS_API_KEY, REGION

BASE_URL = "https://api.the-odds-api.com/v4"

def get_events(sport: str):
    url = f"{BASE_URL}/sports/{sport}/events"
    r = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=20)
    r.raise_for_status()
    return r.json()

def get_event_odds_multi_book(sport: str, event_id: str, markets: str):
    """
    Fetch odds for multiple books (US region). We'll later:
    - extract FanDuel outcome price
    - compute consensus implied probability from other books
    """
    url = f"{BASE_URL}/sports/{sport}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGION,
        "markets": markets,
        "oddsFormat": "american",
        # intentionally NOT filtering bookmakers
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()
