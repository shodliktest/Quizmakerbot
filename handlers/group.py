"""👥 GURUH TEST — Inline + Poll rejim"""
import asyncio, logging, re, time
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from utils import store
from utils.scoring import score
from keyboards.kb import group_mode_kb, group_stop_kb

log    = logging.getLogger(__name__)
router = Router()
LT     = "ABCDEFGHIJ"
BAR    = 20


# ═══════════════════════════════════════════════════════════
# GURUHGA YUBORISH → REJIM TANLOV
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("s_test_"))
async def group_start_choice(cb: CallbackQuery):
    msg = cb.message
    if not msg or msg.chat.type not in ("group", "supergroup"):
        return  # private → tests.py ushlab oladi

    await cb.answer()
    tid = cb.data[7:]

    if store.has_session(msg.chat.id):
        return await cb.answer("⚠️ Bu guruhda test allaqachon boshlanmoqda!", show_alert=True)

    try: await msg.delete()
    except: pass

    await cb.bot.send_message(
        msg.chat.id,
        "👥 <b>GURUH TEST REJIMI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔘 <b>Inline</b> — A/B/C/D tugmalar\n"
        "📊 <b>Poll</b> — Telegram viktorina",
        reply_markup=group_mode_kb(tid)
    )


@router.callback_query(F.data == "gm_cancel")
async def gm_cancel(cb: CallbackQuery):
    await cb.answer()
    try: await cb.message.delete()
    except: pass


# ═══════════════════════════════════════════════════════════
# YORDAMCHILAR
# ═══════════════════════════════════════════════════════════

def _progress(elapsed, total, length=BAR) -> str:
    if total <= 0:
        return "█" * length
    filled = min(int(elapsed / total * length), length)
    return f"{'█'*filled}{'░'*(length-filled)}  {max(0,total-elapsed)}s"


def _clean_q(text: str) -> str:
    return re.sub(r"^\[\d+/\d+\]\s*", "", text).strip()


async def countdown(bot, chat_id, title, total_qs, poll_time):
    msg = await bot.send_message(
        chat_id,
        f"🚀 <b>{title}</b>\n"
        f"📝 {total_qs} savol | ⏱ {poll_time}s/savol\n\n<b>3</b>..."
    )
    for n in (2, 1):
        await asyncio.sleep(1)
        try: await msg.edit_text(f"🚀 <b>{title}</b>\n\n<b>{n}</b>...")
        except: pass
    await asyncio.sleep(1)
    try: await msg.delete()
    except: pass


# ═══════════════════════════════════════════════════════════
# INLINE MODE
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gm_inline_"))
async def start_inline(cb: CallbackQuery):
    await cb.answer()
    tid     = cb.data[10:]
    chat_id = cb.message.chat.id
    uid     = cb.from_user.id

    if store.has_session(chat_id):
        return await cb.answer("⚠️ Allaqachon boshlanmoqda!", show_alert=True)

    test = store.get_test(tid)
    if not test:
        return await cb.answer("❌ Test topilmadi.", show_alert=True)

    qs = [q for q in test.get("questions", [])
          if q.get("type", "multiple_choice") in ("multiple_choice", "true_false", "multi_select")]
    if not qs:
        return await cb.answer("❌ Variantli savollar yo'q!", show_alert=True)

    pt = test.get("poll_time", 30) or 30
    store.create_session(chat_id, tid, test, qs, "inline", uid, pt)

    try: await cb.message.delete()
    except: pass

    await countdown(cb.bot, chat_id, test.get("title", "Test"), len(qs), pt)
    await inline_send_q(cb.bot, chat_id)


