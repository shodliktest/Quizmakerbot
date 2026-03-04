"""👤 PROFIL + NATIJALAR + MENING TESTLARIM"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from utils import store
from keyboards.kb import main_kb, results_kb, my_tests_kb, result_kb, back_kb

log    = logging.getLogger(__name__)
router = Router()
PAGE   = 6


# ═══════════════════════════════════════════════════════════
# PROFIL
# ═══════════════════════════════════════════════════════════

@router.message(F.text == "👤 Profil")
async def profile_msg(msg: Message):
    await _show_profile(msg, msg.from_user.id)

@router.callback_query(F.data == "profile")
async def profile_cb(cb: CallbackQuery):
    await cb.answer()
    await _show_profile(cb.message, cb.from_user.id, edit=True)

async def _show_profile(event, uid, edit=False):
    user = store.get_user(uid)
    if not user:
        text = "❌ Profil topilmadi. /start bosing."
        if edit: await event.edit_text(text)
        else:    await event.answer(text)
        return

    total = user.get("total", 0)
    avg   = round(user.get("avg", 0), 1)
    badges = []
    if total >= 1:  badges.append("🥉 Boshliqchi")
    if total >= 10: badges.append("🥈 Tajribali")
    if total >= 50: badges.append("🥇 Ustoz")
    if avg   >= 90: badges.append("🌟 Mukammal")
    if avg   >= 80: badges.append("🔥 A'lochi")

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📊 Natijalarim",  callback_data="res_p0"))
    b.row(InlineKeyboardButton(text="📋 Mening testlarim", callback_data="mt_p0"))
    b.row(InlineKeyboardButton(text="🏠 Menyu",        callback_data="main_menu"))

    text = (
        f"👤 <b>PROFIL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 <code>{uid}</code>\n"
        f"👤 {user.get('name','?')}\n\n"
        f"📋 Testlar: <b>{total} ta</b>\n"
        f"📊 O'rtacha: <b>{avg}%</b>\n"
        f"🏅 {' '.join(badges) if badges else 'Hali yutuq yo\'q'}"
    )
    try:
        if edit: await event.edit_text(text, reply_markup=b.as_markup())
        else:    await event.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await event.answer(text, reply_markup=b.as_markup())


# ═══════════════════════════════════════════════════════════
# NATIJALARIM
# ═══════════════════════════════════════════════════════════

@router.message(F.text == "📊 Natijalarim")
async def results_msg(msg: Message):
    await _show_results(msg, msg.from_user.id, 0)

@router.callback_query(F.data.startswith("res_p"))
async def results_page(cb: CallbackQuery):
    await cb.answer()
    page = int(cb.data[5:])
    await _show_results(cb.message, cb.from_user.id, page, edit=True)

async def _show_results(event, uid, page, edit=False):
    all_res = store.get_results(uid)
    if not all_res:
        text = "📭 Hali natijalar yo'q."
        if edit:
            try: await event.edit_text(text)
            except: pass
        else:
            await event.answer(text)
        return

    total_pages = max(1, (len(all_res) + PAGE - 1) // PAGE)
    page        = max(0, min(page, total_pages - 1))
    chunk       = all_res[page * PAGE: (page+1) * PAGE]

    text = f"📊 <b>NATIJALARIM</b> (sahifa {page+1}/{total_pages})\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()

    for r in chunk:
        tid   = r.get("tid", "?")
        test  = store.get_test(tid)
        title = test.get("title", tid) if test else tid
        pct   = r.get("percentage", 0)
        emoji = r.get("emoji", "📝")
        mode  = r.get("mode", "")
        mode_icon = {"inline":"▶️","poll":"📊"}.get(mode, "👥")
        text += f"{emoji} <b>{title}</b>\n   {mode_icon} {pct}% | {r.get('correct',0)}/{r.get('total',0)}\n\n"
        b.row(InlineKeyboardButton(
            text=f"🔍 {title[:20]} — {pct}%",
            callback_data=f"analysis_{r.get('rid','?')}_0"
        ))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"res_p{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"res_p{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))

    try:
        if edit: await event.edit_text(text, reply_markup=b.as_markup())
        else:    await event.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await event.answer(text, reply_markup=b.as_markup())


# ═══════════════════════════════════════════════════════════
# MENING TESTLARIM
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("mt_p"))
async def my_tests(cb: CallbackQuery):
    await cb.answer()
    page    = int(cb.data[4:])
    uid     = cb.from_user.id
    all_t   = store.get_my_tests(uid)
    if not all_t:
        try: await cb.message.edit_text("📭 Siz hali test yaratmagansiz.", reply_markup=back_kb())
        except: pass
        return

    total_pages = max(1, (len(all_t) + PAGE - 1) // PAGE)
    page        = max(0, min(page, total_pages - 1))
    chunk       = all_t[page * PAGE: (page+1) * PAGE]

    text = f"📋 <b>MENING TESTLARIM</b> ({page+1}/{total_pages})\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()

    for t in chunk:
        tid   = t.get("test_id", "?")
        title = t.get("title", "Nomsiz")
        qc    = t.get("question_count", len(t.get("questions", [])))
        sc    = t.get("solve_count", 0)
        vis   = {"public":"🌍","link":"🔗","private":"🔒"}.get(t.get("visibility",""), "")
        text += f"{vis} <b>{title}</b>\n   📋 {qc} savol | 👥 {sc} marta\n   🆔 <code>{tid}</code>\n\n"
        b.row(InlineKeyboardButton(text=f"📝 {title[:25]}", callback_data=f"vt_{tid}"))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"mt_p{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"mt_p{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))

    try: await cb.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: pass


# ═══════════════════════════════════════════════════════════
# REYTING
# ═══════════════════════════════════════════════════════════

@router.message(F.text == "🏆 Reyting")
async def leaderboard_msg(msg: Message):
    await _show_lb(msg)

@router.callback_query(F.data == "lb_global")
async def lb_global(cb: CallbackQuery):
    await cb.answer()
    await _show_lb(cb.message, edit=True)

@router.callback_query(F.data.startswith("lb_"))
async def lb_test(cb: CallbackQuery):
    await cb.answer()
    await _show_lb(cb.message, edit=True)

async def _show_lb(event, edit=False):
    rows   = store.get_leaderboard(20)
    medals = ["🥇","🥈","🥉"] + [f"{i}." for i in range(4, 21)]
    text   = "🏆 <b>GLOBAL REYTING</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    if not rows:
        text += "📭 Hali natijalar yo'q."
    else:
        for i, r in enumerate(rows):
            m = medals[i] if i < len(medals) else f"{i+1}."
            text += f"{m} <b>{r['name']}</b> — {r['avg']}% | {r['total']} ta\n"

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Yangilash", callback_data="lb_global"))
    b.row(InlineKeyboardButton(text="🏠 Menyu",    callback_data="main_menu"))

    try:
        if edit: await event.edit_text(text, reply_markup=b.as_markup())
        else:    await event.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await event.answer(text, reply_markup=b.as_markup())
