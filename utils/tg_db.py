"""
TG_DB — Telegram kanal storage
=================================
ARXITEKTURA:
  Index (pinned):      test_ids, msg_ids, meta
  tests_stats.json:    har test: solve_count, avg_score, is_paused, solvers
  users_full.json:     har user: statistika + per-test history
  test_XXX.json:       to'liq savol ma'lumotlari (lazy load)
  backup_DATE.json:    kunlik natijalar

SAQLASH JADVALI:
  Test yechildi    → RAM dirty flag → 5 daqiqada tests_stats + users_full TG ga
  Yangi test       → test_XXX.json darhol
  Midnight         → backup + users_full + tests_stats
  Admin flush      → hammasi

BOT QAYTA YONGANDA:
  tests_stats.json → RAM (solve_count, avg_score, is_paused, solvers)
  users_full.json  → RAM (user statistikalar + history)
  Hot testlar      → backup dan lazy preload
"""
import json, logging, io, asyncio
from datetime import datetime, timezone

log      = logging.getLogger(__name__)
UTC      = timezone.utc
_bot     = None
_cid     = None
_index:  dict = {}
_can_pin = True
_tests_cache: dict = {}   # {tid: test_dict} — savollar bilan

# Dirty flaglar
_stats_dirty  = False
_users_dirty  = False


async def init(bot, channel_id):
    global _bot, _cid, _index, _tests_cache, _stats_dirty, _users_dirty
    _cid = int(channel_id)
    _index = {}
    _tests_cache = {}
    _stats_dirty = False
    _users_dirty = False

    # Storage uchun alohida bot instance — protect_content=False
    # Bu faqat kanal ichki operatsiyalar uchun (forward, send_document)
    from aiogram import Bot as _BotClass
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    _bot = _BotClass(
        token=bot.token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            protect_content=False,  # Storage kanal uchun forward ishlaydi
        )
    )

    _index = await _load_index()
    if not _index:
        log.info("ℹ️ Yangi baza yaratilmoqda...")
        _index = {"tests_meta": [], "backups": {}}
        # Darhol saqlab pin qilamiz
        await _save_index()
        log.info("✅ Yangi baza yaratildi va pinlandi")
        # Users va stats ham bo'sh bo'lsa ham yozib qo'yamiz
        _stats_dirty = True
        _users_dirty = True
        await save_tests_stats()
        await save_users_full()
        return

    log.info(f"✅ Index: {len(_index.get('tests_meta', []))} meta")

    # 1. tests_stats.json — solve_count, avg, is_paused, solvers
    await _load_tests_stats()

    # 2. users_full.json — user statistikalar + history
    await _load_users_full()

    # 3. O'qib bo'lmagan fayllarni darhol qayta yozish (protect_content muammosi)
    if _stats_dirty:
        log.info("♻️ tests_stats qayta yozilmoqda...")
        await save_tests_stats()
    if _users_dirty:
        log.info("♻️ users_full qayta yozilmoqda...")
        await save_users_full()

    # 4. Hot testlar — oxirgi backup dan
    await _preload_from_last_backup()


def ready():
    return _bot is not None and bool(_cid)

def mark_stats_dirty():
    global _stats_dirty
    _stats_dirty = True

def mark_users_dirty_tg():
    global _users_dirty
    _users_dirty = True

def is_dirty():
    return _stats_dirty or _users_dirty


# ══ TESTS STATS — doimiy saqlanadigan ══════════════════════════

async def _load_tests_stats():
    """tests_stats.json dan solve_count, avg, is_paused, solvers yuklash"""
    mid = _index.get("tests_stats_msg_id")
    if not mid:
        log.info("ℹ️ tests_stats yo'q")
        return
    # Avval file_id dan yuklab ko'rish
    fid = _index.get(f"fid_{mid}")
    if fid:
        data = await _read_file(fid)
        if not data:
            _index.pop(f"fid_{mid}", None)
            data = await _download_doc(mid)
    else:
        data = await _download_doc(mid)
    if not data:
        log.warning(f"⚠️ tests_stats o'qilmadi (mid={mid}) — 5 daqiqada qayta yoziladi")
        mark_stats_dirty()
        return
    from utils import ram_cache as ram
    stats = data.get("stats", {})
    loaded = 0
    for tid, s in stats.items():
        ram.update_test_meta(tid, {
            "solve_count": s.get("solve_count", 0),
            "avg_score":   s.get("avg_score", 0.0),
            "is_paused":   s.get("is_paused", False),
            "is_active":   s.get("is_active", True),
        })
        if s.get("solvers"):
            ram.load_solvers_to_ram(tid, s["solvers"])
        loaded += 1
    log.info(f"✅ tests_stats: {loaded} test statistikasi yuklandi")

