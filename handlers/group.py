"""👥 GURUH REJIMI — Quiz Poll + Leaderboard"""
import asyncio, logging, re
from aiogram import Router, F
from aiogram.types import (Message, CallbackQuery, PollAnswer,
                            InlineKeyboardButton, ChatMemberUpdated)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from utils.ram_cache import get_test_by_id, is_test_paused
from utils.db import get_test_full, save_result
from utils.scoring import calculate_score

log    = logging.getLogger(__name__)
router = Router()
_group_sessions: dict = {}
LETTERS = ["A","B","C","D","E","F","G","H","I","J"]
COUNT_EMOJIS = ["3️⃣","2️⃣","1️⃣","🚀"]


async def route_poll_answer(poll_answer: PollAnswer) -> bool:
    poll_id = poll_answer.poll_id
    target_chat = None
    for chat_id, session in _group_sessions.items():
        if poll_id in session.get("poll_map", {}):
            target_chat = chat_id
            break
    if target_chat is None:
        return False
    if not poll_answer.option_ids:
        return True
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
    return True


# ── Boshlash ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("group_start_"))
async def group_start_poll(callback: CallbackQuery):
    await callback.answer()
    tid     = callback.data[12:]
    chat    = callback.message.chat
    chat_id = chat.id
    uid     = callback.from_user.id

    if chat.type not in ("group","supergroup"):
        return await callback.answer(
            "⚠️ Bu tugma faqat guruhda ishlaydi!\n"
            "Testni guruhga yuboring va u yerda bosing.",
            show_alert=True
        )

    if is_test_paused(tid):
        return await callback.answer("⚠️ Bu test vaqtincha to'xtatilgan!", show_alert=True)

    if chat_id in _group_sessions:
        return await callback.answer(
            "⚠️ Guruhda allaqachon test ketmoqda!\n"
            "Avval uni tugating.", show_alert=True
        )

    test = get_test_by_id(tid)
    if not test or not test.get("questions"):
        try:
            wm = await callback.bot.send_message(chat_id, "⏳ <b>Test yuklanmoqda...</b>")
        except Exception: wm = None
        test = await get_test_full(tid)
        if wm:
            try: await wm.delete()
            except: pass

    if not test:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    qs = [q for q in test.get("questions",[])
          if q.get("type","multiple_choice") in ("multiple_choice","true_false")]
    if not qs:
        return await callback.answer(
            "⚠️ Bu testda quiz poll uchun savollar yo'q!", show_alert=True
        )

    poll_time = test.get("poll_time", 30) or 30
    _group_sessions[chat_id] = {
        "tid": tid, "test": test, "questions": qs,
        "answers": {}, "names": {}, "poll_map": {},
        "host_id": uid, "poll_time": poll_time, "task": None,
    }

    try: await callback.message.delete()
    except Exception: pass

    # 🚀 Emoji countdown (guruh uchun)
    cdown = await callback.bot.send_message(chat_id, f"📝 <b>{test.get('title')}</b>")
    for emoji in COUNT_EMOJIS:
        await asyncio.sleep(0.8)
        try: await cdown.edit_text(emoji)
        except Exception: pass
    await asyncio.sleep(0.5)
    try: await cdown.delete()
    except Exception: pass

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏹ Testni to'xtatish", callback_data=f"gstop_{uid}"))
    skipped = len(test.get("questions",[])) - len(qs)
    skip_txt = f"\n⚠️ <i>{skipped} ta matn savol o'tkazildi</i>" if skipped else ""
    await callback.bot.send_message(
        chat_id,
        f"🚀 <b>TEST BOSHLANDI!</b> | {len(qs)} savol | ⏱{poll_time}s{skip_txt}\n"
        f"📢 Hamma qatnashing!",
        reply_markup=b.as_markup()
    )

    task = asyncio.create_task(
        _run_group_polls(callback.bot, chat_id, tid, qs, poll_time)
    )
    _group_sessions[chat_id]["task"] = task


# ── Poll yuborish ─────────────────────────────────────────────

async def _run_group_polls(bot, chat_id, tid, qs, poll_time):
    for i, q in enumerate(qs):
        if chat_id not in _group_sessions:
            return
        session = _group_sessions[chat_id]
        qtype = q.get("type","multiple_choice")
        opts  = q.get("options",[])
        if qtype == "true_false":
            opts = ["Ha","Yo'q"]
        clean_opts = []
        for opt in opts:
            ot = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
            clean_opts.append(ot[:100])
        if not clean_opts:
            continue

        corr = q.get("correct","")
        if qtype == "true_false":
            ci = 0 if "ha" in str(corr).lower() else 1
        elif isinstance(corr, int):
            ci = corr
        else:
            m  = re.match(r"^([A-Za-z])", str(corr).strip())
            ci = (ord(m.group(1).upper()) - ord("A")) if m else 0
        ci = max(0, min(ci, len(clean_opts)-1))

        expl = q.get("explanation") or None
        if expl and expl in ("Izoh kiritilmagan.","Izoh yo'q","Izoh kiritilmagan"):
            expl = None
        if expl and len(expl) > 195:
            expl = expl[:195] + "..."

        qtxt = q.get("question", q.get("text","Savol"))
        qtxt = re.sub(r'^\[\d+/\d+\]\s*','',qtxt).strip()
        hdr  = f"{i+1}/{len(qs)}. "
        if len(hdr+qtxt) > 295:
            qtxt = qtxt[:295-len(hdr)] + "..."

        try:
            pm = await bot.send_poll(
                chat_id=chat_id,
                question=hdr+qtxt,
                options=clean_opts,
                type="quiz",
                correct_option_id=ci,
                explanation=expl,
                open_period=poll_time if poll_time > 0 else None,
                is_anonymous=False,
                allows_multiple_answers=False,
            )
            if chat_id in _group_sessions:
                _group_sessions[chat_id]["poll_map"][pm.poll.id] = i
            wait = (poll_time + 2) if poll_time > 0 else 10
            await asyncio.sleep(wait)
        except TelegramBadRequest as e:
            log.error(f"Guruh poll xato (savol {i+1}): {e}")
            if "not enough rights" in str(e).lower():
                try:
                    await bot.send_message(
                        chat_id,
                        "❌ <b>Bot poll yubora olmadi!</b>\n"
                        "Botga guruhda admin yoki poll yuborish huquqi bering."
                    )
                except Exception: pass
                if chat_id in _group_sessions:
                    del _group_sessions[chat_id]
                return
            await asyncio.sleep(2)
        except Exception as e:
            log.error(f"Poll xato: {e}")
            await asyncio.sleep(2)

    if chat_id in _group_sessions:
        await asyncio.sleep(3)
        await _show_group_leaderboard(bot, chat_id, tid)
        if chat_id in _group_sessions:
            del _group_sessions[chat_id]


