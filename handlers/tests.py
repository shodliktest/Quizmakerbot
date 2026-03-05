"""📚 TESTLAR — Fanlar bo'yicha katalog + Inline test + Pauza logikasi"""
import logging, re, time, asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from utils.db import get_all_tests, get_test_full, save_result
from utils.ram_cache import get_test_by_id, is_test_paused, get_test_meta
from utils.states import TestSolving
from keyboards.keyboards import main_kb, answer_kb, inline_pause_kb, CAT_ICONS

log    = logging.getLogger(__name__)
router = Router()

# inline test timer tasklari: {uid: asyncio.Task}
_inline_timers: dict = {}
INLINE_NEXT_DELAY = 30  # soniya — avto keyingi savol
INLINE_SHOW_DELAY = 2   # javob ko'rsatilgach kutish (soniya)


# ══ TEST KODI TO'G'RIDAN ═══════════════════════════════════════
@router.message(F.text.regexp(r'^[A-Z0-9]{6,10}$'))
async def test_code_direct(message: Message, state: FSMContext):
    cur = await state.get_state()
    if cur in (TestSolving.answering.state, TestSolving.text_answer.state,
               TestSolving.paused.state):
        return
    tid  = message.text.strip().upper()
    test = get_test_by_id(tid) or await get_test_full(tid)
    if not test: return
    from handlers.start import _send_test_card
    await _send_test_card(message, test, tid, viewer_uid=message.from_user.id)


# ══ TESTLAR — FANLAR BO'YICHA ══════════════════════════════════
@router.message(F.text == "📚 Testlar")
async def tests_by_category(message: Message, state: FSMContext):
    cur = await state.get_state()
    if cur in (TestSolving.answering.state, TestSolving.text_answer.state):
        return
    await _show_categories(message, message.from_user.id)

@router.callback_query(F.data == "go_tests")
async def go_tests_cb(callback: CallbackQuery):
    await callback.answer()
    await _show_categories(callback.message, callback.from_user.id, edit=True)

@router.callback_query(F.data == "back_to_cats")
async def back_to_cats(callback: CallbackQuery):
    await callback.answer()
    await _show_categories(callback.message, callback.from_user.id, edit=True)


