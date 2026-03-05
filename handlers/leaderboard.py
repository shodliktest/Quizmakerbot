"""🏆 REYTING"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from utils.db import get_leaderboard
from keyboards.keyboards import main_kb

log    = logging.getLogger(__name__)
router = Router()
MEDALS = ["🥇","🥈","🥉"]+[f"{i}." for i in range(4,21)]

@router.message(F.text == "🏆 Reyting")
async def lb_msg(message: Message): await _show_lb(message)

@router.callback_query(F.data == "lb_global")
async def lb_global(callback: CallbackQuery):
    await callback.answer(); await _show_lb(callback.message,edit=True)

@router.callback_query(F.data.startswith("lb_test_"))
async def lb_test(callback: CallbackQuery):
    await callback.answer()
    docs=get_leaderboard(limit=10)
    text=f"🏆 <b>REYTING</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i,u in enumerate(docs):
        text+=f"{MEDALS[i] if i<len(MEDALS) else str(i+1)} <b>{u.get('name','?')}</b> — {u.get('avg_score',0):.1f}%\n"
    b=InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🌍 Global",callback_data="lb_global"))
    b.row(InlineKeyboardButton(text="🏠 Menyu",callback_data="main_menu"))
    try:    await callback.message.edit_text(text,reply_markup=b.as_markup())
    except TelegramBadRequest: await callback.message.answer(text,reply_markup=b.as_markup())

async def _show_lb(msg, edit=False):
    docs=get_leaderboard(limit=20)
    text="🏆 <b>GLOBAL REYTING</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    if not docs: text+="📭 Hali ma'lumot yo'q."
    for i,u in enumerate(docs):
        text+=f"{MEDALS[i] if i<len(MEDALS) else str(i+1)} <b>{u.get('name','?')}</b> — {u.get('avg_score',0):.1f}% | {u.get('total_tests',0)} ta\n"
    b=InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Yangilash",callback_data="lb_global"))
    b.row(InlineKeyboardButton(text="🏠 Menyu",callback_data="main_menu"))
    try:
        if edit: await msg.edit_text(text,reply_markup=b.as_markup())
        else:    await msg.answer(text,reply_markup=b.as_markup())
    except TelegramBadRequest: await msg.answer(text,reply_markup=b.as_markup())