async def save_tests_stats():
    """Barcha test statistikasini TG ga saqlash"""
    global _stats_dirty
    if not ready(): return False
    from utils import ram_cache as ram
    metas   = ram.get_all_tests_meta()
    daily   = ram.get_daily()
    stats   = {}
    for m in metas:
        tid = m.get("test_id", "")
        if not tid: continue
        # Solvers: daily_results dan yig'amiz
        solvers = {}
        for uid_str, udata in daily.items():
            entry = udata.get("by_test", {}).get(tid)
            if entry and entry.get("attempts", 0) > 0:
                solvers[uid_str] = {
                    "attempts":      entry["attempts"],
                    "best_score":    entry["best_score"],
                    "avg_score":     entry["avg_score"],
                    "all_pcts":      entry["all_pcts"],
                    "first_pct":     entry["all_pcts"][0] if entry["all_pcts"] else 0,
                    "last_at":       entry.get("last_at", ""),
                    # Tahlil uchun saqlaymiz — rebootda tiklanadi
                    "last_analysis": entry.get("last_analysis", []),
                    "last_result":   entry.get("last_result", {}),
                    "first_result":  entry.get("first_result", {}),
                }
        stats[tid] = {
            "solve_count": m.get("solve_count", 0),
            "avg_score":   m.get("avg_score", 0.0),
            "is_paused":   m.get("is_paused", False),
            "is_active":   m.get("is_active", True),
            "solvers":     solvers,
        }
    ts  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    try:
        msg = await _bot.send_document(_cid,
            document=_buf({"stats": stats, "saved_at": ts}, "tests_stats.json"),
            caption=f"📊 TESTS_STATS | {len(stats)} test | {ts}",
            protect_content=False)
        _index["tests_stats_msg_id"] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id   # file_id cache
        await _save_index()
        _stats_dirty = False
        log.info(f"✅ tests_stats saqlandi: {len(stats)} test")
        return True
    except Exception as e:
        log.error(f"save_tests_stats: {e}")
        return False


# ══ USERS FULL — doimiy saqlanadigan ══════════════════════════

async def _load_users_full():
    """users_full.json dan user profil + minimal statistika yuklash"""
    mid = _index.get("users_full_msg_id") or _index.get("users_msg_id")
    if not mid:
        log.info("ℹ️ users_full yo'q")
        return
    fid = _index.get(f"fid_{mid}")
    if fid:
        data = await _read_file(fid)
        if not data:
            _index.pop(f"fid_{mid}", None)
            data = await _download_doc(mid)
    else:
        data = await _download_doc(mid)
    if not data:
        log.warning(f"⚠️ users_full o'qilmadi (mid={mid}) — 5 daqiqada qayta yoziladi")
        mark_users_dirty_tg()
        return
    from utils import ram_cache as ram

    # Profil
    users = data.get("users", {})
    if users:
        ram.set_users(users)

    # Yangi format: by_test — minimal statistika
    by_test = data.get("by_test", {})
    if by_test:
        ram.load_history_to_ram(by_test)

    # Eski format fallback: history
    if not by_test:
        history = data.get("history", {})
        if history:
            ram.load_history_to_ram(history)

    log.info(f"✅ users_full: {len(users)} user yuklandi")

