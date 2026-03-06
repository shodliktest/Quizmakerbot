"""🚀 START — Xush kelibsiz, test kartochkasi"""
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
from utils.ram_cache import get_test_by_id, get_test_meta
from keyboards.keyboards import main_kb, test_info_kb
from utils.states import ContactAdmin

log    = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid   = message.from_user.id
    uname = message.from_user.username
    name  = message.from_user.full_name or (f"@{uname}" if uname else f"User{uid}")

    user   = await get_or_create_user(uid, name, uname)
    is_new = user.pop("_just_created", False)

    if user.get("is_blocked"):
        return await message.answer("🚫 Siz bloklangansiz.")

    if is_new:
        at = f"@{uname}" if uname else "Yo'q"
        for aid in ADMIN_IDS:
            try:
                await message.bot.send_message(
                    aid, f"🆕 <b>YANGI USER!</b>\n👤 <b>{name}</b> | {at} | <code>{uid}</code>"
                )
            except Exception: pass
        welcome = (
            f"👋 Salom, <b>{name}</b>! 🎓\n"
            f"<b>Quiz Bot</b> platformasiga xush kelibsiz!\n\n"
            f"📚 Testlar — Fanlar bo'yicha\n"
            f"➕ Test Yaratish — TXT/PDF/QuizBot\n"
            f"📊 Natijalarim — tariхingiz\n"
            f"🏆 Reyting — eng yaxshi natijalar"
        )
    else:
        welcome = f"🏠 Xush kelibsiz, <b>{name}</b>!"

    args = message.text.split()
    if len(args) > 1:
        param = args[1].strip()
        from utils.db import get_test_full as _gtf

        if param.lower() == "create":
            await message.answer(welcome, reply_markup=main_kb(uid))
            return

        if param.lower().startswith("poll_"):
            tid  = param[5:].upper()
            test = get_test_by_id(tid) or await _gtf(tid)
            if test:
                await message.answer(welcome, reply_markup=main_kb(uid))
                b = InlineKeyboardBuilder()
                b.row(InlineKeyboardButton(
                    text="📊 Quiz Poll boshlash",
                    callback_data=f"start_poll_{tid}"
                ))
                b.row(InlineKeyboardButton(text="▶️ Inline test", callback_data=f"start_test_{tid}"))
                await message.answer(
                    f"📝 <b>{test.get('title')}</b>\nQaysi rejimda boshlash?",
                    reply_markup=b.as_markup()
                )
                return

        tid  = param.upper()
        test = get_test_by_id(tid) or await _gtf(tid)
        if test:
            await message.answer(welcome, reply_markup=main_kb(uid))
            await _send_test_card(message, test, tid, viewer_uid=uid)
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

