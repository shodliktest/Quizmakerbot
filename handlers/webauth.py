"""🌐 WEBAUTH — Sayt uchun Telegram ID orqali kirish"""
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command, CommandStart

router = Router()

WEBAPP_URL = "https://quizmarkerbotweb.vercel.app"


async def _send_id(message: Message):
    uid   = message.from_user.id
    name  = message.from_user.full_name or "Foydalanuvchi"
    uname = f"@{message.from_user.username}" if message.from_user.username else "Mavjud emas"

    await message.answer(
        f"🌐 <b>SAYTGA KIRISH</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Quyidagi ID ni saytga kiriting:\n\n"
        f"<code>{uid}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Ism: {name}\n"
        f"🔗 Username: {uname}\n\n"
        f"<i>💡 ID ni bosib nusxa oling, keyin saytga kiriting</i>"
    )


@router.message(Command("id"))
@router.message(F.text == "🌐 Sayt ID")
async def send_web_id(message: Message):
    await _send_id(message)


@router.message(CommandStart(deep_link=True, magic=F.args == "getid"))
async def start_getid(message: Message):
    await _send_id(message)


@router.message(Command("webapp"))
@router.message(F.text == "🌐 Saytga kirish")
async def open_webapp(message: Message):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="🌐 TestPro saytini ochish",
        web_app=WebAppInfo(url=WEBAPP_URL + "/login.html")
    ))
    await message.answer(
        "🌐 <b>TestPro saytiga kirish</b>\n\n"
        "Quyidagi tugmani bosing — avtomatik kirasiz:",
        reply_markup=b.as_markup()
    )



# ══ OTP — Maxsus test kodi ════════════════════════════════════

@router.message(F.text.regexp(r'^/getcode\s+\S+'))
@router.message(F.text.regexp(r'^getcode\s+\S+'))
async def get_otp_code(message: Message):
    """
    /getcode TEST_ID — maxsus testga kirish uchun OTP kod
    Sayt: "Botdan kod oling" → foydalanuvchi /getcode 860C9B3A yuboradi
    Bot: 10 daqiqalik kod generatsiya qilib yuboradi
    """
    parts = message.text.strip().split()
    test_id = parts[-1].upper().strip()

    from utils import tg_db, ram_cache as ram
    import time, hashlib

    # Test mavjudligini tekshirish
    meta = ram.get_test_meta(test_id)
    if not meta:
        await message.answer(
            f"❌ <b>{test_id}</b> — test topilmadi.\n"
            f"Test ID ni to'g'ri kiriting."
        )
        return

    if meta.get('visibility') not in ('private', 'link'):
        await message.answer(
            f"ℹ️ <b>{meta.get('title','Test')}</b> — bu test ommaviy, "
            f"kod kerak emas.\n\n"
            f"🌐 Saytda to'g'ridan oching."
        )
        return

    # Kod yaratish: "TESTID:TIMESTAMP:HASH" formati
    ts   = str(int(time.time() * 1000))
    secret = f"{test_id}:{ts}:{tg_db._bot.token[-8:]}"
    h    = hashlib.sha256(secret.encode()).hexdigest()[:8].upper()
    code = f"{test_id}:{ts}:{h}"

    # Inson o'qiydigan qisqa versiya ham yuboramiz
    short = h  # 8 ta belgi — shu yetarli

    await message.answer(
        f"🔑 <b>Maxsus test kodi</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 Test: <b>{meta.get('title','?')}</b>\n\n"
        f"Saytga quyidagi kodni kiriting:\n\n"
        f"<code>{code}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ Kod <b>10 daqiqa</b> amal qiladi\n"
        f"🔂 Bir martalik foydalanish"
    )


@router.message(CommandStart(deep_link=True, magic=F.args.startswith('getcode_')))
async def start_getcode(message: Message):
    """Saytdan: t.me/bot?start=getcode_TESTID"""
    test_id = message.text.split('getcode_', 1)[-1].upper().strip().split()[0]
    # getcode kabi ishlaydi
    fake = type('M', (), {
        'text': f'/getcode {test_id}',
        'answer': message.answer,
        'from_user': message.from_user,
    })()
    await get_otp_code(fake)

