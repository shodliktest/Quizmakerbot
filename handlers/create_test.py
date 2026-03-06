"""➕ TEST YARATISH — Fayl yoki QuizBot forward"""
import os, logging, tempfile
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from utils.parser import parse_file
from utils.states import CreateTest
from utils.db import create_test
from keyboards.keyboards import subject_kb, difficulty_kb, visibility_kb, main_kb, test_created_kb

def _get_user_subjects(uid):
    from utils.ram_cache import get_user_custom_subjects
    return get_user_custom_subjects(uid)

log        = logging.getLogger(__name__)
router     = Router()
SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples")
POLL_TIMES  = [10, 12, 20, 30, 50, 120]

SAMPLE_TYPES = {
    "mcq": (
        "mcq_namuna.txt",
        "🔘 Bir javobli (MCQ)",
        (
            "1. O'zbekiston poytaxti qayer?\n"
            "===A) Toshkent\n"
            "B) Samarqand\n"
            "C) Buxoro\n"
            "D) Xiva\n"
            "Izoh: Toshkent 1930-yildan poytaxt.\n\n"
            "2. Pi soni taxminan qancha?\n"
            "A) 2.14\n"
            "===B) 3.14\n"
            "C) 4.14\n"
            "D) 5.14"
        )
    ),
    "tf": (
        "tf_namuna.txt",
        "✅ Ha / Yo'q",
        (
            "TYPE: true_false\n"
            "1. Yer Quyosh atrofida aylanadi.\n"
            "Javob: Ha\n"
            "Izoh: Yer elliptik orbita bo'ylab aylanadi.\n\n"
            "TYPE: true_false\n"
            "2. Quyosh Yerdan kichik.\n"
            "Javob: Yoq\n"
            "Izoh: Quyosh Yerdan 109 marta katta."
        )
    ),
    "fill": (
        "fill_namuna.txt",
        "✍️ Bo'sh joy to'ldirish",
        (
            "TYPE: fill_blank\n"
            "1. Alisher Navoiy ___ yilda tug'ilgan.\n"
            "Javob: 1441\n"
            "Qabul: 1441-yil, 1441 yil\n\n"
            "TYPE: fill_blank\n"
            "2. O'zbekiston mustaqilligini ___ yilda qo'lga kiritdi.\n"
            "Javob: 1991\n"
            "Qabul: 1991-yil"
        )
    ),
    "text": (
        "text_namuna.txt",
        "💬 Erkin javob",
        (
            "TYPE: text_input\n"
            "1. Fotosintez jarayonini tushuntiring.\n"
            "Javob: o'simliklarning quyosh nuri yordamida oziq yaratishi\n"
            "Qabul: fotosintez, quyosh energiyasini kimyoviy energiyaga aylantirish\n\n"
            "TYPE: text_input\n"
            "2. Demokratiya nima?\n"
            "Javob: xalq hokimiyati"
        )
    ),
    "all": (
        "all_namuna.txt",
        "📦 Aralash turlar",
        (
            "1. O'zbekiston poytaxti?\n"
            "===A) Toshkent\n"
            "B) Samarqand\n"
            "C) Buxoro\n\n"
            "TYPE: true_false\n"
            "2. Yer yumaloqmi?\n"
            "Javob: Ha\n\n"
            "TYPE: fill_blank\n"
            "3. 2 + 2 = ___\n"
            "Javob: 4\n\n"
            "TYPE: text_input\n"
            "4. Vatanimiz nomi?\n"
            "Javob: O'zbekiston"
        )
    ),
}


async def _del(bot, cid, mid):
    try:
        await bot.delete_message(cid, mid)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# 1. BOSHLASH
# ═══════════════════════════════════════════════════════════

@router.message(F.text == "➕ Test Yaratish")
async def create_start(message: Message, state: FSMContext):
    await state.clear()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📁 Fayl (TXT/PDF/DOCX)", callback_data="method_file"))
    b.row(InlineKeyboardButton(text="💬 Chat orqali (matn)",  callback_data="method_text"))
    b.row(InlineKeyboardButton(text="📊 QuizBot forward",     callback_data="method_poll"))
    b.row(InlineKeyboardButton(text="❌ Bekor",               callback_data="cancel_create"))
    await message.answer(
        "<b>➕ TEST YARATISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📁 <b>Fayl yuklash</b> — TXT, PDF yoki DOCX\n"
        "   Yaratilgan test ▶️ Inline va 📊 Poll\n"
        "   ikki rejimda ishlaydi!\n\n"
        "📊 <b>QuizBotdan forward</b> — @QuizBot savollarini\n"
        "   uzating. TXT yuklab olish + Poll rejimi!\n\n"
        "<i>💡 Namunani ko'rish uchun turni tanlang</i>",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.choose_method)


