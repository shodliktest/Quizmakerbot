"""📚 TESTLAR — Katalog + Inline test (edit_message + auto-next)"""
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
from keyboards.keyboards import main_kb, inline_pause_kb, CAT_ICONS

log    = logging.getLogger(__name__)
router = Router()

# {uid: asyncio.Task}
_inline_timers: dict = {}
ANSWER_SHOW_SEC = 30   # Javob ko'rsatilgandan keyin keyingi savolga o'tish
QUESTION_SEC    = 30   # Savol chiqgandan so'ng javobsiz kutish




async def _show_next_question(bot, cid, msg_id, qs, idx, state, uid):
    """Keyingi savolni edit orqali ko'rsatib, to'g'ri state o'rnatadi va timer ishlatadi"""
    text, kb, is_text = _build_question_content(qs, idx)
    try:
        await bot.edit_message_text(chat_id=cid, message_id=msg_id, text=text, reply_markup=kb)
        new_msg_id = msg_id
    except TelegramBadRequest:
        msg = await bot.send_message(cid, text, reply_markup=kb)
        new_msg_id = msg.message_id

    await state.update_data(q_msg_id=new_msg_id, answered_this=False)
    if is_text:
        await state.set_state(TestSolving.text_answer)
    else:
        await state.set_state(TestSolving.answering)

    _cancel_timer(uid)
    task = asyncio.create_task(
        _question_timeout(bot, cid, state, uid, idx, QUESTION_SEC)
    )
    _inline_timers[uid] = task

def _check_text_answer(user_ans: str, correct: str, accepted: list = None) -> bool:
    """Matn javobni tekshirish — katta-kichik harf farq qilmaydi, bo'sh joy kesadi"""
    u = user_ans.strip().lower()
    c = str(correct).strip().lower()
    if u == c:
        return True
    # Qabul qilinadigan alternativ javoblar
    for alt in (accepted or []):
        if u == str(alt).strip().lower():
            return True
    # Raqamli javoblar uchun (masalan "42" == "42.0")
    try:
        if float(u.replace(",", ".")) == float(c.replace(",", ".")):
            return True
    except Exception:
        pass
    return False

def _cancel_timer(uid):
    t = _inline_timers.pop(uid, None)
    if t:
        try: t.cancel()
        except: pass


