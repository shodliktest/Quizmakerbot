"""
TG_DB — Yangi arxitektura (chunked storage)
============================================
INDEX (pinned):
  tests_meta: [{test_id, title, ...}]   ← barcha test meta (yengil)
  user_chunks: [{chunk_n, msg_id, uids:[uid1,uid2,...]}]  ← 100 ta uid per chunk
  backups: {date: msg_id}
  settings_msg_id, tests_stats_msg_id

FAYLLAR:
  user_{uid}.json     ← har user uchun alohida: profil + by_test stats
  test_{tid}.json     ← test savollari (o'zgarmagan)
  tests_stats.json    ← test statistikasi (solve_count, avg, solvers)
  backup_DATE.json    ← kunlik backup

QOIDALAR:
  - Har user uchun alohida fayl → 20MB muammo yo'q
  - user_chunks index orqali qaysi chunkda ekanini bilamiz
  - Eski user fayli yangilanishdan oldin o'chiriladi
  - Guruh natijalari saqlanmaydi
"""
import json, logging, io, asyncio
from datetime import datetime, timezone

log      = logging.getLogger(__name__)
UTC      = timezone.utc
_bot     = None
_cid     = None
_index:  dict = {}
_can_pin = True
_tests_cache: dict = {}

_stats_dirty = False
_users_dirty = False

USER_CHUNK_SIZE = 100   # har chunkda max 100 user


async def init(bot, channel_id):
    global _bot, _cid, _index, _tests_cache, _stats_dirty, _users_dirty
    _cid = int(channel_id)
    _index = {}
    _tests_cache = {}
    _stats_dirty = False
    _users_dirty = False

    from aiogram import Bot as _BotClass
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    _bot = _BotClass(
        token=bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, protect_content=False)
    )

    _index = await _load_index()
    if not _index:
        log.info("ℹ️ Yangi baza yaratilmoqda...")
        _index = {"tests_meta": [], "backups": {}, "user_chunks": []}
        await _save_index()
        log.info("✅ Yangi baza yaratildi")
        return

    log.info(f"✅ Index: {len(_index.get('tests_meta', []))} meta, "
             f"{len(_index.get('user_chunks', []))} user chunk")

    # 1. tests_stats yukla
    await _load_tests_stats()
    # 2. Barcha userlarni chunkdan yukla
    await _load_all_users()
    # 3. Qayta yozish kerak bo'lsa
    if _stats_dirty:
        await save_tests_stats()
    if _users_dirty:
        await _flush_dirty_users()

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


# ══ USER CHUNKS ═══════════════════════════════════════════════

def _find_user_chunk(uid_str):
    """Userning chunk indexini topish"""
    for i, chunk in enumerate(_index.get("user_chunks", [])):
        if uid_str in chunk.get("uids", []):
            return i, chunk
    return -1, None

def _get_or_create_chunk_for_user(uid_str):
    """Mavjud bo'sh chunkni topish yoki yangi yaratish"""
    chunks = _index.get("user_chunks", [])
    # Mavjud chunkda joy bormi?
    for i, chunk in enumerate(chunks):
        if uid_str in chunk.get("uids", []):
            return i   # allaqachon bor
        if len(chunk.get("uids", [])) < USER_CHUNK_SIZE:
            chunk["uids"].append(uid_str)
            return i
    # Yangi chunk
    new_chunk = {"chunk_n": len(chunks) + 1, "msg_id": None, "uids": [uid_str]}
    chunks.append(new_chunk)
    _index["user_chunks"] = chunks
    return len(chunks) - 1


# ══ USERS YUKLASH ══════════════════════════════════════════════

async def _load_all_users():
    """Barcha user chunklanrini yuklab RAM ga joylash"""
    global _users_dirty
    from utils import ram_cache as ram
    chunks  = _index.get("user_chunks", [])
    total   = 0
    for chunk in chunks:
        mid = chunk.get("msg_id")
        if not mid:
            continue
        data = await _download_doc(mid)
        if not data:
            log.warning(f"⚠️ User chunk {chunk.get('chunk_n')} o'qilmadi")
            _users_dirty = True
            continue
        users_in_chunk = data.get("users", {})
        # Profil
        cur = ram.get_users()
        cur.update(users_in_chunk)
        ram.set_users(cur)
        # Natijalar meta (by_test)
        by_test = data.get("by_test", {})
        if by_test:
            ram.load_history_to_ram(by_test)
        total += len(users_in_chunk)
    log.info(f"✅ Users yuklandi: {total} ta ({len(chunks)} chunk)")


