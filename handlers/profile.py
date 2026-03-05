"""👤 PROFIL, NATIJALAR, TAHLIL"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from utils.db import (get_user, get_my_tests, get_user_results,
                      get_analysis, get_test, get_test_full, get_test_stats_for_user)
from utils.ram_cache import get_test_by_id
from keyboards.keyboards import main_kb, analysis_kb

log    = logging.getLogger(__name__)
router = Router()
PAGE_SIZE_RESULTS = 8
PAGE_SIZE_TESTS   = 5


# ══ 1. PROFIL ══════════════════════════════════════════

@router.message(F.text == "👤 Profil")
async def profile_msg(message: Message):
    await _show_profile(message, message.from_user.id)

@router.callback_query(F.data == "profile")
async def profile_cb(callback: CallbackQuery):
    await callback.answer()
    await _show_profile(callback.message, callback.from_user.id, edit=True)

async def _show_profile(msg, uid, edit=False):
    user = get_user(uid)
    if not user:
        text = "❌ Profil topilmadi. /start ni bosing."
        await (msg.edit_text(text) if edit else msg.answer(text))
        return

    role_map = {"admin": "👑 Admin", "teacher": "👨‍🏫 O'qituvchi", "user": "🎓 O'quvchi"}
    role  = role_map.get(user.get("role", "user"), "🎓 O'quvchi")
    avg   = round(user.get("avg_score", 0), 1)
    total = user.get("total_tests", 0)

    badges = []
    if total >= 1:  badges.append("🥉 Boshliqchi")
    if total >= 10: badges.append("🥈 Tajribali")
    if total >= 50: badges.append("🥇 Ustoz")
    if avg >= 90:   badges.append("🌟 Mukammal")
    if avg >= 80:   badges.append("🔥 A'lochi")

    text = (
        f"👤 <b>SHAXSIY PROFIL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        "👤 Ism: <b>" + str(user.get("name", "Noma'lum")) + "</b>\n"
        f"🎭 Rol: <b>{role}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Yechilgan testlar: <b>{total} ta</b>\n"
        f"📊 O'rtacha natija: <b>{avg}%</b>\n"
        "🏅 Yutuqlar: " + ("  ".join(badges) if badges else "Hali yo'q") + "\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📋 Natijalarim", callback_data="results_p0"))
    b.row(InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


# ══ 2. NATIJALAR ═══════════════════════════════════════

@router.message(F.text == "📊 Natijalarim")
async def results_msg(message: Message):
    await _show_results(message, message.from_user.id, page=0)

@router.callback_query(F.data.startswith("results_p"))
async def results_page_cb(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data[9:])
    await _show_results(callback.message, callback.from_user.id, page=page, edit=True)

async def _show_results(msg, uid, page=0, edit=False):
    all_results = get_user_results(uid)

    if not all_results:
        text = (
            "📭 <b>NATIJALAR</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Siz hali hech qanday test ishlamagansiz.\n"
            "Testlar bo'limidan boshlang! 🚀"
        )
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="📚 Testlarga o'tish", callback_data="go_tests"))
        b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
        try:
            if edit: await msg.edit_text(text, reply_markup=b.as_markup())
            else:    await msg.answer(text, reply_markup=b.as_markup())
        except TelegramBadRequest:
            await msg.answer(text, reply_markup=b.as_markup())
        return

    total_pages = (len(all_results) + PAGE_SIZE_RESULTS - 1) // PAGE_SIZE_RESULTS
    page  = max(0, min(page, total_pages - 1))
    chunk = all_results[page * PAGE_SIZE_RESULTS:(page + 1) * PAGE_SIZE_RESULTS]

    text = (
        f"📋 <b>NATIJALARIM</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Sahifa {page+1}/{total_pages} | Jami: {len(all_results)} ta test</i>\n\n"
    )
    b = InlineKeyboardBuilder()

    for res in chunk:
        tid   = res.get("test_id", "")
        meta  = get_test_by_id(tid)
        title = meta.get("title", "Noma'lum")[:22] if meta else "Noma'lum test"
        icon  = "✅" if res.get("passed") else "❌"
        pct   = res.get("percentage", 0)
        att   = res.get("attempts", 1)
        best  = res.get("best_score", pct)
        dt    = str(res.get("completed_at", ""))[:10]
        rid   = res.get("result_id", "")

        text += (
            f"{icon} <b>{title}</b>\n"
            f"   📊 Oxirgi: {pct}% | ⭐ Eng yaxshi: {best}%\n"
            f"   🔄 Urinishlar: {att} | 📅 {dt}\n\n"
        )
        b.row(InlineKeyboardButton(
            text=f"{icon} {title[:18]} — {pct}%",
            callback_data=f"res_back_{rid}"
        ))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Oldingi", callback_data=f"results_p{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Keyingi ▶️", callback_data=f"results_p{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))

    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


# ══ 3. NATIJA KARTOCHKASI ══════════════════════════════
# res_back_{rid} — tahlildan va natijalar listidan keladi

@router.callback_query(F.data.startswith("res_back_"))
async def result_back_cb(callback: CallbackQuery):
    await callback.answer()
    rid = callback.data[9:]
    await _show_result_card(callback, rid)

# Eski callback_data bilan moslik (result_kb dan keladi)
@router.callback_query(F.data.startswith("res_detail_"))
async def result_detail(callback: CallbackQuery):
    await callback.answer()
    rid = callback.data[11:]
    await _show_result_card(callback, rid)

async def _show_result_card(callback, rid):
    uid     = callback.from_user.id
    results = get_user_results(uid)
    res     = next((r for r in results if r.get("result_id") == rid), None)
    if not res:
        return await callback.answer("❌ Natija topilmadi.", show_alert=True)

    tid   = res.get("test_id", "")
    meta  = get_test_by_id(tid)
    title = meta.get("title", "Noma'lum") if meta else "O'chirilgan test"
    cat   = meta.get("category", "") if meta else ""

    stats = get_test_stats_for_user(uid, tid)
    att   = stats.get("attempts", res.get("attempts", 1))
    avg_s = stats.get("avg_score", res.get("avg_score", res.get("percentage", 0)))
    best  = stats.get("best_score", res.get("best_score", res.get("percentage", 0)))

    pct    = res.get("percentage", 0)
    passed = res.get("passed", pct >= 60)
    dt_str = str(res.get("completed_at", ""))[:16]

    text = (
        f"{'✅' if passed else '❌'} <b>TEST NATIJASI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 <b>{title}</b>\n"
        f"📁 Fan: {cat}\n"
        f"📅 Oxirgi yechilgan: {dt_str}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Oxirgi natija: <b>{pct}%</b>\n"
        f"⭐ Eng yaxshi natija: <b>{best}%</b>\n"
        f"📈 O'rtacha natija: <b>{avg_s}%</b>\n"
        f"🔄 Jami urinishlar: <b>{att} marta</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{'🎉 MUVAFFAQIYATLI!' if passed else '❌ YIQILDINGIZ'}"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔍 Batafsil tahlil ➡️", callback_data=f"analysis_{rid}_0"))
    if meta:
        b.row(
            InlineKeyboardButton(text="🔄 Qaytadan",   callback_data=f"start_test_{tid}"),
            InlineKeyboardButton(text="📊 Poll rejim", callback_data=f"start_poll_{tid}"),
        )
    b.row(InlineKeyboardButton(text="⬅️ Natijalar", callback_data="results_p0"))
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))

    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=b.as_markup())


# ══ 4. BATAFSIL TAHLIL ═════════════════════════════════

@router.callback_query(F.data.startswith("analysis_"))
async def analysis_handler(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data[9:].rsplit("_", 1)
    rid   = parts[0]
    page  = int(parts[1]) if len(parts) > 1 else 0
    await _show_analysis(callback, rid, page)

async def _show_analysis(callback, rid, page):
    uid      = callback.from_user.id
    detailed = get_analysis(uid, rid)

    if not detailed:
        parts = rid.split("_", 1)
        if len(parts) == 2:
            tid  = parts[1]
            full = await get_test_full(tid)
            if full:
                detailed = get_analysis(uid, rid)

    if not detailed:
        return await callback.answer(
            "❌ Tahlil topilmadi. Testni qaytadan yeching.", show_alert=True
        )

    results = get_user_results(uid)
    res     = next((r for r in results if r.get("result_id") == rid), None)
    tid     = res.get("test_id", "") if res else rid.split("_", 1)[-1]

    test  = await get_test_full(tid) if tid else {}
    qs    = test.get("questions", []) if test else []
    title = test.get("title", "Test") if test else "Test"

    PG      = 5
    total_p = (len(detailed) + PG - 1) // PG
    page    = max(0, min(page, total_p - 1))
    chunk   = detailed[page * PG:(page + 1) * PG]
    corr    = sum(1 for d in detailed if d.get("is_correct"))

    text = (
        f"📊 <b>{title.upper()} — TAHLIL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ {corr}/{len(detailed)} to'g'ri | "
        f"<i>Sahifa {page+1}/{total_p}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for d in chunk:
        i     = d.get("question_index", 0)
        is_c  = d.get("is_correct", False)
        u_ans = d.get("user_answer") or "Belgilanmagan"
        c_ans = d.get("correct_answer", "?")
        q_obj = qs[i] if i < len(qs) else {}
        q_txt = q_obj.get("question", q_obj.get("text", f"{i+1}-savol"))
        expl  = q_obj.get("explanation", "")
        pts   = d.get("earned_points", 0)
        max_p = d.get("max_points", 1)

        text += (
            f"{'✅' if is_c else '❌'} <b>Savol {i+1}</b> [{pts}/{max_p}]\n"
            f"<i>{q_txt[:100]}{'...' if len(q_txt)>100 else ''}</i>\n"
        )
        if not is_c:
            text += (
                f"  👤 Siz: <code>{str(u_ans)[:50]}</code>\n"
                f"  🎯 To'g'ri: <code>{str(c_ans)[:50]}</code>\n"
            )
        else:
            text += f"  ✔️ <code>{str(c_ans)[:50]}</code>\n"
        if expl and expl not in ("Izoh kiritilmagan.", "Izoh yo'q", ""):
            text += f"  💡 <i>{expl[:80]}</i>\n"
        text += "\n"

    try:
        await callback.message.edit_text(text, reply_markup=analysis_kb(rid, page, total_p))
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=analysis_kb(rid, page, total_p))


# ══ 5. MENING TESTLARIM ════════════════════════════════

@router.message(F.text == "🗂 Mening testlarim")
async def my_tests_handler(message: Message):
    await _show_my_tests(message, message.from_user.id, page=0)

@router.callback_query(F.data.startswith("mytests_p"))
async def my_tests_page(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data[9:])
    await _show_my_tests(callback.message, callback.from_user.id, page=page, edit=True)

async def _show_my_tests(msg, uid, page=0, edit=False):
    tests = get_my_tests(uid)
    if not tests:
        text = (
            "📭 <b>MENING TESTLARIM</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Siz hali test yaratmagansiz.\n"
            "➕ Test Yaratish bo'limidan boshlang!"
        )
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
        try:
            if edit: await msg.edit_text(text, reply_markup=b.as_markup())
            else:    await msg.answer(text, reply_markup=b.as_markup())
        except TelegramBadRequest:
            await msg.answer(text, reply_markup=b.as_markup())
        return

    total_pages = (len(tests) + PAGE_SIZE_TESTS - 1) // PAGE_SIZE_TESTS
    page  = max(0, min(page, total_pages - 1))
    chunk = tests[page * PAGE_SIZE_TESTS:(page + 1) * PAGE_SIZE_TESTS]

    text = (
        f"🗂 <b>MENING TESTLARIM</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Sahifa {page+1}/{total_pages} | Jami: {len(tests)} ta</i>\n\n"
    )
    b = InlineKeyboardBuilder()

    for t in chunk:
        tid   = t.get("test_id", "")
        title = t.get("title", "Nomsiz")
        cat   = t.get("category", "")
        vis   = {"public": "🌍", "link": "🔗", "private": "🔒"}.get(t.get("visibility"), "")
        sc    = t.get("solve_count", 0)
        avg   = round(t.get("avg_score", 0), 1)
        qc    = t.get("question_count", len(t.get("questions", [])))

        text += (
            f"{vis} <b>{title}</b> <code>[{tid}]</code>\n"
            f"   📁 {cat} | 📋 {qc} savol | 👁 {sc} marta | ⭐ {avg}%\n\n"
        )
        b.row(
            InlineKeyboardButton(text=f"🔍 {title[:16]}", callback_data=f"mytest_view_{tid}"),
            InlineKeyboardButton(text="📤 Ulash",         callback_data=f"share_test_{tid}"),
            InlineKeyboardButton(text="📄 TXT",           callback_data=f"mytest_txt_{tid}"),
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Oldingi", callback_data=f"mytests_p{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Keyingi ▶️", callback_data=f"mytests_p{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))

    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("mytest_view_"))
async def my_test_view(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[12:]
    test = get_test_by_id(tid)
    if not test:
        return await callback.message.answer("❌ Test topilmadi.")

    qc   = test.get("question_count", len(test.get("questions", [])))
    vis  = {"public": "🌍 Ommaviy", "link": "🔗 Ssilka", "private": "🔒 Shaxsiy"}.get(
        test.get("visibility"), "")
    diff = {"easy": "🟢 Oson", "medium": "🟡 O'rtacha",
            "hard": "🔴 Qiyin", "expert": "⚡ Ekspert"}.get(test.get("difficulty", ""), "")

    text = (
        f"🔍 <b>TEST MA'LUMOTLARI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 <b>{test.get('title')}</b>\n"
        f"📁 Fan: {test.get('category', '')}\n"
        f"📊 Qiyinlik: {diff}\n"
        f"📋 Savollar: <b>{qc} ta</b>\n"
        f"🔒 Ko'rinish: {vis}\n"
        f"👁 Ishlangan: <b>{test.get('solve_count', 0)} marta</b>\n"
        f"⭐ O'rtacha: <b>{round(test.get('avg_score', 0), 1)}%</b>\n"
        f"🆔 Kod: <code>{tid}</code>"
    )
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Inline test", callback_data=f"start_test_{tid}"),
        InlineKeyboardButton(text="📊 Poll test",   callback_data=f"start_poll_{tid}"),
    )
    b.row(
        InlineKeyboardButton(text="📤 Ulashish",   callback_data=f"share_test_{tid}"),
        InlineKeyboardButton(text="📄 TXT yuklab", callback_data=f"mytest_txt_{tid}"),
    )
    b.row(
        InlineKeyboardButton(text="🏆 Reyting", callback_data=f"lb_test_{tid}"),
        InlineKeyboardButton(text="⬅️ Orqaga",  callback_data="mytests_p0"),
    )
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("mytest_txt_"))
async def my_test_to_txt(callback: CallbackQuery):
    await callback.answer("⏳ TXT tayyorlanmoqda...")
    tid  = callback.data[11:]
    test = await get_test_full(tid)
    if not test:
        test = get_test_by_id(tid)
    if not test:
        return await callback.message.answer("❌ Test topilmadi.")

    txt = _test_to_txt(test)
    doc = BufferedInputFile(txt.encode("utf-8"), filename=f"{test.get('title', tid)}.txt")
    await callback.message.answer_document(
        doc,
        caption=(
            f"📄 <b>{test.get('title')}</b> — TXT format\n"
            f"📋 {len(test.get('questions', []))} ta savol\n"
            f"🆔 Kod: <code>{tid}</code>"
        )
    )


@router.callback_query(F.data.startswith("share_test_"))
async def share_test(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[11:]
    test = get_test_by_id(tid)
    if not test:
        return await callback.message.answer("❌ Test topilmadi.")

    bot_uname = (await callback.bot.me()).username
    link = f"https://t.me/{bot_uname}?start={tid}"
    qc   = test.get("question_count", len(test.get("questions", [])))

    text = (
        f"📤 <b>TEST ULASHISH</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 <b>{test.get('title')}</b>\n"
        f"📁 Fan: {test.get('category', '')}\n"
        f"📋 Savollar: {qc} ta\n\n"
        f"🔑 Kod: <code>{tid}</code>\n"
        f"🔗 Ssilka:\n<code>{link}</code>\n\n"
        f"<i>💡 Inline orqali guruhga yuboring:</i>"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📤 Guruhga yuborish", switch_inline_query=f"test_{tid}"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"mytest_view_{tid}"))
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=b.as_markup())


def _test_to_txt(test):
    import re
    lines = [
        f"# {test.get('title', 'Test')}",
        f"# Fan: {test.get('category', '')}",
        f"# Qiyinlik: {test.get('difficulty', '')}",
        f"# O'tish foizi: {test.get('passing_score', 60)}%",
        f"# Kod: {test.get('test_id', '')}",
        ""
    ]
    for i, q in enumerate(test.get("questions", []), 1):
        t    = q.get("type", "multiple_choice")
        lines.append(f"TYPE: {t}")
        lines.append(f"{i}. {q.get('question', q.get('text', ''))}")
        opts = q.get("options", [])
        corr = q.get("correct", "")
        if t in ("multiple_choice", "multi_select"):
            for opt in opts:
                opt_str = str(opt)
                m1 = re.match(r"^([A-Za-z])", opt_str.strip())
                m2 = re.match(r"^([A-Za-z])", str(corr).strip())
                is_c = (m1 and m2 and m1.group(1).lower() == m2.group(1).lower()
                        ) if m1 and m2 else opt_str.strip() == str(corr).strip()
                lines.append(f"{'===' if is_c else ''}{opt_str}")
        elif t == "true_false":
            lines.append(f"Javob: {'Ha' if 'Ha' in str(corr) else 'Yoq'}")
        else:
            lines.append(f"Javob: {corr}")
            acc = q.get("accepted_answers", [])
            if acc: lines.append(f"Qabul: {', '.join(str(a) for a in acc)}")
        expl = q.get("explanation", "")
        if expl and expl not in ("Izoh kiritilmagan.", "Izoh yo'q", ""):
            lines.append(f"Izoh: {expl}")
        lines.append("")
    return "\n".join(lines)
