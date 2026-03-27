"""
TG_DB — Mukammal arxitektura
==============================
INDEX (pinned):
  tests_meta: [...]
  users_list_chunks: [{n, msg_id, uids:[...], size_kb}]  ← 10MB gacha
  user_stats_chunks: [{n, msg_id, uids:[...50]}]          ← 50 userdan
  leaderboard_msg_id
  group_lb_msg_id
  tests_stats_msg_id
  backups: {date: msg_id}

FAYLLAR:
  users_list_N.json    ← uid+profil, 10MB gacha
  user_stats_N.json    ← 50 user stats
  leaderboard.json     ← global top 20
  group_lb_DATE.json   ← guruh top 20 (kunlik)
  tests_stats.json     ← test meta stats
  test_XXX.json        ← test savollari (o'zgarmaydi)
  backup_DATE.json     ← kunlik backup
"""
import json, logging, io, asyncio
from datetime import datetime, timezone, date

log      = logging.getLogger(__name__)
UTC      = timezone.utc
_bot     = None
_cid     = None
_index:  dict = {}
_can_pin = True
_tests_cache: dict = {}

_stats_dirty    = False
_users_dirty    = False


USERS_LIST_CHUNK_KB = 9000
USER_STATS_CHUNK    = 50


async def init(bot, channel_id):
    global _bot, _cid, _index, _tests_cache, _stats_dirty, _users_dirty, _creators_dirty, _creators
    _cid = int(channel_id)
    _index = {}
    _tests_cache = {}
    _stats_dirty    = False
    _users_dirty    = False

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
        _index = {
            "tests_meta": [], "backups": {},
            "users_list_chunks": [], "user_stats_chunks": [],
        }
        await _save_index()
        return

    log.info(f"✅ Index: {len(_index.get('tests_meta',[]))} test, "
             f"{len(_index.get('users_list_chunks',[]))} user chunk, "
             f"{len(_index.get('user_stats_chunks',[]))} stats chunk")

    await _load_tests_stats()
    await _load_users_list()
    await _load_leaderboard()

    if _stats_dirty: await save_tests_stats()
    if _users_dirty: await _flush_users_list()
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


# ══ USERS LIST (profil, kichik) ════════════════════════════════

async def _load_users_list():
    """Barcha users_list chunklanrini yuklab RAM ga"""
    global _users_dirty
    from utils import ram_cache as ram
    chunks = _index.get("users_list_chunks", [])
    total  = 0
    for chunk in chunks:
        mid = chunk.get("msg_id")
        if not mid: continue
        data = await _download_doc(mid)
        if not data:
            _users_dirty = True
            continue
        users = data.get("users", {})
        cur   = ram.get_users()
        cur.update(users)
        ram.set_users(cur)
        total += len(users)
    log.info(f"✅ Users ro'yxati: {total} ta ({len(chunks)} chunk)")


async def _flush_users_list():
    """O'zgargan users ni chunklab TG ga yozish"""
    global _users_dirty
    from utils import ram_cache as ram
    users = ram.get_users()
    if not users: return

    # Barcha userlarni chunklarga bo'lish (9MB gacha)
    chunks    = _index.get("users_list_chunks", [])
    all_uids  = list(users.keys())

    # Har chunk uchun uids ni bilamiz — faqat o'zgarganlari qayta yoziladi
    # Soddaligi uchun: barcha chunklar bir marta qayta yoziladi
    chunk_size = 500   # 500 user per chunk
    uid_groups = [all_uids[i:i+chunk_size] for i in range(0, len(all_uids), chunk_size)]

    new_chunks = []
    for i, group in enumerate(uid_groups):
        chunk_users = {uid: users[uid] for uid in group if uid in users}
        ts  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        old_mid = chunks[i]["msg_id"] if i < len(chunks) else None
        if old_mid:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        try:
            msg = await _bot.send_document(_cid,
                document=_buf({"users": chunk_users, "count": len(chunk_users), "saved_at": ts},
                              f"users_list_{i+1}.json"),
                caption=f"👥 USERS_LIST_{i+1} | {len(chunk_users)} user | {ts}",
                protect_content=False)
            new_chunks.append({"n": i+1, "msg_id": msg.message_id,
                                "uids": group, "count": len(chunk_users)})
            _index[f"fid_{msg.message_id}"] = msg.document.file_id
            await asyncio.sleep(0.5)
        except Exception as e:
            log.error(f"users_list chunk {i+1}: {e}")
            if i < len(chunks):
                new_chunks.append(chunks[i])

    _index["users_list_chunks"] = new_chunks
    await _save_index()
    _users_dirty = False
    log.info(f"✅ Users list saqlandi: {len(users)} ta, {len(new_chunks)} chunk")


