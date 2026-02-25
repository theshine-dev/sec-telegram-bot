import asyncio
import logging
import json
import re

import google.generativeai as genai

from configs.config import GEMINI_API_KEY
from configs.types import ExtractedFilingData

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    """Lazy-initialize and return the Gemini model singleton."""
    global _model
    if _model is None:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
        genai.configure(api_key=GEMINI_API_KEY)
        _model = genai.GenerativeModel('gemini-2.5-flash')
        logger.info("[Gemini] 모델 초기화 완료.")
    return _model


def _format_amount(value) -> str:
    """숫자를 읽기 쉬운 달러 금액 문자열로 변환. None이면 'N/A' 반환."""
    if value is None:
        return "N/A"
    try:
        v = float(value)
        if abs(v) >= 1e9:
            return f"${v / 1e9:.2f}B"
        elif abs(v) >= 1e6:
            return f"${v / 1e6:.2f}M"
        else:
            return f"${v:,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _build_prompt(data: ExtractedFilingData, ticker: str, filing_type: str) -> str:
    """
    Return proper prompt using
    Args:
        data:
        ticker:
        filing_type:

    Returns:

    """
    if filing_type in ["10-K", "10-Q"]:
        # 10-K / 10-Q 용 하이브리드 프롬프트

        # 1. 재무 데이터 (숫자)
        fd = data.financial_data or {}
        _FINANCIAL_LABELS = [
            ("Revenue",           "Revenue"),
            ("GrossProfit",       "Gross Profit"),
            ("OperatingIncome",   "Operating Income"),
            ("NetIncome",         "Net Income"),
            ("EPS",               "EPS"),
            ("OperatingCashFlow", "Operating Cash Flow"),
            ("FreeCashFlow",      "Free Cash Flow"),
            ("TotalAssets",       "Total Assets"),
            ("TotalDebt",         "Total Debt"),
            ("Cash",              "Cash & Equivalents"),
        ]
        lines = [f"- {label}: {_format_amount(fd[key])}" for key, label in _FINANCIAL_LABELS if key in fd]
        financial_summary = "\n".join(lines) if lines else "N/A"

        # 2. 경영진 분석 (텍스트)
        mda_summary = data.mda_text or "N/A"

        # 3. 위험 요소 (텍스트)
        risk_summary = data.risk_factors_text or "N/A"

        prompt = f"""
You are an expert equity analyst writing a concise briefing for a retail stock investor.
Analyze the {filing_type} SEC filing for "{ticker}" using ONLY the data provided below.
Respond with a single minified JSON object with EXACTLY these 5 keys, all values in Korean.

--- 1. Financial Data (Item 8) ---
{financial_summary}

--- 2. Management's Discussion & Analysis (Item 7) ---
{mda_summary}

--- 3. Risk Factors (Item 1A) ---
{risk_summary}

JSON field instructions:

"executive_summary": Exactly 3 sentences.
  - Sentence 1: Headline financial result (revenue and net income vs. prior period, with % change if available).
  - Sentence 2: Management's key explanation or most important forward-looking statement.
  - Sentence 3: Overall business momentum — is the company accelerating, stable, or deteriorating?

"objective_facts": A JSON array of 4–6 strings.
  Each string must be ONE concrete, numbered fact pulled DIRECTLY from the filing.
  Examples: revenue figure with YoY%, net income, operating margin, guidance range, key segment performance.
  NO interpretation — hard facts and numbers only.

"positive_signals": 2–3 sentences. The strongest BULLISH evidence in this filing.
  Focus on: revenue/margin growth, strong guidance, competitive advantage, debt reduction, buybacks.
  Always cite the specific figure or statement that supports the signal.

"potential_risks": 2–3 sentences. The most MATERIAL risks to the share price.
  Focus on: revenue miss, margin compression, rising debt, regulatory exposure, management warnings.
  Always cite the specific figure or statement that supports the risk.

"overall_opinion": Exactly 2 sentences.
  - Sentence 1: Net assessment — is this a strong/weak/mixed filing and what is the single most important takeaway for shareholders?
  - Sentence 2: What specific metric or event should investors watch in the next quarter?
"""
        return prompt

    elif filing_type == "8-K":
        # 8-K Item 코드 → 이벤트 유형 설명 매핑
        ITEM_DESCRIPTIONS = {
            "1.01": "Entry into Material Definitive Agreement",
            "1.02": "Termination of Material Definitive Agreement",
            "1.03": "Bankruptcy or Receivership",
            "1.05": "Cybersecurity Incident",
            "2.01": "Completion of Acquisition or Disposition",
            "2.02": "Results of Operations and Financial Condition (실적 발표)",
            "2.03": "Creation of Direct Financial Obligation",
            "2.05": "Costs Associated with Exit or Disposal Activities",
            "2.06": "Material Impairments",
            "4.01": "Changes in Certifying Accountant",
            "4.02": "Non-Reliance on Previously Issued Financial Statements",
            "5.02": "Departure/Appointment of Directors or Officers (임원 변동)",
            "5.03": "Amendments to Articles of Incorporation or Bylaws",
            "5.07": "Submission of Matters to Vote of Security Holders",
            "7.01": "Regulation FD Disclosure",
            "8.01": "Other Events",
            "9.01": "Financial Statements and Exhibits",
        }
        event_context = "N/A"
        if data.event_items:
            described = [
                f"{code} ({ITEM_DESCRIPTIONS.get(code, 'Unknown')})"
                for code in data.event_items
                if code != "9.01"  # 첨부파일 항목은 제외
            ]
            if described:
                event_context = ", ".join(described)

        filing_text = data.press_release_text or data.clean_8k_text or ""

        prompt = f"""
You are an expert equity analyst covering breaking market-moving news for retail investors.
Analyze the following 8-K SEC filing for "{ticker}".
8-K filings report specific material events. Cut through the legalese: tell investors exactly what happened and what it means for the stock.
Respond with a single minified JSON object with EXACTLY these 5 keys, all values in Korean.

--- REPORTED EVENT ITEMS ---
{event_context}

--- 8-K FILING TEXT ---
{filing_text}

JSON field instructions:

"executive_summary": Exactly 3 sentences.
  - Sentence 1: What event occurred — who, what, when, with concrete specifics (names, dates, amounts).
  - Sentence 2: The direct business or financial consequence of this event.
  - Sentence 3: Why this matters to shareholders and how significant it is.

"objective_facts": A JSON array of 3–5 strings.
  Each string = ONE objective fact extracted from the filing (person name + role, date, dollar amount, contractual term, etc.).
  NO opinion or interpretation — raw facts only.

"positive_signals": 1–2 sentences. Why this event could be BULLISH.
  Examples: new revenue-generating deal, cost reduction, strong leadership hire, resolved legal uncertainty, strategic partnership.
  If no positive angle exists, state "이번 공시에서 뚜렷한 긍정적 신호는 확인되지 않습니다."

"potential_risks": 1–2 sentences. Why this event could be BEARISH or introduce uncertainty.
  Examples: executive departure risk, shareholder dilution, legal/regulatory exposure, one-time charges, strategic pivot risk.
  If no risk angle exists, state "이번 공시에서 뚜렷한 위험 신호는 확인되지 않습니다."

"overall_opinion": Exactly 2 sentences.
  - Sentence 1: Materiality verdict — is this event MAJOR or MINOR, and is the net signal BULLISH / BEARISH / NEUTRAL for the stock?
  - Sentence 2: What follow-up event or disclosure should investors watch for next?
"""
        return prompt

    raise ValueError(f"Unsupported filing_type for prompt generation: {filing_type}")


