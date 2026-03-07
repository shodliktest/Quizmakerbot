"""👥 GURUH REJIMI — Quiz Poll + Inline (tugmalar + countdown)
================================================================
POLL USULI:   group_start_<tid>  → Telegram native poll
INLINE USULI: group_inline_<tid> → Inline tugmalar + countdown timer

Qaysi usul:
  - "📊 Quiz Poll"        → start_poll_ (private) yoki group_start_ (guruh)
  - "👥 Guruhda (Inline)" → group_inline_<tid>

Natijalar:
  - Poll usuli: PollAnswer orqali kim qaysi variantni bosganini bilamiz
  - Inline usuli: callback_query orqali
  - Ikkalasida ham: calculate_score → save_result → rasm leaderboard
"""
import asyncio
import logging
import re
from typing import Dict, Optional

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, PollAnswer,
    InlineKeyboardButton, ChatMemberUpdated
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from utils.ram_cache import get_test_by_id, is_test_paused
from utils.db import get_test_full, save_result
from utils.scoring import calculate_score

log    = logging.getLogger(__name__)
router = Router()

LETTERS      = ["A","B","C","D","E","F","G","H","I","J"]
COUNT_EMOJIS = ["3️⃣","2️⃣","1️⃣","🚀"]

# ─── Sessiyalar ────────────────────────────────────────────────
# Poll sessiyasi: {chat_id: {...}}
_group_sessions: Dict[int, dict] = {}

# Inline sessiyasi: {chat_id: {...}}
_inline_sessions: Dict[int, dict] = {}


# ══════════════════════════════════════════════════════════════
# POLL ANSWER ROUTING (poll_router.py dan chaqiriladi)
# ══════════════════════════════════════════════════════════════

async def route_poll_answer(poll_answer: PollAnswer) -> bool:
    poll_id     = poll_answer.poll_id
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


# ══════════════════════════════════════════════════════════════
# YORDAMCHI: TEST YUKLASH
# ══════════════════════════════════════════════════════════════

async def _load_test(bot, chat_id: int, tid: str) -> Optional[dict]:
    """Test RAMdan yoki TGdan yuklanadi."""
    test = get_test_by_id(tid)
    if not test or not test.get("questions"):
        try:
            wm = await bot.send_message(chat_id, "⏳ <b>Test yuklanmoqda...</b>")
        except Exception:
            wm = None
        test = await get_test_full(tid)
        if wm:
            try: await wm.delete()
            except: pass
    return test or None


# ══════════════════════════════════════════════════════════════
# POLL USULI
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("group_start_"))
async def group_start_poll(callback: CallbackQuery):
    await callback.answer()
    tid = callback.data[12:]
    uid = callback.from_user.id

    # Inline message dan kelganda callback.message = None
    if callback.message is None:
        return await callback.answer(
            "⚠️ Bu tugma faqat guruhda ishlaydi!\n"
            "Testni guruhga yuboring va o'sha yerda bosing.",
            show_alert=True
        )

    chat    = callback.message.chat
    chat_id = chat.id

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
    if chat_id in _inline_sessions:
        return await callback.answer(
            "⚠️ Guruhda inline test ketmoqda!\n"
            "Avval uni tugating.", show_alert=True
        )

    test = await _load_test(callback.bot, chat_id, tid)
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
    except: pass

    cdown = await callback.bot.send_message(chat_id, f"📝 <b>{test.get('title')}</b>")
    for emoji in COUNT_EMOJIS:
        await asyncio.sleep(0.8)
        try: await cdown.edit_text(emoji)
        except: pass
    await asyncio.sleep(0.5)
    try: await cdown.delete()
    except: pass

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏹ Testni to'xtatish", callback_data=f"gstop_{uid}"))
    skipped  = len(test.get("questions",[])) - len(qs)
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


async def _run_group_polls(bot, chat_id: int, tid: str, qs: list, poll_time: int):
    for i, q in enumerate(qs):
        if chat_id not in _group_sessions:
            return
        session = _group_sessions[chat_id]
        qtype   = q.get("type","multiple_choice")
        opts    = q.get("options",[])
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
                except: pass
                _group_sessions.pop(chat_id, None)
                return
            await asyncio.sleep(2)
        except Exception as e:
            log.error(f"Poll xato: {e}")
            await asyncio.sleep(2)

    if chat_id in _group_sessions:
        await asyncio.sleep(3)
        await _show_group_leaderboard(bot, chat_id, tid)
        _group_sessions.pop(chat_id, None)


