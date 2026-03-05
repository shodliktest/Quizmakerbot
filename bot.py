"""🎓 QUIZ BOT — Telegram kanal storage"""
import logging, asyncio, sys, threading, traceback
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
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

bot = None
dp  = None


def _create_bot_dp():
    global bot, dp
    if bot is not None:
        return bot, dp

    from handlers.inline_mode import router as r_inline
    from handlers.poll_router import router as r_poll_router  # Yagona poll_answer
    from handlers.group       import router as r_group
    from handlers.poll_test   import router as r_poll
    from handlers.start       import router as r_start
    from handlers.tests       import router as r_tests
    from handlers.create_test import router as r_create
    from handlers.profile     import router as r_profile
    from handlers.leaderboard import router as r_lb
    from handlers.admin       import router as r_admin

    bot = Bot(token=BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp  = Dispatcher(storage=MemoryStorage())

    dp.include_router(r_inline)      # Inline query — birinchi
    dp.include_router(r_poll_router) # Yagona poll_answer markazi
    dp.include_router(r_group)       # Guruh callback va my_chat_member
    dp.include_router(r_poll)        # Private poll callback (pauza/stop)
    dp.include_router(r_start)
    dp.include_router(r_tests)
    dp.include_router(r_create)
    dp.include_router(r_profile)
    dp.include_router(r_lb)
    dp.include_router(r_admin)

    @dp.errors()
    async def on_error(event: ErrorEvent):
        log.error(f"Bot xatosi: {event.exception}")
        traceback.print_exc()
        return True

    return bot, dp


async def _startup(bot):
    """Bot ishga tushganda TG kanaldan ma'lumotlar yuklanadi"""
    from utils import tg_db
    from utils import ram_cache as ram

    if not STORAGE_CHANNEL_ID:
        log.warning("⚠️ STORAGE_CHANNEL_ID sozlanmagan! Bot RAMsiz ishlaydi.")
        return

    await tg_db.init(bot, STORAGE_CHANNEL_ID)

    tests = await tg_db.get_tests()
    if tests:
        ram.set_tests(tests)
        log.info(f"✅ {len(tests)} test RAM ga yuklandi")
    else:
        log.info("ℹ️ Kanalda testlar yo'q — yangi baza boshlanadi")

    users = await tg_db.get_users()
    if users:
        ram.set_users(users)
        log.info(f"✅ {len(users)} user RAM ga yuklandi")

    settings = await tg_db.get_settings_tg()
    if settings:
        ram.set_all_settings(settings)
        log.info(f"✅ {len(settings)} settings yuklandi")

    # Bugungi backup tiklash
    from datetime import date
    today_str = str(date.today())
    for slot in ("12", "00"):
        today_data = await tg_db.get_backup(today_str, slot)
        if today_data:
            ram._set("daily_results", today_data)
            total_r = sum(len(v.get("history", [])) for v in today_data.values())
            log.info(f"✅ Bugungi backup tiklandi ({slot}:00): {len(today_data)} user, {total_r} natija")
            break

    log.info("🚀 Bot startup yakunlandi!")


async def _flush_loop():
    """
    Har 12 soatda (00:00 va 12:00) ma'lumotlarni TG kanalga yuboradi.
    RAMdagi ma'lumotlar SAQLANIB QOLADI.
    """
    from utils import tg_db
    from utils import ram_cache as ram

    last_flush_slot = None

    while True:
        await asyncio.sleep(60)
        try:
            from datetime import date, datetime, timezone, timedelta
            now     = datetime.now(timezone.utc)
            today   = date.today()
            hour    = now.hour
            minute  = now.minute

            # 00:00–00:05 yoki 12:00–12:05 da flush
            if minute < 5 and hour in (0, 12):
                slot = "00" if hour == 0 else "12"
                key  = f"{today}_{slot}"

                if last_flush_slot != key:
                    daily = ram.get_daily()

                    if daily and tg_db.ready():
                        # Userlar va settings ham yuboriladi
                        users = ram.get_users()
                        if users:
                            ok_u = await tg_db.save_users(users)
                            if ok_u:
                                ram.clear_users_dirty()

                        settings = ram.get_all_settings()
                        if settings:
                            await tg_db.save_settings(settings)

                        # Backup
                        if hour == 0:
                            # Yarim tunda — kechagi kunni saqlaydi
                            yesterday = str(today - timedelta(days=1))
                            mid = await tg_db.upload_backup(daily, yesterday, "00")
                            if mid:
                                log.info(f"✅ Yarim tun backup: {yesterday}_00, msg={mid}")
                                ram.clear_daily()
                        else:
                            # Kunduzi — bugungi kunni saqlaydi
                            mid = await tg_db.upload_backup(daily, str(today), "12")
                            if mid:
                                log.info(f"✅ Kunduz backup: {today}_12, msg={mid}")
                                # Kunduz backup — RAMni o'chirmaymiz

                    last_flush_slot = key

        except Exception as e:
            log.error(f"Flush loop xatosi: {e}")


async def _users_flush_loop():
    """Har 5 daqiqada o'zgargan userlarni TG kanalga yuboradi"""
    from utils import tg_db
    from utils import ram_cache as ram

    while True:
        await asyncio.sleep(300)
        try:
            if ram.is_users_dirty() and tg_db.ready():
                users = ram.get_users()
                ok    = await tg_db.save_users(users)
                if ok:
                    ram.clear_users_dirty()
                    log.info(f"Auto-flush: {len(users)} user saqlandi")
        except Exception as e:
            log.error(f"Users flush xatosi: {e}")


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
        b, d = _create_bot_dp()
    except Exception as e:
        log.error(f"❌ Bot yaratishda xato: {e}")
        traceback.print_exc()
        return None

    async def _run():
        try:
            await b.delete_webhook(drop_pending_updates=True)
            await _startup(b)
            log.info("🤖 Bot polling boshlanmoqda...")
            asyncio.create_task(_flush_loop())
            asyncio.create_task(_users_flush_loop())
            await d.start_polling(b, handle_signals=False, allowed_updates=[
                "message", "callback_query", "inline_query",
                "chosen_inline_result", "poll", "poll_answer",
                "my_chat_member", "chat_member"
            ])
        except Exception as e:
            log.error(f"❌ Bot run xatosi: {e}")
            traceback.print_exc()

    def _thread_func():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run())
        except Exception as e:
            log.error(f"Thread xatosi: {e}")
        finally:
            loop.close()
            global _started
            with _lock:
                _started = False

    with _lock:
        _started = True

    _thread = threading.Thread(target=_thread_func, daemon=True, name="BotThread")
    _thread.start()
    log.info(f"✅ Bot thread ishga tushdi")
    return _thread


# ── Lokal ishga tushirish ─────────────────────────────────
if __name__ == "__main__":
    async def main():
        b, d = _create_bot_dp()
        await b.delete_webhook(drop_pending_updates=True)
        await _startup(b)
        log.info("🤖 Bot lokal ishga tushdi!")
        asyncio.create_task(_flush_loop())
        asyncio.create_task(_users_flush_loop())
        await d.start_polling(b, allowed_updates=[
            "message", "callback_query", "inline_query",
            "chosen_inline_result", "poll", "poll_answer",
            "my_chat_member", "chat_member"
        ])

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot to'xtatildi.")
