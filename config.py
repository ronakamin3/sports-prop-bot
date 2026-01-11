import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
REGION = os.getenv("REGION", "us")

TARGET_BOOKS = [x.strip().lower() for x in os.getenv(
    "TARGET_BOOKS", "draftkings,fanduel,betmgm,fanatics"
).split(",") if x.strip()]

# ✅ NHL REMOVED
SPORTS = [x.strip() for x in os.getenv(
    "SPORTS",
    "americanfootball_nfl,basketball_nba,baseball_mlb,"
    "soccer_epl,soccer_usa_mls,americanfootball_ncaaf,basketball_ncaab"
).split(",") if x.strip()]

EVENTS_PER_SPORT = int(os.getenv("EVENTS_PER_SPORT", "6"))
PREGAME_BUFFER_MINUTES = int(os.getenv("PREGAME_BUFFER_MINUTES", "15"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "90"))

MAX_EDGE_CAP = float(os.getenv("MAX_EDGE_CAP", "0.08"))
ONE_PICK_PER_GAME = os.getenv("ONE_PICK_PER_GAME", "true").lower() == "true"

VERIFY_BEFORE_SEND = os.getenv("VERIFY_BEFORE_SEND", "true").lower() == "true"
MAX_VERIFY_EVENTS = int(os.getenv("MAX_VERIFY_EVENTS", "4"))
MAX_ODDS_MOVE_ABS = int(os.getenv("MAX_ODDS_MOVE_ABS", "25"))

LINE_TOLERANCE = float(os.getenv("LINE_TOLERANCE", "1.0"))

# --- SHARP singles ---
SHARP_MAX_SINGLES = int(os.getenv("SHARP_MAX_SINGLES", "2"))
SHARP_MIN_BOOKS = int(os.getenv("SHARP_MIN_BOOKS", "4"))
SHARP_MIN_P = float(os.getenv("SHARP_MIN_P", "0.53"))
SHARP_MIN_EDGE = float(os.getenv("SHARP_MIN_EDGE", "0.014"))
SHARP_MIN_EV = float(os.getenv("SHARP_MIN_EV", "0.012"))
SHARP_MIN_ODDS = int(os.getenv("SHARP_MIN_ODDS", "-220"))
SHARP_MAX_ODDS = int(os.getenv("SHARP_MAX_ODDS", "175"))

# --- SHARP builder ---
ENABLE_SHARP_BUILDER = os.getenv("ENABLE_SHARP_BUILDER", "true").lower() == "true"
BUILDER_LEGS = int(os.getenv("BUILDER_LEGS", "3"))
BUILDER_MIN_DEC = float(os.getenv("BUILDER_MIN_DEC", "3.0"))
BUILDER_MAX_DEC = float(os.getenv("BUILDER_MAX_DEC", "7.0"))

# --- LOTTO 3-leg ---
ENABLE_LOTTO_3LEG = os.getenv("ENABLE_LOTTO_3LEG", "true").lower() == "true"
LOTTO_LEGS = int(os.getenv("LOTTO_LEGS", "3"))
LOTTO_MIN_ODDS = int(os.getenv("LOTTO_MIN_ODDS", "110"))
LOTTO_MAX_ODDS = int(os.getenv("LOTTO_MAX_ODDS", "350"))
LOTTO_MIN_BOOKS = int(os.getenv("LOTTO_MIN_BOOKS", "4"))
LOTTO_MIN_EDGE = float(os.getenv("LOTTO_MIN_EDGE", "0.018"))
LOTTO_MIN_EV = float(os.getenv("LOTTO_MIN_EV", "0.015"))
LOTTO_MAX_TOTAL_DEC = float(os.getenv("LOTTO_MAX_TOTAL_DEC", "18.0"))

# --- PLUS-MONEY bigger wins ---
ENABLE_PLUS_SHOTS = os.getenv("ENABLE_PLUS_SHOTS", "true").lower() == "true"
PLUS_MAX_PICKS = int(os.getenv("PLUS_MAX_PICKS", "1"))
PLUS_MIN_ODDS = int(os.getenv("PLUS_MIN_ODDS", "160"))
PLUS_MAX_ODDS = int(os.getenv("PLUS_MAX_ODDS", "320"))
PLUS_MIN_BOOKS = int(os.getenv("PLUS_MIN_BOOKS", "5"))
PLUS_MIN_EDGE = float(os.getenv("PLUS_MIN_EDGE", "0.020"))
PLUS_MIN_EV = float(os.getenv("PLUS_MIN_EV", "0.015"))

# --- High-variance parlay (bigger payout) ---
ENABLE_HIGHVAR_3LEG = os.getenv("ENABLE_HIGHVAR_3LEG", "true").lower() == "true"
HIGHVAR_LEGS = int(os.getenv("HIGHVAR_LEGS", "3"))
HIGHVAR_MIN_ODDS = int(os.getenv("HIGHVAR_MIN_ODDS", "140"))
HIGHVAR_MAX_ODDS = int(os.getenv("HIGHVAR_MAX_ODDS", "350"))
HIGHVAR_MIN_TOTAL_DEC = float(os.getenv("HIGHVAR_MIN_TOTAL_DEC", "6.0"))
HIGHVAR_MAX_TOTAL_DEC = float(os.getenv("HIGHVAR_MAX_TOTAL_DEC", "20.0"))