async def save_users_full():
    """
    Users profil + minimal statistika → users_full.json (bot uchun, kichik)
    To'liq history → history_full.json (sayt uchun, katta)
    """
    global _users_dirty
    if not ready(): return False
    from utils import ram_cache as ram
    users = ram.get_users()
    daily = ram.get_daily()
    ts    = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")

    # ── users_full.json: profil + oxirgi natija/tahlil ─────────
    by_test_light = {}
    history_full  = {}

    for uid_str, udata in daily.items():
        bt_light = {}
        bt_hist  = []
        for tid, entry in udata.get("by_test", {}).items():
            # Bot uchun — minimal statistika + oxirgi natija/tahlil
            bt_light[tid] = {
                "attempts":      entry.get("attempts", 0),
                "best_score":    entry.get("best_score", 0.0),
                "avg_score":     entry.get("avg_score", 0.0),
                "all_pcts":      entry.get("all_pcts", []),
                "last_at":       entry.get("last_at", ""),
                "last_result":   entry.get("last_result") or {},
                "last_analysis": entry.get("last_analysis") or [],
                "first_result":  entry.get("first_result") or {},
            }
        # Sayt uchun — to'liq history
        for h in udata.get("history", []):
            bt_hist.append(h)

        if bt_light:
            by_test_light[uid_str] = bt_light
        if bt_hist:
            history_full[uid_str] = bt_hist

    # 1. users_full.json — kichik fayl (bot startup da yuklanadi)
    try:
        msg = await _bot.send_document(_cid,
            document=_buf({
                "users":   users,
                "by_test": by_test_light,
                "count":   len(users),
                "saved_at": ts,
            }, "users_full.json"),
            caption=f"👥 USERS_FULL | {len(users)} user | {ts}",
            protect_content=False)
        _index["users_full_msg_id"] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id   # file_id cache
        log.info(f"✅ users_full saqlandi: {len(users)} user")
    except Exception as e:
        log.error(f"save_users_full: {e}")
        return False

    # 2. history_full.json — katta fayl (sayt uchun, startup da yuklanmaydi)
    if history_full:
        try:
            msg2 = await _bot.send_document(_cid,
                document=_buf({
                    "history":  history_full,
                    "count":    len(history_full),
                    "saved_at": ts,
                }, "history_full.json"),
                caption=f"📜 HISTORY_FULL | {len(history_full)} user | {ts}",
                protect_content=False)
            _index["history_full_msg_id"] = msg2.message_id
            _index[f"fid_{msg2.message_id}"] = msg2.document.file_id   # file_id cache
            log.info(f"✅ history_full saqlandi: {len(history_full)} user tarixi")
        except Exception as e:
            log.warning(f"history_full saqlash: {e}")

    await _save_index()
    _users_dirty = False
    return True


# ══ AUTO-FLUSH (5 daqiqada dirty bo'lsa) ══════════════════════


# ══ OTP KODLAR (sayt uchun) ════════════════════════════════════
# {code: {test_id, uid, expires_at, used}}
_otp_store: dict = {}

def generate_otp(test_id: str, uid: int = 0) -> str:
    """Maxsus test uchun vaqtinchalik 6 xonali kod yaratish (10 daqiqa)"""
    import random, string, time
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    _otp_store[code] = {
        "test_id":    test_id,
        "uid":        uid,
        "expires_at": time.time() + 600,  # 10 daqiqa
        "used":       False,
    }
    # Eskirgan kodlarni tozalash
    now = time.time()
    for k in list(_otp_store):
        if _otp_store[k]["expires_at"] < now:
            del _otp_store[k]
    log.info(f"OTP yaratildi: {code} → test={test_id}")
    return code

def verify_otp(code: str) -> dict:
    """Kodni tekshirish — {test_id, uid} yoki {} qaytaradi"""
    import time
    entry = _otp_store.get(code.upper().strip())
    if not entry:
        return {"ok": False, "error": "Kod topilmadi"}
    if entry["expires_at"] < time.time():
        del _otp_store[code]
        return {"ok": False, "error": "Kod muddati tugagan"}
    if entry["used"]:
        return {"ok": False, "error": "Kod allaqachon ishlatilgan"}
    # Bir martalik — ishlatildi
    entry["used"] = True
    return {"ok": True, "test_id": entry["test_id"], "uid": entry["uid"]}

