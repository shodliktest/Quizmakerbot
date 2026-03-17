"""
RAM CACHE — Arxitektura:
  tests_meta    : [{id,title,...}]  — doim RAM, savolsiz (yengil)
  qcache_{tid}  : 12 soat cache     — savollar bilan, faqat test ochilganda
  users_cache   : {uid_str: {...}}  — doim RAM
  settings      : {uid_str: "uz_1_1"}
  daily_results : {uid_str: {by_test:{...}, history:[...]}} — 1 kun, midnight flush

MUHIM QOIDALAR:
  - Testlar hech qachon o'chirilmaydi (faqat admin delete)
  - Har user uchun har test: ALL percentages + ONLY LAST analysis
  - TG upload: yangi test/user yaratilganda, admin buyruq, midnight
"""
import threading, logging, sys
from datetime import datetime, timezone, timedelta

log  = logging.getLogger(__name__)
UTC  = timezone.utc
_lck = threading.Lock()
_RAM: dict = {}

RAM_LIMIT             = 450 * 1024 * 1024
DEFAULT_SETTINGS      = "uz_1_1"
LANGS  = ["uz", "ru", "en"]
THEMES = ["light", "dark"]
NOTIFS = ["off", "on"]


# ── Internal get/set ─────────────────────────────────────────
def _get(k, d=None):
    with _lck: return _RAM.get(k, d)

def _set(k, v):
    with _lck: _RAM[k] = v


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


# ══ TEST META (yengil, doim RAM) ══════════════════════════════

def get_tests_meta():
    return [t for t in _get("tests_meta", []) if t.get("is_active", True)]

def get_all_tests_meta():
    """Admin uchun — o'chirilganlarni ham ko'rsatish"""
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
    with _lck:
        _RAM.pop(f"qcache_{tid}", None)
    log.info(f"RAM: test_{tid} o'chirildi")

def pause_test(tid, paused: bool):
    update_test_meta(tid, {"is_paused": paused})

def is_test_paused(tid):
    return get_test_meta(tid).get("is_paused", False)

# Eski moslik
def get_tests():       return get_tests_meta()
def get_test_by_id(tid):
    # O'chirilgan test bo'lsa None qaytarsin
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
        # is_active=False bo'lsa meta listga qo'shiladi lekin cache qilinmaydi
        meta = {k: v for k, v in t.items() if k != "questions"}
        meta["question_count"] = len(t.get("questions", []))
        metas.append(meta)
def set_tests(tests):
    """Bot start'da indexdan META YUKLANADI — savollar yuklanmaydi (lazy load)"""
    metas = []
    for t in tests:
        meta = {k: v for k, v in t.items() if k != "questions"}
        meta["question_count"] = len(t.get("questions", []))
        metas.append(meta)
        # Savollarni oldindan yuklash YO'Q — faqat kerak bo'lganda lazy load
    _set("tests_meta", metas)

def add_test(test):
    """Yangi test (bot orqali yaratilgan) — meta RAMga, savollar qisqa cache"""
    meta = {k: v for k, v in test.items() if k != "questions"}
    meta["question_count"] = len(test.get("questions", []))
    add_test_meta(meta)
    # Bot orqali yaratilganda savollar qisqa muddatga cache — web dan kelganda YO'Q
    if test.get("questions") and test.get("source") != "web":
        cache_questions(test["test_id"], test)

def update_test_meta_full(test):
    tid = test.get("test_id")
    meta = {k: v for k, v in test.items() if k != "questions"}
    update_test_meta(tid, meta)

def refresh_tests():
    """Faqat meta tozalash, qcache qoldiramiz"""
    _set("tests_meta", [])


# ══ SAVOLLAR CACHE (on-demand, auto-evict) ════════════════════
#
# Qoidalar:
#   - RAM da FAQAT META turadi (title, category, question_count, ...)
#   - Savollar (qcache_) FAQAT test yechilayotganda yuklanadi (lazy load)
#   - active_users > 0 bo'lsa — hech qachon o'chirilmaydi
#   - active_users == 0 va 10 daqiqa murojaat yo'q bo'lsa — o'chiriladi
#   - TG kanalda doim saqlanadi — keyingi so'rovda qayta lazy load
#
CACHE_TTL_MINUTES = 10   # 10 daqiqa hech kim yechmasa RAMdan o'chadi