async def _show_categories(msg, uid, edit=False):
    from utils.db import get_user_results
    all_tests    = get_all_tests()
    user_results = get_user_results(uid)
    solved_tids  = {r.get("test_id") for r in user_results}

    visible = [
        t for t in all_tests
        if (t.get("visibility")=="public" or
            (t.get("visibility")=="link" and t.get("test_id") in solved_tids))
        and not t.get("is_paused")
    ]

    if not visible:
        text = (
            "📭 <b>TESTLAR</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Hozircha ommaviy test yo'q.\n"
            "Birinchi bo'lib test yaring! 🚀"
        )
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="➕ Test Yaratish", callback_data="create_test"))
        b.row(InlineKeyboardButton(text="🏠 Bosh sahifa",  callback_data="main_menu"))
        try:
            if edit: await msg.edit_text(text, reply_markup=b.as_markup())
            else:    await msg.answer(text, reply_markup=b.as_markup())
        except TelegramBadRequest:
            await msg.answer(text, reply_markup=b.as_markup())
        return

    # Fanlar guruhlash
    cats = {}
    for t in visible:
        c = t.get("category") or "Boshqa"
        if c not in cats:
            cats[c] = {"count":0,"solved":0}
        cats[c]["count"] += 1
        if t.get("test_id") in solved_tids:
            cats[c]["solved"] += 1

    sorted_cats = sorted(cats.items(), key=lambda x: x[1]["count"], reverse=True)

    text = (
        f"📚 <b>TESTLAR — FANLAR BO'YICHA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Jami: {len(visible)} ta test | {len(cats)} ta fan</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for cat, info in sorted_cats:
        icon  = CAT_ICONS.get(cat,"📋")
        count = info["count"]
        solved= info["solved"]
        prog  = f" ✅{solved}/{count}" if solved>0 else f" — {count} ta"
        text += f"{icon} <b>{cat}</b>{prog}\n"
        b.row(InlineKeyboardButton(
            text=f"{icon} {cat} — {count} ta",
            callback_data=f"cat_{cat[:30]}"
        ))

    b.row(
        InlineKeyboardButton(text="🔍 Kod bilan", callback_data="search_by_code"),
        InlineKeyboardButton(text="🌟 Hammasi",   callback_data="cat_ALL"),
    )
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


# ── Fan ichidagi testlar ──────────────────────────────────────
@router.callback_query(F.data.startswith("cat_"))
async def show_cat_tests(callback: CallbackQuery):
    await callback.answer()
    await _show_cat_tests(callback.message, callback.from_user.id,
                          callback.data[4:], page=0, edit=True)

@router.callback_query(F.data.startswith("catp_"))
async def cat_page_cb(callback: CallbackQuery):
    await callback.answer()
    parts    = callback.data[5:].rsplit("_",1)
    cat_name = parts[0]
    page     = int(parts[1]) if len(parts)>1 else 0
    await _show_cat_tests(callback.message, callback.from_user.id, cat_name, page, edit=True)


async def _show_cat_tests(msg, uid, cat_name, page=0, edit=False):
    from utils.db import get_user_results
    user_results = get_user_results(uid)
    solved_tids  = {r.get("test_id") for r in user_results}
    solved_map   = {r.get("test_id"):r for r in user_results}
    all_tests    = get_all_tests()

    if cat_name == "ALL":
        tests = [t for t in all_tests
                 if (t.get("visibility")=="public" or
                     (t.get("visibility")=="link" and t.get("test_id") in solved_tids))
                 and not t.get("is_paused")]
        title = "🌟 BARCHA TESTLAR"
    else:
        tests = [t for t in all_tests
                 if t.get("category")==cat_name
                 and (t.get("visibility")=="public" or
                      (t.get("visibility")=="link" and t.get("test_id") in solved_tids))
                 and not t.get("is_paused")]
        title = f"📚 {cat_name.upper()}"

    if not tests:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⬅️ Fanlar", callback_data="back_to_cats"))
        try: await msg.edit_text(f"📭 {title}\n\nTestlar yo'q.", reply_markup=b.as_markup())
        except TelegramBadRequest: pass
        return

    PG    = 6
    total = (len(tests)+PG-1)//PG
    page  = max(0, min(page, total-1))
    chunk = tests[page*PG:(page+1)*PG]
    diff_m= {"easy":"🟢","medium":"🟡","hard":"🔴","expert":"⚡"}

    text = (
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{len(tests)} ta test | Sahifa {page+1}/{total}</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for t in chunk:
        tid   = t.get("test_id","")
        t_t   = t.get("title","Nomsiz")
        d_ico = diff_m.get(t.get("difficulty",""),"🟡")
        qc    = t.get("question_count",len(t.get("questions",[])))
        sc    = t.get("solve_count",0)
        vis   = "🔗" if t.get("visibility")=="link" else ""
        if tid in solved_tids:
            r      = solved_map[tid]
            best   = r.get("best_pct",r.get("last_pct",0))
            att    = r.get("attempts",1)
            status = f"✅{best}%×{att}"
        else:
            status = "▶️ Boshlanmagan"
        text += f"{vis}{d_ico} <b>{t_t}</b>\n   📋{qc} savol | 👥{sc} | {status}\n\n"
        b.row(InlineKeyboardButton(
            text=f"{'✅' if tid in solved_tids else '▶️'} {t_t[:25]}",
            callback_data=f"view_test_{tid}"
        ))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"catp_{cat_name}_{page-1}"))
    if page < total-1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"catp_{cat_name}_{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Fanlar",  callback_data="back_to_cats"))
    b.row(InlineKeyboardButton(text="🏠 Menyu",    callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("view_test_"))
async def view_test(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[10:]
    uid  = callback.from_user.id
    test = get_test_by_id(tid) or await get_test_full(tid)
    if not test:
        try: await callback.message.edit_text("❌ Test topilmadi.")
        except: pass
        return
    from handlers.start import _send_test_card
    await _send_test_card(callback, test, tid, viewer_uid=uid, edit=True)

@router.callback_query(F.data == "search_by_code")
async def search_by_code(callback: CallbackQuery):
    await callback.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_cats"))
    try:
        await callback.message.edit_text(
            "🔍 <b>TEST KODI BILAN QIDIRISH</b>\n\n"
            "Test kodini yuboring (masalan: <code>AB12CD34</code>)",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest: pass


# ══ INLINE TEST ════════════════════════════════════════════════
@router.callback_query(F.data.startswith("start_test_"))
async def start_inline_test(callback: CallbackQuery, state: FSMContext):
    tid = callback.data[11:]
    if is_test_paused(tid):
        return await callback.answer("⚠️ Bu test vaqtincha to'xtatilgan!", show_alert=True)

    await callback.answer()
    uid = callback.from_user.id
    msg = callback.message
    cid = msg.chat.id if msg and msg.chat else uid

    cur = await state.get_state()
    if cur in (TestSolving.answering.state, TestSolving.text_answer.state,
               TestSolving.paused.state):
        _cancel_inline_timer(uid)
        await state.clear()

    test = get_test_by_id(tid)
    if not test or not test.get("questions"):
        try: lm = await callback.bot.send_message(cid, "⏳ <b>Test yuklanmoqda...</b>")
        except: lm = None
        test = await get_test_full(tid)
        if lm:
            try: await lm.delete()
            except: pass

    if not test:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    qs = test.get("questions",[])
    if not qs:
        return await callback.answer("❌ Savollar yo'q.", show_alert=True)

    via_link = test.get("visibility")=="link"
    await state.set_state(TestSolving.answering)
    await state.set_data({
        "test": test, "qs": qs, "idx": 0, "ans": {},
        "cid": cid, "t0": time.time(), "uid": uid,
        "via_link": via_link, "no_ans_streak": 0,
        "answered_this": False,
    })

    try:
        if msg: await msg.delete()
    except: pass

    await _send_inline_question(callback.bot, cid, state, uid)


async def _send_inline_question(bot, cid, state, uid):
    d     = await state.get_data()
    qs    = d["qs"]
    idx   = d["idx"]

    if idx >= len(qs):
        await _finish_inline(bot, cid, state, d)
        return

    q     = qs[idx]
    qtype = q.get("type","multiple_choice")
    qtxt  = q.get("question",q.get("text","Savol"))
    qtxt  = re.sub(r'^\[\d+/\d+\]\s*','',qtxt).strip()
    total = len(qs)
    await state.update_data(answered_this=False)

    cancel_btn = InlineKeyboardButton(text="⏸ Pauza / ❌ To'xtatish",
                                       callback_data="inline_pause_menu")

    if qtype in ("multiple_choice","multi_select"):
        opts    = q.get("options",[])
        letters = []
        opt_lines = ""
        for i, opt in enumerate(opts):
            raw = str(opt)
            m   = re.match(r"^([A-Za-z])\s*[).]\s*", raw)
            l   = m.group(1).upper() if m else chr(65+i)
            ot  = raw[m.end():].strip() if m else raw.strip()
            letters.append(l)
            opt_lines += f"<b>{l})</b> {ot}\n"

        text = (
            f"📝 <b>Savol {idx+1}/{total}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{qtxt}\n\n{opt_lines}"
        )
        b = InlineKeyboardBuilder()
        for l in letters:
            b.add(InlineKeyboardButton(text=l, callback_data=f"ans_{l}"))
        b.adjust(len(letters))
        b.row(cancel_btn)
        await bot.send_message(cid, text, reply_markup=b.as_markup())

    elif qtype == "true_false":
        text = (
            f"✅❌ <b>Savol {idx+1}/{total}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{qtxt}"
        )
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="✅ Ha",   callback_data="ans_Ha"),
            InlineKeyboardButton(text="❌ Yo'q", callback_data="ans_Yoq"),
        )
        b.row(cancel_btn)
        await bot.send_message(cid, text, reply_markup=b.as_markup())

    else:
        text = (
            f"✏️ <b>Savol {idx+1}/{total}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{qtxt}\n\n<i>Javobingizni yozing:</i>"
        )
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⏭ O'tkazish", callback_data="skip_q"))
        b.row(cancel_btn)
        await bot.send_message(cid, text, reply_markup=b.as_markup())
        await state.set_state(TestSolving.text_answer)
        return

    # 30 soniya timer
    _cancel_inline_timer(uid)
    task = asyncio.create_task(
        _inline_question_timeout(bot, cid, state, uid, idx, INLINE_NEXT_DELAY)
    )
    _inline_timers[uid] = task


def _cancel_inline_timer(uid):
    t = _inline_timers.pop(uid, None)
    if t:
        try: t.cancel()
        except: pass


async def _inline_question_timeout(bot, cid, state, uid, expected_idx, wait_sec):
    """30 soniya javob yo'q bo'lsa — to'g'ri javob ko'rsatib keyingi savol"""
    try:
        await asyncio.sleep(wait_sec)
        cur = await state.get_state()
        if cur not in (TestSolving.answering.state,): return
        d = await state.get_data()
        if d.get("idx") != expected_idx: return

        answered = d.get("answered_this", False)
        if answered: return  # Allaqachon javob berilgan

        # Javob berilmagan — streak
        streak  = d.get("no_ans_streak",0) + 1
        ans     = d.get("ans",{})
        ans[str(expected_idx)] = None
        new_idx = expected_idx + 1
        qs      = d.get("qs",[])

        if streak >= 2:
            # 2 marta javob berilmadi — pauza
            await state.update_data(ans=ans, idx=new_idx, no_ans_streak=0)
            await state.set_state(TestSolving.paused)
            await bot.send_message(
                cid,
                f"⏸ <b>TEST PAUZALAND</b>\n\n"
                f"Ketma-ket 2 ta savol ({expected_idx} va {expected_idx+1}) ga "
                f"javob berilmadi.\n"
                f"<i>Davom etish yoki to'xtatishni tanlang:</i>",
                reply_markup=inline_pause_kb()
            )
        else:
            await state.update_data(ans=ans, idx=new_idx, no_ans_streak=streak)
            # "Vaqt tugadi" xabari — qisqa
            try:
                await bot.send_message(cid, f"⏰ <i>Savol {expected_idx+1} — vaqt tugadi</i>")
            except: pass
            if new_idx < len(qs):
                await _send_inline_question(bot, cid, state, uid)
            else:
                d_fresh = await state.get_data()
                await _finish_inline(bot, cid, state, d_fresh)

    except asyncio.CancelledError: pass
    except Exception as e: log.error(f"Inline timer: {e}")


# ── Pauza menyu ───────────────────────────────────────────────
@router.callback_query(F.data == "inline_pause_menu")
async def inline_pause_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id
    _cancel_inline_timer(uid)
    await state.set_state(TestSolving.paused)
    d = await state.get_data()
    qs_total = len(d.get("qs",[]))
    idx      = d.get("idx",0)
    try: await callback.message.delete()
    except: pass
    await callback.bot.send_message(
        callback.from_user.id,
        f"⏸ <b>PAUZA</b>\n\nSavol {idx}/{qs_total}\nDavom etish yoki to'xtatish:",
        reply_markup=inline_pause_kb()
    )

@router.callback_query(F.data == "resume_inline", StateFilter(TestSolving.paused))
async def resume_inline(callback: CallbackQuery, state: FSMContext):
    await callback.answer("▶️")
    await state.set_state(TestSolving.answering)
    uid = callback.from_user.id
    cid = callback.message.chat.id if callback.message and callback.message.chat else uid
    try: await callback.message.delete()
    except: pass
    await _send_inline_question(callback.bot, cid, state, uid)

@router.callback_query(F.data == "cancel_test")
async def cancel_test_cb(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    _cancel_inline_timer(uid)
    await state.clear()
    await callback.answer("❌ To'xtatildi")
    try: await callback.message.delete()
    except: pass
    await callback.bot.send_message(
        uid, "❌ Test to'xtatildi.",
        reply_markup=main_kb(uid)
    )


# ── Javob handler ─────────────────────────────────────────────
@router.callback_query(F.data.startswith("ans_"), StateFilter(TestSolving.answering))
async def answer_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid     = callback.from_user.id
    cid     = callback.message.chat.id if callback.message and callback.message.chat else uid
    ans_val = callback.data[4:]

    _cancel_inline_timer(uid)

    d    = await state.get_data()
    qs   = d.get("qs",[])
    idx  = d.get("idx",0)
    ans  = d.get("ans",{})

    if idx >= len(qs):
        await _finish_inline(callback.bot, cid, state, d)
        return

    q       = qs[idx]
    corr    = q.get("correct","")
    qtype   = q.get("type","multiple_choice")

    if qtype == "true_false":
        user_ans = "Ha" if ans_val=="Ha" else "Yo'q"
        is_c     = user_ans.lower()==str(corr).strip().lower()
    else:
        m1 = re.match(r"^([A-Za-z])",ans_val)
        m2 = re.match(r"^([A-Za-z])",str(corr).strip())
        is_c = (m1 and m2 and m1.group(1).lower()==m2.group(1).lower()) if m1 and m2 else False

    ans[str(idx)] = ans_val
    new_idx       = idx+1
    await state.update_data(ans=ans, idx=new_idx, answered_this=True, no_ans_streak=0)

    # To'g'ri javob matni
    opts      = q.get("options",[])
    corr_text = str(corr)
    if qtype=="multiple_choice" and opts:
        m = re.match(r"^([A-Za-z])",str(corr).strip())
        if m:
            ci = ord(m.group(1).upper())-ord("A")
            if 0<=ci<len(opts):
                raw  = str(opts[ci])
                mopt = re.match(r"^([A-Za-z])\s*[).]\s*",raw)
                corr_text = f"{m.group(1).upper()}) {raw[mopt.end():].strip() if mopt else raw}"

    expl = q.get("explanation","") or ""
    if expl in ("Izoh kiritilmagan.","Izoh yo'q","Izoh kiritilmagan"): expl=""
    expl_txt = f"\n💡 <i>{expl[:120]}</i>" if expl else ""
    icon     = "✅" if is_c else "❌"
    qtxt     = q.get("question",q.get("text",""))

    # Keyingi tugmasini ko'rsatamiz (30 soniya kutilmaydi, user o'zi bosishi mumkin)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➡️ Keyingi savol", callback_data="next_q_now"))

    try:
        await callback.message.edit_text(
            f"{icon} <b>{'To\'g\'ri!' if is_c else 'Noto\'g\'ri!'}</b>\n"
            f"<i>{qtxt[:80]}{'...' if len(qtxt)>80 else ''}</i>\n\n"
            f"✔️ Javob: <b>{corr_text[:80]}</b>{expl_txt}\n\n"
            f"<i>Keyingi savol 30 soniyada avtomatik o'tadi</i>",
            reply_markup=b.as_markup()
        )
    except: pass

    # 30 soniya timer (user bosmasa avto o'tadi)
    _cancel_inline_timer(uid)
    task = asyncio.create_task(
        _auto_next_question(callback.bot, cid, state, uid, new_idx, INLINE_NEXT_DELAY)
    )
    _inline_timers[uid] = task


async def _auto_next_question(bot, cid, state, uid, expected_new_idx, wait_sec):
    """Javob ko'rsatilgandan keyin 30 soniyada avto keyingi savol"""
    try:
        await asyncio.sleep(wait_sec)
        cur = await state.get_state()
        if cur not in (TestSolving.answering.state,): return
        d = await state.get_data()
        if d.get("idx") != expected_new_idx: return
        qs = d.get("qs",[])
        if expected_new_idx < len(qs):
            await _send_inline_question(bot, cid, state, uid)
        else:
            await _finish_inline(bot, cid, state, d)
    except asyncio.CancelledError: pass
    except Exception as e: log.error(f"Auto next: {e}")


@router.callback_query(F.data == "next_q_now", StateFilter(TestSolving.answering))
async def next_q_now_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id
    cid = callback.message.chat.id if callback.message and callback.message.chat else uid
    _cancel_inline_timer(uid)
    try: await callback.message.delete()
    except: pass
    d   = await state.get_data()
    qs  = d.get("qs",[])
    idx = d.get("idx",0)
    if idx < len(qs):
        await _send_inline_question(callback.bot, cid, state, uid)
    else:
        await _finish_inline(callback.bot, cid, state, d)


@router.callback_query(F.data == "skip_q", StateFilter(TestSolving))
async def skip_q_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id
    cid = callback.message.chat.id if callback.message and callback.message.chat else uid
    _cancel_inline_timer(uid)
    d   = await state.get_data()
    idx = d.get("idx",0)
    ans = d.get("ans",{})
    ans[str(idx)] = None
    new_idx = idx+1
    await state.update_data(ans=ans, idx=new_idx)
    try: await callback.message.delete()
    except: pass
    qs = d.get("qs",[])
    if new_idx < len(qs):
        await _send_inline_question(callback.bot, cid, state, uid)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(callback.bot, cid, state, d_fresh)


# ── Matn javob ────────────────────────────────────────────────
@router.message(StateFilter(TestSolving.text_answer))
async def text_answer_handler(message: Message, state: FSMContext):
    uid = message.from_user.id
    _cancel_inline_timer(uid)
    d   = await state.get_data()
    idx = d.get("idx",0)
    qs  = d.get("qs",[])
    if idx >= len(qs): return
    ans = d.get("ans",{})
    ans[str(idx)] = message.text.strip()
    new_idx = idx+1
    await state.update_data(ans=ans, idx=new_idx, answered_this=True, no_ans_streak=0)
    await state.set_state(TestSolving.answering)
    cid = message.chat.id
    if new_idx < len(qs):
        await _send_inline_question(message.bot, cid, state, uid)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(message.bot, cid, state, d_fresh)


# ── Yakunlash ─────────────────────────────────────────────────
async def _finish_inline(bot, cid, state, d):
    from utils.scoring import calculate_score, format_result
    from keyboards.keyboards import result_kb
    from utils.ram_cache import get_daily

    test     = d["test"]
    qs       = d["qs"]
    ans      = d.get("ans",{})
    elapsed  = int(time.time()-d.get("t0",time.time()))
    uid      = d.get("uid",cid)
    via_link = d.get("via_link",False)
    _cancel_inline_timer(uid)

    scored = calculate_score(qs, ans)
    scored.update({
        "time_spent":    elapsed,
        "passing_score": test.get("passing_score",60),
        "mode":          "inline",
    })
    rid = save_result(uid, test.get("test_id",""), scored, via_link=via_link)
    await state.clear()

    daily   = get_daily()
    pct     = scored.get("percentage",0)
    tid     = test.get("test_id","")
    all_pct = [
        max(v.get("by_test",{}).get(tid,{}).get("all_pcts",[0]))
        for v in daily.values()
        if v.get("by_test",{}).get(tid,{}).get("attempts",0)>0
    ]
    all_pct.sort(reverse=True)
    rank     = next((i+1 for i,p in enumerate(all_pct) if p<=pct), len(all_pct))
    rank_txt = f"\n🏅 <b>Reyting: {rank}/{len(all_pct)} o'rin</b>" if len(all_pct)>1 else ""

    await bot.send_message(
        cid,
        format_result(scored, test)+rank_txt,
        reply_markup=result_kb(tid, rid)
    )