# ═══════════════════════════════════════════════════════════
# 2. FAYL YUKLASH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "method_text", CreateTest.choose_method)
async def method_text(callback: CallbackQuery, state: FSMContext):
    """Chat orqali matn — ko'p xabar bo'lsa ham hammasi yig'iladi"""
    await callback.answer()
    example = (
        "1. O'zbekiston poytaxti?\n"
        "===A) Toshkent\n"
        "B) Samarqand\n"
        "C) Buxoro\n\n"
        "2. Pi soni?\n"
        "A) 2.14\n"
        "===B) 3.14\n"
        "C) 4.14"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Tayyor (parse qilish)", callback_data="finish_text"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="method_file"))
    b.row(InlineKeyboardButton(text="❌ Bekor",  callback_data="cancel_create"))
    await callback.message.edit_text(
        "<b>💬 MATN ORQALI YUKLASH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Savollarni <b>ketma-ket yuboring</b> (ko'p xabar bo'lsa ham yig'ib oladi)\n\n"
        f"<code>{example}</code>\n\n"
        "<i>💡 To'g'ri javob oldiga <b>===</b> qo'ying\n"
        "Hammasi yuborgach — <b>✅ Tayyor</b> bosing</i>",
        reply_markup=b.as_markup()
    )
    # Matn bufferini tozalash + instruktsia xabarini progress id sifatida saqlash
    await state.update_data(
        text_buffer=[], text_msg_ids=[],
        text_progress_id=callback.message.message_id
    )
    await state.set_state(CreateTest.upload_file)


@router.message(F.text, CreateTest.upload_file)
async def upload_text(message: Message, state: FSMContext):
    """Kelgan matn xabarlarini bufferga yig'ish — debounce bilan"""
    text = message.text.strip()
    if len(text) < 3:
        return

    d       = await state.get_data()
    buf     = d.get("text_buffer", [])
    msg_ids = d.get("text_msg_ids", [])
    buf.append(text)
    msg_ids.append(message.message_id)
    await state.update_data(text_buffer=buf, text_msg_ids=msg_ids)

    # Foydalanuvchi xabarini darhol o'chirish
    await _del(message.bot, message.chat.id, message.message_id)

    # Debounce: eski taskni bekor qilib, yangi 0.8s task
    uid      = message.from_user.id
    old_task = _text_debounce.pop(uid, None)
    if old_task:
        old_task.cancel()
    task = asyncio.create_task(
        _flush_texts(message.bot, message.chat.id, uid, state)
    )
    _text_debounce[uid] = task


# {uid: asyncio.Task} — matn debounce
_text_debounce: dict = {}

async def _flush_texts(bot, cid, uid, state):
    """0.8s kutib — eski progress o'chirib, pastga yangi yuboradi"""
    try:
        await asyncio.sleep(0.8)
        d   = await state.get_data()
        buf = d.get("text_buffer", [])
        if not buf:
            return
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="✅ Tayyor (parse qilish)", callback_data="finish_text"))
        b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_create"))
        prog_text = (
            f"📥 <b>{len(buf)} ta xabar qabul qilindi</b>\n\n"
            f"<i>Hammasi yuborgach — ✅ Tayyor bosing</i>"
        )
        # Eski progress xabarini o'chirish
        old_pid = d.get("text_progress_id")
        if old_pid:
            await _del(bot, cid, old_pid)
        # Pastga yangi yuborish
        msg = await bot.send_message(cid, prog_text, reply_markup=b.as_markup())
        await state.update_data(text_progress_id=msg.message_id)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"flush_texts: {e}")