def cache_questions(tid, test_full):
    """Test savollarini RAMga yuklash — faqat yechish boshlanganda chaqiriladi"""
    now = datetime.now(UTC)
    _set(f"qcache_{tid}", {
        "test":         test_full,
        "loaded_at":    now,
        "last_access":  now,
        "active_users": 0,
    })
    log.debug(f"RAM qcache: {tid} yuklandi")

def get_cached_questions(tid):
    """RAMdan o'qish — last_access yangilanadi"""
    e = _get(f"qcache_{tid}")
    if not e:
        return None
    e["last_access"] = datetime.now(UTC)
    _set(f"qcache_{tid}", e)
    return e["test"]

def touch_test_access(tid):
    """Test yechilayotganda last_access yangilanadi"""
    e = _get(f"qcache_{tid}")
    if e:
        e["last_access"] = datetime.now(UTC)
        _set(f"qcache_{tid}", e)

def mark_test_active(tid):
    """User test yechishni BOSHLAGANDA — active_users oshirish"""
    e = _get(f"qcache_{tid}")
    if e:
        e["active_users"] = e.get("active_users", 0) + 1
        e["last_access"]  = datetime.now(UTC)
        _set(f"qcache_{tid}", e)

def mark_test_done(tid):
    """User test yechishni TUGATGANDA — active_users kamaytirish.
    Darhol o'chirmaymiz — TTL ga qoldiramiz (keyingi user tez kelishi mumkin)."""
    e = _get(f"qcache_{tid}")
    if e:
        e["active_users"] = max(0, e.get("active_users", 1) - 1)
        e["last_access"]  = datetime.now(UTC)
        _set(f"qcache_{tid}", e)

def evict_test_cache(tid):
    """Testning savollarini RAMdan o'chirish (meta qoladi, TGda bor)"""
    with _lck:
        _RAM.pop(f"qcache_{tid}", None)
    log.debug(f"RAM evict: {tid} savollari o'chirildi (meta qoldi)")

def clear_expired_cache():
    """TTL o'tgan, hech kim yechmayotgan testlarni RAMdan o'chirish"""
    now      = datetime.now(UTC)
    deadline = now - timedelta(minutes=CACHE_TTL_MINUTES)
    removed  = []
    with _lck:
        keys = [
            k for k in list(_RAM)
            if k.startswith("qcache_")
            and _RAM[k].get("active_users", 0) == 0  # hech kim yechmayotgan
            and _RAM[k].get("last_access", now) < deadline
        ]
        for k in keys:
            del _RAM[k]
            removed.append(k.replace("qcache_", ""))
    if removed:
        log.info(f"RAM cleanup: {len(removed)} test o'chirildi")
    return removed

def get_cache_stats():
    """Admin uchun — RAM holatini ko'rish"""
    now   = datetime.now(UTC)
    items = []
    with _lck:
        for k, v in _RAM.items():
            if not k.startswith("qcache_"): continue
            tid  = k.replace("qcache_", "")
            la   = v.get("last_access", now)
            ago  = int((now - la).total_seconds() / 60)
            items.append({
                "tid": tid,
                "last_access_min_ago": ago,
                "active_users": v.get("active_users", 0),
            })
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
# STRUKTURA:
# daily_results[uid_str] = {
#   "by_test": {
#     tid: {
#       "attempts":     N,
#       "all_pcts":     [85.0, 92.0, ...],   # BARCHA urinishlar foizi
#       "best_score":   92.0,
#       "avg_score":    88.5,
#       "first_result": {...},               # Birinchi urinish to'liq (creator/admin uchun)
#       "last_result":  {...},               # Oxirgi urinish to'liq
#       "last_analysis":[...],              # FAQAT OXIRGI tahlil
#       "accessed_link": False,             # Link orqali kirganmi
#       "last_at":      "2025-01-01 12:00",
#     }
#   },
#   "history": [  # Yengil ro'yxat (profile uchun)
#     {tid, title, last_pct, best_pct, attempts, all_pcts, completed_at, accessed_link}
#   ]
# }

def get_daily():           return _get("daily_results", {})
def clear_daily():
    _set("daily_results", {})
    log.info("Kunlik RAM tozalandi")

