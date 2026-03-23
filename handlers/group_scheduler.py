"""
🗓 GROUP SCHEDULER — Guruh uchun avtomatik test rejalashtirish
==============================================================

BUYRUQLAR:
  /set_tests          — testlar ro'yxatini belgilash (shu guruh uchun)
  /start_sets poll    — ovoz + poll rejimida avto-ketma-ket testlar
  /start_sets inline  — ovoz + inline rejimida avto-ketma-ket testlar
  /stop_sets          — to'liq to'xtatish
  /quiz_stop          — faqat joriy testni to'xtatadi, keyin davom etadi

ISHLASH PRINSIPI:
  1. Admin /set_tests deb testlar ro'yxatini belgilaydi
  2. /start_sets poll bosadi
  3. Bot ovoz ochadi: "Qaysi testni boshlaymiz?"
     - 30 sekund ovoz
     - Ko'p ovoz to'plagan test boshlanadi
     - Hech kim ovoz bermasa → random tanlanadi (yechilganlar qaytmaydi)
  4. Test tugaydi → natija e'lon qilinadi
  5. Bot keyingi ovoz ochadi
  6. Ro'yxatdagi barcha testlar tugagach → "Barcha testlar yakunlandi!"

TEST QO'SHISH USULLARI:
  a) /set_tests → keyin test kodlarini yozish:
     AB12CD34, XY56ZW78
  b) Inline xabarni forward qilish → bot o'zi ID larni ajratib oladi
  c) Bitta kod: AB12CD34
"""

import asyncio, logging, random, re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, Poll
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from utils.ram_cache import get_test_meta, get_tests_meta

log    = logging.getLogger(__name__)
router = Router()

# ── Guruh scheduler sessiyalari ────────────────────────────────
# {chat_id: {
#   "tests":       [tid1, tid2, ...],   ← belgilangan testlar
#   "remaining":   [tid1, tid2, ...],   ← hali yechilmagan testlar
#   "done":        [tid1, ...],         ← yechilgan testlar
#   "mode":        "poll" | "inline",
#   "active":      True/False,
#   "host_id":     uid,
#   "vote_msg_id": msg_id,              ← joriy ovoz xabari
#   "task":        asyncio.Task,
#   "current_tid": tid,                 ← hozir ketayotgan test
# }}
_schedules: dict = {}

VOTE_SECONDS = 30   # ovoz vaqti


# ── Yordamchi funksiyalar ──────────────────────────────────────

def _get_schedule(chat_id):
    return _schedules.get(chat_id)

def _extract_test_ids(text: str) -> list:
    """Matndan test ID larini ajratib olish (6-10 belgili katta harf+raqam)."""
    return list(dict.fromkeys(re.findall(r'\b[A-Z0-9]{6,10}\b', text.upper())))

async def _is_admin(bot, chat_id, uid):
    try:
        m = await bot.get_chat_member(chat_id, uid)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


# ══ /set_tests — testlar ro'yxatini belgilash ══════════════════

@router.message(Command("set_tests"))
async def cmd_set_tests(message: Message):
    """Guruh uchun testlar ro'yxatini ko'rsatish va boshqarish."""
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Bu buyruq faqat guruhlarda ishlaydi!")

    if not await _is_admin(message.bot, chat_id, uid):
        return await message.answer("⚠️ Faqat guruh adminlari testlarni belgilashi mumkin!")

    # Buyruq bilan birga test ID lar berilganmi?
    args = message.text.split()[1:]
    tids = _extract_test_ids(" ".join(args)) if args else []

    if tids:
        await _save_and_confirm_tests(message, chat_id, tids)
    else:
        await _show_tests_list(message, chat_id)


