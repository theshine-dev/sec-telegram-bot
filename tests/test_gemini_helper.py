"""
test_gemini_helper.py — _build_prompt 구조 검증 + 실제 Gemini API 호출 테스트

실행:
    python -m tests.test_gemini_helper
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / "..env")

from configs.types import ExtractedFilingData
from modules.gemini_helper import _build_prompt, get_comprehensive_analysis, shorten_analysis

# --- 가짜 공시 데이터 ---

fake_8k = ExtractedFilingData(
    clean_8k_text=(
        "On February 13, 2026, Matthew Muta notified Palladyne AI Corp. "
        "of his resignation as Chief Executive Officer, effective February 28, 2026. "
        "The Board has initiated a search for a permanent successor."
    )
)

fake_10k = ExtractedFilingData(
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

LONG_ANALYSIS = {
    "executive_summary": "장기 요약 문장입니다. " * 60,
    "objective_facts": ["사실 항목 " * 20 for _ in range(6)],
    "positive_signals": "긍정 신호 내용입니다. " * 50,
    "potential_risks": "위험 신호 내용입니다. " * 50,
    "overall_opinion": "종합 의견 내용입니다. " * 40,
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

# Scenario 1: _build_prompt 10-K 구조 검증
def test_build_prompt_10k():
    prompt = _build_prompt(fake_10k, "FAKE", "10-K")
    assert "Financial Data" in prompt, "prompt에 'Financial Data' 섹션 없음"
    assert "Management" in prompt or "MD&A" in prompt, "prompt에 MD&A 섹션 없음"
    assert "Risk Factors" in prompt, "prompt에 'Risk Factors' 섹션 없음"


# Scenario 2: _build_prompt 8-K 구조 검증 (5개 JSON 필드 포함 여부)
def test_build_prompt_8k():
    prompt = _build_prompt(fake_8k, "AIPAL", "8-K")
    assert "8-K FILING TEXT" in prompt, "prompt에 '8-K FILING TEXT' 없음"
    for field in ["executive_summary", "objective_facts", "positive_signals",
                  "potential_risks", "overall_opinion"]:
        assert field in prompt, f"prompt에 JSON 필드 '{field}' 없음"


# Scenario 3: _build_prompt 잘못된 공시 유형 → ValueError 기대
def test_build_prompt_invalid_type():
    try:
        _build_prompt(fake_8k, "FAKE", "13-F")
        assert False, "ValueError가 발생하지 않았습니다"
    except ValueError:
        pass  # 기대 동작


# Scenario 4: 실제 Gemini API — 8-K 분석 (5개 키 + objective_facts가 list)
async def test_get_analysis_8k():
    result = await get_comprehensive_analysis(fake_8k, "AIPAL", "8-K")
    assert result is not None, "결과가 None"
    for key in ["executive_summary", "objective_facts", "positive_signals",
                "potential_risks", "overall_opinion"]:
        assert key in result, f"결과에 키 '{key}' 없음"
    assert isinstance(result["objective_facts"], list), \
        f"objective_facts가 list가 아님: {type(result['objective_facts'])}"
    print(f"  [INFO] 8-K 분석 완료. objective_facts 항목 수: {len(result['objective_facts'])}")


# Scenario 5: 실제 Gemini API — 10-K 분석 (5개 키 + objective_facts가 list)
async def test_get_analysis_10k():
    result = await get_comprehensive_analysis(fake_10k, "FAKE", "10-K")
    assert result is not None, "결과가 None"
    for key in ["executive_summary", "objective_facts", "positive_signals",
                "potential_risks", "overall_opinion"]:
        assert key in result, f"결과에 키 '{key}' 없음"
    assert isinstance(result["objective_facts"], list), \
        f"objective_facts가 list가 아님: {type(result['objective_facts'])}"
    print(f"  [INFO] 10-K 분석 완료. objective_facts 항목 수: {len(result['objective_facts'])}")


# Scenario 6: shorten_analysis — 각 필드가 원본보다 짧아야 함
async def test_shorten_analysis():
    original_total = sum(
        len(str(v)) for v in LONG_ANALYSIS.values()
    )
    shortened = await shorten_analysis(LONG_ANALYSIS)
    assert isinstance(shortened, dict), f"결과가 dict가 아님: {type(shortened)}"

    shortened_total = sum(len(str(v)) for v in shortened.values())
    assert shortened_total < original_total, (
        f"단축 후 총 길이가 줄지 않음 (원본={original_total}, 단축={shortened_total})"
    )
    print(f"  [INFO] 단축 전 총 길이: {original_total}, 단축 후: {shortened_total}")


if __name__ == "__main__":
    print("=== test_gemini_helper.py ===\n")

    run_test("Scenario 1: _build_prompt 10-K 구조", test_build_prompt_10k)
    run_test("Scenario 2: _build_prompt 8-K 구조 + 5개 JSON 필드", test_build_prompt_8k)
    run_test("Scenario 3: _build_prompt 잘못된 유형 → ValueError", test_build_prompt_invalid_type)
    run_async_test("Scenario 4: get_comprehensive_analysis 8-K (실제 Gemini)", test_get_analysis_8k())
    run_async_test("Scenario 5: get_comprehensive_analysis 10-K (실제 Gemini)", test_get_analysis_10k())
    run_async_test("Scenario 6: shorten_analysis (실제 Gemini)", test_shorten_analysis())

    print()
