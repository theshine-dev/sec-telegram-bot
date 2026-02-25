# bg_task.py
from datetime import datetime, timezone
import logging

from configs import config
from modules.telegram_helper import send_filing_notification_to_users
from modules import db_manager, gemini_helper, ticker_validator, sec_parser

from configs.types import AnalysisStatus, FilingInfo

logger = logging.getLogger(__name__)


async def _process_single_job(job: FilingInfo):
    """
    Helper function for processing a single analysis job.
    """
    try:
        logger.info(f"[Analyzer] 작업 시작: {job.ticker} - {job.accession_number} (시도 {job.retry_count + 1}회)")

        # 1. sec_parser로 공시 데이터 "추출"
        try:
            extracted_data = await sec_parser.extract_filing_data(job)
        except Exception as e:
            raise RuntimeError(f"[파싱 실패] {e}") from e

        if not extracted_data:
            raise ValueError("공시에서 유의미한 데이터를 추출하지 못했습니다.")

        # 2. 추출된 데이터를 Gemini로 "분석"
        try:
            analysis_result = await gemini_helper.get_comprehensive_analysis(
                extracted_data,
                job.ticker,
                job.filing_type
            )
        except Exception as e:
            raise RuntimeError(f"[Gemini 실패] {e}") from e

        if not analysis_result:
            raise ValueError("Gemini API 분석에 실패했거나 결과가 비어있습니다.")

        job.update_gemini_analysis(analysis_result)
        job.update_status(AnalysisStatus.COMPLETED.value)

        # 3. DB 저장 및 Telegram 발송
        try:
            await db_manager.insert_analysis_archive(job)
            await send_filing_notification_to_users(job)
            await db_manager.remove_analysis_queue(job)
        except Exception as e:
            raise RuntimeError(f"[저장/발송 실패] {e}") from e

        logger.info(f"[Analyzer] {job.ticker} - {job.accession_number} 공시 분석 완료 및 사용자 발송 완료.")

        return True  # success indicator for quota counting

    except Exception as e:
        logger.error(
            f"[Analyzer] {job.ticker} - {job.accession_number} 처리 실패 "
            f"(시도 {job.retry_count + 1}회): {e}",
            exc_info=True
        )

        # 실패 시, 재시도 횟수 증가 및 상태 업데이트
        job.retry_count += 1
        if job.retry_count >= config.MAX_RETRY_LIMIT:
            # 최대 재시도 횟수 도달 시 '영구 실패'
            job.update_status(AnalysisStatus.PERMANENT_FAIL.value)
            logger.warning(
                f"[Analyzer] {job.ticker} - {job.accession_number} 최대 재시도({config.MAX_RETRY_LIMIT}) 횟수 도달. 영구 실패로 처리.")
        else:
            # 아닐 경우 '실패' (다음 재시도 대기)
            job.update_status(AnalysisStatus.FAILED.value)

        await db_manager.update_analysis_queue(job)

        return False  # failure indicator