@router.callback_query(F.data == "finish_text", CreateTest.upload_file)
async def finish_text(callback: CallbackQuery, state: FSMContext):
    """Buffer to'plangan matnlarni birga parse qilish"""
    await callback.answer()
    d   = await state.get_data()
    buf = d.get("text_buffer", [])

    if not buf:
        return await callback.answer("❌ Hali matn yuborilmadi!", show_alert=True)

    # Hammasini birlashtirish
    full_text = "\n\n".join(buf)

    status = await callback.message.edit_text("⏳ Tahlil qilinmoqda...")
    try:
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", delete=False,
                                         suffix=".txt", encoding="utf-8") as tmp:
            tmp.write(full_text)
            tmp_path = tmp.name
        questions = parse_file(tmp_path)
        os.remove(tmp_path)

        if not questions:
            return await status.edit_text(
                "❌ <b>Savollar topilmadi!</b>\n\n"
                "To'g'ri javob oldiga <b>===</b> qo'ying:\n"
                "<code>===A) To'g'ri javob</code>"
            )

        await state.update_data(
            questions=questions,
            text_buffer=[],
            text_msg_ids=[],
            upload_status_id=status.message_id
        )
        b_pt = InlineKeyboardBuilder()
        for s in POLL_TIMES:
            b_pt.add(InlineKeyboardButton(text=f"⏱ {s}s", callback_data=f"ptime_{s}"))
        b_pt.adjust(3)
        b_pt.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data="ptime_0"))
        await status.edit_text(
            f"<b>✅ {len(questions)} TA SAVOL TOPILDI!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<i>{len(buf)} ta xabardan yig'ildi</i>\n\n"
            f"⏱ <b>Har bir savol uchun necha soniya?</b>",
            reply_markup=b_pt.as_markup()
        )
        await state.set_state(CreateTest.set_poll_time)
    except Exception as e:
        log.error(f"Text parse: {e}")
        await status.edit_text("❌ Matnni o'qishda xatolik. Formatni tekshiring.")


@router.callback_query(F.data == "method_file", CreateTest.choose_method)
async def method_file(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    b = InlineKeyboardBuilder()
    for key, (_, type_name, _) in SAMPLE_TYPES.items():
        b.add(InlineKeyboardButton(text=type_name, callback_data=f"sample_{key}"))
    b.adjust(2)
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_create"))
    await callback.message.edit_text(
        "<b>📁 TEST TURINI TANLANG</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Turni bosing → namuna ko'rasiz\n"
        "Shu formatda fayl yuborasiz:\n\n"
        "<i>💡 Yaratilgan test ▶️ Inline va 📊 Poll\n"
        "ikki rejimda ishlaydi!</i>",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.upload_file)


@router.callback_query(F.data.startswith("sample_"), CreateTest.upload_file)
async def send_sample(callback: CallbackQuery):
    await callback.answer()
    key = callback.data[7:]
    fname, type_name, mono_text = SAMPLE_TYPES.get(key, SAMPLE_TYPES["mcq"])
    fpath = os.path.join(SAMPLES_DIR, fname)

    if os.path.exists(fpath):
        await callback.message.answer_document(
            FSInputFile(fpath, filename=fname),
            caption=f"📄 <b>{type_name}</b> — namuna fayli"
        )

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Boshqa tur",  callback_data="method_file"))
    b.row(InlineKeyboardButton(text="❌ Bekor",        callback_data="cancel_create"))
    await callback.message.edit_text(
        f"<b>📄 {type_name.upper()} FORMATI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Namuna:\n\n"
        f"<code>{mono_text}</code>\n\n"
        f"⏳ <b>Faylingizni yuboring...</b>",
        reply_markup=b.as_markup()
    )


@router.message(F.document, CreateTest.upload_file)
async def upload_file(message: Message, state: FSMContext):
    doc = message.document
    if not doc.file_name.lower().endswith((".txt", ".pdf", ".docx", ".doc")):
        return await message.answer("❌ Faqat TXT, PDF yoki DOCX fayllar qabul qilinadi!")

    status = await message.answer("⏳ Fayl tahlil qilinmoqda...")
    try:
        file   = await message.bot.get_file(doc.file_id)
        suffix = os.path.splitext(doc.file_name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            await message.bot.download_file(file.file_path, tmp.name)
            tmp_path = tmp.name

        questions = parse_file(tmp_path)
        os.remove(tmp_path)
        await _del(message.bot, message.chat.id, message.message_id)

        if not questions:
            return await status.edit_text(
                "❌ <b>Savollar topilmadi!</b>\n\n"
                "Namuna formatiga qarang va to'g'ri yozing.\n"
                "Namunani ko'rish uchun turni qaytadan tanlang."
            )

        await state.update_data(questions=questions)
        b_pt = InlineKeyboardBuilder()
        for s in POLL_TIMES:
            b_pt.add(InlineKeyboardButton(text=f"⏱ {s}s", callback_data=f"ptime_{s}"))
        b_pt.adjust(3)
        b_pt.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data="ptime_0"))
        await status.edit_text(
            f"<b>✅ {len(questions)} TA SAVOL TOPILDI!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏱ <b>Har bir savol uchun necha soniya?</b>",
            reply_markup=b_pt.as_markup()
        )
        await state.set_state(CreateTest.set_poll_time)

    except Exception as e:
        log.error(f"Fayl yuklashda xato: {e}")
        await status.edit_text(
            "❌ Faylni o'qishda xatolik yuz berdi.\n"
            "Boshqa format yoki faylni sinab ko'ring."
        )