@router.message(F.text & F.chat.type.in_({"group", "supergroup"}))
async def handle_test_ids_input(message: Message):
    """Faqat '➕ Test qo'shish' bosilgandan keyin kod qabul qilish."""
    chat_id = message.chat.id
    uid     = message.from_user.id
    sched   = _schedules.get(chat_id, {})

    # Faqat waiting_input holatida va faqat shu admin uchun
    if sched.get("waiting_input") != uid:
        return

    tids = _extract_test_ids(message.text or "")
    if not tids:
        await message.answer(
            "❌ Test ID topilmadi.\n"
            "6-10 belgili kod kiriting, masalan: <code>AB12CD34</code>"
        )
        return

    _schedules[chat_id].pop("waiting_input", None)
    await _save_and_confirm_tests(message, chat_id, tids)


async def _save_and_confirm_tests(message, chat_id, tids):
    """Testlarni tekshirib, interaktiv tasdiqlash."""
    valid   = []
    invalid = []
    for tid in tids:
        meta = get_test_meta(tid)
        if meta and meta.get("is_active", True):
            if tid not in valid:   # dublikat yo'q
                valid.append(tid)
        else:
            invalid.append(tid)

    if not valid:
        return await message.answer(
            "❌ <b>Hech qanday to'g'ri test topilmadi!</b>\n\n"
            "Test kodlari 6-10 belgili bo'lishi va botda mavjud bo'lishi kerak.\n"
            "Masalan: <code>AB12CD34</code>"
        )

    # Mavjud ro'yxatga qo'shish
    if chat_id not in _schedules:
        _schedules[chat_id] = {}
    current = _schedules[chat_id].get("tests", [])
    # Dublikat qo'shmaslik
    for tid in valid:
        if tid not in current:
            current.append(tid)
    _schedules[chat_id]["tests"] = current

    await _show_tests_list(message, chat_id, newly_added=valid, invalid=invalid)


async def _show_tests_list(message, chat_id, newly_added=None, invalid=None, edit=False):
    """Joriy testlar ro'yxatini interaktiv ko'rsatish."""
    sched = _schedules.get(chat_id, {})
    tests = sched.get("tests", [])

    if not tests:
        text = (
            "📋 <b>TESTLAR RO'YXATI BO'SH</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Test kodlarini yuboring yoki inline xabarni forward qiling."
        )
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="❌ Yopish", callback_data=f"sched_close_{chat_id}"))
        try:
            if edit: await message.edit_text(text, reply_markup=b.as_markup())
            else:    await message.answer(text, reply_markup=b.as_markup())
        except TelegramBadRequest:
            await message.answer(text, reply_markup=b.as_markup())
        return

    text = (
        "📋 <b>TESTLAR RO'YXATI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Jami: <b>{len(tests)} ta test</b>\n\n"
    )
    for i, tid in enumerate(tests, 1):
        meta = get_test_meta(tid) or {}
        name = meta.get("title", tid)[:25]
        qc   = meta.get("question_count", 0)
        text += f"{i}. <b>{name}</b> — {qc} savol\n"
        text += f"   <code>{tid}</code>\n\n"

    if newly_added:
        text += f"✅ Yangi qo'shildi: {len(newly_added)} ta\n"
    if invalid:
        text += f"⚠️ Topilmadi: {', '.join(f'<code>{t}</code>' for t in invalid)}\n"

    text += "\n━━━━━━━━━━━━━━━━━━━━━━━━"

    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Poll boshlash",   callback_data=f"sched_start_poll_{chat_id}"),
        InlineKeyboardButton(text="⚡ Inline boshlash", callback_data=f"sched_start_inline_{chat_id}"),
    )
    b.row(
        InlineKeyboardButton(text="➕ Test qo'shish", callback_data=f"sched_add_{chat_id}"),
        InlineKeyboardButton(text="🗑 Tozalash",       callback_data=f"sched_clear_{chat_id}"),
    )
    b.row(
        InlineKeyboardButton(text="✅ Tayyor — Boshlash", callback_data=f"sched_ready_{chat_id}"),
        InlineKeyboardButton(text="❌ Yopish",             callback_data=f"sched_close_{chat_id}"),
    )
    # Har bir testni o'chirish tugmalari
    for tid in tests:
        meta = get_test_meta(tid) or {}
        name = meta.get("title", tid)[:20]
        b.row(InlineKeyboardButton(
            text=f"➖ {name}",
            callback_data=f"sched_del_{chat_id}_{tid}"
        ))
    try:
        if edit: await message.edit_text(text, reply_markup=b.as_markup())
        else:    await message.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await message.answer(text, reply_markup=b.as_markup())


