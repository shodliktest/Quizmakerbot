"""🚀 START — Xush kelibsiz, test kartochkasi, yordam"""
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
from keyboards.keyboards import main_kb, test_info_kb, test_info_simple_kb
from utils.states import ContactAdmin

log    = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid   = message.from_user.id
    uname = message.from_user.username
    name  = (message.from_user.full_name or
             (f"@{uname}" if uname else f"User{uid}"))

    user   = await get_or_create_user(uid, name, uname)
    is_new = user.pop("_just_created", False)

    if user.get("is_blocked"):
        return await message.answer("🚫 Siz bloklangansiz.")

    if is_new:
        at = f"@{uname}" if uname else "Yo'q"
        for aid in ADMIN_IDS:
            try:
                await message.bot.send_message(
                    aid,
                    f"🆕 <b>YANGI FOYDALANUVCHI!</b>\n"
                    f"👤 <b>{name}</b> | {at} | <code>{uid}</code>"
                )
            except Exception:
                pass
        welcome = (
            f"👋 Salom, <b>{name}</b>! 🎓\n"
            f"<b>Quiz Bot</b> platformasiga xush kelibsiz!\n\n"
            f"📚 Testlar — ommaviy testlar\n"
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

        # ?start=create — test yaratish
        if param.lower() == "create":
            await message.answer(welcome, reply_markup=main_kb(uid))
            await message.answer(
                "➕ <b>TEST YARATISH</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "<b>Test Yaratish</b> tugmasini bosing 👇",
                reply_markup=main_kb(uid)
            )
            return

        # ?start=poll_TID — poll rejimi
        if param.lower().startswith("poll_"):
            tid  = param[5:].upper()
            test = get_test_by_id(tid) or await _gtf(tid)
            if test:
                # Link orqali kiruvchi
                via_link = test.get("visibility") == "link"
                await message.answer(welcome, reply_markup=main_kb(uid))
                b = InlineKeyboardBuilder()
                b.row(InlineKeyboardButton(
                    text="📊 Poll rejimni boshlash",
                    callback_data=f"start_poll_{tid}"
                    + ("_link" if via_link else "")
                ))
                b.row(InlineKeyboardButton(text="▶️ Inline rejim", callback_data=f"start_test_{tid}"))
                await message.answer(
                    f"📝 <b>{test.get('title')}</b>\nQaysi rejimda boshlash?",
                    reply_markup=b.as_markup()
                )
                return

        # ?start=TID — test kartochkasi
        tid  = param.upper()
        test = get_test_by_id(tid) or await _gtf(tid)
        if test:
            await message.answer(welcome, reply_markup=main_kb(uid))
            via_link = test.get("visibility") == "link"
            await _send_test_card(message, test, tid, viewer_uid=uid, via_link=via_link)
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
        "   to'g'ri/noto'g'ri ko'rsatadi, 30s avto-o'tish\n\n"
        "2️⃣ <b>📊 Quiz Poll</b> — Telegram native quiz poll\n"
        "   vaqt tugasa keyingi savolga o'tadi, pauza bor\n\n"
        "3️⃣ <b>👥 Guruhda yechish</b> — quiz poll rejimi\n"
        "   guruhda jamoa bilan, oxirida leaderboard\n\n"
        "4️⃣ <b>📤 Ulashish</b> — inline orqali yuborish\n"
        "   3 ta rejimdan birini tanlab boshlash mumkin\n\n"
        "5️⃣ <b>🔗 Link testlar</b> — maxsus ssilka testlar\n"
        "   faqat havola orqali kirish, cheksiz urinish\n\n"
        "6️⃣ <b>📊 Natijalarim</b> — barcha urinishlar foizi\n"
        "   faqat oxirgi test uchun batafsil tahlil\n\n"
        "7️⃣ <b>Test kodi</b> — to'g'ridan kodni yuboring\n\n"
        "💬 <i>Muammo bo'lsa adminga murojaat qiling:</i>"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✉️ Adminga murojaat", callback_data="contact_admin"))
    b.row(InlineKeyboardButton(text="🏠 Asosiy menyu",     callback_data="main_menu"))
    try:
        if edit:
            await msg.edit_text(text, reply_markup=b.as_markup())
            return
    except Exception:
        pass
    await msg.answer(text, reply_markup=b.as_markup())


async def _send_test_card(event, test, tid, viewer_uid=None, via_link=False, edit=False):
    from utils.ram_cache import get_test_meta as _get_meta
    meta  = _get_meta(tid) or test
    qc    = len(test.get("questions", [])) or meta.get("question_count", 0)
    diff  = {"easy":"🟢 Oson","medium":"🟡 O'rtacha",
              "hard":"🔴 Qiyin","expert":"⚡ Ekspert"}.get(meta.get("difficulty",""), "")
    pt_t  = f"{meta.get('poll_time',30)}s/savol"
    att_t = f"{meta.get('max_attempts',0)} marta" if meta.get("max_attempts",0) else "Cheksiz"
    vis   = {"public":"🌍 Ommaviy","link":"🔗 Link orqali",
              "private":"🔒 Shaxsiy"}.get(meta.get("visibility",""),"")
    pause = "⚠️ <b>Vaqtincha to'xtatilgan!</b>\n" if meta.get("is_paused") else ""

    text = (
        f"📋 <b>TEST MA'LUMOTI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{pause}"
        f"📝 <b>{meta.get('title','Nomsiz')}</b>\n"
        f"📁 Fan: {meta.get('category','')}\n"
        f"📊 Qiyinlik: {diff}\n"
        f"🔒 Ko'rinish: {vis}\n"
        f"📋 Savollar: <b>{qc} ta</b>\n"
        f"⏱ Poll vaqti: {pt_t} | Urinish: {att_t}\n"
        f"🎯 O'tish foizi: <b>{meta.get('passing_score',60)}%</b>\n"
        f"👥 Ishlagan: <b>{meta.get('solve_count',0)} marta</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"▶️ <b>Inline</b> — savoldan keyin to'g'ri/noto'g'ri\n"
        f"📊 <b>Poll</b> — quiz poll, vaqt bilan\n"
        f"👥 <b>Guruh</b> — jamoa bilan, leaderboard"
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


# ── Test pause/resume (creator/admin) ─────────────────────────

@router.callback_query(F.data.startswith("test_pause_"))
async def test_pause_cb(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[11:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid)

    if not meta:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    from config import ADMIN_IDS as _ADMIN
    if uid != meta.get("creator_id") and uid not in _ADMIN:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    from utils.db import pause_test
    pause_test(tid, paused=True)
    await callback.answer("⏸ Test to'xtatildi", show_alert=True)

    # Kartochkani yangilash
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

    from config import ADMIN_IDS as _ADMIN
    if uid != meta.get("creator_id") and uid not in _ADMIN:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    from utils.db import pause_test
    pause_test(tid, paused=False)
    await callback.answer("▶️ Test qayta boshlandi!", show_alert=True)

    from utils.db import get_test_full
    test = get_test_by_id(tid) or await get_test_full(tid)
    if test:
        await _send_test_card(callback, test, tid, viewer_uid=uid, edit=True)


# ── Test solvers (creator/admin uchun) ────────────────────────

@router.callback_query(F.data.startswith("test_solvers_"))
async def test_solvers_cb(callback: CallbackQuery):
    await callback.answer()
    parts    = callback.data[13:].rsplit("_", 1)
    tid      = parts[0]
    page     = int(parts[1]) if len(parts) > 1 else 0
    uid      = callback.from_user.id
    meta     = get_test_meta(tid)

    if not meta:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    from config import ADMIN_IDS as _ADMIN
    if uid != meta.get("creator_id") and uid not in _ADMIN:
        return await callback.answer("⚠️ Faqat test egasi yoki admin!", show_alert=True)

    from utils.db import get_test_solvers
    solvers = get_test_solvers(tid)

    if not solvers:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"view_test_{tid}"))
        try:
            await callback.message.edit_text(
                f"📊 <b>{meta.get('title','Test')} — KIM YECHGAN</b>\n\n"
                f"😔 Hali hech kim yechmagan.",
                reply_markup=b.as_markup()
            )
        except TelegramBadRequest:
            pass
        return

    PG    = 5
    total = (len(solvers) + PG - 1) // PG
    page  = max(0, min(page, total - 1))
    chunk = solvers[page * PG:(page + 1) * PG]

    text = (
        f"📊 <b>{meta.get('title','Test')} — KIM YECHGAN</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Jami: {len(solvers)} kishi | Sahifa {page+1}/{total}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    b = InlineKeyboardBuilder()
    for sv in chunk:
        all_p_str = " → ".join(f"{p}%" for p in sv["all_pcts"])
        uname = sv.get("username", "")
        uname_txt = f"@{uname} " if uname else ""
        text += (
            f"👤 <b>{sv['name']}</b> {uname_txt}\n"
            f"   🔄 {sv['attempts']} urinish | ⭐ Eng yaxshi: {sv['best_score']}%\n"
            f"   📈 Foizlar: {all_p_str}\n\n"
        )
        b.row(InlineKeyboardButton(
            text=f"🔍 {sv['name'][:20]} — {sv['best_score']}%",
            callback_data=f"solver_detail_{tid}_{sv['uid']}"
        ))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"test_solvers_{tid}_{page-1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"test_solvers_{tid}_{page+1}"))
    if nav: b.row(*nav)
    b.row(
        InlineKeyboardButton(text="📄 TXT yuklab olish", callback_data=f"solvers_txt_{tid}"),
        InlineKeyboardButton(text="⬅️ Orqaga",           callback_data=f"view_test_{tid}"),
    )
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("solver_detail_"))
async def solver_detail_cb(callback: CallbackQuery):
    await callback.answer()
    parts   = callback.data[14:].split("_", 1)
    tid     = parts[0]
    uid_str = parts[1] if len(parts) > 1 else ""
    viewer  = callback.from_user.id
    meta    = get_test_meta(tid)

    from config import ADMIN_IDS as _ADMIN
    if viewer != meta.get("creator_id") and viewer not in _ADMIN:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    from utils.db import get_test_solvers
    from utils.ram_cache import get_users
    solvers = get_test_solvers(tid)
    sv      = next((s for s in solvers if s["uid"] == uid_str), None)
    if not sv:
        return await callback.answer("Topilmadi.", show_alert=True)

    first = sv.get("first_result") or {}
    all_p = sv.get("all_pcts", [])
    attempts_txt = "\n".join(
        f"  {'1-urinish (birinchi)' if i == 0 else f'{i+1}-urinish'}: "
        f"{'✅' if p >= meta.get('passing_score', 60) else '❌'} {p}%"
        for i, p in enumerate(all_p)
    )

    text = (
        f"👤 <b>{sv['name']}</b> — {meta.get('title','Test')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔄 Jami urinishlar: <b>{sv['attempts']}</b>\n"
        f"⭐ Eng yaxshi: <b>{sv['best_score']}%</b>\n"
        f"📈 O'rtacha: <b>{sv['avg_score']}%</b>\n\n"
        f"📋 Barcha urinishlar:\n"
        f"<code>{attempts_txt}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>1-urinish tafsiloti:</b>\n"
        f"📊 {first.get('percentage',0)}% | ✅{first.get('correct_count',0)} ❌{first.get('wrong_count',0)}"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"test_solvers_{tid}_0"))
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("solvers_txt_"))
async def solvers_txt_cb(callback: CallbackQuery):
    await callback.answer("⏳ TXT tayyorlanmoqda...")
    tid  = callback.data[12:]
    uid  = callback.from_user.id
    meta = get_test_meta(tid)

    from config import ADMIN_IDS as _ADMIN
    if uid != meta.get("creator_id") and uid not in _ADMIN:
        return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    from utils.db import get_test_solvers
    from aiogram.types import BufferedInputFile
    solvers = get_test_solvers(tid)

    lines = [
        f"TEST: {meta.get('title',tid)}",
        f"KOD: {tid}",
        f"JAMI QATNASHCHILAR: {len(solvers)}",
        "=" * 55, ""
    ]
    for i, sv in enumerate(solvers, 1):
        all_p = " → ".join(f"{p}%" for p in sv["all_pcts"])
        lines.append(f"{i}. {sv['name']}")
        un = sv.get("username","")
        if un: lines.append(f"   @{un}")
        lines.append(f"   Urinishlar: {sv['attempts']}")
        lines.append(f"   Foizlar: {all_p}")
        lines.append(f"   Eng yaxshi: {sv['best_score']}%")
        lines.append(f"   O'rtacha: {sv['avg_score']}%")
        fr = sv.get("first_result") or {}
        if fr:
            lines.append(
                f"   1-urinish: {fr.get('percentage',0)}% | "
                f"To'g'ri: {fr.get('correct_count',0)} | "
                f"Xato: {fr.get('wrong_count',0)}"
            )
        lines.append("")

    txt = "\n".join(lines)
    doc = BufferedInputFile(txt.encode("utf-8"),
                            filename=f"solvers_{meta.get('title',tid)}.txt")
    await callback.message.answer_document(
        doc,
        caption=(
            f"📊 <b>{meta.get('title',tid)}</b>\n"
            f"👥 {len(solvers)} qatnashchi"
        )
    )