async def discover_new_filings():
    """
    Find new filings for all subscribed tickers, Update 'analysis_queue', 'latest_filings' tables.
    """
    logger.info("[Discover] 새로운 공시 탐색 시작...")
    tickers = await db_manager.get_all_subscribed_tickers()

    for ticker in tickers:
        try:
            cik = ticker_validator.get_cik_for_ticker(ticker)
            if not cik: continue

            # 1. get last filing info
            last_accession_num = await db_manager.get_last_accession_number(ticker)

            filings_list = await sec_parser.get_recent_filings_list(cik)  # "accession_number", "form_type", "filing_url"
            new_filings_to_process = []
            for filing in filings_list:
                if filing['accession_number'] == last_accession_num:
                    logger.debug(f"[Discover] {ticker}에 새로운 공시가 없습니다.")
                    break
                new_filings_to_process.append(filing)

            if new_filings_to_process:
                new_filings_to_process = new_filings_to_process[:config.DISCOVER_FILING_AMOUNT]
                logger.info(f"[Discover] {ticker}에서 {len(new_filings_to_process)}개의 새로운 공시 발견.")
                for new_filing in reversed(new_filings_to_process): # 오래된 공시부터 DB 삽입
                    # 2. 'analysis_queue' 테이블에 'pending' 상태로 삽입 (UPSERT 사용)
                    await db_manager.update_analysis_queue(FilingInfo(
                        accession_number=new_filing['accession_number'],
                        ticker=ticker,
                        filing_type=new_filing['form_type'],
                        filing_date=new_filing['filing_date'],
                        filing_url=new_filing['filing_url'],
                        status=AnalysisStatus.PENDING.value,
                    ))

                # 3. 'latest_filings' 테이블의 기준 ID를 가장 최신 공시로 업데이트
                await db_manager.update_last_filing_info(FilingInfo(
                    accession_number=new_filings_to_process[0]['accession_number'],
                    ticker=ticker,
                    filing_type=new_filings_to_process[0]['form_type'],
                    filing_date=new_filings_to_process[0]['filing_date'],
                    filing_url=new_filings_to_process[0]['filing_url'],
                    status=AnalysisStatus.PENDING.value
                    )
                )
        except Exception as e:
            logger.error(
                f"[Discover] {ticker} 처리 중 오류 — 이 티커 건너뜀: {e}",
                exc_info=True
            )
            continue  # 다음 티커로


async def process_analysis_queue():
    """
    Get pending jobs within the limit from 'analysis_queue', and Process(Analyze) them.
    """
    logger.debug("[Analyzer] 처리해야할 작업이 있는지 탐색...")

    current_count, has_quota = await calc_current_quota_status()
    if not has_quota:
        logger.warning(f"[Analyzer] 일일 API 할당량(50)에 도달했습니다. 내일까지 작업을 중지합니다.")
        return
    # 1. 큐에서 'pending' 상태의 작업을 quota만큼 가져옵니다. -> free tier 1/min limit
    jobs = await db_manager.get_pending_jobs(has_quota)
    if not jobs:
        logger.info("[Analyzer] 처리할 작업이 없습니다.")
        return

    logger.info(f"[Analyzer] {len(jobs)} 개의 처리할 작업을 가져왔습니다.")

    # 각 작업 처리 후 성공 시에만 할당량 카운트 증가
    success_count = 0
    for job in jobs:
        result = await _process_single_job(job)
        if result:
            success_count += 1

    if success_count > 0:
        new_count = current_count + success_count
        await db_manager.update_quota_count(new_count, datetime.now(timezone.utc))
        logger.info(f"[Analyzer] API 할당량 사용: {success_count}건 (오늘 총 {new_count}/50 건)")


async def calc_current_quota_status() -> tuple[int, int]:
    """
    Calculate quota satisfied Gemini Usage Quota.
    Return integer 0 or 1 or 2.
    :return:
    """
    # (Google의 할당량은 보통 UTC/PT 기준이므로 UTC가 가장 안전합니다)
    today_utc_str = datetime.now(timezone.utc)
    quota_status = await db_manager.get_quota_status()

    current_count = 0
    # DB에 저장된 날짜가 오늘인지 확인
    if quota_status['date'].date() == today_utc_str.date():
        # 오늘 날짜: 기존 카운트를 사용
        current_count = quota_status['count']
    else:
        # 날짜가 다름: '날짜가 리셋'되었으므로 카운트를 0으로 초기화
        current_count = 0

    # 2-3. (핵심) 일일 할당량을 초과했는지 검사합니다.
    daily_limit = config.GEMINI_DAILY_LIMIT
    if current_count >= daily_limit:
        return daily_limit, 0

    # --- 3. 처리할 작업 개수 계산 (RPM + RPD) ---
    remaining_today = daily_limit - current_count  # 오늘 남은 횟수 (예: 3)
    rpm_limit = config.GEMINI_RPM_LIMIT  # 1분에 처리할 횟수

    # 오늘 남은 횟수와 분당 횟수 중 '더 적은 값'을 선택
    return current_count, min(rpm_limit, remaining_today)
