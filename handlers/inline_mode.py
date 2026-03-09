"""📤 INLINE MODE — Test ulashish"""
import logging
from aiogram import Router, F
from aiogram.types import (InlineQuery, InlineQueryResultArticle,
                            InputTextMessageContent, InlineKeyboardButton)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.ram_cache import get_tests_meta, get_test_by_id

log    = logging.getLogger(__name__)
router = Router()


def _get_all_metas():
    """RAM + tg_db index dan meta olish — bot qayta ishsa ham ishlaydi"""
    ram_metas = {t["test_id"]: t for t in get_tests_meta() if t.get("test_id")}
    try:
        from utils import tg_db
        for m in tg_db.get_tests_meta():
            tid = m.get("test_id")
            if tid and tid not in ram_metas:
                ram_metas[tid] = m
    except Exception:
        pass
    return list(ram_metas.values())


def _get_test_meta(tid):
    """Faqat meta — RAM yoki tg_db index dan"""
    t = get_test_by_id(tid)
    if t:
        return t
    try:
        from utils import tg_db
        return tg_db.get_test_meta(tid) or {}
    except Exception:
        return {}


@router.inline_query()
async def inline_handler(query: InlineQuery):
    text         = (query.query or "").strip().lower()
    bot_info     = await query.bot.me()
    bot_username = bot_info.username

    if text.startswith("test_"):
        tid  = text[5:].upper().strip()
        # Meta topilsa — ko'rsatish (savollar keyinchalik yuklanadi)
        test = _get_test_meta(tid)
        if test and test.get("test_id"):
            return await query.answer(
                [_make_result(test, bot_username)],
                cache_time=0, is_personal=True
            )
        # Meta ham yo'q — TG dan olishga urinish
        try:
            from utils.db import get_test_full
            full = await get_test_full(tid)
            if full and full.get("test_id"):
                return await query.answer(
                    [_make_result(full, bot_username)],
                    cache_time=0, is_personal=True
                )
        except Exception:
            pass

    all_metas = [
        t for t in _get_all_metas()
        if t.get("is_active", True)
        and t.get("visibility") in ("public", "link")
        and not t.get("is_paused", False)
    ]

    if text:
        all_metas = [
            t for t in all_metas
            if text in t.get("title", "").lower()
            or text in t.get("category", "").lower()
            or text in t.get("test_id", "").lower()
        ]

    results = [_make_result(t, bot_username) for t in all_metas[:20]]

    if not results:
        results = [InlineQueryResultArticle(
            id="empty", title="❌ Test topilmadi",
            description="Boshqa so'z bilan qidiring",
            input_message_content=InputTextMessageContent(message_text="❌ Test topilmadi.")
        )]
    await query.answer(results, cache_time=0, is_personal=True)


def _make_result(test: dict, bot_username: str) -> InlineQueryResultArticle:
    tid   = test.get("test_id", "")
    title = test.get("title", "Nomsiz")
    cat   = test.get("category", "Boshqa")
    qc    = len(test.get("questions", [])) or test.get("question_count", 0)
    sc    = test.get("solve_count", 0)
    pt    = test.get("poll_time", 30)
    diff  = {
        "easy":   "🟢 Oson",
        "medium": "🟡 O'rtacha",
        "hard":   "🔴 Qiyin",
        "expert": "⚡ Ekspert"
    }.get(test.get("difficulty", ""), "🟡 O'rtacha")
    base = f"https://t.me/{bot_username}"

    msg_text = (
        f"📝 <b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
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
    b.row(
        InlineKeyboardButton(text="▶️ Inline test", url=f"{base}?start={tid}"),
        InlineKeyboardButton(text="📊 Quiz Poll",   url=f"{base}?start=poll_{tid}"),
    )
    b.row(
        InlineKeyboardButton(
            text="👥 Guruhda Poll",
            url=f"https://t.me/{bot_username}?startgroup=gpoll_{tid}"
        ),
        InlineKeyboardButton(
            text="👥 Guruhda Inline",
            url=f"https://t.me/{bot_username}?startgroup=ginline_{tid}"
        ),
    )
    b.row(InlineKeyboardButton(
        text="➕ Shunga o'xshash test yarat",
        url=f"{base}?start=create"
    ))
    return InlineQueryResultArticle(
        id=tid if tid else "noid",
        title=f"📝 {title}",
        description=f"📁 {cat} | 📋 {qc} savol | 👥 {sc} marta",
        input_message_content=InputTextMessageContent(
            message_text=msg_text, parse_mode="HTML"
        ),
        reply_markup=b.as_markup(),
    )
