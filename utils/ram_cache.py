"""
RAM CACHE — META + 12h questions cache + settings

ARXITEKTURA:
  tests_meta   : [{id,title,cat}]  — doim RAM, savolsiz (yengil)
  qcache_XXXXX : 12 soat cache     — savollar bilan
  users_cache  : doim RAM
  settings     : {uid: "uz_1_1"}  — kodlangan sozlamalar
  daily_results: flush gacha
"""
import threading, logging, sys
from datetime import datetime, timezone, timedelta

log  = logging.getLogger(__name__)
UTC  = timezone.utc
_lck = threading.Lock()
_RAM: dict = {}
RAM_LIMIT             = 450 * 1024 * 1024
QUESTIONS_CACHE_HOURS = 12
DEFAULT_SETTINGS      = "uz_1_1"
LANGS  = ["uz", "ru", "en"]
THEMES = ["light", "dark"]
NOTIFS = ["off", "on"]


def _get(k, d=None):
    with _lck: return _RAM.get(k, d)

def _set(k, v):
    with _lck: _RAM[k] = v


# ══ SETTINGS (kodlangan) ══════════════════════════════

def encode_settings(lang, theme, notify):
    return f"{lang}_{theme}_{notify}"

def decode_settings(code):
    try:
        p = (code or DEFAULT_SETTINGS).split("_")
        lang   = p[0] if p[0] in LANGS else "uz"
        theme  = int(p[1]) if len(p) > 1 else 1
        notify = int(p[2]) if len(p) > 2 else 1
        return {
            "lang":   lang,
            "theme":  THEMES[min(theme, 1)],
            "notify": NOTIFS[min(notify, 1)],
        }
    except Exception:
        return {"lang": "uz", "theme": "dark", "notify": "on"}

def get_settings(uid):
    return decode_settings(_get("settings", {}).get(str(uid), DEFAULT_SETTINGS))

def set_settings(uid, lang=None, theme=None, notify=None):
    s   = _get("settings", {})
    cur = decode_settings(s.get(str(uid), DEFAULT_SETTINGS))
    l   = lang   if lang   is not None else cur["lang"]
    t   = theme  if theme  is not None else THEMES.index(cur["theme"])
    n   = notify if notify is not None else NOTIFS.index(cur["notify"])
    s[str(uid)] = encode_settings(l, t, n)
    _set("settings", s)

def get_all_settings():  return _get("settings", {})
def set_all_settings(d): _set("settings", d)


# ══ TEST META (yengil, doim RAM) ══════════════════════

def get_tests_meta(): return _get("tests_meta", [])

def set_tests_meta(m):
    _set("tests_meta", m)
    log.info(f"RAM: {len(m)} test meta")

def get_test_meta(tid):
    return next((t for t in get_tests_meta()
                 if t.get("test_id") == tid and t.get("is_active", True)), {})

def add_test_meta(meta):
    m = [x for x in get_tests_meta() if x.get("test_id") != meta.get("test_id")]
    m.insert(0, meta)
    set_tests_meta(m)

def update_test_meta(tid, updates):
    m = get_tests_meta()
    for i, t in enumerate(m):
        if t.get("test_id") == tid:
            m[i].update(updates); break
    set_tests_meta(m)

def delete_test_from_ram(tid):
    """Testni RAMdan to'liq o'chirish (meta + cache)"""
    # Meta dan o'chirish
    m = [t for t in get_tests_meta() if t.get("test_id") != tid]
    set_tests_meta(m)
    # Savollar keshidan o'chirish
    with _lck:
        _RAM.pop(f"qcache_{tid}", None)
    log.info(f"RAM: test_{tid} o'chirildi")

# Eski kod bilan moslik
def get_tests(): return get_tests_meta()

def get_test_by_id(tid):
    full = get_cached_questions(tid)
    if full is not None:
        return full
    return get_test_meta(tid)

def set_tests(tests):
    metas = []
    for t in tests:
        meta = {k: v for k, v in t.items() if k != "questions"}
        meta["question_count"] = len(t.get("questions", []))
        metas.append(meta)
        if t.get("questions"):
            cache_questions(t["test_id"], t)
    set_tests_meta(metas)

def add_test(test):
    meta = {k: v for k, v in test.items() if k != "questions"}
    meta["question_count"] = len(test.get("questions", []))
    add_test_meta(meta)
    if test.get("questions"):
        cache_questions(test["test_id"], test)

def update_test_in_ram(test):
    tid = test.get("test_id")
    update_test_meta(tid, {k: v for k, v in test.items() if k != "questions"})
    cached = get_cached_questions(tid)
    if cached:
        cached.update(test)
        cache_questions(tid, cached)

def refresh_tests():
    _set("tests_meta", [])
    with _lck:
        for k in [k for k in list(_RAM) if k.startswith("qcache_")]:
            del _RAM[k]
    log.info("RAM: cache tozalandi")