# ══ USER STATS (50 tadan chunk, 1 soatda) ══════════════════════

async def flush_dirty_user_stats():
    """
    Har 1 soatda: faqat o'zgargan stats chunklar yoziladi.
    Guruh natijalari saqlanmaydi.
    """
    from utils import ram_cache as ram
    dirty_stats = ram.get_dirty_user_stats()   # {uid: {tid: {...}}}
    if not dirty_stats:
        return

    chunks = _index.get("user_stats_chunks", [])
    # Qaysi chunklar o'zgardi
    dirty_chunk_ids = set()
    for uid_str in dirty_stats:
        for i, chunk in enumerate(chunks):
            if uid_str in chunk.get("uids", []):
                dirty_chunk_ids.add(i)
                break
        else:
            # Yangi user — oxirgi chunkga qo'shish yoki yangi chunk
            if chunks and len(chunks[-1].get("uids", [])) < USER_STATS_CHUNK:
                chunks[-1]["uids"].append(uid_str)
                dirty_chunk_ids.add(len(chunks) - 1)
            else:
                chunks.append({"n": len(chunks)+1, "msg_id": None, "uids": [uid_str]})
                dirty_chunk_ids.add(len(chunks) - 1)

    users = ram.get_users()
    ts    = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    saved = 0

    for i in dirty_chunk_ids:
        if i >= len(chunks): continue
        chunk = chunks[i]
        chunk_stats = {}
        for uid_str in chunk.get("uids", []):
            s = ram.get_user_stats_cache(uid_str)
            if s:
                chunk_stats[uid_str] = s
        if not chunk_stats: continue

        old_mid = chunk.get("msg_id")
        if old_mid:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        try:
            msg = await _bot.send_document(_cid,
                document=_buf({"stats": chunk_stats, "saved_at": ts},
                              f"user_stats_{i+1}.json"),
                caption=f"📊 USER_STATS_{i+1} | {len(chunk_stats)} user | {ts}",
                protect_content=False)
            chunk["msg_id"] = msg.message_id
            _index[f"fid_{msg.message_id}"] = msg.document.file_id
            saved += 1
            # Dirty flaglarni tozalash
            for uid_str in chunk.get("uids", []):
                ram.clear_stats_dirty(uid_str)
            await asyncio.sleep(1)   # 1 daqiqa oralig'i (flood oldini olish)
        except Exception as e:
            log.error(f"user_stats chunk {i}: {e}")

    _index["user_stats_chunks"] = chunks
    if saved:
        await _save_index()
        log.info(f"✅ User stats: {saved} chunk yozildi")


async def _load_user_stats(uid_str):
    """Bitta user stats ni lazy load qilish"""
    from utils import ram_cache as ram
    # Allaqachon RAMda bormi?
    if ram.get_user_stats_cache(uid_str) is not None:
        return
    # Qaysi chunkda?
    for chunk in _index.get("user_stats_chunks", []):
        if uid_str not in chunk.get("uids", []):
            continue
        mid = chunk.get("msg_id")
        if not mid: return
        data = await _download_doc(mid)
        if not data: return
        all_stats = data.get("stats", {})
        # Butun chunkni RAMga yuklash
        for uid, s in all_stats.items():
            if ram.get_user_stats_cache(uid) is None:
                ram.set_user_stats_cache(uid, s, dirty=False)
        return


