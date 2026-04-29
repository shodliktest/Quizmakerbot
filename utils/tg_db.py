"""
TG_DB — Chunked Index Arxitektura
===================================

MUAMMO (eski):
  index.json bitta fayl → ko'p test bo'lsa 20MB TG chekloviga uriladi
  Pin o'chsa → testlar yo'qoladi

YECHIM (yangi):
  index_meta.json  (pinned, DOIM KICHIK ~5KB)
    index_chunks:      [{n, msg_id, fid}]   ← index bo'laklari
    users_list_chunks: [{n, msg_id, fid}]
    user_stats_chunks: [{n, msg_id, fid}]
    settings_msg_id, leaderboard_msg_id, ...
    backups: {date: msg_id}

  index_chunk_N.json  (har biri max ~100 test)
    tests_meta: [...]        ← meta ma'lumotlar
    test_{tid}: msg_id       ← test fayl joylashuvi
    fid_{msg_id}: file_id    ← tezroq yuklash uchun

AFZALLIKLAR:
  index_meta.json doim kichik — hech qachon 20MB ga yetmaydi
  Pin o'chsa ham chunk msg_id lar index_meta da saqlanadi
  Har chunk alohida, bir xato butun bazani buzmaydi
  Cheksiz test qo'shish mumkin (har 100 ta yangi chunk)
"""

import json, logging, io, asyncio
from datetime import datetime, timezone, date

log      = logging.getLogger(__name__)
UTC      = timezone.utc
_bot     = None
_cid     = None
_can_pin = True

# index_meta — kichik pinned fayl (faqat chunk joylashuvi)
_meta: dict = {}

# Birlashtiriлган index — barcha chunklar yuklangach RAM da
_index: dict = {"tests_meta": []}

_tests_cache: dict = {}
_stats_dirty       = False
_users_dirty       = False

INDEX_CHUNK_SIZE = 100   # Har chunk necha test


# ══════════════════════════════════════════════════════════════
# INIT
# ══════════════════════════════════════════════════════════════

async def init(bot, channel_id):
    global _bot, _cid, _meta, _index, _tests_cache, _stats_dirty, _users_dirty
    _cid         = int(channel_id)
    _meta        = {}
    _index       = {"tests_meta": []}
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

    _meta = await _load_meta()
    if not _meta:
        log.info("Yangi baza yaratilmoqda...")
        _meta = {
            "index_chunks":      [],
            "users_list_chunks": [],
            "user_stats_chunks": [],
            "backups":           {},
        }
        await _save_meta()
        return

    log.info(f"Meta: {len(_meta.get('index_chunks',[]))} index chunk, "
             f"{len(_meta.get('users_list_chunks',[]))} user chunk")

    await _load_all_index_chunks()
    await _load_tests_stats()
    await _load_users_list()
    await _load_leaderboard()

    if _stats_dirty: await save_tests_stats()
    if _users_dirty: await _flush_users_list()

    log.info(f"Tayyor: {len(_index.get('tests_meta',[]))} test meta yuklandi")


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


# ══════════════════════════════════════════════════════════════
# INDEX META (pinned, kichik fayl ~5-20KB)
# ══════════════════════════════════════════════════════════════

async def _load_meta() -> dict:
    if not ready(): return {}

    # 1. Pin dan o'qi
    try:
        chat = await _bot.get_chat(_cid)
        pin  = getattr(chat, "pinned_message", None)
        if pin:
            doc = getattr(pin, "document", None)
            if doc and "index_meta" in (doc.file_name or "").lower():
                data = await _read_file(doc.file_id)
                if isinstance(data, dict) and "index_chunks" in data:
                    log.info("index_meta pindan yuklandi")
                    return data
    except Exception as e:
        log.warning(f"Pin o'qish: {e}")

    # 2. Oxirgi 100 xabarni skanerlash (meta kichik, tez topiladi)
    try:
        probe = await _bot.send_message(_cid, ".", protect_content=False)
        cur   = probe.message_id
        await _bot.delete_message(_cid, cur)
        for mid in range(cur - 1, max(1, cur - 100), -1):
            try:
                fwd = await _bot.forward_message(_cid, _cid, mid)
                doc = getattr(fwd, "document", None)
                try: await _bot.delete_message(_cid, fwd.message_id)
                except: pass
                if doc and "index_meta" in (doc.file_name or "").lower():
                    data = await _read_file(doc.file_id)
                    if isinstance(data, dict) and "index_chunks" in data:
                        log.info(f"index_meta topildi (msg {mid})")
                        await _pin_msg(mid)
                        return data
                await asyncio.sleep(0.05)
            except: pass
    except Exception as e:
        log.warning(f"Meta qidirish: {e}")
    return {}


