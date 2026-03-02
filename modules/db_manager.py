# db_manager.py (PostgreSQL용 전체 코드)
import json
import logging
import datetime
from contextlib import asynccontextmanager # <-- 변경

import psycopg # <-- 변경
from psycopg.rows import dict_row # <-- 딕셔너리 반환용
from psycopg_pool import AsyncConnectionPool # <-- 비동기 커넥션 풀

from configs import config
from configs.types import FilingInfo, AnalysisStatus

logger = logging.getLogger(__name__)

# 전역 커넥션 풀
DB_POOL: AsyncConnectionPool = None

async def init_db_pool():
    """애플리케이션 시작 시 비동기 DB 커넥션 풀을 생성합니다."""
    global DB_POOL
    if not DB_POOL:
        if not config.DATABASE_URL:
            raise ValueError("DATABASE_URL 환경 변수가 설정되지 않았습니다.")

        # row_factory=dict_row: 결과를 딕셔너리처럼 {'key': 'value'}로 반환
        DB_POOL = AsyncConnectionPool(
            conninfo=config.DATABASE_URL,
            min_size=2,
            max_size=10,
            open=False,
            kwargs={"row_factory": dict_row}
        )

        await DB_POOL.open()

        logger.info("[DB] 비동기 DB 커넥션 풀 생성됨")

async def close_db_pool():
    """애플리케이션 종료 시 DB 커넥션 풀을 닫습니다."""
    global DB_POOL
    if DB_POOL:
        await DB_POOL.close()
        logger.info("[DB] 비동기 DB 커넥션 풀 종료됨")


@asynccontextmanager
async def get_db_connection():
    """
    커넥션 풀에서 비동기 DB 연결을 가져오고, 트랜잭션, 예외 처리를 자동화합니다.
    """
    if not DB_POOL:
        await init_db_pool()

    async with DB_POOL.connection() as conn:
        async with conn.cursor() as cur:
            try:
                logger.debug("[DB] DB 연결 풀에서 가져옴")
                yield cur # <-- 커서(cur)를 yield
                await conn.commit()
                logger.debug("[DB] DB 트랜잭션 커밋됨")
            except psycopg.Error as e:
                logger.error(f"[DB] DB 오류 발생: {e}", exc_info=True)
                await conn.rollback()
                logger.debug("[DB] DB 트랜잭션 롤백됨")
                raise
            except Exception as e:
                logger.error(f"[DB] 알 수 없는 오류: {e}", exc_info=True)
                await conn.rollback()
                logger.debug("[DB] DB 트랜잭션 롤백됨")
                raise # 그 외 예외는 다시 발생시킴


### Setup func ###
async def setup_database():
    """데이터베이스와 테이블을 초기화합니다."""

    schema_sql = """
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id BIGINT NOT NULL,
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
            filing_date DATE DEFAULT CURRENT_DATE,
            filing_url TEXT NOT NULL,
            status TEXT NOT NULL,
            last_modified_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS analysis_archive (
            accession_number TEXT NOT NULL PRIMARY KEY,
            ticker TEXT NOT NULL,
            filing_type TEXT NOT NULL,
            filing_date DATE DEFAULT CURRENT_DATE,
            filing_url TEXT NOT NULL,
            gemini_analysis JSONB,
            analyzed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS daily_quota_tracker (
            id INTEGER PRIMARY KEY DEFAULT 1,
            quota_date TIMESTAMPTZ NOT NULL,
            request_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_analysis_queue_status ON analysis_queue(status);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_ticker ON subscriptions(ticker);
        """

    async with get_db_connection() as cur:
        await cur.execute(schema_sql)

        # retry_count 컬럼 추가 (기존 테이블에도 안전하게 적용, IF NOT EXISTS로 멱등 보장)
        await cur.execute("""
        ALTER TABLE analysis_queue
            ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
        """)

        # 데일리 카운팅 초기 행 삽입
        await cur.execute("""
        INSERT INTO daily_quota_tracker (id, quota_date, request_count)
        VALUES (1, '1970-01-01T00:00:00Z', 0)
        ON CONFLICT(id) DO NOTHING
        """)
    logger.info("[DB] 테이블 스키마 초기화 완료.")


### Subscription func ###
async def add_subscription(user_id, ticker):
    sql = "INSERT INTO subscriptions (user_id, ticker) VALUES (%s, %s) ON CONFLICT(user_id, ticker) DO NOTHING"
    async with get_db_connection() as cur:
        await cur.execute(sql, (user_id, ticker.upper()))
    logger.info(f"[구독] {user_id}가 {ticker}를 구독하기 시작")