async def shorten_analysis(analysis: dict) -> dict:
    """메시지가 Telegram 4096자 제한을 초과할 경우 Gemini에게 재요약 요청."""
    prompt = f"""You are an editor condensing a JSON analysis for a messaging app with a strict 4096 character limit.
Shorten the following JSON analysis while keeping the most critical investor-relevant information.
Return the SAME JSON structure with shortened values. All values must remain in Korean.

Rules:
- "executive_summary": shorten to 2 sentences maximum
- "objective_facts": keep max 3 items, each item max 80 characters
- "positive_signals": shorten to 1 sentence maximum
- "potential_risks": shorten to 1 sentence maximum
- "overall_opinion": shorten to 1 sentence maximum

Current analysis:
{json.dumps(analysis, ensure_ascii=False)}
"""
    try:
        model = _get_model()
        generation_config = genai.types.GenerationConfig(response_mime_type="application/json")
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(prompt, generation_config=generation_config)
        )
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if not match:
            logger.warning("[Gemini] shorten_analysis: JSON 블록을 찾을 수 없어 원본 반환.")
            return analysis
        return json.loads(match.group(0))
    except Exception as e:
        logger.error(f"[Gemini] shorten_analysis 실패: {e}", exc_info=True)
        return analysis  # 실패 시 원본 그대로 반환


async def get_comprehensive_analysis(data: ExtractedFilingData, ticker: str, filing_type: str):
    """
        Gemini API를 호출하여 객관적 요약과 투자 분석을 모두 가져옵니다.
    """

    prompt = _build_prompt(data, ticker, filing_type)   # 공시별 프롬프트 분리

    if not prompt:
        logger.error(f"[Gemini] {ticker} {filing_type}에 대한 프롬프트를 생성할 수 없습니다.")
        return None
    try:
        model = _get_model()
        generation_config = genai.types.GenerationConfig(response_mime_type="application/json")

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(prompt, generation_config=generation_config)
        )

        raw_text = response.text

        # --- 2. (핵심) JSON 추출 로직 추가 ---
        # 응답 텍스트에서 첫 '{'와 마지막 '}' 사이의 모든 것을 찾습니다.
        # re.DOTALL은 줄바꿈 문자(\n)도 '.'이 매치하도록 합니다.
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)

        if not match:
            # 응답에서 JSON 블록 자체를 찾지 못한 경우
            raise ValueError(f"[Gemini] 응답에서 JSON 객체를 찾을 수 없습니다. Raw: {raw_text[:200]}")

        json_text = match.group(0)  # <-- 추출된 순수 JSON 텍스트

        # 3. 원본(raw_text)이 아닌, 정제된(json_text) 텍스트를 파싱합니다.
        analysis_data = json.loads(json_text)

        return analysis_data

    except Exception as e:
        logger.error(f"[Gemini] Gemini JSON 분석 실패 ({ticker}): {e}", exc_info=True)
        return None
