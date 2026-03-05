"""👑 ADMIN PANEL — to'liq versiya"""
import asyncio, logging, json
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import ADMIN_IDS
from utils.db import get_all_users, get_all_tests, block_user, delete_test, get_test
from utils.ram_cache import get_daily, clear_daily, refresh_tests, stats as ram_stats
from utils.states import AdminPanel
from keyboards.keyboards import main_kb, admin_kb

log    = logging.getLogger(__name__)
router = Router()


def _is_admin(uid): return uid in ADMIN_IDS


# ══ 1. PANEL KIRISH ════════════════════════════════════

@router.message(F.text == "👑 Admin Panel")
async def admin_panel_msg(message: Message, state: FSMContext):
    await state.clear()
    if not _is_admin(message.from_user.id): return
    await message.answer(
        "<b>👑 ADMIN PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Bo'limdan birini tanlang:",
        reply_markup=admin_kb()
    )

@router.callback_query(F.data == "admin_panel")
async def admin_panel_cb(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫 Ruxsat yo'q!", show_alert=True)
    await state.clear()
    await callback.answer()
    try:
        await callback.message.edit_text(
            "<b>👑 ADMIN PANEL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Bo'limdan birini tanlang:",
            reply_markup=admin_kb()
        )
    except TelegramBadRequest:
        pass


# ══ 2. STATISTIKA ══════════════════════════════════════

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    await callback.answer("⏳")

    s       = ram_stats()
    users   = get_all_users()
    tests   = get_all_tests()
    blocked = sum(1 for u in users if u.get("is_blocked"))
    scores  = [u.get("avg_score", 0) for u in users if u.get("total_tests", 0) > 0]
    avg_sc  = round(sum(scores) / len(scores), 1) if scores else 0.0
    pass_r  = round(sum(1 for sc in scores if sc >= 60) / len(scores) * 100, 1) if scores else 0.0

    from utils import tg_db
    tg_info = tg_db.get_index_info() if tg_db.ready() else {}

    text = (
        f"📈 <b>TIZIM STATISTIKASI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Foydalanuvchilar: <b>{len(users)} ta</b>\n"
        f"🔴 Bloklangan: <b>{blocked} ta</b>\n"
        f"📋 Testlar: <b>{len(tests)} ta</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 O'rtacha natija: <b>{avg_sc}%</b>\n"
        f"✅ Muvaffaqiyat (≥60%): <b>{pass_r}%</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💾 RAM: <b>{s['mb']} MB</b> ({s['pct']}%)\n"
        f"📋 Test meta: <b>{s['tests']} ta</b>\n"
        f"🔵 Savollar cache: <b>{s.get('cached_q', 0)} ta</b>\n"
        f"👥 Userlar: <b>{s['users']} ta</b>\n"
        f"📊 Kunlik natijalar: <b>{s['daily_r']} ta</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 TG Kanal: {'✅ Ulangan' if tg_db.ready() else '❌ Ulanmagan'}\n"
        f"💾 Backuplar: <b>{tg_info.get('backups', 0)} ta</b>"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin_stats"))
    b.row(InlineKeyboardButton(text="◀️ Panel", callback_data="admin_panel"))
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=b.as_markup())


# ══ 3. FOYDALANUVCHILAR ════════════════════════════════

@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    await callback.answer("⏳")

    users = get_all_users()
    if not users:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="◀️ Panel", callback_data="admin_panel"))
        return await callback.message.answer("❌ Foydalanuvchilar yo'q.", reply_markup=b.as_markup())

    lines = ["ID | ISM | TESTLAR | O'RTACHA | HOLAT", "─" * 55]
    for u in users:
        uid   = u.get("tg_id") or u.get("telegram_id", "?")
        name  = u.get("name", "Ismsiz")[:20]
        tc    = u.get("total_tests", 0)
        avg   = round(u.get("avg_score", 0), 1)
        holat = "🔴 Bloklangan" if u.get("is_blocked") else "🟢 Faol"
        lines.append(f"{uid} | {name} | {tc} | {avg}% | {holat}")

    doc = BufferedInputFile("\n".join(lines).encode("utf-8"), filename="Foydalanuvchilar.txt")
    await callback.message.answer_document(
        doc,
        caption=f"<b>👥 FOYDALANUVCHILAR</b>\nJami: <b>{len(users)} ta</b>"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🚫 Bloklash/Ochish", callback_data="admin_block"))
    b.row(InlineKeyboardButton(text="◀️ Panel", callback_data="admin_panel"))
    await callback.message.answer("Qo'shimcha amallar:", reply_markup=b.as_markup())


# ══ 4. TESTLAR ═════════════════════════════════════════

@router.callback_query(F.data == "admin_tests")
async def admin_tests(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    await callback.answer("⏳")

    tests = get_all_tests()
    if not tests:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="◀️ Panel", callback_data="admin_panel"))
        return await callback.message.answer("❌ Testlar yo'q.", reply_markup=b.as_markup())

    lines = ["KOD | FAN | MAVZU | SAVOLLAR | ISHLANGAN", "─" * 55]
    for t in tests:
        tid   = t.get("test_id", "?")
        cat   = t.get("category", "Boshqa")[:15]
        title = t.get("title", "Nomsiz")[:25]
        qc    = t.get("question_count", len(t.get("questions", [])))
        sc    = t.get("solve_count", 0)
        lines.append(f"{tid} | {cat} | {title} | {qc} ta | {sc} marta")

    doc = BufferedInputFile("\n".join(lines).encode("utf-8"), filename="Testlar.txt")
    await callback.message.answer_document(
        doc,
        caption=f"<b>📋 TESTLAR</b>\nJami: <b>{len(tests)} ta</b>"
    )
    b = InlineKeyboardBuilder()
    for t in tests[:8]:
        tid   = t.get("test_id", "")
        title = t.get("title", "Nomsiz")[:20]
        b.row(InlineKeyboardButton(
            text=f"📄 {title} [{tid}]",
            callback_data=f"admin_dl_{tid}"
        ))
    b.row(InlineKeyboardButton(text="🗑 Test o'chirish", callback_data="admin_del_test"))
    b.row(InlineKeyboardButton(text="◀️ Panel", callback_data="admin_panel"))
    await callback.message.answer("<b>📄 Test TXT yuklab olish:</b>", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("admin_dl_"))
