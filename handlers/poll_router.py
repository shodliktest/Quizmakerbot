"""🔀 POLL ANSWER ROUTER — Yagona markaziy handler"""
import logging
from aiogram import Router
from aiogram.types import PollAnswer
from aiogram.fsm.context import FSMContext

log    = logging.getLogger(__name__)
router = Router()


@router.poll_answer()
async def universal_poll_router(poll_answer: PollAnswer, state: FSMContext,
                                 bot=None):
    from handlers.group    import route_poll_answer as group_handler
    from handlers.poll_test import route_poll_answer as private_handler

    # 1. Guruh sessiyasiga tegishlimi?
    handled = await group_handler(poll_answer)
    if handled:
        return
    # 2. Private poll
    await private_handler(poll_answer, state, bot)