# ══ TEST KODI BILAN QIDIRISH ═══════════════════════════════════
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
    solved_tids  = {r.get("test_id") for r in get_user_results(uid)}

    visible = [
        t for t in all_tests
        if (t.get("visibility") == "public" or
            (t.get("visibility") == "link" and t.get("test_id") in solved_tids))
        and not t.get("is_paused")
    ]
    if not visible:
        text = "📭 <b>TESTLAR</b>\n\nHozircha ommaviy test yo'q."
        b    = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
        try:
            if edit: await msg.edit_text(text, reply_markup=b.as_markup())
            else:    await msg.answer(text, reply_markup=b.as_markup())
        except TelegramBadRequest:
            await msg.answer(text, reply_markup=b.as_markup())
        return

    cats = {}
    for t in visible:
        c = t.get("category") or "Boshqa"
        if c not in cats:
            cats[c] = {"count": 0, "solved": 0}
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
        icon = CAT_ICONS.get(cat, "📋")
        prog = f" ✅{info['solved']}/{info['count']}" if info['solved'] else f" — {info['count']} ta"
        text += f"{icon} <b>{cat}</b>{prog}\n"
        b.row(InlineKeyboardButton(
            text=f"{icon} {cat} — {info['count']} ta",
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


@router.callback_query(F.data.startswith("cat_"))
async def show_cat_tests(callback: CallbackQuery):
    await callback.answer()
    await _show_cat_tests(callback.message, callback.from_user.id,
                          callback.data[4:], page=0, edit=True)

@router.callback_query(F.data.startswith("catp_"))
async def cat_page_cb(callback: CallbackQuery):
    await callback.answer()
    parts    = callback.data[5:].rsplit("_", 1)
    cat_name = parts[0]
    page     = int(parts[1]) if len(parts) > 1 else 0
    await _show_cat_tests(callback.message, callback.from_user.id, cat_name, page, edit=True)


async def _show_cat_tests(msg, uid, cat_name, page=0, edit=False):
    from utils.db import get_user_results
    solved_map  = {r.get("test_id"): r for r in get_user_results(uid)}
    solved_tids = set(solved_map)
    all_tests   = get_all_tests()

    tests = [
        t for t in all_tests
        if (cat_name == "ALL" or t.get("category") == cat_name)
        and (t.get("visibility") == "public" or
             (t.get("visibility") == "link" and t.get("test_id") in solved_tids))
        and not t.get("is_paused")
    ]
    if not tests:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⬅️ Fanlar", callback_data="back_to_cats"))
        try: await msg.edit_text("📭 Bu fanda test yo'q.", reply_markup=b.as_markup())
        except TelegramBadRequest: pass
        return

    PG    = 6
    total = (len(tests)+PG-1)//PG
    page  = max(0, min(page, total-1))
    chunk = tests[page*PG:(page+1)*PG]
    diff_m = {"easy": "🟢", "medium": "🟡", "hard": "🔴", "expert": "⚡"}
    title  = "🌟 BARCHA TESTLAR" if cat_name == "ALL" else f"📚 {cat_name.upper()}"

    text = (
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{len(tests)} ta test | Sahifa {page+1}/{total}</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for t in chunk:
        tid   = t.get("test_id", "")
        t_t   = t.get("title", "Nomsiz")
        d_ico = diff_m.get(t.get("difficulty", ""), "🟡")
        qc    = t.get("question_count", len(t.get("questions", [])))
        sc    = t.get("solve_count", 0)
        vis   = "🔗" if t.get("visibility") == "link" else ""
        if tid in solved_tids:
            r      = solved_map[tid]
            status = f"✅{r.get('best_pct', r.get('last_pct',0))}%×{r.get('attempts',1)}"
        else:
            status = "▶️"
        text += f"{vis}{d_ico} <b>{t_t}</b>\n   📋{qc} | 👥{sc} | {status}\n\n"
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
    b.row(InlineKeyboardButton(text="⬅️ Fanlar", callback_data="back_to_cats"))
    b.row(InlineKeyboardButton(text="🏠 Menyu",   callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("view_test_"))
async def view_test(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[10:]
    test = get_test_by_id(tid) or await get_test_full(tid)
    if not test:
        try: await callback.message.edit_text("❌ Test topilmadi.")
        except: pass
        return
    from handlers.start import _send_test_card
    await _send_test_card(callback, test, tid, viewer_uid=callback.from_user.id, edit=True)

@router.callback_query(F.data == "search_by_code")
async def search_by_code_cb(callback: CallbackQuery):
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


# ══════════════════════════════════════════════════════════════
#  INLINE TEST — edit_message asosida
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("start_test_"))
async def start_inline_test(callback: CallbackQuery, state: FSMContext):
    tid = callback.data[11:]
    if is_test_paused(tid):
        return await callback.answer("⚠️ Bu test vaqtincha to'xtatilgan!", show_alert=True)
    await callback.answer()
    uid = callback.from_user.id
    cid = callback.message.chat.id if callback.message else uid

    # Avvalgi testni to'xtatish
    cur = await state.get_state()
    if cur in (TestSolving.answering.state, TestSolving.text_answer.state,
               TestSolving.paused.state):
        _cancel_timer(uid)
        await state.clear()

    test = get_test_by_id(tid)
    if not test or not test.get("questions"):
        test = await get_test_full(tid)
    if not test:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    qs = test.get("questions", [])
    if not qs:
        return await callback.answer("❌ Savollar yo'q.", show_alert=True)

    await state.set_state(TestSolving.answering)
    await state.set_data({
        "test": test, "qs": qs, "idx": 0, "ans": {},
        "cid": cid, "t0": time.time(), "uid": uid,
        "via_link": test.get("visibility") == "link",
        "no_ans_streak": 0, "q_msg_id": None,
    })

    # Test kartochkasini o'chirmasdan, YANGI xabar sifatida birinchi savol
    await _send_question_new(callback.bot, cid, state, uid)


async def _send_question_new(bot, cid, state, uid):
    """Yangi xabar yuboradi — faqat birinchi savolda yoki pauza qaytganda"""
    d   = await state.get_data()
    qs  = d["qs"]
    idx = d["idx"]
    if idx >= len(qs):
        await _finish_inline(bot, cid, state, d)
        return

    text, kb, is_text = _build_question_content(qs, idx)
    msg = await bot.send_message(cid, text, reply_markup=kb)
    await state.update_data(q_msg_id=msg.message_id, answered_this=False)

    if is_text:
        await state.set_state(TestSolving.text_answer)
    else:
        await state.set_state(TestSolving.answering)

    _cancel_timer(uid)
    task = asyncio.create_task(
        _question_timeout(bot, cid, state, uid, idx, QUESTION_SEC)
    )
    _inline_timers[uid] = task


async def _edit_question(bot, cid, msg_id, state, uid):
    """Mavjud xabarni edit qiladi — keyingi savol"""
    d   = await state.get_data()
    qs  = d["qs"]
    idx = d["idx"]
    if idx >= len(qs):
        await _finish_inline(bot, cid, state, d)
        return

    text, kb, is_text = _build_question_content(qs, idx)
    try:
        await bot.edit_message_text(
            chat_id=cid, message_id=msg_id, text=text, reply_markup=kb
        )
    except TelegramBadRequest:
        # Edit imkoni bo'lmasa yangi yuborish
        msg = await bot.send_message(cid, text, reply_markup=kb)
        msg_id = msg.message_id
        await state.update_data(q_msg_id=msg_id)

    await state.update_data(answered_this=False)
    _cancel_timer(uid)
    task = asyncio.create_task(
        _question_timeout(bot, cid, state, uid, idx, QUESTION_SEC)
    )
    _inline_timers[uid] = task


def _build_question_content(qs, idx):
    """Savol matni va klaviaturasini qurish"""
    total = len(qs)
    q     = qs[idx]
    qtype = q.get("type", "multiple_choice")
    qtxt  = re.sub(r'^\[\d+/\d+\]\s*', '', q.get("question", q.get("text", "Savol"))).strip()

    pause_btn = InlineKeyboardButton(text="⏸ Pauza", callback_data="inline_pause_menu")
    b = InlineKeyboardBuilder()

    if qtype in ("multiple_choice", "multi_select"):
        opts    = q.get("options", [])
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
            f"📝 <b>{idx+1}/{total} — Savol</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{qtxt}\n\n{opt_lines}"
        )
        for l in letters:
            b.add(InlineKeyboardButton(text=l, callback_data=f"ans_{l}"))
        b.adjust(len(letters))
        b.row(pause_btn)

    elif qtype == "true_false":
        text = (
            f"✅❌ <b>{idx+1}/{total} — Ha/Yo'q</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{qtxt}"
        )
        b.row(
            InlineKeyboardButton(text="✅ Ha",   callback_data="ans_Ha"),
            InlineKeyboardButton(text="❌ Yo'q", callback_data="ans_Yoq"),
        )
        b.row(pause_btn)

    else:
        text = (
            f"✏️ <b>{idx+1}/{total} — Matn javob</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{qtxt}\n\n"
            f"<i>✍️ Javobingizni yozing (xabaringiz avtomatik o'chiriladi):</i>"
        )
        b.row(InlineKeyboardButton(text="⏭ O'tkazish", callback_data="skip_q"))
        b.row(pause_btn)
        return text, b.as_markup(), True   # is_text=True

    return text, b.as_markup(), False   # is_text=False


async def _question_timeout(bot, cid, state, uid, expected_idx, wait_sec):
    """Javobsiz QUESTION_SEC soniya o'tsa — xato deb belgilab keyingiga o'tish"""
    try:
        await asyncio.sleep(wait_sec)
        cur = await state.get_state()
        if cur not in (TestSolving.answering.state, TestSolving.text_answer.state): return
        d = await state.get_data()
        if d.get("idx") != expected_idx: return
        if d.get("answered_this"): return

        # Javob berilmadi — streakni oshir
        streak  = d.get("no_ans_streak", 0) + 1
        ans     = d.get("ans", {})
        ans[str(expected_idx)] = None
        new_idx = expected_idx + 1
        qs      = d.get("qs", [])
        msg_id  = d.get("q_msg_id")

        if streak >= 2:
            # 2 marta ketma-ket javobsiz → pauza
            await state.update_data(ans=ans, idx=new_idx, no_ans_streak=0)
            await state.set_state(TestSolving.paused)
            try:
                await bot.edit_message_text(
                    chat_id=cid, message_id=msg_id,
                    text=(
                        f"⏸ <b>TEST PAUZALAND</b>\n\n"
                        f"Ketma-ket 2 ta savolga javob berilmadi.\n"
                        f"<i>Davom etish yoki to'xtatishni tanlang:</i>"
                    ),
                    reply_markup=inline_pause_kb()
                )
            except TelegramBadRequest:
                await bot.send_message(
                    cid,
                    "⏸ <b>TEST PAUZALAND</b>\n\nDavom etish yoki to'xtatish:",
                    reply_markup=inline_pause_kb()
                )
        else:
            # Xato deb belgilab, izoh bilan edit qil, 30s keyingi
            q    = qs[expected_idx] if expected_idx < len(qs) else {}
            corr = q.get("correct", "?")
            expl = q.get("explanation", "")
            if expl in ("Izoh kiritilmagan.", "Izoh yo'q", ""): expl = ""
            expl_txt = f"\n💡 <i>{expl[:120]}</i>" if expl else ""
            qtxt = re.sub(r'^\[\d+/\d+\]\s*', '', q.get("question", q.get("text",""))).strip()

            next_kb = InlineKeyboardBuilder()
            next_kb.row(InlineKeyboardButton(text="➡️ Keyingi", callback_data="next_q_now"))

            text = (
                f"⏰ <b>{expected_idx+1}/{len(qs)} — Vaqt tugadi!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<i>{qtxt[:80]}</i>\n\n"
                f"❌ Javob berilmadi\n"
                f"✔️ To'g'ri: <b>{str(corr)[:60]}</b>{expl_txt}\n\n"
                f"<i>Keyingiga {ANSWER_SHOW_SEC}s da avtomatik o'tadi</i>"
            )
            await state.update_data(ans=ans, idx=new_idx, no_ans_streak=streak)
            try:
                await bot.edit_message_text(
                    chat_id=cid, message_id=msg_id, text=text,
                    reply_markup=next_kb.as_markup()
                )
            except TelegramBadRequest: pass

            # ANSWER_SHOW_SEC soniya keyingi savol
            _cancel_timer(uid)
            task = asyncio.create_task(
                _auto_next(bot, cid, state, uid, new_idx, ANSWER_SHOW_SEC)
            )
            _inline_timers[uid] = task

    except asyncio.CancelledError: pass
    except Exception as e: log.error(f"Timeout: {e}")


# ── Javob handler ─────────────────────────────────────────────
@router.callback_query(F.data.startswith("ans_"), StateFilter(TestSolving.answering))
async def answer_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid    = callback.from_user.id
    cid    = callback.message.chat.id if callback.message else uid
    ans_val= callback.data[4:]
    msg_id = callback.message.message_id

    _cancel_timer(uid)
    d   = await state.get_data()
    qs  = d.get("qs", [])
    idx = d.get("idx", 0)
    ans = d.get("ans", {})

    if idx >= len(qs):
        await _finish_inline(callback.bot, cid, state, d)
        return

    q      = qs[idx]
    corr   = q.get("correct", "")
    qtype  = q.get("type", "multiple_choice")

    if qtype == "true_false":
        is_c = (ans_val.lower() == str(corr).strip().lower())
    else:
        m1 = re.match(r"^([A-Za-z])", ans_val)
        m2 = re.match(r"^([A-Za-z])", str(corr).strip())
        is_c = bool(m1 and m2 and m1.group(1).lower() == m2.group(1).lower())

    # To'g'ri javob matni
    opts      = q.get("options", [])
    corr_text = str(corr)
    if qtype == "multiple_choice" and opts:
        m = re.match(r"^([A-Za-z])", str(corr).strip())
        if m:
            ci = ord(m.group(1).upper()) - ord("A")
            if 0 <= ci < len(opts):
                raw  = str(opts[ci])
                mopt = re.match(r"^([A-Za-z])\s*[).]\s*", raw)
                corr_text = f"{m.group(1).upper()}) {raw[mopt.end():].strip() if mopt else raw}"

    expl = q.get("explanation", "") or ""
    if expl in ("Izoh kiritilmagan.", "Izoh yo'q", "Izoh kiritilmagan"): expl = ""
    expl_txt = f"\n💡 <i>{expl[:120]}</i>" if expl else ""
    qtxt     = re.sub(r'^\[\d+/\d+\]\s*', '', q.get("question", q.get("text",""))).strip()

    ans[str(idx)] = ans_val
    new_idx       = idx + 1
    await state.update_data(ans=ans, idx=new_idx, answered_this=True, no_ans_streak=0)

    # Javob natijasini edit qilib ko'rsatish + "Keyingi" tugma
    next_kb = InlineKeyboardBuilder()
    next_kb.row(InlineKeyboardButton(text="➡️ Keyingi savol", callback_data="next_q_now"))

    result_text = (
        f"{'✅' if is_c else '❌'} <b>{idx+1}/{len(qs)} — {'To\'g\'ri!' if is_c else 'Noto\'g\'ri!'}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<i>{qtxt[:80]}{'...' if len(qtxt)>80 else ''}</i>\n\n"
        f"✔️ To'g'ri: <b>{corr_text[:80]}</b>{expl_txt}\n\n"
        f"<i>{ANSWER_SHOW_SEC}s da avtomatik keyingiga o'tadi</i>"
    )
    try:
        await callback.message.edit_text(result_text, reply_markup=next_kb.as_markup())
    except TelegramBadRequest: pass

    # ANSWER_SHOW_SEC soniyadan keyin keyingi savol — xuddi shu xabarni edit qilamiz
    _cancel_timer(uid)
    task = asyncio.create_task(
        _auto_next(bot=callback.bot, cid=cid, state=state, uid=uid,
                   expected_new_idx=new_idx, wait_sec=ANSWER_SHOW_SEC,
                   msg_id=msg_id)
    )
    _inline_timers[uid] = task


async def _auto_next(bot, cid, state, uid, expected_new_idx, wait_sec, msg_id=None):
    """Javob ko'rsatilgandan keyin ANSWER_SHOW_SEC soniyada keyingi savolga o'tish"""
    try:
        await asyncio.sleep(wait_sec)
        cur = await state.get_state()
        if cur not in (TestSolving.answering.state, TestSolving.text_answer.state): return
        d = await state.get_data()
        if d.get("idx") != expected_new_idx: return

        qs      = d.get("qs", [])
        q_msg_id = msg_id or d.get("q_msg_id")

        if expected_new_idx < len(qs):
            await _show_next_question(bot, cid, q_msg_id, qs, expected_new_idx, state, uid)
        else:
            d_fresh = await state.get_data()
            await _finish_inline(bot, cid, state, d_fresh)

    except asyncio.CancelledError: pass
    except Exception as e: log.error(f"Auto next: {e}")


@router.callback_query(F.data == "next_q_now", StateFilter(TestSolving.answering))
async def next_q_now_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid    = callback.from_user.id
    cid    = callback.message.chat.id if callback.message else uid
    msg_id = callback.message.message_id
    _cancel_timer(uid)
    d   = await state.get_data()
    qs  = d.get("qs", [])
    idx = d.get("idx", 0)

    if idx < len(qs):
        await _show_next_question(callback.bot, cid, msg_id, qs, idx, state, uid)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(callback.bot, cid, state, d_fresh)


# ── Matn javob ────────────────────────────────────────────────
@router.message(StateFilter(TestSolving.text_answer))
async def text_answer_handler(message: Message, state: FSMContext):
    uid      = message.from_user.id
    user_ans = message.text.strip()
    _cancel_timer(uid)

    # Foydalanuvchi xabarini o'chirish
    try: await message.delete()
    except: pass

    d     = await state.get_data()
    idx   = d.get("idx", 0)
    qs    = d.get("qs", [])
    if idx >= len(qs): return
    ans   = d.get("ans", {})
    q     = qs[idx]
    cid   = message.chat.id
    q_msg = d.get("q_msg_id")

    # Javobni tekshirish
    corr      = q.get("correct", "")
    accepted  = q.get("accepted_answers", [])
    is_c      = _check_text_answer(user_ans, corr, accepted)

    ans[str(idx)] = user_ans
    new_idx       = idx + 1
    await state.update_data(ans=ans, idx=new_idx, answered_this=True, no_ans_streak=0)
    await state.set_state(TestSolving.answering)

    # Natija xabarini ko'rsatish (edit)
    expl = q.get("explanation", "") or ""
    if expl in ("Izoh kiritilmagan.", "Izoh yo'q", "Izoh kiritilmagan"): expl = ""
    expl_txt = f"\n💡 <i>{expl[:120]}</i>" if expl else ""
    qtxt     = re.sub(r'^\[\d+/\d+\]\s*', '', q.get("question", q.get("text",""))).strip()

    next_kb = InlineKeyboardBuilder()
    next_kb.row(InlineKeyboardButton(text="➡️ Keyingi savol", callback_data="next_q_now"))

    icon_ok  = "✅" if is_c else "❌"
    label_ok = "To'g'ri!" if is_c else "Noto'g'ri!"
    qtxt_s   = qtxt[:80] + ("..." if len(qtxt) > 80 else "")
    result_text = (
        f"{icon_ok} <b>{idx+1}/{len(qs)} — {label_ok}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<i>{qtxt_s}</i>\n\n"
        f"✍️ Sizning: <code>{user_ans[:60]}</code>\n"
        f"✔️ To'g'ri: <b>{str(corr)[:80]}</b>{expl_txt}\n\n"
        f"<i>{ANSWER_SHOW_SEC}s da avtomatik keyingiga o'tadi</i>"
    )
    try:
        if q_msg:
            await message.bot.edit_message_text(
                chat_id=cid, message_id=q_msg,
                text=result_text, reply_markup=next_kb.as_markup()
            )
        else:
            msg = await message.bot.send_message(
                cid, result_text, reply_markup=next_kb.as_markup()
            )
            await state.update_data(q_msg_id=msg.message_id)
    except TelegramBadRequest:
        msg = await message.bot.send_message(
            cid, result_text, reply_markup=next_kb.as_markup()
        )
        await state.update_data(q_msg_id=msg.message_id)

    # 30s keyingi savol
    _cancel_timer(uid)
    task = asyncio.create_task(
        _auto_next(bot=message.bot, cid=cid, state=state, uid=uid,
                   expected_new_idx=new_idx, wait_sec=ANSWER_SHOW_SEC,
                   msg_id=q_msg)
    )
    _inline_timers[uid] = task


# ── Skip ──────────────────────────────────────────────────────
@router.callback_query(F.data == "skip_q", StateFilter(TestSolving))
async def skip_q_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid    = callback.from_user.id
    cid    = callback.message.chat.id if callback.message else uid
    msg_id = callback.message.message_id
    _cancel_timer(uid)
    d   = await state.get_data()
    idx = d.get("idx", 0)
    ans = d.get("ans", {})
    ans[str(idx)] = None
    new_idx = idx + 1
    await state.update_data(ans=ans, idx=new_idx)
    await state.set_state(TestSolving.answering)
    qs = d.get("qs", [])
    if new_idx < len(qs):
        await _show_next_question(callback.bot, cid, msg_id, qs, new_idx, state, uid)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(callback.bot, cid, state, d_fresh)


# ── Pauza ─────────────────────────────────────────────────────
@router.callback_query(F.data == "inline_pause_menu")
async def inline_pause_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id
    _cancel_timer(uid)
    await state.set_state(TestSolving.paused)
    d   = await state.get_data()
    tot = len(d.get("qs", []))
    idx = d.get("idx", 0)
    try:
        await callback.message.edit_text(
            f"⏸ <b>PAUZA</b>\n\nSavol {idx}/{tot}\nDavom etish yoki to'xtatish:",
            reply_markup=inline_pause_kb()
        )
    except TelegramBadRequest: pass

@router.callback_query(F.data == "resume_inline", StateFilter(TestSolving.paused))
async def resume_inline(callback: CallbackQuery, state: FSMContext):
    await callback.answer("▶️")
    uid    = callback.from_user.id
    cid    = callback.message.chat.id if callback.message else uid
    msg_id = callback.message.message_id
    await state.set_state(TestSolving.answering)
    d   = await state.get_data()
    qs  = d.get("qs", [])
    idx = d.get("idx", 0)
    if idx < len(qs):
        await _show_next_question(callback.bot, cid, msg_id, qs, idx, state, uid)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(callback.bot, cid, state, d_fresh)


@router.callback_query(F.data == "cancel_test")
async def cancel_test_cb(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    _cancel_timer(uid)
    await state.clear()
    await callback.answer("❌ To'xtatildi")
    try:
        await callback.message.edit_text("❌ <b>Test to'xtatildi.</b>")
    except TelegramBadRequest: pass
    await callback.bot.send_message(uid, "🏠 Asosiy menyu:", reply_markup=main_kb(uid))


# ── Yakunlash ─────────────────────────────────────────────────
async def _finish_inline(bot, cid, state, d):
    from utils.scoring import calculate_score, format_result
    from keyboards.keyboards import result_kb

    test     = d["test"]
    qs       = d["qs"]
    ans      = d.get("ans", {})
    elapsed  = int(time.time() - d.get("t0", time.time()))
    uid      = d.get("uid", cid)
    via_link = d.get("via_link", False)
    msg_id   = d.get("q_msg_id")
    _cancel_timer(uid)

    scored = calculate_score(qs, ans)
    scored.update({
        "time_spent":    elapsed,
        "passing_score": test.get("passing_score", 60),
        "mode":          "inline",
    })
    rid = save_result(uid, test.get("test_id", ""), scored, via_link=via_link)
    await state.clear()

    result_text = format_result(scored, test)
    kb          = result_kb(test.get("test_id", ""), rid)

    # Oxirgi savol xabarini natija bilan almashtirish
    if msg_id:
        try:
            await bot.edit_message_text(
                chat_id=cid, message_id=msg_id,
                text=result_text, reply_markup=kb
            )
            return
        except TelegramBadRequest: pass

    await bot.send_message(cid, result_text, reply_markup=kb)
