"""TG_DB — Telegram kanal storage
Qoidalar:
 - Yangi test yaratilganda → test_{tid}.json yuklanadi
 - Yangi user qo'shilganda → users.json yangilanadi
 - Natijalar TG ga YUKLANMAYDI — faqat midnight yoki admin flush
 - Kunlik backup → backup_YYYY-MM-DD.json (1 marta)
 - O'chirilayotgan test → DELETED_test_{tid}.json
"""
import json, logging, io, asyncio
from datetime import datetime, timezone

log      = logging.getLogger(__name__)
UTC      = timezone.utc
_bot     = None
_cid     = None
_index: dict = {}
_can_pin = True


async def init(bot, channel_id):
    global _bot, _cid, _index
    _bot, _cid = bot, int(channel_id)
    _index = await _load_index_from_pin()
    if _index:
        log.info(f"✅ TG_DB: {len(_index.get('tests_meta', []))} meta topildi")
        return
    _index = await _search_index_in_history()
    if _index:
        await _try_pin_current_index()
    else:
        _index = {"tests_meta": [], "backups": {}}
        log.info("ℹ️ Yangi baza boshlandi")

def ready():
    return _bot is not None and bool(_cid)


# ── Index ──────────────────────────────────────────────────────

async def _load_index_from_pin():
    if not ready(): return {}
    try:
        chat = await _bot.get_chat(_cid)
        pin  = getattr(chat, "pinned_message", None)
        if not pin: return {}
        doc  = getattr(pin, "document", None)
        if doc and "index" in (doc.file_name or "").lower():
            data = await _read_doc(doc.file_id)
            if isinstance(data, dict) and "tests_meta" in data:
                return data
    except Exception as e:
        log.warning(f"Pin yuklash: {e}")
    return {}

async def _search_index_in_history():
    if not ready(): return {}
    try:
        probe = await _bot.send_message(_cid, ".")
        cur   = probe.message_id
        await _bot.delete_message(_cid, cur)
        for mid in range(cur - 1, max(1, cur - 200), -1):
            try:
                fwd = await _bot.forward_message(_cid, _cid, mid)
                doc = getattr(fwd, "document", None)
                if doc and "index" in (doc.file_name or "").lower():
                    data = await _read_doc(doc.file_id)
                    try: await _bot.delete_message(_cid, fwd.message_id)
                    except: pass
                    if isinstance(data, dict) and "tests_meta" in data:
                        return data
                try: await _bot.delete_message(_cid, fwd.message_id)
                except: pass
                await asyncio.sleep(0.03)
            except: pass
    except Exception as e:
        log.warning(f"Tarix qidirish: {e}")
    return {}

async def _try_pin_current_index():
    if not ready() or not _index: return
    try:
        msg = await _bot.send_document(_cid,
            document=_buf(_index, "index.json"), caption="📋 INDEX")
        await _bot.pin_chat_message(_cid, msg.message_id, disable_notification=True)
        _index["_last_index_msg_id"] = msg.message_id
    except Exception as e:
        log.warning(f"Pin qilish: {e}")

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


# ── Test META ──────────────────────────────────────────────────

def get_tests_meta():
    return _index.get("tests_meta", [])

def get_test_meta(tid):
    return next((t for t in get_tests_meta()
                 if t.get("test_id") == tid and t.get("is_active", True)), {})


# ── Test TO'LIQ ────────────────────────────────────────────────

async def get_test_full(tid):
    msg_id = _index.get(f"test_{tid}")
    if not msg_id: return {}
    return await _fetch(msg_id)

async def save_test_full(test):
    """Yangi test yaratilganda chaqiriladi — TG ga to'liq JSON yuboradi"""
    if not ready(): return False
    tid = test.get("test_id", "")
    try:
        qc  = len(test.get("questions", []))
        msg = await _bot.send_document(_cid,
            document=_buf(test, f"test_{tid}.json"),
            caption=(f"📝 {test.get('title','?')} | "
                     f"{test.get('category','')} | {qc} savol | {tid}"))
        _index[f"test_{tid}"] = msg.message_id
        meta = {k: v for k, v in test.items() if k != "questions"}
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
    """O'chiriladigan test backup sifatida TG ga yuboriladi"""
    if not ready(): return
    tid = test.get("test_id", "NOID")
    try:
        await _bot.send_document(_cid,
            document=_buf(test, f"DELETED_test_{tid}.json"),
            caption=f"🗑 O'CHIRILGAN: {test.get('title','?')} | {tid}")
    except Exception as e:
        log.error(f"delete backup: {e}")

async def update_test_meta_tg(tid, updates):
    metas = _index.get("tests_meta", [])
    for i, m in enumerate(metas):
        if m.get("test_id") == tid:
            metas[i].update(updates)
            break
    _index["tests_meta"] = metas
    await _save_index()

