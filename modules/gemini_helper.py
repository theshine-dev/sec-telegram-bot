import asyncio
import logging
import json
import re

import google.generativeai as genai

from configs.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro-latest')


async def get_comprehensive_analysis(filing_text, ticker):
    """
    Gemini API를 한 번만 호출하여 객관적 요약과 투자 분석을 모두 가져옵니다.
    """
    # Gemini에게 두 가지 작업을 동시에 요청하는 통합 프롬프트
    prompt = f"""
        You are an expert financial analyst. Analyze the following SEC filing for "{ticker}".
        Provide your entire response as a single, minified JSON object. Do not include markdown or any text outside the JSON.
        The JSON object must have the following keys:
        
        - "executive_summary": A 3-sentence summary (in Korean) of the most critical information for an investor.
        - "objective_facts": A list of key bullet points (as strings, in Korean) based *only* on the text (e.g., revenue, net income, key events).
        - "positive_signals": A brief analysis (in Korean) of positive implications.
        - "potential_risks": A brief analysis (in Korean) of potential risks and concerns.
        - "overall_opinion": A final concluding remark (in Korean).
        --- FILING TEXT ---
        {filing_text}
    """
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
        raise e