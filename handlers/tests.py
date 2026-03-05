"""📚 TESTLAR — Katalog + Inline test (private: darhol javob; guruh: vaqt tugaganda)"""
import time, asyncio, logging, re
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from utils.db import get_user, get_test, save_result
from utils.ram_cache import get_tests, get_test_by_id, get_daily
from utils.states import TestSolving
from utils.scoring import calculate_score, format_result
from keyboards.keyboards import main_kb, result_kb, answer_kb, next_kb, next_q_kb
from handlers.start import _send_test_card

log     = logging.getLogger(__name__)
router  = Router()
LETTERS = ["A","B","C","D","E","F","G","H","I","J"]
BAR_LEN = 35   # Progress bar uzunligi

# Guruh inline sessiyalari: {chat_id: {tid, qs, idx, answers:{uid:ans}, answered_uids, msg_id, task}}
_group_inline: dict = {}
# Private avto-o'tish tasklari: {(chat_id, user_id): asyncio.Task}
_auto_tasks: dict = {}


# ═══════════════════════════════════════════════════════════
# 1. KATALOG
# ═══════════════════════════════════════════════════════════

async def show_catalog(event):
    tests = [t for t in get_tests()
             if t.get("visibility") == "public" and t.get("is_active", True)]
    text  = (
        "<b>📚 TESTLAR BO'LIMI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>Test kodini yuboring yoki fanni tanlang:</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    if not tests:
        text += "📭 Hozircha ommaviy testlar mavjud emas."
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
async def tests_menu(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return
    uid  = message.from_user.id
    user = get_user(uid)
    if user and user.get("is_blocked"):
        return await message.answer("🚫 Siz bloklangansiz.")
    await state.clear()
    await show_catalog(message)


@router.callback_query(F.data.startswith("cat_"))
async def show_category(callback: CallbackQuery):
    await callback.answer()
    cat   = callback.data[4:]
    tests = [t for t in get_tests()
             if str(t.get("category","")).startswith(cat)
             and t.get("visibility") == "public"
             and t.get("is_active", True)]
    if not tests:
        return await callback.message.edit_text("❌ Bu fanda testlar topilmadi.")
    b = InlineKeyboardBuilder()
    for t in tests:
        b.row(InlineKeyboardButton(
            text=f"📝 {t.get('title','Nomsiz')}  ({t.get('solve_count',0)} marta)",
            callback_data=f"view_test_{t.get('test_id')}"
        ))
    b.row(InlineKeyboardButton(text="⬅️ Ortga", callback_data="back_to_cats"))
    try:
        await callback.message.edit_text(
            f"<b>📁 {cat.upper()}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Jami: {len(tests)} ta test",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "back_to_cats")
async def back_to_cats(callback: CallbackQuery):
    await callback.answer()
    await show_catalog(callback)


@router.callback_query(F.data.startswith("view_test_"))
async def view_test(callback: CallbackQuery):
    await callback.answer()
    tid  = callback.data[10:]
    test = get_test_by_id(tid)
    if not test:
        return await callback.message.answer("❌ Test topilmadi.")
    await _send_test_card(callback, test, tid)


class _IsTestCode:
    def __call__(self, msg: Message) -> bool:
        t = (msg.text or "").strip()
        return (bool(t) and "/" not in t and "\n" not in t
                and " " not in t and len(t) in range(6, 21))

_test_code_filter = _IsTestCode()


@router.message(StateFilter(None), F.text, _test_code_filter)
async def direct_code_handler(message: Message):
    if message.chat.type != "private":
        return
    tid  = (message.text or "").strip().upper()
    test = get_test_by_id(tid)
    if not test:
        return
    await _send_test_card(message, test, tid)


# ═══════════════════════════════════════════════════════════
# 2. INLINE TEST BOSHLASH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("start_test_"))
async def start_inline_test(callback: CallbackQuery, state: FSMContext):
    uid  = callback.from_user.id
    user = get_user(uid)
    if user and user.get("is_blocked"):
        return await callback.answer("🚫 Siz bloklangansiz.", show_alert=True)

    # callback.message None bo'lishi mumkin (inline xabar o'chirilgan yoki bot ko'ra olmaydi)
    # Bunday holda foydalanuvchiga bot orqali javob beramiz
    tid     = callback.data[11:]
    msg     = callback.message   # None bo'lishi mumkin
    chat_id = msg.chat.id if msg and msg.chat else uid  # private fallback
    is_group = (msg.chat.type in ("group","supergroup")) if msg and msg.chat else False

    # Faol test bormi?
    cur_state = await state.get_state()
    if cur_state in (TestSolving.answering.state, TestSolving.text_answer.state):
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⏹ Joriy testni to'xtatish", callback_data="cancel_test"))
        b.row(InlineKeyboardButton(text="▶️ Yangi testni davom et",   callback_data=callback.data))
        await callback.answer("⚠️ Avval joriy testni tugatting!", show_alert=True)
        if msg:
            await callback.bot.send_message(
                chat_id,
                "⚠️ <b>Siz hozir test yechyapsiz!</b>\n\n"
                "Joriy testni to'xtatib yangi testni boshlaysizmi?",
                reply_markup=b.as_markup()
            )
        return
    await callback.answer()

    from utils.db import get_test_full
    from utils.ram_cache import get_test_by_id as _get_cached

    # RAM da bormi?
    test = _get_cached(tid)
    if not test or not test.get("questions"):
        # RAM da yo'q — yuklab olamiz
        await callback.answer("⏳ Test yuklanmoqda...", show_alert=False)
        load_msg = None
        if msg:
            try:
                load_msg = await callback.bot.send_message(
                    chat_id,
                    "⏳ <b>Test yuklanmoqda...</b>\n<i>Bir lahza kuting...</i>"
                )
            except: pass
        test = await get_test_full(tid)
        if load_msg:
            try: await load_msg.delete()
            except: pass

    if not test:
        await callback.answer("❌ Test topilmadi.", show_alert=True)
        return
    qs = test.get("questions", [])
    if not qs:
        await callback.answer("❌ Bu testda savollar yo'q.", show_alert=True)
        return

    poll_time = test.get("poll_time", 30) or 30

    if is_group:
        # Guruhda inline test — quiz poll uslubida
        _group_inline[chat_id] = {
            "tid":       tid,
            "test":      test,
            "qs":        qs,
            "idx":       0,
            "answers":   {},     # {uid: letter}
            "names":     {},     # {uid: name}
            "answered":  set(),  # Javob bergan uid lar
            "host_id":   uid,
            "poll_time": poll_time,
            "msg_id":    None,
            "task":      None,
        }
        try:
            await callback.message.delete()
        except:
            pass
        await _group_send_question(callback.bot, chat_id)
    else:
        # Private — oddiy inline test
        await state.set_data({
            "test_data":     test,
            "questions":     qs,
            "current_index": 0,
            "user_answers":  {},
            "start_time":    time.time(),
            "poll_time":     poll_time,
        })
        await state.set_state(TestSolving.answering)
        await _send_question(callback, state, edit=True)


# ═══════════════════════════════════════════════════════════
# 3. GURUH INLINE TEST — quiz poll uslubi
# ═══════════════════════════════════════════════════════════

def _progress_bar(elapsed, total, length=BAR_LEN):
    if total <= 0:
        return "█" * length
    filled = min(int((elapsed / total) * length), length)
    empty  = length - filled
    pct    = min(int(elapsed / total * 100), 100)
    remain = max(0, total - elapsed)
    return f"{'█'*filled}{'░'*empty}  {remain}s"


async def _group_send_question(bot, chat_id):
    sess = _group_inline.get(chat_id)
    if not sess:
        return

    idx  = sess["idx"]
    qs   = sess["qs"]
    test = sess["test"]

    if idx >= len(qs):
        await _group_finish(bot, chat_id)
        return

    q         = qs[idx]
    poll_time = sess["poll_time"]
    opts      = q.get("options", [])
    if q.get("type") == "true_false":
        opts = ["Ha", "Yo'q"]

    # Variant harflari
    letters = []
    clean_opts = []
    for i, opt in enumerate(opts):
        ot = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
        clean_opts.append(ot)
        letters.append(LETTERS[i] if i < len(LETTERS) else str(i+1))

    # Tugmalar
    b = InlineKeyboardBuilder()
    for i, (letter, opt) in enumerate(zip(letters, clean_opts)):
        icon = ["🔵","🟣","🟢","🔴","🟡","🟠"][i] if i < 6 else "▫️"
        b.add(InlineKeyboardButton(
            text=f"{icon} {letter}) {opt[:20]}",
            callback_data=f"ginl_{letter}"
        ))
    b.adjust(2)
    b.row(InlineKeyboardButton(
        text=f"⏹ To'xtatish",
        callback_data=f"gstop_{sess['host_id']}"
    ))

    # Savol matni
    qtxt  = q.get("question", q.get("text", "Savol"))
    # QuizBot raqamlarini olib tashlash: [2/30] → ""
    qtxt  = re.sub(r'^\[\d+/\d+\]\s*', '', qtxt)
    bar   = _progress_bar(0, poll_time)
    total = len(qs)

    text = (
        f"<b>📝 {test.get('title','')} — Savol {idx+1}/{total}</b>\n"
        f"<code>[{bar}]</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{qtxt}</b>\n\n"
        f"<i>⏱ {poll_time} soniya | Javob bering:</i>"
    )

    # Eski xabarni o'chirish
    old_id = sess.get("msg_id")
    if old_id:
        try: await bot.delete_message(chat_id, old_id)
        except: pass

    msg = await bot.send_message(chat_id, text, reply_markup=b.as_markup())
    sess["msg_id"]   = msg.message_id
    sess["answered"] = set()
    sess["q_answers"] = {}  # Bu savol uchun {uid: letter}

    # Taymerli task
    if sess.get("task"):
        try: sess["task"].cancel()
        except: pass

    task = asyncio.create_task(_group_timer(bot, chat_id, msg.message_id, poll_time))
    sess["task"] = task


async def _group_timer(bot, chat_id, msg_id, total_sec):
    """Progress bar yangilash + vaqt tugaganda javobni ko'rsatish"""
    sess = _group_inline.get(chat_id)
    if not sess:
        return

    start = time.time()
    # Har 5 soniyada progress bar yangilanadi
    interval = 5
    try:
        for tick in range(interval, total_sec, interval):
            await asyncio.sleep(interval)
            elapsed = int(time.time() - start)
            sess2   = _group_inline.get(chat_id)
            if not sess2 or sess2.get("msg_id") != msg_id:
                return
            bar  = _progress_bar(elapsed, total_sec)
            idx  = sess2["idx"]
            qs   = sess2["qs"]
            q    = qs[idx]
            qtxt = q.get("question", q.get("text","Savol"))
            qtxt = re.sub(r'^\[\d+/\d+\]\s*', '', qtxt)
            answered_count = len(sess2.get("answered", set()))
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=(
                        f"<b>📝 {sess2['test'].get('title','')} — Savol {idx+1}/{len(qs)}</b>\n"
                        f"<code>[{bar}]</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"<b>{qtxt}</b>\n\n"
                        f"<i>✅ {answered_count} kishi javob berdi</i>"
                    ),
                    reply_markup=sess2.get("_last_kb")
                )
            except:
                pass

        # Qolgan vaqt
        remaining = total_sec - int(time.time() - start)
        if remaining > 0:
            await asyncio.sleep(remaining)

        # Vaqt tugadi — javobni ko'rsatish
        sess3 = _group_inline.get(chat_id)
        if not sess3 or sess3.get("msg_id") != msg_id:
            return
        await _group_reveal_answer(bot, chat_id, msg_id)

    except asyncio.CancelledError:
        pass


async def _group_reveal_answer(bot, chat_id, msg_id):
    """Vaqt tugaganda to'g'ri javob va izohni ko'rsatish"""
    sess = _group_inline.get(chat_id)
    if not sess:
        return

    idx  = sess["idx"]
    qs   = sess["qs"]
    q    = qs[idx]

    qtxt  = q.get("question", q.get("text","Savol"))
    qtxt  = re.sub(r'^\[\d+/\d+\]\s*', '', qtxt)
    opts  = q.get("options", [])
    if q.get("type") == "true_false":
        opts = ["Ha","Yo'q"]

    # To'g'ri javob
    corr = q.get("correct","")
    if isinstance(corr, int):
        c_letter = LETTERS[corr] if corr < len(LETTERS) else "A"
    else:
        m = re.match(r"^([A-Za-z])", str(corr).strip())
        c_letter = m.group(1).upper() if m else "A"

    # Javob statistikasi
    q_ans = sess.get("q_answers", {})
    total_ans = len(q_ans)
    ans_count = {}
    for letter in q_ans.values():
        ans_count[letter] = ans_count.get(letter, 0) + 1

    # Variantlar ko'rsatish
    opts_text = ""
    for i, opt in enumerate(opts):
        ot     = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
        letter = LETTERS[i] if i < len(LETTERS) else str(i+1)
        cnt    = ans_count.get(letter, 0)
        pct    = round(cnt/total_ans*100) if total_ans else 0
        if letter == c_letter:
            opts_text += f"✅ <b>{letter}) {ot}</b>  — {cnt} kishi ({pct}%)\n"
        else:
            opts_text += f"❌ {letter}) {ot}  — {cnt} kishi ({pct}%)\n"

    expl = q.get("explanation","") or ""
    if expl in ("Izoh kiritilmagan.","Izoh yo'q","Izoh kiritilmagan",""):
        expl = ""
    expl_text = f"\n💡 <i>{expl}</i>" if expl else ""

    text = (
        f"<b>📊 SAVOL {idx+1} NATIJASI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{qtxt}</b>\n\n"
        f"{opts_text}"
        f"{expl_text}\n\n"
        f"<i>✅ {total_ans} kishi qatnashdi</i>"
    )

    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text, reply_markup=None
        )
    except:
        pass

    # Keyingi savolga o'tish
    sess["idx"] += 1
    await asyncio.sleep(2)
    await _group_send_question(bot, chat_id)


