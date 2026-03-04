"""🚀 START — kirish, yordam, test kartochkasi"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from config import ADMIN_IDS, DIFFICULTY
from utils import store
from utils.states import Contact
from keyboards.kb import main_kb, test_card_kb, cancel_kb

log    = logging.getLogger(__name__)
router = Router()


# ── /start ───────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    uid   = msg.from_user.id
    uname = msg.from_user.username
    name  = msg.from_user.full_name or f"User{uid}"

    user = store.get_user(uid)
    if not user:
        user = {
            "uid": uid, "name": name, "username": uname,
            "is_blocked": False, "total": 0, "avg": 0.0,
        }
        store.upsert_user(uid, user)
        # Admin xabardor
        for aid in ADMIN_IDS:
            try:
                await msg.bot.send_message(
                    aid,
                    f"🆕 <b>Yangi foydalanuvchi!</b>\n"
                    f"👤 {name}  🔗 @{uname}  🆔 <code>{uid}</code>"
                )
            except:
                pass

    if user.get("is_blocked"):
        return await msg.answer("🚫 Siz bloklangansiz.")

    # Eski keyboard larni tozalash
    await msg.answer("🔄", reply_markup=remove_kb)

    # Deep link parametr?
    args = msg.text.split()
    if len(args) > 1:
        param = args[1].strip().upper()
        test  = store.get_test(param)
        if test:
            await msg.answer(f"👋 Salom, <b>{name}</b>!", reply_markup=main_kb(uid))
            return await _send_card(msg, test, param)

    await msg.answer(
        f"👋 Salom, <b>{name}</b>!\n\n"
        f"📚 <b>QuizBot</b> — test platformasi\n\n"
        f"Pastdagi menyudan tanlang 👇",
        reply_markup=main_kb(uid)
    )


# ── /help ────────────────────────────────────────────────

@router.message(Command("help"))
@router.message(F.text == "ℹ️ Yordam")
async def help_cmd(msg: Message):
    await msg.answer(
        "❓ <b>BOTDAN FOYDALANISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "▶️ <b>Inline</b> — har savoldan keyin natija ko'rinadi\n"
        "📊 <b>Poll</b> — Telegram quiz uslubida, vaqt bilan\n"
        "👥 <b>Guruh</b> — guruhda birga yechish + reyting\n\n"
        "📁 Test kodi yuboring → kartochka chiqadi\n"
        "➕ Test yaratish → TXT/PDF/DOCX fayl yuboring\n\n"
        "Muammo bo'lsa adminga murojaat qiling 👇",
        reply_markup=_contact_kb()
    )


def _contact_kb():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✉️ Adminga yozish", callback_data="contact_admin"))
    return b.as_markup()


# ── Test kodi (to'g'ridan) ───────────────────────────────

@router.message(F.text)
async def maybe_test_code(msg: Message, state: FSMContext):
    if msg.chat.type != "private":
        return
    cur = await state.get_state()
    if cur:  # FSM faol bo'lsa o'tkazib yubor
        return
    text = (msg.text or "").strip()
    # Test kodi: 6-20 belgi, bo'sh joy yo'q, slash yo'q
    if not text or " " in text or "/" in text or len(text) not in range(6, 21):
        return
    test = store.get_test(text.upper())
    if test:
        await _send_card(msg, test, text.upper())


# ── Test kartochkasi ─────────────────────────────────────

async def _send_card(event, test, tid):
    """Kartochkani Message yoki CallbackQuery ga yuboradi."""
    qs    = test.get("questions", [])
    q_cnt = len(qs) if qs else test.get("question_count", 0)
    d     = DIFFICULTY.get(test.get("difficulty", ""), "")
    pt    = test.get("poll_time", 30)
    pt_t  = f"{pt}s/savol" if pt else "Vaqtsiz"
    tl    = test.get("time_limit", 0)
    tl_t  = f"{tl} daqiqa" if tl else "Cheksiz"
    att   = test.get("max_attempts", 0)
    att_t = f"{att} marta" if att else "Cheksiz"

    text = (
        f"📋 <b>TEST MA'LUMOTI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 <b>{test.get('title','Nomsiz')}</b>\n"
        f"📁 Fan: {test.get('category','')}\n"
        f"📊 Qiyinlik: {d}\n"
        f"📋 Savollar: <b>{q_cnt} ta</b>\n"
        f"⏱ Umumiy vaqt: {tl_t}\n"
        f"⏱ Poll vaqti: {pt_t}\n"
        f"🎯 O'tish foizi: <b>{test.get('passing_score',60)}%</b>\n"
        f"🔄 Urinishlar: {att_t}\n"
        f"👥 Ishlagan: <b>{test.get('solve_count',0)} marta</b>"
    )
    kb = test_card_kb(tid)

    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb)
    else:
        try:
            await event.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest:
            await event.message.answer(text, reply_markup=kb)

# Export for other handlers
send_card = _send_card


# ── Menyu ────────────────────────────────────────────────

@router.callback_query(F.data == "main_menu")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    uid = cb.from_user.id
    try:
        await cb.message.delete()
    except:
        pass
    await cb.bot.send_message(uid, "🏠 <b>Asosiy menyu</b>", reply_markup=main_kb(uid))


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer()


@router.callback_query(F.data == "cancel")
async def cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    try:
        await cb.message.delete()
    except:
        pass
    await cb.bot.send_message(
        cb.from_user.id, "❌ Bekor qilindi.", reply_markup=main_kb(cb.from_user.id)
    )


# ── Adminga murojaat ─────────────────────────────────────

@router.callback_query(F.data == "contact_admin")
async def contact_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer(
        "✉️ <b>Xabaringizni yozing:</b>\n"
        "<i>(matn, rasm yoki fayl)</i>",
        reply_markup=cancel_kb()
    )
    await state.set_state(Contact.writing)


@router.message(Contact.writing)
async def contact_send(msg: Message, state: FSMContext):
    await state.clear()
    name  = msg.from_user.full_name
    uname = f"@{msg.from_user.username}" if msg.from_user.username else "yo'q"
    uid   = msg.from_user.id
    ok    = 0
    for aid in ADMIN_IDS:
        try:
            await msg.bot.send_message(
                aid,
                f"📩 <b>Foydalanuvchidan murojaat</b>\n"
                f"👤 {name} | {uname} | <code>{uid}</code>"
            )
            await msg.forward(aid)
            ok += 1
        except:
            pass
    if ok:
        await msg.answer("✅ Xabaringiz adminga yuborildi!", reply_markup=main_kb(uid))
    else:
        await msg.answer("⚠️ Yuborishda xatolik.", reply_markup=main_kb(uid))
