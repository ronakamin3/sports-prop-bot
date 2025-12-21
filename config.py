import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

REGION = os.getenv("REGION", "us")

# FanDuel key differs by provider/region sometimes; we support both common labels.
TARGET_BOOKS = [x.strip().lower() for x in os.getenv("TARGET_BOOKS", "fanduel,fanduel_us").split(",")]

SPORTS = [
    "americanfootball_nfl",
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
    "soccer_epl",
    "soccer_usa_mls",
]

# Request-budget control (each sport ~= 1 events call + EVENTS_PER_SPORT odds calls)
EVENTS_PER_SPORT = int(os.getenv("EVENTS_PER_SPORT", "1"))

# Output controls
DAILY_PROP_COUNT = int(os.getenv("DAILY_PROP_COUNT", "7"))  # you want more lotto ideas
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "180"))

# Process-quality
STRICT_MODE = os.getenv("STRICT_MODE", "true").lower() == "true"

# +EV threshold (per $1 stake). For lotto mode, 0.00 is common (still requires consensus).
EV_THRESHOLD = float(os.getenv("EV_THRESHOLD", "0.00"))

# Capped Kelly stake (fraction of bankroll). Keep small for longshots.
KELLY_CAP = float(os.getenv("KELLY_CAP", "0.005"))  # 0.5% max

# NHL goalie confirmation gate (requires a goalie feed to be meaningful)
NHL_REQUIRE_CONFIRMED_GOALIE = os.getenv("NHL_REQUIRE_CONFIRMED_GOALIE", "false").lower() == "true"

# SUPER MAX HIT MODE (lotto)
SUPER_MAX_MODE = os.getenv("SUPER_MAX_MODE", "true").lower() == "true"
MIN_LONGSHOT_ODDS = int(os.getenv("MIN_LONGSHOT_ODDS", "600"))     # +600+
MAX_LONGSHOT_ODDS = int(os.getenv("MAX_LONGSHOT_ODDS", "2500"))    # cap craziness

# Consensus requirement: how many books must have a price for this exact prop outcome
MIN_BOOKS_FOR_CONSENSUS = int(os.getenv("MIN_BOOKS_FOR_CONSENSUS", "2"))