# ══ SAVOLLAR CACHE (12 soat) ══════════════════════════

def cache_questions(tid, test_full):
    exp = datetime.now(UTC) + timedelta(hours=QUESTIONS_CACHE_HOURS)
    _set(f"qcache_{tid}", {"test": test_full, "expires": exp})

def get_cached_questions(tid):
    """None qaytaradi agar topilmasa yoki muddati o'tgan bo'lsa"""
    e = _get(f"qcache_{tid}")
    if not e: return None
    if datetime.now(UTC) > e["expires"]:
        with _lck: _RAM.pop(f"qcache_{tid}", None)
        return None
    return e["test"]

def clear_expired_cache():
    now = datetime.now(UTC)
    with _lck:
        keys = [k for k in list(_RAM)
                if k.startswith("qcache_") and _RAM[k].get("expires", now) < now]
        for k in keys: del _RAM[k]


# ══ USERLAR ════════════════════════════════════════════

def get_users():         return _get("users_cache", {})
def set_users(u):        _set("users_cache", u)
def get_user(tid):       return get_users().get(str(tid))

def upsert_user(tid, data):
    u = get_users(); u[str(tid)] = data
    set_users(u); _set("users_dirty", True)

def is_users_dirty():    return _get("users_dirty", False)
def clear_users_dirty(): _set("users_dirty", False)


# ══ NATIJALAR ══════════════════════════════════════════

def get_daily(): return _get("daily_results", {})

def save_result(user_id, test_id, result):
    daily = _get("daily_results", {})
    uid   = str(user_id)
    rid   = f"{uid}_{test_id}"

    if uid not in daily:
        daily[uid] = {"by_test": {}, "history": []}

    bt = daily[uid]["by_test"]
    if test_id not in bt:
        bt[test_id] = {
            "attempts": 0, "best_score": 0.0,
            "avg_score": 0.0, "total_score": 0.0,
            "last_result": {}, "last_analysis": []
        }

    e   = bt[test_id]
    pct = result.get("percentage", 0)
    att = e["attempts"] + 1
    ts  = e.get("total_score", 0.0) + pct

    e.update({
        "attempts":      att,
        "total_score":   ts,
        "best_score":    max(e["best_score"], pct),
        "avg_score":     round(ts / att, 1),
        "last_result":   {**result, "result_id": rid, "test_id": test_id,
                          "user_id": user_id,
                          "completed_at": str(datetime.now(UTC))},
        "last_analysis": result.get("detailed_results", []),
    })

    h = [x for x in daily[uid].get("history", []) if x.get("test_id") != test_id]
    h.insert(0, {
        "test_id": test_id, "result_id": rid,
        "percentage": pct, "passed": result.get("passed", False),
        "attempts": att, "avg_score": e["avg_score"],
        "best_score": e["best_score"],
        "completed_at": str(datetime.now(UTC)),
    })
    daily[uid]["history"] = h[:100]
    _set("daily_results", daily)
    return rid

def save_analysis(user_id, result_id, detailed):
    daily = _get("daily_results", {})
    uid   = str(user_id)
    if uid not in daily: daily[uid] = {"by_test": {}, "history": []}
    parts = result_id.split("_", 1)
    if len(parts) == 2:
        tid = parts[1]
        bt  = daily[uid].setdefault("by_test", {})
        if tid in bt:
            bt[tid]["last_analysis"] = detailed
    _set("daily_results", daily)

def get_user_results(uid):
    return _get("daily_results", {}).get(str(uid), {}).get("history", [])

def get_analysis(uid, rid):
    parts = rid.split("_", 1)
    if len(parts) < 2: return []
    return (_get("daily_results", {})
            .get(str(uid), {})
            .get("by_test", {})
            .get(parts[1], {})
            .get("last_analysis", []))

def get_test_stats_for_user(uid, tid):
    return (_get("daily_results", {})
            .get(str(uid), {})
            .get("by_test", {})
            .get(tid, {}))

def get_last_result(uid, tid):
    return get_test_stats_for_user(uid, tid).get("last_result", {})

def clear_daily():
    _set("daily_results", {})
    log.info("Kunlik RAM tozalandi")


# ══ STATS ══════════════════════════════════════════════

def stats():
    metas = get_tests_meta()
    daily = get_daily()
    users = get_users()
    with _lck:
        cq = sum(1 for k in _RAM if k.startswith("qcache_"))
    total = (sys.getsizeof(str(metas))
             + sys.getsizeof(str(daily))
             + sys.getsizeof(str(users)))
    return {
        "tests":    len(metas),
        "users":    len(users),
        "daily_r":  sum(len(v.get("history", [])) for v in daily.values()),
        "cached_q": cq,
        "mb":       round(total / 1024 / 1024, 2),
        "pct":      round(total / RAM_LIMIT * 100, 1),
    }