async def _group_finish(bot, chat_id):
    """Guruh testi tugadi — top 20 leaderboard"""
    sess = _group_inline.pop(chat_id, {})
    if not sess:
        return

    test    = sess.get("test", {})
    qs      = sess.get("qs", [])
    answers = sess.get("answers", {})   # {uid: {q_idx: letter}}
    names   = sess.get("names", {})
    tid     = sess.get("tid","")

    results = []
    for uid_str, user_ans in answers.items():
        uid    = int(uid_str)
        scored = calculate_score(qs, user_ans)
        name   = names.get(uid_str, f"User{uid}")
        pct    = scored.get("percentage", 0)
        corr   = scored.get("correct_count", 0)
        save_result(uid, tid, {**scored, "mode":"group_inline"})
        results.append((name, pct, corr))

    results.sort(key=lambda x: x[1], reverse=True)
    top20 = results[:20]

    medals = ["🥇","🥈","🥉"]
    text   = (
        f"🏆 <b>TEST YAKUNLANDI — REYTING</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {test.get('title','')} | {len(qs)} savol\n"
        f"👥 {len(results)} ishtirokchi\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    for i, (name, pct, corr) in enumerate(top20):
        medal = medals[i] if i < 3 else f"{i+1}."
        bar   = "█" * int(pct/10) + "░" * (10 - int(pct/10))
        text += f"{medal} <b>{name}</b>\n   <code>[{bar}]</code> {pct}% ({corr}/{len(qs)})\n\n"

    bot_info = await bot.me()
    link     = f"https://t.me/{bot_info.username}?start={tid}"
    b        = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Yana bir marta", url=link))
    await bot.send_message(chat_id, text, reply_markup=b.as_markup())

    # Guruh natijalarini RAMdan tozalash
    from utils.ram_cache import get_daily as _get_daily
    import utils.ram_cache as ram
    daily = ram.get_daily()
    for uid_str in answers.keys():
        if uid_str in daily:
            bt = daily[uid_str].get("by_test",{})
            if tid in bt:
                del bt[tid]
    ram._set("daily_results", daily)


# ═══════════════════════════════════════════════════════════
# 4. GURUH INLINE — javob qabul qilish
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ginl_"))
async def group_inline_answer(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    uid     = callback.from_user.id
    name    = callback.from_user.username
    if name:
        name = f"@{name}"
    else:
        name = callback.from_user.full_name

    sess = _group_inline.get(chat_id)
    if not sess:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    letter = callback.data[5:]

    # Bir marta javob qoidasi
    if uid in sess.get("answered", set()):
        return await callback.answer("⚠️ Siz allaqachon javob berdingiz!", show_alert=True)

    # Javobni saqlash
    uid_str = str(uid)
    idx     = sess["idx"]
    if uid_str not in sess["answers"]:
        sess["answers"][uid_str] = {}
    sess["answers"][uid_str][str(idx)] = letter
    sess["names"][uid_str] = name
    sess.setdefault("answered", set()).add(uid)
    sess.setdefault("q_answers", {})[uid_str] = letter

    # Faqat shu odamga ko'rinadigan toast
    await callback.answer(
        "✅ Javobingiz qabul qilindi! Natija vaqt tugaganda e'lon qilinadi.",
        show_alert=False
    )


@router.callback_query(F.data.startswith("gstop_"))
async def group_stop(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    sess    = _group_inline.get(chat_id)
    if not sess:
        return await callback.answer("Test topilmadi.", show_alert=True)

    uid     = callback.from_user.id
    host_id = sess.get("host_id")

    # Faqat host yoki admin to'xtatishi mumkin
    from config import ADMIN_IDS
    if uid != host_id and uid not in ADMIN_IDS:
        return await callback.answer(
            "❌ Faqat test boshlaganki yoki admin to'xtatishi mumkin!",
            show_alert=True
        )

    await callback.answer("⏹ To'xtatilmoqda...")
    if sess.get("task"):
        try: sess["task"].cancel()
        except: pass

    try: await callback.message.delete()
    except: pass

    del _group_inline[chat_id]
    await callback.bot.send_message(chat_id, "⏹ <b>Test to'xtatildi.</b>")


# ═══════════════════════════════════════════════════════════
# 5. PRIVATE INLINE TEST — savol yuborish
# ═══════════════════════════════════════════════════════════

async def _send_question(event, state: FSMContext, edit: bool = False):
    data      = await state.get_data()
    qs        = data["questions"]
    idx       = data["current_index"]
    q         = qs[idx]
    title     = data["test_data"].get("title","Test")
    t_limit   = data["test_data"].get("time_limit",0)
    start     = data.get("start_time", time.time())
    poll_time = data.get("poll_time", 30) or 30

    time_txt = ""
    if t_limit > 0:
        remain = max(0, t_limit*60 - int(time.time()-start))
        m, s   = divmod(remain, 60)
        time_txt = f"  ⏱ {m:02d}:{s:02d}"
        if remain == 0:
            await _finish_test(event, state, data)
            return

    filled = int((idx / len(qs)) * BAR_LEN)
    bar    = "█"*filled + "░"*(BAR_LEN-filled)

    header = (
        f"<b>📝 {title}</b>  {idx+1}/{len(qs)}{time_txt}\n"
        f"<code>[{bar}]</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    qtxt   = q.get("question", q.get("text","Savol matni yo'q"))
    # QuizBot raqamlarini olib tashlash
    qtxt   = re.sub(r'^\[\d+/\d+\]\s*', '', qtxt)
    qtype  = q.get("type","multiple_choice")
    body   = f"<b>{qtxt}</b>\n\n"
    letters = []

    if qtype in ("multiple_choice","multi_select","true_false"):
        opts = q.get("options",[])
        if qtype == "true_false" and not opts:
            opts = ["Ha","Yo'q"]
        for i, opt in enumerate(opts):
            letter = LETTERS[i] if i < len(LETTERS) else str(i+1)
            ot     = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
            body  += f"▫️ <b>{letter})</b> <i>{ot}</i>\n"
            letters.append(letter)
        # Poll vaqti ko'rsatish
        body += f"\n<i>⏱ Javob uchun {poll_time} soniya</i>"
        kb    = answer_kb(letters)
    else:
        body += "✍️ <i>Javobingizni yozing:</i>"
        kb    = next_kb()
        await state.set_state(TestSolving.text_answer)

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
# 6. JAVOB QAYTA ISHLASH — private: darhol ko'rsatish + 30s avto-o'tish
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("ans_"), TestSolving.answering)
async def process_answer(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if await state.get_state() != TestSolving.answering.state:
        return

    letter = callback.data[4:]
    data   = await state.get_data()
    idx    = data["current_index"]
    qs     = data["questions"]
    q      = qs[idx]
    title  = data["test_data"].get("title","Test")

    answers = data.get("user_answers",{})
    answers[str(idx)] = letter
    await state.update_data(user_answers=answers)

    correct = q.get("correct","")
    if isinstance(correct, int):
        c_letter = LETTERS[correct] if correct < len(LETTERS) else "?"
    else:
        m = re.match(r"^([A-Za-z])", str(correct).strip())
        c_letter = m.group(1).upper() if m else "?"

    is_correct = letter.upper() == c_letter.upper()

    # Progress bar
    filled = int((idx / len(qs)) * BAR_LEN)
    bar    = "█"*filled + "░"*(BAR_LEN-filled)

    header = (
        f"<b>📝 {title}</b>  {idx+1}/{len(qs)}\n"
        f"<code>[{bar}]</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    qtxt   = q.get("question", q.get("text","Savol"))
    qtxt   = re.sub(r'^\[\d+/\d+\]\s*', '', qtxt)
    body   = f"<b>{qtxt}</b>\n\n"

    for i, opt in enumerate(q.get("options",[])):
        ltr = LETTERS[i] if i < len(LETTERS) else str(i+1)
        ot  = str(opt).split(")",1)[-1].strip() if ")" in str(opt) else str(opt)
        if ltr.upper() == c_letter.upper():
            body += f"✅ <b>{ltr})</b> <i>{ot}</i>\n"
        elif ltr.upper() == letter.upper() and not is_correct:
            body += f"❌ <b>{ltr})</b> <i>{ot}</i>\n"
        else:
            body += f"▫️ <b>{ltr})</b> <i>{ot}</i>\n"

    body += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    body += "🎯 ✅ TO'G'RI!\n" if is_correct else "🎯 ❌ XATO\n"

    expl = q.get("explanation","")
    if expl and expl not in ("Izoh kiritilmagan.","Izoh yo'q","Izoh kiritilmagan",""):
        body += f"💡 <b>Izoh:</b> <i>{expl}</i>\n"

    # 30 soniya avto-o'tish tugmasi
    body += "\n<i>⏭ 30 soniyada keyingi savol...</i>"
    kb = next_q_kb(30)

    try:
        await callback.message.edit_text(header + body, reply_markup=kb)
    except TelegramBadRequest:
        pass

    # Avto-o'tish task
    uid   = callback.from_user.id
    key   = (callback.message.chat.id, uid)
    old   = _auto_tasks.pop(key, None)
    if old: old.cancel()

    task = asyncio.create_task(_auto_next(callback, state, idx, qs, 30))
    _auto_tasks[key] = task


async def _auto_next(callback, state, idx, qs, delay):
    """30 soniyadan keyin avtomatik keyingi savolga o'tish"""
    try:
        await asyncio.sleep(delay)
        if await state.get_state() != TestSolving.answering.state:
            return
        data = await state.get_data()
        if data.get("current_index") != idx:
            return  # Foydalanuvchi o'zi o'tdi
        if idx < len(qs) - 1:
            await state.update_data(current_index=idx+1)
            await _send_question(callback, state, edit=True)
        else:
            await _finish_test(callback, state, data)
    except asyncio.CancelledError:
        pass


@router.callback_query(F.data == "next_now", TestSolving.answering)
async def next_now(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id
    key = (callback.message.chat.id, uid)
    t   = _auto_tasks.pop(key, None)
    if t: t.cancel()

    data = await state.get_data()
    idx  = data["current_index"]
    qs   = data["questions"]
    if idx < len(qs) - 1:
        await state.update_data(current_index=idx+1)
        await _send_question(callback, state, edit=True)
    else:
        await _finish_test(callback, state, data)


@router.message(TestSolving.text_answer)
async def text_answer(message: Message, state: FSMContext):
    data    = await state.get_data()
    idx     = data["current_index"]
    answers = data.get("user_answers",{})
    qs      = data["questions"]

    answers[str(idx)] = message.text.strip()
    await state.update_data(user_answers=answers, current_index=idx+1)
    await state.set_state(TestSolving.answering)

    try: await message.delete()
    except: pass

    if idx+1 < len(qs):
        await _send_question(message, state, edit=False)
    else:
        fresh = await state.get_data()
        await _finish_test(message, state, fresh)


@router.callback_query(F.data == "cancel_test", TestSolving.answering)
async def cancel_test(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    key = (callback.message.chat.id, uid)
    t   = _auto_tasks.pop(key, None)
    if t: t.cancel()

    await state.clear()
    await callback.answer("❌ Test to'xtatildi")
    try: await callback.message.delete()
    except: pass
    await callback.bot.send_message(
        callback.message.chat.id,
        "<b>❌ TEST TO'XTATILDI</b>\nNatijalar saqlanmadi.",
        reply_markup=main_kb(callback.from_user.id)
    )


# ═══════════════════════════════════════════════════════════
# 7. TEST YAKUNLASH — private
# ═══════════════════════════════════════════════════════════

async def _finish_test(event, state: FSMContext, data: dict):
    test      = data.get("test_data",{})
    qs        = data.get("questions",[])
    u_answers = data.get("user_answers",{})
    elapsed   = int(time.time()-data.get("start_time",time.time()))

    scored = calculate_score(qs, u_answers)
    scored["time_spent"]    = elapsed
    scored["passing_score"] = test.get("passing_score",60)
    scored["mode"]          = "inline"

    uid     = event.from_user.id
    chat_id = (event.message if isinstance(event, CallbackQuery) else event).chat.id
    tid     = test.get("test_id","")
    rid     = save_result(uid, tid, scored)

    # Reyting o'rni
    daily   = get_daily()
    pct     = scored.get("percentage",0)
    all_pct = []
    for u_data in daily.values():
        last = u_data.get("by_test",{}).get(tid,{}).get("last_result",{})
        if last:
            all_pct.append(last.get("percentage",0))
    all_pct.sort(reverse=True)
    rank     = next((i+1 for i,p in enumerate(all_pct) if p<=pct), len(all_pct))
    rank_txt = f"\n\n🏅 <b>Umumiy reyting: {rank}/{len(all_pct)} o'rin</b>" if len(all_pct)>1 else ""

    text = format_result(scored, test) + rank_txt

    await state.clear()
    try:
        if isinstance(event, CallbackQuery): await event.message.delete()
        else: await event.delete()
    except:
        pass

    await event.bot.send_message(chat_id, text, reply_markup=result_kb(tid, rid))


@router.callback_query(F.data == "go_tests")
async def go_tests(callback: CallbackQuery):
    await callback.answer()
    await show_catalog(callback)