# ══ LEADERBOARD ════════════════════════════════════════════════

async def _load_leaderboard():
    """Startup da global leaderboard yuklanadi"""
    from utils import ram_cache as ram
    mid = _index.get("leaderboard_msg_id")
    if not mid: return
    data = await _download_doc(mid)
    if data:
        ram.set_global_leaderboard(data.get("top20", []))
        log.info(f"✅ Global leaderboard: {len(data.get('top20',[]))} ta")


async def save_leaderboard():
    """Global top 20 ni TG ga saqlash"""
    from utils import ram_cache as ram
    top20 = ram.update_global_leaderboard()
    if not top20: return
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    old_mid = _index.get("leaderboard_msg_id")
    if old_mid:
        try: await _bot.delete_message(_cid, old_mid)
        except: pass
    try:
        msg = await _bot.send_document(_cid,
            document=_buf({"top20": top20, "saved_at": ts}, "leaderboard.json"),
            caption=f"🏆 LEADERBOARD | top {len(top20)} | {ts}",
            protect_content=False)
        _index["leaderboard_msg_id"] = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id
        await _save_index()
        log.info(f"✅ Leaderboard saqlandi: {len(top20)} ta")
    except Exception as e:
        log.error(f"save_leaderboard: {e}")


async def save_group_leaderboard():
    """Guruh top 20 ni TG ga saqlash (kunlik)"""
    from utils import ram_cache as ram
    if not ram.is_group_lb_dirty(): return
    lb   = ram.get_group_leaderboard()
    if not lb: return
    today = str(date.today())
    ts    = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")

    # Eski kunning faylini o'chirish
    old_mid = _index.get("group_lb_msg_id")
    old_date = _index.get("group_lb_date", "")
    if old_mid and old_date != today:
        try: await _bot.delete_message(_cid, old_mid)
        except: pass
        old_mid = None

    if old_mid:
        try: await _bot.delete_message(_cid, old_mid)
        except: pass
    try:
        msg = await _bot.send_document(_cid,
            document=_buf({"top20": lb, "date": today, "saved_at": ts},
                          f"group_lb_{today}.json"),
            caption=f"🏆 GROUP_LB | {today} | top {len(lb)} | {ts}",
            protect_content=False)
        _index["group_lb_msg_id"]  = msg.message_id
        _index["group_lb_date"]    = today
        _index[f"fid_{msg.message_id}"] = msg.document.file_id
        await _save_index()
        ram.clear_group_lb_dirty()
        log.info(f"✅ Guruh leaderboard: {len(lb)} ta")
    except Exception as e:
        log.error(f"save_group_leaderboard: {e}")


async def load_group_leaderboard():
    """Bugungi guruh leaderboard ni yuklab RAM ga"""
    from utils import ram_cache as ram
    today   = str(date.today())
    lb_date = _index.get("group_lb_date", "")
    if lb_date != today:
        ram.clear_group_leaderboard()
        return
    mid = _index.get("group_lb_msg_id")
    if not mid: return
    data = await _download_doc(mid)
    if data:
        from utils.ram_cache import _set
        _set("group_leaderboard", data.get("top20", []))


# ══ TESTS STATS ════════════════════════════════════════════════

async def _load_tests_stats():
    global _stats_dirty
    mid = _index.get("tests_stats_msg_id")
    if not mid: return
    fid  = _index.get(f"fid_{mid}")
    data = await _read_file(fid) if fid else {}
    if not data:
        _index.pop(f"fid_{mid}", None)
        data = await _download_doc(mid)
    if not data:
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
    log.info(f"✅ tests_stats: {len(data.get('stats',{}))} test")


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
        log.info(f"✅ tests_stats: {len(stats)} test")
        return True
    except Exception as e:
        log.error(f"save_tests_stats: {e}")
        return False


# ══ AUTO FLUSH LOOP ════════════════════════════════════════════

