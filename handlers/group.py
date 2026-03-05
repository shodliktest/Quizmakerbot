"""👥 GURUH REJIMI — Quiz Poll + Leaderboard (ommaviy guruhlar uchun)"""
import asyncio, logging, re
from aiogram import Router, F
from aiogram.types import (Message, CallbackQuery, PollAnswer,
                            InlineKeyboardButton, ChatMemberUpdated)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from utils.ram_cache import get_test_by_id
from utils.db import get_test_full, save_result
from utils.scoring import calculate_score

log    = logging.getLogger(__name__)
router = Router()

# Faol guruh sessiyalari: {chat_id: {...}}
_group_sessions: dict = {}
LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]


async def route_poll_answer(poll_answer: PollAnswer) -> bool:
    """
    Markaziy router tomonidan chaqiriladi.
    Guruh sessiyasiga tegishli bo'lsa True qaytaradi va event boshqariladi.
    Aks holda False — private handler ishlatiladi.
    """
    poll_id = poll_answer.poll_id

    target_chat = None
    for chat_id, session in _group_sessions.items():
        if poll_id in session.get("poll_map", {}):
            target_chat = chat_id
            break

    if target_chat is None:
        return False  # Bu guruh sessiyasiga tegishli emas

    if not poll_answer.option_ids:
        return True   # Retract — e'tibor bermaymiz, lekin handle qildik

    session = _group_sessions[target_chat]
    uid_str = str(poll_answer.user.id)
    q_idx   = session["poll_map"][poll_id]

    if uid_str not in session["answers"]:
        session["answers"][uid_str] = {}
    session["names"][uid_str] = poll_answer.user.full_name

    opt_idx = poll_answer.option_ids[0]
    q = session["questions"][q_idx] if q_idx < len(session["questions"]) else {}

    if q.get("type") == "true_false":
        letter = "Ha" if opt_idx == 0 else "Yo'q"
    else:
        letter = LETTERS[opt_idx] if opt_idx < len(LETTERS) else str(opt_idx)

    session["answers"][uid_str][str(q_idx)] = letter
    log.debug(f"Guruh poll javob: chat={target_chat} uid={poll_answer.user.id} q={q_idx} → {letter}")
    return True


# ═══════════════════════════════════════════════════════════
# GURUHGA YUBORISH YO'RIQNOMASI
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("group_info_"))
async def group_info(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[11:]
    meta = get_test_by_id(tid)
    if not meta:
        return await callback.message.answer("❌ Test topilmadi.")

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="📤 Guruhga yuborish",
        switch_inline_query=f"test_{tid}"
    ))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"view_test_{tid}"))

    await callback.message.edit_text(
        f"👥 <b>GURUHDA YECHISH</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 <b>{meta.get('title')}</b>\n\n"
        f"<b>Qanday ishlaydi:</b>\n"
        f"1️⃣ <b>\"Guruhga yuborish\"</b> — guruhni tanlang\n"
        f"2️⃣ Guruhda xabar ko'rinadi\n"
        f"3️⃣ <b>\"👥 Guruhda boshlash\"</b> tugmasini bosing\n"
        f"4️⃣ Bot quiz poll larni navbat bilan yuboradi\n"
        f"5️⃣ Hamma javob beradi — oxirida reyting!\n\n"
        f"<i>💡 Bot guruhda admin yoki a'zo bo'lishi kerak.\n"
        f"Guruh sozlamalari: Polls = yoqilgan bo'lsin.</i>",
        reply_markup=b.as_markup()
    )