async def inline_send_q(bot, chat_id):
    sess = store.get_session(chat_id)
    if not sess or not sess["is_active"]:
        return

    idx = sess["idx"]
    qs  = sess["qs"]
    if idx >= len(qs):
        await _finish_group(bot, chat_id)
        return

    q         = qs[idx]
    pt        = sess["poll_time"]
    test      = sess["test"]
    opts      = q.get("options", [])
    if q.get("type") == "true_false" or not opts:
        opts = ["Ha", "Yo'q"]

    clean_opts = []
    for opt in opts:
        ot = str(opt).split(")", 1)[-1].strip() if ")" in str(opt) else str(opt)
        clean_opts.append(ot)

    b     = InlineKeyboardBuilder()
    icons = ["🔵","🟣","🟢","🔴","🟡","🟠","⚪","⚫","🔷","🔶"]
    for i, (lt, opt) in enumerate(zip(LT, clean_opts)):
        b.add(InlineKeyboardButton(
            text=f"{icons[i] if i<len(icons) else '▫️'} {lt}) {opt[:18]}",
            callback_data=f"g_ans_{lt}"
        ))
    b.adjust(2)
    b.row(InlineKeyboardButton(
        text="⏹ To'xtatish",
        callback_data=f"g_stop_{sess['host_id']}"
    ))

    qtxt = _clean_q(q.get("question", q.get("text", "Savol")))
    bar  = _progress(0, pt)
    text = (
        f"<b>📝 {test.get('title','')} — {idx+1}/{len(qs)}</b>\n"
        f"<code>[{bar}]</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{qtxt}</b>\n\n"
        f"<i>⏱ {pt}s da keyingi savol!</i>"
    )

    old = sess.get("msg_id")
    if old:
        try: await bot.delete_message(chat_id, old)
        except: pass

    msg = await bot.send_message(chat_id, text, reply_markup=b.as_markup())
    sess["msg_id"]   = msg.message_id
    sess["answered"] = set()
    sess["q_answers"] = {}
    sess["_last_kb"] = b.as_markup()

    task = asyncio.create_task(_inline_timer(bot, chat_id, msg.message_id, pt))
    store.set_session_task(chat_id, task)


async def _inline_timer(bot, chat_id, msg_id, total_sec):
    sess  = store.get_session(chat_id)
    if not sess:
        return
    start    = time.time()
    interval = min(30, max(10, total_sec // 3))

    try:
        for tick in range(interval, total_sec, interval):
            sleep = tick - int(time.time() - start)
            if sleep > 0:
                await asyncio.sleep(sleep)
            elapsed = int(time.time() - start)
            s2 = store.get_session(chat_id)
            if not s2 or s2.get("msg_id") != msg_id:
                return
            idx  = s2["idx"]
            qs   = s2["qs"]
            q    = qs[idx]
            qtxt = _clean_q(q.get("question", q.get("text", "Savol")))
            bar  = _progress(elapsed, total_sec)
            cnt  = len(s2.get("answered", set()))
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=(
                        f"<b>📝 {s2['test'].get('title','')} — {idx+1}/{len(qs)}</b>\n"
                        f"<code>[{bar}]</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"<b>{qtxt}</b>\n\n"
                        f"<i>✅ {cnt} kishi javob berdi</i>"
                    ),
                    reply_markup=s2.get("_last_kb")
                )
            except TelegramBadRequest:
                pass

        remaining = total_sec - int(time.time() - start)
        if remaining > 0:
            await asyncio.sleep(remaining)

        s3 = store.get_session(chat_id)
        if s3 and s3.get("msg_id") == msg_id and s3["is_active"]:
            await _inline_reveal(bot, chat_id, msg_id)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"inline_timer: {e}")


