import os
from pathlib import Path

from dotenv import load_dotenv

# Base Dir(Project Root Path)
BASE_DIR = Path(__file__).resolve().parent.parent

# Read .env file
load_dotenv(dotenv_path=BASE_DIR / ".env")

# Path
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

PROCESSED_TICKER_FILE_PATH = DATA_DIR / "tickers.json"

# Token, CHAT ID
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID","6939053311")    # 본인의 chat_id
GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY", "AIzaSyAZKUzsQtV2gfhMmC1hDwG8_8EwNHR7ZQE")

# DB
DATABASE_URL = os.environ.get("DATABASE_URL")

# Scheduler Interval, etc.
UPDATE_TICKER_INTERVAL_HOURS = int(os.environ.get("UPDATE_TICKER_INTERVAL_HOURS", 24))
DISCOVER_INTERVAL_SECONDS = int(os.environ.get("DISCOVER_INTERVAL_SECONDS", 300))
ANALYSIS_INTERVAL_SECONDS = int(os.environ.get("ANALYSIS_INTERVAL_SECONDS", 80))

DISCOVER_FILING_AMOUNT = int(os.environ.get("DISCOVER_FILING_AMOUNT", 3))

# Gemini Quota
GEMINI_RPM_LIMIT = int(os.environ.get("GEMINI_RPM_LIMIT", 2))
GEMINI_DAILY_LIMIT = int(os.environ.get("GEMINI_DAILY_LIMIT", 50))
GEMINI_QUOTA_TIMEZONE = os.environ.get("GEMINI_QUOTA_TIMEZONE", "America/Los_Angeles")

# Logging
GLOBAL_LOG_LEVEL = os.environ.get("GLOBAL_LOG_LEVEL", "INFO").upper()

# Constant
SEC_HEADERS = {'User-Agent': 'Smile Always admin@smile-always.me'}  # type: 'dict'
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"