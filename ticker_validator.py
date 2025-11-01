# ticker_validator.py
import logging

import requests
import json
import os
import time
import asyncio

from config import config

logger = logging.getLogger(__name__)


def _update_ticker_list():
    """
    실제 파일 처리 로직 (동기식).
    이 함수는 메인 스레드에서 직접 호출되어서는 안 됩니다.
    """
    try:
        if os.path.exists(config.PROCESSED_TICKER_FILE_PATH):
            if time.time() - os.path.getmtime(config.PROCESSED_TICKER_FILE_PATH) < 86400:  # 24시간
                logger.debug("티커 목록이 최신입니다. (백그라운드 체크)")
                return

        logger.info("백그라운드: 새로운 티커 목록을 SEC에서 다운로드 중...")
        response = requests.get(config.SEC_TICKER_URL, headers=config.SEC_HEADERS)
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

    except Exception as e:
        logger.error(f"백그라운드 티커 업데이트 실패: {e}")

async def update_ticker_list():
    """
    비동기 래퍼 함수.
    무거운 동기 작업을 별도의 스레드에서 실행시킵니다.
    """
    logger.debug("Trigger : Update ticker list(Async)")

    loop = asyncio.get_running_loop()
    # run_in_executor를 사용하여 _blocking_file_update 함수를
    # 기본 스레드 풀(None)에서 실행합니다.
    await loop.run_in_executor(None, func=_update_ticker_list)
    logger.info("Success : Update Ticker List(Background)")

def get_cik_for_ticker(ticker):
    """
    로컬에 캐시된 티커 목록에서 CIK를 즉시 조회합니다.
    존재하면 CIK(문자열)를, 없으면 None을 반환합니다.
    """
    try:
        with open(config.PROCESSED_TICKER_FILE_PATH, 'r') as f:
            ticker_map = json.load(f)

        # .get()을 사용하여 티커가 존재하지 않으면 None을 반환
        return ticker_map.get(ticker.upper())
    except FileNotFoundError:
        logger.critical("에러: 처리된 티커 목록 파일이 없습니다. 먼저 update_ticker_list()를 실행하세요.")
        return None
    except Exception as e:
        logger.error(f"티커 조회 중 에러: {e}")
        return None