import html
import logging

from telegram import Bot
from telegram.constants import ParseMode

from modules import db_manager
from configs.config import TELEGRAM_BOT_TOKEN
from configs.types import FilingInfo

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def _get_bot() -> Bot:
    """Return a module-level singleton Bot instance."""
    global _bot
    if _bot is None:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot


async def send_filing_notification_to_users(filing_info: FilingInfo):
    bot = _get_bot()

    gemini_analysis = filing_info.gemini_analysis

    # Escape dynamic Gemini content to prevent HTML injection
    executive_summary = html.escape(gemini_analysis.get('executive_summary', '요약 없음'))
    positive_signals = html.escape(gemini_analysis.get('positive_signals', 'N/A'))
    potential_risks = html.escape(gemini_analysis.get('potential_risks', 'N/A'))
    overall_opinion = html.escape(gemini_analysis.get('overall_opinion', 'N/A'))

    msg = f"🔔 <b>{html.escape(filing_info.ticker)} 신규 공시 ({html.escape(filing_info.filing_type)})</b> 🔔\n\n"

    msg += f"<b>✨ 3줄 요약 </b>\n"
    msg += f"<i>{executive_summary}</i>\n\n"

    msg += "<b>📊 주요 공시 내용 </b>\n"
    facts = gemini_analysis.get('objective_facts', [])
    if facts:
        for fact in facts:
            msg += f"  • {html.escape(str(fact))}\n"
    else:
        msg += "  - N/A\n"
    msg += "\n"

    msg += "<b>💡 AI 인사이트 </b>\n"
    msg += f"  <b>[👍]</b> {positive_signals}\n"
    msg += f"  <b>[👎]</b> {potential_risks}\n"
    msg += f"  <b>[종합]</b> {overall_opinion}\n\n"

    msg += f'🔗 <a href="{html.escape(filing_info.filing_url)}">공시 원문 보기</a>'

    users_id = await db_manager.get_users_for_ticker(filing_info.ticker)
    for user_id in users_id:
        try:
            await bot.send_message(chat_id=user_id, text=msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"[Telegram] user_id={user_id} 메시지 전송 실패: {e}")
