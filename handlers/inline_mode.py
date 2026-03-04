"""🔍 INLINE QUERY — guruhga test yuborish"""
import logging
from aiogram import Router, F
from aiogram.types import (
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils import store

log    = logging.getLogger(__name__)
router = Router()


@router.inline_query()
async def inline_query(query: InlineQuery):
    q_text = (query.query or "").strip()
    results = []

    # test_TID formatdagi so'rov
    if q_text.upper().startswith("TEST_"):
        tid  = q_text[5:].upper()
        test = store.get_test(tid)
        if test:
            results.append(_make_result(test, tid))
    elif q_text:
        # Qidirish
        for test in store.get_public_tests():
            title = test.get("title", "")
            cat   = test.get("category", "")
            if q_text.lower() in title.lower() or q_text.lower() in cat.lower():
                results.append(_make_result(test, test["test_id"]))
            if len(results) >= 10:
                break
    else:
        # Hammasi
        for test in store.get_public_tests()[:10]:
            results.append(_make_result(test, test["test_id"]))

    await query.answer(results, cache_time=30, is_personal=False)


def _make_result(test, tid) -> InlineQueryResultArticle:
    qc   = test.get("question_count", len(test.get("questions", [])))
    b    = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Inline",  callback_data=f"s_test_{tid}"),
        InlineKeyboardButton(text="📊 Poll",    callback_data=f"s_poll_{tid}"),
    )
    b.row(InlineKeyboardButton(text="📋 Ma'lumot", callback_data=f"vt_{tid}"))

    return InlineQueryResultArticle(
        id=tid,
        title=f"📝 {test.get('title','Nomsiz')}",
        description=f"📁 {test.get('category','')} | 📋 {qc} savol | 👥 {test.get('solve_count',0)}x",
        input_message_content=InputTextMessageContent(
            message_text=(
                f"📋 <b>{test.get('title','Nomsiz')}</b>\n"
                f"📁 {test.get('category','')} | {qc} savol\n"
                f"🆔 <code>{tid}</code>\n\n"
                f"👇 Boshlash uchun tugmani bosing:"
            ),
            parse_mode="HTML"
        ),
        reply_markup=b.as_markup(),
    )
