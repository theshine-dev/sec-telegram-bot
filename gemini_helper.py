import logging
import os
import json
import re

import google.generativeai as genai
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-pro-latest')


def get_objective_summary(filing_text):
    """Gemini를 사용하여 공시 내용의 객관적인 정보를 요약합니다."""
    prompt = f"""
    Please act as a financial data extractor.
    Based on the following SEC filing text, summarize the key objective information.
    Focus ONLY on the facts and numbers presented in the document such as financial results (revenue, net income, EPS), key business updates, and segment performance.
    Do not include any opinions, interpretations, or predictions.
    Present the summary in clear, concise bullet points in Korean.

    --- FILING TEXT ---
    {filing_text}
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini 요약 중 오류 발생: {e}"

def get_investment_insight(filing_text, ticker):
    """Gemini를 사용하여 공시 내용에 대한 투자 인사이트를 제공합니다."""
    prompt = f"""
    You are an experienced investment analyst providing insights for a retail investor.
    Analyze the following SEC filing for the company with ticker "{ticker}".
    Based on the filing and your general knowledge of the market, industry trends, and macroeconomic factors, provide an analysis on what this filing implies for the company's future.

    Please structure your analysis in Korean as follows:
    1.  **공시 핵심 요약:** (1-2 문장으로 공시의 가장 중요한 내용을 요약)
    2.  **긍정적 시그널:** (이 공시 내용이 회사에 긍정적인 이유와 잠재적 주가 상승 요인 분석)
    3.  **잠재적 리스크:** (공시에서 드러난 우려 사항이나 투자자가 주의해야 할 리스크 분석)
    4.  **종합 의견:** (개인 투자자가 이 공시를 바탕으로 어떤 의사결정을 내리면 좋을지에 대한 종합적인 조언)
    --- FILING TEXT ---
    {filing_text}
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini 분석 중 오류 발생: {e}"


def get_comprehensive_analysis(filing_text, ticker):
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
        response = model.generate_content(prompt, generation_config=generation_config)

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