async def auto_flush_loop():
    """
    Har 2 daqiqada: tests_stats
    Har 1 soatda:   user_stats (faqat o'zgarganlar), leaderboard, guruh lb
    """
    await asyncio.sleep(30)
    last_hourly = datetime.now(UTC)
    while True:
        try:
            await asyncio.sleep(120)   # 2 daqiqa
            now = datetime.now(UTC)

            if _stats_dirty:
                log.info("⚡ auto_flush: tests_stats...")
                await save_tests_stats()

            if _users_dirty:
                log.info("⚡ auto_flush: users_list...")
                await _flush_users_list()

            # Har 1 soatda
            if (now - last_hourly).total_seconds() >= 3600:
                last_hourly = now
                log.info("⏰ Soatlik flush boshlandi...")
                await flush_dirty_user_stats()
                await save_leaderboard()
                await save_group_leaderboard()
                log.info("✅ Soatlik flush tugadi")

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"auto_flush: {e}")


# ══ OTP ════════════════════════════════════════════════════════

_otp_store: dict = {}

def generate_otp(test_id: str, uid: int = 0) -> str:
    import random, string, time
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    _otp_store[code] = {"test_id": test_id, "uid": uid,
                        "expires_at": time.time() + 600, "used": False}
    now = time.time()
    for k in list(_otp_store):
        if _otp_store[k]["expires_at"] < now: del _otp_store[k]
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
            if not (new_index and "tests_meta" in new_index): continue
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
            log.error(f"web_sync_loop: {e}")
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

    # Faqat joriy fayllarning fid_ larini saqlash — eskilarini o'chirish
    _cleanup_old_fids()

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


def _cleanup_old_fids():
    """Faqat joriy aktiv fayllarning fid_ larini saqlaydi, eskilarini o'chiradi."""
    # Joriy aktiv msg_id lar
    active_mids = set()
    for key, val in _index.items():
        if key.startswith("fid_"): continue
        if isinstance(val, int):
            active_mids.add(str(val))
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    mid = item.get("msg_id")
                    if mid: active_mids.add(str(mid))
                    # user_msg_ kalitlar
                    for k2, v2 in item.items():
                        if k2.startswith("user_msg_") and isinstance(v2, int):
                            active_mids.add(str(v2))
    # Eski fid_ larni o'chirish
    to_del = [k for k in list(_index) if k.startswith("fid_")
              and k[4:] not in active_mids]
    for k in to_del:
        del _index[k]
    if to_del:
        log.debug(f"Index cleanup: {len(to_del)} eski fid_ o'chirildi")


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

    # 1. fid_ (cache) orqali tez yuklab olishga urinish
    if msg_id and _index.get(f"fid_{msg_id}"):
        data = await _read_file(_index[f"fid_{msg_id}"])
        if data and data.get("questions"):
            _tests_cache[tid] = data
            ram.cache_questions(tid, data)
            log.info(f"✅ {tid} yuklandi ({len(data['questions'])} savol)")
            return data
        # fid eskirgan — o'chirib, msg_id orqali qayta urinish
        log.info(f"♻️ {tid} fid eskirgan, msg_id orqali qayta yuklanmoqda")
        _index.pop(f"fid_{msg_id}", None)

    # 2. msg_id yo'q bo'lsa — index ni qayta yuklab topishga urinish
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
            log.info(f"ℹ️ {tid} msg_id yo'q")
            return {}

    # 3. msg_id bor — to'g'ridan Telegram'dan yuklab olish
    log.info(f"⬇️ Lazy load: {tid} (msg_id={msg_id})")
    data = await _download_doc(msg_id)
    if data and data.get("questions"):
        _tests_cache[tid] = data
        ram.cache_questions(tid, data)
        # Yangi fid_ ni saqlab qo'yish
        if _index.get(f"fid_{msg_id}"):
            await _save_index()
        return data
    # Fayl topilmadi — is_active=False qilinmaydi, faqat log yoziladi
    # (xabar o'chirilgan bo'lishi mumkin, lekin test hali mavjud)
    log.warning(f"⚠️ {tid} yuklanmadi (msg_id={msg_id} o'chirilgan bo'lishi mumkin)")
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
    global _creators_dirty
    for m in _index.get("tests_meta", []):
        if m.get("test_id") == tid:
            m["is_active"] = False
            break
    _tests_cache.pop(tid, None)
    await _save_index()
    mark_stats_dirty()





