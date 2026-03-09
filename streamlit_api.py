"""
TestPro — Streamlit API Server
================================
Sayt (HTML/JS) ←→ Bu API ←→ Telegram kanal (JSON ma'lumotlar)

Deploy: streamlit run streamlit_api.py

.streamlit/secrets.toml:
  BOT_TOKEN            = "123:ABC..."
  BOT_USERNAME         = "YourBotUsername"
  ADMIN_IDS            = "123456789"
  STORAGE_CHANNEL_ID   = "-1001234567890"
"""

import streamlit as st
import json, time, os, hashlib, hmac
from typing import Optional

# ── Sozlamalar ──
BOT_TOKEN  = st.secrets.get("BOT_TOKEN",  os.getenv("BOT_TOKEN", ""))
ADMIN_IDS  = [int(x) for x in str(st.secrets.get("ADMIN_IDS","")).split(",") if x.strip()]

# ── Bot modullarini import qilish ──
try:
    import sys; sys.path.insert(0, ".")
    from utils import tg_db
    HAS_TG = True
except Exception as e:
    HAS_TG = False

st.set_page_config(page_title="TestPro API", page_icon="📡", layout="centered")

# ════════════════════════════════════════════
# CORS — har bir response uchun
# ════════════════════════════════════════════
def cors_headers():
    """Streamlit native CORS qo'llab-quvvatlamaydi.
       Ishlab turgan yechim: Cloudflare Worker yoki Vercel Edge proxy."""
    pass

# ════════════════════════════════════════════
# TG AUTH TEKSHIRISH
# ════════════════════════════════════════════
def check_tg_auth(data: dict) -> bool:
    if not BOT_TOKEN:
        return True  # dev rejim
    check_hash = data.pop("hash", "")
    data_check = "\n".join(f"{k}={v}" for k,v in sorted(data.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, check_hash)

# ════════════════════════════════════════════
# TG DB WRAPPERS (async → sync)
# ════════════════════════════════════════════
def run_async(coro):
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=15)
        return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)

def tg_get_tests():
    if HAS_TG:
        try: return tg_db.get_tests_meta() or []
        except: pass
    return st.session_state.get("_demo_tests", [])

def tg_get_full(tid):
    if HAS_TG:
        try: return run_async(tg_db.get_test_full(tid))
        except: pass
    return None

def tg_save_full(data):
    if HAS_TG:
        try: run_async(tg_db.save_test_full(data)); return True
        except: pass
    return False

def tg_delete(tid):
    if HAS_TG:
        try: run_async(tg_db.delete_test_tg(tid)); return True
        except: pass
    return False

# ════════════════════════════════════════════
# ROUTER
# ════════════════════════════════════════════
p    = st.query_params
ep   = p.get("endpoint", "")
meth = p.get("m", "GET").upper()

try:
    body = json.loads(p.get("body", "{}") or "{}")
except:
    body = {}

tg_id = p.get("tg_id", "")  # saytdan keladi

def resp(data):
    st.json(data)

# ── tests/public ──
if ep == "tests/public":
    tests = [t for t in tg_get_tests() if t.get("visibility") == "public" and t.get("is_active", True)]
    resp(sorted(tests, key=lambda x: x.get("created_at",""), reverse=True))

# ── tests/my ──
elif ep == "tests/my":
    uid = p.get("uid","")
    mine = [t for t in tg_get_tests() if str(t.get("creator_id","")) == uid]
    resp(sorted(mine, key=lambda x: x.get("created_at",""), reverse=True))

# ── tests (all) ──
elif ep == "tests":
    resp(tg_get_tests())

# ── test/{id}/full ──
elif "/" in ep and ep.endswith("/full"):
    tid  = ep.split("/")[1]
    full = tg_get_full(tid)
    if full:
        meta = {k:v for k,v in full.items() if k != "questions"}
        resp({"testData": meta, "questions": full.get("questions", [])})
    else:
        tests = tg_get_tests()
        meta  = next((t for t in tests if t.get("test_id") == tid), None)
        resp({"testData": meta, "questions": []})

# ── test/{id}/questions GET ──
elif "/" in ep and ep.endswith("/questions") and meth == "GET":
    tid  = ep.split("/")[1]
    full = tg_get_full(tid)
    resp(full.get("questions", []) if full else [])

# ── test/{id}/questions POST ──
elif "/" in ep and ep.endswith("/questions") and meth == "POST":
    tid = ep.split("/")[1]
    qs  = body.get("questions", [])
    full = tg_get_full(tid) or {}
    full["test_id"]  = tid
    full["questions"] = qs
    tg_save_full(full)
    resp({"ok": True})

