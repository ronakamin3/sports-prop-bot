import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

REGION = os.getenv("REGION", "us")

TARGET_BOOKS = [
    x.strip().lower()
    for x in os.getenv("TARGET_BOOKS", "draftkings,fanduel,fanatics,betmgm").split(",")
]

SPORTS = [
    "americanfootball_nfl",
    "basketball_nba",
    "icehockey_nhl",
    "soccer_epl",
    "soccer_usa_mls",
    "baseball_mlb",
]

EVENTS_PER_SPORT = int(os.getenv("EVENTS_PER_SPORT", "1"))

STRICT_MODE = os.getenv("STRICT_MODE", "true").lower() == "true"

EV_THRESHOLD = float(os.getenv("EV_THRESHOLD", "0.01"))
MIN_BOOKS_FOR_CONSENSUS = int(os.getenv("MIN_BOOKS_FOR_CONSENSUS", "4"))

MIN_ODDS = int(os.getenv("MIN_ODDS", "-200"))
MAX_ODDS = int(os.getenv("MAX_ODDS", "130"))

KELLY_CAP = float(os.getenv("KELLY_CAP", "0.01"))

MAX_SINGLES = int(os.getenv("MAX_SINGLES", "2"))
WATCHLIST_COUNT = int(os.getenv("WATCHLIST_COUNT", "3"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "240"))

ENABLE_PARLAYS = os.getenv("ENABLE_PARLAYS", "true").lower() == "true"
ENABLE_SGP = os.getenv("ENABLE_SGP", "false").lower() == "true"
ENABLE_LOTTERY = os.getenv("ENABLE_LOTTERY", "false").lower() == "true"

# NHL goalie gate (leave off unless you have a goalie-confirm feed)
NHL_REQUIRE_CONFIRMED_GOALIE = os.getenv("NHL_REQUIRE_CONFIRMED_GOALIE", "false").lower() == "true"

# ✅ “Actually good” filters
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.020"))          # p_fair - implied
MIN_EV_DOLLARS = float(os.getenv("MIN_EV_DOLLARS", "0.03"))  # EV per $1
MIN_P_FAIR = float(os.getenv("MIN_P_FAIR", "0.54"))       # better hit rate

# ✅ Pre-game only
PREGAME_BUFFER_MINUTES = int(os.getenv("PREGAME_BUFFER_MINUTES", "15"))
