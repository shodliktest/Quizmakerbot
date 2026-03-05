"""📚 TESTLAR — Fanlar bo'yicha kategoriya + inline test"""
import logging, re, time, asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from utils.db import get_all_tests, get_test_full, save_result
from utils.ram_cache import get_test_by_id, is_test_paused, get_tests_meta
from utils.states import TestSolving
from keyboards.keyboards import main_kb, answer_kb

log    = logging.getLogger(__name__)
router = Router()


# ══ TEST KODI TO'G'RIDAN ═══════════════════════════════════════
@router.message(F.text.regexp(r'^[A-Z0-9]{6,10}$'))
async def test_code_direct(message: Message, state: FSMContext):
    cur = await state.get_state()
    if cur in (TestSolving.answering.state, TestSolving.text_answer.state):
        return
    tid  = message.text.strip().upper()
    test = get_test_by_id(tid) or await get_test_full(tid)
    if not test: return
    uid = message.from_user.id
    from handlers.start import _send_test_card
    await _send_test_card(message, test, tid, viewer_uid=uid)


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
    """Fanlar ro'yxati — har birida nechta test bor"""
    from utils.db import get_user_results
    all_tests    = get_all_tests()
    user_results = get_user_results(uid)
    solved_tids  = {r.get("test_id") for r in user_results}

    # Faqat ommaviy testlar + yechgan link testlar
    visible = [
        t for t in all_tests
        if (t.get("visibility") == "public" or
            (t.get("visibility") == "link" and t.get("test_id") in solved_tids))
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

    # Fanlar bo'yicha guruhlash
    cats = {}
    for t in visible:
        c = t.get("category") or "Boshqa"
        if c not in cats:
            cats[c] = {"count": 0, "solved": 0}
        cats[c]["count"] += 1
        if t.get("test_id") in solved_tids:
            cats[c]["solved"] += 1

    # Saralash: eng ko'p testli fan birinchi
    sorted_cats = sorted(cats.items(), key=lambda x: x[1]["count"], reverse=True)

    text = (
        f"📚 <b>TESTLAR — FANLAR BO'YICHA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Jami: {len(visible)} ta test | {len(cats)} ta fan</i>\n\n"
    )

    CAT_ICONS = {
        "Matematika": "📐", "Fizika": "⚛️", "Kimyo": "🧪",
        "Biologiya": "🌱", "Tarix": "📜", "Geografiya": "🌍",
        "Ingliz tili": "🇬🇧", "Rus tili": "🇷🇺", "Ona tili": "📖",
        "Informatika": "💻", "Adabiyot": "📚", "Huquq": "⚖️",
        "Iqtisodiyot": "📈", "Boshqa": "📋",
    }

    b = InlineKeyboardBuilder()
    for cat, info in sorted_cats:
        icon     = CAT_ICONS.get(cat, "📋")
        count    = info["count"]
        solved   = info["solved"]
        prog_txt = f" ✅{solved}/{count}" if solved > 0 else f" {count} ta"

        text += f"{icon} <b>{cat}</b>{prog_txt}\n"
        b.row(InlineKeyboardButton(
            text=f"{icon} {cat} — {count} ta",
            callback_data=f"cat_{cat[:30]}"
        ))

    b.row(
        InlineKeyboardButton(text="🔍 Kod bilan qidirish", callback_data="search_by_code"),
        InlineKeyboardButton(text="🌟 Hammasi",            callback_data="cat_ALL"),
    )
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))

    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


# ══ FAN ICHIDAGI TESTLAR ═══════════════════════════════════════
@router.callback_query(F.data.startswith("cat_"))
async def show_cat_tests(callback: CallbackQuery):
    await callback.answer()
    cat_name = callback.data[4:]
    uid      = callback.from_user.id
    await _show_cat_tests(callback.message, uid, cat_name, page=0, edit=True)