async def _save_meta():
    global _can_pin
    if not ready(): return False
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    try:
        msg = await _bot.send_document(
            _cid,
            document=_buf(_meta, "index_meta.json"),
            caption=f"INDEX_META | {ts}",
            protect_content=False
        )
        _meta["_last_meta_msg_id"] = msg.message_id
        _meta["_last_meta_fid"]    = msg.document.file_id
        if _can_pin:
            try:
                await _bot.pin_chat_message(_cid, msg.message_id, disable_notification=True)
            except:
                _can_pin = False
        return True
    except Exception as e:
        log.error(f"_save_meta: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# INDEX CHUNKS
# ══════════════════════════════════════════════════════════════

async def _load_all_index_chunks():
    chunks    = _meta.get("index_chunks", [])
    all_metas = []
    for ch in chunks:
        fid  = ch.get("fid")
        mid  = ch.get("msg_id")
        data = {}
        if fid:
            data = await _read_file(fid)
        if not data and mid:
            data = await _download_doc(mid)
            if data and ch.get("fid") != data.get("_self_fid"):
                pass   # fid yangilanadi keyingi _save_index_chunks da
        if not data:
            log.warning(f"Index chunk {ch.get('n')} yuklanmadi")
            continue
        for m in data.get("tests_meta", []):
            if not any(x.get("test_id") == m.get("test_id") for x in all_metas):
                all_metas.append(m)
        for k, v in data.items():
            if k.startswith("test_") or k.startswith("fid_"):
                _index[k] = v
    _index["tests_meta"] = all_metas
    log.info(f"Index chunks yuklandi: {len(all_metas)} test meta")


async def _save_index_chunks():
    from utils import ram_cache as ram
    # RAM dan yangilangan meta ni _index ga o'tkaz
    for m in _index.get("tests_meta", []):
        tid = m.get("test_id")
        if not tid: continue
        rm = ram.get_test_meta(tid)
        if not rm: continue
        for key in ("solve_count", "avg_score", "is_paused", "is_active",
                    "poll_time", "allowed_users", "title", "max_attempts"):
            if key in rm:
                m[key] = rm[key]

    metas  = _index.get("tests_meta", [])
    groups = [metas[i:i+INDEX_CHUNK_SIZE]
              for i in range(0, max(len(metas), 1), INDEX_CHUNK_SIZE)]
    old_chunks = _meta.get("index_chunks", [])
    new_chunks = []
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")

    for i, group in enumerate(groups):
        chunk_data = {"n": i+1, "saved_at": ts, "tests_meta": group}
        for m in group:
            tid = m.get("test_id")
            if tid and _index.get(f"test_{tid}"):
                msg_id = _index[f"test_{tid}"]
                chunk_data[f"test_{tid}"] = msg_id
                fk = f"fid_{msg_id}"
                if _index.get(fk):
                    chunk_data[fk] = _index[fk]

        old_mid = old_chunks[i]["msg_id"] if i < len(old_chunks) else None
        if old_mid:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        try:
            msg = await _bot.send_document(
                _cid,
                document=_buf(chunk_data, f"index_chunk_{i+1}.json"),
                caption=f"INDEX_CHUNK_{i+1} | {len(group)} test | {ts}",
                protect_content=False
            )
            new_chunks.append({
                "n":      i + 1,
                "msg_id": msg.message_id,
                "fid":    msg.document.file_id,
                "count":  len(group),
            })
            await asyncio.sleep(0.3)
        except Exception as e:
            log.error(f"index chunk {i+1} xato: {e}")
            if i < len(old_chunks):
                new_chunks.append(old_chunks[i])

    _meta["index_chunks"] = new_chunks
    await _save_meta()
    log.info(f"Index chunks saqlandi: {len(new_chunks)} chunk, {len(metas)} test")


async def _save_index():
    await _save_index_chunks()


# ══════════════════════════════════════════════════════════════
# USERS LIST
# ══════════════════════════════════════════════════════════════

async def _load_users_list():
    global _users_dirty
    from utils import ram_cache as ram
    chunks = _meta.get("users_list_chunks", [])
    total  = 0
    for chunk in chunks:
        fid  = chunk.get("fid")
        mid  = chunk.get("msg_id")
        data = {}
        if fid:
            data = await _read_file(fid)
        if not data and mid:
            data = await _download_doc(mid)
        if not data:
            _users_dirty = True
            continue
        users = data.get("users", {})
        cur   = ram.get_users()
        cur.update(users)
        ram.set_users(cur)
        total += len(users)
    log.info(f"Users: {total} ta ({len(chunks)} chunk)")


async def _flush_users_list():
    global _users_dirty
    from utils import ram_cache as ram
    users = ram.get_users()
    if not users: return

    chunks     = _meta.get("users_list_chunks", [])
    all_uids   = list(users.keys())
    uid_groups = [all_uids[i:i+500] for i in range(0, len(all_uids), 500)]
    new_chunks = []
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")

    for i, group in enumerate(uid_groups):
        chunk_users = {uid: users[uid] for uid in group if uid in users}
        old_mid = chunks[i]["msg_id"] if i < len(chunks) else None
        if old_mid:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        try:
            msg = await _bot.send_document(
                _cid,
                document=_buf({"users": chunk_users, "count": len(chunk_users), "saved_at": ts},
                              f"users_list_{i+1}.json"),
                caption=f"USERS_LIST_{i+1} | {len(chunk_users)} user | {ts}",
                protect_content=False
            )
            new_chunks.append({"n": i+1, "msg_id": msg.message_id,
                                "fid": msg.document.file_id, "count": len(chunk_users)})
            await asyncio.sleep(0.5)
        except Exception as e:
            log.error(f"users_list chunk {i+1}: {e}")
            if i < len(chunks):
                new_chunks.append(chunks[i])

    _meta["users_list_chunks"] = new_chunks
    await _save_meta()
    _users_dirty = False
    log.info(f"Users list saqlandi: {len(users)} ta, {len(new_chunks)} chunk")


# ══════════════════════════════════════════════════════════════
# USER STATS
# ══════════════════════════════════════════════════════════════

async def flush_dirty_user_stats():
    from utils import ram_cache as ram
    dirty_stats = ram.get_dirty_user_stats()
    if not dirty_stats: return

    chunks          = _meta.get("user_stats_chunks", [])
    dirty_chunk_ids = set()
    for uid_str in dirty_stats:
        for i, chunk in enumerate(chunks):
            if uid_str in chunk.get("uids", []):
                dirty_chunk_ids.add(i)
                break
        else:
            if chunks and len(chunks[-1].get("uids", [])) < 50:
                chunks[-1]["uids"].append(uid_str)
                dirty_chunk_ids.add(len(chunks) - 1)
            else:
                chunks.append({"n": len(chunks)+1, "msg_id": None, "fid": None, "uids": [uid_str]})
                dirty_chunk_ids.add(len(chunks) - 1)

    ts    = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    saved = 0
    for i in dirty_chunk_ids:
        if i >= len(chunks): continue
        chunk       = chunks[i]
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
            msg = await _bot.send_document(
                _cid,
                document=_buf({"stats": chunk_stats, "saved_at": ts},
                              f"user_stats_{i+1}.json"),
                caption=f"USER_STATS_{i+1} | {len(chunk_stats)} user | {ts}",
                protect_content=False
            )
            chunk["msg_id"] = msg.message_id
            chunk["fid"]    = msg.document.file_id
            saved += 1
            for uid_str in chunk.get("uids", []):
                ram.clear_stats_dirty(uid_str)
            await asyncio.sleep(1)
        except Exception as e:
            log.error(f"user_stats chunk {i}: {e}")

    _meta["user_stats_chunks"] = chunks
    if saved:
        await _save_meta()
        log.info(f"User stats: {saved} chunk yozildi")


async def _load_user_stats(uid_str):
    from utils import ram_cache as ram
    if ram.get_user_stats_cache(uid_str) is not None:
        return
    for chunk in _meta.get("user_stats_chunks", []):
        if uid_str not in chunk.get("uids", []):
            continue
        fid  = chunk.get("fid")
        mid  = chunk.get("msg_id")
        data = {}
        if fid:
            data = await _read_file(fid)
        if not data and mid:
            data = await _download_doc(mid)
        if not data: return
        for uid, s in data.get("stats", {}).items():
            if ram.get_user_stats_cache(uid) is None:
                ram.set_user_stats_cache(uid, s, dirty=False)
        return


# ══════════════════════════════════════════════════════════════
# LEADERBOARD
# ══════════════════════════════════════════════════════════════

async def _load_leaderboard():
    from utils import ram_cache as ram
    fid = _meta.get("leaderboard_fid")
    mid = _meta.get("leaderboard_msg_id")
    if not mid: return
    data = {}
    if fid:
        data = await _read_file(fid)
    if not data and mid:
        data = await _download_doc(mid)
    if data:
        ram.set_global_leaderboard(data.get("top20", []))
        log.info(f"Leaderboard: {len(data.get('top20',[]))} ta")


async def save_leaderboard():
    from utils import ram_cache as ram
    top20 = ram.update_global_leaderboard()
    if not top20: return
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    old_mid = _meta.get("leaderboard_msg_id")
    if old_mid:
        try: await _bot.delete_message(_cid, old_mid)
        except: pass
    try:
        msg = await _bot.send_document(
            _cid,
            document=_buf({"top20": top20, "saved_at": ts}, "leaderboard.json"),
            caption=f"LEADERBOARD | top {len(top20)} | {ts}",
            protect_content=False
        )
        _meta["leaderboard_msg_id"] = msg.message_id
        _meta["leaderboard_fid"]    = msg.document.file_id
        await _save_meta()
        log.info(f"Leaderboard saqlandi: {len(top20)} ta")
    except Exception as e:
        log.error(f"save_leaderboard: {e}")


async def save_group_leaderboard():
    from utils import ram_cache as ram
    if not ram.is_group_lb_dirty(): return
    lb    = ram.get_group_leaderboard()
    if not lb: return
    today = str(date.today())
    ts    = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    old_mid  = _meta.get("group_lb_msg_id")
    old_date = _meta.get("group_lb_date", "")
    if old_mid and old_date != today:
        try: await _bot.delete_message(_cid, old_mid)
        except: pass
        old_mid = None
    if old_mid:
        try: await _bot.delete_message(_cid, old_mid)
        except: pass
    try:
        msg = await _bot.send_document(
            _cid,
            document=_buf({"top20": lb, "date": today, "saved_at": ts},
                          f"group_lb_{today}.json"),
            caption=f"GROUP_LB | {today} | top {len(lb)} | {ts}",
            protect_content=False
        )
        _meta["group_lb_msg_id"]  = msg.message_id
        _meta["group_lb_fid"]     = msg.document.file_id
        _meta["group_lb_date"]    = today
        await _save_meta()
        ram.clear_group_lb_dirty()
        log.info(f"Guruh leaderboard: {len(lb)} ta")
    except Exception as e:
        log.error(f"save_group_leaderboard: {e}")


async def load_group_leaderboard():
    from utils import ram_cache as ram
    today   = str(date.today())
    lb_date = _meta.get("group_lb_date", "")
    if lb_date != today:
        ram.clear_group_leaderboard()
        return
    fid = _meta.get("group_lb_fid")
    mid = _meta.get("group_lb_msg_id")
    data = {}
    if fid:
        data = await _read_file(fid)
    if not data and mid:
        data = await _download_doc(mid)
    if data:
        from utils.ram_cache import _set
        _set("group_leaderboard", data.get("top20", []))


# ══════════════════════════════════════════════════════════════
# TESTS STATS
# ══════════════════════════════════════════════════════════════

async def _load_tests_stats():
    global _stats_dirty
    fid = _meta.get("tests_stats_fid")
    mid = _meta.get("tests_stats_msg_id")
    if not mid: return
    data = {}
    if fid:
        data = await _read_file(fid)
    if not data and mid:
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
    log.info(f"tests_stats: {len(data.get('stats',{}))} test")


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
        old_mid = _meta.get("tests_stats_msg_id")
        if old_mid:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        msg = await _bot.send_document(
            _cid,
            document=_buf({"stats": stats, "saved_at": ts}, "tests_stats.json"),
            caption=f"TESTS_STATS | {len(stats)} test | {ts}",
            protect_content=False
        )
        _meta["tests_stats_msg_id"] = msg.message_id
        _meta["tests_stats_fid"]    = msg.document.file_id
        await _save_meta()
        _stats_dirty = False
        log.info(f"tests_stats: {len(stats)} test")
        return True
    except Exception as e:
        log.error(f"save_tests_stats: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# AUTO FLUSH LOOP
# ══════════════════════════════════════════════════════════════

async def auto_flush_loop():
    await asyncio.sleep(30)
    last_hourly = datetime.now(UTC)
    while True:
        try:
            await asyncio.sleep(120)
            now = datetime.now(UTC)
            if _stats_dirty:
                log.info("auto_flush: tests_stats...")
                await save_tests_stats()
            if _users_dirty:
                log.info("auto_flush: users_list...")
                await _flush_users_list()
            if (now - last_hourly).total_seconds() >= 3600:
                last_hourly = now
                log.info("Soatlik flush...")
                await flush_dirty_user_stats()
                await save_leaderboard()
                await save_group_leaderboard()
                log.info("Soatlik flush tugadi")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"auto_flush: {e}")


# ══════════════════════════════════════════════════════════════
# OTP
# ══════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════
# WEB SYNC
# ══════════════════════════════════════════════════════════════

async def web_sync_loop():
    await asyncio.sleep(30)
    consecutive_errors = 0
    while True:
        try:
            await asyncio.sleep(43200)
            if not ready(): continue
            from utils import ram_cache as ram
            try:
                new_meta = await asyncio.wait_for(_load_meta(), timeout=20)
            except asyncio.TimeoutError:
                consecutive_errors += 1
                continue
            if not new_meta: continue
            consecutive_errors = 0

            new_metas = []
            new_test_ids = {}
            for ch in new_meta.get("index_chunks", []):
                fid  = ch.get("fid")
                mid  = ch.get("msg_id")
                data = {}
                if fid:
                    data = await _read_file(fid)
                if not data and mid:
                    data = await _download_doc(mid)
                for m in data.get("tests_meta", []):
                    if not any(x.get("test_id") == m.get("test_id") for x in new_metas):
                        new_metas.append(m)
                for k, v in data.items():
                    if k.startswith("test_"):
                        new_test_ids[k] = v

            ram_ids = {t.get("test_id") for t in ram.get_all_tests_meta()}
            added   = 0
            for meta in new_metas:
                tid = meta.get("test_id")
                if not tid or tid in ram_ids: continue
                clean = {k: v for k, v in meta.items() if k != "questions"}
                ram.add_test_meta(clean)
                if not any(m.get("test_id") == tid for m in _index.get("tests_meta", [])):
                    _index.setdefault("tests_meta", []).insert(0, clean)
                if new_test_ids.get(f"test_{tid}"):
                    _index[f"test_{tid}"] = new_test_ids[f"test_{tid}"]
                added += 1
            if added:
                log.info(f"Web sync: {added} yangi test")
                mark_stats_dirty()
        except asyncio.CancelledError:
            break
        except Exception as e:
            consecutive_errors += 1
            log.error(f"web_sync_loop: {e}")
            if consecutive_errors >= 5:
                await asyncio.sleep(900)
                consecutive_errors = 0


# ══════════════════════════════════════════════════════════════
# TESTLAR
# ══════════════════════════════════════════════════════════════

def get_tests_meta():
    return _index.get("tests_meta", [])

def get_test_meta(tid):
    return next((t for t in get_tests_meta()
                 if t.get("test_id") == tid and t.get("is_active", True)), {})

async def get_test_full(tid):
    from utils import ram_cache as ram

    # 1. RAM cache
    if tid in _tests_cache:
        ram.touch_test_access(tid)
        return _tests_cache[tid]
    cached = ram.get_cached_questions(tid)
    if cached:
        _tests_cache[tid] = cached
        return cached

    # 2. fid orqali to'g'ridan o'qi (tezkor)
    msg_id  = _index.get(f"test_{tid}")
    fid_key = f"fid_{msg_id}" if msg_id else None
    if msg_id and fid_key and _index.get(fid_key):
        data = await _read_file(_index[fid_key])
        if data and data.get("questions"):
            _tests_cache[tid] = data
            ram.cache_questions(tid, data)
            return data
        _index.pop(fid_key, None)

    # 3. msg_id orqali yukla
    if msg_id:
        data = await _download_doc(msg_id)
        if data and data.get("questions"):
            _tests_cache[tid] = data
            ram.cache_questions(tid, data)
            return data

    # 4. Barcha chunklarni skan qilish (so'nggi chora)
    log.info(f"{tid} — chunkdan qidirilmoqda...")
    for ch in _meta.get("index_chunks", []):
        fid  = ch.get("fid")
        mid  = ch.get("msg_id")
        cdata = {}
        if fid:
            cdata = await _read_file(fid)
        if not cdata and mid:
            cdata = await _download_doc(mid)
        new_mid = cdata.get(f"test_{tid}")
        if new_mid:
            _index[f"test_{tid}"] = new_mid
            data = await _download_doc(new_mid)
            if data and data.get("questions"):
                _tests_cache[tid] = data
                ram.cache_questions(tid, data)
                log.info(f"{tid} chunk skanidan topildi")
                return data

    log.warning(f"{tid} topilmadi")
    return {}

async def get_tests():
    return _index.get("tests_meta", [])

async def save_test_full(test):
    if not ready(): return False
    tid = test.get("test_id", "")
    try:
        qc  = len(test.get("questions", []))
        msg = await _bot.send_document(
            _cid,
            document=_buf(test, f"test_{tid}.json"),
            caption=f"TEST | {test.get('title','?')} | {qc} savol | {tid}",
            protect_content=False
        )
        _index[f"test_{tid}"]           = msg.message_id
        _index[f"fid_{msg.message_id}"] = msg.document.file_id
        _tests_cache[tid] = test

        meta = {k: v for k, v in test.items() if k != "questions"}
        meta["question_count"] = qc
        metas = [m for m in _index.get("tests_meta", []) if m.get("test_id") != tid]
        metas.insert(0, meta)
        _index["tests_meta"] = metas

        from utils import ram_cache as ram
        ram.add_test_meta(meta)
        ram.cache_questions(tid, test)

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
        await _bot.send_document(
            _cid,
            document=_buf(test, f"DELETED_test_{tid}.json"),
            caption=f"DELETED: {test.get('title','?')} | {tid}",
            protect_content=False
        )
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

async def update_test_meta_tg(tid: str, updates: dict):
    from utils import ram_cache as ram
    for m in _index.get("tests_meta", []):
        if m.get("test_id") == tid:
            m.update(updates)
            break
    ram.update_test_meta(tid, updates)
    if tid in _tests_cache:
        _tests_cache[tid].update(updates)
        ram.cache_questions(tid, _tests_cache[tid])
    else:
        cached = ram.get_cached_questions(tid)
        if cached:
            cached.update(updates)
            ram.cache_questions(tid, cached)
            _tests_cache[tid] = cached
    await _save_index()
    mark_stats_dirty()
    log.info(f"update_test_meta_tg: {tid} → {list(updates.keys())}")


# ══════════════════════════════════════════════════════════════
# USERS
# ══════════════════════════════════════════════════════════════

async def get_users():
    from utils import ram_cache as ram
    return ram.get_users()

async def save_users(users):
    mark_users_dirty_tg()
    return True

async def save_users_full():
    await _flush_users_list()
    return True


# ══════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════

async def save_settings(settings_dict):
    if not ready(): return False
    try:
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        old_mid = _meta.get("settings_msg_id")
        if old_mid:
            try: await _bot.delete_message(_cid, old_mid)
            except: pass
        msg = await _bot.send_document(
            _cid,
            document=_buf({"settings": settings_dict, "saved_at": ts}, "settings.json"),
            caption=f"SETTINGS | {ts}",
            protect_content=False
        )
        _meta["settings_msg_id"] = msg.message_id
        _meta["settings_fid"]    = msg.document.file_id
        await _save_meta()
        return True
    except Exception as e:
        log.error(f"save_settings: {e}")
        return False

async def get_settings_tg():
    fid = _meta.get("settings_fid")
    mid = _meta.get("settings_msg_id")
    if not mid: return {}
    data = {}
    if fid:
        data = await _read_file(fid)
    if not data and mid:
        data = await _download_doc(mid)
    return data.get("settings", {}) if isinstance(data, dict) else {}


# ══════════════════════════════════════════════════════════════
# BACKUP
# ══════════════════════════════════════════════════════════════

async def upload_backup(daily_data, date_str):
    if not ready(): return 0
    try:
        r_count = sum(len(v.get("by_test", {})) for v in daily_data.values())
        ts      = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        msg     = await _bot.send_document(
            _cid,
            document=_buf({
                "date": date_str, "saved_at": ts,
                "users": len(daily_data), "results": r_count,
                "data":  daily_data,
            }, f"backup_{date_str}.json"),
            caption=f"BACKUP | {date_str} | {len(daily_data)} user | {r_count} natija",
            protect_content=False
        )
        _meta.setdefault("backups", {})[date_str] = msg.message_id
        await _save_meta()
        log.info(f"Backup: {date_str}")
        return msg.message_id
    except Exception as e:
        log.error(f"backup: {e}")
        return 0

async def get_backup(date_str):
    mid = _meta.get("backups", {}).get(date_str)
    if not mid: return {}
    data = await _download_doc(mid)
    return data.get("data", {}) if isinstance(data, dict) else {}

def get_backup_dates():
    return sorted(_meta.get("backups", {}).keys(), reverse=True)


# ══════════════════════════════════════════════════════════════
# MANUAL FLUSH
# ══════════════════════════════════════════════════════════════

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
        "index_chunks":      len(_meta.get("index_chunks", [])),
        "user_list_chunks":  len(_meta.get("users_list_chunks", [])),
        "user_stats_chunks": len(_meta.get("user_stats_chunks", [])),
        "backups":           len(_meta.get("backups", {})),
        "can_pin":           _can_pin,
        "stats_dirty":       _stats_dirty,
        "users_dirty":       _users_dirty,
    }


# ══════════════════════════════════════════════════════════════
# YORDAMCHILAR
# ══════════════════════════════════════════════════════════════

async def _pin_msg(msg_id: int):
    global _can_pin
    if not _can_pin: return
    try:
        await _bot.pin_chat_message(_cid, msg_id, disable_notification=True)
    except:
        _can_pin = False


async def _download_doc(msg_id):
    try:
        fwd = await _bot.forward_message(_cid, _cid, int(msg_id))
        doc = getattr(fwd, "document", None)
        try: await _bot.delete_message(_cid, fwd.message_id)
        except: pass
        if doc:
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
    raw = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":")).encode()
    return BufferedInputFile(raw, filename=name)
