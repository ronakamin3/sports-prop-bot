import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

REGION = os.getenv("REGION", "us")

TARGET_BOOKS = [
    x.strip().lower()
    for x in os.getenv(
        "TARGET_BOOKS",
        "draftkings,fanduel,fanatics"
    ).split(",")
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
EV_THRESHOLD = float(os.getenv("EV_THRESHOLD", "0.02"))
KELLY_CAP = float(os.getenv("KELLY_CAP", "0.01"))
MIN_BOOKS_FOR_CONSENSUS = int(os.getenv("MIN_BOOKS_FOR_CONSENSUS", "4"))

MIN_ODDS = int(os.getenv("MIN_ODDS", "-180"))
MAX_ODDS = int(os.getenv("MAX_ODDS", "150"))

MAX_SINGLES = int(os.getenv("MAX_SINGLES", "2"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "180"))

ENABLE_PARLAYS = os.getenv("ENABLE_PARLAYS", "true").lower() == "true"
ENABLE_SGP = os.getenv("ENABLE_SGP", "true").lower() == "true"
ENABLE_LOTTERY = os.getenv("ENABLE_LOTTERY", "true").lower() == "true"

SGP_DECIMAL_CAP = float(os.getenv("SGP_DECIMAL_CAP", "6.0"))
LOTTERY_DECIMAL_CAP = float(os.getenv("LOTTERY_DECIMAL_CAP", "10.0"))

NHL_REQUIRE_CONFIRMED_GOALIE = os.getenv(
    "NHL_REQUIRE_CONFIRMED_GOALIE", "false"
).lower() == "true"
