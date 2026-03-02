import sys
import html
import datetime

from dotenv import load_dotenv
import os
import logging
import asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeChat
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters,
)
from telegram.constants import ChatAction, ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 내부 헬퍼 모듈 임포트
from modules import db_manager, ticker_validator, sec_parser, gemini_helper
from modules.bg_task import discover_new_filings, process_analysis_queue, get_last_discover_at
from modules.telegram_helper import _build_message

from configs.logging_config import setup_logging
from configs import config
from configs.types import FilingInfo, AnalysisStatus


logger = logging.getLogger(__name__)

# ConversationHandler 상태 상수
WAITING_TICKER = 1


# --- /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start"""
    await update.message.reply_text(
        "안녕하세요! 미국 기업 공시 분석 봇입니다.\n\n"
        "/sub <티커> — 티커 구독 (예: /sub TSLA)\n"
        "/unsub <티커> — 구독 취소\n"
        "/list — 구독 목록 확인\n"
        "/latest <티커> — 최신 공시 분석 즉시 조회\n"
        "/status — 봇 상태 확인"
    )


# --- /sub (ConversationHandler 진입점) ---
async def sub_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sub [ticker] — 인자가 있으면 즉시 구독, 없으면 가이드 플로우 시작."""
    if context.args:
        ticker = context.args[0].upper()
        cik = ticker_validator.get_cik_for_ticker(ticker)
        if cik is None:
            await update.message.reply_text(
                f"'{ticker}'는 SEC 데이터베이스에 존재하지 않는 티커입니다. 오타를 확인해주세요."
            )
            return ConversationHandler.END
        await db_manager.add_subscription(update.message.chat_id, ticker)
        await update.message.reply_text(f"✅ {ticker} 구독을 추가했습니다.")
        return ConversationHandler.END

    # 인자 없이 /sub만 입력한 경우 — 가이드 플로우
    await update.message.reply_text(
        "구독할 티커를 입력해주세요. (예: TSLA)\n"
        "취소하려면 /cancel 을 입력하세요."
    )
    return WAITING_TICKER


async def sub_receive_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """WAITING_TICKER 상태에서 사용자가 입력한 텍스트로 구독 처리."""
    ticker = update.message.text.strip().upper()
    cik = ticker_validator.get_cik_for_ticker(ticker)
    if cik is None:
        await update.message.reply_text(
            f"'{ticker}'는 SEC에 존재하지 않는 티커입니다. 다시 입력하거나 /cancel 로 취소하세요."
        )
        return WAITING_TICKER  # 다시 입력 대기
    await db_manager.add_subscription(update.message.chat_id, ticker)
    await update.message.reply_text(f"✅ {ticker} 구독을 추가했습니다.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel — 진행 중인 대화를 종료합니다."""
    await update.message.reply_text("구독 입력이 취소되었습니다.")
    return ConversationHandler.END


# --- /unsub ---
async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unsub [ticker]"""
    try:
        ticker = context.args[0].upper()
        await db_manager.remove_subscription(update.message.chat_id, ticker)
        await update.message.reply_text(f"✅ {ticker} 구독을 취소했습니다.")
    except IndexError:
        await update.message.reply_text("사용법: /unsub <티커>")


# --- /list ---
async def sub_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/list — 구독 목록을 인라인 버튼과 함께 출력합니다."""
    tickers = await db_manager.get_subscribed_tickers_for_user(update.message.chat_id)
    if not tickers:
        await update.message.reply_text(
            "구독 목록이 없습니다. 티커를 추가해보세요.\n예) /sub TSLA"
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"❌ {ticker} 구독 취소", callback_data=f"unsub:{ticker}")]
        for ticker in tickers
    ])
    await update.message.reply_text(
        f"📋 구독 목록 ({len(tickers)}개):",
        reply_markup=keyboard,
    )