async def admin_download_test(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    await callback.answer("⏳ TXT tayyorlanmoqda...")
    tid  = callback.data[9:]
    from utils.db import get_test_full as _gtf
    test = await _gtf(tid)
    if not test: test = get_test(tid)
    if not test:
        return await callback.message.answer("❌ Test topilmadi.")
    from handlers.profile import _test_to_txt
    txt = _test_to_txt(test)
    doc = BufferedInputFile(txt.encode("utf-8"), filename=f"{test.get('title', tid)}.txt")
    await callback.message.answer_document(
        doc,
        caption=f"📄 <b>{test.get('title')}</b>\n📋 {len(test.get('questions', []))} savol\n🆔 <code>{tid}</code>"
    )


# ══ 5. BROADCAST ═══════════════════════════════════════

@router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    await callback.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_panel"))
    try:
        await callback.message.edit_text(
            "<b>📢 BARCHA FOYDALANUVCHILARGA XABAR</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Xabaringizni yozing:\n"
            "<i>(matn, rasm, video, fayl qabul qilinadi)</i>",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        pass
    await state.set_state(AdminPanel.broadcast)

@router.message(AdminPanel.broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id): return
    status = await message.answer("⏳ Tarqatish boshlandi...")
    users  = get_all_users()
    ok = fail = 0
    for u in users:
        uid = u.get("tg_id") or u.get("telegram_id")
        if not uid or u.get("is_blocked"): continue
        try:
            await message.bot.copy_message(uid, message.chat.id, message.message_id)
            ok += 1
        except TelegramForbiddenError:
            block_user(uid, True); fail += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await state.clear()
    await status.edit_text(
        f"<b>✅ TARQATISH YAKUNLANDI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢 Muvaffaqiyatli: <b>{ok} ta</b>\n"
        f"🔴 Yetkazilmadi: <b>{fail} ta</b>"
    )


# ══ 6. BLOKLASH ════════════════════════════════════════

@router.callback_query(F.data == "admin_block")
async def block_start(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id): return
    await callback.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_panel"))
    try:
        await callback.message.edit_text(
            "<b>🚫 BLOKLASH / OCHISH</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Foydalanuvchi <b>Telegram ID</b> ni yuboring:",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        pass
    await state.set_state(AdminPanel.block_user)

@router.message(AdminPanel.block_user)
async def block_process(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id): return
    t = message.text.strip().lstrip("-")
    if not t.isdigit():
        return await message.answer("❌ Faqat Telegram ID raqam kiriting.")
    uid   = int(t)
    users = get_all_users()
    user  = next((u for u in users
                  if (u.get("tg_id") or u.get("telegram_id")) == uid), None)
    if not user:
        return await message.answer("❌ Foydalanuvchi topilmadi.")
    new_status = not user.get("is_blocked", False)
    block_user(uid, new_status)
    await state.clear()
    txt = "🔴 BLOKLANDI" if new_status else "🟢 BLOKDAN CHIQARILDI"
    await message.answer(
        f"<b>✅ BAJARILDI</b>\n"
        "👤 " + str(user.get("name", "Noma'lum")) + "\n"
        f"🆔 <code>{uid}</code>\n"
        f"Holat: <b>{txt}</b>"
    )


# ══ 7. TEST O'CHIRISH ══════════════════════════════════

@router.callback_query(F.data == "admin_del_test")
async def del_test_start(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id): return
    await callback.answer()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_panel"))
    try:
        await callback.message.edit_text(
            "<b>🗑 TESTNI O'CHIRISH</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Test <b>KODINI</b> yuboring:\n"
            "<i>⚠️ Bu amalni qaytarib bo'lmaydi! RAM + TG kanaldan o'chiriladi.</i>",
            reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        pass
    await state.set_state(AdminPanel.delete_test)

@router.message(AdminPanel.delete_test)
async def del_test_process(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id): return
    tid  = message.text.strip().upper()
    test = get_test(tid)
    if not test:
        return await message.answer("❌ Bu kodli test topilmadi.")

    # RAM dan o'chirish
    import utils.ram_cache as ram
    ram.delete_test_from_ram(tid)

    # TG kanaldan o'chirish
    await delete_test(tid)

    await state.clear()
    await message.answer(
        f"<b>✅ TEST TO'LIQ O'CHIRILDI</b>\n"
        f"🗑 Kod: <code>{tid}</code>\n"
        f"📝 Mavzu: {test.get('title', '?')}\n\n"
        f"<i>RAM va TG kanaldan o'chirildi.</i>"
    )


# ══ 8. RAM FLUSH (RAM → TG) ════════════════════════════

@router.callback_query(F.data == "adm_flush")
async def admin_flush(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    await callback.answer("⏳")
    status_msg = await callback.message.answer("⏳ RAM → TG yuborilmoqda...")
    try:
        from utils import tg_db
        from utils import ram_cache as ram
        from datetime import date, datetime

        if not tg_db.ready():
            return await status_msg.edit_text("❌ TG kanal ulanmagan.")

        results = []

        # Userlar
        users = ram.get_users()
        ok2   = await tg_db.save_users(users)
        if ok2: ram.clear_users_dirty()
        results.append(f"{'✅' if ok2 else '❌'} Userlar: {len(users)} ta")

        # Settings
        settings = ram.get_all_settings()
        if settings:
            ok_s = await tg_db.save_settings(settings)
            results.append(f"{'✅' if ok_s else '❌'} Settings: {len(settings)} ta")

        # Backup
        daily = ram.get_daily()
        if daily:
            today = str(date.today())
            slot  = "12" if datetime.now().hour >= 12 else "00"
            mid   = await tg_db.upload_backup(daily, today, slot)
            if mid:
                results.append(f"✅ Backup ({today}_{slot}): {len(daily)} user")
            else:
                results.append("❌ Backup xato!")
        else:
            results.append("ℹ️ Kunlik natijalar bo'sh")

        await status_msg.edit_text(
            f"<b>✅ RAM FLUSH NATIJASI</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n".join(results)
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Flush xatosi: {e}")


# ══ 9. TG → RAM REFRESH ════════════════════════════════

@router.callback_query(F.data == "adm_refresh")
async def admin_refresh(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    await callback.answer("⏳")
    status = await callback.message.answer("⏳ TG → RAM yangilanmoqda...")
    try:
        from utils import tg_db
        from utils import ram_cache as ram
        if not tg_db.ready():
            return await status.edit_text("❌ TG kanal ulanmagan.")

        tests = await tg_db.get_tests()
        if tests: ram.set_tests(tests)

        users = await tg_db.get_users()
        if users: ram.set_users(users)

        settings = await tg_db.get_settings_tg()
        if settings: ram.set_all_settings(settings)

        ram.clear_expired_cache()
        info = tg_db.get_index_info()

        await status.edit_text(
            f"✅ <b>Cache yangilandi!</b>\n"
            f"📋 {len(tests) if tests else 0} test meta\n"
            f"👥 {len(users) if users else 0} user\n"
            f"⚙️ {len(settings) if settings else 0} settings\n"
            f"💾 Backup: {info.get('backups', 0)} ta"
        )
    except Exception as e:
        await status.edit_text(f"❌ Xato: {e}")


# ══ 10. JSON EXPORT ════════════════════════════════════

@router.callback_query(F.data == "adm_export_json")
async def admin_export_json(callback: CallbackQuery):
    """To'liq bazani JSON fayl sifatida yuborish"""
    if not _is_admin(callback.from_user.id):
        return await callback.answer("🚫", show_alert=True)
    await callback.answer("⏳ JSON tayyorlanmoqda...")
    status = await callback.message.answer("⏳ <b>JSON fayl tayyorlanmoqda...</b>")

    try:
        from utils import ram_cache as ram
        from utils import tg_db
        from datetime import datetime, timezone

        # RAM dan to'liq ma'lumotlar
        export_data = {
            "exported_at": str(datetime.now(timezone.utc)),
            "tests_meta":  ram.get_tests_meta(),
            "users":       ram.get_users(),
            "settings":    ram.get_all_settings(),
            "daily_results": ram.get_daily(),
            "tg_index":    tg_db.get_index_info() if tg_db.ready() else {},
            "backup_dates": tg_db.get_backup_dates() if tg_db.ready() else [],
        }

        raw = json.dumps(export_data, ensure_ascii=False, default=str, indent=2).encode("utf-8")
        doc = BufferedInputFile(raw, filename=f"quizbot_export_{datetime.now().strftime('%Y%m%d_%H%M')}.json")

        await status.delete()
        await callback.message.answer_document(
            doc,
            caption=(
                f"💾 <b>TO'LIQ BAZA EXPORT</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📋 Testlar: <b>{len(export_data['tests_meta'])} ta</b>\n"
                f"👥 Userlar: <b>{len(export_data['users'])} ta</b>\n"
                f"📊 Kunlik: <b>{len(export_data['daily_results'])} user</b>\n\n"
                f"<i>Bu faylni saqlang — backup uchun ishlatiladi.</i>"
            )
        )
    except Exception as e:
        await status.edit_text(f"❌ Export xatosi: {e}")
