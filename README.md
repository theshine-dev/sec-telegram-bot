# 📈 SEC Filing Telegram Bot

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Hub-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/demisoda/sec-telegram-bot)
[![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub_Actions-2088FF?logo=github-actions&logoColor=white)](https://github.com/theshine-dev/sec-telegram-bot/actions)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)

미국 SEC EDGAR에 새로운 공시(10-K, 10-Q, 8-K)가 등록되면 **Google Gemini AI**로 자동 분석하여 **Telegram**으로 알려주는 봇입니다.

---

## ✨ 주요 기능

| 기능 | 설명 |
|------|------|
| 🔍 **공시 자동 탐지** | SEC EDGAR API를 주기적으로 폴링하여 구독 티커의 신규 공시를 자동으로 감지 |
| 🤖 **AI 분석** | Google Gemini로 MD&A, 리스크 팩터, 재무 데이터를 요약·분석 |
| 📬 **Telegram 알림** | 분석 결과를 HTML 형식으로 구독자에게 즉시 발송 |
| 📊 **재무 데이터 추출** | Revenue, GrossProfit, OperatingIncome 등 핵심 지표 자동 추출 |
| 🔁 **스마트 재시도** | 3회 일반 재시도 후 3시간 대기 → 최종 재시도 → 영구 실패 처리 |
| 🛡️ **Gemini 할당량 관리** | RPM / 일일 한도 추적으로 API 초과 방지 |

---

## 🏗️ 아키텍처

```
SEC EDGAR
    │
    ▼
discover_new_filings()     ← APScheduler (5분마다)
    │  새 공시 발견
    ▼
analysis_queue (PENDING)
    │
    ▼
process_analysis_queue()   ← APScheduler (80초마다)
    │
    ├─ sec_parser  → edgartools로 MD&A / 리스크 / 재무 추출
    ├─ gemini_helper → Gemini AI 분석 (JSON 응답)
    ├─ db_manager  → analysis_archive 저장
    └─ telegram_helper → 구독자에게 알림 발송
```

### 모듈 구성

```
sec-telegram-bot/
├── main.py                  # 봇 진입점, Telegram 핸들러, 스케줄러 설정
├── modules/
│   ├── bg_task.py           # 공시 탐지 · 분석 큐 오케스트레이터
│   ├── sec_parser.py        # edgartools 기반 공시 데이터 파싱
│   ├── gemini_helper.py     # Gemini AI 분석 요청 · 응답 처리
│   ├── db_manager.py        # 비동기 PostgreSQL (psycopg3)
│   ├── telegram_helper.py   # Telegram 메시지 포매팅 · 발송
│   └── ticker_validator.py  # SEC 전체 티커 목록 다운로드 · CIK 매핑
└── configs/
    ├── config.py            # 환경변수 기반 설정
    ├── types.py             # FilingType, AnalysisStatus, 데이터클래스
    └── logging_config.py    # 도메인별 로테이팅 파일 핸들러
```

---

## 🚀 시작하기

### 사전 요구사항

- Docker & Docker Compose
- Telegram Bot Token ([BotFather](https://t.me/BotFather))
- Google Gemini API Key ([AI Studio](https://aistudio.google.com/))

### 1. 환경 변수 설정

프로젝트 루트에 `.env` 파일을 생성합니다.

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
ADMIN_CHAT_ID=your_admin_chat_id   # 생략 시 TELEGRAM_CHAT_ID로 폴백

# Google Gemini
GEMINI_API_KEY=your_gemini_api_key

# PostgreSQL
DATABASE_URL=postgresql://postgres:password@db:5432/sec_bot_db

# 스케줄러 (선택, 기본값 사용 가능)
DISCOVER_INTERVAL_SECONDS=300      # 공시 탐지 주기 (기본: 5분)
ANALYSIS_INTERVAL_SECONDS=80       # 분석 실행 주기 (기본: 80초)

# Gemini 할당량 (선택)
GEMINI_RPM_LIMIT=2                 # 분당 최대 요청 수
GEMINI_DAILY_LIMIT=50              # 일일 최대 요청 수

# 재시도 설정 (선택)
MAX_RETRY_LIMIT=4                  # 최대 시도 횟수
LAST_RETRY_INTERVAL_HOURS=3        # 마지막 재시도 전 대기 시간(시)
```

### 2. 데이터베이스 실행

```bash
docker compose -f docker-compose-postgres.yml up -d
```

### 3. 봇 실행

**Docker (권장)**
```bash
docker run -d \
  --env-file .env \
  --name sec-telegram-bot \
  demisoda/sec-telegram-bot:latest
```

**로컬 개발**
```bash
pip install -r requirements.txt
python main.py
```

---

## 🤖 Telegram 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` | 봇 소개 및 명령어 안내 |
| `/sub TSLA` | 티커 구독 추가 |
| `/unsub` | 구독 취소 (인라인 버튼) |
| `/list` | 현재 구독 중인 티커 목록 |
| `/latest AAPL` | 해당 티커의 최신 분석 결과 즉시 조회 |
| `/status` | 봇 상태 · 큐 현황 · 할당량 확인 |
| `/test` ⚙️ | (관리자) 전체 파이프라인 테스트 (DB 저장 없음) |

---

## 🔁 재시도 흐름

일시적인 네트워크 오류나 SEC API 장애 상황을 고려한 단계적 재시도 전략을 사용합니다.

```
1차 시도 → 실패 → 10분 대기
2차 시도 → 실패 → 10분 대기
3차 시도 → 실패 → 3시간 대기  (마지막 재시도)
4차 시도 → 실패 → PERMANENT_FAIL + 관리자 알림
```

---

## 🛠️ CI/CD

`v*.*.*` 형식의 태그를 푸시하면 GitHub Actions가 자동으로 Docker 이미지를 빌드하여 Docker Hub에 배포합니다.

```bash
git tag v1.2.3
git push origin main --tags
```

→ `demisoda/sec-telegram-bot:v1.2.3` 및 `latest` 태그로 자동 배포

---

## 🧰 기술 스택

| 분류 | 라이브러리 |
|------|-----------|
| 비동기 런타임 | Python 3.13 asyncio |
| Telegram | python-telegram-bot 22 |
| AI 분석 | google-generativeai (Gemini) |
| SEC 데이터 | edgartools 4 |
| 스케줄러 | APScheduler 3 |
| 데이터베이스 | PostgreSQL 16 + psycopg3 + psycopg-pool |
| 컨테이너 | Docker + GitHub Actions |
