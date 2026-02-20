#sec_parser.py
import asyncio
import logging
import requests

from edgar import set_identity, Filing, find, enable_local_storage
from edgar.financials import Financials
from edgar.company_reports import TenK, TenQ, EightK

from configs import config
from configs.types import FilingInfo, FilingType, ExtractedFilingData
from modules import ticker_validator


logger = logging.getLogger(__name__)


# edgartools의 동기 함수를 비동기 래퍼로 감싸기
async def _run_in_executor(sync_func):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, sync_func)


async def init_parser():
    """
    봇 시작 시 edgartools의 ID 및 로컬 캐시를 설정합니다. (필수)
    """
    logger.info(f"SEC Parser(edgartools) ID 설정: {config.SEC_USER_AGENT}")
    await _run_in_executor(lambda: set_identity(config.SEC_USER_AGENT))

    # 로컬 캐싱 활성화: 동일 공시 재요청 시 SEC API 호출 없이 로컬에서 로드
    config.EDGAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    await _run_in_executor(lambda: enable_local_storage(str(config.EDGAR_CACHE_DIR)))
    logger.info(f"[Parser] edgartools 로컬 캐싱 활성화: {config.EDGAR_CACHE_DIR}")


async def extract_filing_data(filing_info: FilingInfo) -> ExtractedFilingData:
    """
    FilingInfo를 받아 edgartools로 핵심 데이터를 추출하고
    ExtractedFilingData 객체를 반환합니다.
    """
    ticker = filing_info.ticker

    cik = ticker_validator.get_cik_for_ticker(ticker)

    if not cik:
        logger.error(f"[Parser] {ticker}의 CIK를 로컬 tickers.json에서 찾을 수 없습니다! (ticker_validator 확인 필요)")
        raise ValueError(f"{ticker}의 CIK를 로컬 tickers.json에서 찾을 수 없습니다.")

    logger.debug(f"[Parser] {ticker}({cik}) - {filing_info.accession_number} 파싱 시작...")

    try:
        # https://edgartools.readthedocs.io/en/latest/data-objects/
        filing: Filing = await _run_in_executor(
            lambda: Filing(
                        cik=int(cik),
                        company=ticker,
                        form=filing_info.filing_type,
                        filing_date=filing_info.filing_date,
                        accession_no=filing_info.accession_number,
            )
        )

        data = ExtractedFilingData()

        # 8-K: 구조화 추출 (프레스릴리즈 우선, 없으면 전문 폴백)
        if filing_info.filing_type == "8-K":
            eightk = await _run_in_executor(lambda: filing.obj())

            # 1. Item 코드 목록 추출 (예: ["2.02", "9.01"])
            try:
                raw_items = eightk.items
                if raw_items:
                    data.event_items = [str(item) for item in raw_items]
                    logger.debug(f"[Parser] {ticker} 8-K Items: {data.event_items}")
            except Exception as e:
                logger.debug(f"[Parser] {ticker} 8-K Item 목록 추출 실패: {e}")

            # 2. 프레스릴리즈 우선 추출
            try:
                if eightk.has_press_release:
                    prs = eightk.press_releases
                    if prs:
                        data.press_release_text = prs[0].content
                        logger.info(f"[Parser] {ticker} 8-K 프레스릴리즈 추출 완료 ({len(data.press_release_text)}자)")
            except Exception as e:
                logger.debug(f"[Parser] {ticker} 프레스릴리즈 추출 실패: {e}")

            # 3. 프레스릴리즈 없으면 전문 텍스트 폴백
            if not data.press_release_text:
                data.clean_8k_text = await _run_in_executor(lambda: filing.text())
                logger.info(f"[Parser] {ticker} 8-K 파싱 완료 ({len(data.clean_8k_text or '')}자)")
            else:
                logger.info(f"[Parser] {ticker} 8-K 파싱 완료 (프레스릴리즈 {len(data.press_release_text)}자)")

        # 10-K / 10-Q: extract structured data
        if filing_info.filing_type in ["10-K", "10-Q"]:
            # filing.obj()는 네트워크/디스크 I/O가 포함된 동기 호출 → executor 필수
            filing_obj: TenK | TenQ = await _run_in_executor(lambda: filing.obj())

            if filing_obj.management_discussion:
                data.mda_text = filing_obj.management_discussion

            if filing_obj.risk_factors:
                data.risk_factors_text = filing_obj.risk_factors

            # financials API로 재무 데이터 추출 (표준화된 메서드 사용)
            try:
                financials = filing_obj.financials
                if financials:
                    def _extract_financials(fin):
                        result = {}
                        for key, method in [
                            # 손익계산서
                            ("Revenue",         fin.get_revenue),
                            ("GrossProfit",     fin.get_gross_profit),
                            ("OperatingIncome", fin.get_operating_income),
                            ("NetIncome",       fin.get_net_income),
                            ("EPS",             fin.get_earnings_per_share),
                            # 현금흐름표
                            ("OperatingCashFlow", fin.get_operating_cash_flow),
                            ("FreeCashFlow",      fin.get_free_cash_flow),
                            # 재무상태표
                            ("TotalAssets", fin.get_total_assets),
                            ("TotalDebt",   fin.get_total_debt),
                            ("Cash",        fin.get_cash_and_equivalents),
                        ]:
                            try:
                                val = method()
                                if val is not None:
                                    result[key] = val
                            except Exception:
                                pass
                        return result

                    data.financial_data = await _run_in_executor(lambda: _extract_financials(financials))
                    logger.info(f"[Parser] {ticker} 재무 데이터 추출 완료: {list(data.financial_data.keys())}")
            except Exception as e:
                logger.warning(f"[Parser] {ticker} 재무 데이터 추출 실패: {e}")

            logger.info(f"[Parser] {ticker} {filing_info.filing_type} 파싱 완료 (MD&A: {len(data.mda_text or '')}자)")

        return data

    except Exception as e:
        logger.error(f"[Parser] {ticker} {filing_info.accession_number} 파싱 중 심각한 오류: {e}", exc_info=True)
        raise