# ── test/code/{code} ──
elif ep.startswith("test/code/"):
    code  = ep.split("/",2)[2].upper()
    tests = tg_get_tests()
    test  = next((t for t in tests if t.get("accessCode","").upper() == code), None)
    resp(test or {"error": "Topilmadi"})

# ── test/create ──
elif ep == "test/create":
    import uuid
    tid  = str(uuid.uuid4())[:8].upper()
    test = {"test_id": tid, **body, "created_at": int(time.time())}
    tg_save_full(test)
    resp({"id": tid, "accessCode": body.get("accessCode","")})

# ── test/{id}/update ──
elif "/" in ep and ep.endswith("/update") and ep.startswith("test/"):
    tid = ep.split("/")[1]
    if HAS_TG:
        try: run_async(tg_db.update_test_meta_tg(tid, body))
        except: pass
    resp({"ok": True})

# ── test/{id}/delete ──
elif "/" in ep and ep.endswith("/delete") and ep.startswith("test/"):
    tid = ep.split("/")[1]
    tg_delete(tid)
    resp({"ok": True})

# ── test/{id} ──
elif ep.startswith("test/") and ep.count("/") == 1:
    tid   = ep[5:]
    tests = tg_get_tests()
    test  = next((t for t in tests if t.get("test_id") == tid), None)
    resp(test or {"error": "Topilmadi"})

# ── user/{uid} ──
elif ep.startswith("user/") and ep.count("/") == 1 and not ep.endswith("/update"):
    uid = ep[5:]
    user = None
    if HAS_TG:
        try:
            from utils import ram_cache as ram
            user = ram.get_user(int(uid)) if uid.isdigit() else None
        except: pass
    resp(user or {"error": "Topilmadi"})

# ── user/create ──
elif ep == "user/create":
    if HAS_TG:
        try:
            from utils import ram_cache as ram
            uid = body.get("uid","")
            if uid: ram.ensure_user(int(uid), body)
        except: pass
    resp({"ok": True})

# ── user/{uid}/update ──
elif ep.endswith("/update") and ep.startswith("user/"):
    uid = ep.split("/")[1]
    if HAS_TG:
        try:
            from utils import ram_cache as ram
            if uid.isdigit(): ram.update_user(int(uid), body)
        except: pass
    resp({"ok": True})

# ── users ──
elif ep == "users":
    users = []
    if HAS_TG:
        try:
            from utils import ram_cache as ram
            users = ram.get_all_users() if hasattr(ram,"get_all_users") else []
        except: pass
    resp(users)

# ── result/save ──
elif ep == "result/save":
    if HAS_TG:
        try:
            from utils.db import save_result
            uid = int(body.get("userId",0))
            tid = body.get("testId","")
            score = {
                "percentage":    body.get("score", 0),
                "correct_count": body.get("correct", 0),
                "total":         body.get("total", 0),
                "time_spent":    body.get("elapsed", 0),
                "mode": "web",
            }
            run_async(save_result(uid, tid, score))
        except Exception as e:
            st.error(f"save_result: {e}")
    resp({"ok": True})

# ── results/{uid} ──
elif ep.startswith("results/"):
    uid   = ep[8:]
    limit = int(p.get("limit", 20))
    results = []
    if HAS_TG:
        try:
            from utils.db import get_user_results
            results = get_user_results(int(uid)) if uid.isdigit() else []
        except: pass
    resp(results[:limit] if limit else results)

# ── Dashboard (endpoint yo'q) ──
else:
    st.title("📡 TestPro API")
    col1, col2, col3 = st.columns(3)
    tests = tg_get_tests()
    col1.metric("Jami testlar",   len(tests))
    col2.metric("Ommaviy",        len([t for t in tests if t.get("visibility")=="public"]))
    col3.metric("TG DB",          "✅" if HAS_TG else "❌")

    st.divider()
    st.markdown("### Saytni ulash")
    st.markdown("""
`js/api.js` faylida **2 joyni** o'zgartiring:

```js
const BOT_USERNAME = 'SizningBotUsername';   // ← bot @username
const API_URL      = 'https://shu-url.streamlit.app';  // ← shu sahifa URL
```

### Secrets (.streamlit/secrets.toml)
```toml
BOT_TOKEN          = "123456:ABC..."
BOT_USERNAME       = "YourBot"
ADMIN_IDS          = "123456789"
STORAGE_CHANNEL_ID = "-1001234567890"
```
""")

    if not HAS_TG:
        st.warning("⚠️ `utils.tg_db` topilmadi — bot papkasini tekshiring")
