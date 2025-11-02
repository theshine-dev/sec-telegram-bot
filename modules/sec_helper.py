import asyncio
import logging

import requests
from bs4 import BeautifulSoup

from configs import config
from configs.types import FilingType

logger = logging.getLogger(__name__)

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
            lambda: requests.get(url, headers=config.SEC_HEADERS, timeout=10)
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
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_clean}/{primary_doc_name}"

            # 완성된 딕셔너리를 리스트에 추가합니다.
            filings_data.append({
                "accession_number": accession_no_raw,
                "form_type": form_type_enum.value,
                "filing_url": filing_url
            })

        return filings_data

    except requests.RequestException as e:
        print(f"Error fetching recent filings list for CIK {cik}: {e}")
        # 에러 발생 시 빈 리스트를 반환하여 프로그램 중단을 방지합니다.
        return []

async def get_filing_text(url):
    """공시 URL에서 텍스트 내용만 추출합니다."""
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.get(url, headers=config.SEC_HEADERS, timeout=10)
        )
        response.raise_for_status()
        # BeautifulSoup를 사용하여 HTML에서 텍스트만 추출
        soup = BeautifulSoup(response.content, 'html.parser')
        return soup.get_text(separator='\n', strip=True)
    except requests.RequestException as e:
        print(f"Error fetching filing text from {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"공시 원문 파싱 중 오류 (URL: {url}): {e}", exc_info=True)
        return None
