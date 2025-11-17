from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict


# EIGHT_K_ITEM_MAPPING = {
# 1,"Item 1.01",Entry into a Material Definitive Agreement
# 1,"Item 1.02",Termination of a Material Definitive Agreement
# 1,"Item 1.03",Bankruptcy or Receivership
# 1,"Item 1.05",Cybersecurity Incidents
# 2,"Item 2.01",Completion of Acquisition or Disposition of Assets
# 2,"Item 2.02",Results of Operations and Financial Condition
# 2,"Item 2.03",Creation of a Direct Financial Obligation or an Obligation under an Off-Balance Sheet Arrangement of a Registrant (부외 부채 의무 포함)
# 2,"Item 2.05",Costs Associated with Exit or Disposal Activities
# 2,"Item 2.06",Material Impairments
# 4,"Item 4.01",Changes in Registrant's Certifying Accountant
# 4,"Item 4.02",Non-Reliance on Previously Issued Financial Statements or a Related Audit Report or Completed Interim Review (관련 감사 보고서 및 검토 포함)
# 5,"Item 5.02",Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers (임원 보상 약정 포함)
# 5,"Item 5.03",Amendments to Articles of Incorporation or Bylaws; Change in Fiscal Year
# 5,"Item 5.07",Submission of Matters to a Vote of Security Holders
# 7,"Item 7.01",Regulation FD Disclosure
# 8,"Item 8.01",Other Events
# 9,"Item 9.01",Financial Statements and Exhibits
# }

# Enum
class FilingType(Enum):
    """SEC filing Type"""
    ### 실적 공시 ###
    FORM_10K = "10-K"   # Annual
    FORM_10Q = "10-Q"   # Quarter
    ### 상시 공시 ###
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
    filing_date: str
    filing_url: str
    status: str
    gemini_analysis: Optional[dict] = None
    retry_count: int = 0

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

@dataclass
class ExtractedFilingData:
    """
        sec_parser가 공시에서 추출한 정제된 데이터.
        gemini_helper의 프롬프트 재료로 사용됨.
    """
    # 10-K / 10-Q 용
    mda_text: Optional[str] = None  # Item 7. MD&A 섹션 텍스트
    risk_factors_text: Optional[str] = None  # Item 1A. Risk Factors 텍스트
    financial_data: Optional[Dict] = None  # Item 8. 핵심 재무제표 숫자 (예: {"Revenue": 100, "Net Income": 10})

    # 8-K 용
    clean_8k_text: Optional[str] = None  # 잡음이 제거된 8-K 전문
    event_title: Optional[str] = None  # 8-K의 이벤트 Item (예: "Item 5.02")