async def save_user(uid_str, user_data, results_meta=None):
    """
    Bitta userni TG ga saqlash.
    - Eski fayli o'chiriladi
    - Yangi fayl yuboriladi
    - Chunk index yangilanadi
    """
    if not ready():
        return False
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    chunk_idx = _get_or_create_chunk_for_user(uid_str)
    chunk     = _index["user_chunks"][chunk_idx]

    # Eski faylni o'chirish
    old_mid = chunk.get(f"user_msg_{uid_str}")
    if old_mid:
        try: await _bot.delete_message(_cid, old_mid)
        except: pass

    payload = {
        "uid":      uid_str,
        "user":     user_data,
        "by_test":  results_meta or {},
        "saved_at": ts,
    }
    try:
        msg = await _bot.send_document(
            _cid,
            document=_buf(payload, f"user_{uid_str}.json"),
            caption=f"👤 USER | {uid_str} | {user_data.get('name','?')} | {ts}",
            protect_content=False
        )
        chunk[f"user_msg_{uid_str}"] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id
        return True
    except Exception as e:
        log.error(f"save_user {uid_str}: {e}")
        return False


async def _flush_dirty_users():
    """
    Barcha o'zgargan userlarni TG ga saqlash.
    Har user uchun alohida fayl.
    """
    global _users_dirty
    from utils import ram_cache as ram
    users   = ram.get_users()
    saved   = 0
    for uid_str, user_data in users.items():
        # Natijalar meta
        results = ram.get_all_user_stats(uid_str)
        ok = await save_user(uid_str, user_data, results)
        if ok:
            saved += 1
        await asyncio.sleep(0.05)   # Flood oldini olish
    await _save_index()
    _users_dirty = False
    log.info(f"✅ Users flushed: {saved} ta")


# ══ TESTS STATS ════════════════════════════════════════════════

async def _load_tests_stats():
    global _stats_dirty
    mid = _index.get("tests_stats_msg_id")
    if not mid:
        return
    fid  = _index.get(f"fid_{mid}")
    data = await _read_file(fid) if fid else {}
    if not data:
        _index.pop(f"fid_{mid}", None)
        data = await _download_doc(mid)
    if not data:
        log.warning(f"⚠️ tests_stats o'qilmadi — qayta yoziladi")
        _stats_dirty = True
        return
    from utils import ram_cache as ram
    for tid, s in data.get("stats", {}).items():
        ram.update_test_meta(tid, {
            "solve_count": s.get("solve_count", 0),
            "avg_score":   s.get("avg_score", 0.0),
            "is_paused":   s.get("is_paused", False),
            "is_active":   s.get("is_active", True),
        })
        if s.get("solvers"):
            ram.load_solvers_to_ram(tid, s["solvers"])
    log.info(f"✅ tests_stats: {len(data.get('stats', {}))} test")


async def save_tests_stats():
    global _stats_dirty
    if not ready(): return False
    from utils import ram_cache as ram
    metas  = ram.get_all_tests_meta()
    daily  = ram.get_daily()
    stats  = {}
    for m in metas:
        tid = m.get("test_id", "")
        if not tid: continue
        solvers = {}
        for uid_str, udata in daily.items():
            entry = udata.get("by_test", {}).get(tid)
            if entry and entry.get("attempts", 0) > 0:
                solvers[uid_str] = {
                    "attempts":   entry["attempts"],
                    "best_score": entry["best_score"],
                    "avg_score":  entry["avg_score"],
                    "all_pcts":   entry["all_pcts"],
                    "last_at":    entry.get("last_at", ""),
                }
        stats[tid] = {
            "solve_count": m.get("solve_count", 0),
            "avg_score":   m.get("avg_score", 0.0),
            "is_paused":   m.get("is_paused", False),
            "is_active":   m.get("is_active", True),
            "solvers":     solvers,
        }
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    try:
        old_mid = _index.get("tests_stats_msg_id")
        if old_mid:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        msg = await _bot.send_document(_cid,
            document=_buf({"stats": stats, "saved_at": ts}, "tests_stats.json"),
            caption=f"📊 TESTS_STATS | {len(stats)} test | {ts}",
            protect_content=False)
        _index["tests_stats_msg_id"] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id
        await _save_index()
        _stats_dirty = False
        log.info(f"✅ tests_stats saqlandi: {len(stats)} test")
        return True
    except Exception as e:
        log.error(f"save_tests_stats: {e}")
        return False


# ══ AUTO-FLUSH ════════════════════════════════════════════════

async def auto_flush_loop():
    """Har 2 daqiqada dirty bo'lsa TG ga yuboradi"""
    await asyncio.sleep(30)
    while True:
        try:
            await asyncio.sleep(120)
            if _stats_dirty:
                log.info("⚡ auto_flush: tests_stats...")
                await save_tests_stats()
            if _users_dirty:
                log.info("⚡ auto_flush: users...")
                await _flush_dirty_users()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"auto_flush: {e}")


