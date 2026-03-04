"""➕ TEST YARATISH"""
import os, logging, tempfile, uuid
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from utils import store
from utils.parser import parse_file, parse_text
from utils.states import Create
from config import DIFFICULTY
from keyboards.kb import (
    subject_kb, difficulty_kb, visibility_kb,
    test_created_kb, cancel_kb, main_kb
)

log    = logging.getLogger(__name__)
router = Router()

POLL_TIMES  = [10, 15, 20, 30, 45, 60, 120]
SAMPLE_TEXT = (
    "1. O'zbekiston poytaxti?\n"
    "*A) Toshkent\n"
    "B) Samarqand\n"
    "C) Buxoro\n\n"
    "2. Pi soni taxminan?\n"
    "A) 2.14\n"
    "*B) 3.14\n"
    "C) 4.14\n\n"
    "TYPE: true_false\n"
    "3. Yer yumaloqmi?\n"
    "Javob: Ha\n"
    "Izoh: Ha, Yer sharsimon."
)


async def _del(bot, cid, mid):
    try: await bot.delete_message(cid, mid)
    except: pass


# ═══════════════════════════════════════════════════════════
# BOSHLASH
# ═══════════════════════════════════════════════════════════

@router.message(F.text == "➕ Test Yaratish")
async def create_start(msg: Message, state: FSMContext):
    await state.clear()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📁 Fayl (TXT/PDF/DOCX)", callback_data="cm_file"))
    b.row(InlineKeyboardButton(text="💬 Matn (chat orqali)",   callback_data="cm_text"))
    b.row(InlineKeyboardButton(text="📊 QuizBot forward",      callback_data="cm_poll"))
    b.row(InlineKeyboardButton(text="❌ Bekor",                callback_data="cancel"))
    await msg.answer(
        "<b>➕ TEST YARATISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📁 <b>Fayl</b> — TXT, PDF, DOCX yuklang\n"
        "💬 <b>Matn</b> — savollarni chat orqali yuboring\n"
        "📊 <b>QuizBot</b> — @QuizBot savollarini forward qiling\n\n"
        f"<i>Namuna format:</i>\n\n<code>{SAMPLE_TEXT[:200]}...</code>",
        reply_markup=b.as_markup()
    )
    await state.set_state(Create.method)


