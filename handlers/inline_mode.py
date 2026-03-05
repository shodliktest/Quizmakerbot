"""📤 INLINE MODE — Test ulashish: inline + poll + guruh tugmalari"""
import logging
from aiogram import Router, F
from aiogram.types import (InlineQuery, InlineQueryResultArticle,
                            InputTextMessageContent, InlineKeyboardButton)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.ram_cache import get_tests_meta, get_test_by_id

log    = logging.getLogger(__name__)
router = Router()


@router.inline_query()
async def inline_handler(query: InlineQuery):
    from utils.db import get_test_full

    text         = (query.query or "").strip().lower()
    bot_info     = await query.bot.me()
    bot_username = bot_info.username

    # "test_XXXXX" — to'g'ridan
    if text.startswith("test_"):
        tid  = text[5:].upper()
        test = get_test_by_id(tid) or await get_test_full(tid)
        if test and (len(test.get("questions", [])) > 0 or test.get("question_count", 0) > 0):
            return await query.answer(
                [_make_result(test, bot_username)],
                cache_time=0, is_personal=True
            )

    # Barcha ommaviy + link testlar
    all_metas = [t for t in get_tests_meta()
                 if t.get("is_active", True)
                 and t.get("visibility") in ("public", "link")
                 and not t.get("is_paused", False)]

    if text:
        all_metas = [t for t in all_metas
                     if text in t.get("title", "").lower()
                     or text in t.get("category", "").lower()
                     or text in t.get("test_id", "").lower()]

    results = [_make_result(get_test_by_id(t["test_id"]) or t, bot_username)
               for t in all_metas[:20]]

    if not results:
        results = [InlineQueryResultArticle(
            id="empty",
            title="❌ Test topilmadi",
            description="Boshqa so'z bilan qidiring",
            input_message_content=InputTextMessageContent(
                message_text="❌ Test topilmadi.")
        )]

    await query.answer(results, cache_time=0, is_personal=True)


def _make_result(test: dict, bot_username: str) -> InlineQueryResultArticle:
    tid   = test.get("test_id", "")
    title = test.get("title", "Nomsiz")
    cat   = test.get("category", "Boshqa")
    qc    = len(test.get("questions", [])) or test.get("question_count", 0)
    sc    = test.get("solve_count", 0)
    pt    = test.get("poll_time", 30)

    diff_map = {
        "easy":   "🟢 Oson", "medium": "🟡 O'rtacha",
        "hard":   "🔴 Qiyin", "expert": "⚡ Ekspert",
    }
    diff = diff_map.get(test.get("difficulty", ""), "🟡 O'rtacha")
    base = f"https://t.me/{bot_username}"

    msg_text = (
        f"📝 <b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📁 Fan: <b>{cat}</b>\n"
        f"📊 Qiyinlik: {diff}\n"
        f"📋 Savollar: <b>{qc} ta</b>\n"
        f"⏱ Poll vaqti: {pt}s/savol\n"
        f"🎯 O'tish foizi: <b>{test.get('passing_score', 60)}%</b>\n"
        f"👥 Ishlaganlar: <b>{sc} marta</b>\n"
        f"🆔 Kod: <code>{tid}</code>\n\n"
        f"👇 <b>Qanday boshlash?</b>"
    )

    b = InlineKeyboardBuilder()
    # Ulashgandan keyin 3 ta tugma:
    b.row(
        InlineKeyboardButton(text="▶️ Inline test",  url=f"{base}?start={tid}"),
        InlineKeyboardButton(text="📊 Quiz Poll",    url=f"{base}?start=poll_{tid}"),
    )
    b.row(
        InlineKeyboardButton(text="👥 Guruhda boshlash", callback_data=f"group_start_{tid}"),
    )
    b.row(
        InlineKeyboardButton(text="📤 Ulashish",
                             switch_inline_query=f"test_{tid}"),
    )

    return InlineQueryResultArticle(
        id=tid if tid else "noid",
        title=f"📝 {title}",
        description=f"📁 {cat} | 📋 {qc} savol | 👥 {sc} marta",
        input_message_content=InputTextMessageContent(
            message_text=msg_text, parse_mode="HTML"
        ),
        reply_markup=b.as_markup(),
    )