# ══════════════════════════════════════════════════════════════
# INLINE USULI (tugmalar + countdown timer)
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("group_inline_"))
async def group_start_inline(callback: CallbackQuery):
    await callback.answer()
    tid = callback.data[13:]
    uid = callback.from_user.id

    # Inline message dan kelganda callback.message = None
    if callback.message is None:
        return await callback.answer(
            "⚠️ Bu tugma faqat guruhda ishlaydi!\n"
            "Testni guruhga yuboring va o'sha yerda bosing.",
            show_alert=True
        )

    chat    = callback.message.chat
    chat_id = chat.id

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
            "⚠️ Guruhda poll testi ketmoqda!\nAvval uni tugating.", show_alert=True
        )
    if chat_id in _inline_sessions:
        return await callback.answer(
            "⚠️ Guruhda allaqachon test ketmoqda!\nAvval uni tugating.", show_alert=True
        )

    test = await _load_test(callback.bot, chat_id, tid)
    if not test:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    qs = test.get("questions", [])
    if not qs:
        return await callback.answer("⚠️ Bu testda savollar yo'q!", show_alert=True)

    poll_time     = test.get("poll_time", 30) or 30
    passing_score = float(test.get("passing_score", 60))

    _inline_sessions[chat_id] = {
        "tid":           tid,
        "test":          test,
        "questions":     qs,
        "answers":       {},          # {uid_str: {q_idx_str: answer_letter}}
        "names":         {},          # {uid_str: full_name}
        "host_id":       uid,
        "poll_time":     poll_time,
        "passing_score": passing_score,
        "cur_q":         0,
        "q_msg_id":      None,
        "task":          None,
        "locked":        False,
    }

    try: await callback.message.delete()
    except: pass

    # Countdown
    cdown = await callback.bot.send_message(chat_id, f"📝 <b>{test.get('title')}</b>")
    for emoji in COUNT_EMOJIS:
        await asyncio.sleep(0.8)
        try: await cdown.edit_text(emoji)
        except: pass
    await asyncio.sleep(0.5)
    try: await cdown.delete()
    except: pass

    # Boshlanish xabari
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏹ To'xtatish", callback_data=f"gi_stop_{uid}"))
    await callback.bot.send_message(
        chat_id,
        f"🚀 <b>INLINE TEST BOSHLANDI!</b>\n"
        f"📝 {test.get('title')} | {len(qs)} savol | ⏱{poll_time}s\n"
        f"📢 Tugmalar orqali javob bering!",
        reply_markup=b.as_markup()
    )

    task = asyncio.create_task(
        _run_inline_session(callback.bot, chat_id, tid, qs, poll_time, passing_score)
    )
    _inline_sessions[chat_id]["task"] = task


