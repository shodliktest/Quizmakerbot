"""📤 INLINE MODE — Test ulashish (guruh tugmalarsiz)"""
import logging
from aiogram import Router, F
from aiogram.types import (InlineQuery, InlineQueryResultArticle,
                            InputTextMessageContent, InlineKeyboardButton,
                            SwitchInlineQueryChosenChat)
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

    # ── GURUH TEST BOSHLASH — gpoll_TID yoki ginline_TID ──
    if text.startswith("gpoll_") or text.startswith("ginline_"):
        is_poll = text.startswith("gpoll_")
        tid     = text[6:].upper() if is_poll else text[8:].upper()
        mode    = "poll" if is_poll else "inline"
        test    = get_test_by_id(tid) or await get_test_full(tid)
        if test:
            qc    = len(test.get("questions",[])) or test.get("question_count",0)
            title = test.get("title","Test")
            # Guruhga yuboriladigan xabar
            msg = (
                f"🎯 <b>{title}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📋 Savollar: <b>{qc} ta</b>\n"
                f"⏱ Vaqt: {test.get('poll_time',30)}s/savol\n"
                f"🎯 O'tish: {test.get('passing_score',60)}%\n\n"
                f"👇 Testni boshlash uchun quyidagi tugmani bosing!"
            )
            b = InlineKeyboardBuilder()
            if is_poll:
                b.row(InlineKeyboardButton(
                    text="🚀 Poll testni boshlash",
                    callback_data=f"gsend_poll_{tid}"
                ))
            else:
                b.row(InlineKeyboardButton(
                    text="🚀 Inline testni boshlash",
                    callback_data=f"gsend_inline_{tid}"
                ))
            result = InlineQueryResultArticle(
                id=f"{mode}_{tid}",
                title=f"{'📊 Poll' if is_poll else '▶️ Inline'}: {title}",
                description=f"Guruhga yuborish va boshlash",
                input_message_content=InputTextMessageContent(
                    message_text=msg, parse_mode="HTML"
                ),
                reply_markup=b.as_markup(),
            )
            return await query.answer([result], cache_time=0, is_personal=True)
        return await query.answer([], cache_time=0)

    if text.startswith("test_"):
        tid  = text[5:].upper()
        test = get_test_by_id(tid) or await get_test_full(tid)
        if test and (len(test.get("questions",[])) > 0 or test.get("question_count",0) > 0):
            return await query.answer(
                [_make_result(test, bot_username)],
                cache_time=0, is_personal=True
            )

    all_metas = [t for t in get_tests_meta()
                 if t.get("is_active", True)
                 and t.get("visibility") in ("public","link")
                 and not t.get("is_paused", False)]

    if text:
        all_metas = [t for t in all_metas
                     if text in t.get("title","").lower()
                     or text in t.get("category","").lower()
                     or text in t.get("test_id","").lower()]

    results = [_make_result(get_test_by_id(t["test_id"]) or t, bot_username)
               for t in all_metas[:20]]

    if not results:
        results = [InlineQueryResultArticle(
            id="empty", title="❌ Test topilmadi",
            description="Boshqa so'z bilan qidiring",
            input_message_content=InputTextMessageContent(message_text="❌ Test topilmadi.")
        )]
    await query.answer(results, cache_time=0, is_personal=True)


def _make_result(test: dict, bot_username: str) -> InlineQueryResultArticle:
    tid   = test.get("test_id","")
    title = test.get("title","Nomsiz")
    cat   = test.get("category","Boshqa")
    qc    = len(test.get("questions",[])) or test.get("question_count",0)
    sc    = test.get("solve_count",0)
    pt    = test.get("poll_time",30)
    diff  = {"easy":"🟢 Oson","medium":"🟡 O'rtacha",
              "hard":"🔴 Qiyin","expert":"⚡ Ekspert"}.get(test.get("difficulty",""),"🟡 O'rtacha")
    base  = f"https://t.me/{bot_username}"

    msg_text = (
        f"📝 <b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📁 Fan: <b>{cat}</b>\n"
        f"📊 Qiyinlik: {diff}\n"
        f"📋 Savollar: <b>{qc} ta</b>\n"
        f"⏱ Poll vaqti: {pt}s/savol\n"
        f"🎯 O'tish foizi: <b>{test.get('passing_score',60)}%</b>\n"
        f"👥 Ishlaganlar: <b>{sc} marta</b>\n"
        f"🆔 Kod: <code>{tid}</code>\n\n"
        f"👇 <b>Qanday boshlash?</b>"
    )
    b = InlineKeyboardBuilder()
    # Private chat uchun
    b.row(
        InlineKeyboardButton(text="▶️ Inline test", url=f"{base}?start={tid}"),
        InlineKeyboardButton(text="📊 Quiz Poll",   url=f"{base}?start=poll_{tid}"),
    )
    # Guruhda ishlash: switch_inline_query_chosen_chat
    # Foydalanuvchi guruhni tanlaydi → inline_handler gpoll_/ginline_ ni oladi
    # → guruhga to'g'ridan xabar + tugma yuboriladi — @bot nomi yo'q!
    b.row(
        InlineKeyboardButton(
            text="👥 Guruhda Poll",
            switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(
                query=f"gpoll_{tid}",
                allow_group_chats=True,
                allow_channel_chats=False,
                allow_user_chats=False,
                allow_bot_chats=False,
            )
        ),
        InlineKeyboardButton(
            text="👥 Guruhda Inline",
            switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(
                query=f"ginline_{tid}",
                allow_group_chats=True,
                allow_channel_chats=False,
                allow_user_chats=False,
                allow_bot_chats=False,
            )
        ),
    )
    b.row(InlineKeyboardButton(text="➕ Shunga o'xshash test yarat",
                               url=f"{base}?start=create"))

    return InlineQueryResultArticle(
        id=tid if tid else "noid",
        title=f"📝 {title}",
        description=f"📁 {cat} | 📋 {qc} savol | 👥 {sc} marta",
        input_message_content=InputTextMessageContent(
            message_text=msg_text, parse_mode="HTML"
        ),
        reply_markup=b.as_markup(),
    )
