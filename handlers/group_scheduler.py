"""
🗓 GROUP SCHEDULER — Guruh uchun avtomatik test rejalashtirish
==============================================================

BUYRUQLAR:
  /start_create <id1, id2, ...>  — ro'yxat yaratish va ko'rsatish
  /set_tests                     — mavjud ro'yxatni ko'rish/tahrirlash
  /start_set                     — ovoz ochib testlarni boshlash
  /stop_set                      — hammani to'xtatish
  /quiz_stop                     — joriy testni to'xtatib natija + keyingi ovoz

ISHLASH:
  1. /start_create A1B2C3D4, E5F6G7H8  → ro'yxat yaratiladi
  2. /start_set  → 30s ovoz → ko'p ovoz → test boshlanadi
  3. Test tugaydi → natija → keyingi ovoz
  4. /quiz_stop  → joriy test to'xtatiladi → natija → keyingi ovoz
  5. /stop_set   → hammasi to'xtatiladi
"""

import asyncio, logging, random, re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from utils.ram_cache import get_test_meta

log    = logging.getLogger(__name__)
router = Router()

# {chat_id: {tests, remaining, done, mode, active, host_id, task, current_tid, ...}}
_schedules: dict = {}
VOTE_SECONDS = 30


# ── Yordamchilar ──────────────────────────────────────────────

def _extract_ids(text: str) -> list:
    return list(dict.fromkeys(re.findall(r'\b[A-Z0-9]{6,10}\b', text.upper())))

async def _is_admin(bot, chat_id, uid):
    try:
        m = await bot.get_chat_member(chat_id, uid)
        return m.status in ("administrator", "creator")
    except Exception:
        return False

def _tests_list_text(chat_id, title="📋 TESTLAR RO'YXATI") -> str:
    sched = _schedules.get(chat_id, {})
    tests = sched.get("tests", [])
    if not tests:
        return f"<b>{title}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\nRo'yxat bo'sh."
    done      = sched.get("done", [])
    remaining = sched.get("remaining", [])
    text = f"<b>{title}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nJami: <b>{len(tests)} ta</b>\n\n"
    for i, tid in enumerate(tests, 1):
        meta  = get_test_meta(tid) or {}
        name  = meta.get("title", tid)[:25]
        qc    = meta.get("question_count", 0)
        if tid in done:
            icon = "✅"
        elif tid == sched.get("current_tid"):
            icon = "▶️"
        else:
            icon = "⏳"
        text += f"{icon} {i}. <b>{name}</b> ({qc} savol)\n   <code>{tid}</code>\n\n"
    return text.strip()

def _list_kb(chat_id) -> object:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Poll testlarni boshlash", callback_data=f"sch_start_poll_{chat_id}"),
    )
    b.row(
        InlineKeyboardButton(text="➕ Test qo'shish",  callback_data=f"sch_add_{chat_id}"),
        InlineKeyboardButton(text="🗑 Tozalash",        callback_data=f"sch_clear_{chat_id}"),
    )
    sched = _schedules.get(chat_id, {})
    for tid in sched.get("tests", []):
        meta = get_test_meta(tid) or {}
        name = meta.get("title", tid)[:22]
        b.row(InlineKeyboardButton(
            text=f"➖ {name}",
            callback_data=f"sch_del_{chat_id}_{tid}"
        ))
    b.row(InlineKeyboardButton(text="❌ Yopish", callback_data=f"sch_close_{chat_id}"))
    return b.as_markup()


# ══ /start_create ════════════════════════════════════════════

@router.message(Command("start_create"))
async def cmd_start_create(message: Message):
    """/start_create A1B2, C3D4  — ro'yxat yaratish"""
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Faqat guruhlarda ishlaydi!")

    if not await _is_admin(message.bot, chat_id, uid):
        return await message.answer("⚠️ Faqat guruh adminlari!")

    args = message.text.split(None, 1)
    raw  = args[1] if len(args) > 1 else ""
    tids = _extract_ids(raw)

    if not tids:
        return await message.answer(
            "❌ Test ID kiritilmadi.\n\n"
            "Namuna:\n"
            "<code>/start_create A36D37BE, 11D13889, 7D71EE2E</code>"
        )

    valid, invalid = [], []
    for tid in tids:
        meta = get_test_meta(tid)
        if meta and meta.get("is_active", True):
            if tid not in valid:
                valid.append(tid)
        else:
            invalid.append(tid)

    if not valid:
        return await message.answer("❌ Hech qanday to'g'ri test topilmadi!")

    if chat_id not in _schedules:
        _schedules[chat_id] = {}
    _schedules[chat_id]["tests"]     = valid
    _schedules[chat_id]["remaining"] = valid[:]
    _schedules[chat_id]["done"]      = []

    text = _tests_list_text(chat_id, "✅ RO'YXAT YARATILDI")
    if invalid:
        text += f"\n\n⚠️ Topilmadi: {', '.join(f'<code>{t}</code>' for t in invalid)}"

    await message.answer(text, reply_markup=_list_kb(chat_id))


