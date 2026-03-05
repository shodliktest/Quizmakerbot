"""⌨️ BARCHA KLAVIATURALAR — Yagona manba"""
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton,
                            ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import SUBJECTS, DIFFICULTY_LEVELS

COLORS = ["🔵", "🟣", "🟢", "🔴", "🟡", "🟠", "⚪", "⚫", "🔷", "🔶"]


def main_kb(uid=None, chat_type="private"):
    if chat_type != "private":
        return ReplyKeyboardRemove()
    kb = [
        [KeyboardButton(text="📚 Testlar"),         KeyboardButton(text="➕ Test Yaratish")],
        [KeyboardButton(text="📊 Natijalarim"),      KeyboardButton(text="🏆 Reyting")],
        [KeyboardButton(text="🗂 Mening testlarim"), KeyboardButton(text="👤 Profil")],
        [KeyboardButton(text="ℹ️ Yordam")],
    ]
    if uid:
        from config import ADMIN_IDS
        if uid in ADMIN_IDS:
            kb.append([KeyboardButton(text="👑 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def subject_kb():
    b = InlineKeyboardBuilder()
    for s in SUBJECTS:
        b.add(InlineKeyboardButton(text=s, callback_data=f"subj_{s}"))
    b.adjust(2)
    b.row(InlineKeyboardButton(text="✏️ Boshqa",  callback_data="subj_other"))
    b.row(InlineKeyboardButton(text="❌ Bekor",    callback_data="cancel_create"))
    return b.as_markup()


def difficulty_kb():
    b = InlineKeyboardBuilder()
    icons = {"easy": "🟢", "medium": "🟡", "hard": "🔴", "expert": "⚡"}
    for k, v in DIFFICULTY_LEVELS.items():
        b.add(InlineKeyboardButton(text=f"{icons.get(k,'')} {v}", callback_data=f"diff_{k}"))
    b.adjust(2)
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_create"))
    return b.as_markup()


def visibility_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🌍 Ommaviy",       callback_data="vis_public"))
    b.row(InlineKeyboardButton(text="🔗 Ssilka orqali", callback_data="vis_link"))
    b.row(InlineKeyboardButton(text="🔒 Shaxsiy",       callback_data="vis_private"))
    b.row(InlineKeyboardButton(text="❌ Bekor",          callback_data="cancel_create"))
    return b.as_markup()


def test_info_kb(tid, bot_username=""):
    """Test kartochkasi tugmalari — private va guruh uchun"""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Inline test",  callback_data=f"start_test_{tid}"),
        InlineKeyboardButton(text="📊 Poll test",    callback_data=f"start_poll_{tid}"),
    )
    b.row(
        InlineKeyboardButton(text="📤 Guruhga yuborish",  switch_inline_query=f"test_{tid}"),
        InlineKeyboardButton(text="👥 Guruhda boshlash",  callback_data=f"group_info_{tid}"),
    )
    b.row(
        InlineKeyboardButton(text="🏆 Reyting", callback_data=f"lb_test_{tid}"),
        InlineKeyboardButton(text="🏠 Menyu",   callback_data="main_menu"),
    )
    return b.as_markup()


def result_kb(tid, rid):
    """Test yakunlanganidan keyingi tugmalar"""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔍 Batafsil tahlil", callback_data=f"analysis_{rid}_0"))
    b.row(
        InlineKeyboardButton(text="🔄 Qaytadan",   callback_data=f"start_test_{tid}"),
        InlineKeyboardButton(text="📊 Poll rejim", callback_data=f"start_poll_{tid}"),
    )
    b.row(InlineKeyboardButton(text="📤 Ulashish", switch_inline_query=f"test_{tid}"))
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
    return b.as_markup()


def answer_kb(letters):
    b = InlineKeyboardBuilder()
    for i, l in enumerate(letters):
        icon = COLORS[i] if i < len(COLORS) else "▫️"
        b.add(InlineKeyboardButton(text=f"{icon} {l}", callback_data=f"ans_{l}"))
    b.adjust(len(letters))
    return b.as_markup()


def next_q_kb(remaining_sec=30):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text=f"⏭ Keyingi savol ({remaining_sec}s)",
        callback_data="next_now"
    ))
    b.row(InlineKeyboardButton(text="❌ To'xtatish", callback_data="cancel_test"))
    return b.as_markup()


def next_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➡️ Keyingi savol", callback_data="next_q"))
    b.row(InlineKeyboardButton(text="❌ To'xtatish",     callback_data="cancel_test"))
    return b.as_markup()


def poll_cancel_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏹ To'xtatish", callback_data="cancel_poll"))
    return b.as_markup()


def poll_pause_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="▶️ Davom etish",     callback_data="resume_poll"))
    b.row(InlineKeyboardButton(text="❌ Testni yakunlash", callback_data="cancel_poll"))
    return b.as_markup()


def analysis_kb(rid, page, total):
    """Tahlil navigatsiya tugmalari — oxirgi sahifada 'Bosh sahifa'"""
    b = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"analysis_{rid}_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"analysis_{rid}_{page+1}"))
    b.row(*nav)
    # Natijaga qaytish — doim ko'rinadi
    b.row(InlineKeyboardButton(text="⬅️ Natijaga qaytish", callback_data=f"res_back_{rid}"))
    # Oxirgi sahifada yoki istalgan sahifada Bosh sahifa ham ko'rinadi
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
    return b.as_markup()


def admin_kb():
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="👥 Userlar",    callback_data="admin_users"),
        InlineKeyboardButton(text="📋 Testlar",    callback_data="admin_tests"),
    )
    b.row(
        InlineKeyboardButton(text="📈 Statistika", callback_data="admin_stats"),
        InlineKeyboardButton(text="📢 Broadcast",  callback_data="admin_broadcast"),
    )
    b.row(
        InlineKeyboardButton(text="⚡ RAM → TG",       callback_data="adm_flush"),
        InlineKeyboardButton(text="🔄 TG → RAM",       callback_data="adm_refresh"),
    )
    b.row(
        InlineKeyboardButton(text="💾 JSON yuklab ol", callback_data="adm_export_json"),
    )
    b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))
    return b.as_markup()


def test_created_kb(tid, bot_username=""):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Boshlash",   callback_data=f"start_test_{tid}"),
        InlineKeyboardButton(text="📊 Poll rejim", callback_data=f"start_poll_{tid}"),
    )
    b.row(InlineKeyboardButton(text="📤 Guruhga ulashish", switch_inline_query=f"test_{tid}"))
    b.row(InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu"))
    return b.as_markup()


def group_stop_kb(host_id):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏹ Testni to'xtatish", callback_data=f"gstop_{host_id}"))
    return b.as_markup()
