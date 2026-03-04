"""📚 TESTLAR KATALOGI + INLINE TEST"""
import time, asyncio, logging, re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from utils import store
from utils.states import Solve
from utils.scoring import score, fmt_result
from keyboards.kb import (
    main_kb, test_card_kb, answer_kb, next_kb, result_kb, analysis_kb
)
from handlers.start import send_card

log    = logging.getLogger(__name__)
router = Router()
LT     = "ABCDEFGHIJ"
BAR    = 30


# ═══════════════════════════════════════════════════════════
# KATALOG
# ═══════════════════════════════════════════════════════════

async def show_catalog(event):
    tests = store.get_public_tests()
    text  = (
        "<b>📚 TESTLAR BO'LIMI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>Test kodini yuboring yoki fanni tanlang:</i>\n\n"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    if not tests:
        text += "📭 Hozircha ommaviy testlar yo'q."
    else:
        cats = {}
        for t in tests:
            c = t.get("category", "Boshqa")
            cats[c] = cats.get(c, 0) + 1
        for cat, cnt in sorted(cats.items()):
            b.row(InlineKeyboardButton(
                text=f"📁 {cat}  ({cnt} ta)",
                callback_data=f"cat_{cat[:30]}"
            ))

    if isinstance(event, Message):
        await event.answer(text, reply_markup=b.as_markup())
    else:
        try:
            await event.message.edit_text(text, reply_markup=b.as_markup())
        except TelegramBadRequest:
            await event.message.answer(text, reply_markup=b.as_markup())


@router.message(StateFilter(None), F.text == "📚 Testlar")
async def tests_menu(msg: Message):
    if msg.chat.type != "private":
        return
    await show_catalog(msg)


@router.callback_query(F.data.startswith("cat_"))
async def show_cat(cb: CallbackQuery):
    await cb.answer()
    cat   = cb.data[4:]
    tests = [t for t in store.get_public_tests()
             if str(t.get("category", "")).startswith(cat)]
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    for t in tests:
        b.row(InlineKeyboardButton(
            text=f"📝 {t.get('title','Nomsiz')} ({t.get('solve_count',0)} marta)",
            callback_data=f"vt_{t.get('test_id')}"
        ))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_cats"))
    try:
        await cb.message.edit_text(
            f"<b>📁 {cat}</b> — {len(tests)} ta test",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "back_cats")
async def back_cats(cb: CallbackQuery):
    await cb.answer()
    await show_catalog(cb)


@router.callback_query(F.data.startswith("vt_"))
async def view_test(cb: CallbackQuery):
    await cb.answer()
    tid  = cb.data[3:]
    test = store.get_test(tid)
    if not test:
        return await cb.message.answer("❌ Test topilmadi.")
    await send_card(cb, test, tid)


# ═══════════════════════════════════════════════════════════
# INLINE TEST BOSHLASH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("s_test_"))
async def start_inline(cb: CallbackQuery, state: FSMContext):
    msg = cb.message
    # Guruh → group.py da boshqariladi
    if msg and msg.chat.type in ("group", "supergroup"):
        return

    uid = cb.from_user.id
    user = store.get_user(uid)
    if user and user.get("is_blocked"):
        return await cb.answer("🚫 Bloklangansiz.", show_alert=True)

    tid  = cb.data[7:]
    test = store.get_test(tid)
    if not test:
        return await cb.answer("❌ Test topilmadi.", show_alert=True)

    qs = test.get("questions", [])
    if not qs:
        return await cb.answer("❌ Bu testda savollar yo'q.", show_alert=True)

    # Joriy test bormi?
    cur = await state.get_state()
    if cur in (Solve.answering.state, Solve.text_answer.state):
        await state.clear()

    await cb.answer()
    poll_time = test.get("poll_time", 30) or 30

    await state.set_data({
        "test":    test,
        "qs":      qs,
        "idx":     0,
        "answers": {},
        "t0":      time.time(),
        "pt":      poll_time,
        "cid":     msg.chat.id if msg else uid,
    })
    await state.set_state(Solve.answering)
    await _send_q(cb, state, edit=True)


# ═══════════════════════════════════════════════════════════
# SAVOL YUBORISH
# ═══════════════════════════════════════════════════════════

async def _send_q(event, state: FSMContext, edit=False):
    d    = await state.get_data()
    qs   = d["qs"]
    idx  = d["idx"]
    q    = qs[idx]
    test = d["test"]
    pt   = d.get("pt", 30)

    filled  = int(idx / len(qs) * BAR)
    bar     = "█" * filled + "░" * (BAR - filled)
    qtxt    = re.sub(r"^\[\d+/\d+\]\s*", "", q.get("question", q.get("text", "?")))
    qtype   = q.get("type", "multiple_choice")

    header = (
        f"<b>📝 {test.get('title','')} — {idx+1}/{len(qs)}</b>\n"
        f"<code>[{bar}]</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if qtype in ("multiple_choice", "true_false", "multi_select"):
        opts = q.get("options", [])
        if qtype == "true_false" and not opts:
            opts = ["Ha", "Yo'q"]
        letters = []
        body    = f"<b>{qtxt}</b>\n\n"
        for i, opt in enumerate(opts):
            lt  = LT[i] if i < len(LT) else str(i+1)
            ot  = str(opt).split(")", 1)[-1].strip() if ")" in str(opt) else str(opt)
            body += f"▫️ <b>{lt})</b> {ot}\n"
            letters.append(lt)
        body += f"\n<i>⏱ {pt}s</i>"
        kb    = answer_kb(letters)
        await state.set_state(Solve.answering)
    else:
        body = f"<b>{qtxt}</b>\n\n✍️ <i>Javobingizni yozing:</i>"
        kb   = None
        await state.set_state(Solve.text_answer)

    full = header + body
    if edit and isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(full, reply_markup=kb)
            return
        except TelegramBadRequest:
            pass
    target = event.message if isinstance(event, CallbackQuery) else event
    await target.answer(full, reply_markup=kb)


# ═══════════════════════════════════════════════════════════
# JAVOB
# ═══════════════════════════════════════════════════════════

_auto: dict = {}   # (cid, uid) -> Task

@router.callback_query(F.data.startswith("ans_"), Solve.answering)
async def process_ans(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    letter  = cb.data[4:]
    d       = await state.get_data()
    idx     = d["idx"]
    qs      = d["qs"]
    q       = qs[idx]
    answers = d.get("answers", {})
    answers[str(idx)] = letter
    await state.update_data(answers=answers)

    # Natijani ko'rsat
    correct = q.get("correct", "")
    if isinstance(correct, int):
        c_lt = LT[correct] if correct < len(LT) else "A"
    else:
        m    = re.match(r"^([A-Za-z])", str(correct).strip())
        c_lt = m.group(1).upper() if m else "A"

    is_ok = letter.upper() == c_lt.upper()
    filled = int(idx / len(qs) * BAR)
    bar    = "█" * filled + "░" * (BAR - filled)
    qtxt   = re.sub(r"^\[\d+/\d+\]\s*", "", q.get("question", q.get("text", "?")))

    header = (
        f"<b>📝 {d['test'].get('title','')} — {idx+1}/{len(qs)}</b>\n"
        f"<code>[{bar}]</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    body = f"<b>{qtxt}</b>\n\n"
    for i, opt in enumerate(q.get("options", [])):
        lt = LT[i] if i < len(LT) else str(i+1)
        ot = str(opt).split(")", 1)[-1].strip() if ")" in str(opt) else str(opt)
        if lt.upper() == c_lt.upper():
            body += f"✅ <b>{lt})</b> {ot}\n"
        elif lt.upper() == letter.upper() and not is_ok:
            body += f"❌ <b>{lt})</b> {ot}\n"
        else:
            body += f"▫️ {lt}) {ot}\n"

    body += f"\n{'🎯 ✅ TO\'G\'RI!' if is_ok else '🎯 ❌ XATO'}\n"
    expl  = (q.get("explanation") or "").strip()
    if expl and expl not in ("Izoh kiritilmagan.", "Izoh yo'q", ""):
        body += f"💡 <i>{expl}</i>\n"

    body += "\n<i>⏭ 30s da keyingi...</i>"
    kb    = next_kb(30)

    try:
        await cb.message.edit_text(header + body, reply_markup=kb)
    except TelegramBadRequest:
        pass

    # Avtomatik keyingi
    uid = cb.from_user.id
    key = (cb.message.chat.id, uid)
    old = _auto.pop(key, None)
    if old:
        old.cancel()
    task = asyncio.create_task(_auto_next(cb, state, idx, qs, 30))
    _auto[key] = task


async def _auto_next(cb, state, idx, qs, delay):
    try:
        await asyncio.sleep(delay)
        if await state.get_state() != Solve.answering.state:
            return
        d = await state.get_data()
        if d.get("idx") != idx:
            return
        if idx < len(qs) - 1:
            await state.update_data(idx=idx + 1)
            await _send_q(cb, state, edit=True)
        else:
            await _finish(cb, state, d)
    except asyncio.CancelledError:
        pass


@router.callback_query(F.data == "next_now", Solve.answering)
async def next_now(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    uid = cb.from_user.id
    key = (cb.message.chat.id, uid)
    t   = _auto.pop(key, None)
    if t:
        t.cancel()
    d   = await state.get_data()
    idx = d["idx"]
    qs  = d["qs"]
    if idx < len(qs) - 1:
        await state.update_data(idx=idx + 1)
        await _send_q(cb, state, edit=True)
    else:
        await _finish(cb, state, d)


@router.message(Solve.text_answer)
async def text_ans(msg: Message, state: FSMContext):
    d       = await state.get_data()
    idx     = d["idx"]
    answers = d.get("answers", {})
    qs      = d["qs"]
    answers[str(idx)] = msg.text.strip()
    await state.update_data(answers=answers, idx=idx + 1)
    await state.set_state(Solve.answering)
    try:
        await msg.delete()
    except:
        pass
    if idx + 1 < len(qs):
        await _send_q(msg, state, edit=False)
    else:
        fresh = await state.get_data()
        await _finish(msg, state, fresh)


@router.callback_query(F.data == "stop_test", Solve.answering)
async def stop_test(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    key = (cb.message.chat.id, uid)
    t   = _auto.pop(key, None)
    if t:
        t.cancel()
    await state.clear()
    await cb.answer("❌ To'xtatildi")
    try:
        await cb.message.delete()
    except:
        pass
    await cb.bot.send_message(
        cb.message.chat.id,
        "❌ <b>Test to'xtatildi.</b>",
        reply_markup=main_kb(uid)
    )


# ═══════════════════════════════════════════════════════════
# YAKUNLASH
# ═══════════════════════════════════════════════════════════

async def _finish(event, state: FSMContext, d: dict):
    test    = d.get("test", {})
    qs      = d.get("qs", [])
    answers = d.get("answers", {})
    elapsed = int(time.time() - d.get("t0", time.time()))

    res     = score(qs, answers)
    res["time_spent"] = elapsed
    res["passing_score"] = test.get("passing_score", 60)
    res["mode"] = "inline"

    uid     = event.from_user.id
    uname   = f"@{event.from_user.username}" if event.from_user.username else event.from_user.full_name
    cid     = (event.message if isinstance(event, CallbackQuery) else event).chat.id
    tid     = test.get("test_id", "")

    res["user_name"] = uname
    res["tid"]       = tid
    rid = store.save_result(uid, res)

    # User statistikasini yangilash
    user = store.get_user(uid) or {}
    total = user.get("total", 0) + 1
    avg   = round((user.get("avg", 0) * (total - 1) + res["percentage"]) / total, 1)
    user.update({"total": total, "avg": avg})
    store.upsert_user(uid, user)

    await state.clear()
    try:
        if isinstance(event, CallbackQuery):
            await event.message.delete()
        else:
            await event.delete()
    except:
        pass

    text = fmt_result(res, test)
    await event.bot.send_message(cid, text, reply_markup=result_kb(tid, rid))


# ═══════════════════════════════════════════════════════════
# TAHLIL
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("analysis_"))
async def show_analysis(cb: CallbackQuery):
    await cb.answer()
    parts = cb.data.split("_")
    if len(parts) < 3:
        return
    rid = parts[1]
    idx = int(parts[2])
    uid = cb.from_user.id

    res = store.get_result(uid, rid)
    if not res:
        return await cb.message.answer("❌ Natija topilmadi.")

    tid  = res.get("tid", "")
    test = store.get_test(tid)
    qs   = test.get("questions", []) if test else []
    dets = res.get("details", [])

    if not dets:
        return await cb.message.answer("❌ Tahlil ma'lumoti yo'q.")

    total = len(dets)
    if idx >= total:
        idx = 0

    det = dets[idx]
    q   = qs[idx] if idx < len(qs) else {}
    qtxt = re.sub(r"^\[\d+/\d+\]\s*", "", q.get("question", q.get("text", f"Savol {idx+1}")))

    text = (
        f"🔍 <b>TAHLIL — {idx+1}/{total}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{qtxt}</b>\n\n"
        f"{'✅ To\'g\'ri!' if det.get('ok') else '❌ Xato'}\n"
        f"📝 Sizning javob: <b>{det.get('answer','—')}</b>\n"
        f"✅ To'g'ri javob: <b>{det.get('correct','—')}</b>\n"
    )
    expl = (det.get("explain") or "").strip()
    if expl and expl not in ("Izoh kiritilmagan.", ""):
        text += f"\n💡 <i>{expl}</i>"

    try:
        await cb.message.edit_text(text, reply_markup=analysis_kb(rid, idx, total))
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=analysis_kb(rid, idx, total))
