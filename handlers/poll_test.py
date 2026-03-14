"""📊 POLL TEST — private chat, sanash emoji bilan"""
import time, logging, re, asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, PollAnswer
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from utils.db import get_test_full, save_result
from utils.ram_cache import get_test_by_id, get_daily, is_test_paused
from utils.states import PollTest
from utils.scoring import calculate_score, format_result
from keyboards.keyboards import main_kb, result_kb, poll_pause_kb

log    = logging.getLogger(__name__)
router = Router()
LT     = ["A","B","C","D","E","F","G","H","I","J"]
POLL_TYPES = ("multiple_choice", "true_false", "multi_select")
_poll_timers: dict = {}

COUNT_EMOJIS = ["3️⃣","2️⃣","1️⃣","🚀"]


async def route_poll_answer(poll_answer: PollAnswer, state: FSMContext, bot=None):
    cur_st = await state.get_state()
    if cur_st not in (PollTest.active.state, PollTest.paused.state):
        return
    d    = await state.get_data()
    pmap = d.get("poll_map", {})
    pid  = poll_answer.poll_id
    if pid not in pmap:
        return
    if not poll_answer.option_ids:
        return
    qi  = pmap[pid]
    q   = d["qs"][qi] if qi < len(d["qs"]) else {}
    ans = d.get("ans", {})
    ch  = LT[poll_answer.option_ids[0]] if poll_answer.option_ids[0] < len(LT) else str(poll_answer.option_ids[0])
    if q.get("type") == "true_false":
        ch = "Ha" if poll_answer.option_ids[0] == 0 else "Yo'q"
    ans[str(qi)] = ch
    new_idx = d.get("idx", 0) + 1
    await state.update_data(ans=ans, idx=new_idx, answered_this=True, no_ans_streak=0)
    await state.set_state(PollTest.active)
    cid = d.get("cid")
    _cancel_timer(cid)
    if bot and cid:
        fresh = await state.get_data()
        if new_idx < len(fresh["qs"]):
            await _send_poll(bot, cid, state)
        else:
            await _finish_poll(bot, cid, state, fresh)


# ── Boshlash ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("start_poll_"))
async def start_poll(callback: CallbackQuery, state: FSMContext):
    if callback.message and callback.message.chat.type in ("group","supergroup"):
        return await callback.answer(
            "📊 Poll test private chatda ishlaydi.\n"
            "👥 Guruh uchun → \"Guruhda yechish\" tugmasini ishlating.",
            show_alert=True
        )

    await callback.answer()
    raw    = callback.data[11:]
    via_link = raw.endswith("_link")
    tid    = raw[:-5].upper() if via_link else raw.upper()
    uid    = callback.from_user.id
    msg    = callback.message
    chat_id= msg.chat.id if msg and msg.chat else uid

    # Paused?
    if is_test_paused(tid):
        return await callback.answer("⚠️ Bu test vaqtincha to'xtatilgan!", show_alert=True)

    # FSM tozalash
    from utils.states import TestSolving as _TS
    cur = await state.get_state()
    if cur in (_TS.answering.state, _TS.text_answer.state,
               PollTest.active.state, PollTest.paused.state):
        await state.clear()

    test = get_test_by_id(tid)
    if not test or not test.get("questions"):
        load_msg = None
        try:
            load_msg = await callback.bot.send_message(
                chat_id, "⏳ <b>Test yuklanmoqda...</b>"
            )
        except Exception: pass
        test = await get_test_full(tid)
        if load_msg:
            try: await load_msg.delete()
            except Exception: pass

    if not test:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    all_qs = test.get("questions", [])

    # Savollar va variantlarni har safar aralashtirish
    import random, copy, re as _re
    all_qs = copy.deepcopy(all_qs)
    random.shuffle(all_qs)

    LABELS = ["A","B","C","D","E","F","G","H"]
    def _strip(o): return _re.sub(r"^[A-Ha-h]\s*[).:]\s*", "", str(o)).strip()
    for q in all_qs:
        if q.get("type") not in ("multiple_choice", "multiple", "multi_select"):
            continue
        opts = q.get("options", [])
        if len(opts) < 2: continue
        pure = [_strip(o) for o in opts]
        corr = q.get("correct")
        corr_text = pure[corr] if isinstance(corr, int) and 0 <= corr < len(pure) else (
            _strip(corr) if isinstance(corr, str) else None
        )
        random.shuffle(pure)
        q["options"] = [f"{LABELS[i]}) {t}" for i, t in enumerate(pure)]
        if corr_text is not None:
            ni = next((i for i, t in enumerate(pure) if t == corr_text), 0)
            q["correct"] = f"{LABELS[ni]}) {corr_text}"

    qs = [q for q in all_qs if q.get("type", "multiple_choice") in POLL_TYPES]
    skipped = len(all_qs) - len(qs)

    if not qs:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="▶️ Inline test", callback_data=f"start_test_{tid}"))
        return await msg.answer(
            "⚠️ Bu testda variantli savollar yo'q.",
            reply_markup=b.as_markup()
        )

    pt = test.get("poll_time", 30) or 30
    await state.set_state(PollTest.active)
    await state.set_data({
        "test": test, "qs": qs, "idx": 0,
        "ans": {}, "poll_map": {}, "msg_ids": [],
        "cid": chat_id, "t0": time.time(), "pt": pt,
        "uid": uid, "answered_this": False,
        "via_link": via_link,
    })

    try: await msg.delete()
    except Exception: pass

    # 🚀 Faqat emoji countdown (test nomi bilan)
    countdown = await callback.bot.send_message(
        chat_id,
        f"📝 <b>{test.get('title')}</b>"
    )
    for emoji in COUNT_EMOJIS:
        await asyncio.sleep(0.8)
        try: await countdown.edit_text(emoji)
        except Exception: pass
    await asyncio.sleep(0.5)
    try: await countdown.delete()
    except Exception: pass

    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="⏸ Pauza",      callback_data="pause_poll"),
        InlineKeyboardButton(text="⏹ To'xtatish", callback_data="cancel_poll"),
    )
    skip_txt = f"\n⚠️ <i>{skipped} ta matn savol o'tkazildi</i>" if skipped else ""
    info = await callback.bot.send_message(
        chat_id,
        f"<b>📊 POLL TEST</b> | {len(qs)} savol | ⏱ {pt}s{skip_txt}",
        reply_markup=b.as_markup()
    )
    await state.update_data(info_msg_id=info.message_id)
    await _send_poll(callback.bot, chat_id, state)


