"""
TG_DB — Telegram kanal storage
=================================
ARXITEKTURA:
  - Bot ishga tushganda:  barcha testlar + users RAM ga yuklanadi (1 marta)
  - Test so'ralganda:     RAM dan o'qiladi (0 API call)
  - Yangi test:           TG ga yoziladi + index yangilanadi
  - Midnight:             backup + users yuklanadi

API CALL HISOBI:
  Bot start:   get_chat(1) + tests o'qish(N*3) + users(3) + settings(3)
  Test o'qish: 0 call (RAM dan)
  Yangi test:  send_document(1) + save_index(1) = 2 call
  Midnight:    send_document(3) + save_index(1) = 4 call
"""
import json, logging, io, asyncio
from datetime import datetime, timezone

log      = logging.getLogger(__name__)
UTC      = timezone.utc
_bot     = None
_cid     = None
_index:  dict = {}
_can_pin = True

# RAM cache — barcha testlar to'liq saqlangan
_tests_cache: dict = {}   # {tid: test_dict}


async def init(bot, channel_id):
    """
    Bot start arxitekturasi:
      1. Index yuklash (pinned)
      2. Oxirgi backup faylidan — faqat shu kunda yechilgan testlar RAMga
      3. Qolgan testlar — birinchi so'rovda lazy load
    """
    global _bot, _cid, _index, _tests_cache
    _bot, _cid = bot, int(channel_id)
    _index = {}
    _tests_cache = {}

    # 1. Index yuklash
    _index = await _load_index()
    if not _index:
        _index = {"tests_meta": [], "backups": {}}
        log.info("ℹ️ Yangi baza boshlandi")
        return

    log.info(f"✅ Index: {len(_index.get('tests_meta', []))} meta")

    # 2. Oxirgi backup dan — kechagi aktiv testlarni RAMga yukla
    await _preload_from_last_backup()


def ready():
    return _bot is not None and bool(_cid)

def get_cached_test(tid):
    """RAM dan to'liq test — 0 API call"""
    return _tests_cache.get(tid, {})

def cache_test(tid, test):
    """RAMga qo'shish"""
    _tests_cache[tid] = test


# ══ INDEX ══════════════════════════════════════════════════════

async def _preload_from_last_backup():
    """
    Oxirgi backup faylidan test ID larni olib, ularni RAMga yuklaydi.
    Backup struktura: {"data": {uid: {"by_test": {tid: {...}}}}}
    Faqat kechagi kunda yechilgan testlar — bot start da minimal yuklanadi.
    """
    backups = _index.get("backups", {})
    if not backups:
        log.info("ℹ️ Backup yo'q — testlar lazy load bo'ladi")
        return

    # Oxirgi backup
    last_date = sorted(backups.keys(), reverse=True)[0]
    # _manual backup bo'lsa skip
    clean_dates = [d for d in backups.keys() if "_manual" not in d]
    if not clean_dates:
        log.info("ℹ️ Faqat manual backup bor — lazy load")
        return

    last_date  = sorted(clean_dates, reverse=True)[0]
    msg_id     = backups[last_date]
    log.info(f"📥 Oxirgi backup: {last_date} (msg={msg_id})")

    backup_data = await _download_doc(msg_id)
    if not backup_data:
        log.warning("⚠️ Backup yuklanmadi — lazy load")
        return

    daily = backup_data.get("data", {})
    # Kechagi kunda qaysi testlar yechilgan — TID larini yig'ish
    hot_tids = set()
    for uid_data in daily.values():
        for tid in uid_data.get("by_test", {}).keys():
            hot_tids.add(tid)

    log.info(f"🔥 Hot testlar: {len(hot_tids)} ta — RAMga yuklanmoqda...")
    loaded = 0
    for tid in hot_tids:
        msg_id = _index.get(f"test_{tid}")
        if not msg_id:
            continue
        data = await _download_doc(msg_id)
        if data and data.get("questions"):
            _tests_cache[tid] = data
            # ram_cache ga ham qo'shamiz
            from utils import ram_cache as ram
            ram.cache_questions(tid, data)
            loaded += 1
        await asyncio.sleep(0.08)

    log.info(f"✅ {loaded}/{len(hot_tids)} hot test RAM ga yuklandi. "
             f"Qolgan {len(_index.get('tests_meta', [])) - loaded} ta — lazy load.")