async def get_users():
    from utils import ram_cache as ram
    return ram.get_users()

async def save_users(users):
    mark_users_dirty_tg()
    return True

async def save_users_full():
    await _flush_users_list()
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
    metas = _index.get("tests_meta", [])
    log.info(f"✅ Preload: {len(metas)} test meta (savollar lazy)")


# ══ MANUAL FLUSH ══════════════════════════════════════════════

async def manual_flush(daily_data, users, settings=None):
    results = []
    if not ready():
        return ["❌ TG kanal ulanmagan"]
    ok = await save_tests_stats()
    results.append(f"{'✅' if ok else '❌'} Tests stats")
    await _flush_users_list()
    results.append(f"✅ Users: {len(users)} ta")
    await flush_dirty_user_stats()
    results.append("✅ User stats")
    await save_leaderboard()
    results.append("✅ Leaderboard")
    if settings:
        ok = await save_settings(settings)
        results.append(f"{'✅' if ok else '❌'} Settings")
    if daily_data:
        from datetime import date as _date
        today = str(_date.today())
        mid   = await upload_backup(daily_data, f"{today}_manual")
        results.append(f"{'✅' if mid else '❌'} Backup: {len(daily_data)} user")
    return results

def get_index_info():
    return {
        "tests_count":       len(_index.get("tests_meta", [])),
        "cached_tests":      len(_tests_cache),
        "user_list_chunks":  len(_index.get("users_list_chunks", [])),
        "user_stats_chunks": len(_index.get("user_stats_chunks", [])),
        "backups":           len(_index.get("backups", {})),
        "can_pin":           _can_pin,
        "stats_dirty":       _stats_dirty,
        "users_dirty":       _users_dirty,
    }


# ══ YORDAMCHILAR ══════════════════════════════════════════════

async def _download_doc(msg_id):
    fid_key    = f"fid_{msg_id}"
    cached_fid = _index.get(fid_key)
    if cached_fid:
        data = await _read_file(cached_fid)
        if data: return data
        _index.pop(fid_key, None)

    # 1-urinish: copy + forward
    try:
        copied     = await _bot.copy_message(_cid, _cid, int(msg_id), protect_content=False)
        copied_mid = copied.message_id
        fwd2       = await _bot.forward_message(_cid, _cid, copied_mid)
        doc2       = getattr(fwd2, "document", None)
        try: await _bot.delete_message(_cid, copied_mid)
        except: pass
        try: await _bot.delete_message(_cid, fwd2.message_id)
        except: pass
        if doc2:
            _index[fid_key] = doc2.file_id
            data = await _read_file(doc2.file_id)
            if data: return data
    except Exception as e:
        log.debug(f"copy+forward {msg_id}: {e}")

    # 2-urinish: to'g'ridan forward
    try:
        fwd = await _bot.forward_message(_cid, _cid, int(msg_id))
        doc = getattr(fwd, "document", None)
        try: await _bot.delete_message(_cid, fwd.message_id)
        except: pass
        if doc:
            _index[fid_key] = doc.file_id
            data = await _read_file(doc.file_id)
            if data: return data
    except Exception as e:
        log.error(f"download_doc forward {msg_id}: {e}")

    # 3-urinish: get_messages (supergroup uchun)
    try:
        msgs = await _bot.get_messages(_cid, [int(msg_id)])
        if msgs:
            m   = msgs[0]
            doc = getattr(m, "document", None)
            if doc:
                _index[fid_key] = doc.file_id
                data = await _read_file(doc.file_id)
                if data: return data
    except Exception as e:
        log.debug(f"get_messages {msg_id}: {e}")

    log.error(f"❌ download_doc: {msg_id} hech qaysi usulda yuklanmadi")
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
