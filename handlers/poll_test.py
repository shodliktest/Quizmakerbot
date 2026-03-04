"""📊 POLL TEST — private chat"""
import time, asyncio, logging, re
from aiogram import Router, F
from aiogram.types import CallbackQuery, PollAnswer
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from utils import store
from utils.states import PollSolve
from utils.scoring import score, fmt_result
from keyboards.kb import main_kb, result_kb, poll_ctrl_kb, poll_resume_kb

log    = logging.getLogger(__name__)
router = Router()
LT     = "ABCDEFGHIJ"
PTYPES = ("multiple_choice", "true_false", "multi_select")

_timers: dict = {}   # cid -> Task


# ═══════════════════════════════════════════════════════════
# BOSHLASH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("s_poll_"))
async def start_poll(cb: CallbackQuery, state: FSMContext):
    msg = cb.message
    uid = cb.from_user.id

    # Guruhda → group.py boshqaradi
    if msg and msg.chat.type in ("group", "supergroup"):
        tid     = cb.data[7:]
        chat_id = msg.chat.id
        if store.has_session(chat_id):
            return await cb.answer("⚠️ Guruhda test allaqachon boshlanmoqda!", show_alert=True)
        test = store.get_test(tid)
        if not test:
            return await cb.answer("❌ Test topilmadi.", show_alert=True)
        qs = [q for q in test.get("questions", [])
              if q.get("type", "multiple_choice") in ("multiple_choice", "true_false")]
        if not qs:
            return await cb.answer("❌ Poll uchun variantli savollar yo'q!", show_alert=True)
        pt = test.get("poll_time", 30) or 30
        store.create_session(chat_id, tid, test, qs, "poll", uid, pt)
        await cb.answer()
        try: await msg.delete()
        except: pass
        from handlers.group import countdown, poll_send_q
        await countdown(cb.bot, chat_id, test.get("title", "Test"), len(qs), pt)
        await poll_send_q(cb.bot, chat_id)
        return

    # Private
    tid  = cb.data[7:]
    test = store.get_test(tid)
    if not test:
        return await cb.answer("❌ Test topilmadi.", show_alert=True)

    all_qs = test.get("questions", [])
    qs     = [q for q in all_qs if q.get("type", "multiple_choice") in PTYPES]
    if not qs:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="▶️ Inline test", callback_data=f"s_test_{tid}"))
        try:
            await msg.edit_text(
                "⚠️ Poll uchun variantli savollar yo'q.\n"
                "▶️ Inline testni sinab ko'ring:",
                reply_markup=b.as_markup()
            )
        except:
            await msg.answer("⚠️ Variantli savollar yo'q.", reply_markup=b.as_markup())
        return

    cur = await state.get_state()
    if cur in (PollSolve.active.state, PollSolve.paused.state):
        await state.clear()
        _cancel_timer(msg.chat.id)

    await cb.answer()
    pt = test.get("poll_time", 30) or 30
    cid = msg.chat.id

    await state.set_state(PollSolve.active)
    await state.set_data({
        "test": test, "qs": qs, "idx": 0,
        "answers": {}, "poll_map": {}, "msg_ids": [],
        "cid": cid, "t0": time.time(), "pt": pt,
        "uid": uid, "answered_this": False,
        "no_ans_streak": 0,
    })

    try: await msg.delete()
    except: pass

    # Countdown
    skip = len(all_qs) - len(qs)
    skip_txt = f"\n⚠️ <i>{skip} ta matn savol o'tkazildi</i>" if skip else ""
    info = await cb.bot.send_message(
        cid,
        f"<b>📊 POLL TEST</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 <b>{test.get('title')}</b>\n"
        f"📋 {len(qs)} savol | ⏱ {pt}s/savol"
        f"{skip_txt}\n\n"
        f"<i>Javob bering — timer avtomatik o'tadi.</i>",
        reply_markup=poll_ctrl_kb()
    )
    await state.update_data(info_msg_id=info.message_id)
    await _send_poll(cb.bot, cid, state)


# ═══════════════════════════════════════════════════════════
# SAVOL YUBORISH
# ═══════════════════════════════════════════════════════════