# ── Poll yuborish ─────────────────────────────────────────────

async def _send_poll(bot, cid, state):
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

    corr = q.get("correct","")
    if q.get("type") == "true_false":
        ci = 0 if "ha" in str(corr).lower() else 1
    elif isinstance(corr, int):
        ci = corr
    else:
        m  = re.match(r"^([A-Za-z])", str(corr).strip())
        ci = (ord(m.group(1).upper()) - ord("A")) if m else 0
    ci = max(0, min(ci, len(opts) - 1))

    expl = q.get("explanation","") or None
    if expl and expl in ("Izoh kiritilmagan.","Izoh yo'q","Izoh kiritilmagan"):
        expl = None
    if expl and len(expl) > 195:
        expl = expl[:195] + "..."

    qtxt = q.get("question", q.get("text","Savol"))
    qtxt = re.sub(r'^\[\d+/\d+\]\s*', '', qtxt).strip()
    hdr  = f"[{idx+1}/{len(qs)}] "
    if len(hdr + qtxt) > 295:
        qtxt = qtxt[:295 - len(hdr)] + "..."

    await state.update_data(answered_this=False)
    try:
        pm = await bot.send_poll(
            chat_id=cid, question=hdr+qtxt, options=opts,
            type="quiz", correct_option_id=ci, explanation=expl,
            is_anonymous=False, open_period=pt if pt > 0 else None
        )
        msgs = d.get("msg_ids", [])
        msgs.append(pm.message_id)
        pmap = d.get("poll_map", {})
        pmap[pm.poll.id] = idx
        await state.update_data(msg_ids=msgs, poll_map=pmap)
        wait = pt if pt > 0 else 50
        _cancel_timer(cid)
        task = asyncio.create_task(_poll_timeout(bot, cid, state, idx, wait))
        _poll_timers[cid] = task
    except Exception as e:
        log.error(f"Poll xatosi: {e}")
        await state.update_data(idx=idx+1)
        await _send_poll(bot, cid, state)


def _cancel_timer(cid):
    t = _poll_timers.pop(cid, None)
    if t:
        try: t.cancel()
        except Exception: pass


