"""⌨️ BARCHA KLAVIATURALAR"""
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import SUBJECTS, DIFFICULTY, ADMIN_IDS

remove_kb = ReplyKeyboardRemove()

# ── Reply KB ──────────────────────────────────────────────

def main_kb(uid=None) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📚 Testlar"),     KeyboardButton(text="➕ Test Yaratish")],
        [KeyboardButton(text="📊 Natijalarim"), KeyboardButton(text="🏆 Reyting")],
        [KeyboardButton(text="👤 Profil"),       KeyboardButton(text="ℹ️ Yordam")],
    ]
    if uid and uid in ADMIN_IDS:
        rows.append([KeyboardButton(text="👑 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# ── Test kartochkasi ──────────────────────────────────────

def test_card_kb(tid) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Inline",  callback_data=f"s_test_{tid}"),
        InlineKeyboardButton(text="📊 Poll",    callback_data=f"s_poll_{tid}"),
    )
    b.row(InlineKeyboardButton(
        text="👥 Guruhga yuborish",
        switch_inline_query=f"test_{tid}"
    ))
    b.row(
        InlineKeyboardButton(text="🏆 Reyting", callback_data=f"lb_{tid}"),
        InlineKeyboardButton(text="🏠 Menyu",   callback_data="main_menu"),
    )
    return b.as_markup()


# ── Inline test ───────────────────────────────────────────

def answer_kb(letters: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    icons = ["🔵","🟣","🟢","🔴","🟡","🟠","⚪","⚫","🔷","🔶"]
    for i, lt in enumerate(letters):
        b.add(InlineKeyboardButton(
            text=f"{icons[i] if i<len(icons) else '▫️'} {lt}",
            callback_data=f"ans_{lt}"
        ))
    b.adjust(2)
    return b.as_markup()

def next_kb(sec=30) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=f"⏭ Keyingi ({sec}s)", callback_data="next_now"))
    b.row(InlineKeyboardButton(text="⏹ To'xtatish",         callback_data="stop_test"))
    return b.as_markup()

def result_kb(tid, rid) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔍 Tahlil",    callback_data=f"analysis_{rid}_0"))
    b.row(InlineKeyboardButton(text="🔄 Qayta",     callback_data=f"s_test_{tid}"))
    b.row(InlineKeyboardButton(text="🏠 Menyu",     callback_data="main_menu"))
    return b.as_markup()

def analysis_kb(rid, idx, total) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if idx > 0:
        b.add(InlineKeyboardButton(text="◀️", callback_data=f"analysis_{rid}_{idx-1}"))
    b.add(InlineKeyboardButton(text=f"{idx+1}/{total}", callback_data="noop"))
    if idx < total - 1:
        b.add(InlineKeyboardButton(text="▶️", callback_data=f"analysis_{rid}_{idx+1}"))
    b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))
    return b.as_markup()


# ── Poll test ────────────────────────────────────────────

def poll_ctrl_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="⏸ Pauza",      callback_data="pause_poll"),
        InlineKeyboardButton(text="⏹ To'xtatish", callback_data="stop_poll"),
    )
    return b.as_markup()

def poll_resume_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="▶️ Davom etish",  callback_data="resume_poll"))
    b.row(InlineKeyboardButton(text="⏹ Tugatish",      callback_data="stop_poll"))
    return b.as_markup()


# ── Guruh test ───────────────────────────────────────────

def group_mode_kb(tid) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔘 Inline (tugmali)", callback_data=f"gm_inline_{tid}"))
    b.row(InlineKeyboardButton(text="📊 Poll (viktorina)",  callback_data=f"gm_poll_{tid}"))
    b.row(InlineKeyboardButton(text="❌ Bekor",             callback_data="gm_cancel"))
    return b.as_markup()

def group_stop_kb(host_id) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏹ To'xtatish", callback_data=f"g_stop_{host_id}"))
    return b.as_markup()


# ── Test yaratish ─────────────────────────────────────────

def subject_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in SUBJECTS:
        b.add(InlineKeyboardButton(text=s, callback_data=f"subj_{s}"))
    b.adjust(2)
    return b.as_markup()

def difficulty_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for k, v in DIFFICULTY.items():
        b.add(InlineKeyboardButton(text=v, callback_data=f"diff_{k}"))
    b.adjust(2)
    return b.as_markup()

def visibility_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🌍 Ommaviy",  callback_data="vis_public"))
    b.row(InlineKeyboardButton(text="🔗 Ssilka",   callback_data="vis_link"))
    b.row(InlineKeyboardButton(text="🔒 Shaxsiy",  callback_data="vis_private"))
    return b.as_markup()

def test_created_kb(tid, bot_username) -> InlineKeyboardMarkup:
    link = f"https://t.me/{bot_username}?start={tid}"
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Inline",  callback_data=f"s_test_{tid}"),
        InlineKeyboardButton(text="📊 Poll",    callback_data=f"s_poll_{tid}"),
    )
    b.row(InlineKeyboardButton(
        text="👥 Guruhga yuborish",
        switch_inline_query=f"test_{tid}"
    ))
    b.row(InlineKeyboardButton(text="🔗 Ssilkani ulashish", url=link))
    b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))
    return b.as_markup()


# ── Natijalar ─────────────────────────────────────────────

def results_kb(page, total_pages) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"res_p{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"res_p{page+1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))
    return b.as_markup()

def my_tests_kb(page, total_pages) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"mt_p{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"mt_p{page+1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))
    return b.as_markup()


# ── Admin ────────────────────────────────────────────────

def admin_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📈 Statistika",     callback_data="adm_stats"))
    b.row(InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="adm_users"))
    b.row(InlineKeyboardButton(text="📋 Testlar",        callback_data="adm_tests"))
    b.row(InlineKeyboardButton(text="📢 Xabar tarqatish", callback_data="adm_broadcast"))
    b.row(InlineKeyboardButton(text="🚫 Bloklash/Ochish", callback_data="adm_block"))
    b.row(InlineKeyboardButton(text="🗑 Test o'chirish",  callback_data="adm_del_test"))
    b.row(InlineKeyboardButton(text="💾 Saqlash (flush)", callback_data="adm_flush"))
    return b.as_markup()


# ── Umumiy ───────────────────────────────────────────────

def back_kb(cb="main_menu") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data=cb))
    return b.as_markup()

def cancel_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel"))
    return b.as_markup()