# ═══════════════════════════════════════════════════════════
# GURUHDA BOSHLASH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("group_start_"))
async def group_start_poll(callback: CallbackQuery):
    await callback.answer()
    tid     = callback.data[12:]
    chat    = callback.message.chat
    chat_id = chat.id
    uid     = callback.from_user.id

    if chat.type not in ("group", "supergroup"):
        return await callback.answer(
            "⚠️ Bu tugma faqat guruhda ishlaydi!\n"
            "Testni guruhga yuboring va u yerda bosing.",
            show_alert=True
        )

    if chat_id in _group_sessions:
        return await callback.answer(
            "⚠️ Guruhda allaqachon test ketmoqda!\n"
            "Avval uni tugating.",
            show_alert=True
        )

    # Test yuklash — avval RAM, keyin TG
    test = get_test_by_id(tid)
    if not test or not test.get("questions"):
        try:
            wait_msg = await callback.bot.send_message(
                chat_id,
                "⏳ <b>Test yuklanmoqda...</b>\n"
                "<i>Telegram bazasidan savollar olinmoqda...</i>"
            )
        except Exception:
            wait_msg = None

        test = await get_test_full(tid)

        if wait_msg:
            try: await wait_msg.delete()
            except Exception: pass

    if not test:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    qs = [q for q in test.get("questions", [])
          if q.get("type", "multiple_choice") in ("multiple_choice", "true_false")]

    if not qs:
        return await callback.answer(
            "⚠️ Bu testda quiz poll uchun savollar yo'q!\n"
            "(Faqat A/B/C/D va Ha/Yo'q savollar ishlaydi)",
            show_alert=True
        )

    poll_time = test.get("poll_time", 30) or 30

    _group_sessions[chat_id] = {
        "tid":       tid,
        "test":      test,
        "questions": qs,
        "answers":   {},   # {uid_str: {q_idx_str: letter}}
        "names":     {},   # {uid_str: full_name}
        "poll_map":  {},   # {poll_id: question_index}
        "host_id":   uid,
        "poll_time": poll_time,
        "task":      None,
    }

    try: await callback.message.delete()
    except Exception: pass

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="⏹ Testni to'xtatish",
        callback_data=f"gstop_{uid}"
    ))

    host_name = callback.from_user.full_name
    skipped   = len(test.get("questions", [])) - len(qs)
    skip_txt  = f"\n⚠️ <i>{skipped} ta matn savol o'tkazildi</i>" if skipped else ""

    await callback.bot.send_message(
        chat_id,
        f"🚀 <b>GURUH TESTI BOSHLANDI!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 <b>{test.get('title')}</b>\n"
        f"📋 {len(qs)} ta savol | ⏱ {poll_time}s/savol{skip_txt}\n\n"
        f"👤 Boshlovchi: <b>{host_name}</b>\n\n"
        f"<i>📢 Hamma qatnashsin! Poll larni yuboring...\n"
        f"Javob bering — oxirida reyting ko'rinadi! 🏆</i>",
        reply_markup=b.as_markup()
    )

    task = asyncio.create_task(
        _run_group_polls(callback.bot, chat_id, tid, qs, poll_time)
    )
    _group_sessions[chat_id]["task"] = task


# ═══════════════════════════════════════════════════════════
# POLL YUBORISH — KETMA-KET
# ═══════════════════════════════════════════════════════════

async def _run_group_polls(bot, chat_id, tid, qs, poll_time):
    for i, q in enumerate(qs):
        if chat_id not in _group_sessions:
            return

        session = _group_sessions[chat_id]

        qtype = q.get("type", "multiple_choice")
        opts  = q.get("options", [])
        if qtype == "true_false":
            opts = ["Ha", "Yo'q"]

        clean_opts = []
        for opt in opts:
            ot = str(opt).split(")", 1)[-1].strip() if ")" in str(opt) else str(opt)
            clean_opts.append(ot[:100])
        if not clean_opts:
            continue

        # To'g'ri javob indeksi
        correct = q.get("correct", "")
        if qtype == "true_false":
            correct_idx = 0 if "ha" in str(correct).lower() else 1
        elif isinstance(correct, int):
            correct_idx = correct
        else:
            m = re.match(r"^([A-Za-z])", str(correct).strip())
            correct_idx = (ord(m.group(1).upper()) - ord("A")) if m else 0
        correct_idx = max(0, min(correct_idx, len(clean_opts) - 1))

        expl = q.get("explanation") or None
        if expl and expl in ("Izoh kiritilmagan.", "Izoh yo'q", "Izoh kiritilmagan", ""):
            expl = None
        if expl and len(expl) > 195:
            expl = expl[:195] + "..."

        qtxt = q.get("question", q.get("text", "Savol"))
        qtxt = re.sub(r'^\[\d+/\d+\]\s*', '', qtxt).strip()
        header = f"{i+1}/{len(qs)}. "
        if len(header + qtxt) > 295:
            qtxt = qtxt[:295 - len(header)] + "..."

        try:
            poll_msg = await bot.send_poll(
                chat_id=chat_id,
                question=header + qtxt,
                options=clean_opts,
                type="quiz",
                correct_option_id=correct_idx,
                explanation=expl,
                open_period=poll_time if poll_time > 0 else None,
                is_anonymous=False,
                allows_multiple_answers=False,
            )
            if chat_id in _group_sessions:
                _group_sessions[chat_id]["poll_map"][poll_msg.poll.id] = i

            # Vaqt tugashini kutish + 2 soniya bufer
            wait = (poll_time + 2) if poll_time > 0 else 10
            await asyncio.sleep(wait)

        except TelegramBadRequest as e:
            log.error(f"Guruh poll xatosi (savol {i+1}): {e}")
            if "not enough rights" in str(e).lower():
                try:
                    await bot.send_message(
                        chat_id,
                        "❌ <b>Bot guruhda poll yubora olmadi!</b>\n\n"
                        "Botga guruhda <b>admin</b> yoki "
                        "<b>poll yuborish huquqi</b> bering."
                    )
                except Exception:
                    pass
                if chat_id in _group_sessions:
                    del _group_sessions[chat_id]
                return
            await asyncio.sleep(2)
        except Exception as e:
            log.error(f"Poll yuborishda noma'lum xato: {e}")
            await asyncio.sleep(2)

    # Barcha savollar tugadi
    if chat_id in _group_sessions:
        await asyncio.sleep(3)  # Oxirgi javoblar kelishini kutish
        await _show_group_leaderboard(bot, chat_id, tid)
        if chat_id in _group_sessions:
            del _group_sessions[chat_id]