# ══ OTP ════════════════════════════════════════════════════════

_otp_store: dict = {}

def generate_otp(test_id: str, uid: int = 0) -> str:
    import random, string, time
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    _otp_store[code] = {
        "test_id": test_id, "uid": uid,
        "expires_at": time.time() + 600, "used": False,
    }
    now = time.time()
    for k in list(_otp_store):
        if _otp_store[k]["expires_at"] < now:
            del _otp_store[k]
    return code

def verify_otp(code: str) -> dict:
    import time
    entry = _otp_store.get(code.upper().strip())
    if not entry: return {"ok": False, "error": "Kod topilmadi"}
    if entry["expires_at"] < time.time():
        del _otp_store[code]
        return {"ok": False, "error": "Kod muddati tugagan"}
    if entry["used"]: return {"ok": False, "error": "Kod ishlatilgan"}
    entry["used"] = True
    return {"ok": True, "test_id": entry["test_id"], "uid": entry["uid"]}

def get_otp_info(code: str) -> dict:
    import time
    entry = _otp_store.get(code.upper().strip())
    if not entry or entry["expires_at"] < time.time(): return {}
    return entry


# ══ WEB SYNC ══════════════════════════════════════════════════

async def web_sync_loop():
    """Har 12 soatda saytdan yangi testlarni tekshiradi"""
    await asyncio.sleep(30)
    consecutive_errors = 0
    while True:
        try:
            await asyncio.sleep(43200)   # 12 soat
            if not ready(): continue
            from utils import ram_cache as ram
            try:
                new_index = await asyncio.wait_for(_load_index(), timeout=20)
            except asyncio.TimeoutError:
                consecutive_errors += 1
                continue
            if not (new_index and "tests_meta" in new_index):
                continue
            consecutive_errors = 0
            ram_ids = {t.get("test_id") for t in ram.get_all_tests_meta()}
            added   = 0
            for meta in new_index.get("tests_meta", []):
                tid = meta.get("test_id")
                if not tid or tid in ram_ids: continue
                clean = {k: v for k, v in meta.items() if k != "questions"}
                ram.add_test_meta(clean)
                if not any(m.get("test_id") == tid for m in _index.get("tests_meta", [])):
                    _index.setdefault("tests_meta", []).insert(0, clean)
                msg_id = new_index.get(f"test_{tid}")
                if msg_id: _index[f"test_{tid}"] = msg_id
                added += 1
            if added:
                log.info(f"✅ Web sync: {added} yangi test")
                mark_stats_dirty()
        except asyncio.CancelledError:
            break
        except Exception as e:
            consecutive_errors += 1
            log.error(f"web_sync_loop xato ({consecutive_errors}): {e}")
            if consecutive_errors >= 5:
                await asyncio.sleep(900)
                consecutive_errors = 0


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
                    _restore_stats_from_index(data)
                    return data
    except Exception as e:
        log.warning(f"Pin o'qish: {e}")
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
    from utils import ram_cache as ram
    for m in _index.get("tests_meta", []):
        tid = m.get("test_id")
        if not tid: continue
        rm = ram.get_test_meta(tid)
        if not rm: continue
        if rm.get("solve_count", 0) > m.get("solve_count", 0):
            m["solve_count"] = rm["solve_count"]
        if rm.get("avg_score", 0.0) > 0:
            m["avg_score"] = rm["avg_score"]
        if rm.get("is_paused") is not None:
            m["is_paused"] = rm["is_paused"]
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    try:
        msg = await _bot.send_document(_cid,
            document=_buf(_index, "index.json"),
            caption=f"📋 INDEX | {ts}",
            protect_content=False)
        _index["_last_index_msg_id"] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id
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
        _index[f"fid_{msg.message_id}"] = msg.document.file_id
        await _bot.pin_chat_message(_cid, msg.message_id, disable_notification=True)
    except Exception as e:
        log.warning(f"Pin: {e}")


def _restore_stats_from_index(index_data: dict):
    try:
        from utils import ram_cache as ram
        for m in index_data.get("tests_meta", []):
            tid = m.get("test_id")
            if not tid: continue
            if m.get("solve_count", 0) > 0 or m.get("avg_score", 0) > 0:
                ram.update_test_meta(tid, {
                    "solve_count": m.get("solve_count", 0),
                    "avg_score":   m.get("avg_score", 0.0),
                })
    except Exception as e:
        log.warning(f"_restore_stats_from_index: {e}")


# ══ TESTLAR ════════════════════════════════════════════════════

def get_tests_meta():
    return _index.get("tests_meta", [])

def get_test_meta(tid):
    return next((t for t in get_tests_meta()
                 if t.get("test_id") == tid and t.get("is_active", True)), {})

