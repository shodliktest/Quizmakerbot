"""🎓 QUIZBOT — asosiy fayl"""
import logging, asyncio, sys, threading, traceback

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent

from config import BOT_TOKEN, STORAGE_CHANNEL_ID

_bot = None
_dp  = None


def _make_bot_dp():
    global _bot, _dp
    if _bot:
        return _bot, _dp

    from handlers.start       import router as r_start
    from handlers.tests       import router as r_tests
    from handlers.poll_test   import router as r_poll
    from handlers.group       import router as r_group
    from handlers.create_test import router as r_create
    from handlers.profile     import router as r_profile
    from handlers.admin       import router as r_admin
    from handlers.inline_mode import router as r_inline

    _bot = Bot(token=BOT_TOKEN,
               default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    _dp  = Dispatcher(storage=MemoryStorage())

    # Tartib muhim: guruh handlerlari tests/poll dan oldin!
    _dp.include_router(r_inline)
    _dp.include_router(r_group)
    _dp.include_router(r_poll)
    _dp.include_router(r_start)
    _dp.include_router(r_tests)
    _dp.include_router(r_create)
    _dp.include_router(r_profile)
    _dp.include_router(r_admin)

    @_dp.errors()
    async def on_error(event: ErrorEvent):
        log.error(f"❌ Xato: {event.exception}")
        traceback.print_exc()
        return True

    return _bot, _dp


async def _startup(bot):
    from utils import store
    if not STORAGE_CHANNEL_ID:
        log.warning("⚠️ STORAGE_CHANNEL_ID sozlanmagan! Bot faqat RAMda ishlaydi.")
        return
    await store.startup(bot, STORAGE_CHANNEL_ID)


async def _auto_save_loop():
    """Har 5 daqiqada o'zgargan userlarni kanalga yuboradi."""
    from utils import store
    while True:
        await asyncio.sleep(300)
        try:
            if store.is_users_dirty() and store.tg_ready():
                ok = await store.save_users_tg()
                if ok:
                    log.info("Auto-save: userlar saqlandi")
        except Exception as e:
            log.error(f"Auto-save xato: {e}")


# ── Streamlit uchun background thread ─────────────────────
_lock    = threading.Lock()
_started = False
_thread  = None


def run_in_background():
    global _started, _thread
    with _lock:
        if _started and _thread and _thread.is_alive():
            return _thread
        _started = False

    try:
        b, d = _make_bot_dp()
    except Exception as e:
        log.error(f"Bot yaratishda xato: {e}")
        return None

    async def _run():
        try:
            await b.delete_webhook(drop_pending_updates=True)
            await _startup(b)
            log.info("🤖 Bot ishga tushdi!")
            asyncio.create_task(_auto_save_loop())
            await d.start_polling(b, handle_signals=False, allowed_updates=[
                "message", "callback_query", "inline_query",
                "poll", "poll_answer",
            ])
        except Exception as e:
            log.error(f"Bot run xato: {e}")
            traceback.print_exc()

    def _thread_fn():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()
            global _started
            with _lock:
                _started = False

    with _lock:
        _started = True
    _thread = threading.Thread(target=_thread_fn, daemon=True, name="BotThread")
    _thread.start()
    log.info("✅ Bot thread ishga tushdi")
    return _thread


# ── To'g'ridan ishga tushirish ─────────────────────────────
if __name__ == "__main__":
    async def main():
        b, d = _make_bot_dp()
        await b.delete_webhook(drop_pending_updates=True)
        await _startup(b)
        log.info("🤖 Bot lokal ishga tushdi!")
        asyncio.create_task(_auto_save_loop())
        await d.start_polling(b, allowed_updates=[
            "message", "callback_query", "inline_query",
            "poll", "poll_answer",
        ])

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot to'xtatildi.")