def save_result_to_ram(user_id, test_id, result, via_link=False):
    """
    Natijani RAMga saqlash.
    - all_pcts: barcha urinishlar foizi (to'planib boradi)
    - last_analysis: faqat oxirgi tahlil (eskisi o'chib ketadi)
    - first_result: birinchi urinish (bir marta yoziladi)
    - last_result: har safar yangilanadi
    Returns: result_id
    """
    daily   = _get("daily_results", {})
    uid_str = str(user_id)
    rid     = f"{uid_str}_{test_id}"
    now_str = str(datetime.now(UTC))[:16]

    if uid_str not in daily:
        daily[uid_str] = {"by_test": {}, "history": []}

    bt = daily[uid_str]["by_test"]
    if test_id not in bt:
        bt[test_id] = {
            "attempts":      0,
            "all_pcts":      [],
            "best_score":    0.0,
            "avg_score":     0.0,
            "first_result":  None,
            "last_result":   None,
            "last_analysis": [],
            "accessed_link": via_link,
            "last_at":       now_str,
        }

    e       = bt[test_id]
    pct     = float(result.get("percentage", 0))
    att     = e["attempts"] + 1
    all_p   = e["all_pcts"] + [pct]
    best    = max(e["best_score"], pct)
    avg     = round(sum(all_p) / len(all_p), 1)

    # To'liq natija (result_id va meta qo'shib)
    full_res = {
        **result,
        "result_id":   rid,
        "test_id":     test_id,
        "user_id":     user_id,
        "attempt_num": att,
        "completed_at": now_str,
    }

    e.update({
        "attempts":      att,
        "all_pcts":      all_p,
        "best_score":    best,
        "avg_score":     avg,
        "last_result":   full_res,
        "last_analysis": result.get("detailed_results", []),
        "last_at":       now_str,
    })
    if e["first_result"] is None:
        e["first_result"] = full_res
    if via_link:
        e["accessed_link"] = True

    # History (yengil) — har test uchun bitta yozuv
    h = [x for x in daily[uid_str].get("history", []) if x.get("test_id") != test_id]
    h.insert(0, {
        "test_id":      test_id,
        "result_id":    rid,
        "last_pct":     pct,
        "best_pct":     best,
        "attempts":     att,
        "all_pcts":     all_p,
        "passed":       pct >= result.get("passing_score", 60),
        "accessed_link":via_link or e["accessed_link"],
        "completed_at": now_str,
    })
    daily[uid_str]["history"] = h[:200]
    _set("daily_results", daily)
    return rid

def get_user_results(uid):
    """History ro'yxati (yengil)"""
    return _get("daily_results", {}).get(str(uid), {}).get("history", [])

def get_test_entry(uid, tid):
    """Bitta test uchun to'liq entry"""
    return (_get("daily_results", {})
            .get(str(uid), {})
            .get("by_test", {})
            .get(tid, {}))

def get_analysis(uid, rid):
    """Oxirgi tahlil — rid = uid_testid"""
    parts = str(rid).split("_", 1)
    if len(parts) < 2:
        return []
    tid = parts[1]
    return (_get("daily_results", {})
            .get(str(uid), {})
            .get("by_test", {})
            .get(tid, {})
            .get("last_analysis", []))

def get_test_stats_for_user(uid, tid):
    """Moslik uchun — test entry qaytaradi"""
    return get_test_entry(uid, tid)

def get_all_solvers_for_test(tid):
    """
    Bu test yechgan barcha userlar:
    [{uid_str, name, attempts, all_pcts, best_score, avg_score, first_result, last_result}]
    Creator/admin uchun.
    """
    daily   = _get("daily_results", {})
    users   = get_users()
    result  = []
    for uid_str, data in daily.items():
        entry = data.get("by_test", {}).get(tid)
        if not entry or entry.get("attempts", 0) == 0:
            continue
        user = users.get(uid_str, {})
        result.append({
            "uid":          uid_str,
            "name":         user.get("name", f"User {uid_str}"),
            "username":     user.get("username", ""),
            "attempts":     entry["attempts"],
            "all_pcts":     entry["all_pcts"],
            "best_score":   entry["best_score"],
            "avg_score":    entry["avg_score"],
            "first_result": entry.get("first_result"),
            "last_result":  entry.get("last_result"),
            "last_at":      entry.get("last_at", ""),
        })
    result.sort(key=lambda x: x["best_score"], reverse=True)
    return result

