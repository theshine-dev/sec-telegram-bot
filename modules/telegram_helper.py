from telegram import Bot
from telegram.constants import ParseMode

from . import db_manager
from configs.config import TELEGRAM_BOT_TOKEN
from configs.types import FilingInfo


async def send_filing_notification_to_users(filing_info: FilingInfo):
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    gemini_analysis = filing_info.gemini_analysis

    msg = f"🔔 <b>{filing_info.ticker} 신규 공시 ({filing_info.filing_type})</b> 🔔\n\n"

    msg += f"<b>✨ 3줄 요약 </b>\n"
    msg += f"<i>{gemini_analysis.get('executive_summary', '요약 없음')}</i>\n\n"

    msg += "<b>📊 주요 공시 내용 </b>\n"
    facts = gemini_analysis.get('objective_facts', [])
    if facts:
        for fact in facts:
            msg += f"  • {fact}\n"
    else:
        msg += "  - N/A\n"
    msg += "\n"

    msg += "<b>💡 AI 인사이트 </b>\n"
    msg += f"  <b>[👍]</b> {gemini_analysis.get('positive_signals', 'N/A')}\n"
    msg += f"  <b>[👎]</b> {gemini_analysis.get('potential_risks', 'N/A')}\n"
    msg += f"  <b>[종합]</b> {gemini_analysis.get('overall_opinion', 'N/A')}\n\n"

    msg += f'🔗 <a href="{filing_info.filing_url}">공시 원문 보기</a>'

    users_id = await db_manager.get_users_for_ticker(filing_info.ticker)
    for user_id in users_id:
        await bot.send_message(chat_id=user_id, text=msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

