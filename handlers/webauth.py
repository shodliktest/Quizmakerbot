"""🌐 WEBAUTH — Sayt uchun Telegram ID orqali kirish"""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

router = Router()


@router.message(Command("id"))
@router.message(F.text == "🌐 Sayt ID")
async def send_web_id(message: Message):
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
