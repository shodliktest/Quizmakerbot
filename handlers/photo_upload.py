"""
photo_upload.py — Rasmli savollar uchun yordamchi handler

Foydalanish:
  1. Botga rasm yuboring (istalgan chat)
  2. Bot file_id qaytaradi
  3. Shu file_id ni TXT testga qo'shing:
     [rasm: AgACAgI...]
     Savol matni...
     *A) To'g'ri javob

main.py ga qo'shing:
  from handlers.photo_upload import router as photo_router
  dp.include_router(photo_router)
"""

import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

log    = logging.getLogger(__name__)
router = Router()


@router.message(Command("upload_photo"))
async def cmd_upload_photo(message: Message):
    """Rasm yuklash yo'riqnomasi."""
    await message.answer(
        "📸 <b>Rasm yuklash</b>\n\n"
        "Menga rasm yuboring — men uning <code>file_id</code> sini qaytaraman.\n\n"
        "So'ng shu <code>file_id</code> ni TXT testga qo'shing:\n"
        "<pre>[rasm: file_id_bu_yerga]\n"
        "Savol matni...\n"
        "*A) To'g'ri javob\n"
        "B) Variant\n"
        "C) Variant\n"
        "D) Variant</pre>",
        parse_mode="HTML"
    )


@router.message(lambda m: m.photo is not None)
async def handle_photo(message: Message):
    """Rasm qabul qilish — file_id qaytarish."""
    photo   = message.photo[-1]  # Eng yuqori sifatli rasm
    file_id = photo.file_id

    await message.answer(
        f"✅ <b>Rasm qabul qilindi!</b>\n\n"
        f"<b>file_id:</b>\n"
        f"<code>[rasm: {file_id}]</code>\n\n"
        f"Shu qatorni savol oldiga qo'ying:\n"
        f"<pre>[rasm: {file_id}]\n"
        f"Savol matni...\n"
        f"*A) To'g'ri javob</pre>",
        parse_mode="HTML"
    )
    log.info(f"Rasm yuklandi: {file_id[:30]}...")


@router.message(lambda m: m.document is not None and
                m.document.mime_type and
                m.document.mime_type.startswith("image/"))
async def handle_photo_doc(message: Message):
    """Fayl sifatida yuborilgan rasm."""
    file_id = message.document.file_id
    await message.answer(
        f"✅ <b>Rasm (fayl) qabul qilindi!</b>\n\n"
        f"<code>[rasm: {file_id}]</code>",
        parse_mode="HTML"
    )
