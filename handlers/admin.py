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
from keyboards.keyboards import admin_kb, main_kb, CAT_ICONS
from utils.states import AdminPanel

log    = logging.getLogger(__name__)
router = Router()
UTC    = timezone.utc

def is_admin(uid): return uid in ADMIN_IDS


# ══ ADMIN PANEL ASOSIY ════════════════════════════════════════
@router.message(F.text == "👑 Admin Panel")
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id): return
    await _show_admin(message)

@router.callback_query(F.data == "admin_panel")
async def admin_panel_cb(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    await _show_admin(callback, edit=True)

async def _show_admin(ev, edit=False):
    st    = ram.stats()
    tests = ram.get_tests_meta()
    users = ram.get_users()
    text  = (
        f"👑 <b>ADMIN PANEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Testlar: <b>{len(tests)}</b>\n"
        f"👥 Userlar: <b>{len(users)}</b>\n"
        f"📊 Kunlik: <b>{st.get('daily_r',0)}</b>\n"
        f"💾 RAM cache: <b>{st.get('cached_q',0)} test</b>\n"
        f"🧠 RAM: <b>{st.get('mb',0)} MB ({st.get('pct',0)}%)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    try:
        if edit and hasattr(ev, 'message'):
            await ev.message.edit_text(text, reply_markup=admin_kb())
        elif edit:
            await ev.edit_text(text, reply_markup=admin_kb())
        else:
            await ev.answer(text, reply_markup=admin_kb())
    except TelegramBadRequest:
        target = ev.message if hasattr(ev, 'message') else ev
        await target.answer(text, reply_markup=admin_kb())


# ══ STATISTIKA ════════════════════════════════════════════════
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    st    = ram.stats()
    users = ram.get_users()
    tests = ram.get_tests_meta()
    daily = ram.get_daily()
    today_users  = sum(1 for v in daily.values() if v.get("by_test"))
    today_solves = sum(
        len(v.get("by_test", {})) for v in daily.values()
    )
    cache_info = ram.get_cache_stats() if hasattr(ram, 'get_cache_stats') else []
    text = (
        f"📈 <b>STATISTIKA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Jami userlar: <b>{len(users)}</b>\n"
        f"📋 Jami testlar: <b>{len(tests)}</b>\n\n"
        f"📅 <b>Bugun:</b>\n"
        f"  👤 Aktiv userlar: <b>{today_users}</b>\n"
        f"  🎯 Yechilgan: <b>{today_solves}</b>\n\n"
        f"🧠 <b>RAM holati:</b>\n"
        f"  💾 {st.get('mb',0)} MB / {st.get('limit_mb',450)} MB ({st.get('pct',0)}%)\n"
        f"  📦 Cached testlar: <b>{st.get('cached_q',0)} ta</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin panel", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())


# ══ USERLAR ════════════════════════════════════════════════════
@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    await _show_users_page(callback.message, page=0, edit=True)

@router.callback_query(F.data.startswith("adm_users_p"))
async def admin_users_page(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data[11:])
    await _show_users_page(callback.message, page=page, edit=True)

async def _show_users_page(msg, page=0, edit=False):
    users_dict = ram.get_users()
    users      = sorted(users_dict.values(), key=lambda u: u.get("total_tests",0), reverse=True)
    PG    = 10
    total = (len(users)+PG-1)//PG
    page  = max(0, min(page, total-1))
    chunk = users[page*PG:(page+1)*PG]
    text  = (
        f"👥 <b>FOYDALANUVCHILAR</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Jami: {len(users)} ta | Sahifa {page+1}/{total}</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for u in chunk:
        uid   = u.get("telegram_id","")
        name  = u.get("name","?")[:16]
        total_t = u.get("total_tests",0)
        avg   = round(u.get("avg_score",0),1)
        blk   = "🚫" if u.get("is_blocked") else ""
        text += f"{blk}👤 <b>{name}</b> | 📋{total_t} | ⭐{avg}%\n"
        b.row(InlineKeyboardButton(
            text=f"{'🚫' if u.get('is_blocked') else '👤'} {name} — {total_t} test",
            callback_data=f"adm_user_{uid}"
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_users_p{page-1}"))
    if page < total-1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_users_p{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_panel"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("adm_user_"))
async def adm_user_detail(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    uid_str = callback.data[9:]
    users   = ram.get_users()
    u       = users.get(str(uid_str), {})
    if not u:
        return await callback.answer("Topilmadi", show_alert=True)
    name  = u.get("name","?")
    uname = f"@{u['username']}" if u.get("username") else "Yo'q"
    blk   = u.get("is_blocked", False)
    text  = (
        f"👤 <b>{name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 <code>{uid_str}</code>\n"
        f"📱 {uname}\n"
        f"📋 Testlar: <b>{u.get('total_tests',0)}</b>\n"
        f"⭐ O'rtacha: <b>{round(u.get('avg_score',0),1)}%</b>\n"
        f"🕐 Oxirgi: {str(u.get('last_active',''))[:16]}\n"
        f"{'🚫 BLOKLANGAN' if blk else '✅ Aktiv'}"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="✅ Blokdan chiqarish" if blk else "🚫 Bloklash",
        callback_data=f"adm_block_{uid_str}"
    ))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_users"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("adm_block_"))
async def adm_block_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    uid_str = callback.data[10:]
    users   = ram.get_users()
    u       = users.get(str(uid_str), {})
    new_blk = not u.get("is_blocked", False)
    block_user(int(uid_str), new_blk)
    await callback.answer("🚫 Bloklandi" if new_blk else "✅ Blok ochildi", show_alert=True)
    await adm_user_detail(callback)


# ══ TESTLAR — FANLAR BO'YICHA ══════════════════════════════════
@router.callback_query(F.data == "admin_tests")
async def admin_tests(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    await _show_admin_test_cats(callback.message, edit=True)

@router.callback_query(F.data == "adm_back_to_cats")
async def adm_back_cats(callback: CallbackQuery):
    await callback.answer()
    await _show_admin_test_cats(callback.message, edit=True)

async def _show_admin_test_cats(msg, edit=False):
    tests = ram.get_all_tests_meta()
    cats  = {}
    for t in tests:
        c = t.get("category") or "Boshqa"
        if c not in cats:
            cats[c] = {"total": 0, "active": 0, "paused": 0, "deleted": 0}
        cats[c]["total"] += 1
        if not t.get("is_active", True):
            cats[c]["deleted"] += 1
        elif t.get("is_paused"):
            cats[c]["paused"] += 1
        else:
            cats[c]["active"] += 1

    sorted_cats = sorted(cats.items(), key=lambda x: x[1]["total"], reverse=True)
    text = (
        f"📋 <b>TESTLAR — FANLAR BO'YICHA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Jami: {len(tests)} ta test | {len(cats)} ta fan</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for cat, info in sorted_cats:
        icon  = CAT_ICONS.get(cat, "📋")
        parts = []
        if info["active"]:  parts.append(f"✅{info['active']}")
        if info["paused"]:  parts.append(f"⏸{info['paused']}")
        if info["deleted"]: parts.append(f"🗑{info['deleted']}")
        stat  = " ".join(parts)
        text += f"{icon} <b>{cat}</b> — {info['total']} ta ({stat})\n"
        b.row(InlineKeyboardButton(
            text=f"{icon} {cat} — {info['total']} ta",
            callback_data=f"adm_cat_{cat[:30]}_0"
        ))
    b.row(InlineKeyboardButton(text="🌟 Hammasi", callback_data="adm_cat_ALL_0"))
    b.row(InlineKeyboardButton(text="⬅️ Admin",   callback_data="admin_panel"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("adm_cat_"))
async def adm_cat_tests(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    raw   = callback.data[8:]
    parts = raw.rsplit("_", 1)
    cat   = parts[0]
    page  = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    await _show_adm_cat_tests(callback.message, cat, page, edit=True)

async def _show_adm_cat_tests(msg, cat_name, page=0, edit=False):
    tests = ram.get_all_tests_meta()
    if cat_name != "ALL":
        tests = [t for t in tests if t.get("category") == cat_name]
    PG    = 8
    total = (len(tests)+PG-1)//PG
    page  = max(0, min(page, total-1))
    chunk = tests[page*PG:(page+1)*PG]
    title = "🌟 BARCHA TESTLAR" if cat_name == "ALL" else f"📋 {cat_name.upper()}"
    vis_m = {"public":"🌍","link":"🔗","private":"🔒"}
    diff_m= {"easy":"🟢","medium":"🟡","hard":"🔴","expert":"⚡"}

    text = (
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{len(tests)} ta | Sahifa {page+1}/{total}</i>\n\n"
    )
    b = InlineKeyboardBuilder()
    for t in chunk:
        tid   = t.get("test_id","")
        title_t = t.get("title","?")[:18]
        active  = t.get("is_active", True)
        paused  = t.get("is_paused", False)
        sc    = t.get("solve_count", 0)
        vis   = vis_m.get(t.get("visibility",""), "")
        diff  = diff_m.get(t.get("difficulty",""), "")
        icon  = "🗑" if not active else ("⏸" if paused else "✅")
        text += f"{icon}{vis}{diff} <b>{title_t}</b> <code>[{tid}]</code> | 👥{sc}\n"
        b.row(InlineKeyboardButton(
            text=f"{icon} {title_t[:20]} [{tid}]",
            callback_data=f"adm_test_{tid}"
        ))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_cat_{cat_name}_{page-1}"))
    if page < total-1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_cat_{cat_name}_{page+1}"))
    if nav: b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Fanlar", callback_data="adm_back_to_cats"))
    try:
        if edit: await msg.edit_text(text, reply_markup=b.as_markup())
        else:    await msg.answer(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("adm_test_"))
async def adm_test_detail(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    tid  = callback.data[9:]
    meta = ram.get_test_meta(tid) or {}
    if not meta:
        # O'chirilgan test — all_tests_meta dan qidirish
        meta = next((t for t in ram.get_all_tests_meta() if t.get("test_id")==tid), {})
    if not meta:
        return await callback.answer("❌ Test topilmadi", show_alert=True)

    active = meta.get("is_active", True)
    paused = meta.get("is_paused", False)
    vis_m  = {"public":"🌍 Ommaviy","link":"🔗 Ssilka","private":"🔒 Shaxsiy"}
    diff_m = {"easy":"🟢","medium":"🟡","hard":"🔴","expert":"⚡"}

    text = (
        f"🔍 <b>TEST BATAFSIL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{'🗑 <b>O\'CHIRILGAN</b>\n\n' if not active else ''}"
        f"{'⏸ <b>PAUZADA</b>\n\n' if paused else ''}"
        f"📝 <b>{meta.get('title','?')}</b>\n"
        f"🆔 <code>{tid}</code>\n"
        f"📁 {meta.get('category','')}\n"
        f"📊 {diff_m.get(meta.get('difficulty',''),'')}\n"
        f"🔒 {vis_m.get(meta.get('visibility',''),'')}\n"
        f"📋 {meta.get('question_count',0)} savol\n"
        f"👥 {meta.get('solve_count',0)} yechgan\n"
        f"⭐ {round(meta.get('avg_score',0),1)}%\n"
        f"👤 Creator: <code>{meta.get('creator_id','?')}</code>"
    )
    b = InlineKeyboardBuilder()
    if active:
        b.row(InlineKeyboardButton(
            text="▶️ Davom ettirish" if paused else "⏸ To'xtatish",
            callback_data=f"{'test_resume' if paused else 'test_pause'}_{tid}"
        ))
        b.row(InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del_test_{tid}"))
    cat = meta.get("category","")[:30]
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"adm_cat_{cat}_0"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("del_test_"))
async def del_test_confirm(callback: CallbackQuery):
    await callback.answer()   # Telegram timeoutni oldini olish
    if not is_admin(callback.from_user.id):
        return
    tid  = callback.data[9:]
    meta = ram.get_test_meta(tid) or {}
    if not meta:
        meta = next((t for t in ram.get_all_tests_meta() if t.get("test_id")==tid), {})
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"del_confirm_{tid}"),
        InlineKeyboardButton(text="❌ Yo'q",          callback_data=f"adm_test_{tid}"),
    )
    try:
        await callback.message.edit_text(
            f"⚠️ <b>O'CHIRISH TASDIQLASH</b>\n\n"
            f"📝 {meta.get('title','?')} [{tid}]\n\n"
            f"TG ga backup yuboriladi. Qaytarib bo'lmaydi!",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest: pass

@router.callback_query(F.data.startswith("del_confirm_"))
async def del_test_exec(callback: CallbackQuery):
    await callback.answer("⏳ O'chirilmoqda...")   # DARHOL javob
    if not is_admin(callback.from_user.id):
        return
    tid  = callback.data[12:]
    meta = ram.get_test_meta(tid) or {}
    from utils.db import delete_test
    await delete_test(tid)
    try:
        await callback.message.edit_text(
            f"✅ <b>{meta.get('title','?')} [{tid}]</b>\n\n"
            f"🗑 RAMdan o'chirildi\n"
            f"🗑 Katalogdan yashirildi\n"
            f"✅ TG kanalda backup saqlanadi"
        )
    except: pass
    await _show_admin_test_cats(callback.message)


# ══ BROADCAST ══════════════════════════════════════════════════
@router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="admin_panel"))
    try:
        await callback.message.edit_text(
            "📢 <b>BROADCAST</b>\n\nXabar yozing (HTML qo'llab-quvvatlanadi):",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest: pass
    await state.set_state(AdminPanel.broadcast)

@router.message(AdminPanel.broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    users   = ram.get_users()
    sent = ok = fail = 0
    status = await message.answer(f"⏳ <b>Yuborilmoqda...</b> 0/{len(users)}")
    for uid_str, u in users.items():
        if u.get("is_blocked"): continue
        try:
            await message.bot.send_message(int(uid_str), message.text or message.caption or "")
            ok += 1
        except Exception:
            fail += 1
        sent += 1
        if sent % 20 == 0:
            try:
                await status.edit_text(f"⏳ {sent}/{len(users)} | ✅{ok} ❌{fail}")
            except: pass
    await state.clear()
    try:
        await status.edit_text(
            f"✅ <b>Broadcast tugadi</b>\n\n"
            f"✅ Yuborildi: {ok}\n❌ Xato: {fail}\n📊 Jami: {sent}"
        )
    except: pass


# ══ FLUSH / REFRESH ════════════════════════════════════════════
@router.callback_query(F.data == "adm_flush")
async def adm_flush(callback: CallbackQuery):
    await callback.answer("⏳ Yuborilmoqda...")
    if not is_admin(callback.from_user.id): return
    from utils import tg_db
    results = await tg_db.manual_flush(
        ram.get_daily(), ram.get_users(), ram.get_all_settings()
    )
    text = "⚡ <b>MANUAL FLUSH</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n" + "\n".join(results)
    b    = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())

@router.callback_query(F.data == "adm_refresh")
async def adm_refresh(callback: CallbackQuery):
    await callback.answer("⏳ Sync qilinmoqda...")
    if not is_admin(callback.from_user.id): return
    from utils import tg_db
    from utils.db import _sync_from_tg
    try:
        await _sync_from_tg()
        text = "🔄 <b>SYNC TUGADI</b>\n\nRAM TGdan yangilandi."
    except Exception as e:
        text = f"❌ Sync xato: {e}"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())

@router.callback_query(F.data == "adm_export_json")
async def adm_export_json(callback: CallbackQuery):
    await callback.answer("⏳")
    if not is_admin(callback.from_user.id): return
    data = {
        "tests_meta": ram.get_all_tests_meta(),
        "users_count": len(ram.get_users()),
        "daily_users": len(ram.get_daily()),
        "exported_at": str(datetime.now(UTC))
    }
    doc = BufferedInputFile(
        json.dumps(data, ensure_ascii=False, indent=2, default=str).encode(),
        filename=f"export_{datetime.now(UTC).strftime('%Y%m%d_%H%M')}.json"
    )
    await callback.message.answer_document(doc, caption="💾 Export")

@router.callback_query(F.data == "adm_backups")
async def adm_backups(callback: CallbackQuery):
    await callback.answer()
    if not is_admin(callback.from_user.id): return
    from utils import tg_db
    dates = tg_db.get_backup_dates()
    info  = tg_db.get_index_info()
    text  = (
        f"🗂 <b>BACKUPLAR</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Jami: {len(dates)} ta\n"
        f"📋 Testlar: {info.get('tests_count',0)} | Cache: {info.get('cached_tests',0)}\n\n"
    )
    for d in dates[:10]:
        text += f"💾 {d}\n"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_panel"))
    try: await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text, reply_markup=b.as_markup())
