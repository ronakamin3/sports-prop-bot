import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# Sports supported by The Odds API
# Soccer props are available for EPL, Ligue 1, Bundesliga, Serie A, La Liga, MLS (US bookmakers coverage). :contentReference[oaicite:1]{index=1}
SPORTS = [
    "americanfootball_nfl",
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
    "soccer_epl",
    "soccer_usa_mls",
]

BOOKMAKER_KEY = os.getenv("BOOKMAKER_KEY", "fanduel")
REGION = os.getenv("REGION", "us")

# How many props per message
DAILY_PROP_COUNT = int(os.getenv("DAILY_PROP_COUNT", "5"))

# Prevent duplicate spam (minutes)
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "180"))

# IMPORTANT FOR 500-requests/month:
# Each sport costs: 1 (events) + EVENTS_PER_SPORT (event-odds calls)
# Total per run ~= len(SPORTS) * (1 + EVENTS_PER_SPORT)
EVENTS_PER_SPORT = int(os.getenv("EVENTS_PER_SPORT", "2"))
