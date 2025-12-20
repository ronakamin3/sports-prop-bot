import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

REGION = os.getenv("REGION", "us")

# FanDuel is the book you want to bet / alert on
TARGET_BOOK = os.getenv("TARGET_BOOK", "fanduel").lower()

# Sports
SPORTS = [
    "americanfootball_nfl",
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
    "soccer_epl",
    "soccer_usa_mls",
]

# Request-budget control: each sport costs ~ (1 + EVENTS_PER_SPORT) requests per run
EVENTS_PER_SPORT = int(os.getenv("EVENTS_PER_SPORT", "1"))

# Output controls
DAILY_PROP_COUNT = int(os.getenv("DAILY_PROP_COUNT", "5"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "180"))

# Process-quality controls
STRICT_MODE = os.getenv("STRICT_MODE", "true").lower() == "true"

# +EV threshold (per $1 stake). 0.02 = +2% expected value
EV_THRESHOLD = float(os.getenv("EV_THRESHOLD", "0.02"))

# Capped Kelly stake (fraction of bankroll). 0.01 = max 1%
KELLY_CAP = float(os.getenv("KELLY_CAP", "0.01"))

# NHL goalie gate: without a goalie feed, this blocks most NHL picks.
# Set to "false" if you want NHL picks anyway.
NHL_REQUIRE_CONFIRMED_GOALIE = os.getenv("NHL_REQUIRE_CONFIRMED_GOALIE", "false").lower() == "true"
