#sec_parser.py
import asyncio
import logging
import requests

from edgar import set_identity, Filing, find
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
    봇 시작 시 edgartools의 ID를 설정합니다. (필수)
    """
    logger.info(f"SEC Parser(edgartools) ID 설정: {config.SEC_USER_AGENT}")
    # set_identity는 동기 함수이므로 스레드 풀에서 실행
    await _run_in_executor(lambda: set_identity(config.SEC_USER_AGENT))


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
                        cik=cik,
                        company=ticker,
                        form=filing_info.filing_type,
                        filing_date=filing_info.filing_date,
                        accession_no=filing_info.accession_number,
            )
        )

        data = ExtractedFilingData()

        # 8-K: extract plain text
        if filing_info.filing_type == "8-K":
            data.clean_8k_text = await _run_in_executor(lambda: filing.text())
            logger.info(f"[Parser] {ticker} 8-K 파싱 완료 ({len(data.clean_8k_text or '')}자)")

        # 10-K / 10-Q: extract structured data
        if filing_info.filing_type in ["10-K", "10-Q"]:
            filing_obj: TenK | TenQ = filing.obj()

            if filing_obj.management_discussion:
                data.mda_text = await _run_in_executor(lambda: filing_obj.management_discussion)

            if filing_obj.risk_factors:
                data.risk_factors_text = await _run_in_executor(lambda: filing_obj.risk_factors)

            if filing_obj.income_statement:
                is_df = filing_obj.income_statement.to_dataframe()
                latest_period = is_df.columns[0]
                data.financial_data = {}
                try:
                    data.financial_data["Revenue"] = is_df.loc['Revenues', latest_period]
                except KeyError:
                    logger.warning(f"[Parser] {ticker} 'Revenues' XBRL 태그를 찾을 수 없습니다.")
                try:
                    data.financial_data["NetIncome"] = is_df.loc['NetIncomeLoss', latest_period]
                except KeyError:
                    logger.warning(f"[Parser] {ticker} 'NetIncomeLoss' XBRL 태그를 찾을 수 없습니다.")

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
