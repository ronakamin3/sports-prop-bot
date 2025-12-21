import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

REGION = os.getenv("REGION", "us")
TARGET_BOOKS = [x.strip().lower() for x in os.getenv("TARGET_BOOKS", "fanduel,fanduel_us").split(",")]

SPORTS = [
    "americanfootball_nfl",
    "basketball_nba",
    "icehockey_nhl",
    "soccer_epl",
    "soccer_usa_mls",
    # baseball_mlb is offseason in winter; keep if you want, but often empty
    "baseball_mlb",
]

EVENTS_PER_SPORT = int(os.getenv("EVENTS_PER_SPORT", "1"))

DAILY_PROP_COUNT = int(os.getenv("DAILY_PROP_COUNT", "5"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "180"))

STRICT_MODE = os.getenv("STRICT_MODE", "true").lower() == "true"

# Accuracy mode filters
EV_THRESHOLD = float(os.getenv("EV_THRESHOLD", "0.02"))        # +2% EV per $1
KELLY_CAP = float(os.getenv("KELLY_CAP", "0.01"))              # max 1% bankroll
MIN_BOOKS_FOR_CONSENSUS = int(os.getenv("MIN_BOOKS_FOR_CONSENSUS", "4"))

# Odds window for accuracy
MIN_ODDS = int(os.getenv("MIN_ODDS", "-200"))                  # avoid crazy juice
MAX_ODDS = int(os.getenv("MAX_ODDS", "200"))                   # avoid longshots

# Optional NHL goalie gate (off unless you add a goalie source)
NHL_REQUIRE_CONFIRMED_GOALIE = os.getenv("NHL_REQUIRE_CONFIRMED_GOALIE", "false").lower() == "true"
