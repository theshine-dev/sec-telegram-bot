import sys

from dotenv import load_dotenv
import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 내부 헬퍼 모듈 임포트
from modules import db_manager, ticker_validator
from modules.bg_task import discover_new_filings, process_analysis_queue
from configs.logging_config import setup_logging

load_dotenv()

logger = logging.getLogger(__name__)


# --- 사용자 명령어 함수들 ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start"""
    await update.message.reply_text(
        "안녕하세요! 미국 기업 공시 분석 봇입니다.\n"
        "사용법: /sub <티커> (예: /sub TSLA)"
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sub [ticker]"""
    try:
        ticker = context.args[0].upper()

        cik = ticker_validator.get_cik_for_ticker(ticker)
        if cik is None:
            await update.message.reply_text(f"'{ticker}'는 SEC 데이터베이스에 존재하지 않는 티커입니다. 오타를 확인해주세요.")
            return

        await db_manager.add_subscription(update.message.chat_id, ticker)
        await update.message.reply_text(f"{ticker} 구독을 추가했습니다.")
    except IndexError:
        await update.message.reply_text("사용법: /sub <티커>")


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unsub [ticker]"""
    try:
        ticker = context.args[0].upper()

        await db_manager.remove_subscription(update.message.chat_id, ticker)
        await update.message.reply_text(f"{ticker} 구독을 취소했습니다.")
    except IndexError:
        await update.message.reply_text("사용법: /unsub <티커>")


async def sub_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/list"""
    tickers = await db_manager.get_subscribed_tickers_for_user(update.message.chat_id)
    if tickers:
        await update.message.reply_text(f"구독 목록 : {', '.join(tickers)}")
    else:
        await update.message.reply_text(f"구독 목록이 없습니다. 티커를 추가해보세요. \n예) /sub TSLA")


async def post_init(app: Application):
    """
        봇이 시작된 직후, 폴링을 시작하기 전에 실행됩니다.
        DB 풀 초기화, 스케줄러 시작, 초기 백그라운드 작업 트리가
        """
    # DB 풀, 스키마 초기화
    await db_manager.init_db_pool()
    await db_manager.setup_database()

    # 봇이 시작하자마자 티커 목록 업데이트를 '백그라운드에서' 즉시 실행
    # create_task는 이 작업이 끝나는 것을 기다리지 않고 바로 다음으로 넘어갑니다.
    asyncio.create_task(ticker_validator.update_ticker_list())

    try:
        scheduler = app.bot_data['scheduler']
        scheduler.start()
        logger.info(f"[스케줄러] 초기 티커 갱신 작업 등록 완료(APScheduler)")
    except Exception as e:
        logger.critical(f"[스케줄러] 초기 티커 갱신 작업 등록 실패(APScheduler) : {e}")


async def on_shutdown(app: Application):
    """봇 종료 직전에 DB 풀을 닫습니다."""
    logger.info("[종료] 봇 종료 시작... DB 풀을 닫습니다.")
    await db_manager.close_db_pool()

    scheduler = app.bot_data.get('scheduler')
    if scheduler and scheduler.running:
        scheduler.shutdown()
        logger.info("[종료] 스케줄러 종료됨.")


def main():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    setup_logging()  # Applying Custom Logging Config

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.critical(f"[설정] 'TELEGRAM_BOT_TOKEN' 환경변수 체크 필요")
        raise ValueError("Please, Set a 'TELEGRAM_BOT_TOKEN' environment variable!!")

    # --- Application 빌더에 post_init 훅 추가 ---
    application = (Application.builder()
                   .token(token)
                   .post_init(post_init)
                   .post_shutdown(on_shutdown)
                   .build()
                   )

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    # --- 스케줄러에 동기 함수 대신 비동기 함수 등록 ---
    scheduler.add_job(
        ticker_validator.update_ticker_list,
        'interval',
        hours=24,
        id='daily_ticker_update',
        max_instances=1,
    )
    scheduler.add_job(
        discover_new_filings,
        'interval',
        minutes=1,
        id='discover_new_filings'
    )
    scheduler.add_job(
        process_analysis_queue,
        'interval',
        seconds=80,
        id='process_analysis_queue',
        max_instances=1,  # 인스턴스 1개로 강제
        coalesce=True,  # 병합 처리(딜레이된 작업 누적 처리 방지)
    )

    application.bot_data['scheduler'] = scheduler

    # 명령어 핸들러 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("sub", subscribe))
    application.add_handler(CommandHandler("unsub", unsubscribe))
    application.add_handler(CommandHandler("list", sub_list))

    application.run_polling()

    logger.info(f"[봇] 성공적으로 봇을 구동하였습니다.")


if __name__ == '__main__':
    main()