# ══ /start_sets — ketma-ket testlarni boshlash ═════════════════

@router.message(Command("start_sets"))
async def cmd_start_sets(message: Message):
    """
    /start_sets poll   — ovoz + poll rejimida boshlash
    /start_sets inline — ovoz + inline rejimida boshlash
    /start_sets        — rejimni so'raydi
    """
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Bu buyruq faqat guruhlarda ishlaydi!")

    if not await _is_admin(message.bot, chat_id, uid):
        return await message.answer("⚠️ Faqat guruh adminlari boshlashi mumkin!")

    sched = _schedules.get(chat_id, {})
    if not sched.get("tests"):
        return await message.answer(
            "❌ <b>Testlar ro'yxati belgilanmagan!</b>\n\n"
            "Avval <code>/set_tests</code> buyrug'i bilan testlarni belgilang."
        )

    if sched.get("active"):
        return await message.answer(
            "⚠️ <b>Jarayon allaqachon boshlangan!</b>\n\n"
            "To'xtatish uchun: <code>/stop_sets</code>"
        )

    args = message.text.split()
    mode = args[1].lower() if len(args) > 1 and args[1].lower() in ("poll", "inline") else None

    await _start_schedule(message.bot, chat_id, uid, "poll", message)


@router.callback_query(F.data.startswith("sched_ready_"))
async def sched_ready_cb(callback: CallbackQuery):
    """✅ Tayyor — menyu yopiladi, ovoz boshlanadi."""
    await callback.answer()
    parts   = callback.data.split("_")
    chat_id = int(parts[2])
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    sched = _schedules.get(chat_id, {})
    if not sched.get("tests"):
        return await callback.answer("❌ Testlar ro'yxati bo'sh!", show_alert=True)

    if sched.get("active"):
        return await callback.answer("⚠️ Jarayon allaqachon boshlangan!", show_alert=True)

    # Menyuni o'chirish
    try: await callback.message.delete()
    except: pass

    # Rejimni so'rash — poll yoki inline
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="📊 Poll rejimi",   callback_data=f"sched_start_poll_{chat_id}"),
        InlineKeyboardButton(text="⚡ Inline rejimi", callback_data=f"sched_start_inline_{chat_id}"),
    )
    n = len(sched.get("tests", []))
    await callback.bot.send_message(
        chat_id,
        "\U0001F3AF <b>REJIMNI TANLANG</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"\U0001F4CB Testlar soni: <b>{n} ta</b>\n\n"
        "\U0001F4CA <b>Poll</b> \u2014 Telegram native quiz\n"
        "\u26A1 <b>Inline</b> \u2014 Har savoldan keyin javob ko'rsatiladi",
        reply_markup=b.as_markup()
    )


@router.callback_query(F.data.startswith("sched_add_"))
async def sched_add_cb(callback: CallbackQuery):
    """➕ Test qo'shish tugmasi — admin test kodi yuborishini kutadi."""
    await callback.answer()
    parts   = callback.data.split("_")
    chat_id = int(parts[2])
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    if chat_id not in _schedules:
        _schedules[chat_id] = {}
    _schedules[chat_id]["waiting_input"] = uid

    await callback.message.answer(
        "➕ <b>TEST QO'SHISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Test kodini yuboring:\n"
        "<code>AB12CD34</code>\n\n"
        "Bir nechta kod:\n"
        "<code>AB12CD34, XY56ZW78</code>\n\n"
        "<i>Inline xabarni forward qilsangiz ham bo'ladi</i>"
    )


