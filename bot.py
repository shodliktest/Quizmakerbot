"""🤖 BOT — Asosiy ishga tushirish"""
import asyncio, logging
from datetime import datetime, timezone, date, timedelta
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, STORAGE_CHANNEL_ID, ADMIN_IDS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger(__name__)
UTC = timezone.utc


async def main():
    from handlers.inline_mode import router as r_inline
    from handlers.poll_router import router as r_poll_router
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

    dp.include_router(r_inline)
    dp.include_router(r_poll_router)
    dp.include_router(r_group)
    dp.include_router(r_poll)
    dp.include_router(r_start)
    dp.include_router(r_tests)
    dp.include_router(r_create)
    dp.include_router(r_profile)
    dp.include_router(r_lb)
    dp.include_router(r_admin)

    # TG DB boshlash
    if STORAGE_CHANNEL_ID:
        from utils import tg_db
        log.info("TG DB initsializatsiya...")
        await tg_db.init(bot, STORAGE_CHANNEL_ID)
        from utils import ram_cache as ram
        tests = await tg_db.get_tests()
        if tests: ram.set_tests(tests)
        users = await tg_db.get_users()
        if users: ram.set_users(users)
        settings = await tg_db.get_settings_tg()
        if settings: ram.set_all_settings(settings)
        log.info(f"✅ Yuklandi: {ram.stats()['tests']} test, {ram.stats()['users']} user")

    # Background tasklar
    asyncio.create_task(_midnight_flush_loop(bot))
    asyncio.create_task(_users_auto_flush_loop(bot))
    asyncio.create_task(_cache_cleanup_loop())

    # Admin ga xabar
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid,
                f"✅ <b>Bot ishga tushdi!</b>\n"
                f"📅 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC")
        except Exception: pass

    log.info("🚀 Bot ishga tushdi!")
    await dp.start_polling(bot, drop_pending_updates=True)


# ── MIDNIGHT FLUSH — kuniga 1 marta, 00:00 UTC ────────────────

async def _midnight_flush_loop(bot):
    """
    Har kun 00:00 UTC da:
    1. Kecha kunlik natijalarni TG ga yuboradi (backup)
    2. Users va settings saqlaydi
    3. RAM daily tozalanadi — yangi kun uchun
    4. Admin ga xabar yuboriladi

    MUHIM:
    - Natijalar TG ga FAQAT shu yerda yuklanadi (har yechilganda emas)
    - RAM daily faqat midnight da tozalanadi
    """
    flushed_date = None
    while True:
        try:
            await asyncio.sleep(60)
            now   = datetime.now(UTC)
            today = date.today()
            if now.hour == 0 and now.minute < 5 and flushed_date != today:
                flushed_date = today
                log.info("🌙 Midnight flush boshlanmoqda...")
                from utils import tg_db, ram_cache as ram

                yesterday = str(today - timedelta(days=1))
                daily     = ram.get_daily()
                users     = ram.get_users()
                settings  = ram.get_all_settings()

                if tg_db.ready():
                    # 1. Kunlik backup (bitta fayl)
                    if daily:
                        mid = await tg_db.upload_backup(daily, yesterday)
                        log.info(f"✅ Backup yuborildi: {yesterday} msg={mid}")
                    # 2. Users
                    await tg_db.save_users(users)
                    ram.clear_users_dirty()
                    # 3. Settings
                    await tg_db.save_settings(settings)
                    # 4. RAM daily tozalash
                    ram.clear_daily()
                    log.info("✅ Midnight flush yakunlandi")

                # Admin ga xabar
                for aid in ADMIN_IDS:
                    try:
                        await bot.send_message(
                            aid,
                            f"🌙 <b>Midnight Flush</b> yakunlandi!\n"
                            f"📅 {yesterday} backupi saqlandi\n"
                            f"👥 {len(users)} user | 💾 {len(daily)} kunlik yozuv"
                        )
                    except Exception: pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Flush loop xato: {e}")


# ── USERS AUTO FLUSH — har 10 daqiqada (dirty bo'lsa) ─────────

async def _users_auto_flush_loop(bot):
    """Yangi user qo'shilsa users.json ni TG ga yuboradi"""
    await asyncio.sleep(600)
    while True:
        try:
            await asyncio.sleep(600)
            from utils import tg_db, ram_cache as ram
            if tg_db.ready() and ram.is_users_dirty():
                await tg_db.save_users(ram.get_users())
                ram.clear_users_dirty()
                log.debug("Users auto-flush")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Users flush xato: {e}")


# ── CACHE CLEANUP — har 30 daqiqada ──────────────────────────

async def _cache_cleanup_loop():
    await asyncio.sleep(1800)
    while True:
        try:
            await asyncio.sleep(1800)
            from utils import ram_cache as ram
            ram.clear_expired_cache()
            log.debug("Cache tozalandi")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Cache cleanup xato: {e}")


def run_in_background():
    """Streamlit app tomonidan chaqiriladi — botni background threadda ishga tushiradi"""
    import threading

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(main())
        except Exception as e:
            log.error(f"Bot thread xato: {e}")
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True, name="bot-thread")
    t.start()
    log.info("✅ Bot background threadda ishga tushdi")
    return t


if __name__ == "__main__":
    asyncio.run(main())
