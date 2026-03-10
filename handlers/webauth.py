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