@router.callback_query(F.data.startswith("sched_view_"))
async def sched_view_cb(callback: CallbackQuery):
    """Ro'yxatni ko'rish."""
    await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    await _show_tests_list(callback.message, chat_id, edit=False)


@router.callback_query(F.data.startswith("sched_del_"))
async def sched_del_cb(callback: CallbackQuery):
    """Ro'yxatdan bitta testni o'chirish."""
    await callback.answer()
    parts   = callback.data.split("_")
    chat_id = int(parts[2])
    tid     = parts[3]
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    sched = _schedules.get(chat_id, {})
    tests = sched.get("tests", [])
    if tid in tests:
        tests.remove(tid)
        sched["tests"] = tests

    await _show_tests_list(callback.message, chat_id, edit=True)


@router.callback_query(F.data.startswith("sched_clear_"))
async def sched_clear_cb(callback: CallbackQuery):
    """Ro'yxatni to'liq tozalash."""
    await callback.answer()
    parts   = callback.data.split("_")
    chat_id = int(parts[2])
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    if chat_id in _schedules:
        _schedules[chat_id]["tests"] = []

    await _show_tests_list(callback.message, chat_id, edit=True)


@router.callback_query(F.data.startswith("sched_close_"))
async def sched_close_cb(callback: CallbackQuery):
    """Xabarni yopish."""
    await callback.answer()
    try: await callback.message.delete()
    except: pass


@router.callback_query(F.data.startswith("sched_start_"))
async def sched_start_cb(callback: CallbackQuery):
    await callback.answer()
    parts   = callback.data.split("_")
    mode    = parts[2]   # poll yoki inline
    chat_id = int(parts[3])
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    await _start_schedule(callback.bot, chat_id, uid, mode, callback.message)


async def _start_schedule(bot, chat_id, uid, mode, reply_msg=None):
    """Scheduler ni ishga tushirish."""
    sched = _schedules.get(chat_id, {})
    tests = sched.get("tests", [])

    if not tests:
        if reply_msg:
            await reply_msg.answer("❌ Testlar ro'yxati yo'q!")
        return

    _schedules[chat_id] = {
        "tests":       tests[:],
        "remaining":   tests[:],
        "done":        [],
        "mode":        mode,
        "active":      True,
        "host_id":     uid,
        "vote_msg_id": None,
        "task":        None,
        "current_tid": None,
    }

    mode_txt = "📊 Quiz Poll" if mode == "poll" else "⚡ Inline test"
    await bot.send_message(
        chat_id,
        f"🚀 <b>AVTOMATIK TEST REJIMI BOSHLANDI!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 Rejim: <b>{mode_txt}</b>\n"
        f"📋 Testlar soni: <b>{len(tests)} ta</b>\n\n"
        f"📣 Har test boshlanishidan oldin <b>{VOTE_SECONDS} soniya</b> ovoz beriladi.\n"
        f"Ko'p ovoz to'plagan test boshlanadi!\n\n"
        f"⏹ To'xtatish: <code>/stop_sets</code>\n"
        f"⏸ Joriy testni to'xtatish: <code>/quiz_stop</code>",
    )

    task = asyncio.create_task(_scheduler_loop(bot, chat_id))
    _schedules[chat_id]["task"] = task


