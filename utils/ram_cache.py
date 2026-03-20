"""
RAM CACHE — Yangi arxitektura:

  tests_meta      : [{id,title,...}]   — doim RAM, savolsiz
  qcache_{tid}    : 48 soat TTL        — savollar, faqat kerakda yuklanadi
  users_cache     : {uid_str: {...}}   — doim RAM
  settings        : {uid_str: "uz_1_1"}
  results_{uid}   : {tid: {meta}}      — doim RAM (foiz, attempts, best)
  analysis_{uid}_{tid} : [...]         — 1 SOAT TTL, keyin o'chadi
  group_results   : vaqtinchalik, e'lon qilingach o'chadi

QOIDALAR:
  - Tahlil (analysis) — 1 soat, keyin RAMdan o'chadi
  - Guruh natijalari — e'lon qilingach darhol o'chadi
  - Test savollari   — 48 soat yechilmasa RAMdan o'chadi
  - User meta        — doim RAM (kichik)
"""
import threading, logging, sys
from datetime import datetime, timezone, timedelta

log  = logging.getLogger(__name__)
UTC  = timezone.utc
_lck = threading.Lock()
_RAM: dict = {}

RAM_LIMIT        = 450 * 1024 * 1024
ANALYSIS_TTL_H   = 1
CACHE_TTL_HOURS  = 48

DEFAULT_SETTINGS = "uz_1_1"
LANGS   = ["uz", "ru", "en"]
THEMES  = ["light", "dark"]
NOTIFS  = ["off", "on"]


def _get(k, d=None):
    with _lck: return _RAM.get(k, d)

def _set(k, v):
    with _lck: _RAM[k] = v

def _pop(k):
    with _lck: return _RAM.pop(k, None)


# ══ SETTINGS ══════════════════════════════════════════════════

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
    s[str(uid)] = f"{l}_{t}_{n}"
    _set("settings", s)

def get_all_settings():  return _get("settings", {})
def set_all_settings(d): _set("settings", d)


# ══ TEST META ══════════════════════════════════════════════════

def get_tests_meta():
    return [t for t in _get("tests_meta", []) if t.get("is_active", True)]

def get_all_tests_meta():
    return _get("tests_meta", [])

def set_tests_meta(m):
    _set("tests_meta", m)

def get_test_meta(tid):
    return next((t for t in _get("tests_meta", [])
                 if t.get("test_id") == tid), {})

def add_test_meta(meta):
    m = [x for x in _get("tests_meta", []) if x.get("test_id") != meta.get("test_id")]
    m.insert(0, meta)
    _set("tests_meta", m)

def update_test_meta(tid, updates):
    m = _get("tests_meta", [])
    for i, t in enumerate(m):
        if t.get("test_id") == tid:
            m[i].update(updates)
            break
    _set("tests_meta", m)

def delete_test_from_ram(tid):
    m = [t for t in _get("tests_meta", []) if t.get("test_id") != tid]
    _set("tests_meta", m)
    _pop(f"qcache_{tid}")
    log.info(f"RAM: test_{tid} o'chirildi")

def pause_test(tid, paused: bool):
    update_test_meta(tid, {"is_paused": paused})

def is_test_paused(tid):
    return get_test_meta(tid).get("is_paused", False)

def get_tests():       return get_tests_meta()
def get_test_by_id(tid):
    meta = get_test_meta(tid)
    if meta and not meta.get("is_active", True):
        return {}
    full = get_cached_questions(tid)
    if full is not None:
        return full
    return meta or {}

def set_tests(tests):
    metas = []
    for t in tests:
        meta = {k: v for k, v in t.items() if k != "questions"}
        meta["question_count"] = len(t.get("questions", []))
        metas.append(meta)
        if t.get("is_active", True) and t.get("questions"):
            cache_questions(t["test_id"], t)
    _set("tests_meta", metas)

def add_test(test):
    meta = {k: v for k, v in test.items() if k != "questions"}
    meta["question_count"] = len(test.get("questions", []))
    add_test_meta(meta)
    if test.get("questions"):
        cache_questions(test["test_id"], test)

def update_test_meta_full(test):
    tid  = test.get("test_id")
    meta = {k: v for k, v in test.items() if k != "questions"}
    update_test_meta(tid, meta)

def refresh_tests():
    _set("tests_meta", [])


# ══ SAVOLLAR CACHE (48 soat) ═══════════════════════════════════

def cache_questions(tid, test_full):
    now = datetime.now(UTC)
    _set(f"qcache_{tid}", {
        "test":        test_full,
        "loaded_at":   now,
        "last_access": now,
    })

def get_cached_questions(tid):
    e = _get(f"qcache_{tid}")
    if not e:
        return None
    e["last_access"] = datetime.now(UTC)
    _set(f"qcache_{tid}", e)
    return e["test"]

def touch_test_access(tid):
    e = _get(f"qcache_{tid}")
    if e:
        e["last_access"] = datetime.now(UTC)
        _set(f"qcache_{tid}", e)