@router.callback_query(F.data.startswith("catp_"))
async def cat_page_cb(callback: CallbackQuery):
    await callback.answer()
    parts    = callback.data[5:].rsplit("_", 1)
    cat_name = parts[0]
    page     = int(parts[1]) if len(parts) > 1 else 0
    await _show_cat_tests(callback.message, callback.from_user.id, cat_name, page, edit=True)


async def _show_cat_tests(msg, uid, cat_name, page=0, edit=False):
    from utils.db import get_user_results
    all_tests    = get_all_tests()
    user_results = get_user_results(uid)
    solved_tids  = {r.get("test_id") for r in user_results}
    solved_map   = {r.get("test_id"): r for r in user_results}

    if cat_name == "ALL":
        tests = [t for t in all_tests
                 if (t.get("visibility") == "public" or
                     (t.get("visibility") == "link" and t.get("test_id") in solved_tids))
                 and not t.get("is_paused")]
        title = "🌟 BARCHA TESTLAR"
    else:
        tests = [t for t in all_tests
                 if t.get("category") == cat_name
                 and (t.get("visibility") == "public" or
                      (t.get("visibility") == "link" and t.get("test_id") in solved_tids))
                 and not t.get("is_paused")]
        title = f"📚 {cat_name.upper()}"

    if not tests:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⬅️ Fanlar", callback_data="back_to_cats"))
        try: await msg.edit_text(f"📭 {title}\n\nTestlar yo'q.", reply_markup=b.as_markup())
        except TelegramBadRequest: pass
        return

    PG    = 6
    total = (len(tests) + PG - 1) // PG
    page  = max(0, min(page, total - 1))
    chunk = tests[page * PG:(page + 1) * PG]

    diff_map = {"easy":"🟢","medium":"🟡","hard":"🔴","expert":"⚡"}

    text = (
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{len(tests)} ta test | Sahifa {page+1}/{total}</i>\n\n"
    )
    b = InlineKeyboardBuilder()

    for t in chunk:
        tid    = t.get("test_id","")
        t_title= t.get("title","Nomsiz")
        d_ico  = diff_map.get(t.get("difficulty",""),"🟡")
        qc     = t.get("question_count", len(t.get("questions",[])))
        sc     = t.get("solve_count",0)
        vis    = "🔗" if t.get("visibility")=="link" else ""

        # Bu user yechganmi?
        if tid in solved_tids:
            r     = solved_map[tid]
            best  = r.get("best_pct", r.get("last_pct",0))
            att   = r.get("attempts",1)
            check = f"✅{best}%×{att}"
        else:
            check = "▶️ Boshlanmagan"

        text += f"{vis}{d_ico} <b>{t_title}</b>\n   📋{qc} savol | 👥{sc} | {check}\n\n"
        b.row(InlineKeyboardButton(
            text=f"{'✅' if tid in solved_tids else '▶️'} {t_title[:25]}",
            callback_data=f"view_test_{tid}"
        ))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"catp_{cat_name}_{page-1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"catp_{cat_name}_{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Fanlar", callback_data="back_to_cats"))
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))

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