async def _run_inline_session(
    bot, chat_id: int, tid: str,
    qs: list, poll_time: int, passing_score: float
):
    """Inline sessiya: har savol uchun tugmalar + countdown."""
    for i, q in enumerate(qs):
        if chat_id not in _inline_sessions:
            return

        session = _inline_sessions[chat_id]
        session["cur_q"]  = i
        session["locked"] = False

        opts    = q.get("options", [])
        qtype   = q.get("type","multiple_choice")
        if qtype == "true_false":
            opts = ["Ha","Yo'q"]
        qtxt = q.get("question", q.get("text","Savol"))
        qtxt = re.sub(r'^\[\d+/\d+\]\s*','',qtxt).strip()

        # ── Savol xabarini yasash ──
        def _q_text(remaining: int) -> str:
            filled = int((poll_time - remaining) / poll_time * 10) if poll_time else 0
            bar    = "■" * filled + "□" * (10 - filled)
            pct    = int((poll_time - remaining) / poll_time * 100) if poll_time else 0
            opt_labels = ["🅐","🅑","🅒","🅓","🅔","🅕"]
            opts_disp  = "\n".join(
                f"  {opt_labels[j]}  {str(o).split(')',1)[-1].strip() if ')' in str(o) else str(o)}"
                for j, o in enumerate(opts[:6])
            )
            return (
                f"❓ <b>{i+1}/{len(qs)}. Savol</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{qtxt}\n\n"
                f"{opts_disp}\n\n"
                f"{bar} {pct}%  ⏱ <b>{remaining}s</b>"
            )

        # ── Klaviatura ──
        def _build_kb() -> InlineKeyboardMarkup:
            from aiogram.types import InlineKeyboardMarkup
            labels = ["🅐","🅑","🅒","🅓","🅔","🅕"]
            btns   = []
            for j, opt in enumerate(opts[:6]):
                opt_clean = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
                btns.append([InlineKeyboardButton(
                    text=f"{labels[j]}  {opt_clean[:40]}",
                    callback_data=f"gi_ans:{chat_id}:{i}:{j}"
                )])
            return InlineKeyboardMarkup(inline_keyboard=btns)

        from aiogram.types import InlineKeyboardMarkup
        kb = _build_kb()

        try:
            msg = await bot.send_message(
                chat_id, _q_text(poll_time),
                parse_mode="HTML", reply_markup=kb
            )
            session["q_msg_id"] = msg.message_id
        except Exception as e:
            log.error(f"Inline savol yuborishda xato: {e}")
            continue

        # ── Countdown timer ──
        for remaining in range(poll_time, 0, -1):
            await asyncio.sleep(1)
            if chat_id not in _inline_sessions:
                return
            if _inline_sessions[chat_id].get("locked"):
                break
            if remaining % 5 == 0 or remaining <= 5:
                try:
                    await bot.edit_message_text(
                        text=_q_text(remaining),
                        chat_id=chat_id,
                        message_id=msg.message_id,
                        parse_mode="HTML",
                        reply_markup=kb
                    )
                except TelegramBadRequest:
                    pass
                except Exception as e:
                    if "retry" in str(e).lower():
                        await asyncio.sleep(5)

        if chat_id not in _inline_sessions:
            return

        # ── Vaqt tugadi → to'g'ri javobni ko'rsat ──
        session["locked"] = True
        await _reveal_inline_answer(bot, chat_id, i, q, opts, msg.message_id)
        await asyncio.sleep(3)

    # ── Test tugadi ──
    if chat_id in _inline_sessions:
        session = _inline_sessions[chat_id]
        await asyncio.sleep(1)
        await _show_group_leaderboard(
            bot, chat_id, session["tid"],
            session=session, mode="inline"
        )
        _inline_sessions.pop(chat_id, None)


async def _reveal_inline_answer(
    bot, chat_id: int, q_idx: int, q: dict, opts: list, msg_id: int
):
    """Savol vaqti tugagach to'g'ri javobni ko'rsatadi."""
    session     = _inline_sessions.get(chat_id, {})
    answers_map = session.get("answers", {})
    corr        = q.get("correct","")
    qtype       = q.get("type","multiple_choice")

    if qtype == "true_false":
        ci = 0 if "ha" in str(corr).lower() else 1
    elif isinstance(corr, int):
        ci = corr
    else:
        m  = re.match(r"^([A-Za-z])", str(corr).strip())
        ci = (ord(m.group(1).upper()) - ord("A")) if m else 0
    ci = max(0, min(ci, len(opts)-1))

    # Ovozlar soni
    vote_counts = [0] * len(opts)
    total_ans   = 0
    for uid_str, uanswers in answers_map.items():
        ans = uanswers.get(str(q_idx))
        if ans is not None:
            total_ans += 1
            # ans — harf (A,B...) yoki "Ha"/"Yo'q"
            if qtype == "true_false":
                ai = 0 if ans == "Ha" else 1
            else:
                m = re.match(r"^([A-Za-z])", str(ans))
                ai = ord(m.group(1).upper()) - ord("A") if m else -1
            if 0 <= ai < len(vote_counts):
                vote_counts[ai] += 1

    labels     = ["🅐","🅑","🅒","🅓","🅔","🅕"]
    opt_lines  = []
    for j, opt in enumerate(opts[:6]):
        cnt   = vote_counts[j] if j < len(vote_counts) else 0
        pct   = round(cnt / total_ans * 100) if total_ans else 0
        bar_n = int(pct / 10)
        bar   = "🟩" * bar_n + "⬜" * (10 - bar_n)
        lbl   = labels[j] if j < len(labels) else str(j+1)
        mark  = "✅ " if j == ci else "    "
        opt_clean = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
        opt_lines.append(
            f"{mark}{lbl}  {opt_clean}\n"
            f"        {bar}  {pct}%  ({cnt} kishi)"
        )

    qtxt = q.get("question", q.get("text","Savol"))
    qtxt = re.sub(r'^\[\d+/\d+\]\s*','',qtxt).strip()
    expl = q.get("explanation","").strip()

    revealed = (
        f"🏁 <b>Savol {q_idx+1}</b>  —  Vaqt tugadi!\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{qtxt}\n\n"
        f"{chr(10).join(opt_lines)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Javob berdi: <b>{total_ans}</b>"
    )

    try:
        await bot.edit_message_text(
            text=revealed, chat_id=chat_id, message_id=msg_id,
            parse_mode="HTML", reply_markup=None
        )
    except Exception:
        try:
            await bot.send_message(chat_id, revealed, parse_mode="HTML")
        except Exception: pass

    # Izoh
    if expl and expl not in ("Izoh kiritilmagan.","Izoh yo'q","Izoh kiritilmagan"):
        try:
            await bot.send_message(
                chat_id,
                f"<blockquote>💡 {expl}</blockquote>",
                parse_mode="HTML"
            )
        except Exception: pass


