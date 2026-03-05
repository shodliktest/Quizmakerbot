"""👑 ADMIN PANEL"""
import json, logging
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from config import ADMIN_IDS
from utils import ram_cache as ram
from utils.db import get_all_users, get_all_tests, block_user
from keyboards.keyboards import admin_kb, main_kb
from utils.states import AdminPanel

log    = logging.getLogger(__name__)
router = Router()
UTC    = timezone.utc


def is_admin(uid): return uid in ADMIN_IDS


# ── Kirish ────────────────────────────────────────────────────

@router.message(F.text == "👑 Admin Panel")
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("🚫 Ruxsat yo'q.")
    await _show_admin(message)

async def _show_admin(msg_or_cb, edit=False):
    st    = ram.stats()
    tests = ram.get_tests_meta()
    users = ram.get_users()
    text  = (
        f"👑 <b>ADMIN PANEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Testlar: <b>{len(tests)}</b>\n"
        f"👥 Foydalanuvchilar: <b>{len(users)}</b>\n"
        f"📊 Kunlik natijalar: <b>{st.get('daily_r',0)}</b>\n"
        f"💾 Cached savollar: <b>{st.get('cached_q',0)}</b>\n"
        f"🧠 RAM: <b>{st.get('mb',0)} MB ({st.get('pct',0)}%)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    try:
        if edit and hasattr(msg_or_cb, 'message'):
            await msg_or_cb.message.edit_text(text, reply_markup=admin_kb())
        elif edit:
            await msg_or_cb.edit_text(text, reply_markup=admin_kb())
        else:
            await msg_or_cb.answer(text, reply_markup=admin_kb())
    except TelegramBadRequest:
        target = msg_or_cb.message if hasattr(msg_or_cb, 'message') else msg_or_cb
        await target.answer(text, reply_markup=admin_kb())


@router.callback_query(F.data == "admin_panel")
async def admin_panel_cb(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return await callback.answer("🚫 Ruxsat yo'q!", show_alert=True)
    await _show_admin(callback, edit=True)


# ── Statistika ────────────────────────────────────────────────

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return

    st    = ram.stats()
    users = ram.get_users()
    tests = ram.get_tests_meta()
    daily = ram.get_daily()

    active_today = sum(
        1 for uid_str, d in daily.items()
        if d.get("by_test") and any(
            e.get("attempts",0) > 0 for e in d["by_test"].values()
        )
    )
    total_attempts = sum(
        sum(e.get("attempts",0) for e in d.get("by_test",{}).values())
        for d in daily.values()
    )
    text = (
        f"📈 <b>STATISTIKA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Jami userlar: <b>{len(users)}</b>\n"
        f"📋 Jami testlar: <b>{len(tests)}</b>\n\n"
        f"<b>BUGUN:</b>\n"
        f"  👤 Faol userlar: <b>{active_today}</b>\n"
        f"  🔄 Jami urinishlar: <b>{total_attempts}</b>\n\n"
        f"<b>RAM:</b>\n"
        f"  💾 {st.get('mb',0)} MB ({st.get('pct',0)}%)\n"
        f"  📦 {st.get('cached_q',0)} ta savollar cache\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())


# ── Kunlik hisobot ────────────────────────────────────────────

@router.callback_query(F.data == "adm_daily_report")
@router.message(Command("daily"))
async def adm_daily_report(event):
    """Kunlik natijalar hisoboti — admin buyrug'i bilan"""
    uid = event.from_user.id
    if not is_admin(uid): return
    await _send_daily_report(event.bot if hasattr(event, 'bot') else event.bot, uid)

async def _send_daily_report(bot, send_to_uid):
    """Kunlik hisobotni generatsiya qilish va yuborish"""
    daily  = ram.get_daily()
    users  = ram.get_users()
    tests  = ram.get_tests_meta()
    today  = datetime.now(UTC).strftime("%Y-%m-%d")
    now    = datetime.now(UTC).strftime("%H:%M")

    total_attempts = sum(
        sum(e.get("attempts",0) for e in d.get("by_test",{}).values())
        for d in daily.values()
    )
    active_users = sum(
        1 for d in daily.values()
        if any(e.get("attempts",0) > 0 for e in d.get("by_test",{}).values())
    )

    # Test bo'yicha statistika
    test_stats = {}
    for uid_str, data in daily.items():
        for tid, entry in data.get("by_test",{}).items():
            if entry.get("attempts",0) == 0: continue
            if tid not in test_stats:
                test_stats[tid] = {"count": 0, "pcts": []}
            test_stats[tid]["count"] += entry.get("attempts",0)
            test_stats[tid]["pcts"].extend(entry.get("all_pcts",[]))

    top_tests = sorted(test_stats.items(), key=lambda x: x[1]["count"], reverse=True)[:5]

    text = (
        f"📊 <b>KUNLIK HISOBOT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {today} | ⏰ {now} UTC\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Faol foydalanuvchilar: <b>{active_users}</b>\n"
        f"🔄 Jami urinishlar: <b>{total_attempts}</b>\n"
        f"📋 Jami testlar: <b>{len(tests)}</b>\n\n"
    )

    if top_tests:
        text += "<b>🔥 TOP TESTLAR (bugun):</b>\n"
        for tid, stat in top_tests:
            meta   = next((t for t in tests if t.get("test_id") == tid), {})
            title  = meta.get("title", tid)[:20] if meta else tid
            avg_p  = round(sum(stat["pcts"]) / len(stat["pcts"]), 1) if stat["pcts"] else 0
            text  += f"  📝 {title}: {stat['count']} urinish | ⭐ {avg_p}%\n"
        text += "\n"

    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin_panel"))
    b.row(InlineKeyboardButton(text="💾 TG ga saqlash", callback_data="adm_flush"))
    try:
        await bot.send_message(send_to_uid, text, reply_markup=b.as_markup())
    except Exception as e:
        log.error(f"Daily report: {e}")


# ── Userlar ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin_users"))
async def admin_users(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return

    users = get_all_users()
    page  = int(callback.data.split("_")[-1]) if callback.data != "admin_users" else 0
    PG    = 8
    total = (len(users)+PG-1)//PG
    page  = max(0, min(page, total-1))
    chunk = users[page*PG:(page+1)*PG]

    text = (
        f"👥 <b>FOYDALANUVCHILAR</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Sahifa {page+1}/{total} | Jami: {len(users)}\n\n"
    )
    b = InlineKeyboardBuilder()
    for u in chunk:
        uid   = u.get("telegram_id","")
        name  = u.get("name","?")[:15]
        role  = "👑" if uid in ADMIN_IDS else ("🚫" if u.get("is_blocked") else "👤")
        tt    = u.get("total_tests",0)
        avg   = round(u.get("avg_score",0),1)
        text += f"{role} <b>{name}</b> | {tt} test | {avg}%\n<code>{uid}</code>\n\n"
        b.row(
            InlineKeyboardButton(text=f"{'🔓' if u.get('is_blocked') else '🔒'} Block",
                                 callback_data=f"block_{uid}_{1 if not u.get('is_blocked') else 0}"),
        )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_users_{page-1}"))
    if page < total-1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_users_{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("block_"))
async def block_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    parts   = callback.data.split("_")
    uid     = int(parts[1])
    blocked = parts[2] == "1"
    block_user(uid, blocked)
    await callback.answer(f"{'🚫 Bloklandi' if blocked else '✅ Blok ochildi'}")
    await admin_users(callback)


# ── Testlar (admin) ───────────────────────────────────────────

@router.callback_query(F.data == "admin_tests")
async def admin_tests(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return

    tests = ram.get_all_tests_meta()
    text  = (
        f"📋 <b>BARCHA TESTLAR</b> ({len(tests)} ta)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    b = InlineKeyboardBuilder()
    for t in tests[:15]:
        tid    = t.get("test_id","")
        title  = t.get("title","?")[:20]
        sc     = t.get("solve_count",0)
        active = t.get("is_active",True)
        paused = t.get("is_paused",False)
        icon   = "🗑" if not active else ("⏸" if paused else "✅")
        text += f"{icon} <b>{title}</b> [{tid}] | 👥{sc}\n"
        b.row(
            InlineKeyboardButton(text=f"🗑 O'chirish {tid}",
                                 callback_data=f"del_test_{tid}"),
            InlineKeyboardButton(text=f"{'▶️' if paused else '⏸'} {tid}",
                                 callback_data=f"{'test_resume' if paused else 'test_pause'}_{tid}"),
        )
    if len(tests) > 15:
        text += f"\n<i>...va yana {len(tests)-15} ta test</i>"
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("del_test_"))
async def del_test_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    tid  = callback.data[9:]
    meta = ram.get_test_meta(tid)
    if not meta:
        return await callback.answer("❌ Test topilmadi.", show_alert=True)

    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"del_confirm_{tid}"),
        InlineKeyboardButton(text="❌ Yo'q",          callback_data="admin_tests"),
    )
    try:
        await callback.message.edit_text(
            f"⚠️ <b>O'CHIRISH TASDIQLASH</b>\n\n"
            f"📝 {meta.get('title','?')} [{tid}]\n\n"
            f"O'chirishdan avval <b>TG ga backup yuboriladi</b>.\n"
            f"Bu amalni qaytarib bo'lmaydi!",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            f"⚠️ {meta.get('title','?')} [{tid}] ni o'chirilsinmi?",
            reply_markup=b.as_markup()
        )

@router.callback_query(F.data.startswith("del_confirm_"))
async def del_test_exec(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    tid = callback.data[12:]
    await callback.answer("⏳ O'chirilmoqda...")
    from utils.db import delete_test
    await delete_test(tid)
    try:
        await callback.message.edit_text(
            f"✅ Test [{tid}] o'chirildi va TG ga backup yuborildi."
        )
    except Exception: pass


# ── Broadcast ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="admin_panel"))
    try:
        await callback.message.edit_text(
            "📢 <b>BROADCAST</b>\n\nYubormoqchi bo'lgan xabarni yozing:",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer("📢 Xabarni yozing:", reply_markup=b.as_markup())
    await state.set_state(AdminPanel.broadcast)

@router.message(AdminPanel.broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    users = get_all_users()
    ok = err = 0
    for u in users:
        uid = u.get("telegram_id")
        if uid and not u.get("is_blocked"):
            try:
                await message.copy_to(uid)
                ok += 1
            except Exception:
                err += 1
    await state.clear()
    await message.answer(
        f"✅ Broadcast yakunlandi!\n✅ Muvaffaqiyatli: {ok}\n❌ Xato: {err}",
        reply_markup=admin_kb()
    )


# ── Flush (RAM → TG) ──────────────────────────────────────────

@router.callback_query(F.data == "adm_flush")
async def adm_flush(callback: CallbackQuery):
    await callback.answer("⏳ Yuklanmoqda...")
    if not is_admin(callback.from_user.id): return

    from utils import tg_db
    daily    = ram.get_daily()
    users    = ram.get_users()
    settings = ram.get_all_settings()

    results = await tg_db.manual_flush(daily, users, settings)
    ram.clear_users_dirty()

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin_panel"))
    try:
        await callback.message.edit_text(
            f"💾 <b>FLUSH NATIJASI</b>\n\n" + "\n".join(results),
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "💾 Flush:\n" + "\n".join(results), reply_markup=b.as_markup()
        )


# ── TG → RAM (Refresh) ────────────────────────────────────────

@router.callback_query(F.data == "adm_refresh")
async def adm_refresh(callback: CallbackQuery):
    await callback.answer("🔄 Yangilanmoqda...")
    if not is_admin(callback.from_user.id): return

    from utils import tg_db
    ram.clear_expired_cache()

    tests = await tg_db.get_tests()
    if tests:
        ram.set_tests_meta(tests) if all("questions" not in t for t in tests) else None
        ram.set_tests(tests)

    users = await tg_db.get_users()
    if users: ram.set_users(users)

    st = ram.stats()
    b  = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin Panel", callback_data="admin_panel"))
    try:
        await callback.message.edit_text(
            f"✅ <b>YANGILANDI</b>\n\n"
            f"📋 Testlar: {st['tests']}\n"
            f"👥 Userlar: {st['users']}\n"
            f"💾 RAM: {st['mb']} MB",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        await callback.message.answer("✅ Yangilandi.", reply_markup=b.as_markup())


# ── JSON Export ───────────────────────────────────────────────

@router.callback_query(F.data == "adm_export_json")
async def adm_export_json(callback: CallbackQuery):
    await callback.answer("⏳ JSON tayyorlanmoqda...")
    if not is_admin(callback.from_user.id): return

    from utils import tg_db
    export_data = {
        "exported_at": str(datetime.now(UTC)),
        "tests_meta":  ram.get_tests_meta(),
        "users":       ram.get_users(),
        "settings":    ram.get_all_settings(),
        "daily":       ram.get_daily(),
        "tg_index":    tg_db.get_index_info() if tg_db.ready() else {},
        "backup_dates":tg_db.get_backup_dates() if tg_db.ready() else [],
    }
    raw = json.dumps(export_data, ensure_ascii=False, default=str, indent=2).encode()
    doc = BufferedInputFile(raw, filename="quizbot_export.json")
    await callback.message.answer_document(
        doc,
        caption=(
            f"💾 <b>FULL EXPORT</b>\n"
            f"📋 {len(export_data['tests_meta'])} test\n"
            f"👥 {len(export_data['users'])} user\n"
            f"📅 {export_data['exported_at'][:16]}"
        )
    )


# ── Backuplar ─────────────────────────────────────────────────

@router.callback_query(F.data == "adm_backups")
async def adm_backups(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return

    from utils import tg_db
    dates = tg_db.get_backup_dates() if tg_db.ready() else []
    if not dates:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_panel"))
        try: await callback.message.edit_text("📦 Backuplar yo'q.", reply_markup=b.as_markup())
        except TelegramBadRequest: pass
        return

    text = f"🗂 <b>BACKUPLAR</b> ({len(dates)} ta)\n\n"
    b    = InlineKeyboardBuilder()
    for d in dates[:10]:
        text += f"📅 {d}\n"
        b.row(InlineKeyboardButton(text=f"📥 {d}", callback_data=f"dl_backup_{d}"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("dl_backup_"))
async def dl_backup(callback: CallbackQuery):
    await callback.answer("⏳ Yuklanmoqda...")
    if not is_admin(callback.from_user.id): return

    from utils import tg_db
    date_str = callback.data[10:]
    data = await tg_db.get_backup(date_str)
    if not data:
        return await callback.answer("❌ Backup topilmadi.", show_alert=True)
    raw = json.dumps(data, ensure_ascii=False, default=str, indent=2).encode()
    doc = BufferedInputFile(raw, filename=f"backup_{date_str}.json")
    await callback.message.answer_document(
        doc, caption=f"📦 Backup: {date_str}"
    )