# ═══════════════════════════════════════════════════════════
# TO'XTATISH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gstop_"))
async def group_stop(callback: CallbackQuery):
    host_id = int(callback.data[6:])
    chat_id = callback.message.chat.id
    uid     = callback.from_user.id

    if uid != host_id:
        try:
            member = await callback.bot.get_chat_member(chat_id, uid)
            if member.status not in ("administrator", "creator"):
                return await callback.answer(
                    "⚠️ Faqat boshlovchi yoki admin to'xtatishi mumkin!",
                    show_alert=True
                )
        except Exception:
            return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    await callback.answer("⏹ To'xtatilmoqda...")

    if chat_id in _group_sessions:
        session = _group_sessions[chat_id]
        task    = session.get("task")
        if task and not task.done():
            task.cancel()

        tid = session.get("tid", "")
        await _show_group_leaderboard(callback.bot, chat_id, tid)
        if chat_id in _group_sessions:
            del _group_sessions[chat_id]
    else:
        try: await callback.message.delete()
        except Exception: pass
        await callback.bot.send_message(chat_id, "⏹ Test to'xtatildi.")


# ═══════════════════════════════════════════════════════════
# LEADERBOARD
# ═══════════════════════════════════════════════════════════

async def _show_group_leaderboard(bot, chat_id, tid):
    session      = _group_sessions.get(chat_id, {})
    names        = session.get("names", {})
    answers      = session.get("answers", {})
    test         = session.get("test", {})
    qs           = session.get("questions", [])
    bot_info     = await bot.me()
    bot_username = bot_info.username

    if not answers:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(
            text="▶️ Testni boshlash",
            url=f"https://t.me/{bot_username}?start={tid}"
        ))
        await bot.send_message(
            chat_id,
            f"🏁 <b>TEST YAKUNLANDI!</b>\n\n"
            f"📝 {test.get('title', 'Test')}\n\n"
            f"😔 Hech kim javob bermadi.",
            reply_markup=b.as_markup()
        )
        return

    results = []
    for uid_str, user_answers in answers.items():
        scored = calculate_score(qs, user_answers)
        results.append({
            "name":    names.get(uid_str, f"User {uid_str}"),
            "pct":     scored.get("percentage", 0),
            "correct": scored.get("correct_count", 0),
            "uid":     int(uid_str),
            "scored":  scored,
        })
        try:
            save_result(int(uid_str), tid, {**scored, "mode": "group_poll"})
        except Exception as e:
            log.error(f"Natija saqlashda xato: {e}")

    results.sort(key=lambda x: x["pct"], reverse=True)

    medals = ["🥇", "🥈", "🥉"]
    text   = (
        f"🏆 <b>GURUH TEST NATIJALARI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {test.get('title', 'Test')} | {len(qs)} savol\n"
        f"👥 {len(results)} qatnashchi\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    for i, r in enumerate(results[:20]):
        medal  = medals[i] if i < 3 else f"{i+1}."
        filled = int(r["pct"] / 10)
        bar    = "█" * filled + "░" * (10 - filled)
        text  += f"{medal} <b>{r['name']}</b>\n"
        text  += f"   <code>[{bar}]</code> {r['pct']}% ({r['correct']}/{len(qs)})\n\n"

    if len(results) > 20:
        text += f"<i>...va yana {len(results) - 20} ta qatnashchi</i>\n"

    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text="🔄 Yana bir marta",
            url=f"https://t.me/{bot_username}?start={tid}"
        ),
        InlineKeyboardButton(
            text="📤 Ulashish",
            switch_inline_query=f"test_{tid}"
        ),
    )
    await bot.send_message(chat_id, text, reply_markup=b.as_markup())


# ═══════════════════════════════════════════════════════════
# BOT GURUHGA QO'SHILDI
# ═══════════════════════════════════════════════════════════

@router.my_chat_member()
async def on_bot_added(event: ChatMemberUpdated):
    new_status = event.new_chat_member.status
    if new_status in ("member", "administrator") and event.chat.type in ("group", "supergroup"):
        bot_info = await event.bot.me()
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(
            text="📚 Testlarni ko'rish",
            url=f"https://t.me/{bot_info.username}"
        ))
        try:
            await event.bot.send_message(
                event.chat.id,
                f"👋 Salom! <b>Quiz Bot</b> guruhga qo'shildi! 🎉\n\n"
                f"📤 <b>Guruhga test yuborish:</b>\n"
                f"<code>@{bot_info.username} [test nomi]</code>\n\n"
                f"👥 Yuborilgan testda <b>\"Guruhda boshlash\"</b> tugmasini bosing.\n\n"
                f"<i>💡 Bot to'g'ri ishlashi uchun guruhda <b>poll yuborish</b> "
                f"huquqi bo'lishi kerak.</i>",
                reply_markup=b.as_markup()
            )
        except Exception as e:
            log.warning(f"Guruhga xabar yuborishda xato: {e}")
