# db_manager.py
import json
import logging
import os
import sqlite3
import datetime
from contextlib import contextmanager

from config import config
from config.types import FilingInfo, AnalysisStatus

logger = logging.getLogger(__name__)


@contextmanager
def get_db_connection():
    """
    DB 연결, 트랜잭션, 예외 처리, 자원 반납을 자동화하는 컨텍스트 매니저.
    성공 시 'conn' 객체를, 실패 시 None을 yield합니다.
    """
    conn = None
    try:
        conn = sqlite3.connect(config.DB_FILE_PATH)
        # 딕셔너리 형태 접근을 위해 row_factory 설정
        conn.row_factory = sqlite3.Row
        logger.debug("[DB] DB 연결 생성됨")
        yield conn

        conn.commit()
        logger.debug("[DB] DB 트랜잭션 커밋됨")

    except sqlite3.Error as e:
        logger.error(f"[DB] DB 오류 발생: {e}", exc_info=True)
        if conn:
            conn.rollback()
            logger.debug("[DB] DB 트랜잭션 롤백됨")
    finally:
        if conn:
            conn.close()
            logger.debug("[DB] DB 연결 종료됨")


### Setup func  ###
def setup_database():
    """데이터베이스와 테이블을 초기화합니다."""
    os.makedirs(config.DATA_DIR, exist_ok=True)

    conn = sqlite3.connect(config.DB_FILE_PATH)
    cur = conn.cursor()

    try:
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                PRIMARY KEY (user_id, ticker)
            );
            CREATE TABLE IF NOT EXISTS latest_filings (
                ticker TEXT PRIMARY KEY,
                last_accession_number TEXT NOT NULL,
                last_filing_type TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analysis_queue (
                accession_number TEXT NOT NULL PRIMARY KEY,
                ticker TEXT NOT NULL,
                filing_type TEXT NOT NULL,
                filing_url TEXT NOT NULL,
                status TEXT NOT NULL,
                last_modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS analysis_archive (
                accession_number TEXT NOT NULL PRIMARY KEY,
                ticker TEXT NOT NULL,
                filing_type TEXT NOT NULL,
                filing_url TEXT NOT NULL,
                gemini_analysis TEXT,
                analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS daily_quota_tracker (
                id INTEGER PRIMARY KEY DEFAULT 1,
                current_date TIMESTAMP NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0
            );
            """
                          )

        # 데일리 카운팅 초기 행 삽입
        cur.execute("""
        INSERT OR IGNORE INTO daily_quota_tracker (id, current_date, request_count)
        VALUES (1, '1970-01-01', 0)
        """)
        conn.commit()
    except sqlite3.OperationalError as e:
        logger.error("Error creating database and tables!!")
        logger.debug(e)
    finally:
        conn.close()


### Subscription func  ###
def add_subscription(user_id, ticker):
    sql = "INSERT INTO subscriptions (user_id, ticker) VALUES (?, ?)"
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, (user_id, ticker.upper()))
    logger.info(f"[구독] {user_id}가 {ticker}를 구독하기 시작")


def remove_subscription(user_id, ticker):
    sql = "DELETE FROM subscriptions WHERE user_id=? AND ticker=?"
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, (user_id, ticker.upper()))
    logger.info(f"[구독취소] {user_id}가 {ticker}를 구독 취소")


def get_all_subscribed_tickers():
    sql = "SELECT DISTINCT ticker FROM subscriptions"
    tickers = None
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        tickers = [row[0] for row in cur.fetchall()]
    return tickers


def get_subscribed_tickers_for_user(user_id):
    sql = "SELECT ticker FROM subscriptions WHERE user_id = ?"
    tickers = None
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, (user_id,))
        tickers = [row[0] for row in cur.fetchall()]
    return tickers


def get_users_for_ticker(ticker):
    sql = "SELECT user_id FROM subscriptions WHERE ticker = ?"
    user_ids = None
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, (ticker,))
        user_ids = [row[0] for row in cur.fetchall()]
    return user_ids


### SEC & Gemini func  ###
def get_last_accession_number(ticker):
    """ Return a last accession number for ticker from 'latest_filings' table. """
    sql = "SELECT last_accession_number FROM latest_filings WHERE ticker = ?"
    result = None
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, (ticker,))
        result = cur.fetchone()
    return result[0] if result else None


def update_last_filing_info(last_filing: FilingInfo):
    """ Update a new last filing info for ticker into 'latest_filings' table. """
    sql = """
    INSERT INTO latest_filings (ticker, last_accession_number, last_filing_type) VALUES (?, ?, ?)
    ON CONFLICT(ticker) DO UPDATE SET
    last_accession_number = excluded.last_accession_number,
    last_filing_type = excluded.last_filing_type
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, (last_filing.ticker, last_filing.accession_number, last_filing.filing_type))


def update_analysis_queue(analysis_job: FilingInfo):
    """ UPSERT analysis queue for ticker into 'analysis_queue' table. """
    with get_db_connection() as conn:
        cur = conn.cursor()

        sql = """
        INSERT INTO analysis_queue (accession_number, ticker, filing_type, filing_url, status, last_modified_at) 
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(accession_number) DO UPDATE SET
        status = excluded.status,
        last_modified_at = excluded.last_modified_at
        """

        cur.execute(sql,
                    (analysis_job.accession_number, analysis_job.ticker, analysis_job.filing_type,
                     analysis_job.filing_url, analysis_job.status, datetime.datetime.now())
                    )


def get_pending_jobs(limit: int) -> list[FilingInfo]:
    """ Get a limited number of pending jobs from 'analysis_queue' table. """
    jobs: list[FilingInfo] = list()
    sql = """
            SELECT accession_number, ticker, filing_type, filing_url
            FROM analysis_queue
            WHERE status = 'PENDING'
            ORDER BY last_modified_at ASC
            LIMIT ?
            """

    with get_db_connection() as conn:
        cur = conn.cursor()
        # pending 상태인 작업을 오래된 순(last_modified_at ASC)으로 정렬하여 limit만큼 선택
        cur.execute(sql, (limit,))

        rows = cur.fetchall()

        # FilingInfo 타입의 딕셔너리 반환
        for row in rows:
            jobs.append(FilingInfo(
                accession_number=row['accession_number'],
                ticker=row['ticker'],
                filing_type=row['filing_type'],
                filing_url=row['filing_url'],
                status=AnalysisStatus.PENDING.value,
            )
            )
    return jobs


def remove_analysis_queue(job: FilingInfo):
    sql = "DELETE FROM analysis_queue WHERE accession_number=?"
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, (job.accession_number,))


def insert_analysis_archive(analysis_job: FilingInfo):
    """
    Insert an analysis archive into 'analysis_archive' table.
    """
    sql = """
        INSERT INTO analysis_archive (accession_number, ticker, filing_type, filing_url, gemini_analysis, analyzed_at) 
        VALUES (?, ?, ?, ?, ?, ?)
        """

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql,
                    (analysis_job.accession_number, analysis_job.ticker, analysis_job.filing_type,
                     analysis_job.filing_url, json.dumps(analysis_job.gemini_analysis), datetime.datetime.now())
                    )


def get_analysis_archive(ticker):
    return


def get_quota_status() -> dict:
    """현재 할당량 상태(카운트, 날짜)를 DB에서 가져옵니다."""
    sql = "SELECT current_date, request_count FROM daily_quota_tracker WHERE id = 1"

    with get_db_connection() as conn:
        row = conn.execute(sql).fetchone()
        if row:
            return {
                    "date": row['current_date'],
                    "count": row['request_count']
            }

    logger.critical(f"[Quota] 할당량 추적기 테이블을 읽을 수 없습니다!")
    return {"date": "1970-01-01", "count": 999}  # 안전을 위해 999 반환


def update_quota_count(new_count: int, date_str: str):
    """오늘의 할당량 카운트를 새 값으로 업데이트합니다."""
    sql = "UPDATE daily_quota_tracker SET request_count = ?, current_date = ? WHERE id = 1"

    with get_db_connection() as conn:
        conn.execute(sql, (new_count, date_str))
    logger.info(f"일일 할당량 카운트 업데이트: {new_count} (날짜: {date_str})")