# ── Inline javob callback ──────────────────────────────────────

@router.callback_query(F.data.startswith("gi_ans:"))
async def handle_inline_answer(callback: CallbackQuery):
    """Guruh inline testida foydalanuvchi javob bosadi."""
    parts = callback.data.split(":")
    if len(parts) != 4:
        return await callback.answer("❌", show_alert=False)

    _, chat_id_str, q_idx_str, ans_idx_str = parts
    chat_id  = int(chat_id_str)
    q_idx    = int(q_idx_str)
    ans_idx  = int(ans_idx_str)
    user     = callback.from_user
    uid_str  = str(user.id)

    session = _inline_sessions.get(chat_id)
    if not session:
        return await callback.answer("❌ Faol test sessiyasi yo'q.", show_alert=False)
    if session.get("locked"):
        return await callback.answer("🔒 Vaqt tugadi!", show_alert=True)
    if session.get("cur_q") != q_idx:
        return await callback.answer("⏰ Bu savol o'tib ketdi.", show_alert=True)

    # Allaqachon javob berganmi?
    if uid_str in session["answers"] and str(q_idx) in session["answers"][uid_str]:
        return await callback.answer("✋ Siz allaqachon javob bergansiz!", show_alert=False)

    # Javobni saqlash
    if uid_str not in session["answers"]:
        session["answers"][uid_str] = {}
    session["names"][uid_str] = user.full_name or user.first_name or "O'quvchi"

    qs    = session["questions"]
    q     = qs[q_idx] if q_idx < len(qs) else {}
    qtype = q.get("type","multiple_choice")
    opts  = q.get("options",[])
    if qtype == "true_false":
        opts = ["Ha","Yo'q"]

    # ans_idx → harf yoki "Ha"/"Yo'q"
    if qtype == "true_false":
        letter = "Ha" if ans_idx == 0 else "Yo'q"
    else:
        letter = LETTERS[ans_idx] if ans_idx < len(LETTERS) else str(ans_idx)
    session["answers"][uid_str][str(q_idx)] = letter

    # To'g'ri yoki yo'q?
    corr = q.get("correct","")
    if qtype == "true_false":
        ci = 0 if "ha" in str(corr).lower() else 1
        is_correct = ans_idx == ci
    elif isinstance(corr, int):
        is_correct = ans_idx == corr
    else:
        m  = re.match(r"^([A-Za-z])", str(corr).strip())
        ci = (ord(m.group(1).upper()) - ord("A")) if m else 0
        is_correct = ans_idx == ci

    if is_correct:
        await callback.answer("✅ To'g'ri! Ajoyib!", show_alert=False)
    else:
        corr_opt = opts[ci] if 0 <= ci < len(opts) else "?"
        corr_clean = str(corr_opt).split(")",1)[-1].strip() if ")" in str(corr_opt) else str(corr_opt)
        await callback.answer(
            f"❌ Noto'g'ri!\n✅ To'g'ri javob: {corr_clean}",
            show_alert=True
        )


