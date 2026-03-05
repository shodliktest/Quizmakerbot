"""🚀 START — Xush kelibsiz, yordam, adminga murojaat"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from config import ADMIN_IDS
from utils.db import get_or_create_user
from utils.ram_cache import get_test_by_id
from keyboards.keyboards import main_kb, test_info_kb
from utils.states import ContactAdmin

log    = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid   = message.from_user.id
    uname = message.from_user.username
    name  = (message.from_user.full_name or
             (f"@{uname}" if uname else f"User{message.from_user.id}"))

    user   = await get_or_create_user(uid, name, uname)
    is_new = user.get("_just_created", False)

    if user.get("is_blocked"):
        return await message.answer("🚫 Siz bloklangansiz. Admin bilan bog'laning.")

    if is_new:
        at = f"@{uname}" if uname else "Yo'q"
        for aid in ADMIN_IDS:
            try:
                await message.bot.send_message(
                    aid,
                    f"🆕 <b>YANGI FOYDALANUVCHI!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 Ism: <b>{name}</b>\n"
                    f"🔗 Username: {at}\n"
                    f"🆔 ID: <code>{uid}</code>"
                )
            except Exception:
                pass
        welcome = (
            f"👋 Salom, <b>{name}</b>!\n"
            f"🎓 <b>Quiz Bot</b> platformasiga xush kelibsiz!\n\n"
            f"📚 Testlar — ommaviy testlar ro'yxati\n"
            f"➕ Test Yaratish — TXT/PDF yoki QuizBot\n"
            f"📊 Natijalarim — yechgan testlaringiz\n"
            f"🏆 Reyting — eng yaxshi natijalar"
        )
    else:
        welcome = f"🏠 Xush kelibsiz, <b>{name}</b>!"

    args = message.text.split()
    if len(args) > 1:
        param = args[1].strip()

        from utils.db import get_test_full as _gtf

        # ?start=poll_TID — poll rejimini to'g'ridan boshlash
        if param.lower().startswith("poll_"):
            tid  = param[5:].upper()
            test = get_test_by_id(tid) or await _gtf(tid)
            if test:
                await message.answer(welcome, reply_markup=main_kb(uid))
                b = InlineKeyboardBuilder()
                b.row(InlineKeyboardButton(text="📊 Poll rejimni boshlash", callback_data=f"start_poll_{tid}"))
                b.row(InlineKeyboardButton(text="▶️ Inline rejim",          callback_data=f"start_test_{tid}"))
                await message.answer(
                    f"📝 <b>{test.get('title')}</b>\n\nQaysi rejimda boshlash?",
                    reply_markup=b.as_markup()
                )
                return

        # ?start=lb_TID — reyting
        if param.lower().startswith("lb_"):
            tid = param[3:].upper()
            from handlers.leaderboard import show_leaderboard
            await message.answer(welcome, reply_markup=main_kb(uid))
            await show_leaderboard(message, tid)
            return

        # ?start=TID — test kartochkasi (RAM + TG kanal)
        tid  = param.upper()
        test = get_test_by_id(tid) or await _gtf(tid)
        if test:
            await message.answer(welcome, reply_markup=main_kb(uid))
            await _send_test_card(message, test, tid)
            return

    await message.answer(
        f"{welcome}\n\nPastdagi menyudan kerakli bo'limni tanlang 👇",
        reply_markup=main_kb(uid)
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Yordam")
async def help_msg(message: Message):
    await _send_help(message)


@router.callback_query(F.data == "help")
async def help_cb(callback: CallbackQuery):
    await callback.answer()
    await _send_help(callback.message, edit=True)


async def _send_help(msg, edit: bool = False):
    text = (
        "❓ <b>BOTDAN FOYDALANISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ <b>▶️ Inline test</b> — har savoldan keyin\n"
        "   to'g'ri/noto'g'ri ko'rsatadi, 5 soniya kutish\n\n"
        "2️⃣ <b>📊 Poll test</b> — Telegram native quiz\n"
        "   (@QuizBot uslubida, vaqt bilan)\n\n"
        "3️⃣ <b>Test yaratish</b> — TXT/PDF/DOCX fayl\n"
        "   yoki @QuizBot savollarini forward qiling\n\n"
        "4️⃣ <b>Test kodi</b> — kodni to'g'ridan yuboring\n"
        "   yoki /start KOD havolasidan kiring\n\n"
        "5️⃣ <b>Natijalarim</b> — 8 tadan ko'rsatiladi,\n"
        "   ◀️▶️ tugmalar bilan almashtirish mumkin\n\n"
        "6️⃣ <b>Mening testlarim</b> — 5 tadan,\n"
        "   TXT yuklab olish va ulashish ssilkasi\n\n"
        "💬 <i>Muammo bo'lsa adminga murojaat qiling:</i>"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✉️ Adminga murojaat", callback_data="contact_admin"))
    b.row(InlineKeyboardButton(text="🏠 Asosiy menyu",     callback_data="main_menu"))
    kb = b.as_markup()
    try:
        if edit:
            await msg.edit_text(text, reply_markup=kb)
            return
    except Exception:
        pass
    await msg.answer(text, reply_markup=kb)


async def _send_test_card(event, test, tid):
    qs   = test.get("questions", [])
    d    = {
        "easy": "🟢 Oson", "medium": "🟡 O'rtacha",
        "hard": "🔴 Qiyin", "expert": "⚡ Ekspert"
    }.get(test.get("difficulty", ""), "")
    pt   = test.get("poll_time", 30)
    pt_t = f"{pt}s/savol" if pt else "Vaqtsiz"
    tl_t  = f"{test.get('time_limit')} daqiqa" if test.get("time_limit") else "Cheksiz"
    att   = test.get("max_attempts", 0)
    att_t = f"{att} marta" if att else "Cheksiz"
    title = test.get("title", "Nomsiz")
    cat   = test.get("category", "")
    text = (
        f"📋 <b>TEST MA'LUMOTI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 <b>{title}</b>\n"
        f"📁 Fan: {cat}\n"
        f"📊 Qiyinlik: {d}\n"
        f"📋 Savollar: <b>{len(qs)} ta</b>\n"
        f"⏱ Umumiy vaqt: {tl_t}\n"
        f"⏱ Poll vaqti: {pt_t}\n"
        f"🎯 O'tish foizi: <b>{test.get('passing_score', 60)}%</b>\n"
        f"🔄 Urinishlar: {att_t}\n"
        f"👥 Ishlagan: <b>{test.get('solve_count', 0)} marta</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"▶️ <b>Inline</b> — savoldan keyin togri/notogri korinadi\n"
        f"📊 <b>Poll</b> — Telegram quiz poll, pauza/toxtatish bor\n"
        f"👥 <b>Guruh</b> — guruhda birga yechish, oxirida reyting"
    )
    if isinstance(event, Message):
        await event.answer(text, reply_markup=test_info_kb(tid))
    else:
        try:
            await event.message.edit_text(text, reply_markup=test_info_kb(tid))
        except TelegramBadRequest:
            await event.message.answer(text, reply_markup=test_info_kb(tid))


@router.callback_query(F.data == "main_menu")
async def back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    uid = callback.from_user.id
    await callback.bot.send_message(
        uid, "🏠 <b>Asosiy menyu</b>\n👇",
        reply_markup=main_kb(uid)
    )


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


# ── ADMINGA MUROJAAT ──────────────────────────────────────

@router.callback_query(F.data == "contact_admin")
async def contact_admin_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_contact"))
    try:
        await callback.message.edit_text(
            "<b>✉️ ADMINGA MUROJAAT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Xabaringizni yozing:\n"
            "<i>(matn, rasm yoki fayl yuborishingiz mumkin)</i>\n\n"
            "<i>Admin imkon topib javob beradi 🙏</i>",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "<b>✉️ ADMINGA MUROJAAT</b>\n\nXabaringizni yozing:",
            reply_markup=b.as_markup()
        )
    await state.set_state(ContactAdmin.waiting_message)


@router.callback_query(F.data == "cancel_contact")
async def cancel_contact(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Bekor qilindi")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.bot.send_message(
        callback.from_user.id,
        "✅ Bekor qilindi.",
        reply_markup=main_kb(callback.from_user.id, "private")
    )


@router.message(ContactAdmin.waiting_message)
async def contact_admin_send(message: Message, state: FSMContext):
    uid   = message.from_user.id
    name  = message.from_user.full_name
    uname = f"@{message.from_user.username}" if message.from_user.username else "Yo'q"

    sent = 0
    for aid in ADMIN_IDS:
        try:
            await message.bot.send_message(
                aid,
                f"📩 <b>FOYDALANUVCHIDAN MUROJAAT</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 Ism: <b>{name}</b>\n"
                f"🔗 Username: {uname}\n"
                f"🆔 ID: <code>{uid}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📝 Xabar:"
            )
            await message.forward(aid)
            sent += 1
        except Exception as e:
            log.error(f"Admin {aid} ga xato: {e}")

    await state.clear()
    if sent > 0:
        await message.answer(
            "✅ <b>Xabaringiz adminga yuborildi!</b>\n\n"
            "Javobni kuting 🙏",
            reply_markup=main_kb(uid)
        )
    else:
        await message.answer(
            "⚠️ Yuborishda muammo yuz berdi.\n"
            "Keyinroq urinib ko'ring.",
            reply_markup=main_kb(uid)
        )


@router.message(F.text.startswith("/reply "))
async def admin_reply(message: Message):
    """Admin javob yuborish: /reply USER_ID Xabar matni"""
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        return await message.answer("Format: <code>/reply USER_ID Xabar matni</code>")
    try:
        target_id = int(parts[1])
        await message.bot.send_message(
            target_id,
            f"📬 <b>ADMINDAN JAVOB:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{parts[2]}"
        )
        await message.answer(f"✅ <code>{target_id}</code> ga muvaffaqiyatli yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
