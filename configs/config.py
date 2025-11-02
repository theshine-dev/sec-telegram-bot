# configs.py

from pathlib import Path

# Base Dir(Project Path)
BASE_DIR = Path(__file__).resolve().parent.parent

# Path
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DB_FILE_PATH = DATA_DIR / "bot.db"
PROCESSED_TICKER_FILE_PATH = DATA_DIR / "tickers.json"

# Constant
SEC_HEADERS = {'User-Agent': 'Smile Always admin@smile-always.me'}
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"