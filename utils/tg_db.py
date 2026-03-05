"""TG_DB — har test alohida fayl + BufferedInputFile + kuniga 2x backup"""
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
        log.info(f"✅ TG_DB: {len(_index.get('tests_meta',[]))} meta topildi")
        return
    _index = await _search_index_in_history()
    if _index:
        await _try_pin_current_index()
    else:
        _index = {"tests_meta": [], "backups": {}}
        log.info("ℹ️ Yangi baza")

def ready():
    return _bot is not None and bool(_cid)

# ── Index ──────────────────────────────────────────────
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
        log.warning(f"Pin: {e}")
    return {}

async def _search_index_in_history():
    if not ready(): return {}
    try:
        probe = await _bot.send_message(_cid, ".")
        cur   = probe.message_id
        await _bot.delete_message(_cid, cur)
        for mid in range(cur - 1, max(1, cur - 100), -1):
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
                await asyncio.sleep(0.05)
            except: pass
    except Exception as e:
        log.warning(f"History: {e}")
    return {}

async def _try_pin_current_index():
    if not ready() or not _index: return
    try:
        msg = await _bot.send_document(_cid,
            document=_buf(_index, "index.json"), caption="📋 INDEX")
        await _bot.pin_chat_message(_cid, msg.message_id, disable_notification=True)
        _index["_last_index_msg_id"] = msg.message_id
    except Exception as e:
        log.warning(f"Pin: {e}")

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
        log.error(f"Index: {e}"); return False

# ── Test META ──────────────────────────────────────────
def get_tests_meta(): return _index.get("tests_meta", [])

def get_test_meta(tid):
    return next((t for t in get_tests_meta()
                 if t.get("test_id") == tid and t.get("is_active", True)), {})

# ── Test TO'LIQ (alohida fayl) ─────────────────────────
async def get_test_full(tid):
    msg_id = _index.get(f"test_{tid}")
    if not msg_id: return {}
    return await _fetch(msg_id)

async def save_test_full(test):
    if not ready(): return False
    tid = test.get("test_id", "")
    try:
        qc  = len(test.get("questions", []))
        msg = await _bot.send_document(_cid,
            document=_buf(test, f"test_{tid}.json"),
            caption=f"📝 {test.get('title','?')} | {test.get('category','')} | {qc} savol | {tid}")
        _index[f"test_{tid}"] = msg.message_id
        meta = {k: v for k, v in test.items() if k != "questions"}
        meta["question_count"] = qc
        metas = [m for m in _index.get("tests_meta", []) if m.get("test_id") != tid]
        metas.insert(0, meta)
        _index["tests_meta"] = metas
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_test_full: {e}"); return False

# Eski moslik
async def save_tests(tests):
    if not ready(): return False
    try:
        msg = await _bot.send_document(_cid,
            document=_buf({"tests": tests, "saved_at": str(datetime.now(UTC))}, "tests.json"),
            caption=f"📋 TESTLAR | {len(tests)} ta")
        _index["tests_msg_id"] = msg.message_id
        metas = []
        for t in tests:
            meta = {k: v for k, v in t.items() if k != "questions"}
            meta["question_count"] = len(t.get("questions", []))
            metas.append(meta)
        _index["tests_meta"] = metas
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_tests: {e}"); return False

async def get_tests():
    meta = _index.get("tests_meta", [])
    if meta: return meta
    mid = _index.get("tests_msg_id")
    if not mid: return []
    data = await _fetch(mid)
    return data.get("tests", []) if isinstance(data, dict) else []

async def update_test_meta_tg(tid, updates):
    metas = _index.get("tests_meta", [])
    for i, m in enumerate(metas):
        if m.get("test_id") == tid: metas[i].update(updates); break
    _index["tests_meta"] = metas
    await _save_index()

async def delete_test_tg(tid):
    for m in _index.get("tests_meta", []):
        if m.get("test_id") == tid: m["is_active"] = False; break
    await _save_index()

# ── Userlar ────────────────────────────────────────────
async def get_users():
    mid = _index.get("users_msg_id")
    if not mid: return {}
    data = await _fetch(mid)
    return data.get("users", {}) if isinstance(data, dict) else {}

async def save_users(users):
    if not ready(): return False
    try:
        msg = await _bot.send_document(_cid,
            document=_buf({"users": users, "saved_at": str(datetime.now(UTC))}, "users.json"),
            caption=f"👥 USERLAR | {len(users)} ta")
        _index["users_msg_id"] = msg.message_id
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_users: {e}"); return False

# ── Settings ───────────────────────────────────────────
async def save_settings(settings_dict):
    if not ready(): return False
    try:
        msg = await _bot.send_document(_cid,
            document=_buf({"settings": settings_dict,
                           "saved_at": str(datetime.now(UTC))}, "settings.json"),
            caption=f"⚙️ SETTINGS | {len(settings_dict)} user")
        _index["settings_msg_id"] = msg.message_id
        await _save_index()
        return True
    except Exception as e:
        log.error(f"save_settings: {e}"); return False

async def get_settings_tg():
    mid = _index.get("settings_msg_id")
    if not mid: return {}
    data = await _fetch(mid)
    return data.get("settings", {}) if isinstance(data, dict) else {}

# ── Backup (kuniga 2x: slot "00" va "12") ─────────────
async def upload_backup(daily_data, date_str, slot="00"):
    if not ready(): return 0
    try:
        fname   = f"backup_{date_str}_{slot}.json"
        r_count = sum(len(v.get("history", [])) for v in daily_data.values())
        msg = await _bot.send_document(_cid,
            document=_buf({
                "date": date_str, "slot": slot,
                "saved_at": str(datetime.now(UTC)),
                "users": len(daily_data), "results": r_count,
                "data": daily_data
            }, fname),
            caption=f"💾 BACKUP | {date_str} ({slot}:00) | {len(daily_data)} user | {r_count} natija")
        if "backups" not in _index: _index["backups"] = {}
        _index["backups"][f"{date_str}_{slot}"] = msg.message_id
        await _save_index()
        log.info(f"✅ Backup: {fname}")
        return msg.message_id
    except Exception as e:
        log.error(f"backup: {e}"); return 0

async def get_backup(date_str, slot="00"):
    mid = _index.get("backups", {}).get(f"{date_str}_{slot}")
    if not mid: return {}
    data = await _fetch(mid)
    return data.get("data", {}) if isinstance(data, dict) else {}

def get_backup_dates(): return sorted(_index.get("backups", {}).keys(), reverse=True)

def get_index_info():
    return {
        "tests_count":  len(_index.get("tests_meta", [])),
        "users_msg_id": _index.get("users_msg_id"),
        "backups":      len(_index.get("backups", {})),
        "can_pin":      _can_pin,
    }

# ── Yordamchilar ───────────────────────────────────────
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
        log.error(f"fetch {msg_id}: {e}"); return {}

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
        log.error(f"read_doc: {e}"); return {}