async def _scheduler_loop(bot, chat_id):
    """Asosiy scheduler loop — ovoz → test → ovoz → ..."""
    try:
        while True:
            sched = _schedules.get(chat_id)
            if not sched or not sched.get("active"):
                break

            remaining = sched.get("remaining", [])
            if not remaining:
                # Barcha testlar yakunlandi — qayta boshlash
                done  = sched.get("done", [])
                tests = sched.get("tests", [])
                await bot.send_message(
                    chat_id,
                    f"🔄 <b>BARCHA TESTLAR YAKUNLANDI!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"✅ Jami {len(done)} ta test o'tkazildi.\n"
                    f"♾️ Ro'yxat qaytadan boshlanmoqda...\n\n"
                    f"⏹ To'xtatish uchun: <code>/stop_sets</code>"
                )
                # Ro'yxatni qayta to'ldirish
                sched["remaining"] = tests[:]
                sched["done"]      = []
                await asyncio.sleep(3)
                continue   # Loopni qayta boshlash

            # Ovoz ochish
            tid = await _run_vote(bot, chat_id, remaining)
            if tid is None:
                break   # stop_sets chaqirilgan

            # Testni boshlash
            sched["current_tid"] = tid
            sched["remaining"]   = [t for t in remaining if t != tid]
            sched["done"].append(tid)

            meta = get_test_meta(tid) or {}
            mode = sched.get("mode", "poll")
            await bot.send_message(
                chat_id,
                f"🎯 <b>{meta.get('title', tid)}</b> testi boshlanmoqda...\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📋 {meta.get('question_count', 0)} ta savol | "
                f"⏱ {meta.get('poll_time', 30)}s/savol"
            )
            await asyncio.sleep(2)

            # Testni ishga tushirish
            from handlers.group import _start_group_test
            await _start_group_test(bot, chat_id, sched["host_id"], tid, mode)

            # Test tugashini kutish
            await _wait_for_test(bot, chat_id)

            sched["current_tid"] = None

            # Qisqa tanaffus
            if sched.get("active") and sched.get("remaining"):
                await bot.send_message(
                    chat_id,
                    f"⏳ <b>Keyingi test {VOTE_SECONDS} soniyadan keyin...</b>\n"
                    f"📋 Qolgan testlar: <b>{len(sched['remaining'])} ta</b>"
                )
                await asyncio.sleep(5)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"Scheduler loop xato: {e}")
        import traceback; traceback.print_exc()


async def _run_vote(bot, chat_id, remaining: list) -> str | None:
    """
    Ovoz ochish va natijani qaytarish.
    - Ko'p ovoz to'plagan test tanlanadi
    - Hech kim ovoz bermasa → random
    - /stop_sets chaqirilsa → None
    """
    sched = _schedules.get(chat_id)
    if not sched or not sched.get("active"):
        return None

    # Ovoz uchun maksimal 5 ta variant ko'rsatish
    vote_tids = remaining[:5]
    options   = []
    for tid in vote_tids:
        meta = get_test_meta(tid) or {}
        name = meta.get("title", tid)[:20]
        qc   = meta.get("question_count", 0)
        options.append(f"📝 {name} ({qc} savol)")

    try:
        poll_msg = await bot.send_poll(
            chat_id,
            question=f"🗳 Keyingi testni tanlang! ({VOTE_SECONDS}s)",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
            protect_content=True,
        )
        sched["vote_msg_id"]  = poll_msg.message_id
        sched["vote_poll_id"] = poll_msg.poll.id
        sched["vote_counts"]  = {i: 0 for i in range(len(vote_tids))}
        sched["vote_tids"]    = vote_tids
    except Exception as e:
        log.error(f"Ovoz ochishda xato: {e}")
        return random.choice(remaining)

    # VOTE_SECONDS kutamiz
    for _ in range(VOTE_SECONDS):
        await asyncio.sleep(1)
        sched = _schedules.get(chat_id)
        if not sched or not sched.get("active"):
            return None

    # Ovozni yopish
    try:
        result = await bot.stop_poll(chat_id, poll_msg.message_id)
        # Ko'p ovoz to'plagan variant
        max_votes = max((opt.voter_count for opt in result.options), default=0)
        if max_votes == 0:
            # Hech kim ovoz bermadi → random
            chosen_tid = random.choice(vote_tids)
            await bot.send_message(
                chat_id,
                f"🎲 <b>Hech kim ovoz bermadi — random tanlanadi!</b>\n\n"
                f"🎯 Tanlandi: <b>{get_test_meta(chosen_tid).get('title', chosen_tid) if get_test_meta(chosen_tid) else chosen_tid}</b>"
            )
        else:
            # Ko'p ovoz to'plagan
            best_idx  = max(range(len(result.options)), key=lambda i: result.options[i].voter_count)
            chosen_tid = vote_tids[best_idx]
            meta       = get_test_meta(chosen_tid) or {}
            await bot.send_message(
                chat_id,
                f"🏆 <b>Ovoz natijasi:</b>\n\n"
                f"✅ Yutdi: <b>{meta.get('title', chosen_tid)}</b>\n"
                f"🗳 Ovozlar: {result.options[best_idx].voter_count} ta"
            )
        return chosen_tid
    except Exception as e:
        log.error(f"Ovozni yopishda xato: {e}")
        return random.choice(vote_tids)