# ══ /set_tests — ro'yxatni ko'rish/tahrirlash ════════════════

@router.message(Command("set_tests"))
async def cmd_set_tests(message: Message):
    """/set_tests — mavjud ro'yxatni ko'rish va tahrirlash"""
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Faqat guruhlarda ishlaydi!")

    if not await _is_admin(message.bot, chat_id, uid):
        return await message.answer("⚠️ Faqat guruh adminlari!")

    # Arg bilan kelsa — qo'shish
    args = message.text.split(None, 1)
    if len(args) > 1:
        tids = _extract_ids(args[1])
        if tids:
            if chat_id not in _schedules:
                _schedules[chat_id] = {}
            current = _schedules[chat_id].get("tests", [])
            for tid in tids:
                meta = get_test_meta(tid)
                if meta and meta.get("is_active", True) and tid not in current:
                    current.append(tid)
            _schedules[chat_id]["tests"] = current

    text = _tests_list_text(chat_id)
    await message.answer(text, reply_markup=_list_kb(chat_id))


# ══ /start_set — ovoz ochib boshlash ═════════════════════════

@router.message(Command("start_set"))
async def cmd_start_set(message: Message):
    """/start_set — ovoz ochib testlarni boshlash"""
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Faqat guruhlarda ishlaydi!")

    if not await _is_admin(message.bot, chat_id, uid):
        return await message.answer("⚠️ Faqat guruh adminlari!")

    sched = _schedules.get(chat_id, {})
    if not sched.get("tests"):
        return await message.answer(
            "❌ Ro'yxat yo'q!\n\n"
            "Avval ro'yxat yarating:\n"
            "<code>/start_create ID1, ID2, ID3</code>"
        )

    if sched.get("active"):
        return await message.answer(
            "⚠️ Allaqachon boshlangan!\n"
            "To'xtatish: <code>/stop_set</code>"
        )

    n = len(sched.get("tests", []))
    await message.answer(
        f"🎯 <b>BOSHLASH TASDIQLANG</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Testlar: <b>{n} ta</b>\n"
        f"📊 Rejim: <b>Quiz Poll</b>\n\n"
        f"Har test oldidan {VOTE_SECONDS}s ovoz beriladi.",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="▶️ Boshlash", callback_data=f"sch_start_poll_{chat_id}"),
            InlineKeyboardButton(text="❌ Bekor",    callback_data=f"sch_close_{chat_id}"),
        ).as_markup()
    )


# ══ /stop_set — hammani to'xtatish ═══════════════════════════

@router.message(Command("stop_set"))
async def cmd_stop_set(message: Message):
    """/stop_set — scheduler va joriy testni to'xtatish"""
    chat_id = message.chat.id
    uid     = message.from_user.id

    if message.chat.type not in ("group", "supergroup"):
        return await message.answer("⚠️ Faqat guruhlarda ishlaydi!")

    if not await _is_admin(message.bot, chat_id, uid):
        return await message.answer("⚠️ Faqat guruh adminlari!")

    sched = _schedules.get(chat_id)
    if not sched or not sched.get("active"):
        return await message.answer("ℹ️ Hozir faol jarayon yo'q.")

    await _stop_schedule(message.bot, chat_id, sched)

    done  = sched.get("done", [])
    left  = sched.get("remaining", [])
    _schedules.pop(chat_id, None)

    await message.answer(
        f"⏹ <b>TO'XTATILDI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ O'tkazildi: <b>{len(done)} ta</b>\n"
        f"📋 Qoldi: <b>{len(left)} ta</b>\n\n"
        f"Qayta boshlash: <code>/start_set</code>"
    )


async def _stop_schedule(bot, chat_id, sched):
    """Schedulerni va joriy testni to'xtatish."""
    sched["active"] = False
    task = sched.get("task")
    if task and not task.done():
        task.cancel()

    from handlers.group import _group_sessions, _inline_sessions
    for sessions in (_group_sessions, _inline_sessions):
        if chat_id in sessions:
            t = sessions[chat_id].get("task")
            if t and not t.done():
                t.cancel()
            sessions.pop(chat_id, None)


# ══ Callback handlerlar ═══════════════════════════════════════