async def _send_help(msg, edit=False):
    text = (
        "❓ <b>BOTDAN FOYDALANISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ <b>▶️ Inline test</b> — har savoldan keyin\n"
        "   to'g'ri/noto'g'ri ko'rsatadi\n"
        "   30s avtomatik keyingi savolga o'tadi\n\n"
        "2️⃣ <b>📊 Quiz Poll</b> — Telegram native quiz\n"
        "   vaqt bilan, pauza/to'xtatish bor\n\n"
        "3️⃣ <b>📤 Ulashish</b> — inline orqali yuborish\n"
        "   2 ta rejimdan birini tanlab boshlash\n\n"
        "4️⃣ <b>Test kodi</b> — to'g'ridan yuboring\n\n"
        "5️⃣ <b>📊 Natijalarim</b> — barcha foizlar\n"
        "   faqat oxirgi test uchun tahlil\n\n"
        "💬 <i>Muammo bo'lsa adminga murojaat:</i>"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✉️ Adminga murojaat", callback_data="contact_admin"))
    b.row(InlineKeyboardButton(text="🏠 Asosiy menyu",     callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except Exception:
        await msg.answer(text, reply_markup=b.as_markup())


async def _send_test_card(event, test, tid, viewer_uid=None, edit=False):
    meta     = get_test_meta(tid) or test
    qc       = len(test.get("questions",[])) or meta.get("question_count",0)
    diff     = {"easy":"🟢 Oson","medium":"🟡 O'rtacha",
                "hard":"🔴 Qiyin","expert":"⚡ Ekspert"}.get(meta.get("difficulty",""),"")
    att_t    = f"{meta.get('max_attempts',0)} marta" if meta.get("max_attempts",0) else "Cheksiz"
    vis      = {"public":"🌍 Ommaviy","link":"🔗 Link orqali",
                "private":"🔒 Shaxsiy"}.get(meta.get("visibility",""),"")
    pause_t  = "⚠️ <b>Vaqtincha to'xtatilgan!</b>\n\n" if meta.get("is_paused") else ""

    text = (
        f"📋 <b>TEST MA'LUMOTI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{pause_t}"
        f"📝 <b>{meta.get('title','Nomsiz')}</b>\n"
        f"📁 Fan: {meta.get('category','')}\n"
        f"📊 Qiyinlik: {diff}\n"
        f"🔒 Ko'rinish: {vis}\n"
        f"📋 Savollar: <b>{qc} ta</b>\n"
        f"⏱ Poll vaqti: {meta.get('poll_time',30)}s/savol\n"
        f"🎯 O'tish foizi: <b>{meta.get('passing_score',60)}%</b>\n"
        f"🔄 Urinishlar: {att_t}\n"
        f"👥 Ishlagan: <b>{meta.get('solve_count',0)} marta</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"▶️ Inline — savoldan keyin javob, 30s avto-o'tish\n"
        f"📊 Poll — Telegram quiz, vaqt bilan"
    )
    creator_id = meta.get("creator_id")
    kb = test_info_kb(tid, creator_id=creator_id, viewer_uid=viewer_uid)
    target = event if isinstance(event, Message) else event.message
    try:
        if edit and not isinstance(event, Message):
            await target.edit_text(text, reply_markup=kb)
        else:
            await target.answer(text, reply_markup=kb)
    except TelegramBadRequest:
        await target.answer(text, reply_markup=kb)


# ── Pause/Resume (creator/admin) ───────────────────────────────
@router.callback_query(F.data.startswith("test_pause_"))
async def test_pause_cb(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[11:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid)
    if not meta:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)
    if uid != meta.get("creator_id") and uid not in ADMIN_IDS:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)
    from utils.db import pause_test
    pause_test(tid, paused=True)
    await callback.answer("⏸ To'xtatildi", show_alert=True)
    from utils.db import get_test_full
    test = get_test_by_id(tid) or await get_test_full(tid)
    if test:
        await _send_test_card(callback, test, tid, viewer_uid=uid, edit=True)

@router.callback_query(F.data.startswith("test_resume_"))
async def test_resume_cb(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[12:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid)
    if not meta:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)
    if uid != meta.get("creator_id") and uid not in ADMIN_IDS:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)
    from utils.db import pause_test
    pause_test(tid, paused=False)
    await callback.answer("▶️ Qayta boshlandi!", show_alert=True)
    from utils.db import get_test_full
    test = get_test_by_id(tid) or await get_test_full(tid)
    if test:
        await _send_test_card(callback, test, tid, viewer_uid=uid, edit=True)


# ── Asosiy menyu ───────────────────────────────────────────────
@router.callback_query(F.data == "main_menu")
async def back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    try: await callback.message.delete()
    except: pass
    uid  = callback.from_user.id
    from utils import ram_cache as ram
    msg  = await callback.bot.send_message(uid, "🏠 <b>Asosiy menyu</b> 👇", reply_markup=main_kb(uid))
    ram.set_menu_msg(uid, uid, msg.message_id)

@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


# ── Adminga murojaat ───────────────────────────────────────────
@router.callback_query(F.data == "contact_admin")
async def contact_admin_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_contact"))
    try:
        await callback.message.edit_text(
            "<b>✉️ ADMINGA MUROJAAT</b>\n\nXabaringizni yozing:",
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
    try: await callback.message.delete()
    except: pass
    uid = callback.from_user.id
    await callback.bot.send_message(uid, "✅ Bekor qilindi.", reply_markup=main_kb(uid))

@router.message(ContactAdmin.waiting_message)
async def contact_admin_send(message: Message, state: FSMContext):
    uid   = message.from_user.id
    name  = message.from_user.full_name
    uname = f"@{message.from_user.username}" if message.from_user.username else "Yo'q"
    sent  = 0
    for aid in ADMIN_IDS:
        try:
            await message.bot.send_message(
                aid, f"📩 <b>MUROJAAT</b>\n👤 <b>{name}</b> | {uname} | <code>{uid}</code>"
            )
            await message.forward(aid)
            sent += 1
        except Exception as e: log.error(f"Admin {aid}: {e}")
    await state.clear()
    txt = "✅ Xabaringiz adminga yuborildi! 🙏" if sent else "⚠️ Yuborishda muammo."
    await message.answer(txt, reply_markup=main_kb(uid))

@router.message(F.text.startswith("/reply "))
async def admin_reply(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        return await message.answer("Format: <code>/reply USER_ID Matn</code>")
    try:
        await message.bot.send_message(
            int(parts[1]),
            f"📬 <b>ADMINDAN JAVOB:</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n{parts[2]}"
        )
        await message.answer(f"✅ <code>{parts[1]}</code> ga yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