# ═══════════════════════════════════════════════════════════
# 3. QUIZBOT FORWARD
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "method_poll", CreateTest.choose_method)
async def method_poll(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(questions=[], poll_time=30)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Tayyor", callback_data="finish_polls"))
    b.row(InlineKeyboardButton(text="❌ Bekor",  callback_data="cancel_create"))
    await callback.message.edit_text(
        "<b>📊 QUIZBOT FORWARD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ @QuizBot ga o'ting\n"
        "2️⃣ Quiz savollarini bu yerga forward qiling\n"
        "3️⃣ Hammasi yuborilgach — <b>✅ Tayyor</b> bosing\n\n"
        "<i>💡 Faqat 'Viktorina' (Quiz) turi qabul qilinadi!</i>",
        reply_markup=b.as_markup()
    )
    # progress_msg_id = None — birinchi poll kelganda yangi progress xabar chiqadi
    await state.update_data(questions=[], progress_msg_id=None)
    await state.set_state(CreateTest.waiting_polls)


# {uid: asyncio.Task} — debounce tasklari
_poll_debounce: dict = {}

async def _flush_polls(bot, cid, uid, state):
    """0.8s kutib — eski progress o'chirib, pastga yangi yuboradi"""
    try:
        await asyncio.sleep(0.8)
        d   = await state.get_data()
        qs  = d.get("questions", [])
        if not qs:
            return
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="✅ Tayyor",  callback_data="finish_polls"))
        b.row(InlineKeyboardButton(text="❌ Bekor",   callback_data="cancel_create"))
        prog_text = (
            f"📥 <b>Qabul qilindi: {len(qs)} ta savol</b>\n\n"
            f"<i>Davom ettiring yoki tayyor bo'lsa bosing:</i>"
        )
        # Eski progress xabarini o'chirish
        old_pid = d.get("progress_msg_id")
        if old_pid:
            await _del(bot, cid, old_pid)
        # Pastga yangi yuborish
        prog = await bot.send_message(cid, prog_text, reply_markup=b.as_markup())
        await state.update_data(progress_msg_id=prog.message_id)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"flush_polls: {e}")


@router.message(F.poll, CreateTest.waiting_polls)
async def catch_poll(message: Message, state: FSMContext):
    if message.poll.type != "quiz":
        await _del(message.bot, message.chat.id, message.message_id)
        return await message.answer("❌ Faqat <b>Viktorina (Quiz)</b> turi qabul qilinadi!")

    import re as _re
    p    = message.poll
    lts  = ["A)", "B)", "C)", "D)", "E)", "F)"]
    opts = [f"{lts[i]} {op.text}" for i, op in enumerate(p.options)]
    clean_q = _re.sub(r"^\[\d+/\d+\]\s*", "", p.question).strip()

    # Poll xabarini darhol o'chirish
    await _del(message.bot, message.chat.id, message.message_id)

    # Savolni RAMga qo'shamiz
    d  = await state.get_data()
    qs = d.get("questions", [])
    qs.append({
        "type":        "multiple_choice",
        "question":    clean_q,
        "options":     opts,
        "correct":     opts[p.correct_option_id],
        "explanation": p.explanation or "",
        "points":      1
    })
    await state.update_data(questions=qs)

    # Debounce: eski taskni bekor qilib, yangi 0.8s task ishlatamiz
    uid = message.from_user.id
    old_task = _poll_debounce.pop(uid, None)
    if old_task:
        old_task.cancel()
    task = asyncio.create_task(
        _flush_polls(message.bot, message.chat.id, uid, state)
    )
    _poll_debounce[uid] = task


