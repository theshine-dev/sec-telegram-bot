import asyncio
import logging
import json
import re

import google.generativeai as genai

from configs.config import GEMINI_API_KEY
from configs.types import ExtractedFilingData

logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro-latest')


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
        financial_summary = "N/A"
        if data.financial_data:
            financial_summary = (
                f"- Revenue: {data.financial_data.get('Revenue', 'N/A')}\n"
                f"- Net Income: {data.financial_data.get('NetIncome', 'N/A')}"
            )

        # 2. 경영진 분석 (텍스트)
        mda_summary = data.mda_text or "N/A"

        # 3. 위험 요소 (텍스트)
        risk_summary = data.risk_factors_text or "N/A"

        prompt = f"""
            You are an expert financial analyst. Analyze the {filing_type} filing for "{ticker}" based on the following extracted data.
            Provide your entire response as a single, minified JSON object.

            --- 1. Key Financial Data (From Item 8) ---
            {financial_summary}

            --- 2. Management's Discussion & Analysis (From Item 7) ---
            {mda_summary} 

            --- 3. Risk Factors (From Item 1A) ---
            {risk_summary}

            Based *only* on the 3 sections above, analyze and respond in JSON (Korean):

            - "executive_summary": A 3-sentence summary (in Korean) combining the financial data and management's discussion.
            - "objective_facts": Key numbers (from Section 1) and key facts (from Section 2 & 3).
            - "positive_signals": Positive implications from the data and text.
            - "potential_risks": Risks identified in Section 2 and Section 3.
            - "overall_opinion": A final concluding remark (in Korean).
        """
        return prompt

    elif filing_type == "8-K":
        # 8-K 용 프롬프트
        prompt = f"""
            You are an expert breaking news analyst. Analyze the following 8-K filing for "{ticker}".
            This filing reports a specific, immediate event. Analyze it and provide your response as a single, minified JSON object...

            - "executive_summary": A 3-sentence summary (in Korean) explaining *what just happened* and its potential impact.
            - "objective_facts": Some Sentences (in Korean) explaining 'Key facts of the event'.
            --- 8-K TEXT ---
            {data.clean_8k_text}
        """
        return prompt

    raise ValueError(f"Unsupported filing_type for prompt generation: {filing_type}")


async def get_comprehensive_analysis(data: ExtractedFilingData, ticker: str, filing_type: str):
    """
        Gemini API를 호출하여 객관적 요약과 투자 분석을 모두 가져옵니다.
    """

    prompt = _build_prompt(data, ticker, filing_type)   # 공시별 프롬프트 분리

    if not prompt:
        logger.error(f"[Gemini] {ticker} {filing_type}에 대한 프롬프트를 생성할 수 없습니다.")
        return None
    try:
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