def clear_expired_cache():
    now      = datetime.now(UTC)
    deadline = now - timedelta(hours=CACHE_TTL_HOURS)
    removed  = []
    with _lck:
        keys = [
            k for k in list(_RAM)
            if k.startswith("qcache_")
            and _RAM[k].get("last_access", now) < deadline
        ]
        for k in keys:
            del _RAM[k]
            removed.append(k.replace("qcache_", ""))
    if removed:
        log.info(f"RAM expired qcache: {len(removed)} test o'chirildi")
    return removed

def get_cache_stats():
    now   = datetime.now(UTC)
    items = []
    with _lck:
        for k, v in _RAM.items():
            if not k.startswith("qcache_"): continue
            tid = k.replace("qcache_", "")
            la  = v.get("last_access", now)
            ago = int((now - la).total_seconds() / 3600)
            items.append({"tid": tid, "last_access_hours_ago": ago})
    return items


# ══ USERLAR ════════════════════════════════════════════════════

def get_users():         return _get("users_cache", {})
def set_users(u):        _set("users_cache", u)
def get_user(tg_id):     return get_users().get(str(tg_id))

def upsert_user(tg_id, data):
    u = get_users()
    u[str(tg_id)] = data
    set_users(u)
    _set("users_dirty", True)

def is_users_dirty():    return _get("users_dirty", False)
def mark_users_dirty():  _set("users_dirty", True)
def clear_users_dirty(): _set("users_dirty", False)


# ══ NATIJALAR ══════════════════════════════════════════════════
#
# results_{uid} = {
#   tid: {attempts, all_pcts, best_score, avg_score, last_at, passed}
# }
# analysis_{uid}_{tid} = {data, last_result, saved_at}  ← 1 soat TTL

def _res_key(uid):      return f"results_{uid}"
def _ana_key(uid, tid): return f"analysis_{uid}_{tid}"

def get_user_stat(uid, tid):
    return _get(_res_key(uid), {}).get(tid, {})

def get_all_user_stats(uid):
    return _get(_res_key(uid), {})

def save_result_to_ram(user_id, test_id, result, via_link=False):
    uid_str = str(user_id)
    rid     = f"{uid_str}_{test_id}"
    now_str = str(datetime.now(UTC))[:16]

    # Meta (kichik, doim RAM)
    res = _get(_res_key(uid_str), {})
    e   = res.get(test_id, {
        "attempts":   0,
        "all_pcts":   [],
        "best_score": 0.0,
        "avg_score":  0.0,
        "last_at":    now_str,
        "passed":     False,
    })
    pct   = float(result.get("percentage", 0))
    att   = e["attempts"] + 1
    all_p = e["all_pcts"] + [pct]
    best  = max(e["best_score"], pct)
    avg   = round(sum(all_p) / len(all_p), 1)
    ps    = float(result.get("passing_score", 60))

    res[test_id] = {
        "attempts":   att,
        "all_pcts":   all_p,
        "best_score": best,
        "avg_score":  avg,
        "last_at":    now_str,
        "passed":     pct >= ps,
    }
    _set(_res_key(uid_str), res)

    # Tahlil (1 soat TTL)
    _set(_ana_key(uid_str, test_id), {
        "data": result.get("detailed_results", []),
        "last_result": {
            **result,
            "result_id":    rid,
            "test_id":      test_id,
            "user_id":      user_id,
            "attempt_num":  att,
            "completed_at": now_str,
        },
        "saved_at": datetime.now(UTC),
    })

    _set("users_dirty", True)
    return rid

def get_user_results(uid):
    res     = _get(_res_key(str(uid)), {})
    history = []
    for tid, e in res.items():
        history.append({
            "test_id":      tid,
            "result_id":    f"{uid}_{tid}",
            "last_pct":     e["all_pcts"][-1] if e["all_pcts"] else 0,
            "best_pct":     e["best_score"],
            "attempts":     e["attempts"],
            "all_pcts":     e["all_pcts"],
            "passed":       e["passed"],
            "completed_at": e["last_at"],
        })
    history.sort(key=lambda x: x.get("completed_at", ""), reverse=True)
    return history

def get_test_entry(uid, tid):
    return get_user_stat(uid, tid)

def get_analysis(uid, rid):
    parts = str(rid).split("_", 1)
    if len(parts) < 2:
        return []
    tid = parts[1]
    ana = _get(_ana_key(str(uid), tid))
    return ana.get("data", []) if ana else []

def get_last_result(uid, tid):
    ana = _get(_ana_key(str(uid), tid))
    return ana.get("last_result", {}) if ana else {}

def get_test_stats_for_user(uid, tid):
    return get_user_stat(uid, tid)

