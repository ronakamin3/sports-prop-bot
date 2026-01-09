import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

REGION = os.getenv("REGION", "us")

TARGET_BOOKS = [
    x.strip().lower()
    for x in os.getenv("TARGET_BOOKS", "draftkings,fanduel,betmgm,fanatics").split(",")
]

SPORTS = [
    x.strip()
    for x in os.getenv(
        "SPORTS",
        "americanfootball_nfl,basketball_nba,baseball_mlb,icehockey_nhl,soccer_epl,soccer_usa_mls,americanfootball_ncaaf,basketball_ncaab"
    ).split(",")
    if x.strip()
]

EVENTS_PER_SPORT = int(os.getenv("EVENTS_PER_SPORT", "6"))
PREGAME_BUFFER_MINUTES = int(os.getenv("PREGAME_BUFFER_MINUTES", "15"))

STRICT_MODE = os.getenv("STRICT_MODE", "true").lower() == "true"

MIN_BOOKS_FOR_CONSENSUS = int(os.getenv("MIN_BOOKS_FOR_CONSENSUS", "4"))
MIN_P_FAIR = float(os.getenv("MIN_P_FAIR", "0.54"))
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.015"))
MIN_EV_DOLLARS = float(os.getenv("MIN_EV_DOLLARS", "0.012"))

MIN_ODDS = int(os.getenv("MIN_ODDS", "-220"))
MAX_ODDS = int(os.getenv("MAX_ODDS", "150"))

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

LINE_TOLERANCE = float(os.getenv("LINE_TOLERANCE", "1.0"))
VERIFY_BEFORE_SEND = os.getenv("VERIFY_BEFORE_SEND", "true").lower() == "true"
MAX_VERIFY_EVENTS = int(os.getenv("MAX_VERIFY_EVENTS", "4"))
MAX_ODDS_MOVE_ABS = int(os.getenv("MAX_ODDS_MOVE_ABS", "25"))

MAX_EDGE_CAP = float(os.getenv("MAX_EDGE_CAP", "0.08"))
ONE_PICK_PER_GAME = os.getenv("ONE_PICK_PER_GAME", "true").lower() == "true"

NHL_SHOTS_UNDER_MIN_BOOKS = int(os.getenv("NHL_SHOTS_UNDER_MIN_BOOKS", "5"))
NHL_LINE_TOLERANCE = float(os.getenv("NHL_LINE_TOLERANCE", "0.0"))

# ✅ LIVE
LIVE_ENABLE = os.getenv("LIVE_ENABLE", "true").lower() == "true"
LIVE_MAX_EVENTS_PER_SPORT = int(os.getenv("LIVE_MAX_EVENTS_PER_SPORT", "1"))
LIVE_LOOKBACK_MINUTES = int(os.getenv("LIVE_LOOKBACK_MINUTES", "180"))
LIVE_MARKETS = os.getenv("LIVE_MARKETS", "h2h,spreads,totals")
LIVE_MIN_BOOKS = int(os.getenv("LIVE_MIN_BOOKS", "5"))
LIVE_MIN_EDGE = float(os.getenv("LIVE_MIN_EDGE", "0.020"))
LIVE_MIN_EV_DOLLARS = float(os.getenv("LIVE_MIN_EV_DOLLARS", "0.020"))