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
    _bot, _cid = bot, int(channel_id)
    _index = {}
    _tests_cache = {}
    _stats_dirty = False
    _users_dirty = False

    _index = await _load_index()
    if not _index:
        _index = {"tests_meta": [], "backups": {}}
        log.info("ℹ️ Yangi baza boshlandi")
        return

    log.info(f"✅ Index: {len(_index.get('tests_meta', []))} meta")

    # 1. tests_stats.json — solve_count, avg, is_paused, solvers
    await _load_tests_stats()

    # 2. users_full.json — user statistikalar + history
    await _load_users_full()

    # 3. Hot testlar — oxirgi backup dan
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
    data = await _download_doc(mid)
    if not data:
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
        # Solvers ham RAMga
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
                    "attempts":   entry["attempts"],
                    "best_score": entry["best_score"],
                    "avg_score":  entry["avg_score"],
                    "all_pcts":   entry["all_pcts"],
                    "first_pct":  entry["all_pcts"][0] if entry["all_pcts"] else 0,
                    "last_at":    entry.get("last_at", ""),
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
            caption=f"📊 TESTS_STATS | {len(stats)} test | {ts}")
        _index["tests_stats_msg_id"] = msg.message_id
        await _save_index()
        _stats_dirty = False
        log.info(f"✅ tests_stats saqlandi: {len(stats)} test")
        return True
    except Exception as e:
        log.error(f"save_tests_stats: {e}")
        return False


# ══ USERS FULL — doimiy saqlanadigan ══════════════════════════

async def _load_users_full():
    """users_full.json dan user statistikalar + history yuklash"""
    mid = _index.get("users_full_msg_id")
    if not mid:
        # Eski users.json bor bo'lsa
        mid = _index.get("users_msg_id")
        if not mid:
            log.info("ℹ️ users_full yo'q")
            return
    data = await _download_doc(mid)
    if not data:
        return
    from utils import ram_cache as ram
    # Users
    users = data.get("users", {})
    if users:
        ram.set_users(users)
    # Per-user history (results)
    history = data.get("history", {})
    if history:
        ram.load_history_to_ram(history)
    log.info(f"✅ users_full: {len(users)} user, {len(history)} history yuklandi")

async def save_users_full():
    """Users + barcha history ni TG ga saqlash"""
    global _users_dirty
    if not ready(): return False
    from utils import ram_cache as ram
    users   = ram.get_users()
    daily   = ram.get_daily()
    # History: har user uchun by_test (tahlilsiz, yengil)
    history = {}
    for uid_str, udata in daily.items():
        by_test = {}
        for tid, entry in udata.get("by_test", {}).items():
            by_test[tid] = {
                "attempts":   entry["attempts"],
                "best_score": entry["best_score"],
                "avg_score":  entry["avg_score"],
                "all_pcts":   entry["all_pcts"],
                "last_at":    entry.get("last_at", ""),
                "first_pct":  entry["all_pcts"][0] if entry["all_pcts"] else 0,
                # Oxirgi tahlil ham saqlanadi
                "last_analysis": entry.get("last_analysis", []),
                "last_result": entry.get("last_result", {}),
                "first_result": entry.get("first_result", {}),
            }
        if by_test:
            history[uid_str] = by_test
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    try:
        msg = await _bot.send_document(_cid,
            document=_buf({
                "users":   users,
                "history": history,
                "count":   len(users),
                "saved_at": ts,
            }, "users_full.json"),
            caption=f"👥 USERS_FULL | {len(users)} user | {ts}")
        _index["users_full_msg_id"] = msg.message_id
        await _save_index()
        _users_dirty = False
        log.info(f"✅ users_full saqlandi: {len(users)} user, {len(history)} history")
        return True
    except Exception as e:
        log.error(f"save_users_full: {e}")
        return False


# ══ AUTO-FLUSH (5 daqiqada dirty bo'lsa) ══════════════════════

async def auto_flush_loop():
    """Har 5 daqiqada dirty bo'lsa TG ga yuboradi"""
    while True:
        try:
            await asyncio.sleep(300)   # 5 daqiqa
            if _stats_dirty:
                await save_tests_stats()
            if _users_dirty:
                await save_users_full()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"auto_flush: {e}")


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
                    return data
    except Exception as e:
        log.warning(f"Pin o'qish: {e}")
    # Oxirgi 50 xabardan qidirish
    try:
        probe = await _bot.send_message(_cid, ".")
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
    try:
        ts  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        msg = await _bot.send_document(_cid,
            document=_buf(_index, "index.json"),
            caption=f"📋 INDEX | {ts}")
        _index["_last_index_msg_id"] = msg.message_id
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
            document=_buf(data, "index.json"), caption="📋 INDEX")
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
    from utils import ram_cache as ram
    if tid in _tests_cache:
        ram.touch_test_access(tid)
        return _tests_cache[tid]
    cached = ram.get_cached_questions(tid)
    if cached:
        _tests_cache[tid] = cached
        return cached
    msg_id = _index.get(f"test_{tid}")
    if not msg_id:
        return {}
    log.info(f"⬇️ Lazy load: {tid} (msg={msg_id})")
    data = await _download_doc(msg_id)
    if data and data.get("questions"):
        _tests_cache[tid] = data
        ram.cache_questions(tid, data)
        log.info(f"✅ {tid} RAMga yuklandi")
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
            caption=f"📝 {test.get('title','?')} | {test.get('category','')} | {qc} savol | {tid}")
        _index[f"test_{tid}"] = msg.message_id
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
            caption=f"🗑 O'CHIRILGAN: {test.get('title','?')} | {tid}")
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
            caption=f"⚙️ SETTINGS | {ts}")
        _index["settings_msg_id"] = msg.message_id
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
            caption=f"💾 BACKUP | {date_str} | {len(daily_data)} user | {r_count} natija")
        if "backups" not in _index:
            _index["backups"] = {}
        _index["backups"][date_str] = msg.message_id
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
    backups = _index.get("backups", {})
    clean_dates = [d for d in backups.keys() if "_manual" not in d]
    if not clean_dates:
        log.info("ℹ️ Backup yo'q — lazy load")
        return
    last_date = sorted(clean_dates, reverse=True)[0]
    msg_id    = backups[last_date]
    log.info(f"📥 Oxirgi backup: {last_date} (msg={msg_id})")
    backup_data = await _download_doc(msg_id)
    if not backup_data:
        return
    daily    = backup_data.get("data", {})
    hot_tids = set()
    for uid_data in daily.values():
        for tid in uid_data.get("by_test", {}).keys():
            hot_tids.add(tid)
    log.info(f"🔥 Hot testlar: {len(hot_tids)} ta — RAMga yuklanmoqda...")
    loaded = 0
    for tid in hot_tids:
        msg_id = _index.get(f"test_{tid}")
        if not msg_id: continue
        data = await _download_doc(msg_id)
        if data and data.get("questions"):
            _tests_cache[tid] = data
            from utils import ram_cache as ram
            ram.cache_questions(tid, data)
            loaded += 1
        await asyncio.sleep(0.08)
    log.info(f"✅ {loaded}/{len(hot_tids)} hot test RAMga yuklandi")


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
    try:
        fwd = await _bot.forward_message(_cid, _cid, msg_id)
        doc = getattr(fwd, "document", None)
        try: await _bot.delete_message(_cid, fwd.message_id)
        except: pass
        if not doc: return {}
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