def get_otp_info(code: str) -> dict:
    """Kodni o'chirmasdan tekshirish (admin uchun)"""
    import time
    entry = _otp_store.get(code.upper().strip())
    if not entry or entry["expires_at"] < time.time():
        return {}
    return entry


async def web_sync_loop():
    """
    Har 5 daqiqada web index dan yangi testlar va statistikani tekshiradi.
    Faqat index faylini o'qiydi — kanal ga xabar yubormaydi.
    Bot ishlashiga ta'sir qilmaydi (fon task, asyncio).
    """
    await asyncio.sleep(30)   # Bot start dan 30s kutish
    consecutive_errors = 0

    while True:
        try:
            await asyncio.sleep(300)   # Har 5 daqiqada (avval 60s edi)
            if not ready():
                continue
            from utils import ram_cache as ram

            # Faqat index faylini o'qiymiz — probe/forward yo'q
            try:
                new_index = await asyncio.wait_for(_load_index(), timeout=20)
            except asyncio.TimeoutError:
                log.warning("web_sync: _load_index timeout — skip")
                consecutive_errors += 1
                continue

            if not (new_index and "tests_meta" in new_index):
                continue

            consecutive_errors = 0
            ram_metas   = {t.get("test_id") for t in ram.get_all_tests_meta()}
            index_metas = new_index.get("tests_meta", [])
            added = 0
            stats_updated = 0

            for meta in index_metas:
                tid = meta.get("test_id")
                if not tid:
                    continue

                if tid not in ram_metas:
                    # Yangi test — META qo'shamiz (savolsiz)
                    clean_meta = {k: v for k, v in meta.items() if k != "questions"}
                    ram.add_test_meta(clean_meta)
                    _index.setdefault("tests_meta", [])
                    if not any(m.get("test_id") == tid for m in _index["tests_meta"]):
                        _index["tests_meta"].insert(0, clean_meta)
                    msg_id = new_index.get(f"test_{tid}")
                    if msg_id:
                        _index[f"test_{tid}"] = msg_id
                    log.info(f"🌐 Web test qo'shildi: {meta.get('title','?')} ({tid})")
                    added += 1
                else:
                    # Saytda solve_count yangilangan bo'lsa — merge
                    web_sc  = meta.get("solve_count", 0)
                    web_avg = meta.get("avg_score", 0.0)
                    cur     = ram.get_test_meta(tid)
                    ram_sc  = cur.get("solve_count", 0)
                    if web_sc > ram_sc:
                        ram_avg = cur.get("avg_score", 0.0)
                        merged_avg = round(
                            (web_avg * web_sc + ram_avg * ram_sc) / (web_sc + ram_sc), 1
                        ) if ram_sc > 0 else web_avg
                        ram.update_test_meta(tid, {
                            "solve_count": web_sc,
                            "avg_score":   merged_avg,
                        })
                        stats_updated += 1

            if added:
                log.info(f"✅ Web sync: {added} yangi test")
            if stats_updated:
                log.info(f"📊 Web sync: {stats_updated} statistika yangilandi")
                mark_stats_dirty()

        except asyncio.CancelledError:
            break
        except Exception as e:
            consecutive_errors += 1
            log.error(f"web_sync_loop xato ({consecutive_errors}): {e}")
            if consecutive_errors >= 5:
                log.error("web_sync: 5 xato — 15 daqiqa tanaffus")
                await asyncio.sleep(900)
                consecutive_errors = 0

async def auto_flush_loop():
    """Har 2 daqiqada dirty bo'lsa TG ga yuboradi (avval 5 daqiqa edi)"""
    await asyncio.sleep(30)   # Startup dan 30s kuting
    while True:
        try:
            await asyncio.sleep(120)   # Har 2 daqiqada tekshirish
            if _stats_dirty:
                log.info("⚡ auto_flush: tests_stats yuborilmoqda...")
                await save_tests_stats()
            if _users_dirty:
                log.info("⚡ auto_flush: users_full yuborilmoqda...")
                await save_users_full()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"auto_flush: {e}")


