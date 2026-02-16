# ticker_validator.py
import logging
import requests
import json
import os
import time
import asyncio

from configs import config

logger = logging.getLogger(__name__)

# Module-level in-memory cache for ticker -> CIK mapping
_ticker_cache: dict | None = None


def _load_ticker_cache():
    """Load ticker data from disk into the module-level cache."""
    global _ticker_cache
    try:
        with open(config.PROCESSED_TICKER_FILE_PATH, 'r') as f:
            _ticker_cache = json.load(f)
        logger.debug(f"티커 캐시 로드 완료: {len(_ticker_cache)}개 항목")
    except FileNotFoundError:
        logger.critical("에러: 처리된 티커 목록 파일이 없습니다. 먼저 update_ticker_list()를 실행하세요.")
        _ticker_cache = None
    except Exception as e:
        logger.error(f"티커 캐시 로드 중 에러: {e}")
        _ticker_cache = None


def _update_ticker_list():
    """
    실제 파일 처리 로직 (동기식).
    이 함수는 메인 스레드에서 직접 호출되어서는 안 됩니다.
    """
    global _ticker_cache
    try:
        if os.path.exists(config.PROCESSED_TICKER_FILE_PATH):
            if time.time() - os.path.getmtime(config.PROCESSED_TICKER_FILE_PATH) < 86400:  # 24시간
                logger.debug("티커 목록이 최신입니다. (백그라운드 체크)")
                return

        logger.info("백그라운드: 새로운 티커 목록을 SEC에서 다운로드 중...")
        response = requests.get(config.SEC_TICKER_URL, headers=config.SEC_TICKER_HEADER)
        response.raise_for_status()
        raw_data = response.json()

        processed_data = {}
        for cik, info in raw_data.items():
            ticker = info.get('ticker')
            if ticker:
                processed_data[ticker.upper()] = str(info.get('cik_str')).zfill(10)

        os.makedirs("data", exist_ok=True)
        with open(config.PROCESSED_TICKER_FILE_PATH, 'w') as f:
            json.dump(processed_data, f)
        logger.info("백그라운드: 티커 목록 업데이트 및 저장 완료.")

        # Invalidate and reload cache after update
        _ticker_cache = processed_data

    except Exception as e:
        logger.error(f"백그라운드 티커 업데이트 실패: {e}")

async def update_ticker_list():
    """
    비동기 래퍼 함수.
    무거운 동기 작업을 별도의 스레드에서 실행시킵니다.
    """
    logger.debug("Trigger : Update ticker list(Async)")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, func=_update_ticker_list)
    logger.info("Success : Update Ticker List(Background)")

def get_cik_for_ticker(ticker):
    """
    로컬에 캐시된 티커 목록에서 CIK를 즉시 조회합니다.
    존재하면 CIK(문자열)를, 없으면 None을 반환합니다.
    """
    global _ticker_cache
    if _ticker_cache is None:
        _load_ticker_cache()
    if _ticker_cache is None:
        return None
    return _ticker_cache.get(ticker.upper())
