"""⌨️ BARCHA KLAVIATURALAR"""
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton,
                            ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import SUBJECTS, DIFFICULTY_LEVELS

COLORS = ["🔵","🟣","🟢","🔴","🟡","🟠","⚪","⚫","🔷","🔶"]


# ── Reply klaviaturalar ────────────────────────────────────────

def main_kb(uid=None, chat_type="private"):
    if chat_type != "private":
        return ReplyKeyboardRemove()
    kb = [
        [KeyboardButton(text="📚 Testlar"),          KeyboardButton(text="➕ Test Yaratish")],
        [KeyboardButton(text="📊 Natijalarim"),       KeyboardButton(text="🏆 Reyting")],
        [KeyboardButton(text="🗂 Mening testlarim"),  KeyboardButton(text="👤 Profil")],
        [KeyboardButton(text="ℹ️ Yordam")],
    ]
    if uid:
        from config import ADMIN_IDS
        if uid in ADMIN_IDS:
            kb.append([KeyboardButton(text="👑 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


# ── Test kartochkasi ───────────────────────────────────────────

def test_info_kb(tid, creator_id=None, viewer_uid=None):
    """
    Test kartochkasi tugmalari.
    - "Guruhda yechish" olib tashlandi — faqat ulashish orqali
    - Ulashish → inline mode → 3 ta tugma (inline, poll, guruh)
    """
    from utils.ram_cache import get_test_meta
    from config import ADMIN_IDS

    b = InlineKeyboardBuilder()
    meta = get_test_meta(tid)
    is_paused = meta.get("is_paused", False)
    is_owner  = viewer_uid and (
        viewer_uid == creator_id or
        viewer_uid in ADMIN_IDS
    )

    if is_paused:
        b.row(InlineKeyboardButton(
            text="⚠️ Test vaqtincha to'xtatilgan",
            callback_data="noop"
        ))
        if is_owner:
            b.row(InlineKeyboardButton(
                text="▶️ Testni qayta boshlash",
                callback_data=f"test_resume_{tid}"
            ))
    else:
        b.row(
            InlineKeyboardButton(text="▶️ Inline test",  callback_data=f"start_test_{tid}"),
            InlineKeyboardButton(text="📊 Quiz Poll",    callback_data=f"start_poll_{tid}"),
        )

    # Ulashish — faqat inline share
    b.row(InlineKeyboardButton(text="📤 Ulashish", switch_inline_query=f"test_{tid}"))

    if is_owner and not is_paused:
        b.row(
            InlineKeyboardButton(text="⏸ To'xtatib qo'yish", callback_data=f"test_pause_{tid}"),
            InlineKeyboardButton(text="📊 Kim yechgan",       callback_data=f"test_solvers_{tid}_0"),
        )
    elif is_owner and is_paused:
        b.row(InlineKeyboardButton(text="📊 Kim yechgan", callback_data=f"test_solvers_{tid}_0"))

    b.row(
        InlineKeyboardButton(text="🏆 Reyting", callback_data=f"lb_test_{tid}"),
        InlineKeyboardButton(text="🏠 Menyu",   callback_data="main_menu"),
    )
    return b.as_markup()

def test_info_simple_kb(tid):
    """Oddiy test kartochkasi"""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Inline test", callback_data=f"start_test_{tid}"),
        InlineKeyboardButton(text="📊 Quiz Poll",   callback_data=f"start_poll_{tid}"),
    )
    b.row(InlineKeyboardButton(text="📤 Ulashish", switch_inline_query=f"test_{tid}"))
    b.row(
        InlineKeyboardButton(text="🏆 Reyting", callback_data=f"lb_test_{tid}"),
        InlineKeyboardButton(text="🏠 Menyu",   callback_data="main_menu"),
    )
    return b.as_markup()


# ── Test yaratilgandan keyin ───────────────────────────────────

def test_created_kb(tid):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️ Boshlash",   callback_data=f"start_test_{tid}"),
        InlineKeyboardButton(text="📊 Poll rejim", callback_data=f"start_poll_{tid}"),
    )
    b.row(InlineKeyboardButton(text="📤 Ulashish", switch_inline_query=f"test_{tid}"))
    b.row(InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu"))
    return b.as_markup()


# ── Natija klaviaturasi ────────────────────────────────────────

def result_kb(tid, rid):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔍 Batafsil tahlil", callback_data=f"analysis_{rid}_0"))
    b.row(
        InlineKeyboardButton(text="🔄 Qaytadan",   callback_data=f"start_test_{tid}"),
        InlineKeyboardButton(text="📊 Poll rejim", callback_data=f"start_poll_{tid}"),
    )
    b.row(InlineKeyboardButton(text="📤 Ulashish", switch_inline_query=f"test_{tid}"))
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
    return b.as_markup()


# ── Tahlil klaviaturasi ────────────────────────────────────────

def analysis_kb(rid, page, total):
    b = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"analysis_{rid}_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"analysis_{rid}_{page+1}"))
    b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Natijaga qaytish", callback_data=f"res_back_{rid}"))
    b.row(InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="main_menu"))
    return b.as_markup()


# ── Javob klaviaturalari ───────────────────────────────────────

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

def poll_pause_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="▶️ Davom etish",     callback_data="resume_poll"))
    b.row(InlineKeyboardButton(text="❌ Testni yakunlash", callback_data="cancel_poll"))
    return b.as_markup()


# ── Admin panel ────────────────────────────────────────────────

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
        InlineKeyboardButton(text="⚡ RAM → TG (Flush)", callback_data="adm_flush"),
        InlineKeyboardButton(text="🔄 TG → RAM (Sync)",  callback_data="adm_refresh"),
    )
    b.row(
        InlineKeyboardButton(text="💾 JSON export", callback_data="adm_export_json"),
        InlineKeyboardButton(text="🗂 Backuplar",   callback_data="adm_backups"),
    )
    b.row(
        InlineKeyboardButton(text="📊 Kunlik hisobot", callback_data="adm_daily_report"),
    )
    b.row(InlineKeyboardButton(text="🏠 Menyu", callback_data="main_menu"))
    return b.as_markup()


# ── Test yaratish ──────────────────────────────────────────────

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
    icons = {"easy":"🟢","medium":"🟡","hard":"🔴","expert":"⚡"}
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

def group_stop_kb(host_id):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏹ Testni to'xtatish", callback_data=f"gstop_{host_id}"))
    return b.as_markup()