def _restore_stats_from_index(index_data: dict):
    """Index dagi solve_count, avg_score ni RAM ga tiklash.
    tests_stats.json o'chirilgan bo'lsa ham asosiy statistika saqlanadi."""
    try:
        from utils import ram_cache as ram
        for m in index_data.get("tests_meta", []):
            tid = m.get("test_id")
            if not tid: continue
            sc  = m.get("solve_count", 0)
            avg = m.get("avg_score", 0.0)
            if sc > 0 or avg > 0:
                ram.update_test_meta(tid, {
                    "solve_count": sc,
                    "avg_score":   avg,
                })
    except Exception as e:
        log.warning(f"_restore_stats_from_index: {e}")


# ══ INDEX ══════════════════════════════════════════════════════

async def _load_index():
    if not ready(): return {}
    try:
        chat = await _bot.get_chat(_cid)
        pin  = getattr(chat, "pinned_message", None)
        if pin:
            doc = getattr(pin, "document", None)
            if doc and "index" in (doc.file_name or "").lower():
                data = await _read_file(doc.file_id)
                if isinstance(data, dict) and "tests_meta" in data:
                    log.info("✅ Index pindan yuklandi")
                    # Index dagi statistikani RAM ga o'tkazish
                    _restore_stats_from_index(data)
                    return data
    except Exception as e:
        log.warning(f"Pin o'qish: {e}")
    # Oxirgi 50 xabardan qidirish
    try:
        probe = await _bot.send_message(_cid, ".", protect_content=False)
        cur   = probe.message_id
        await _bot.delete_message(_cid, cur)
        for mid in range(cur - 1, max(1, cur - 50), -1):
            try:
                msg = await _bot.forward_message(_cid, _cid, mid)
                doc = getattr(msg, "document", None)
                try: await _bot.delete_message(_cid, msg.message_id)
                except: pass
                if doc and "index" in (doc.file_name or "").lower():
                    data = await _read_file(doc.file_id)
                    if isinstance(data, dict) and "tests_meta" in data:
                        # file_id ni indexga qo'shish (keyingi o'qishlar tez bo'ladi)
                        data[f"fid_{mid}"] = doc.file_id
                        await _pin_index(data)
                        return data
                await asyncio.sleep(0.05)
            except: pass
    except Exception as e:
        log.warning(f"Tarix qidirish: {e}")
    return {}

async def _save_index():
    global _can_pin
    if not ready(): return False
    try:
        # RAM dagi solve_count, avg_score ni index meta ga ham yozib qo'yamiz
        # Shunda tests_stats.json o'chirilsa ham index da asosiy statistika saqlanadi
        from utils import ram_cache as ram
        for m in _index.get("tests_meta", []):
            tid = m.get("test_id")
            if not tid: continue
            rm = ram.get_test_meta(tid)
            if not rm: continue
            if rm.get("solve_count", 0) > m.get("solve_count", 0):
                m["solve_count"] = rm.get("solve_count", 0)
            if rm.get("avg_score", 0.0) > 0:
                m["avg_score"] = rm.get("avg_score", 0.0)
            if rm.get("is_paused") is not None:
                m["is_paused"] = rm.get("is_paused", False)

        ts  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        msg = await _bot.send_document(_cid,
            document=_buf(_index, "index.json"),
            caption=f"📋 INDEX | {ts}",
            protect_content=False)
        _index["_last_index_msg_id"] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id   # index file_id
        if _can_pin:
            try: await _bot.pin_chat_message(_cid, msg.message_id, disable_notification=True)
            except: _can_pin = False
        return True
    except Exception as e:
        log.error(f"Index saqlash: {e}")
        return False

async def _pin_index(data):
    try:
        msg = await _bot.send_document(_cid,
            document=_buf(data, "index.json"), caption="📋 INDEX",
            protect_content=False)
        _index[f"fid_{msg.message_id}"] = msg.document.file_id   # file_id cache
        await _bot.pin_chat_message(_cid, msg.message_id, disable_notification=True)
    except Exception as e:
        log.warning(f"Pin: {e}")


# ══ TESTLAR ════════════════════════════════════════════════════

def get_tests_meta():
    return _index.get("tests_meta", [])