async def _send_poll(bot, cid, state: FSMContext):
    d   = await state.get_data()
    qs  = d["qs"]
    idx = d["idx"]
    if idx >= len(qs):
        await _finish_poll(bot, cid, state, d)
        return

    q  = qs[idx]
    pt = d.get("pt", 30)

    opts = []
    for opt in q.get("options", []):
        ot = str(opt).split(")", 1)[-1].strip() if ")" in str(opt) else str(opt)
        opts.append(ot[:95] + "..." if len(ot) > 95 else ot)
    if q.get("type") == "true_false" or not opts:
        opts = ["Ha", "Yo'q"]

    corr = q.get("correct", "")
    if q.get("type") == "true_false":
        ci = 0 if "ha" in str(corr).lower() else 1
    elif isinstance(corr, int):
        ci = corr
    else:
        m  = re.match(r"^([A-Za-z])", str(corr).strip())
        ci = (ord(m.group(1).upper()) - ord("A")) if m else 0
    ci = max(0, min(ci, len(opts) - 1))

    expl = (q.get("explanation") or "").strip()
    if expl in ("Izoh kiritilmagan.", "Izoh yo'q", ""):
        expl = None
    if expl and len(expl) > 195:
        expl = expl[:195] + "..."

    qtxt = re.sub(r"^\[\d+/\d+\]\s*", "", q.get("question", q.get("text", "Savol"))).strip()
    hdr  = f"[{idx+1}/{len(qs)}] "
    if len(hdr + qtxt) > 295:
        qtxt = qtxt[:295 - len(hdr)] + "..."

    await state.update_data(answered_this=False)

    try:
        pm = await bot.send_poll(
            chat_id=cid, question=hdr + qtxt, options=opts,
            type="quiz", correct_option_id=ci, explanation=expl,
            is_anonymous=False, open_period=pt if pt > 0 else None
        )
        msgs   = d.get("msg_ids", []);  msgs.append(pm.message_id)
        pmap   = d.get("poll_map", {}); pmap[pm.poll.id] = idx
        await state.update_data(msg_ids=msgs, poll_map=pmap, cur_poll_id=pm.poll.id)

        _cancel_timer(cid)
        wait = pt if pt > 0 else 60
        task = asyncio.create_task(_poll_timeout(bot, cid, state, idx, wait))
        _timers[cid] = task
    except Exception as e:
        log.error(f"send_poll: {e}")
        await state.update_data(idx=idx + 1)
        await _send_poll(bot, cid, state)


def _cancel_timer(cid):
    t = _timers.pop(cid, None)
    if t:
        try: t.cancel()
        except: pass


async def _poll_timeout(bot, cid, state, expected_idx, wait_sec):
    try:
        await asyncio.sleep(wait_sec)
        if await state.get_state() != PollSolve.active.state:
            return
        d = await state.get_data()
        if d.get("idx") != expected_idx:
            return

        answered = d.get("answered_this", False)
        total_qs = len(d.get("qs", []))

        if not answered:
            streak = d.get("no_ans_streak", 0) + 1
            await state.update_data(no_ans_streak=streak)
            ans = d.get("answers", {}); ans[str(expected_idx)] = None
            new_idx = expected_idx + 1
            await state.update_data(answers=ans, idx=new_idx)

            if streak >= 2:
                await state.set_state(PollSolve.paused)
                await state.update_data(no_ans_streak=0)
                await bot.send_message(
                    cid,
                    f"⏸ <b>PAUZA</b>\n\n"
                    f"Ketma-ket 2 ta savolga javob berilmadi.\n"
                    f"Savol {expected_idx+1}/{total_qs}",
                    reply_markup=poll_resume_kb()
                )
            else:
                if new_idx < total_qs:
                    await _send_poll(bot, cid, state)
                else:
                    fresh = await state.get_data()
                    await _finish_poll(bot, cid, state, fresh)
        else:
            await state.update_data(no_ans_streak=0)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"poll_timeout: {e}")


# ═══════════════════════════════════════════════════════════
# JAVOB
# ═══════════════════════════════════════════════════════════