# ── Inline to'xtatish ─────────────────────────────────────────

@router.callback_query(F.data.startswith("gi_stop_"))
async def group_inline_stop(callback: CallbackQuery):
    host_id = int(callback.data[8:])
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
    session = _inline_sessions.get(chat_id)
    if session:
        task = session.get("task")
        if task and not task.done():
            task.cancel()
        tid = session.get("tid","")
        await _show_group_leaderboard(
            callback.bot, chat_id, tid,
            session=session, mode="inline", stopped_early=True
        )
        _inline_sessions.pop(chat_id, None)
    else:
        await callback.bot.send_message(chat_id, "⏹ Test to'xtatildi.")


# ══════════════════════════════════════════════════════════════
# POLL TO'XTATISH
# ══════════════════════════════════════════════════════════════

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
        task    = session.get("task")
        if task and not task.done():
            task.cancel()
        tid = session.get("tid","")
        await _show_group_leaderboard(callback.bot, chat_id, tid, stopped_early=True)
        _group_sessions.pop(chat_id, None)
    else:
        try: await callback.message.delete()
        except: pass
        await callback.bot.send_message(chat_id, "⏹ Test to'xtatildi.")


# ══════════════════════════════════════════════════════════════
# LEADERBOARD — RASM + MATN FALLBACK
# ══════════════════════════════════════════════════════════════

async def _show_group_leaderboard(
    bot, chat_id: int, tid: str,
    session: dict = None, mode: str = "poll",
    stopped_early: bool = False
):
    """
    Test natijalari: avval rasm leaderboard, fallback — matn.
    mode: "poll" yoki "inline"
    """
    if session is None:
        # Poll sessiyasi
        session = _group_sessions.get(chat_id, {})

    names   = session.get("names", {})
    answers = session.get("answers", {})
    test    = session.get("test", {})
    qs      = session.get("questions", [])
    passing = float(session.get("passing_score", test.get("passing_score", 60)))

    bot_info  = await bot.me()
    bot_uname = bot_info.username

    if not answers:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(
            text="▶️ Boshlash",
            url=f"https://t.me/{bot_uname}?start={tid}"
        ))
        stop_txt = "⛔ Test to'xtatildi!\n\n" if stopped_early else ""
        await bot.send_message(
            chat_id,
            f"🏁 <b>TEST YAKUNLANDI!</b>\n📝 {test.get('title','Test')}\n\n{stop_txt}😔 Hech kim javob bermadi.",
            reply_markup=b.as_markup()
        )
        return

    # ── Natijalarni hisoblash ──
    results_for_card = []
    for uid_str, user_answers in answers.items():
        scored = calculate_score(qs, user_answers)
        results_for_card.append({
            "first_name": names.get(uid_str, f"User {uid_str}"),
            "username":   names.get(uid_str, f"User {uid_str}"),
            "score":      scored.get("percentage", 0),
            "correct":    scored.get("correct_count", 0),
            "total":      len(qs),
            "uid":        int(uid_str),
            "scored":     scored,
        })
        try:
            await save_result(
                int(uid_str), tid,
                {**scored, "mode": f"group_{mode}"}
            )
        except Exception as e:
            log.error(f"Natija saqlash: {e}")

    results_for_card.sort(key=lambda x: x["score"], reverse=True)

    # ── 1. Rasm leaderboard ──
    try:
        from utils.leaderboard_card import send_leaderboard_card
        caption = _build_caption(results_for_card, test.get("title","Test"), passing, stopped_early)
        b       = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(
                text="🔄 Yana bir marta",
                url=f"https://t.me/{bot_uname}?start={tid}"
            ),
            InlineKeyboardButton(
                text="📤 Ulashish",
                switch_inline_query=f"test_{tid}"
            ),
        )
        card_msg_id = await send_leaderboard_card(
            bot=bot,
            chat_id=chat_id,
            quiz_title=test.get("title","Test"),
            results=results_for_card,
            passing_score=passing,
            total_questions=len(qs),
            caption=caption,
            delete_after=0,
        )
        if card_msg_id:
            # Tugmalarni alohida xabar sifatida yuborish
            await bot.send_message(
                chat_id,
                "🎉 <b>Barcha ishtirokchilarga rahmat!</b>",
                reply_markup=b.as_markup()
            )
            return
    except Exception as e:
        log.warning(f"Rasm leaderboard xato, matn rejimiga o'tilmoqda: {e}")

    # ── 2. Fallback: Matn leaderboard ──
    await _send_text_leaderboard(
        bot, chat_id, tid, results_for_card,
        test, qs, bot_uname, stopped_early, passing
    )