def get_test_meta(tid):
    return next((t for t in get_tests_meta()
                 if t.get("test_id") == tid and t.get("is_active", True)), {})

async def get_test_full(tid):
    """
    Test savollarini yuklash (lazy load):
    1. RAM qcache → 2. _index msg_id → 3. web index qayta o'qish
    Savollar yuklanib bo'lgach bot ularni ishlatadi, keyin cache evict bo'ladi.
    """
    from utils import ram_cache as ram
    # 1. _tests_cache (tez)
    if tid in _tests_cache:
        ram.touch_test_access(tid)
        return _tests_cache[tid]
    # 2. RAM qcache
    cached = ram.get_cached_questions(tid)
    if cached:
        _tests_cache[tid] = cached
        return cached
    # 3. TG kanaldan lazy load — avval file_id dan, keyin forward
    msg_id = _index.get(f"test_{tid}")
    # Agar fid_ allaqachon saqlangan bo'lsa, to'g'ridan yuklaymiz (forward siz)
    if msg_id and _index.get(f"fid_{msg_id}"):
        data = await _read_file(_index[f"fid_{msg_id}"])
        if data and data.get("questions"):
            _tests_cache[tid] = data
            ram.cache_questions(tid, data)
            log.info(f"✅ {tid} fid dan yuklandi ({len(data['questions'])} savol)")
            return data
        else:
            _index.pop(f"fid_{msg_id}", None)   # Ishlamagan fid ni o'chir
    if not msg_id:
        # msg_id yo'q — web test yoki hali index ga tushmagan
        # Indexni qayta o'qib tekshiramiz (silent)
        new_index = await _load_index()
        if new_index:
            msg_id = new_index.get(f"test_{tid}")
            if msg_id:
                _index[f"test_{tid}"] = msg_id
                if not any(m.get("test_id") == tid for m in _index.get("tests_meta", [])):
                    for m in new_index.get("tests_meta", []):
                        if m.get("test_id") == tid:
                            clean = {k: v for k, v in m.items() if k != "questions"}
                            _index.setdefault("tests_meta", []).insert(0, clean)
                            ram.add_test_meta(clean)
                            break
        if not msg_id:
            # Normal holat — web test hali sync bo'lmagan (5 daqiqada bo'ladi)
            log.info(f"ℹ️ {tid} msg_id yo'q (web test sync kutilmoqda)")
            return {}
    log.info(f"⬇️ Lazy load: {tid} (msg={msg_id})")
    data = await _download_doc(msg_id)
    if data and data.get("questions"):
        _tests_cache[tid] = data
        ram.cache_questions(tid, data)
        log.info(f"✅ {tid} yuklandi ({len(data['questions'])} savol)")
        return data
    if not data:
        log.warning(f"⚠️ {tid} TGdan yuklanmadi")
        for m in _index.get("tests_meta", []):
            if m.get("test_id") == tid:
                m["is_active"] = False
                break
        ram.update_test_meta(tid, {"is_active": False})
    return {}

async def get_tests():
    return _index.get("tests_meta", [])

async def save_test_full(test):
    if not ready(): return False
    tid = test.get("test_id", "")
    try:
        qc  = len(test.get("questions", []))
        msg = await _bot.send_document(_cid,
            document=_buf(test, f"test_{tid}.json"),
            caption=f"📝 {test.get('title','?')} | {test.get('category','')} | {qc} savol | {tid}",
            protect_content=False)
        _index[f"test_{tid}"] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id   # file_id cache
        _tests_cache[tid] = test
        meta  = {k: v for k, v in test.items() if k != "questions"}
        meta["question_count"] = qc
        metas = [m for m in _index.get("tests_meta", []) if m.get("test_id") != tid]
        metas.insert(0, meta)
        _index["tests_meta"] = metas
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_test_full: {e}")
        return False

async def save_deleted_test_backup(test):
    if not ready(): return
    tid = test.get("test_id", "NOID")
    _tests_cache.pop(tid, None)
    try:
        await _bot.send_document(_cid,
            document=_buf(test, f"DELETED_test_{tid}.json"),
            caption=f"🗑 O'CHIRILGAN: {test.get('title','?')} | {tid}",
            protect_content=False)
    except Exception as e:
        log.error(f"delete backup: {e}")

