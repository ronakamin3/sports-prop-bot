import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

REGION = os.getenv("REGION", "us")

# DraftKings target book
# If your provider returns a different DK key, add it comma-separated.
TARGET_BOOKS = [x.strip().lower() for x in os.getenv("TARGET_BOOKS", "draftkings").split(",")]

SPORTS = [
    "americanfootball_nfl",
    "basketball_nba",
    "icehockey_nhl",
    "soccer_epl",
    "soccer_usa_mls",
    "baseball_mlb",
]

# Request budget control
EVENTS_PER_SPORT = int(os.getenv("EVENTS_PER_SPORT", "1"))

# Output controls
DAILY_PROP_COUNT = int(os.getenv("DAILY_PROP_COUNT", "5"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "180"))

# Accuracy gates
STRICT_MODE = os.getenv("STRICT_MODE", "true").lower() == "true"
EV_THRESHOLD = float(os.getenv("EV_THRESHOLD", "0.02"))
KELLY_CAP = float(os.getenv("KELLY_CAP", "0.01"))
MIN_BOOKS_FOR_CONSENSUS = int(os.getenv("MIN_BOOKS_FOR_CONSENSUS", "4"))

# Avoid longshots + extreme juice for accuracy
MIN_ODDS = int(os.getenv("MIN_ODDS", "-200"))
MAX_ODDS = int(os.getenv("MAX_ODDS", "200"))

# Optional NHL goalie gate (only meaningful if you add a goalie feed later)
NHL_REQUIRE_CONFIRMED_GOALIE = os.getenv("NHL_REQUIRE_CONFIRMED_GOALIE", "false").lower() == "true"