async def _poll_timeout(bot, cid, state, expected_idx, wait_sec):
    try:
        await asyncio.sleep(wait_sec)
        cur_st = await state.get_state()
        if cur_st != PollTest.active.state: return
        d = await state.get_data()
        if d.get("idx") != expected_idx: return
        answered = d.get("answered_this", False)
        qs_total = len(d.get("qs", []))
        if not answered:
            streak = d.get("no_ans_streak", 0) + 1
            await state.update_data(no_ans_streak=streak)
            ans = d.get("ans", {})
            ans[str(expected_idx)] = None
            if streak >= 2:
                await state.set_state(PollTest.paused)
                await state.update_data(ans=ans, idx=expected_idx+1, no_ans_streak=0)
                b = InlineKeyboardBuilder()
                b.row(InlineKeyboardButton(text="▶️ Davom etish",   callback_data="resume_poll"))
                b.row(InlineKeyboardButton(text="⏹ Yakunlash",     callback_data="cancel_poll"))
                await bot.send_message(
                    cid,
                    f"⏸ <b>PAUZA</b> — {expected_idx+1}/{qs_total} savolga javob berilmadi (2 marta).",
                    reply_markup=b.as_markup()
                )
            else:
                new_idx = expected_idx + 1
                await state.update_data(ans=ans, idx=new_idx)
                if new_idx < qs_total:
                    await _send_poll(bot, cid, state)
                else:
                    fresh = await state.get_data()
                    await _finish_poll(bot, cid, state, fresh)
    except asyncio.CancelledError: pass
    except Exception as e: log.error(f"Timeout xato: {e}")


# ── Pauza / Davom / To'xtatish ────────────────────────────────

@router.callback_query(F.data == "pause_poll", PollTest.active)
async def pause_poll(callback: CallbackQuery, state: FSMContext):
    await callback.answer("⏸")
    cid = callback.message.chat.id if callback.message and callback.message.chat else callback.from_user.id
    _cancel_timer(cid)
    await state.set_state(PollTest.paused)
    try: await callback.message.delete()
    except Exception: pass
    d = await state.get_data()
    await callback.bot.send_message(
        cid,
        f"⏸ <b>PAUZA</b> | Savol {d.get('idx',0)}/{len(d.get('qs',[]))}",
        reply_markup=poll_pause_kb()
    )

@router.callback_query(F.data == "resume_poll", PollTest.paused)
async def resume_poll(callback: CallbackQuery, state: FSMContext):
    await callback.answer("▶️")
    await state.set_state(PollTest.active)
    try: await callback.message.delete()
    except Exception: pass
    cid = callback.message.chat.id if callback.message and callback.message.chat else callback.from_user.id
    await _send_poll(callback.bot, cid, state)

@router.callback_query(F.data == "cancel_poll")
async def cancel_poll(callback: CallbackQuery, state: FSMContext):
    cid = callback.message.chat.id if callback.message and callback.message.chat else callback.from_user.id
    _cancel_timer(cid)
    d = await state.get_data()
    await state.clear()
    await callback.answer("❌")
    for mid in d.get("msg_ids", []):
        try: await callback.bot.stop_poll(cid, mid)
        except Exception: pass
    mid = d.get("info_msg_id")
    if mid:
        try: await callback.bot.delete_message(cid, mid)
        except Exception: pass
    try:
        if callback.message: await callback.message.delete()
    except Exception: pass
    await callback.bot.send_message(
        cid, "❌ <b>POLL TEST TO'XTATILDI</b>",
        reply_markup=main_kb(callback.from_user.id)
    )


# ── Yakunlash ─────────────────────────────────────────────────

async def _finish_poll(bot, cid, state, d):
    test    = d["test"]
    qs      = d["qs"]
    ans     = d.get("ans", {})
    elapsed = int(time.time() - d.get("t0", time.time()))
    uid     = d.get("uid", cid)
    via_link= d.get("via_link", False)
    _cancel_timer(cid)

    mid = d.get("info_msg_id")
    if mid:
        try: await bot.delete_message(cid, mid)
        except Exception: pass

    scored = calculate_score(qs, ans)
    scored.update({
        "time_spent":    elapsed,
        "passing_score": test.get("passing_score", 60),
        "mode":          "poll",
    })
    rid = save_result(uid, test.get("test_id",""), scored, via_link=via_link)
    await state.clear()

    daily   = get_daily()
    pct     = scored.get("percentage", 0)
    tid     = test.get("test_id","")
    all_pct = [
        max(v.get("by_test",{}).get(tid,{}).get("all_pcts",[0]))
        for v in daily.values()
        if v.get("by_test",{}).get(tid,{}).get("attempts",0) > 0
    ]
    all_pct.sort(reverse=True)
    rank     = next((i+1 for i, p in enumerate(all_pct) if p <= pct), len(all_pct))
    rank_txt = f"\n🏅 <b>Reyting: {rank}/{len(all_pct)} o'rin</b>" if len(all_pct) > 1 else ""

    await bot.send_message(
        cid,
        format_result(scored, test) + rank_txt,
        reply_markup=result_kb(tid, rid)
    )
