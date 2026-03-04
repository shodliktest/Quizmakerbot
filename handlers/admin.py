"""👑 ADMIN PANEL"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from config import ADMIN_IDS
from utils import store
from utils.states import Admin
from keyboards.kb import admin_kb, main_kb, cancel_kb

log    = logging.getLogger(__name__)
router = Router()


def _is_admin(uid): return uid in ADMIN_IDS


# ═══════════════════════════════════════════════════════════
# KIRISH
# ═══════════════════════════════════════════════════════════

@router.message(F.text == "👑 Admin Panel")
@router.message(Command("admin"))
async def admin_panel(msg: Message):
    if not _is_admin(msg.from_user.id):
        return
    await msg.answer("👑 <b>ADMIN PANEL</b>", reply_markup=admin_kb())


@router.callback_query(F.data == "adm_back")
async def adm_back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    try: await cb.message.edit_text("👑 <b>ADMIN PANEL</b>", reply_markup=admin_kb())
    except: pass


# ═══════════════════════════════════════════════════════════
# STATISTIKA
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm_stats")
async def adm_stats(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("❌")
    await cb.answer()

    users     = store.get_all_users()
    tests     = store.get_all_tests()
    sessions  = len(store._sessions)
    blocked   = sum(1 for u in users if u.get("is_blocked"))
    tg_status = "✅ Ulangan" if store.tg_ready() else "❌ Ulanmagan"

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Yangilash", callback_data="adm_stats"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga",   callback_data="adm_back"))

    await cb.message.edit_text(
        f"📈 <b>STATISTIKA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Foydalanuvchilar: <b>{len(users)}</b>\n"
        f"   🚫 Bloklangan: {blocked}\n\n"
        f"📋 Testlar: <b>{len(tests)}</b>\n"
        f"🟢 Faol sessiyalar: <b>{sessions}</b>\n\n"
        f"💾 TG kanal: {tg_status}",
        reply_markup=b.as_markup()
    )


# ═══════════════════════════════════════════════════════════
# FOYDALANUVCHILAR
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm_users")
async def adm_users(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("❌")
    await cb.answer()

    users = store.get_all_users()
    text  = f"👥 <b>FOYDALANUVCHILAR</b> — {len(users)} ta\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for u in users[:30]:
        status = "🚫" if u.get("is_blocked") else "✅"
        uname  = f"@{u.get('username')}" if u.get("username") else "—"
        text  += f"{status} {u.get('name','?')} | {uname} | <code>{u.get('uid','?')}</code>\n"
    if len(users) > 30:
        text += f"\n<i>...va yana {len(users)-30} ta</i>"

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm_back"))
    try: await cb.message.edit_text(text, reply_markup=b.as_markup())
    except: pass


# ═══════════════════════════════════════════════════════════
# TESTLAR
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm_tests")
async def adm_tests(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("❌")
    await cb.answer()

    tests = store.get_all_tests()
    text  = f"📋 <b>BARCHA TESTLAR</b> — {len(tests)} ta\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tests[:20]:
        vis = {"public":"🌍","link":"🔗","private":"🔒"}.get(t.get("visibility",""), "")
        qc  = t.get("question_count", len(t.get("questions", [])))
        text += (
            f"{vis} <b>{t.get('title','?')}</b>\n"
            f"   📋 {qc} savol | 👥 {t.get('solve_count',0)}x | <code>{t.get('test_id')}</code>\n\n"
        )
    if len(tests) > 20:
        text += f"<i>...va yana {len(tests)-20} ta</i>"

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm_back"))
    try: await cb.message.edit_text(text, reply_markup=b.as_markup())
    except: pass


# ═══════════════════════════════════════════════════════════
# BROADCAST
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm_broadcast")
async def adm_broadcast_start(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("❌")
    await cb.answer()
    await cb.message.answer(
        "📢 <b>XABAR TARQATISH</b>\n\n"
        "Barcha foydalanuvchilarga yuboriladigan xabarni yuboring:",
        reply_markup=cancel_kb()
    )
    await state.set_state(Admin.broadcast)


@router.message(Admin.broadcast)
async def adm_broadcast_send(msg: Message, state: FSMContext):
    await state.clear()
    users = store.get_all_users()
    ok = fail = 0
    status = await msg.answer(f"📤 <b>Yuborilmoqda...</b> 0/{len(users)}")

    for i, u in enumerate(users):
        if u.get("is_blocked"):
            continue
        try:
            await msg.copy_to(u["uid"])
            ok += 1
        except:
            fail += 1
        if i % 20 == 0:
            try:
                await status.edit_text(f"📤 <b>Yuborilmoqda...</b> {i+1}/{len(users)}")
            except: pass

    await status.edit_text(
        f"✅ <b>Broadcast yakunlandi</b>\n\n"
        f"✅ Yuborildi: {ok}\n"
        f"❌ Yuborilmadi: {fail}"
    )


# ═══════════════════════════════════════════════════════════
# BLOKLASH / OCHISH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm_block")
async def adm_block_start(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("❌")
    await cb.answer()
    await cb.message.answer(
        "🚫 <b>BLOKLASH / OCHISH</b>\n\n"
        "Foydalanuvchi ID sini yuboring:",
        reply_markup=cancel_kb()
    )
    await state.set_state(Admin.block_user)


@router.message(Admin.block_user)
async def adm_block_do(msg: Message, state: FSMContext):
    await state.clear()
    text = (msg.text or "").strip()
    if not text.lstrip("-").isdigit():
        return await msg.answer("❌ ID raqam bo'lishi kerak.")

    uid  = int(text)
    user = store.get_user(uid)
    if not user:
        return await msg.answer("❌ Foydalanuvchi topilmadi.")

    new_status = not user.get("is_blocked", False)
    user["is_blocked"] = new_status
    store.upsert_user(uid, user)

    action = "🚫 Bloklandi" if new_status else "✅ Blok ochildi"
    await msg.answer(
        f"{action}\n\n"
        f"👤 {user.get('name','?')} | <code>{uid}</code>",
        reply_markup=admin_kb()
    )


# ═══════════════════════════════════════════════════════════
# TEST O'CHIRISH
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm_del_test")
async def adm_del_start(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("❌")
    await cb.answer()
    await cb.message.answer(
        "🗑 <b>TEST O'CHIRISH</b>\n\nTest ID sini yuboring:",
        reply_markup=cancel_kb()
    )
    await state.set_state(Admin.delete_test)


@router.message(Admin.delete_test)
async def adm_del_do(msg: Message, state: FSMContext):
    await state.clear()
    tid  = (msg.text or "").strip().upper()
    test = store.get_test(tid)
    if not test:
        return await msg.answer("❌ Test topilmadi.")
    import asyncio
    asyncio.create_task(store.delete_test(tid))
    await msg.answer(
        f"🗑 <b>O'chirildi:</b> {test.get('title','?')}\n<code>{tid}</code>",
        reply_markup=admin_kb()
    )


# ═══════════════════════════════════════════════════════════
# FLUSH (saqlash)
# ═══════════════════════════════════════════════════════════

@router.callback_query(F.data == "adm_flush")
async def adm_flush(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("❌")
    await cb.answer("💾 Saqlanmoqda...")

    import asyncio
    status = await cb.message.answer("💾 <b>Saqlanmoqda...</b>")
    ok_u = await store.save_users_tg()
    ok_r = await store.save_results_tg()

    await status.edit_text(
        f"💾 <b>SAQLANDI</b>\n\n"
        f"👥 Userlar: {'✅' if ok_u else '❌ (kanal yo\'q)'}\n"
        f"📊 Natijalar: {'✅' if ok_r else '❌ (kanal yo\'q)'}"
    )