@router.callback_query(F.data.startswith("sch_start_"))
async def sch_start_cb(callback: CallbackQuery):
    await callback.answer()
    parts   = callback.data.split("_")
    mode    = "poll"             # faqat poll rejimi
    chat_id = int(parts[3])
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    sched = _schedules.get(chat_id, {})
    if not sched.get("tests"):
        return await callback.answer("❌ Ro'yxat bo'sh!", show_alert=True)
    if sched.get("active"):
        return await callback.answer("⚠️ Allaqachon boshlangan!", show_alert=True)

    try: await callback.message.delete()
    except: pass

    await _start_schedule(callback.bot, chat_id, uid, mode)


@router.callback_query(F.data.startswith("sch_add_"))
async def sch_add_cb(callback: CallbackQuery):
    await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    if chat_id not in _schedules:
        _schedules[chat_id] = {}
    _schedules[chat_id]["waiting_input"] = uid

    await callback.message.answer(
        "➕ <b>TEST KODI YUBORING</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<code>AB12CD34</code>\n"
        "yoki bir nechtasi:\n"
        "<code>AB12CD34, XY56ZW78</code>"
    )


@router.callback_query(F.data.startswith("sch_del_"))
async def sch_del_cb(callback: CallbackQuery):
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

    try:
        await callback.message.edit_text(
            _tests_list_text(chat_id), reply_markup=_list_kb(chat_id)
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("sch_clear_"))
async def sch_clear_cb(callback: CallbackQuery):
    await callback.answer()
    chat_id = int(callback.data.split("_")[2])
    uid     = callback.from_user.id

    if not await _is_admin(callback.bot, chat_id, uid):
        return await callback.answer("⚠️ Faqat admin!", show_alert=True)

    if chat_id in _schedules:
        _schedules[chat_id]["tests"]     = []
        _schedules[chat_id]["remaining"] = []
        _schedules[chat_id]["done"]      = []

    try:
        await callback.message.edit_text(
            _tests_list_text(chat_id), reply_markup=_list_kb(chat_id)
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("sch_close_"))
async def sch_close_cb(callback: CallbackQuery):
    await callback.answer()
    try: await callback.message.delete()
    except: pass


# ══ Matn orqali test ID qo'shish ═════════════════════════════

@router.message(F.text & F.chat.type.in_({"group", "supergroup"}))
async def handle_test_ids_input(message: Message):
    chat_id = message.chat.id
    uid     = message.from_user.id
    sched   = _schedules.get(chat_id, {})

    if sched.get("waiting_input") != uid:
        return

    tids = _extract_ids(message.text or "")
    if not tids:
        await message.answer(
            "❌ Test ID topilmadi.\n"
            "Masalan: <code>AB12CD34</code>"
        )
        return

    _schedules[chat_id].pop("waiting_input", None)
    current = _schedules[chat_id].get("tests", [])
    added = []
    for tid in tids:
        meta = get_test_meta(tid)
        if meta and meta.get("is_active", True) and tid not in current:
            current.append(tid)
            added.append(tid)

    _schedules[chat_id]["tests"] = current

    text = _tests_list_text(chat_id)
    if added:
        text = f"✅ {len(added)} ta test qo'shildi!\n\n" + text
    await message.answer(text, reply_markup=_list_kb(chat_id))


# ══ Scheduler loop ════════════════════════════════════════════

async def _start_schedule(bot, chat_id, uid, mode):
    sched = _schedules.get(chat_id, {})
    tests = sched.get("tests", [])

    _schedules[chat_id].update({
        "remaining":   sched.get("remaining") or tests[:],
        "done":        sched.get("done") or [],
        "mode":        mode,
        "active":      True,
        "host_id":     uid,
        "task":        None,
        "current_tid": None,
    })

    await bot.send_message(
        chat_id,
        f"🚀 <b>AVTO-TEST REJIMI BOSHLANDI!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 Rejim: <b>📊 Quiz Poll</b>\n"
        f"📋 Testlar: <b>{len(tests)} ta</b>\n\n"
        f"⏸ Joriy testni to'xtatish: <code>/quiz_stop</code>\n"
        f"⏹ Hammani to'xtatish: <code>/stop_set</code>",
    )

    task = asyncio.create_task(_scheduler_loop(bot, chat_id))
    _schedules[chat_id]["task"] = task