async def delete_test_tg(tid):
    for m in _index.get("tests_meta", []):
        if m.get("test_id") == tid:
            m["is_active"] = False
            break
    await _save_index()

async def get_tests():
    meta = _index.get("tests_meta", [])
    if meta: return meta
    mid = _index.get("tests_msg_id")
    if not mid: return []
    data = await _fetch(mid)
    return data.get("tests", []) if isinstance(data, dict) else []


# ── Users (alohida JSON fayl) ──────────────────────────────────

async def get_users():
    mid = _index.get("users_msg_id")
    if not mid: return {}
    data = await _fetch(mid)
    return data.get("users", {}) if isinstance(data, dict) else {}

async def save_users(users):
    """
    Users JSON — yangi user kelganda DARHOL chaqiriladi.
    users.json har yangi user qo'shilganda yangilanadi.
    """
    if not ready(): return False
    try:
        ts  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        msg = await _bot.send_document(_cid,
            document=_buf({
                "users":    users,
                "count":    len(users),
                "saved_at": ts
            }, "users.json"),
            caption=f"👥 USERS | {len(users)} ta | {ts}")
        _index["users_msg_id"] = msg.message_id
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_users: {e}")
        return False


# ── Settings ───────────────────────────────────────────────────

async def save_settings(settings_dict):
    if not ready(): return False
    try:
        ts  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        msg = await _bot.send_document(_cid,
            document=_buf({
                "settings": settings_dict,
                "saved_at": ts
            }, "settings.json"),
            caption=f"⚙️ SETTINGS | {len(settings_dict)} user | {ts}")
        _index["settings_msg_id"] = msg.message_id
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_settings: {e}")
        return False

async def get_settings_tg():
    mid = _index.get("settings_msg_id")
    if not mid: return {}
    data = await _fetch(mid)
    return data.get("settings", {}) if isinstance(data, dict) else {}


# ── Backup (kuniga 1x: midnight) ────────────────────────────────

async def upload_backup(daily_data, date_str):
    """
    Kunlik natijalar backup — midnight da chaqiriladi.
    Har kun bir marta, bitta fayl.
    """
    if not ready(): return 0
    try:
        fname   = f"backup_{date_str}.json"
        r_count = sum(
            len(v.get("by_test", {}))
            for v in daily_data.values()
        )
        ts  = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        msg = await _bot.send_document(_cid,
            document=_buf({
                "date":     date_str,
                "saved_at": ts,
                "users":    len(daily_data),
                "results":  r_count,
                "data":     daily_data,
            }, fname),
            caption=(f"💾 BACKUP | {date_str} | "
                     f"{len(daily_data)} user | {r_count} test natija"))
        if "backups" not in _index:
            _index["backups"] = {}
        _index["backups"][date_str] = msg.message_id
        await _save_index()
        log.info(f"✅ Backup: {fname} msg={msg.message_id}")
        return msg.message_id
    except Exception as e:
        log.error(f"backup: {e}")
        return 0

async def get_backup(date_str):
    mid = _index.get("backups", {}).get(date_str)
    if not mid: return {}
    data = await _fetch(mid)
    return data.get("data", {}) if isinstance(data, dict) else {}

def get_backup_dates():
    return sorted(_index.get("backups", {}).keys(), reverse=True)

def get_index_info():
    return {
        "tests_count":  len(_index.get("tests_meta", [])),
        "users_msg_id": _index.get("users_msg_id"),
        "backups":      len(_index.get("backups", {})),
        "can_pin":      _can_pin,
    }

async def manual_flush(daily_data, users, settings=None):
    """Admin buyruq bilan to'liq flush"""
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


# ── Yordamchilar ───────────────────────────────────────────────

async def _fetch(msg_id):
    try:
        fwd = await _bot.forward_message(_cid, _cid, msg_id)
        doc = getattr(fwd, "document", None)
        if not doc:
            try: await _bot.delete_message(_cid, fwd.message_id)
            except: pass
            return {}
        data = await _read_doc(doc.file_id)
        try: await _bot.delete_message(_cid, fwd.message_id)
        except: pass
        return data
    except Exception as e:
        log.error(f"fetch {msg_id}: {e}")
        return {}

def _buf(data, name):
    from aiogram.types import BufferedInputFile
    raw = json.dumps(data, ensure_ascii=False, default=str, indent=2).encode()
    return BufferedInputFile(raw, filename=name)

async def _read_doc(file_id):
    try:
        f   = await _bot.get_file(file_id)
        buf = io.BytesIO()
        await _bot.download_file(f.file_path, destination=buf)
        buf.seek(0)
        return json.loads(buf.read().decode())
    except Exception as e:
        log.error(f"read_doc: {e}")
        return {}