# ═══════════════════════════════════════════════════════════
# FAYL USULI
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "cm_file", Create.method)
async def method_file(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.edit_text(
        "<b>📁 FAYL YUKLASH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "TXT, PDF yoki DOCX faylni yuboring.\n\n"
        f"<b>Namuna format:</b>\n<code>{SAMPLE_TEXT}</code>",
        reply_markup=cancel_kb()
    )
    await state.set_state(Create.file)


@router.message(F.document, Create.file)
async def upload_file(msg: Message, state: FSMContext):
    doc = msg.document
    if not doc.file_name.lower().endswith((".txt", ".pdf", ".docx", ".doc")):
        return await msg.answer("❌ Faqat TXT, PDF, DOCX qabul qilinadi!")

    status = await msg.answer("⏳ Tahlil qilinmoqda...")
    try:
        file   = await msg.bot.get_file(doc.file_id)
        suffix = os.path.splitext(doc.file_name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            await msg.bot.download_file(file.file_path, tmp.name)
            tmp_path = tmp.name

        questions = parse_file(tmp_path)
        os.remove(tmp_path)
        await _del(msg.bot, msg.chat.id, msg.message_id)

        if not questions:
            return await status.edit_text(
                "❌ <b>Savollar topilmadi!</b>\n\n"
                "To'g'ri javob oldiga <b>*</b> yoki <b>===</b> qo'ying:\n"
                "<code>*A) To'g'ri javob</code>"
            )
        await state.update_data(questions=questions)
        await status.edit_text(
            f"✅ <b>{len(questions)} ta savol topildi!</b>\n\n⏱ Har savolga necha soniya?",
            reply_markup=_poll_time_kb()
        )
        await state.set_state(Create.poll_time)
    except Exception as e:
        log.error(f"upload_file: {e}")
        await status.edit_text("❌ Faylni o'qishda xatolik.")


# ═══════════════════════════════════════════════════════════
# MATN USULI
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "cm_text", Create.method)
async def method_text(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.edit_text(
        "<b>💬 MATN ORQALI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Savollarni yuboring (bir yoki ko'p xabar).\n"
        "Tayyor bo'lgach <b>✅ Tayyor</b> bosing.\n\n"
        f"<b>Format:</b>\n<code>{SAMPLE_TEXT}</code>",
        reply_markup=_text_ready_kb()
    )
    await state.update_data(text_buffer=[], progress_id=None)
    await state.set_state(Create.file)


@router.message(F.text, Create.file)
async def collect_text(msg: Message, state: FSMContext):
    text = (msg.text or "").strip()
    if len(text) < 5:
        return
    d   = await state.get_data()
    buf = d.get("text_buffer", [])
    buf.append(text)
    await state.update_data(text_buffer=buf)
    await _del(msg.bot, msg.chat.id, msg.message_id)

    old = d.get("progress_id")
    b   = _text_ready_kb()
    txt = f"📥 <b>{len(buf)} ta xabar qabul qilindi</b>\n\n<i>✅ Tayyor bosing</i>"
    if old:
        try:
            await msg.bot.edit_message_text(
                chat_id=msg.chat.id, message_id=old, text=txt, reply_markup=b
            )
            return
        except: pass
    pm = await msg.answer(txt, reply_markup=b)
    await state.update_data(progress_id=pm.message_id)


@router.callback_query(F.data == "cm_finish_text", Create.file)
async def finish_text(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    d   = await state.get_data()
    buf = d.get("text_buffer", [])
    if not buf:
        return await cb.answer("❌ Hali matn yuborilmadi!", show_alert=True)

    full_text = "\n\n".join(buf)
    status    = await cb.message.edit_text("⏳ Tahlil qilinmoqda...")
    try:
        questions = parse_text(full_text)
        if not questions:
            return await status.edit_text(
                "❌ Savollar topilmadi!\n\n"
                "To'g'ri javob oldiga <b>*</b> qo'ying:\n"
                "<code>*A) To'g'ri</code>"
            )
        await state.update_data(questions=questions, text_buffer=[])
        await status.edit_text(
            f"✅ <b>{len(questions)} ta savol topildi!</b>\n\n⏱ Har savolga necha soniya?",
            reply_markup=_poll_time_kb()
        )
        await state.set_state(Create.poll_time)
    except Exception as e:
        log.error(f"finish_text: {e}")
        await status.edit_text("❌ Matnni tahlil qilishda xatolik.")


# ═══════════════════════════════════════════════════════════
# QUIZBOT FORWARD
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "cm_poll", Create.method)
async def method_poll(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.edit_text(
        "<b>📊 QUIZBOT FORWARD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1. @QuizBot ga boring\n"
        "2. Quiz savollarini bu yerga forward qiling\n"
        "3. Hammasini yuborgach <b>✅ Tayyor</b> bosing\n\n"
        "<i>Faqat Quiz (Viktorina) turi qabul qilinadi</i>",
        reply_markup=_polls_ready_kb()
    )
    await state.update_data(questions=[], progress_id=None)
    await state.set_state(Create.polls)


@router.message(F.poll, Create.polls)
async def catch_poll(msg: Message, state: FSMContext):
    if msg.poll.type != "quiz":
        await _del(msg.bot, msg.chat.id, msg.message_id)
        return await msg.answer("❌ Faqat <b>Viktorina (Quiz)</b> turi qabul qilinadi!")

    import re as _re
    p   = msg.poll
    LT  = ["A)","B)","C)","D)","E)","F)"]
    opts = [f"{LT[i]} {op.text}" for i, op in enumerate(p.options)]
    q_clean = _re.sub(r"^\[\d+/\d+\]\s*", "", p.question).strip()

    d  = await state.get_data()
    qs = d.get("questions", [])
    qs.append({
        "type":        "multiple_choice",
        "question":    q_clean,
        "options":     opts,
        "correct":     opts[p.correct_option_id],
        "explanation": p.explanation or "",
        "points":      1,
    })
    await state.update_data(questions=qs)
    await _del(msg.bot, msg.chat.id, msg.message_id)

    d2  = await state.get_data()
    old = d2.get("progress_id")
    if old:
        await _del(msg.bot, msg.chat.id, old)

    pm = await msg.answer(
        f"📥 <b>{len(qs)} ta savol qabul qilindi</b>",
        reply_markup=_polls_ready_kb()
    )
    await state.update_data(progress_id=pm.message_id)


@router.callback_query(F.data == "cm_finish_polls", Create.polls)
async def finish_polls(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if not d.get("questions"):
        return await cb.answer("❌ Hali savol yo'q!", show_alert=True)
    await cb.answer()
    await cb.message.edit_text(
        f"✅ <b>{len(d['questions'])} ta savol</b>\n\n⏱ Har savolga necha soniya?",
        reply_markup=_poll_time_kb()
    )
    await state.set_state(Create.poll_time)


# ═══════════════════════════════════════════════════════════
# SOZLAMALAR ZANJIRI
# ═══════════════════════════════════════════════════════════

def _poll_time_kb():
    b = InlineKeyboardBuilder()
    for s in POLL_TIMES:
        b.add(InlineKeyboardButton(text=f"⏱ {s}s", callback_data=f"pt_{s}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Vaqtsiz", callback_data="pt_0"))
    return b.as_markup()


@router.callback_query(F.data.startswith("pt_"))
async def set_pt(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    pt = int(cb.data[3:])
    await state.update_data(poll_time=pt)
    ptt = f"{pt}s/savol" if pt else "Vaqtsiz"
    await cb.message.edit_text(
        f"⏱ Savol vaqti: <b>{ptt}</b>\n\n📁 Qaysi fanga tegishli?",
        reply_markup=subject_kb()
    )
    await state.set_state(Create.subject)


@router.callback_query(F.data.startswith("subj_"), Create.subject)
async def set_subject(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    s = cb.data[5:]
    if s == "other":
        return await cb.message.edit_text(
            "✏️ <b>Fan nomini yozing:</b>",
            reply_markup=cancel_kb()
        )
    await state.update_data(category=s)
    await cb.message.edit_text(
        f"📁 Fan: <b>{s}</b>\n\n🏷 <b>Test nomini yozing:</b>",
        reply_markup=cancel_kb()
    )
    await state.set_state(Create.title)


@router.message(F.text, Create.subject)
async def subject_custom(msg: Message, state: FSMContext):
    await state.update_data(category=msg.text.strip())
    await _del(msg.bot, msg.chat.id, msg.message_id)
    await msg.answer(f"📁 Fan: <b>{msg.text.strip()}</b>\n\n🏷 <b>Test nomini yozing:</b>",
                     reply_markup=cancel_kb())
    await state.set_state(Create.title)


@router.message(F.text, Create.title)
async def set_title(msg: Message, state: FSMContext):
    await state.update_data(title=msg.text.strip())
    await _del(msg.bot, msg.chat.id, msg.message_id)
    await msg.answer(
        f"🏷 Nom: <b>{msg.text.strip()}</b>\n\n📊 <b>Qiyinlik darajasi?</b>",
        reply_markup=difficulty_kb()
    )
    await state.set_state(Create.difficulty)


@router.callback_query(F.data.startswith("diff_"), Create.difficulty)
async def set_diff(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(difficulty=cb.data[5:])
    b = InlineKeyboardBuilder()
    for m in [15, 20, 30, 45, 60, 90, 120]:
        b.add(InlineKeyboardButton(text=f"⏱ {m}daq", callback_data=f"tl_{m}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data="tl_0"))
    await cb.message.edit_text("⏱ <b>Umumiy vaqt limiti?</b>", reply_markup=b.as_markup())
    await state.set_state(Create.time_limit)


@router.callback_query(F.data.startswith("tl_"), Create.time_limit)
async def set_tl(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(time_limit=int(cb.data[3:]))
    b = InlineKeyboardBuilder()
    for p in [50, 60, 70, 80, 90, 100]:
        b.add(InlineKeyboardButton(text=f"{p}%", callback_data=f"ps_{p}"))
    b.adjust(3)
    await cb.message.edit_text("🎯 <b>O'tish foizi?</b>", reply_markup=b.as_markup())
    await state.set_state(Create.passing)


@router.callback_query(F.data.startswith("ps_"), Create.passing)
async def set_passing(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(passing_score=int(cb.data[3:]))
    b = InlineKeyboardBuilder()
    for a in [1, 2, 3, 5, 10]:
        b.add(InlineKeyboardButton(text=f"🔄 {a}x", callback_data=f"at_{a}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data="at_0"))
    await cb.message.edit_text("🔄 <b>Urinishlar soni?</b>", reply_markup=b.as_markup())
    await state.set_state(Create.attempts)


@router.callback_query(F.data.startswith("at_"), Create.attempts)
async def set_attempts(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(max_attempts=int(cb.data[3:]))
    await cb.message.edit_text("🔒 <b>Test maxfiyligi?</b>", reply_markup=visibility_kb())
    await state.set_state(Create.visibility)


# ═══════════════════════════════════════════════════════════
# SAQLASH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("vis_"), Create.visibility)
async def save_test(cb: CallbackQuery, state: FSMContext):
    await cb.answer("⏳")
    d = await state.get_data()

    tid = str(uuid.uuid4())[:8].upper()
    test = {
        "test_id":       tid,
        "creator_id":    cb.from_user.id,
        "title":         d.get("title", "Nomsiz"),
        "category":      d.get("category", "Boshqa"),
        "difficulty":    d.get("difficulty", "medium"),
        "visibility":    cb.data[4:],
        "time_limit":    d.get("time_limit", 0),
        "poll_time":     d.get("poll_time", 30),
        "passing_score": d.get("passing_score", 60),
        "max_attempts":  d.get("max_attempts", 0),
        "questions":     d.get("questions", []),
        "question_count": len(d.get("questions", [])),
        "solve_count":   0,
        "is_active":     True,
    }

    store.add_test(test)
    await state.clear()

    # TG kanalga yuborish (background)
    import asyncio
    asyncio.create_task(store.save_test_tg(test))

    bu   = (await cb.bot.me()).username
    link = f"https://t.me/{bu}?start={tid}"
    diff = DIFFICULTY.get(test["difficulty"], "")
    pt_t = f"{test['poll_time']}s/savol" if test["poll_time"] else "Vaqtsiz"
    tl_t = f"{test['time_limit']} daqiqa"  if test["time_limit"] else "Cheksiz"

    await cb.message.edit_text(
        f"🎉 <b>TEST YARATILDI!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Kod: <code>{tid}</code>\n"
        f"🔗 <code>{link}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {test['title']}\n"
        f"📁 {test['category']} | {diff}\n"
        f"📋 <b>{len(test['questions'])} ta savol</b>\n"
        f"⏱ {tl_t} | Poll: {pt_t}\n"
        f"🎯 O'tish: {test['passing_score']}%\n\n"
        f"👇 Test boshlansin:",
        reply_markup=test_created_kb(tid, bu)
    )

    # Kalitlar
    keys = f"🔑 <b>JAVOBLAR KALITI</b>\n<code>{tid}</code>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, q in enumerate(test["questions"], 1):
        keys += f"<b>{i}.</b> {q.get('correct','?')}\n"
    if len(keys) <= 4000:
        await cb.message.answer(keys)


# ═══════════════════════════════════════════════════════════
# YORDAMCHI KBLAR
# ═══════════════════════════════════════════════════════════

def _text_ready_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Tayyor (parse qilish)", callback_data="cm_finish_text"))
    b.row(InlineKeyboardButton(text="❌ Bekor",                 callback_data="cancel"))
    return b.as_markup()

def _polls_ready_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Tayyor", callback_data="cm_finish_polls"))
    b.row(InlineKeyboardButton(text="❌ Bekor",  callback_data="cancel"))
    return b.as_markup()