# ── To'xtatish ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("gstop_"))
async def group_stop(callback: CallbackQuery):
    host_id = int(callback.data[6:])
    chat_id = callback.message.chat.id
    uid     = callback.from_user.id
    if uid != host_id:
        try:
            member = await callback.bot.get_chat_member(chat_id, uid)
            if member.status not in ("administrator","creator"):
                return await callback.answer("⚠️ Faqat boshlovchi yoki admin!", show_alert=True)
        except Exception:
            return await callback.answer("⚠️ Ruxsat yo'q!", show_alert=True)

    await callback.answer("⏹ To'xtatilmoqda...")
    if chat_id in _group_sessions:
        session = _group_sessions[chat_id]
        task = session.get("task")
        if task and not task.done():
            task.cancel()
        tid = session.get("tid","")
        await _show_group_leaderboard(callback.bot, chat_id, tid)
        if chat_id in _group_sessions:
            del _group_sessions[chat_id]
    else:
        try: await callback.message.delete()
        except Exception: pass
        await callback.bot.send_message(chat_id, "⏹ Test to'xtatildi.")


# ── Leaderboard ───────────────────────────────────────────────

async def _show_group_leaderboard(bot, chat_id, tid):
    session  = _group_sessions.get(chat_id, {})
    names    = session.get("names", {})
    answers  = session.get("answers", {})
    test     = session.get("test", {})
    qs       = session.get("questions", [])
    bot_info = await bot.me()
    bot_uname= bot_info.username

    if not answers:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="▶️ Boshlash", url=f"https://t.me/{bot_uname}?start={tid}"))
        await bot.send_message(
            chat_id,
            f"🏁 <b>TEST YAKUNLANDI!</b>\n📝 {test.get('title','Test')}\n\n😔 Hech kim javob bermadi.",
            reply_markup=b.as_markup()
        )
        return

    results = []
    for uid_str, user_answers in answers.items():
        scored = calculate_score(qs, user_answers)
        results.append({
            "name":    names.get(uid_str, f"User {uid_str}"),
            "pct":     scored.get("percentage",0),
            "correct": scored.get("correct_count",0),
            "uid":     int(uid_str),
            "scored":  scored,
        })
        try:
            save_result(int(uid_str), tid, {**scored, "mode":"group_poll"})
        except Exception as e:
            log.error(f"Natija saqlash: {e}")

    results.sort(key=lambda x: x["pct"], reverse=True)
    medals = ["🥇","🥈","🥉"]
    text = (
        f"🏆 <b>GURUH TEST NATIJALARI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {test.get('title','Test')} | {len(qs)} savol | 👥 {len(results)} kishi\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    for i, r in enumerate(results[:20]):
        medal  = medals[i] if i < 3 else f"{i+1}."
        filled = int(r["pct"]/10)
        bar    = "█"*filled + "░"*(10-filled)
        text  += f"{medal} <b>{r['name']}</b>\n   <code>[{bar}]</code> {r['pct']}% ({r['correct']}/{len(qs)})\n\n"
    if len(results) > 20:
        text += f"<i>...va yana {len(results)-20} ta qatnashchi</i>\n"

    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🔄 Yana bir marta",
                             url=f"https://t.me/{bot_uname}?start={tid}"),
        InlineKeyboardButton(text="📤 Ulashish",
                             switch_inline_query=f"test_{tid}"),
    )
    await bot.send_message(chat_id, text, reply_markup=b.as_markup())


# ── Bot guruhga qo'shildi ─────────────────────────────────────

@router.my_chat_member()
async def on_bot_added(event: ChatMemberUpdated):
    new_status = event.new_chat_member.status
    if new_status in ("member","administrator") and event.chat.type in ("group","supergroup"):
        bot_info = await event.bot.me()
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="📚 Testlarni ko'rish",
                                   url=f"https://t.me/{bot_info.username}"))
        try:
            await event.bot.send_message(
                event.chat.id,
                f"👋 <b>Quiz Bot</b> guruhga qo'shildi! 🎉\n\n"
                f"📤 Test ulashish: <code>@{bot_info.username} test nomi</code>\n"
                f"👥 Yuborilgan testda <b>\"Guruhda yechish\"</b> tugmasini bosing.\n\n"
                f"<i>💡 Bot poll yuborish huquqiga ega bo'lsin.</i>",
                reply_markup=b.as_markup()
            )
        except Exception as e:
            log.warning(f"Guruh xabar: {e}")
