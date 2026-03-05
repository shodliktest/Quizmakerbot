"""
🔀 POLL ANSWER ROUTER — Yagona markaziy handler
Barcha poll_answer eventlari shu yerdan o'tadi:
  - Guruh sessiyasi → group.py ga yo'naltiradi
  - Private sessiya → poll_test.py ga yo'naltiradi
"""
import logging
from aiogram import Router, F
from aiogram.types import PollAnswer
from aiogram.fsm.context import FSMContext

log    = logging.getLogger(__name__)
router = Router()


@router.poll_answer()
async def universal_poll_router(poll_answer: PollAnswer, state: FSMContext, bot=None):
    """
    Yagona poll_answer handler.
    Guruh sessiyasi bormi? → group handler
    Yo'q → private poll handler
    """
    from handlers.group     import route_poll_answer as group_handler
    from handlers.poll_test import route_poll_answer as private_handler

    poll_id = poll_answer.poll_id

    # 1. Guruh sessiyasiga tegishlimi?
    handled = await group_handler(poll_answer)
    if handled:
        return

    # 2. Private poll testi (FSM state tekshiradi)
    await private_handler(poll_answer, state, bot)
