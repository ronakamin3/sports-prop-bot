import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

REGION = os.getenv("REGION", "us")

TARGET_BOOKS = [
    x.strip().lower()
    for x in os.getenv("TARGET_BOOKS", "draftkings,fanduel,betmgm,fanatics").split(",")
]

# All sports
SPORTS = [
    "americanfootball_nfl",
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
    "soccer_epl",
    "soccer_usa_mls",
]

EVENTS_PER_SPORT = int(os.getenv("EVENTS_PER_SPORT", "1"))
PREGAME_BUFFER_MINUTES = int(os.getenv("PREGAME_BUFFER_MINUTES", "20"))

STRICT_MODE = os.getenv("STRICT_MODE", "true").lower() == "true"

MIN_BOOKS_FOR_CONSENSUS = int(os.getenv("MIN_BOOKS_FOR_CONSENSUS", "3"))
MIN_P_FAIR = float(os.getenv("MIN_P_FAIR", "0.55"))
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.018"))
MIN_EV_DOLLARS = float(os.getenv("MIN_EV_DOLLARS", "0.015"))

MIN_ODDS = int(os.getenv("MIN_ODDS", "-220"))
MAX_ODDS = int(os.getenv("MAX_ODDS", "130"))

KELLY_CAP = float(os.getenv("KELLY_CAP", "0.01"))

MAX_SINGLES = int(os.getenv("MAX_SINGLES", "2"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "240"))

ENABLE_PARLAYS = os.getenv("ENABLE_PARLAYS", "true").lower() == "true"
ENABLE_SGP = os.getenv("ENABLE_SGP", "false").lower() == "true"
ENABLE_LOTTERY = os.getenv("ENABLE_LOTTERY", "false").lower() == "true"

BUILDER_LEGS = int(os.getenv("BUILDER_LEGS", "3"))
BUILDER_MIN_DEC = float(os.getenv("BUILDER_MIN_DEC", "3.0"))
BUILDER_MAX_DEC = float(os.getenv("BUILDER_MAX_DEC", "6.0"))

NHL_REQUIRE_CONFIRMED_GOALIE = os.getenv("NHL_REQUIRE_CONFIRMED_GOALIE", "false").lower() == "true"