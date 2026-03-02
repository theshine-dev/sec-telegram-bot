import html
import logging

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode

from modules import db_manager, gemini_helper
from configs.config import TELEGRAM_BOT_TOKEN
from configs.types import FilingInfo

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096

_bot: Bot | None = None


def _get_bot() -> Bot:
    """Return a module-level singleton Bot instance."""
    global _bot
    if _bot is None:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot


async def send_admin_alert(message: str):
    """관리자 chat_id로 알림 메시지를 전송합니다. ADMIN_CHAT_ID 미설정 시 무시."""
    from configs import config
    if not config.ADMIN_CHAT_ID:
        return
    bot = _get_bot()
    try:
        await bot.send_message(
            chat_id=int(config.ADMIN_CHAT_ID),
            text=message,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"[Telegram] 관리자 알림 전송 실패: {e}")


def _build_message(filing_info: FilingInfo, analysis: dict) -> str:
    """FilingInfo와 분석 결과로 Telegram HTML 메시지를 조립."""
    type_emoji = {"10-K": "📋", "10-Q": "📄", "8-K": "⚡"}.get(filing_info.filing_type, "🔔")

    msg = f"{type_emoji} <b>{html.escape(filing_info.ticker)} 신규 공시 ({html.escape(filing_info.filing_type)})</b>\n"
    msg += f"<code>📅 {html.escape(filing_info.filing_date)}</code>\n\n"

    executive_summary = html.escape(analysis.get('executive_summary', '요약 없음'))
    msg += "<b>✨ 3줄 요약</b>\n"
    msg += f"<i>{executive_summary}</i>\n\n"

    msg += "<b>📊 주요 공시 내용</b>\n"
    facts = analysis.get('objective_facts', [])
    if isinstance(facts, str):  # Gemini가 배열 대신 문자열 반환 시 방어
        facts = [facts]
    if facts:
        for fact in facts:
            msg += f"  • {html.escape(str(fact))}\n"
    else:
        msg += "  • N/A\n"
    msg += "\n"

    positive_signals = html.escape(analysis.get('positive_signals', 'N/A'))
    potential_risks  = html.escape(analysis.get('potential_risks',  'N/A'))
    overall_opinion  = html.escape(analysis.get('overall_opinion',  'N/A'))

    msg += "<b>💡 AI 인사이트</b>\n"
    msg += f"<b>👍 긍정 신호</b>\n{positive_signals}\n\n"
    msg += f"<b>👎 위험 신호</b>\n{potential_risks}\n\n"
    msg += f"<b>💬 종합 의견</b>\n{overall_opinion}\n\n"

    msg += f'🔗 <a href="{html.escape(filing_info.filing_url)}">공시 원문 보기</a>'

    return msg


async def send_filing_notification_to_users(filing_info: FilingInfo):
    bot = _get_bot()
    analysis = filing_info.gemini_analysis or {}

    msg = _build_message(filing_info, analysis)

    # Telegram 4096자 초과 시 Gemini에게 재요약 요청 후 재조립
    if len(msg) > TELEGRAM_MAX_LENGTH:
        logger.warning(f"[Telegram] {filing_info.ticker} 메시지 {len(msg)}자 초과 — Gemini 재요약 요청.")
        analysis = await gemini_helper.shorten_analysis(analysis)
        msg = _build_message(filing_info, analysis)

        # 재요약 후에도 초과 시 (안전망) 말미 절단
        if len(msg) > TELEGRAM_MAX_LENGTH:
            tail = "\n\n<i>⚠️ 내용이 너무 길어 일부가 생략되었습니다.</i>"
            msg = msg[:TELEGRAM_MAX_LENGTH - len(tail)] + tail
            logger.warning(f"[Telegram] {filing_info.ticker} 재요약 후에도 초과 — 강제 절단.")

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"🔕 {filing_info.ticker} 구독 취소", callback_data=f"unsub:{filing_info.ticker}")
    ]])

    users_id = await db_manager.get_users_for_ticker(filing_info.ticker)
    fail_count = 0
    for user_id in users_id:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=msg,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )
        except Exception as e:
            fail_count += 1
            logger.error(f"[Telegram] user_id={user_id} 메시지 전송 실패: {e}", exc_info=True)

    if fail_count > 0:
        logger.warning(
            f"[Telegram] {filing_info.ticker} 알림 전송 결과: "
            f"{len(users_id) - fail_count}/{len(users_id)} 성공, "
            f"{fail_count}명 실패"
        )