# --- /status ---
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — 분석 큐 상태, Gemini 쿼터, 마지막 탐색 시각을 출력합니다."""
    counts = await db_manager.get_queue_status_counts()
    quota  = await db_manager.get_quota_status()
    last_discover = get_last_discover_at()

    # 오늘(UTC) 사용량 계산
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    used = quota['count'] if quota['date'].date() == now_utc.date() else 0

    # 마지막 탐색 시각 → KST
    kst = datetime.timezone(datetime.timedelta(hours=9))
    if last_discover:
        last_str = last_discover.astimezone(kst).strftime('%m/%d %H:%M KST')
    else:
        last_str = '아직 실행 전'

    msg = (
        f"📊 <b>봇 상태</b>\n\n"
        f"<b>📋 분석 큐</b>\n"
        f"  대기 중: {counts['pending']}건\n"
        f"  실패(재시도 대기): {counts['failed']}건\n"
        f"  영구 실패: {counts['permanent_fail']}건\n\n"
        f"<b>🤖 Gemini 할당량 (오늘)</b>\n"
        f"  사용: {used} / {config.GEMINI_DAILY_LIMIT}건\n\n"
        f"<b>🔍 마지막 공시 탐색</b>\n"
        f"  {last_str}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


# --- /latest ---
async def latest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/latest <ticker> — analysis_archive에서 최신 분석 결과를 즉시 조회합니다."""
    if not context.args:
        await update.message.reply_text("사용법: /latest <티커> (예: /latest TSLA)")
        return

    ticker = context.args[0].upper()

    # 처리 중임을 사용자에게 표시
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    filing_info = await db_manager.get_latest_archive(ticker)
    if not filing_info:
        await update.message.reply_text(f"'{ticker}'의 분석 기록이 없습니다.")
        return

    msg = _build_message(filing_info, filing_info.gemini_analysis or {})
    if len(msg) > 4096:
        tail = "\n\n<i>⚠️ 내용이 너무 길어 일부가 생략되었습니다.</i>"
        msg = msg[:4096 - len(tail)] + tail

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"🔕 {ticker} 구독 취소", callback_data=f"unsub:{ticker}")
    ]])
    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=keyboard,
    )