@router.poll_answer()
async def on_poll_answer(poll_answer: PollAnswer, bot, state: FSMContext):
    # Guruh sessiyasiga tegishlimi?
    poll_id = poll_answer.poll_id
    for sess in store._sessions.values():
        if sess.get("mode") == "poll" and poll_id in sess.get("poll_map", {}):
            # group.py boshqaradi
            uid   = poll_answer.user.id
            uname = poll_answer.user.username
            name  = f"@{uname}" if uname else poll_answer.user.full_name
            if poll_answer.option_ids:
                store.record_poll_answer(sess, uid, name, poll_id, poll_answer.option_ids)
            return

    # Private poll
    cur = await state.get_state()
    if cur not in (PollSolve.active.state, PollSolve.paused.state):
        return

    d    = await state.get_data()
    pmap = d.get("poll_map", {})
    pid  = poll_answer.poll_id
    if pid not in pmap:
        return
    if not poll_answer.option_ids:
        return

    qi  = pmap[pid]
    qs  = d.get("qs", [])
    q   = qs[qi] if qi < len(qs) else {}
    ans = d.get("answers", {})

    if q.get("type") == "true_false":
        ch = "Ha" if poll_answer.option_ids[0] == 0 else "Yo'q"
    else:
        i  = poll_answer.option_ids[0]
        ch = LT[i] if i < len(LT) else str(i)
    ans[str(qi)] = ch

    new_idx = d.get("idx", 0) + 1
    await state.update_data(
        answers=ans, idx=new_idx,
        answered_this=True, no_ans_streak=0
    )
    await state.set_state(PollSolve.active)

    cid = d.get("cid")
    _cancel_timer(cid)

    if cid:
        fresh = await state.get_data()
        if new_idx < len(fresh["qs"]):
            await _send_poll(bot, cid, state)
        else:
            await _finish_poll(bot, cid, state, fresh)


# ═══════════════════════════════════════════════════════════
# PAUZA / DAVOM / TO'XTATISH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "pause_poll", PollSolve.active)
async def pause_poll(cb: CallbackQuery, state: FSMContext):
    cid = cb.message.chat.id
    _cancel_timer(cid)
    await state.set_state(PollSolve.paused)
    await cb.answer("⏸")
    try: await cb.message.delete()
    except: pass
    d = await state.get_data()
    await cb.bot.send_message(
        cid,
        f"⏸ <b>PAUZA</b>\n\nSavol {d.get('idx',0)}/{len(d.get('qs',[]))}",
        reply_markup=poll_resume_kb()
    )


@router.callback_query(F.data == "resume_poll", PollSolve.paused)
async def resume_poll(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PollSolve.active)
    await cb.answer("▶️")
    try: await cb.message.delete()
    except: pass
    cid = cb.message.chat.id
    await _send_poll(cb.bot, cid, state)


@router.callback_query(F.data == "stop_poll")
async def stop_poll(cb: CallbackQuery, state: FSMContext):
    cid = cb.message.chat.id
    _cancel_timer(cid)
    d   = await state.get_data()
    await state.clear()
    await cb.answer("⏹")
    for mid in d.get("msg_ids", []):
        try: await cb.bot.stop_poll(cid, mid)
        except: pass
    mid = d.get("info_msg_id")
    if mid:
        try: await cb.bot.delete_message(cid, mid)
        except: pass
    try: await cb.message.delete()
    except: pass
    await cb.bot.send_message(
        cid, "⏹ <b>Poll test to'xtatildi.</b>",
        reply_markup=main_kb(cb.from_user.id)
    )


# ═══════════════════════════════════════════════════════════
# YAKUNLASH
# ═══════════════════════════════════════════════════════════

async def _finish_poll(bot, cid, state: FSMContext, d: dict):
    test    = d["test"]
    qs      = d["qs"]
    answers = d.get("answers", {})
    elapsed = int(time.time() - d.get("t0", time.time()))
    uid     = d.get("uid", cid)

    _cancel_timer(cid)
    mid = d.get("info_msg_id")
    if mid:
        try: await bot.delete_message(cid, mid)
        except: pass

    res = score(qs, answers)
    res.update({"time_spent": elapsed, "passing_score": test.get("passing_score", 60), "mode": "poll"})

    # User nomi
    try:
        chat = await bot.get_chat(uid)
        uname = f"@{chat.username}" if chat.username else chat.full_name
    except:
        uname = f"User{uid}"
    res["user_name"] = uname
    res["tid"]       = test.get("test_id", "")

    rid = store.save_result(uid, res)
    user = store.get_user(uid) or {}
    total = user.get("total", 0) + 1
    avg   = round((user.get("avg", 0) * (total - 1) + res["percentage"]) / total, 1)
    user.update({"total": total, "avg": avg})
    store.upsert_user(uid, user)

    await state.clear()
    await bot.send_message(
        cid,
        fmt_result(res, test),
        reply_markup=result_kb(test.get("test_id", ""), rid)
    )
