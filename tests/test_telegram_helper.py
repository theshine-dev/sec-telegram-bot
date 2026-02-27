"""
test_telegram_helper.py — 메시지 포맷 검증 + 실제 Telegram 전송 테스트

실행:
    python -m tests.test_telegram_helper
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from configs.types import FilingInfo
from configs.config import TELEGRAM_CHAT_ID, TELEGRAM_BOT_TOKEN
from modules.telegram_helper import _build_message, _get_bot, TELEGRAM_MAX_LENGTH
from telegram.constants import ParseMode

# --- 가짜 FilingInfo ---

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

# --- 분석 픽스처 ---

analysis_8k_normal = {
    "executive_summary": (
        "CEO Matthew Muta가 2026년 2월 13일 사임을 통보했습니다. "
        "이사회는 후임 CEO 탐색에 착수했습니다. "
        "주주들에게 단기적 불확실성이 발생할 수 있습니다."
    ),
    "objective_facts": [
        "Matthew Muta가 2026-02-28 효력으로 CEO직 사임",
        "이사회가 영구 후임자 탐색 시작",
    ],
    "positive_signals": "이번 CEO 교체가 새로운 전략적 방향을 제시할 기회가 될 수 있습니다.",
    "potential_risks": "CEO 공백이 사업 연속성과 투자자 신뢰에 악영향을 미칠 수 있습니다.",
    "overall_opinion": "이번 공시는 단기적으로 중립~약세 신호입니다. 후임 CEO 발표를 주시하십시오.",
}

analysis_8k_string_facts = {
    "executive_summary": "테스트 요약입니다.",
    "objective_facts": "이것은 리스트가 아닌 문자열로 반환된 objective_facts입니다.",  # old bug
    "positive_signals": "긍정 신호 없음.",
    "potential_risks": "위험 신호 없음.",
    "overall_opinion": "중립.",
}

analysis_10k = {
    "executive_summary": (
        "매출이 전년 대비 15% 증가했습니다. "
        "클라우드 부문 성장이 주요 동력이었습니다. "
        "전반적으로 양호한 실적입니다."
    ),
    "objective_facts": [
        "매출: 1.25억 달러 (YoY +15%)",
        "순이익: 1,250만 달러",
        "영업이익률: 12%",
    ],
    "positive_signals": "클라우드 부문 고성장과 영업이익률 개선이 긍정적입니다.",
    "potential_risks": "AI 시장 경쟁 심화와 인재 유출 위험이 주요 리스크입니다.",
    "overall_opinion": "강세 공시입니다. 다음 분기 클라우드 성장률을 주시하십시오.",
}

OVERFLOW_ANALYSIS = {
    "executive_summary": "장문 요약 내용입니다. " * 100,
    "objective_facts": ["긴 사실 항목 내용 " * 30 for _ in range(5)],
    "positive_signals": "긍정 신호 내용이 매우 깁니다. " * 60,
    "potential_risks": "위험 신호 내용이 매우 깁니다. " * 60,
    "overall_opinion": "종합 의견이 매우 깁니다. " * 40,
}

# --- 테스트 러너 ---

def run_test(name: str, fn):
    try:
        fn()
        print(f"[PASS] {name}")
    except AssertionError as e:
        print(f"[FAIL] {name} - AssertionError: {e}")
    except Exception as e:
        print(f"[FAIL] {name} - {type(e).__name__}: {e}")


def run_async_test(name: str, coro):
    try:
        asyncio.run(coro)
        print(f"[PASS] {name}")
    except AssertionError as e:
        print(f"[FAIL] {name} - AssertionError: {e}")
    except Exception as e:
        print(f"[FAIL] {name} - {type(e).__name__}: {e}")


# --- 시나리오 ---

# Scenario 1: 8-K 정상 분석 (facts가 list) — 각 항목이 불릿으로 출력
def test_build_message_8k_normal():
    msg = _build_message(fake_filing_8k, analysis_8k_normal)
    for fact in analysis_8k_normal["objective_facts"]:
        assert fact in msg, f"fact가 메시지에 없음: {fact}"
    print(f"  [INFO] 메시지 길이: {len(msg)} chars")


# Scenario 2: 8-K facts가 문자열 (old bug) — 단 하나의 불릿으로 렌더링
def test_build_message_8k_string_facts():
    msg = _build_message(fake_filing_8k, analysis_8k_string_facts)
    facts_text = analysis_8k_string_facts["objective_facts"]
    assert facts_text in msg, "문자열 facts 내용이 메시지에 없음"
    bullet_count = msg.count("  • ")
    assert bullet_count == 1, (
        f"문자열 facts는 불릿 1개여야 하는데 {bullet_count}개 발견"
    )


# Scenario 3: 10-K — 📋 이모지 및 날짜가 헤더에 포함
def test_build_message_10k():
    msg = _build_message(fake_filing_10k, analysis_10k)
    assert "📋" in msg, "10-K 이모지(📋)가 메시지에 없음"
    assert fake_filing_10k.filing_date in msg, "공시 날짜가 메시지에 없음"


# Scenario 4: None 분석 (empty dict 폴백) — 크래시 없이 폴백 텍스트 출력
def test_build_message_none_analysis():
    # send_filing_notification_to_users는 None → {} 로 정규화 후 _build_message 호출
    msg = _build_message(fake_filing_8k, {})
    assert "요약 없음" in msg or "N/A" in msg, "폴백 텍스트가 메시지에 없음"


# Scenario 5: 오버플로우 — 메시지 길이가 4096자를 초과하는지 확인
def test_build_message_overflow():
    msg = _build_message(fake_filing_8k, OVERFLOW_ANALYSIS)
    assert len(msg) > TELEGRAM_MAX_LENGTH, (
        f"오버플로우가 발생하지 않음 (길이={len(msg)}, 기준={TELEGRAM_MAX_LENGTH})"
    )
    print(f"  [INFO] 오버플로우 메시지 길이: {len(msg)} chars")


# Scenario 6: 실제 Telegram 전송 — Bot으로 TELEGRAM_CHAT_ID에 직접 전송
async def test_real_telegram_send():
    assert TELEGRAM_CHAT_ID, "TELEGRAM_CHAT_ID가 설정되지 않음"
    assert TELEGRAM_BOT_TOKEN, "TELEGRAM_BOT_TOKEN이 설정되지 않음"
    bot = _get_bot()
    msg = _build_message(fake_filing_8k, analysis_8k_normal)
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=msg,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    print(f"  [INFO] chat_id={TELEGRAM_CHAT_ID}에 메시지 전송 완료")


if __name__ == "__main__":
    print("=== test_telegram_helper.py ===\n")

    run_test("Scenario 1: _build_message 8-K 정상 (list facts)", test_build_message_8k_normal)
    run_test("Scenario 2: _build_message 8-K 문자열 facts → 단일 불릿", test_build_message_8k_string_facts)
    run_test("Scenario 3: _build_message 10-K (이모지 + 날짜)", test_build_message_10k)
    run_test("Scenario 4: _build_message None 분석 → 폴백", test_build_message_none_analysis)
    run_test("Scenario 5: _build_message 오버플로우 감지", test_build_message_overflow)
    run_async_test("Scenario 6: 실제 Telegram 전송", test_real_telegram_send())

    print()