async def _load_index():
    """Pinned xabardan yoki oxirgi index.json dan yuklash"""
    if not ready():
        return {}
    # 1. Pinned xabar
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

    # 2. Oxirgi xabarlarda qidirish (faqat 50 ta)
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
    """
    Lazy load arxitekturasi:
      - RAM da bor → 0 API call, last_access yangilanadi
      - RAM da yo'q → TGdan yuklab RAMga saqlaydi (o'chmaydi)
      - 2 kun yechilmasa → clear_expired_cache() o'chiradi (TGda qoladi)
    """
    # 1. tg_db ichki cache
    if tid in _tests_cache:
        from utils import ram_cache as ram
        ram.touch_test_access(tid)
        return _tests_cache[tid]

    # 2. ram_cache da bor (qcache_*)
    from utils import ram_cache as ram
    cached = ram.get_cached_questions(tid)
    if cached:
        _tests_cache[tid] = cached
        return cached

    # 3. TGdan lazy load
    msg_id = _index.get(f"test_{tid}")
    if not msg_id:
        return {}

    log.info(f"⬇️ Lazy load: {tid} (msg={msg_id})")
    data = await _download_doc(msg_id)
    if data and data.get("questions"):
        _tests_cache[tid] = data
        ram.cache_questions(tid, data)   # RAMda, o'chmas (last_access bilan)
        log.info(f"✅ {tid} RAMga yuklandi")
    return data

async def get_tests():
    """Bot start uchun — barcha test meta (index dan)"""
    return _index.get("tests_meta", [])

async def save_test_full(test):
    """Yangi test yaratilganda — TG + index"""
    if not ready(): return False
    tid = test.get("test_id", "")
    try:
        qc  = len(test.get("questions", []))
        msg = await _bot.send_document(_cid,
            document=_buf(test, f"test_{tid}.json"),
            caption=f"📝 {test.get('title','?')} | {test.get('category','')} | {qc} savol | {tid}")
        _index[f"test_{tid}"] = msg.message_id
        # RAM ga ham saqla
        _tests_cache[tid] = test
        # Meta ro'yxat yangilash
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

async def update_test_meta_tg(tid, updates):
    for m in _index.get("tests_meta", []):
        if m.get("test_id") == tid:
            m.update(updates)
            break
    await _save_index()


# ══ USERS ══════════════════════════════════════════════════════

async def get_users():
    mid = _index.get("users_msg_id")
    if not mid: return {}
    data = await _download_doc(mid)
    return data.get("users", {}) if isinstance(data, dict) else {}

async def save_users(users):
    if not ready(): return False
    try:
        ts  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        msg = await _bot.send_document(_cid,
            document=_buf({"users": users, "count": len(users), "saved_at": ts}, "users.json"),
            caption=f"👥 USERS | {len(users)} ta | {ts}")
        _index["users_msg_id"] = msg.message_id
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_users: {e}")
        return False


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


# ══ ADMIN FLUSH ════════════════════════════════════════════════

async def manual_flush(daily_data, users, settings=None):
    results = []
    if not ready():
        return ["❌ TG kanal ulanmagan"]
    if users:
        ok = await save_users(users)
        results.append(f"{'✅' if ok else '❌'} Users: {len(users)} ta")
    if settings:
        ok = await save_settings(settings)
        results.append(f"{'✅' if ok else '❌'} Settings: {len(settings)} ta")
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
        "users_msg_id": _index.get("users_msg_id"),
        "backups":      len(_index.get("backups", {})),
        "can_pin":      _can_pin,
    }


# ══ YORDAMCHILAR ═══════════════════════════════════════════════

async def _download_doc(msg_id):
    """
    Xabardan document yuklab o'qish.
    forward emas — to'g'ridan getMessages ishlatadi (1 API call kam).
    """
    try:
        # forward_message ishlatmasdan file_id ni olish imkoni yo'q
        # Lekin bot kanalda admin bo'lsa copyMessage ishlatish mumkin
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