def _build_caption(results, title, passing, stopped_early):
    if not results:
        return f"🏁 <b>{title}</b>"
    passed   = sum(1 for r in results if r["score"] >= passing)
    avg      = sum(r["score"] for r in results) / len(results)
    top      = results[0]
    top_name = top.get("username") or top.get("first_name","?")
    stop_txt = "\n⛔ <i>Test to'xtatildi</i>" if stopped_early else ""
    return (
        f"🏁 <b>{title}</b>\n\n"
        f"🥇 <b>{top_name}</b> — {top['score']:.0f}%\n"
        f"👥 {len(results)} ishtirokchi  •  ✅ {passed} o'tdi  •  📊 {avg:.0f}% o'rtacha"
        f"{stop_txt}"
    )


async def _send_text_leaderboard(
    bot, chat_id, tid, results, test, qs,
    bot_uname, stopped_early, passing
):
    medals = ["🥇","🥈","🥉"]
    stop_h = "⛔ <b>Test to'xtatildi!</b>\n" if stopped_early else ""
    text   = (
        f"{stop_h}"
        f"🏆 <b>GURUH TEST NATIJALARI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {test.get('title','Test')} | {len(qs)} savol | 👥 {len(results)} kishi\n"
        f"🎯 O'tish bali: {passing:.0f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    for i, r in enumerate(results[:20]):
        medal  = medals[i] if i < 3 else f"{i+1}."
        pct    = r["score"]
        filled = int(pct/10)
        bar    = "█"*filled + "░"*(10-filled)
        icon   = "✅" if pct >= passing else "❌"
        text  += (
            f"{medal} <b>{r['first_name']}</b> {icon}\n"
            f"   <code>[{bar}]</code> {pct:.0f}% ({r['correct']}/{len(qs)})\n\n"
        )
    if len(results) > 20:
        text += f"<i>...va yana {len(results)-20} ta qatnashchi</i>\n"

    avg = sum(r["score"] for r in results) / len(results)
    passed = sum(1 for r in results if r["score"] >= passing)
    text += (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 O'rtacha: <b>{avg:.1f}%</b>  |  ✅ O'tdi: <b>{passed}/{len(results)}</b>\n"
        f"🎉 Barcha ishtirokchilarga rahmat!"
    )
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text="🔄 Yana bir marta",
            url=f"https://t.me/{bot_uname}?start={tid}"
        ),
        InlineKeyboardButton(
            text="📤 Ulashish",
            switch_inline_query=f"test_{tid}"
        ),
    )
    await bot.send_message(chat_id, text, reply_markup=b.as_markup())


# ══════════════════════════════════════════════════════════════
# BOT GURUHGA QO'SHILDI
# ══════════════════════════════════════════════════════════════

@router.my_chat_member()
async def on_bot_added(event: ChatMemberUpdated):
    new_status = event.new_chat_member.status
    if new_status in ("member","administrator") and event.chat.type in ("group","supergroup"):
        bot_info = await event.bot.me()
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(
            text="📚 Testlarni ko'rish",
            url=f"https://t.me/{bot_info.username}"
        ))
        try:
            await event.bot.send_message(
                event.chat.id,
                f"👋 <b>Quiz Bot</b> guruhga qo'shildi! 🎉\n\n"
                f"📊 <b>Poll usuli:</b> Telegram native poll savollar\n"
                f"👥 <b>Inline usuli:</b> Tugmalar + countdown timer\n\n"
                f"Botga yuborilgan testda:\n"
                f"  • <b>\"📊 Quiz Poll\"</b> — poll usuli\n"
                f"  • <b>\"👥 Guruhda (Inline)\"</b> — inline usuli\n\n"
                f"<i>💡 Poll uchun botga admin huquqi kerak.</i>",
                reply_markup=b.as_markup()
            )
        except Exception as e:
            log.warning(f"Guruh xabar: {e}")