async def _scheduler_loop(bot, chat_id):
    try:
        while True:
            sched = _schedules.get(chat_id)
            if not sched or not sched.get("active"):
                break

            remaining = sched.get("remaining", [])

            if not remaining:
                done  = sched.get("done", [])
                tests = sched.get("tests", [])
                await bot.send_message(
                    chat_id,
                    f"🔄 <b>BARCHA TESTLAR YAKUNLANDI!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"✅ {len(done)} ta test o'tkazildi.\n"
                    f"♾️ Ro'yxat qaytadan boshlanmoqda...\n\n"
                    f"⏹ To'xtatish: <code>/stop_set</code>"
                )
                sched["remaining"] = tests[:]
                sched["done"]      = []
                await asyncio.sleep(3)
                continue

            # Ovoz
            tid = await _run_vote(bot, chat_id, remaining)
            if tid is None:
                break

            sched["current_tid"] = tid
            sched["remaining"]   = [t for t in remaining if t != tid]
            sched["done"].append(tid)

            meta = get_test_meta(tid) or {}
            mode = sched.get("mode", "poll")
            await bot.send_message(
                chat_id,
                f"🎯 <b>{meta.get('title', tid)}</b> boshlanmoqda...\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📋 {meta.get('question_count', 0)} savol | "
                f"⏱ {meta.get('poll_time', 30)}s/savol"
            )
            await asyncio.sleep(2)

            from handlers.group import _start_group_test
            await _start_group_test(bot, chat_id, sched["host_id"], tid, mode)

            await _wait_for_test(bot, chat_id)
            sched["current_tid"] = None

            if sched.get("active") and sched.get("remaining"):
                left = len(sched["remaining"])
                await bot.send_message(
                    chat_id,
                    f"✅ Test yakunlandi! "
                    f"📋 Qolgan: <b>{left} ta</b>"
                )
                await asyncio.sleep(3)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"Scheduler loop xato ({chat_id}): {e}")
        import traceback; traceback.print_exc()


async def _run_vote(bot, chat_id, remaining: list):
    sched = _schedules.get(chat_id)
    if not sched or not sched.get("active"):
        return None

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
            question=f"🗳 Keyingi test ({VOTE_SECONDS}s)",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
            protect_content=True,
        )
        sched["vote_msg_id"]  = poll_msg.message_id
        sched["vote_poll_id"] = poll_msg.poll.id
        sched["vote_tids"]    = vote_tids
    except Exception as e:
        log.error(f"Ovoz ochishda xato: {e}")
        return random.choice(remaining)

    # Kutish
    for _ in range(VOTE_SECONDS):
        await asyncio.sleep(1)
        sched = _schedules.get(chat_id)
        if not sched or not sched.get("active"):
            return None

    # Ovozni yopish
    try:
        result    = await bot.stop_poll(chat_id, poll_msg.message_id)
        max_votes = max((o.voter_count for o in result.options), default=0)

        if max_votes == 0:
            chosen_tid = random.choice(vote_tids)
            meta = get_test_meta(chosen_tid) or {}
            await bot.send_message(
                chat_id,
                f"🎲 Hech kim ovoz bermadi — random:\n"
                f"🎯 <b>{meta.get('title', chosen_tid)}</b>"
            )
        else:
            best_idx   = max(range(len(result.options)), key=lambda i: result.options[i].voter_count)
            chosen_tid = vote_tids[best_idx]
            meta       = get_test_meta(chosen_tid) or {}
            await bot.send_message(
                chat_id,
                f"🏆 <b>Ovoz natijasi:</b>\n"
                f"✅ <b>{meta.get('title', chosen_tid)}</b>\n"
                f"🗳 {result.options[best_idx].voter_count} ovoz"
            )
        return chosen_tid
    except Exception as e:
        log.error(f"Ovozni yopishda xato: {e}")
        return random.choice(vote_tids)


async def _wait_for_test(bot, chat_id):
    from handlers.group import _group_sessions, _inline_sessions
    for _ in range(3600):
        await asyncio.sleep(1)
        sched = _schedules.get(chat_id)
        if not sched or not sched.get("active"):
            return
        if chat_id not in _group_sessions and chat_id not in _inline_sessions:
            return


# ══ /quiz_stop hook — joriy testni to'xtatib keyingi ovozga ══

async def notify_test_finished(bot, chat_id):
    """
    group.py dan chaqiriladi — /quiz_stop bosilganda.
    Joriy test to'xtatiladi, scheduler keyingi ovozga o'tadi.
    _wait_for_test sessiya yo'qligini sezib davom etadi.
    """
    pass  # _wait_for_test o'zi sezadi


# ══ Poll answer ═══════════════════════════════════════════════

@router.poll_answer()
async def scheduler_poll_answer(poll_answer):
    poll_id = poll_answer.poll_id
    for sched in _schedules.values():
        if sched.get("vote_poll_id") == poll_id:
            break