async def delete_test_tg(tid):
    for m in _index.get("tests_meta", []):
        if m.get("test_id") == tid:
            m["is_active"] = False
            break
    _tests_cache.pop(tid, None)
    await _save_index()
    # Stats ham yangilash
    mark_stats_dirty()

async def update_test_meta_tg(tid, updates):
    for m in _index.get("tests_meta", []):
        if m.get("test_id") == tid:
            m.update(updates)
            break
    await _save_index()


# ══ USERS (eski moslik) ════════════════════════════════════════

async def get_users():
    mid = _index.get("users_full_msg_id") or _index.get("users_msg_id")
    if not mid: return {}
    data = await _download_doc(mid)
    return data.get("users", {}) if isinstance(data, dict) else {}

async def save_users(users):
    """Eski users.json — moslik uchun, save_users_full ishlatish tavsiya"""
    return await save_users_full()


# ══ SETTINGS ═══════════════════════════════════════════════════

async def save_settings(settings_dict):
    if not ready(): return False
    try:
        ts  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        msg = await _bot.send_document(_cid,
            document=_buf({"settings": settings_dict, "saved_at": ts}, "settings.json"),
            caption=f"⚙️ SETTINGS | {ts}",
            protect_content=False)
        _index["settings_msg_id"] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id   # file_id cache
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_settings: {e}")
        return False

async def get_settings_tg():
    mid = _index.get("settings_msg_id")
    if not mid: return {}
    data = await _download_doc(mid)
    return data.get("settings", {}) if isinstance(data, dict) else {}


# ══ BACKUP (midnight) ══════════════════════════════════════════

async def upload_backup(daily_data, date_str):
    if not ready(): return 0
    try:
        r_count = sum(len(v.get("by_test", {})) for v in daily_data.values())
        ts      = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        msg     = await _bot.send_document(_cid,
            document=_buf({
                "date": date_str, "saved_at": ts,
                "users": len(daily_data), "results": r_count,
                "data":  daily_data,
            }, f"backup_{date_str}.json"),
            caption=f"💾 BACKUP | {date_str} | {len(daily_data)} user | {r_count} natija",
            protect_content=False)
        if "backups" not in _index:
            _index["backups"] = {}
        _index["backups"][date_str] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id   # file_id cache
        await _save_index()
        log.info(f"✅ Backup: {date_str}")
        return msg.message_id
    except Exception as e:
        log.error(f"backup: {e}")
        return 0

async def get_backup(date_str):
    mid = _index.get("backups", {}).get(date_str)
    if not mid: return {}
    data = await _download_doc(mid)
    return data.get("data", {}) if isinstance(data, dict) else {}

def get_backup_dates():
    return sorted(_index.get("backups", {}).keys(), reverse=True)


# ══ PRELOAD ════════════════════════════════════════════════════

async def _preload_from_last_backup():
    """
    Bot start'da oxirgi backup dan faqat msg_id larni _index ga yuklaymiz.
    Savollar yuklanmaydi — kerak bo'lganda lazy load bo'ladi.
    """
    backups = _index.get("backups", {})
    clean_dates = [d for d in backups.keys() if "_manual" not in d]
    if not clean_dates:
        log.info("ℹ️ Backup yo'q — barcha testlar lazy load bo'ladi")
        return
    # Faqat index da test_{tid} msg_id lar borligini tekshiramiz
    metas = _index.get("tests_meta", [])
    missing = [m.get("test_id") for m in metas if not _index.get(f"test_{m.get('test_id')}")]
    if missing:
        log.info(f"ℹ️ {len(missing)} test uchun msg_id yo'q — ular lazy load bo'ladi: {missing[:5]}...")
    log.info(f"✅ Preload o'tkazib yuborildi — {len(metas)} test meta, savollar on-demand yuklandi")


# ══ MANUAL FLUSH ══════════════════════════════════════════════

