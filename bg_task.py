# bg_task.py
from datetime import datetime, timezone
import logging

from telegram_helper import send_filing_notification_to_users

import db_manager
import gemini_helper
import sec_helper
import ticker_validator

from config.types import AnalysisStatus, FilingInfo

logger = logging.getLogger(__name__)

async def discover_new_filings():
    """
    Find new filings for all subscribed tickers, Update 'analysis_queue', 'latest_filings' tables.
    """
    logger.info("[Discover] 새로운 공시 탐색 시작...")
    tickers = await db_manager.get_all_subscribed_tickers()

    for ticker in tickers:
        cik = ticker_validator.get_cik_for_ticker(ticker)
        if not cik: continue

        # 1. get last filing info
        last_accession_num = await db_manager.get_last_accession_number(ticker)

        filings_list = await sec_helper.get_recent_filings_list(cik)  # "accession_number", "form_type", "filing_url"
        new_filings_to_process = []
        for filing in filings_list:
            if filing['accession_number'] == last_accession_num:
                logger.debug(f"[Discover] {ticker}에 새로운 공시가 없습니다.")
                break
            new_filings_to_process.append(filing)

        if new_filings_to_process:
            new_filings_to_process = new_filings_to_process[:5]
            logger.info(f"[Discover] {ticker}에서 {len(new_filings_to_process)}개의 새로운 공시 발견.")
            for new_filing in reversed(new_filings_to_process): # 오래된 공시부터 DB 삽입
                # 2. 'analysis_queue' 테이블에 'pending' 상태로 삽입 (UPSERT 사용)
                await db_manager.update_analysis_queue(FilingInfo(
                    accession_number=new_filing['accession_number'],
                    ticker=ticker,
                    filing_type=new_filing['form_type'],
                    filing_url=new_filing['filing_url'],
                    status=AnalysisStatus.PENDING.value
                ))

            # 3. 'latest_filings' 테이블의 기준 ID를 가장 최신 공시로 업데이트
            await db_manager.update_last_filing_info(FilingInfo(
                accession_number=new_filings_to_process[0]['accession_number'],
                ticker=ticker,
                filing_type=new_filings_to_process[0]['form_type'],
                filing_url=new_filings_to_process[0]['filing_url'],
                status=AnalysisStatus.PENDING.value
                )
            )


async def process_analysis_queue():
    """
    Get pending jobs withing the limit from 'analysis_queue', and Process(Analyze) them.
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

    new_count = current_count + len(jobs)
    await db_manager.update_quota_count(new_count, datetime.now(timezone.utc))
    logger.info(f"[Analyzer] API 할당량 사용: {len(jobs)}건 (오늘 총 {new_count}/50 건)")


    for job in jobs:
        logger.info(f"[Analyzer] {len(jobs)} 개의 처리할 작업을 가져왔습니다.")
        try:
            # 2. Gemini 분석 수행
            filing_text = await sec_helper.get_filing_text(job.filing_url)
            analysis_result = await gemini_helper.get_comprehensive_analysis(filing_text, job.ticker,)

            job.update_gemini_analysis(analysis_result)
            job.update_status(AnalysisStatus.COMPLETED.value)

            # 3. 분석 성공 시, 아카이브 DB에 기록, 사용자에게 전송, queue 삭제
            await db_manager.insert_analysis_archive(job)
            await send_filing_notification_to_users(job)
            await db_manager.remove_analysis_queue(job)
            logger.info(f"[Analyzer] {job.ticker} - {job.accession_number} 공시 분석 완료 및 사용자 발송 완료.")

        except Exception as e:
            logger.error(f"[Analyzer] {job.ticker} - {job.accession_number} 처리 실패: {e}")
            # 4. 실패 시, 상태를 'FAILED'로 변경 (재시도 로직 고려 필요)
            job.update_status(AnalysisStatus.FAILED.value)
            await db_manager.update_analysis_queue(job)


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
    if current_count >= 50:
        return 50, 0

    # --- 3. 처리할 작업 개수 계산 (RPM + RPD) ---
    remaining_today = 50 - current_count  # 오늘 남은 횟수 (예: 3)
    rpm_limit = 2  # 1분에 처리할 횟수

    # 오늘 남은 횟수와 분당 횟수 중 '더 적은 값'을 선택
    return current_count, min(rpm_limit, remaining_today)