async def _wait_for_test(bot, chat_id):
    """Test tugashini kutish — guruh sessiyasi tugaguncha."""
    from handlers.group import _group_sessions, _inline_sessions
    max_wait = 3600   # maksimal 1 soat kutish

    for _ in range(max_wait):
        await asyncio.sleep(1)
        sched = _schedules.get(chat_id)
        if not sched or not sched.get("active"):
            return
        # Test tugadimi?
        if chat_id not in _group_sessions and chat_id not in _inline_sessions:
            return


# ══ /stop_sets — to'liq to'xtatish ═══════════════════════════

@router.message(Command("stop_sets"))
async def cmd_stop_sets(message: Message):
    """To'liq to'xtatish — scheduler va joriy test."""
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Bu buyruq faqat guruhlarda ishlaydi!")

    if not await _is_admin(message.bot, chat_id, uid):
        return await message.answer("⚠️ Faqat guruh adminlari to'xtatishi mumkin!")

    sched = _schedules.get(chat_id)
    if not sched or not sched.get("active"):
        return await message.answer("ℹ️ Hozir avtomatik test rejimi faol emas.")

    # Schedulerni to'xtatish
    sched["active"] = False
    task = sched.get("task")
    if task and not task.done():
        task.cancel()

    # Joriy testni ham to'xtatish
    from handlers.group import _group_sessions, _inline_sessions
    for sessions in (_group_sessions, _inline_sessions):
        if chat_id in sessions:
            t = sessions[chat_id].get("task")
            if t and not t.done():
                t.cancel()
            sessions.pop(chat_id, None)

    done  = sched.get("done", [])
    left  = sched.get("remaining", [])
    _schedules.pop(chat_id, None)

    await message.answer(
        "⏹ <b>AVTOMATIK TEST REJIMI TO'XTATILDI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ O'tkazildi: <b>{len(done)} ta test</b>\n"
        f"📋 Qoldi: <b>{len(left)} ta test</b>\n\n"
        "Qayta boshlash uchun: <code>/start_sets</code>"
    )


# ══ /quiz_stop — faqat joriy testni to'xtatish ════════════════
# Bu group.py dagi cmd_quiz_stop ga hook qo'shamiz
# Scheduler faol bo'lsa natija e'lon qilingach keyingi ovoz boshlanadi

async def on_test_finished(bot, chat_id):
    """
    group.py dan chaqiriladi — test tugagach scheduler davom etishini xabardor qiladi.
    Scheduler loop o'zi _wait_for_test orqali buni sezadi.
    """
    pass   # _wait_for_test sessiya yo'qligini sezib o'zi davom etadi


# ══ Ovoz javoblarini qayta ishlash ════════════════════════════

@router.poll_answer()
async def scheduler_vote_answer(poll_answer):
    """Ovoz javoblarini qayd etish."""
    poll_id = poll_answer.poll_id
    for chat_id, sched in _schedules.items():
        if sched.get("vote_poll_id") == poll_id:
            opt_idx = poll_answer.option_ids[0] if poll_answer.option_ids else 0
            counts  = sched.get("vote_counts", {})
            counts[opt_idx] = counts.get(opt_idx, 0) + 1
            sched["vote_counts"] = counts
            break