# ── Asosiy menyu ───────────────────────────────────────────────

@router.callback_query(F.data == "main_menu")
async def back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    try: await callback.message.delete()
    except Exception: pass
    uid = callback.from_user.id
    await callback.bot.send_message(
        uid, "🏠 <b>Asosiy menyu</b> 👇",
        reply_markup=main_kb(uid)
    )

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
            "<b>✉️ ADMINGA MUROJAAT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Xabaringizni yozing:\n"
            "<i>(matn, rasm yoki fayl yuborishingiz mumkin)</i>",
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
    except Exception: pass
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
                aid,
                f"📩 <b>FOYDALANUVCHIDAN</b>\n"
                f"👤 <b>{name}</b> | {uname} | <code>{uid}</code>"
            )
            await message.forward(aid)
            sent += 1
        except Exception as e:
            log.error(f"Admin {aid}: {e}")
    await state.clear()
    txt = "✅ Xabaringiz adminga yuborildi! 🙏" if sent else "⚠️ Yuborishda muammo yuz berdi."
    await message.answer(txt, reply_markup=main_kb(uid))

@router.message(F.text.startswith("/reply "))
async def admin_reply(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        return await message.answer("Format: <code>/reply USER_ID Matn</code>")
    try:
        target_id = int(parts[1])
        await message.bot.send_message(
            target_id,
            f"📬 <b>ADMINDAN JAVOB:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{parts[2]}"
        )
        await message.answer(f"✅ <code>{target_id}</code> ga yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
