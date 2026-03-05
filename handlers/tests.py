"""📚 TESTLAR KATALOGI"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from utils.db import get_all_tests, get_test_full, get_user_results
from utils.ram_cache import get_test_by_id, is_test_paused
from keyboards.keyboards import main_kb, test_info_simple_kb
from config import SUBJECTS

log    = logging.getLogger(__name__)
router = Router()
PAGE   = 6


# ── Test kodi yuborilganda ─────────────────────────────────────
@router.message(F.text.regexp(r'^[A-Z0-9]{6,10}$'))
async def test_code_direct(message: Message, state: FSMContext):
    tid  = message.text.strip().upper()
    test = get_test_by_id(tid)
    if not test:
        test = await get_test_full(tid)
    if not test:
        return
    uid = message.from_user.id

    # Link testga to'g'ridan kirish — ruxsat yo'q
    if test.get("visibility") == "link":
        results  = get_user_results(uid)
        solved   = {r.get("test_id") for r in results}
        if tid not in solved:
            return  # Kod bilan link testni yechib bo'lmaydi

    from handlers.start import _send_test_card
    await _send_test_card(message, test, tid, viewer_uid=uid)


# ── Katalog ────────────────────────────────────────────────────
@router.message(F.text == "📚 Testlar")
async def tests_list(message: Message):
    await _catalog(message, uid=message.from_user.id, page=0)

@router.callback_query(F.data == "go_tests")
async def go_tests_cb(callback: CallbackQuery):
    await callback.answer()
    await show_catalog(callback)

async def show_catalog(callback: CallbackQuery, page=0):
    await _catalog(callback.message, uid=callback.from_user.id, page=page, edit=True)

@router.callback_query(F.data.startswith("catalog_p"))
async def catalog_page(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data[9:])
    await _catalog(callback.message, uid=callback.from_user.id, page=page, edit=True)

@router.callback_query(F.data.startswith("cat_filter_"))
async def cat_filter_cb(callback: CallbackQuery):
    await callback.answer()
    cat = callback.data[11:]
    if cat == "all":
        await _catalog(callback.message, uid=callback.from_user.id, page=0, edit=True)
    else:
        await _catalog(callback.message, uid=callback.from_user.id, page=0, edit=True, cat_filter=cat)

@router.callback_query(F.data == "cat_filter")
async def cat_filter_menu(callback: CallbackQuery):
    await callback.answer()
    tests = get_all_tests()
    cats  = list({t.get("category","Boshqa") for t in tests if t.get("visibility") == "public"})
    cats.sort()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🌐 Barchasi", callback_data="cat_filter_all"))
    for c in cats:
        count = sum(1 for t in tests if t.get("category") == c and t.get("visibility") == "public")
        b.add(InlineKeyboardButton(text=f"{c} ({count})", callback_data=f"cat_filter_{c}"))
    b.adjust(2)
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="go_tests"))
    try:
        await callback.message.edit_text("🗂 <b>KATEGORIYALAR</b>\n\nBirini tanlang:", reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer("🗂 Kategoriyalar:", reply_markup=b.as_markup())

async def _catalog(msg, uid, page=0, edit=False, cat_filter=None):
    # Faqat ommaviy testlar
    tests = [t for t in get_all_tests()
             if not t.get("is_paused") and
             t.get("visibility") == "public"]
    if cat_filter and cat_filter != "all":
        tests = [t for t in tests if t.get("category") == cat_filter]

    # Link testlar — faqat yechganlarga ko'rinsin
    user_results = get_user_results(uid)
    solved_tids  = {r.get("test_id") for r in user_results}
    link_tests   = [t for t in get_all_tests()
                    if t.get("visibility") == "link"
                    and t.get("test_id") in solved_tids
                    and not t.get("is_paused")]

    # Kategoriyalar bo'yicha guruhlash
    if not cat_filter:
        # Kategoriyalar bo'yicha ajratib ko'rsatish
        all_tests = tests
    else:
        all_tests = tests

    if link_tests and not cat_filter:
        # Link testlar alohida bo'lim sifatida oxirida
        pass

    if not tests and not link_tests:
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

    # Kategoriya filtri bo'lsa oddiy list, bo'lmasa kategoriyalarga bo'lib
    if cat_filter and cat_filter != "all":
        display_tests = tests
        section_title = f"📁 {cat_filter}"
    else:
        display_tests = tests
        section_title = "📚 TESTLAR KATALOGI"

    total_pages = (len(display_tests) + PAGE - 1) // PAGE
    if total_pages == 0: total_pages = 1
    page  = max(0, min(page, total_pages - 1))
    chunk = display_tests[page * PAGE:(page + 1) * PAGE]

    diff_map = {"easy":"🟢","medium":"🟡","hard":"🔴","expert":"⚡"}
    total_public = len(display_tests)
    link_count   = len(link_tests)

    text = (
        f"<b>{section_title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Sahifa {page+1}/{total_pages} | Jami: {total_public} ta test"
        + (f" | 🔗 {link_count} ta link test" if link_count and not cat_filter else "")
        + "</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for t in chunk:
        tid   = t.get("test_id","")
        title = t.get("title","Nomsiz")
        cat   = t.get("category","")
        d_ico = diff_map.get(t.get("difficulty",""),"🟡")
        sc    = t.get("solve_count",0)
        qc    = t.get("question_count", len(t.get("questions",[])))
        avg   = round(t.get("avg_score",0),1)
        text += f"{d_ico} <b>{title}</b> [{tid}]\n📁{cat} | 📋{qc}s | 👥{sc} | ⭐{avg}%\n\n"
        b.row(InlineKeyboardButton(text=f"▶️ {title[:25]}", callback_data=f"view_test_{tid}"))

    # Link testlar bo'limi (agar kategoriya filtri yo'q bo'lsa)
    if link_tests and not cat_filter and page == 0:
        text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        text += "🔗 <b>LINKLAR</b> (siz yechgan)\n\n"
        for t in link_tests[:3]:
            tid   = t.get("test_id","")
            title = t.get("title","Nomsiz")
            sc    = t.get("solve_count",0)
            text += f"🔗 <b>{title}</b> [{tid}] | 👥{sc}\n"
            b.row(InlineKeyboardButton(text=f"🔗 {title[:25]}", callback_data=f"view_test_{tid}"))
        if len(link_tests) > 3:
            text += f"<i>...va yana {len(link_tests)-3} ta</i>\n"
        text += "\n"

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"catalog_p{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"catalog_p{page+1}"))
    if nav: b.row(*nav)
    b.row(
        InlineKeyboardButton(text="🔍 Qidirish",   callback_data="search_tests"),
        InlineKeyboardButton(text="🗂 Kategoriya", callback_data="cat_filter"),
    )
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
    test = get_test_by_id(tid)
    if not test:
        test = await get_test_full(tid)
    if not test:
        try: await callback.message.edit_text("❌ Test topilmadi.")
        except: pass
        return
    from handlers.start import _send_test_card
    await _send_test_card(callback, test, tid, viewer_uid=uid, edit=True)

@router.callback_query(F.data.startswith("start_test_"))
async def start_inline_test(callback: CallbackQuery, state: FSMContext):
    """Inline test boshlash"""
    from utils.ram_cache import is_test_paused
    tid = callback.data[11:]
    if is_test_paused(tid):
        return await callback.answer("⚠️ Bu test vaqtincha to'xtatilgan!", show_alert=True)

    await callback.answer()
    uid  = callback.from_user.id
    msg  = callback.message
    chat = msg.chat if msg else None
    cid  = chat.id if chat else uid

    test = get_test_by_id(tid)
    if not test or not test.get("questions"):
        try:
            lm = await callback.bot.send_message(cid, "⏳ <b>Test yuklanmoqda...</b>")
        except Exception: lm = None
        test = await get_test_full(tid)
        if lm:
            try: await lm.delete()
            except Exception: pass

    if not test:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    qs = test.get("questions", [])
    if not qs:
        return await callback.answer("❌ Bu testda savollar yo'q.", show_alert=True)

    via_link = test.get("visibility") == "link"

    from utils.states import TestSolving, PollTest
    cur = await state.get_state()
    if cur in (TestSolving.answering.state, TestSolving.text_answer.state,
               PollTest.active.state, PollTest.paused.state):
        await state.clear()

    import time
    await state.set_state(TestSolving.answering)
    await state.set_data({
        "test": test, "qs": qs, "idx": 0, "ans": {},
        "cid": cid, "t0": time.time(), "uid": uid,
        "via_link": via_link,
    })

    try:
        if msg: await msg.delete()
    except Exception: pass

    from keyboards.keyboards import answer_kb
    await _send_inline_question(callback.bot, cid, state)


async def _send_inline_question(bot, cid, state):
    import re, asyncio
    from keyboards.keyboards import answer_kb, next_kb
    from utils.states import TestSolving

    d   = await state.get_data()
    qs  = d["qs"]
    idx = d["idx"]

    if idx >= len(qs):
        await _finish_inline(bot, cid, state, d)
        return

    q     = qs[idx]
    qtype = q.get("type","multiple_choice")
    qtxt  = q.get("question", q.get("text","Savol"))
    qtxt  = re.sub(r'^\[\d+/\d+\]\s*','',qtxt).strip()

    if qtype in ("multiple_choice","multi_select"):
        opts = q.get("options",[])
        letters = []
        for opt in opts:
            ot = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
            m  = re.match(r"^([A-Za-z])",str(opt).strip())
            l  = m.group(1).upper() if m else chr(65+len(letters))
            letters.append(l)

        text = (
            f"📝 <b>Savol {idx+1}/{len(qs)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{qtxt}\n\n"
        )
        for i, opt in enumerate(opts):
            ot = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
            l  = letters[i] if i < len(letters) else chr(65+i)
            text += f"<b>{l})</b> {ot}\n"

        await bot.send_message(cid, text, reply_markup=answer_kb(letters))
        await state.set_state(TestSolving.answering)

    elif qtype == "true_false":
        text = (
            f"✅❌ <b>Savol {idx+1}/{len(qs)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{qtxt}"
        )
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="✅ Ha",  callback_data="ans_Ha"),
            InlineKeyboardButton(text="❌ Yo'q",callback_data="ans_Yoq"),
        )
        await bot.send_message(cid, text, reply_markup=b.as_markup())
        await state.set_state(TestSolving.answering)

    else:
        text = (
            f"✏️ <b>Savol {idx+1}/{len(qs)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{qtxt}\n\n"
            f"<i>Javobingizni yozing:</i>"
        )
        await bot.send_message(cid, text)
        await state.set_state(TestSolving.text_answer)


async def _finish_inline(bot, cid, state, d):
    import time
    from utils.db import save_result
    from utils.scoring import calculate_score, format_result
    from keyboards.keyboards import result_kb

    test    = d["test"]
    qs      = d["qs"]
    ans     = d.get("ans",{})
    elapsed = int(time.time() - d.get("t0",time.time()))
    uid     = d.get("uid", cid)
    via_link= d.get("via_link",False)

    scored = calculate_score(qs, ans)
    scored.update({
        "time_spent":    elapsed,
        "passing_score": test.get("passing_score",60),
        "mode":          "inline",
    })
    rid = save_result(uid, test.get("test_id",""), scored, via_link=via_link)
    await state.clear()
    await bot.send_message(
        cid,
        format_result(scored, test),
        reply_markup=result_kb(test.get("test_id",""), rid)
    )


# ── Inline test javob handler ─────────────────────────────────

@router.callback_query(F.data.startswith("ans_"))
async def answer_cb(callback: CallbackQuery, state: FSMContext):
    from utils.states import TestSolving
    cur = await state.get_state()
    if cur != TestSolving.answering.state:
        return await callback.answer()
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
    import re
    corr    = q.get("correct","")
    qtype   = q.get("type","multiple_choice")

    if qtype == "true_false":
        user_ans = "Ha" if ans_val in ("Ha","Ha") else "Yo'q"
        corr_norm = str(corr).strip().lower()
        is_c  = (user_ans.lower() == corr_norm)
    else:
        m1 = re.match(r"^([A-Za-z])", ans_val)
        m2 = re.match(r"^([A-Za-z])", str(corr).strip())
        is_c = (m1 and m2 and m1.group(1).lower()==m2.group(1).lower()) if m1 and m2 else False

    ans[str(idx)] = ans_val
    new_idx = idx + 1
    await state.update_data(ans=ans, idx=new_idx)

    icon    = "✅" if is_c else "❌"
    expl    = q.get("explanation","") or ""
    if expl in ("Izoh kiritilmagan.","Izoh yo'q","Izoh kiritilmagan"):
        expl = ""
    expl_txt = f"\n\n💡 <i>{expl[:100]}</i>" if expl else ""
    qtxt     = q.get("question",q.get("text",""))

    try:
        await callback.message.edit_text(
            f"{icon} <b>{'To\'g\'ri!' if is_c else 'Noto\'g\'ri!'}</b>\n\n"
            f"<i>{qtxt[:80]}</i>\n"
            f"✔️ Javob: <code>{corr}</code>{expl_txt}\n\n"
            f"<i>Keyingi savol yuklanmoqda...</i>"
        )
    except Exception: pass

    import asyncio
    await asyncio.sleep(2.5)

    if new_idx < len(qs):
        try: await callback.message.delete()
        except Exception: pass
        await _send_inline_question(callback.bot, cid, state)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(callback.bot, cid, state, d_fresh)


@router.callback_query(F.data == "next_q")
async def next_q_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    cid = callback.message.chat.id if callback.message and callback.message.chat else callback.from_user.id
    d   = await state.get_data()
    if not d: return
    new_idx = d.get("idx",0) + 1
    await state.update_data(idx=new_idx, ans={**d.get("ans",{}), str(d.get("idx",0)): None})
    try: await callback.message.delete()
    except Exception: pass
    qs = d.get("qs",[])
    if new_idx < len(qs):
        await _send_inline_question(callback.bot, cid, state)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(callback.bot, cid, state, d_fresh)

@router.callback_query(F.data == "cancel_test")
async def cancel_test_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("❌ Test to'xtatildi")
    uid = callback.from_user.id
    try: await callback.message.delete()
    except Exception: pass
    from keyboards.keyboards import main_kb
    await callback.bot.send_message(uid, "❌ Test to'xtatildi.", reply_markup=main_kb(uid))

@router.message(F.text, flags={"priority":1})
async def text_answer_handler(message: Message, state: FSMContext):
    from utils.states import TestSolving
    cur = await state.get_state()
    if cur != TestSolving.text_answer.state:
        return
    d   = await state.get_data()
    idx = d.get("idx",0)
    qs  = d.get("qs",[])
    if idx >= len(qs): return
    ans = d.get("ans",{})
    ans[str(idx)] = message.text.strip()
    new_idx = idx + 1
    await state.update_data(ans=ans, idx=new_idx)
    cid = message.chat.id
    if new_idx < len(qs):
        await _send_inline_question(message.bot, cid, state)
    else:
        d_fresh = await state.get_data()
        await _finish_inline(message.bot, cid, state, d_fresh)
