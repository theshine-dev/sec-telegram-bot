from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# Enum
class FilingType(Enum):
    """SEC filing Type"""
    ### 실적 공시 ###
    FORM_10K = "10-K"   # Annual
    FORM_10Q = "10-Q"   # Quarter
    FORM_8K = "8-K"     # on-demand announcement for major
    ### 지분 변경 공시 ###
    # FORM_3 = "3"      # 내부자 최초 지분
    # FORM_4 = "4"      # 주식 보유 변동사항
    # FORM_13F = "13F"  # 기관투자자 보유내역
    ### M&A ###
    # FORM_S4 = "S-4"   # M&A specific report


class AnalysisStatus(Enum):
    """SEC analysis status"""
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    def __str__(self):
        return self.value

# Dataclass
@dataclass
class FilingInfo:
    """분석 큐 작업을 정의하는 데이터 클래스"""
    accession_number: str
    ticker: str
    filing_type: str
    filing_url: str
    status: str
    gemini_analysis: Optional[dict] = None

    # def __init__(self, accession_number: str, ticker: str, filing_type: FilingType, filing_url: str, status: AnalysisStatus,
    #              gemini_summary: Optional[str] = None, gemini_insight: Optional[str] = None, gemini_point: Optional[str] = None):
    #     self.accession_number = accession_number
    #     self.ticker = ticker
    #     self.filing_type = filing_type
    #     self.filing_url = filing_url
    #     self.status = status
    #     self.gemini_summary = gemini_summary
    #     self.gemini_insight = gemini_insight
    #     self.gemini_point = gemini_point

    def as_dict(self):
        return {
            'accession_number': self.accession_number,
            'ticker': self.ticker,
            'filing_type': self.filing_type,  # DB 저장을 위해 .value 사용
            'filing_url': self.filing_url,
            'status': self.status,
            'gemini_analysis': self.gemini_analysis,
        }

    def update_gemini_analysis(self, analysis_result):
        self.gemini_analysis = analysis_result

    def update_status(self, status: str | AnalysisStatus):
        self.status = str(status)


@dataclass
class AnalysisResult:
    """Gemini 분석 완료 후 DB에 업데이트할 결과를 담는 객체"""
    accession_number: str
    status: AnalysisStatus
    summary: Optional[str] = None
    insight: Optional[str] = None

    def as_dict(self):
        return {
            'accession_number': self.accession_number,
            'status': self.status.value,
            'summary': self.summary,
            'insight': self.insight,
        }