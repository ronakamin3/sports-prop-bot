import requests
from config import ODDS_API_KEY, REGION, BOOKMAKER_KEY

BASE_URL = "https://api.the-odds-api.com/v4"

def get_events(sport):
    url = f"{BASE_URL}/sports/{sport}/events"
    r = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=15)
    r.raise_for_status()
    return r.json()

def get_event_props(sport, event_id, markets):
    url = f"{BASE_URL}/sports/{sport}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGION,
        "markets": markets,
        "bookmakers": BOOKMAKER_KEY,
        "oddsFormat": "american"
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()