# --- /test (관리자 전용) ---
_TEST_TICKER = 'KO'

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/test — 관리자 전용: KO 공시로 전체 파이프라인(추출→분석→발송)을 검증합니다. DB 저장 없음."""
    # ── 관리자 확인 ──────────────────────────────────────────────────────
    if config.ADMIN_CHAT_ID and str(update.message.chat_id) != str(config.ADMIN_CHAT_ID):
        logger.warning(f"[테스트] 비관리자 접근 차단: chat_id={update.message.chat_id}")
        return

    status_msg = await update.message.reply_text(
        f"🧪 [{_TEST_TICKER}] 파이프라인 테스트를 시작합니다..."
    )

    try:
        # ── Step 1: CIK 조회 ─────────────────────────────────────────────
        cik = ticker_validator.get_cik_for_ticker(_TEST_TICKER)
        if not cik:
            await status_msg.edit_text(f"❌ [{_TEST_TICKER}] CIK 조회 실패 — 티커 목록을 확인하세요.")
            return

        # ── Step 2: 최신 공시 목록 조회 ──────────────────────────────────
        await status_msg.edit_text(f"🔍 [{_TEST_TICKER}] 최신 공시 목록 조회 중...")
        filings = await sec_parser.get_recent_filings_list(cik)
        if not filings:
            await status_msg.edit_text(f"❌ [{_TEST_TICKER}] 공시 목록을 가져올 수 없습니다.")
            return

        latest   = filings[0]
        f_type   = latest['form_type']
        f_date   = str(latest['filing_date'])
        f_url    = latest['filing_url']
        f_acc    = latest['accession_number']

        # ── Step 3: FilingInfo 생성 (DB 저장 없음) ────────────────────────
        job = FilingInfo(
            accession_number=f_acc,
            ticker=_TEST_TICKER,
            filing_type=f_type,
            filing_date=f_date,
            filing_url=f_url,
            status=AnalysisStatus.PENDING.value,
        )

        # ── Step 4: 공시 데이터 추출 ─────────────────────────────────────
        await status_msg.edit_text(
            f"📄 [{_TEST_TICKER}] 공시 데이터 추출 중...\n"
            f"유형: <code>{html.escape(f_type)}</code>  날짜: <code>{html.escape(f_date)}</code>",
            parse_mode=ParseMode.HTML,
        )
        extracted_data = await sec_parser.extract_filing_data(job)
        if not extracted_data:
            await status_msg.edit_text(
                f"❌ [{_TEST_TICKER}] 공시 데이터 추출 실패 — 유의미한 내용 없음."
            )
            return

        # ── Step 5: Gemini 쿼터 확인 후 분석 ────────────────────────────
        quota   = await db_manager.get_quota_status()
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        used_today = quota['count'] if quota['date'].date() == now_utc.date() else 0

        if used_today >= config.GEMINI_DAILY_LIMIT:
            await status_msg.edit_text(
                f"⚠️ [{_TEST_TICKER}] Gemini 일일 쿼터 소진 "
                f"({used_today}/{config.GEMINI_DAILY_LIMIT}) — 테스트를 실행할 수 없습니다."
            )
            return

        await status_msg.edit_text(
            f"🤖 [{_TEST_TICKER}] Gemini 분석 중... (쿼터 {used_today}/{config.GEMINI_DAILY_LIMIT})\n"
            f"유형: <code>{html.escape(f_type)}</code>  날짜: <code>{html.escape(f_date)}</code>",
            parse_mode=ParseMode.HTML,
        )
        analysis_result = await gemini_helper.get_comprehensive_analysis(
            extracted_data, _TEST_TICKER, f_type
        )
        if not analysis_result:
            await status_msg.edit_text(
                f"❌ [{_TEST_TICKER}] Gemini 분석 실패 또는 빈 결과."
            )
            return

        # Gemini 호출 성공 시에만 쿼터 카운트 업데이트
        await db_manager.update_quota_count(used_today + 1, now_utc)

        job.update_gemini_analysis(analysis_result)

        # ── Step 6: 메시지 조립 및 발송 (DB 저장 없음) ───────────────────
        msg_body = _build_message(job, job.gemini_analysis or {})
        header   = "🧪 <b>[테스트 실행 결과 — DB 미저장]</b>\n\n"
        full_msg = header + msg_body

        # 4096자 초과 시 말미 절단
        if len(full_msg) > 4096:
            tail     = "\n\n<i>⚠️ 내용이 너무 길어 일부가 생략되었습니다.</i>"
            full_msg = full_msg[:4096 - len(tail)] + tail

        await status_msg.delete()
        await update.message.reply_text(
            full_msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(f"[테스트] [{_TEST_TICKER}] 파이프라인 테스트 완료 — DB 미저장.")

    except Exception as e:
        logger.error(f"[테스트] [{_TEST_TICKER}] 파이프라인 테스트 중 오류: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ [{_TEST_TICKER}] 테스트 중 오류 발생\n\n"
            f"<code>{html.escape(str(e)[:400])}</code>",
            parse_mode=ParseMode.HTML,
        )


# --- CallbackQuery 핸들러: 구독 취소 버튼 ---
async def unsub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """공시 알림·/list·/latest의 '구독 취소' 버튼 콜백."""
    query = update.callback_query
    await query.answer()  # 버튼 로딩 상태 해제 (필수)

    ticker = query.data.split(":", 1)[1]
    user_id = query.from_user.id
    await db_manager.remove_subscription(user_id, ticker)
    await query.edit_message_reply_markup(reply_markup=None)  # 버튼 제거
    await query.message.reply_text(f"✅ {ticker} 구독이 취소되었습니다.")


# --- 봇 수명주기 훅 ---
async def post_init(app: Application):
    """봇 시작 직후 실행: DB·스케줄러 초기화 + 명령어 메뉴 등록."""
    await db_manager.init_db_pool()
    await db_manager.setup_database()
    await sec_parser.init_parser()
    asyncio.create_task(ticker_validator.update_ticker_list())

    # 전체 사용자 명령어 메뉴 등록
    await app.bot.set_my_commands([
        BotCommand("start",  "봇 소개"),
        BotCommand("sub",    "티커 구독 (예: /sub TSLA)"),
        BotCommand("unsub",  "티커 구독 취소"),
        BotCommand("list",   "구독 목록 확인"),
        BotCommand("latest", "최신 공시 분석 조회"),
        BotCommand("status", "봇 상태 확인"),
        BotCommand("cancel", "진행 중인 입력 취소"),
    ])

    # 관리자 채팅 전용 메뉴: 전체 공개 명령어 + /test 추가
    # (BotCommandScopeChat은 전역 목록을 덮어쓰므로 모든 명령어를 함께 포함해야 함)
    if config.ADMIN_CHAT_ID:
        try:
            await app.bot.set_my_commands(
                [
                    BotCommand("start",  "봇 소개"),
                    BotCommand("sub",    "티커 구독 (예: /sub TSLA)"),
                    BotCommand("unsub",  "티커 구독 취소"),
                    BotCommand("list",   "구독 목록 확인"),
                    BotCommand("latest", "최신 공시 분석 조회"),
                    BotCommand("status", "봇 상태 확인"),
                    BotCommand("cancel", "진행 중인 입력 취소"),
                    BotCommand("test",   f"파이프라인 전체 테스트 ({_TEST_TICKER})"),
                ],
                scope=BotCommandScopeChat(chat_id=int(config.ADMIN_CHAT_ID)),
            )
        except Exception as e:
            logger.warning(f"[봇] 관리자 전용 명령어 등록 실패: {e}")

    try:
        scheduler = app.bot_data['scheduler']
        scheduler.start()
        logger.info("[스케줄러] 초기 티커 갱신 작업 등록 완료(APScheduler)")
        logger.info("[봇] 성공적으로 봇을 구동하였습니다.")
    except Exception as e:
        logger.critical(f"[스케줄러] 초기 티커 갱신 작업 등록 실패(APScheduler) : {e}")


async def on_shutdown(app: Application):
    """봇 종료 직전: DB 풀·스케줄러 정리."""
    logger.info("[종료] 봇 종료 시작... DB 풀을 닫습니다.")
    await db_manager.close_db_pool()

    scheduler = app.bot_data.get('scheduler')
    if scheduler and scheduler.running:
        scheduler.shutdown()
        logger.info("[종료] 스케줄러 종료됨.")


def main():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    setup_logging()

    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        logger.critical("[설정] 'TELEGRAM_BOT_TOKEN' 환경변수 체크 필요")
        raise ValueError("Please, Set a 'TELEGRAM_BOT_TOKEN' environment variable!!")

    application = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(on_shutdown)
        .build()
    )

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        ticker_validator.update_ticker_list,
        'interval',
        hours=config.UPDATE_TICKER_INTERVAL_HOURS,
        id='daily_ticker_update',
        max_instances=1,
    )
    scheduler.add_job(
        discover_new_filings,
        'interval',
        seconds=config.DISCOVER_INTERVAL_SECONDS,
        id='discover_new_filings',
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        process_analysis_queue,
        'interval',
        seconds=config.ANALYSIS_INTERVAL_SECONDS,
        id='process_analysis_queue',
        max_instances=1,
        coalesce=True,
    )

    application.bot_data['scheduler'] = scheduler

    # --- 핸들러 등록 순서 중요: ConversationHandler 먼저 ---

    # /sub 가이드 플로우 (인자 없이 /sub 입력 시)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("sub", sub_start)],
        states={
            WAITING_TICKER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sub_receive_ticker)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)

    # 일반 명령어 핸들러
    application.add_handler(CommandHandler("start",  start))
    application.add_handler(CommandHandler("unsub",  unsubscribe))
    application.add_handler(CommandHandler("list",   sub_list))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("latest", latest_command))

    # 관리자 전용 명령어 핸들러
    application.add_handler(CommandHandler("test", test_command))

    # 인라인 버튼 콜백 핸들러
    application.add_handler(CallbackQueryHandler(unsub_callback, pattern=r"^unsub:"))

    application.run_polling()


if __name__ == '__main__':
    main()