@router.callback_query(F.data == "finish_polls", CreateTest.waiting_polls)
async def finish_polls(callback: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if not d.get("questions"):
        return await callback.answer("❌ Hali savol yo'q!", show_alert=True)
    await callback.answer()
    b = InlineKeyboardBuilder()
    for s in POLL_TIMES:
        b.add(InlineKeyboardButton(text=f"⏱ {s}s", callback_data=f"ptime_{s}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Vaqtsiz", callback_data="ptime_0"))
    b.row(InlineKeyboardButton(text="❌ Bekor",   callback_data="cancel_create"))
    await callback.message.edit_text(
        f"<b>⏱ POLL VAQTI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ {len(d['questions'])} ta savol qabul qilindi!\n\n"
        f"Har bir savol uchun necha soniya?",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.set_poll_time)


@router.callback_query(F.data.startswith("ptime_"))
async def set_pt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    pt  = int(callback.data[6:])
    await state.update_data(poll_time=pt)
    ptt = f"{pt} soniya/savol" if pt else "Vaqtsiz"
    await callback.message.edit_text(
        f"⏱ <b>Savol vaqti: {ptt}</b>\n\n"
        f"📁 Qaysi fanga tegishli?",
        reply_markup=subject_kb(extra_subjects=_get_user_subjects(callback.from_user.id))
    )
    await state.set_state(CreateTest.set_subject)


# ═══════════════════════════════════════════════════════════
# 4. FAN, MAVZU, SOZLAMALAR
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("subj_"), CreateTest.set_subject)
async def set_subj(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    s = callback.data[5:]
    if s == "other":
        return await callback.message.edit_text(
            "✏️ <b>Fan nomini yozing:</b>\n"
            "<i>Masalan: Fizika, Ona tili, Tarix...</i>"
        )
    await state.update_data(category=s)
    await callback.message.edit_text(
        f"📁 Fan: <b>{s}</b>\n\n"
        f"<b>🏷 Test nomini yozing:</b>"
    )
    await state.set_state(CreateTest.set_title)


@router.message(F.text, CreateTest.set_subject)
async def subj_text(message: Message, state: FSMContext):
    subj = message.text.strip()
    d    = await state.get_data()
    await _del(message.bot, message.chat.id, message.message_id)
    await _del(message.bot, message.chat.id, d.get("prev_bot_msg_id"))
    from utils.ram_cache import add_user_custom_subject
    add_user_custom_subject(message.from_user.id, subj)
    await state.update_data(category=subj)
    msg = await message.answer("<b>🏷 Test nomini yozing:</b>")
    await state.update_data(prev_bot_msg_id=msg.message_id)
    await state.set_state(CreateTest.set_title)


@router.message(F.text, CreateTest.set_title)
async def set_title(message: Message, state: FSMContext):
    title = message.text.strip()
    d     = await state.get_data()
    await _del(message.bot, message.chat.id, message.message_id)
    await _del(message.bot, message.chat.id, d.get("prev_bot_msg_id"))
    await state.update_data(title=title)
    msg = await message.answer(
        f"<b>📊 QIYINLIK DARAJASI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Mavzu: <b>{title}</b>",
        reply_markup=difficulty_kb()
    )
    await state.update_data(prev_bot_msg_id=msg.message_id)
    await state.set_state(CreateTest.set_difficulty)


@router.callback_query(F.data.startswith("diff_"), CreateTest.set_difficulty)
async def set_diff(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(difficulty=callback.data[5:])
    b = InlineKeyboardBuilder()
    for m in [15, 20, 30, 45, 60, 90, 120]:
        b.add(InlineKeyboardButton(text=f"⏱ {m}daq", callback_data=f"tlim_{m}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data="tlim_0"))
    await callback.message.edit_text(
        "<b>⏱ UMUMIY VAQT LIMITI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Test uchun umumiy necha daqiqa?",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.set_time_limit)


@router.callback_query(F.data.startswith("tlim_"), CreateTest.set_time_limit)
async def set_tlim(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(time_limit=int(callback.data[5:]))
    b = InlineKeyboardBuilder()
    for p in [50, 60, 70, 80, 90, 100]:
        b.add(InlineKeyboardButton(text=f"{p}%", callback_data=f"pass_{p}"))
    b.adjust(3)
    await callback.message.edit_text(
        "<b>🎯 O'TISH FOIZI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Testdan o'tish uchun minimum foiz?",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.set_passing)


@router.callback_query(F.data.startswith("pass_"), CreateTest.set_passing)
async def set_pass(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(passing_score=int(callback.data[5:]))
    b = InlineKeyboardBuilder()
    for a in [1, 2, 3, 5, 10]:
        b.add(InlineKeyboardButton(text=f"🔄 {a}x", callback_data=f"att_{a}"))
    b.adjust(3)
    b.row(InlineKeyboardButton(text="♾ Cheksiz", callback_data="att_0"))
    await callback.message.edit_text(
        "<b>🔄 URINISHLAR SONI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Har foydalanuvchi necha marta ishlashi mumkin?",
        reply_markup=b.as_markup()
    )
    await state.set_state(CreateTest.set_attempts)


@router.callback_query(F.data.startswith("att_"), CreateTest.set_attempts)
async def set_att(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(max_attempts=int(callback.data[4:]))
    await callback.message.edit_text(
        "<b>🔒 TEST MAXFIYLIGI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌍 <b>Ommaviy</b> — hamma ko'ra oladi\n"
        "🔗 <b>Ssilka</b> — faqat havola orqali\n"
        "🔒 <b>Shaxsiy</b> — faqat siz",
        reply_markup=visibility_kb()
    )
    await state.set_state(CreateTest.set_visibility)


# ═══════════════════════════════════════════════════════════
# 5. SAQLASH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("vis_"), CreateTest.set_visibility)
async def save_test(callback: CallbackQuery, state: FSMContext):
    await callback.answer("⏳")
    d = await state.get_data()
    td = {
        "title":         d.get("title", "Nomsiz"),
        "category":      d.get("category", "Boshqa"),
        "difficulty":    d.get("difficulty", "medium"),
        "visibility":    callback.data[4:],
        "time_limit":    d.get("time_limit", 0),
        "poll_time":     d.get("poll_time", 30),
        "passing_score": d.get("passing_score", 60),
        "max_attempts":  d.get("max_attempts", 0),
        "questions":     d.get("questions", []),
    }
    tid  = await create_test(callback.from_user.id, td)
    bu   = (await callback.bot.me()).username
    link = f"https://t.me/{bu}?start={tid}"
    pt_t = f"{td['poll_time']}s/savol" if td.get("poll_time") else "Vaqtsiz"
    tl_t = f"{td['time_limit']} daqiqa" if td.get("time_limit") else "Cheksiz"
    diff_map = {
        "easy": "🟢 Oson", "medium": "🟡 O'rtacha",
        "hard": "🔴 Qiyin", "expert": "⚡ Ekspert"
    }
    diff = diff_map.get(td["difficulty"], "")
    vis_map = {"public": "🌍 Ommaviy", "link": "🔗 Ssilka", "private": "🔒 Shaxsiy"}
    vis  = vis_map.get(td["visibility"], "")

    # Progress xabarlar chatda qoladi (foydalanuvchi ko'rishi uchun)
    # Faqat joriy (callback) xabar test ma'lumoti bilan almashtiriladi
    await state.clear()

    # Kalit javoblar matni
    qs   = td["questions"]
    keys = (
        f"🔑 <b>JAVOBLAR KALITI</b> — <code>{tid}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    for i, q in enumerate(qs, 1):
        corr = q.get("correct", "?")
        keys += f"<b>{i}.</b> {corr}\n"

    # Test haqida to'liq ma'lumot + kalit + tugmalar
    info_text = (
        "🎉 <b>TEST MUVAFFAQIYATLI YARATILDI!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Kod: <code>{tid}</code>\n"
        f"🔗 Ssilka: <code>{link}</code>\n\n"
        f"📝 Mavzu: <b>{td['title']}</b>\n"
        f"📁 Fan: {td['category']}\n"
        f"📊 Qiyinlik: {diff}\n"
        f"🔒 Ko'rinish: {vis}\n"
        f"📋 Savollar: <b>{len(qs)} ta</b>\n"
        f"⏱ Umumiy vaqt: {tl_t}\n"
        f"⏱ Poll vaqti: {pt_t}\n"
        f"🎯 O'tish foizi: <b>{td['passing_score']}%</b>\n\n"
        "👇 <b>Boshlash usulini tanlang:</b>"
    )

    try:
        await callback.message.edit_text(info_text, reply_markup=test_created_kb(tid, bu))
    except Exception:
        await callback.message.answer(info_text, reply_markup=test_created_kb(tid, bu))

    # Kalitni alohida xabar sifatida yuborish
    if len(keys) <= 4000:
        await callback.message.answer(keys)


@router.callback_query(F.data == "cancel_create")
async def cancel_create(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    d   = await state.get_data()
    cid = callback.message.chat.id
    await state.clear()
    # Progress xabar chatda qolsin, faqat callback xabarni o'chirish
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.bot.send_message(
        callback.from_user.id,
        "❌ Bekor qilindi.",
        reply_markup=main_kb(callback.from_user.id)
    )
