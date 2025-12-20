import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# Change if your provider uses different sport keys
SPORTS = [
    "americanfootball_nfl",
    "basketball_nba"
]

BOOKMAKER_KEY = "fanduel"
REGION = "us"

# How many props you want per message
DAILY_PROP_COUNT = 5

# Prevent duplicate spam
COOLDOWN_MINUTES = 180