def load_solvers_to_ram(tid, solvers_dict):
    """TG dan yuklangan solvers ma'lumotlarini daily_results ga joylash"""
    daily = _get("daily_results", {})
    for uid_str, s in solvers_dict.items():
        if uid_str not in daily:
            daily[uid_str] = {"by_test": {}, "history": []}
        bt = daily[uid_str]["by_test"]
        if tid not in bt:
            bt[tid] = {
                "attempts":      s.get("attempts", 0),
                "all_pcts":      s.get("all_pcts", []),
                "best_score":    s.get("best_score", 0.0),
                "avg_score":     s.get("avg_score", 0.0),
                # Rebootdan keyin tiklanadi
                "first_result":  s.get("first_result") or {},
                "last_result":   s.get("last_result") or {},
                "last_analysis": s.get("last_analysis") or [],
                "accessed_link": False,
                "last_at":       s.get("last_at", ""),
            }
    _set("daily_results", daily)


def load_history_to_ram(history_dict):
    """TG users_full.json dan history ni RAMga yuklash"""
    daily = _get("daily_results", {})
    for uid_str, by_test in history_dict.items():
        if uid_str not in daily:
            daily[uid_str] = {"by_test": {}, "history": []}
        bt = daily[uid_str]["by_test"]
        for tid, entry in by_test.items():
            if tid not in bt:
                bt[tid] = {
                    "attempts":      entry.get("attempts", 0),
                    "all_pcts":      entry.get("all_pcts", []),
                    "best_score":    entry.get("best_score", 0.0),
                    "avg_score":     entry.get("avg_score", 0.0),
                    "first_result":  entry.get("first_result", {}),
                    "last_result":   entry.get("last_result", {}),
                    "last_analysis": entry.get("last_analysis", []),
                    "accessed_link": False,
                    "last_at":       entry.get("last_at", ""),
                }
        # History ro'yxatini ham tiklash
        h = []
        for tid, entry in bt.items():
            if entry.get("attempts", 0) > 0:
                pcts = entry.get("all_pcts", [])
                h.append({
                    "test_id":       tid,
                    "result_id":     f"{uid_str}_{tid}",
                    "last_pct":      pcts[-1] if pcts else 0,
                    "best_pct":      entry.get("best_score", 0),
                    "attempts":      entry["attempts"],
                    "all_pcts":      pcts,
                    "passed":        entry.get("best_score", 0) >= 60,
                    "accessed_link": entry.get("accessed_link", False),
                    "completed_at":  entry.get("last_at", ""),
                })
        h.sort(key=lambda x: x.get("completed_at", ""), reverse=True)
        daily[uid_str]["history"] = h[:200]
    _set("daily_results", daily)


def get_last_result(uid, tid):
    return get_test_entry(uid, tid).get("last_result", {})


# ══ STATS ══════════════════════════════════════════════════════


def set_menu_msg(uid, cid, msg_id):
    """Asosiy menyu xabarini saqlash — keyingi harakatda o'chiriladi"""
    _set(f"menu_msg_{uid}", {"cid": cid, "mid": msg_id})

def pop_menu_msg(uid):
    """Asosiy menyu xabarini olish va o'chirish"""
    with _lck:
        key  = f"menu_msg_{uid}"
        data = _RAM.pop(key, None)
    return data  # {"cid":..., "mid":...} yoki None

def stats():
    metas = _get("tests_meta", [])
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


# ══ FOYDALANUVCHI MAXSUS FANLARI ═══════════════════════════════

def get_user_custom_subjects(uid):
    """Foydalanuvchi qo'lda yozgan fan nomlari"""
    return _get("user_custom_subjects", {}).get(str(uid), [])

def add_user_custom_subject(uid, subject):
    """Yangi maxsus fan nomini saqlash"""
    from config import SUBJECTS
    if subject in SUBJECTS:
        return  # Standart fanda qo'shish shart emas
    d = _get("user_custom_subjects", {})
    lst = d.get(str(uid), [])
    if subject not in lst:
        lst.insert(0, subject)
        lst = lst[:10]  # Max 10 ta
    d[str(uid)] = lst
    _set("user_custom_subjects", d)

def get_all_custom_subjects():
    return _get("user_custom_subjects", {})

def set_all_custom_subjects(d):
    _set("user_custom_subjects", d)