# ══ KOD BILAN QIDIRISH ═════════════════════════════════════════
@router.callback_query(F.data == "search_by_code")
async def search_by_code(callback: CallbackQuery):
    await callback.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_cats"))
    try:
        await callback.message.edit_text(
            "🔍 <b>TEST KODI BILAN QIDIRISH</b>\n\n"
            "Test kodini yuboring (masalan: <code>AB12CD34</code>)\n\n"
            "<i>Kodni to'g'ridan yuboring yoki /start KOD ko'rinishida</i>",
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
    uid   = callback.from_user.id
    msg   = callback.message
    cid   = msg.chat.id if msg and msg.chat else uid

    # FSM tozalash
    cur = await state.get_state()
    if cur in (TestSolving.answering.state, TestSolving.text_answer.state):
        await state.clear()

    test = get_test_by_id(tid)
    if not test or not test.get("questions"):
        try:
            lm = await callback.bot.send_message(cid, "⏳ <b>Test yuklanmoqda...</b>")
        except Exception: lm = None
        test = await get_test_full(tid)
        if lm:
            try: await lm.delete()
            except: pass

    if not test:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    qs = test.get("questions", [])
    if not qs:
        return await callback.answer("❌ Savollar yo'q.", show_alert=True)

    via_link = test.get("visibility") == "link"
    await state.set_state(TestSolving.answering)
    await state.set_data({
        "test": test, "qs": qs, "idx": 0, "ans": {},
        "cid": cid, "t0": time.time(), "uid": uid,
        "via_link": via_link,
    })

    try:
        if msg: await msg.delete()
    except Exception: pass

    await _send_inline_question(callback.bot, cid, state)


async def _send_inline_question(bot, cid, state):
    d     = await state.get_data()
    qs    = d["qs"]
    idx   = d["idx"]

    if idx >= len(qs):
        await _finish_inline(bot, cid, state, d)
        return

    q     = qs[idx]
    qtype = q.get("type","multiple_choice")
    qtxt  = q.get("question", q.get("text","Savol"))
    qtxt  = re.sub(r'^\[\d+/\d+\]\s*','', qtxt).strip()
    total = len(qs)

    # Cancel tugmasi
    cancel_btn = InlineKeyboardButton(text="❌ To'xtatish", callback_data="cancel_test")

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
            f"{qtxt}\n\n"
            f"{opt_lines}"
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
        await state.set_state(TestSolving.answering)

    else:
        # Text input
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


async def _finish_inline(bot, cid, state, d):
    from utils.scoring import calculate_score, format_result
    from keyboards.keyboards import result_kb
    from utils.ram_cache import get_daily

    test    = d["test"]
    qs      = d["qs"]
    ans     = d.get("ans",{})
    elapsed = int(time.time() - d.get("t0", time.time()))
    uid     = d.get("uid", cid)
    via_link= d.get("via_link", False)

    scored = calculate_score(qs, ans)
    scored.update({
        "time_spent":    elapsed,
        "passing_score": test.get("passing_score",60),
        "mode":          "inline",
    })
    rid = save_result(uid, test.get("test_id",""), scored, via_link=via_link)
    await state.clear()

    # Reyting
    daily   = get_daily()
    pct     = scored.get("percentage",0)
    tid     = test.get("test_id","")
    all_pct = [
        max(v.get("by_test",{}).get(tid,{}).get("all_pcts",[0]))
        for v in daily.values()
        if v.get("by_test",{}).get(tid,{}).get("attempts",0) > 0
    ]
    all_pct.sort(reverse=True)
    rank     = next((i+1 for i,p in enumerate(all_pct) if p<=pct), len(all_pct))
    rank_txt = f"\n🏅 <b>Reyting: {rank}/{len(all_pct)} o'rin</b>" if len(all_pct)>1 else ""

    await bot.send_message(
        cid,
        format_result(scored, test) + rank_txt,
        reply_markup=result_kb(tid, rid)
    )


# ── Javob handler ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ans_"), StateFilter(TestSolving.answering))
async def answer_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id
    cid = callback.message.chat.id if callback.message and callback.message.chat else uid

    ans_val = callback.data[4:]
    d       = await state.get_data()
    qs      = d.get("qs",[])
    idx     = d.get("idx",0)
    ans     = d.get("ans",{})

    if idx >= len(qs):
        await _finish_inline(callback.bot, cid, state, d)
        return

    q       = qs[idx]
    corr    = q.get("correct","")
    qtype   = q.get("type","multiple_choice")

    if qtype == "true_false":
        user_ans  = "Ha" if ans_val in ("Ha",) else "Yo'q"
        is_c      = user_ans.lower() == str(corr).strip().lower()
    else:
        m1 = re.match(r"^([A-Za-z])", ans_val)
        m2 = re.match(r"^([A-Za-z])", str(corr).strip())
        is_c = (m1 and m2 and m1.group(1).lower()==m2.group(1).lower()) if m1 and m2 else (ans_val.strip().lower()==str(corr).strip().lower())

    ans[str(idx)] = ans_val
    new_idx       = idx + 1
    await state.update_data(ans=ans, idx=new_idx)

    # Natija ko'rsatish
    icon   = "✅" if is_c else "❌"
    expl   = q.get("explanation","") or ""
    if expl in ("Izoh kiritilmagan.","Izoh yo'q","Izoh kiritilmagan"):
        expl = ""
    expl_txt = f"\n💡 <i>{expl[:120]}</i>" if expl else ""
    qtxt = q.get("question",q.get("text",""))[:80]

    # To'g'ri javob chiqarish
    opts      = q.get("options",[])
    corr_text = str(corr)
    if qtype == "multiple_choice" and opts:
        m = re.match(r"^([A-Za-z])", str(corr).strip())
        if m:
            ci = ord(m.group(1).upper()) - ord("A")
            if 0 <= ci < len(opts):
                raw = str(opts[ci])
                mopt = re.match(r"^([A-Za-z])\s*[).]\s*", raw)
                corr_text = f"{m.group(1).upper()}) {raw[mopt.end():].strip() if mopt else raw}"

    try:
        await callback.message.edit_text(
            f"{icon} <b>{'To\'g\'ri!' if is_c else 'Noto\'g\'ri!'}</b>\n"
            f"<i>{qtxt}{'...' if len(q.get('question',q.get('text','')))>80 else ''}</i>\n\n"
            f"✔️ Javob: <b>{corr_text[:60]}</b>{expl_txt}"
        )
    except Exception: pass

    await asyncio.sleep(2.5)

    d_fresh = await state.get_data()
    new_idx2 = d_fresh.get("idx", new_idx)
    qs2      = d_fresh.get("qs", qs)

    try: await callback.message.delete()
    except Exception: pass

    if new_idx2 < len(qs2):
        await _send_inline_question(callback.bot, cid, state)
    else:
        await _finish_inline(callback.bot, cid, state, d_fresh)


@router.callback_query(F.data == "skip_q", StateFilter(TestSolving))
async def skip_q_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    d   = await state.get_data()
    idx = d.get("idx",0)
    ans = d.get("ans",{})
    ans[str(idx)] = None
    new_idx = idx + 1
    await state.update_data(ans=ans, idx=new_idx)
    cid = callback.message.chat.id if callback.message and callback.message.chat else callback.from_user.id
    try: await callback.message.delete()
    except Exception: pass
    qs = d.get("qs",[])
    if new_idx < len(qs):
        await _send_inline_question(callback.bot, cid, state)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(callback.bot, cid, state, d_fresh)


@router.callback_query(F.data == "cancel_test", StateFilter(TestSolving))
async def cancel_test_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("❌ To'xtatildi")
    uid = callback.from_user.id
    try: await callback.message.delete()
    except Exception: pass
    await callback.bot.send_message(
        uid, "❌ Test to'xtatildi.",
        reply_markup=main_kb(uid)
    )


# ── Matn javob (faqat text_answer state da) ──────────────────

@router.message(StateFilter(TestSolving.text_answer))
async def text_answer_handler(message: Message, state: FSMContext):
    d   = await state.get_data()
    idx = d.get("idx",0)
    qs  = d.get("qs",[])
    if idx >= len(qs): return
    ans             = d.get("ans",{})
    ans[str(idx)]   = message.text.strip()
    new_idx         = idx + 1
    await state.update_data(ans=ans, idx=new_idx)
    cid = message.chat.id
    await state.set_state(TestSolving.answering)
    if new_idx < len(qs):
        await _send_inline_question(message.bot, cid, state)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(message.bot, cid, state, d_fresh)