async def remove_subscription(user_id, ticker):
    sql = "DELETE FROM subscriptions WHERE user_id=%s AND ticker=%s"
    async with get_db_connection() as cur:
        await cur.execute(sql, (user_id, ticker.upper()))
    logger.info(f"[구독취소] {user_id}가 {ticker}를 구독 취소")


async def get_all_subscribed_tickers():
    sql = "SELECT DISTINCT ticker FROM subscriptions"
    tickers = []
    async with get_db_connection() as cur:
        await cur.execute(sql)
        rows = await cur.fetchall()
        tickers = [row['ticker'] for row in rows]
    return tickers


async def get_subscribed_tickers_for_user(user_id):
    sql = "SELECT ticker FROM subscriptions WHERE user_id = %s"
    tickers = []
    async with get_db_connection() as cur:
        await cur.execute(sql, (user_id,))
        rows = await cur.fetchall()
        tickers = [row['ticker'] for row in rows]
    return tickers


async def get_users_for_ticker(ticker):
    sql = "SELECT user_id FROM subscriptions WHERE ticker = %s"
    user_ids = []
    async with get_db_connection() as cur:
        await cur.execute(sql, (ticker,))
        rows = await cur.fetchall()
        user_ids = [row['user_id'] for row in rows]
    return user_ids


### SEC & Gemini func ###
async def get_last_accession_number(ticker):
    """ Return a last accession number for ticker from 'latest_filings' table. """
    sql = "SELECT last_accession_number FROM latest_filings WHERE ticker = %s"
    result = None
    async with get_db_connection() as cur:
        await cur.execute(sql, (ticker,))
        result = await cur.fetchone()
    return result['last_accession_number'] if result else None


async def update_last_filing_info(last_filing: FilingInfo):
    """ Update a new last filing info for ticker into 'latest_filings' table. """
    sql = """
    INSERT INTO latest_filings (ticker, last_accession_number, last_filing_type) VALUES (%s, %s, %s)
    ON CONFLICT(ticker) DO UPDATE SET
    last_accession_number = excluded.last_accession_number,
    last_filing_type = excluded.last_filing_type
    """
    async with get_db_connection() as cur:
        await cur.execute(sql, (last_filing.ticker, last_filing.accession_number, last_filing.filing_type))


async def update_analysis_queue(analysis_job: FilingInfo):
    """ UPSERT analysis queue for ticker into 'analysis_queue' table. retry_count 포함. """
    sql = """
    INSERT INTO analysis_queue
        (accession_number, ticker, filing_type, filing_date, filing_url, status, retry_count, last_modified_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT(accession_number) DO UPDATE SET
        status           = excluded.status,
        retry_count      = excluded.retry_count,
        last_modified_at = excluded.last_modified_at
    """
    async with get_db_connection() as cur:
        await cur.execute(sql,
                    (analysis_job.accession_number, analysis_job.ticker, analysis_job.filing_type,
                     analysis_job.filing_date, analysis_job.filing_url, analysis_job.status,
                     int(analysis_job.retry_count),           # 명시적 int 변환으로 타입 안전 보장
                     datetime.datetime.now(datetime.timezone.utc))
                    )


async def get_pending_jobs(limit: int) -> list[FilingInfo]:
    """
    PENDING 작업은 즉시, FAILED 작업은 마지막 시도 후 10분이 경과한 건만 가져옵니다.
    retry_count를 DB에서 읽어 FilingInfo에 주입합니다.
    """
    jobs: list[FilingInfo] = list()
    sql = """
            SELECT accession_number, ticker, filing_type, filing_date, filing_url,
                   status, retry_count
            FROM analysis_queue
            WHERE status = 'PENDING'
               OR (status = 'FAILED'
                   AND last_modified_at < NOW() - INTERVAL '10 minutes')
            ORDER BY last_modified_at ASC
            LIMIT %s
            """

    async with get_db_connection() as cur:
        await cur.execute(sql, (limit,))
        rows = await cur.fetchall()

        for row in rows:
            jobs.append(FilingInfo(
                accession_number=row['accession_number'],
                ticker=row['ticker'],
                filing_type=row['filing_type'],
                filing_date=str(row['filing_date']),  # DATE 컬럼 → datetime.date → str 변환
                filing_url=row['filing_url'],
                status=str(row['status']),
                retry_count=int(row['retry_count']),  # DB 값 명시적 int 변환
            ))
    return jobs