async def manual_flush(daily_data, users, settings=None):
    results = []
    if not ready():
        return ["❌ TG kanal ulanmagan"]
    ok = await save_tests_stats()
    results.append(f"{'✅' if ok else '❌'} Tests stats")
    ok = await save_users_full()
    results.append(f"{'✅' if ok else '❌'} Users full: {len(users)} ta")
    if settings:
        ok = await save_settings(settings)
        results.append(f"{'✅' if ok else '❌'} Settings")
    if daily_data:
        from datetime import date
        today = str(date.today())
        mid   = await upload_backup(daily_data, f"{today}_manual")
        results.append(f"{'✅' if mid else '❌'} Backup: {len(daily_data)} user")
    return results

def get_index_info():
    return {
        "tests_count":  len(_index.get("tests_meta", [])),
        "cached_tests": len(_tests_cache),
        "users_msg_id": _index.get("users_full_msg_id"),
        "backups":      len(_index.get("backups", {})),
        "can_pin":      _can_pin,
        "stats_dirty":  _stats_dirty,
        "users_dirty":  _users_dirty,
    }


# ══ YORDAMCHILAR ═══════════════════════════════════════════════

async def _download_doc(msg_id):
    """
    Kanaldan fayl yuklab olish.

    STRATEGIYA (protect_content muammosini bartaraf etish):
    1. _index da file_id saqlangan bo'lsa — to'g'ridan yuklash (FORWARD siz)
    2. copyMessage — forward dan ko'ra ishonchli, protect_content ta'sir qilmaydi
    3. forward_message — oxirgi fallback

    MUHIM: getMessages — Bot API da YO'Q (faqat MTProto), shuning uchun o'chirildi.
    file_id Telegram serverlarida abadiy saqlanadi va bot uchun doim ishlatiladi.
    """
    # ── 1. Index da file_id saqlangan bo'lsa — to'g'ridan ─────
    fid_key = f"fid_{msg_id}"
    cached_fid = _index.get(fid_key)
    if cached_fid:
        data = await _read_file(cached_fid)
        if data:
            return data
        # file_id ishlamasa indexdan o'chirib davom etamiz
        _index.pop(fid_key, None)

    # ── 2. copyMessage — protect_content ta'sir qilmaydi ─────
    try:
        copied = await _bot.copy_message(
            chat_id=_cid,
            from_chat_id=_cid,
            message_id=int(msg_id),
            protect_content=False
        )
        # copy qaytargan message_id dan faylni olish
        copied_mid = copied.message_id
        # Copied xabarni forward qilmasdan file_id olish uchun
        # Bot API da getChatMessage yo'q, shuning uchun forward orqali file_id olamiz
        fwd2 = await _bot.forward_message(_cid, _cid, copied_mid)
        doc2 = getattr(fwd2, "document", None)
        try: await _bot.delete_message(_cid, copied_mid)
        except: pass
        try: await _bot.delete_message(_cid, fwd2.message_id)
        except: pass
        if doc2:
            # file_id ni cache qilish
            _index[fid_key] = doc2.file_id
            return await _read_file(doc2.file_id)
    except Exception as e:
        log.debug(f"copy+forward {msg_id}: {e}")

    # ── 3. Fallback: to'g'ri forward ──────────────────────────
    try:
        fwd = await _bot.forward_message(_cid, _cid, int(msg_id))
        doc = getattr(fwd, "document", None)
        try: await _bot.delete_message(_cid, fwd.message_id)
        except: pass
        if doc:
            _index[fid_key] = doc.file_id   # Keyingi safar tez ishlaydi
            return await _read_file(doc.file_id)
    except Exception as e:
        log.error(f"download_doc {msg_id}: {e}")

    return {}

async def _read_file(file_id):
    try:
        f   = await _bot.get_file(file_id)
        buf = io.BytesIO()
        await _bot.download_file(f.file_path, destination=buf)
        buf.seek(0)
        return json.loads(buf.read().decode())
    except Exception as e:
        log.error(f"read_file: {e}")
        return {}

def _buf(data, name):
    from aiogram.types import BufferedInputFile
    raw = json.dumps(data, ensure_ascii=False, default=str, indent=2).encode()
    return BufferedInputFile(raw, filename=name)