def get_all_solvers_for_test(tid):
    users  = get_users()
    result = []
    with _lck:
        keys = [k for k in _RAM if k.startswith("results_")]
    for key in keys:
        uid_str = key[8:]
        res     = _get(key, {})
        entry   = res.get(tid)
        if not entry or entry.get("attempts", 0) == 0:
            continue
        user = users.get(uid_str, {})
        result.append({
            "uid":        uid_str,
            "name":       user.get("name", f"User {uid_str}"),
            "username":   user.get("username", ""),
            "attempts":   entry["attempts"],
            "all_pcts":   entry["all_pcts"],
            "best_score": entry["best_score"],
            "avg_score":  entry["avg_score"],
            "last_at":    entry.get("last_at", ""),
        })
    result.sort(key=lambda x: x["best_score"], reverse=True)
    return result

def clear_expired_analysis():
    """1 soatdan eski tahlillarni RAMdan o'chirish"""
    now      = datetime.now(UTC)
    deadline = now - timedelta(hours=ANALYSIS_TTL_H)
    removed  = 0
    with _lck:
        keys = [
            k for k in list(_RAM)
            if k.startswith("analysis_")
            and isinstance(_RAM[k], dict)
            and _RAM[k].get("saved_at", now) < deadline
        ]
        for k in keys:
            del _RAM[k]
            removed += 1
    if removed:
        log.info(f"RAM: {removed} ta tahlil o'chirildi (1 soat TTL)")
    return removed


# ══ MOSLIK — eski daily_results formati ═══════════════════════

def get_daily():
    daily = {}
    with _lck:
        res_keys = [k for k in _RAM if k.startswith("results_")]
    for key in res_keys:
        uid_str = key[8:]
        res     = _get(key, {})
        by_test = {}
        for tid, e in res.items():
            by_test[tid] = {
                "attempts":      e["attempts"],
                "all_pcts":      e["all_pcts"],
                "best_score":    e["best_score"],
                "avg_score":     e["avg_score"],
                "last_at":       e.get("last_at", ""),
                "last_analysis": [],
                "last_result":   {},
                "first_result":  None,
                "accessed_link": False,
            }
        if by_test:
            daily[uid_str] = {"by_test": by_test, "history": []}
    return daily

def clear_daily():
    with _lck:
        keys = [k for k in list(_RAM)
                if k.startswith("results_") or k.startswith("analysis_")]
        for k in keys:
            del _RAM[k]
    log.info("RAM natijalar tozalandi")

def load_solvers_to_ram(tid, solvers_dict):
    for uid_str, s in solvers_dict.items():
        res = _get(_res_key(uid_str), {})
        if tid not in res:
            res[tid] = {
                "attempts":   s.get("attempts", 0),
                "all_pcts":   s.get("all_pcts", []),
                "best_score": s.get("best_score", 0.0),
                "avg_score":  s.get("avg_score", 0.0),
                "last_at":    s.get("last_at", ""),
                "passed":     s.get("best_score", 0) >= 60,
            }
            _set(_res_key(uid_str), res)

def load_history_to_ram(history_dict):
    for uid_str, by_test in history_dict.items():
        res = _get(_res_key(uid_str), {})
        for tid, entry in by_test.items():
            if tid not in res:
                res[tid] = {
                    "attempts":   entry.get("attempts", 0),
                    "all_pcts":   entry.get("all_pcts", []),
                    "best_score": entry.get("best_score", 0.0),
                    "avg_score":  entry.get("avg_score", 0.0),
                    "last_at":    entry.get("last_at", ""),
                    "passed":     entry.get("best_score", 0) >= 60,
                }
        if res:
            _set(_res_key(uid_str), res)


# ══ MENYU ══════════════════════════════════════════════════════

def set_menu_msg(uid, cid, msg_id):
    _set(f"menu_msg_{uid}", {"cid": cid, "mid": msg_id})

def pop_menu_msg(uid):
    with _lck:
        return _RAM.pop(f"menu_msg_{uid}", None)


# ══ STATS ══════════════════════════════════════════════════════

def stats():
    metas = _get("tests_meta", [])
    users = get_users()
    with _lck:
        cq  = sum(1 for k in _RAM if k.startswith("qcache_"))
        ana = sum(1 for k in _RAM if k.startswith("analysis_"))
        res = sum(1 for k in _RAM if k.startswith("results_"))
    total = sys.getsizeof(str(metas)) + sys.getsizeof(str(users))
    return {
        "tests":    len(metas),
        "users":    len(users),
        "daily_r":  res,
        "cached_q": cq,
        "analysis": ana,
        "mb":       round(total / 1024 / 1024, 2),
        "pct":      round(total / RAM_LIMIT * 100, 1),
        "limit_mb": 450,
    }


# ══ FAN NOMLARI ════════════════════════════════════════════════

def get_user_custom_subjects(uid):
    return _get("user_custom_subjects", {}).get(str(uid), [])

def add_user_custom_subject(uid, subject):
    from config import SUBJECTS
    if subject in SUBJECTS:
        return
    d   = _get("user_custom_subjects", {})
    lst = d.get(str(uid), [])
    if subject not in lst:
        lst.insert(0, subject)
        lst = lst[:10]
    d[str(uid)] = lst
    _set("user_custom_subjects", d)

def get_all_custom_subjects():
    return _get("user_custom_subjects", {})

def set_all_custom_subjects(d):
    _set("user_custom_subjects", d)