async def get_recent_filings_list(cik):
    """
    CIK를 사용하여 최근 제출된 모든 주요 공시의 '목록'을 가져옵니다.
    최신순으로 정렬된 딕셔너리 리스트를 반환합니다.

    반환값 예시:
    [
        {'accession_number': '0001...', 'form_type': FilingType.FORM_4, 'filing_url': 'http...'},
        {'accession_number': '0002...', 'form_type': FilingType.FORM_8K, 'filing_url': 'http...'}
    ]
    """
    filings_data = []
    try:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"

        # 비동기 처리
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,  # 기본 스레드 풀 사용
            lambda: requests.get(url, headers=config.SEC_TICKER_HEADER, timeout=10)
        )
        response.raise_for_status()  # HTTP 에러 체크

        data = response.json()

        recent_filings = data['filings']['recent']

        # API가 반환하는 최근 문서 목록 전체를 순회합니다.
        for i in range(len(recent_filings['accessionNumber'])):
            form_str = recent_filings['form'][i]

            # 우리가 Enum에 정의한 주요 공시 타입인지 확인합니다.
            try:
                form_type_enum = FilingType(form_str)
            except ValueError:
                # Enum에 없는 타입(예: 'SC 13G')이면 건너뜁니다.
                continue

            # 공시 정보를 딕셔너리 형태로 만듭니다.
            accession_no_raw = recent_filings['accessionNumber'][i]
            accession_no_clean = accession_no_raw.replace('-', '')
            primary_doc_name = recent_filings['primaryDocument'][i]
            filing_date = recent_filings['filingDate'][i]
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_clean}/{primary_doc_name}"

            # 완성된 딕셔너리를 리스트에 추가합니다.
            filings_data.append({
                "accession_number": accession_no_raw,
                "form_type": form_type_enum.value,
                "filing_date": filing_date,
                "filing_url": filing_url
            })

        return filings_data

    except requests.RequestException as e:
        logger.error(f"Error fetching recent filings list for CIK {cik}: {e}")
        # 에러 발생 시 빈 리스트를 반환하여 프로그램 중단을 방지합니다.
        return []