async def _inline_reveal(bot, chat_id, msg_id):
    sess = store.get_session(chat_id)
    if not sess:
        return

    idx  = sess["idx"]
    qs   = sess["qs"]
    q    = qs[idx]
    qtxt = _clean_q(q.get("question", q.get("text", "Savol")))
    opts = q.get("options", [])
    if q.get("type") == "true_false" or not opts:
        opts = ["Ha", "Yo'q"]

    corr = q.get("correct", "")
    if isinstance(corr, int):
        c_lt = LT[corr] if corr < len(LT) else "A"
    else:
        m    = re.match(r"^([A-Za-z])", str(corr).strip())
        c_lt = m.group(1).upper() if m else "A"

    q_ans     = sess.get("q_answers", {})
    total_ans = len(q_ans)
    cnt_map   = {}
    for lt in q_ans.values():
        cnt_map[lt] = cnt_map.get(lt, 0) + 1

    opts_text = ""
    for i, opt in enumerate(opts):
        lt  = LT[i] if i < len(LT) else str(i+1)
        ot  = str(opt).split(")", 1)[-1].strip() if ")" in str(opt) else str(opt)
        cnt = cnt_map.get(lt, 0)
        pct = round(cnt / total_ans * 100) if total_ans else 0
        if lt == c_lt:
            opts_text += f"✅ <b>{lt}) {ot}</b> — {cnt} kishi ({pct}%)\n"
        else:
            opts_text += f"❌ {lt}) {ot} — {cnt} kishi ({pct}%)\n"

    expl = (q.get("explanation") or "").strip()
    if expl in ("Izoh kiritilmagan.", "Izoh yo'q", ""):
        expl = ""

    text = (
        f"<b>📊 SAVOL {idx+1} NATIJASI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{qtxt}</b>\n\n"
        f"{opts_text}"
        f"{chr(10)+'💡 <i>'+expl+'</i>' if expl else ''}\n\n"
        f"<i>✅ {total_ans} kishi qatnashdi</i>"
    )

    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                    text=text, reply_markup=None)
    except TelegramBadRequest:
        pass

    sess["idx"] += 1
    await asyncio.sleep(3)
    await inline_send_q(bot, chat_id)


@router.callback_query(F.data.startswith("g_ans_"))
async def group_inline_ans(cb: CallbackQuery):
    chat_id = cb.message.chat.id
    uid     = cb.from_user.id
    uname   = cb.from_user.username
    name    = f"@{uname}" if uname else cb.from_user.full_name

    sess = store.get_session(chat_id)
    if not sess or sess.get("mode") != "inline":
        return await cb.answer("❌ Faol test yo'q.", show_alert=True)

    letter = cb.data[6:]
    idx    = sess["idx"]

    if uid in sess.get("answered", set()):
        return await cb.answer("⚠️ Allaqachon javob berdingiz!", show_alert=True)

    ok = store.record_answer(sess, uid, name, idx, letter)
    if ok:
        await cb.answer("✅ Javob qabul qilindi!", show_alert=False)
    else:
        await cb.answer("⚠️ Allaqachon javob berdingiz!", show_alert=True)


# ═══════════════════════════════════════════════════════════
# POLL MODE
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gm_poll_"))
async def start_poll(cb: CallbackQuery):
    await cb.answer()
    tid     = cb.data[8:]
    chat_id = cb.message.chat.id
    uid     = cb.from_user.id

    if store.has_session(chat_id):
        return await cb.answer("⚠️ Allaqachon boshlanmoqda!", show_alert=True)

    test = store.get_test(tid)
    if not test:
        return await cb.answer("❌ Test topilmadi.", show_alert=True)

    qs = [q for q in test.get("questions", [])
          if q.get("type", "multiple_choice") in ("multiple_choice", "true_false")]
    if not qs:
        return await cb.answer("❌ Poll uchun variantli savollar yo'q!", show_alert=True)

    pt = test.get("poll_time", 30) or 30
    store.create_session(chat_id, tid, test, qs, "poll", uid, pt)

    try: await cb.message.delete()
    except: pass

    await countdown(cb.bot, chat_id, test.get("title", "Test"), len(qs), pt)
    await poll_send_q(cb.bot, chat_id)


