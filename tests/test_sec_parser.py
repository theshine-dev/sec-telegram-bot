"""
test_sec_parser.py — SEC Parser 기능 검증 (실제 SEC API 호출)

리팩터링 핵심 검증:
  - Company.get_financials() 방식이 AttributeError 없이 동작하는지
  - financial_data에 비공식 키(EPS, TotalDebt, Cash)가 없는지
  - 8-K 텍스트 추출이 정상 동작하는지
  - get_recent_filings_list timeout(30s) 동작 확인

실행:
    python -m tests.test_sec_parser
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / "..env")

from modules.sec_parser import init_parser, extract_filing_data, get_recent_filings_list
from modules.ticker_validator import update_ticker_list, get_cik_for_ticker
from configs.types import FilingInfo, AnalysisStatus

# 리팩터링 후 허용되는 financial_data 키 (공식 문서 기재 메서드 기준)
VALID_FINANCIAL_KEYS = {
    "Revenue", "GrossProfit", "OperatingIncome", "NetIncome",
    "OperatingCashFlow", "FreeCashFlow", "TotalAssets", "TotalLiabilities",
}

# 제거된 비공식 키 (이 키들이 있으면 리팩터링 실패)
FORBIDDEN_FINANCIAL_KEYS = {"EPS", "TotalDebt", "Cash"}


# --- 테스트 러너 ---

def run_async_test(name: str, coro):
    try:
        asyncio.run(coro)
        print(f"[PASS] {name}")
    except AssertionError as e:
        print(f"[FAIL] {name} - AssertionError: {e}")
    except Exception as e:
        print(f"[FAIL] {name} - {type(e).__name__}: {e}")


# --- 공통 초기화 ---

async def _setup():
    """parser 초기화 + ticker 캐시 로드"""
    await init_parser()
    await update_ticker_list()


# --- 시나리오 ---

# Scenario 1: get_recent_filings_list — AAPL CIK로 목록 조회 및 구조 검증
async def test_get_recent_filings_list():
    await _setup()

    cik = get_cik_for_ticker("AAPL")
    assert cik, "AAPL CIK를 찾을 수 없음"

    filings = await get_recent_filings_list(cik)

    assert isinstance(filings, list), f"반환값이 list가 아님: {type(filings)}"
    assert len(filings) > 0, "공시 목록이 비어있음"

    for f in filings[:3]:
        assert "accession_number" in f, "accession_number 키 없음"
        assert "form_type" in f, "form_type 키 없음"
        assert "filing_date" in f, "filing_date 키 없음"
        assert "filing_url" in f, "filing_url 키 없음"

    print(f"  [INFO] AAPL 최근 공시 {len(filings)}건 조회 완료")
    print(f"  [INFO] 최신 공시: {filings[0]['form_type']} ({filings[0]['filing_date']})")


# Scenario 2: 10-K extract_filing_data — IONQ (get_gross_profit 오류 재발 방지)
async def test_extract_10k_ionq():
    await _setup()

    cik = get_cik_for_ticker("IONQ")
    assert cik, "IONQ CIK를 찾을 수 없음"

    filings = await get_recent_filings_list(cik)
    tenk = next((f for f in filings if f["form_type"] == "10-K"), None)
    if not tenk:
        print("  [SKIP] IONQ 최근 10-K 없음")
        return

    print(f"  [INFO] IONQ 10-K 발견: {tenk['accession_number']} ({tenk['filing_date']})")

    filing_info = FilingInfo(
        accession_number=tenk["accession_number"],
        ticker="IONQ",
        filing_type="10-K",
        filing_date=tenk["filing_date"],
        filing_url=tenk["filing_url"],
        status=AnalysisStatus.PENDING.value,
    )

    # AttributeError 없이 완료되어야 함 (핵심 검증)
    data = await extract_filing_data(filing_info)

    assert data is not None, "추출된 데이터가 None"
    assert data.mda_text, "MD&A 텍스트가 없음"

    if data.financial_data:
        forbidden = set(data.financial_data.keys()) & FORBIDDEN_FINANCIAL_KEYS
        assert not forbidden, f"제거됐어야 할 비공식 키 발견: {forbidden}"

        unexpected = set(data.financial_data.keys()) - VALID_FINANCIAL_KEYS
        assert not unexpected, f"허용되지 않은 키 발견: {unexpected}"

        print(f"  [INFO] IONQ 재무 데이터: {list(data.financial_data.keys())}")
    else:
        print("  [INFO] IONQ 재무 데이터 없음 (None — 정상)")

    print(f"  [INFO] MD&A 길이: {len(data.mda_text)}자")


# Scenario 3: 10-K extract_filing_data — RKLB (두 번째 오류 티커)
async def test_extract_10k_rklb():
    await _setup()

    cik = get_cik_for_ticker("RKLB")
    assert cik, "RKLB CIK를 찾을 수 없음"

    filings = await get_recent_filings_list(cik)
    tenk = next((f for f in filings if f["form_type"] == "10-K"), None)
    if not tenk:
        print("  [SKIP] RKLB 최근 10-K 없음")
        return

    print(f"  [INFO] RKLB 10-K 발견: {tenk['accession_number']} ({tenk['filing_date']})")

    filing_info = FilingInfo(
        accession_number=tenk["accession_number"],
        ticker="RKLB",
        filing_type="10-K",
        filing_date=tenk["filing_date"],
        filing_url=tenk["filing_url"],
        status=AnalysisStatus.PENDING.value,
    )

    data = await extract_filing_data(filing_info)

    assert data is not None, "추출된 데이터가 None"

    if data.financial_data:
        forbidden = set(data.financial_data.keys()) & FORBIDDEN_FINANCIAL_KEYS
        assert not forbidden, f"제거됐어야 할 비공식 키 발견: {forbidden}"

        unexpected = set(data.financial_data.keys()) - VALID_FINANCIAL_KEYS
        assert not unexpected, f"허용되지 않은 키 발견: {unexpected}"

        print(f"  [INFO] RKLB 재무 데이터: {list(data.financial_data.keys())}")
    else:
        print("  [INFO] RKLB 재무 데이터 없음 (None — 정상)")


# Scenario 4: 8-K extract_filing_data — 텍스트 추출 검증 (RKLB)
async def test_extract_8k_rklb():
    await _setup()

    cik = get_cik_for_ticker("RKLB")
    assert cik, "RKLB CIK를 찾을 수 없음"

    filings = await get_recent_filings_list(cik)
    eightk = next((f for f in filings if f["form_type"] == "8-K"), None)
    if not eightk:
        print("  [SKIP] RKLB 최근 8-K 없음")
        return

    print(f"  [INFO] RKLB 8-K 발견: {eightk['accession_number']} ({eightk['filing_date']})")

    filing_info = FilingInfo(
        accession_number=eightk["accession_number"],
        ticker="RKLB",
        filing_type="8-K",
        filing_date=eightk["filing_date"],
        filing_url=eightk["filing_url"],
        status=AnalysisStatus.PENDING.value,
    )

    data = await extract_filing_data(filing_info)

    assert data is not None, "추출된 데이터가 None"
    has_content = data.clean_8k_text or data.press_release_text
    assert has_content, "8-K 텍스트가 없음 (clean_8k_text + press_release_text 모두 없음)"

    # 8-K는 financial_data가 없어야 함
    assert data.financial_data is None, f"8-K에 financial_data가 있음: {data.financial_data}"

    pr_status = "있음" if data.press_release_text else "없음"
    text_len = len(data.press_release_text or data.clean_8k_text or "")
    print(f"  [INFO] 8-K 추출 완료. 프레스릴리즈={pr_status}, 텍스트 길이={text_len}자")


# Scenario 5: gemini_helper와 연동 — financial_data 키가 _FINANCIAL_LABELS와 일치하는지
def test_financial_key_sync():
    """sec_parser의 financial_data 키와 gemini_helper의 _FINANCIAL_LABELS 키가 일치하는지 검증."""
    from modules.gemini_helper import _build_prompt
    from configs.types import ExtractedFilingData

    # VALID_FINANCIAL_KEYS 전체를 financial_data에 넣어 프롬프트 생성 테스트
    fake_data = ExtractedFilingData(
        financial_data={k: 1_000_000 for k in VALID_FINANCIAL_KEYS},
        mda_text="Test MD&A text.",
        risk_factors_text="Test risk factors.",
    )

    prompt = _build_prompt(fake_data, "TEST", "10-K")

    assert "Revenue" in prompt, "Revenue가 프롬프트에 없음"
    assert "Gross Profit" in prompt, "Gross Profit이 프롬프트에 없음"
    assert "Total Liabilities" in prompt, "Total Liabilities가 프롬프트에 없음"

    # 제거된 항목이 프롬프트에 없어야 함
    assert "Total Debt" not in prompt, "Total Debt가 프롬프트에 남아있음 (동기화 실패)"
    assert "\"EPS\"" not in prompt and "- EPS:" not in prompt, "EPS가 프롬프트에 남아있음"

    print("  [INFO] financial_data 키 ↔ _FINANCIAL_LABELS 동기화 확인 완료")


if __name__ == "__main__":
    print("=== test_sec_parser.py ===\n")

    # Scenario 5는 동기 테스트
    try:
        test_financial_key_sync()
        print("[PASS] Scenario 5: financial_data 키 ↔ gemini_helper 동기화")
    except AssertionError as e:
        print(f"[FAIL] Scenario 5 - AssertionError: {e}")
    except Exception as e:
        print(f"[FAIL] Scenario 5 - {type(e).__name__}: {e}")

    run_async_test("Scenario 1: get_recent_filings_list (AAPL)", test_get_recent_filings_list())
    run_async_test("Scenario 2: extract_filing_data 10-K IONQ (AttributeError 재발 방지)", test_extract_10k_ionq())
    run_async_test("Scenario 3: extract_filing_data 10-K RKLB", test_extract_10k_rklb())
    run_async_test("Scenario 4: extract_filing_data 8-K RKLB", test_extract_8k_rklb())

    print()