async def remove_analysis_queue(job: FilingInfo):
    sql = "DELETE FROM analysis_queue WHERE accession_number=%s"
    async with get_db_connection() as cur:
        await cur.execute(sql, (job.accession_number,))


async def insert_analysis_archive(analysis_job: FilingInfo):
    """
    Insert an analysis archive into 'analysis_archive' table.
    """
    sql = """
        INSERT INTO analysis_archive (accession_number, ticker, filing_type, filing_date, filing_url, gemini_analysis, analyzed_at) 
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
    # gemini_analysis가 dict이므로 json.dumps로 텍스트화
    gemini_analysis_json = json.dumps(analysis_job.gemini_analysis) if analysis_job.gemini_analysis else None

    async with get_db_connection() as cur:
        await cur.execute(sql,
                    (analysis_job.accession_number, analysis_job.ticker, analysis_job.filing_type, analysis_job.filing_date,
                     analysis_job.filing_url, gemini_analysis_json, datetime.datetime.now(datetime.timezone.utc))
                    )


### 상태 조회 ###
async def get_queue_status_counts() -> dict:
    """분석 큐의 상태별 건수를 반환합니다."""
    sql = """
    SELECT
        COUNT(*) FILTER (WHERE status = 'PENDING')       AS pending,
        COUNT(*) FILTER (WHERE status = 'FAILED')        AS failed,
        COUNT(*) FILTER (WHERE status = 'PERMANENT_FAIL') AS permanent_fail
    FROM analysis_queue
    """
    async with get_db_connection() as cur:
        await cur.execute(sql)
        row = await cur.fetchone()
        return {
            'pending':       int(row['pending']       or 0),
            'failed':        int(row['failed']        or 0),
            'permanent_fail': int(row['permanent_fail'] or 0),
        }


async def get_latest_archive(ticker: str) -> FilingInfo | None:
    """analysis_archive에서 특정 티커의 가장 최근 분석 결과를 반환합니다."""
    sql = """
    SELECT accession_number, ticker, filing_type, filing_date, filing_url, gemini_analysis
    FROM analysis_archive
    WHERE ticker = %s
    ORDER BY analyzed_at DESC
    LIMIT 1
    """
    async with get_db_connection() as cur:
        await cur.execute(sql, (ticker.upper(),))
        row = await cur.fetchone()
        if not row:
            return None
        # psycopg3는 JSONB 컬럼을 자동으로 dict로 역직렬화하지만, 방어적으로 처리
        gemini_analysis = row['gemini_analysis']
        if isinstance(gemini_analysis, str):
            import json as _json
            gemini_analysis = _json.loads(gemini_analysis)
        return FilingInfo(
            accession_number=row['accession_number'],
            ticker=row['ticker'],
            filing_type=row['filing_type'],
            filing_date=str(row['filing_date']),
            filing_url=row['filing_url'],
            status=AnalysisStatus.COMPLETED.value,
            gemini_analysis=gemini_analysis,
        )


### 할당량 테이블 ###
async def get_quota_status() -> dict:
    """현재 할당량 상태(카운트, 날짜)를 DB에서 가져옵니다."""
    sql = "SELECT quota_date, request_count FROM daily_quota_tracker WHERE id = 1"

    async with get_db_connection() as cur:
        await cur.execute(sql)
        row = await cur.fetchone()
        if row:
            return {
                    "date": row['quota_date'], # TIMESTAMPTZ 객체가 반환됨
                    "count": row['request_count']
            }

    logger.critical(f"[Quota] 할당량 추적기 테이블을 읽을 수 없습니다!")
    # 1970-01-01T00:00:00Z (UTC)
    return {"date": datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc), "count": 999}


async def update_quota_count(new_count: int, date_obj: datetime.datetime):
    """오늘의 할당량 카운트를 새 값으로 업데이트합니다."""
    sql = "UPDATE daily_quota_tracker SET request_count = %s, quota_date = %s WHERE id = 1"

    async with get_db_connection() as cur:
        await cur.execute(sql, (new_count, date_obj))
    logger.info(f"일일 할당량 카운트 업데이트: {new_count} (날짜: {date_obj.strftime('%Y-%m-%d')})")