async def poll_send_q(bot, chat_id):
    sess = store.get_session(chat_id)
    if not sess or not sess["is_active"] or sess.get("mode") != "poll":
        return

    idx = sess["idx"]
    qs  = sess["qs"]
    if idx >= len(qs):
        await _finish_group(bot, chat_id)
        return

    q         = qs[idx]
    pt        = sess["poll_time"]
    test      = sess["test"]

    opts = []
    for opt in q.get("options", []):
        ot = str(opt).split(")", 1)[-1].strip() if ")" in str(opt) else str(opt)
        opts.append(ot[:100])
    if q.get("type") == "true_false" or not opts:
        opts = ["Ha", "Yo'q"]

    corr = q.get("correct", "")
    if isinstance(corr, int):
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

    qtxt = _clean_q(q.get("question", q.get("text", "Savol")))
    hdr  = f"[{idx+1}/{len(qs)}] "
    if len(hdr + qtxt) > 295:
        qtxt = qtxt[:295 - len(hdr)] + "..."

    try:
        pm = await bot.send_poll(
            chat_id=chat_id, question=hdr + qtxt, options=opts,
            type="quiz", correct_option_id=ci, explanation=expl,
            is_anonymous=False, open_period=pt if pt > 0 else None
        )
        sess["poll_map"][pm.poll.id]  = idx
        sess["poll_msg_ids"].append(pm.message_id)
        sess["msg_id"] = pm.message_id

        task = asyncio.create_task(_poll_timer(bot, chat_id, pm.message_id, pt, idx))
        store.set_session_task(chat_id, task)
    except Exception as e:
        log.error(f"group poll_send_q: {e}")
        sess["idx"] += 1
        await poll_send_q(bot, chat_id)


async def _poll_timer(bot, chat_id, poll_msg_id, total_sec, q_idx):
    try:
        await asyncio.sleep(total_sec)
        sess = store.get_session(chat_id)
        if not sess or sess.get("idx") != q_idx:
            return
        try: await bot.stop_poll(chat_id, poll_msg_id)
        except TelegramBadRequest: pass
        sess["idx"] += 1
        await asyncio.sleep(2)
        await poll_send_q(bot, chat_id)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"group poll_timer: {e}")


# ═══════════════════════════════════════════════════════════
# TO'XTATISH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("g_stop_"))
async def group_stop(cb: CallbackQuery):
    chat_id = cb.message.chat.id
    sess    = store.get_session(chat_id)
    if not sess:
        return await cb.answer("Test topilmadi.", show_alert=True)

    uid     = cb.from_user.id
    from config import ADMIN_IDS
    if uid != sess.get("host_id") and uid not in ADMIN_IDS:
        return await cb.answer("❌ Faqat test boshlaganki to'xtatishi mumkin!", show_alert=True)

    await cb.answer("⏹")
    store.delete_session(chat_id)
    try: await cb.message.delete()
    except: pass
    await cb.bot.send_message(chat_id, "⏹ <b>Test to'xtatildi.</b>")


# ═══════════════════════════════════════════════════════════
# YAKUNLASH
# ═══════════════════════════════════════════════════════════

async def _finish_group(bot, chat_id):
    sess = store.get_session(chat_id)
    if not sess:
        return

    test = sess.get("test", {})
    qs   = sess.get("qs", [])
    tid  = sess.get("tid", "")
    lb   = store.get_session_leaderboard(sess)

    # Natijalarni saqlash
    for name, sc_val, pct, ans_cnt, uid_str in lb:
        uid = int(uid_str)
        p   = sess["participants"][uid_str]
        res = score(qs, p.get("answers", {}))
        res["mode"]      = f"group_{sess.get('mode','inline')}"
        res["user_name"] = name
        res["tid"]       = tid
        store.save_result(uid, res)

        user  = store.get_user(uid) or {}
        total = user.get("total", 0) + 1
        avg   = round((user.get("avg", 0) * (total - 1) + res["percentage"]) / total, 1)
        user.update({"total": total, "avg": avg})
        store.upsert_user(uid, user)

    medals = ["🥇","🥈","🥉"]
    text   = (
        f"🏆 <b>TEST YAKUNLANDI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {test.get('title','')} | {len(qs)} savol\n"
        f"👥 {len(lb)} ishtirokchi\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    if not lb:
        text += "😕 Hech kim qatnashmadi."
    else:
        for i, (name, sc_val, pct, ans_cnt, uid_str) in enumerate(lb[:20]):
            medal = medals[i] if i < 3 else f"{i+1}."
            bar   = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            text += f"{medal} <b>{name}</b>\n   <code>[{bar}]</code> {pct}% ({sc_val}/{len(qs)})\n\n"

    bot_info = await bot.me()
    link     = f"https://t.me/{bot_info.username}?start={tid}"
    b        = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Yana bir marta", url=link))

    store.delete_session(chat_id)
    await bot.send_message(chat_id, text, reply_markup=b.as_markup())