async def get_test_full(tid):
    from utils import ram_cache as ram
    if tid in _tests_cache:
        ram.touch_test_access(tid)
        return _tests_cache[tid]
    cached = ram.get_cached_questions(tid)
    if cached:
        _tests_cache[tid] = cached
        return cached
    msg_id = _index.get(f"test_{tid}")
    if msg_id and _index.get(f"fid_{msg_id}"):
        data = await _read_file(_index[f"fid_{msg_id}"])
        if data and data.get("questions"):
            _tests_cache[tid] = data
            ram.cache_questions(tid, data)
            log.info(f"✅ {tid} fid dan yuklandi ({len(data['questions'])} savol)")
            return data
        else:
            _index.pop(f"fid_{msg_id}", None)
    if not msg_id:
        new_index = await _load_index()
        if new_index:
            msg_id = new_index.get(f"test_{tid}")
            if msg_id:
                _index[f"test_{tid}"] = msg_id
                for m in new_index.get("tests_meta", []):
                    if m.get("test_id") == tid:
                        clean = {k: v for k, v in m.items() if k != "questions"}
                        _index.setdefault("tests_meta", []).insert(0, clean)
                        ram.add_test_meta(clean)
                        break
        if not msg_id:
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
        _index[f"fid_{msg.message_id}"] = msg.document.file_id
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
    mark_stats_dirty()

async def update_test_meta_tg(tid, updates):
    for m in _index.get("tests_meta", []):
        if m.get("test_id") == tid:
            m.update(updates)
            break
    await _save_index()


# ══ USERS (moslik) ════════════════════════════════════════════

async def get_users():
    from utils import ram_cache as ram
    return ram.get_users()

async def save_users(users):
    mark_users_dirty_tg()
    return True

async def save_users_full():
    await _flush_dirty_users()
    return True


# ══ SETTINGS ══════════════════════════════════════════════════

async def save_settings(settings_dict):
    if not ready(): return False
    try:
        ts  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        old_mid = _index.get("settings_msg_id")
        if old_mid:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        msg = await _bot.send_document(_cid,
            document=_buf({"settings": settings_dict, "saved_at": ts}, "settings.json"),
            caption=f"⚙️ SETTINGS | {ts}",
            protect_content=False)
        _index["settings_msg_id"] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id
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


# ══ BACKUP ════════════════════════════════════════════════════

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
        _index.setdefault("backups", {})[date_str] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id
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
    metas   = _index.get("tests_meta", [])
    missing = [m.get("test_id") for m in metas if not _index.get(f"test_{m.get('test_id')}")]
    if missing:
        log.info(f"ℹ️ {len(missing)} test lazy load bo'ladi")
    log.info(f"✅ Preload: {len(metas)} test meta")


# ══ MANUAL FLUSH ══════════════════════════════════════════════

async def manual_flush(daily_data, users, settings=None):
    results = []
    if not ready():
        return ["❌ TG kanal ulanmagan"]
    ok = await save_tests_stats()
    results.append(f"{'✅' if ok else '❌'} Tests stats")
    await _flush_dirty_users()
    results.append(f"✅ Users: {len(users)} ta")
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
        "user_chunks":  len(_index.get("user_chunks", [])),
        "backups":      len(_index.get("backups", {})),
        "can_pin":      _can_pin,
        "stats_dirty":  _stats_dirty,
        "users_dirty":  _users_dirty,
    }


# ══ YORDAMCHILAR ══════════════════════════════════════════════

async def _download_doc(msg_id):
    fid_key    = f"fid_{msg_id}"
    cached_fid = _index.get(fid_key)
    if cached_fid:
        data = await _read_file(cached_fid)
        if data: return data
        _index.pop(fid_key, None)
    try:
        copied    = await _bot.copy_message(_cid, _cid, int(msg_id), protect_content=False)
        copied_mid = copied.message_id
        fwd2      = await _bot.forward_message(_cid, _cid, copied_mid)
        doc2      = getattr(fwd2, "document", None)
        try: await _bot.delete_message(_cid, copied_mid)
        except: pass
        try: await _bot.delete_message(_cid, fwd2.message_id)
        except: pass
        if doc2:
            _index[fid_key] = doc2.file_id
            return await _read_file(doc2.file_id)
    except Exception as e:
        log.debug(f"copy+forward {msg_id}: {e}")
    try:
        fwd = await _bot.forward_message(_cid, _cid, int(msg_id))
        doc = getattr(fwd, "document", None)
        try: await _bot.delete_message(_cid, fwd.message_id)
        except: pass
        if doc:
            _index[fid_key] = doc.file_id
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
    raw = json.dumps(data, ensure_ascii=False, default=str, separators=(",",":")).encode()
    return BufferedInputFile(raw, filename=name)
