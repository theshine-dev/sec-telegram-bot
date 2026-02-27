"""
test_e2e.py — 전체 파이프라인 통합 테스트 (가짜 데이터 → Gemini → 포맷 → Telegram)
DB 없이 TELEGRAM_CHAT_ID에 직접 전송.

실행:
    python -m tests.test_e2e
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from configs.types import ExtractedFilingData, FilingInfo
from configs.config import TELEGRAM_CHAT_ID, TELEGRAM_BOT_TOKEN
from modules.gemini_helper import get_comprehensive_analysis, shorten_analysis
from modules.telegram_helper import _build_message, _get_bot, TELEGRAM_MAX_LENGTH
from telegram.constants import ParseMode

# --- 가짜 추출 데이터 ---

fake_8k_data = ExtractedFilingData(
    clean_8k_text=(
        "On February 13, 2026, Matthew Muta notified Palladyne AI Corp. "
        "of his resignation as Chief Executive Officer, effective February 28, 2026. "
        "The Board has initiated a search for a permanent successor."
    )
)

fake_10k_data = ExtractedFilingData(
    financial_data={"Revenue": 125_000_000, "NetIncome": 12_500_000},
    mda_text=(
        "Revenue increased 15% YoY driven by cloud segment growth. "
        "Operating margin expanded to 12% from 9% in the prior year."
    ),
    risk_factors_text=(
        "Competition in the AI market is intensifying. "
        "Key risks include talent retention, regulatory changes in AI policy, "
        "and macroeconomic headwinds."
    ),
)

fake_filing_8k = FilingInfo(
    accession_number="0001234567-26-000001",
    ticker="AIPAL",
    filing_type="8-K",
    filing_date="2026-02-13",
    filing_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/0001234567-26-000001-index.htm",
    status="COMPLETED",
)

fake_filing_10k = FilingInfo(
    accession_number="0001234567-26-000002",
    ticker="FAKECORP",
    filing_type="10-K",
    filing_date="2026-02-19",
    filing_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456726000002/0001234567-26-000002-index.htm",
    status="COMPLETED",
)

# --- 테스트 러너 ---

def run_async_test(name: str, coro):
    try:
        asyncio.run(coro)
        print(f"[PASS] {name}")
    except AssertionError as e:
        print(f"[FAIL] {name} - AssertionError: {e}")
    except Exception as e:
        print(f"[FAIL] {name} - {type(e).__name__}: {e}")


# --- 공통 파이프라인 ---

async def e2e_pipeline(extracted_data: ExtractedFilingData, filing_info: FilingInfo):
    """가짜 데이터 → Gemini 분석 → 메시지 포맷 → 오버플로우 처리 → Telegram 전송."""
    assert TELEGRAM_CHAT_ID, "TELEGRAM_CHAT_ID가 설정되지 않음"
    assert TELEGRAM_BOT_TOKEN, "TELEGRAM_BOT_TOKEN이 설정되지 않음"

    # Step 1: Gemini 분석
    analysis = await get_comprehensive_analysis(
        extracted_data, filing_info.ticker, filing_info.filing_type
    )
    assert analysis is not None, "Gemini 분석 결과가 None"
    for key in ["executive_summary", "objective_facts", "positive_signals",
                "potential_risks", "overall_opinion"]:
        assert key in analysis, f"분석 결과에 키 '{key}' 없음"
    print(f"  [INFO] Gemini 분석 완료. keys={list(analysis.keys())}")

    # Step 2: 메시지 포맷
    msg = _build_message(filing_info, analysis)
    print(f"  [INFO] 포맷 후 메시지 길이: {len(msg)} chars")

    # Step 3: 오버플로우 → Gemini 재요약 → 강제 절단(안전망)
    if len(msg) > TELEGRAM_MAX_LENGTH:
        print(f"  [INFO] 오버플로우 감지 ({len(msg)} chars), 재요약 요청...")
        analysis = await shorten_analysis(analysis)
        msg = _build_message(filing_info, analysis)
        print(f"  [INFO] 재요약 후 길이: {len(msg)} chars")

        if len(msg) > TELEGRAM_MAX_LENGTH:
            tail = "\n\n<i>⚠️ 내용이 너무 길어 일부가 생략되었습니다.</i>"
            msg = msg[: TELEGRAM_MAX_LENGTH - len(tail)] + tail
            print(f"  [INFO] 강제 절단 후 길이: {len(msg)} chars")

    assert len(msg) <= TELEGRAM_MAX_LENGTH, (
        f"최종 메시지가 여전히 {TELEGRAM_MAX_LENGTH}자 초과: {len(msg)} chars"
    )

    # Step 4: Telegram 전송
    bot = _get_bot()
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=msg,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    print(f"  [INFO] Telegram 전송 완료 → chat_id={TELEGRAM_CHAT_ID}")


if __name__ == "__main__":
    print("=== test_e2e.py ===\n")

    run_async_test("Scenario 1: E2E 8-K 파이프라인", e2e_pipeline(fake_8k_data, fake_filing_8k))
    run_async_test("Scenario 2: E2E 10-K 파이프라인", e2e_pipeline(fake_10k_data, fake_filing_10k))

    print()
