"""
TestPro — Streamlit API Server
================================
Arxitektura:
  1. tests/public  → RAM dagi meta (tezkor, sahifa yuklanishida)
  2. test/{id}/full → Telegram kanaldan lazy load (test boshlanganda)

Deploy: bot GitHub repoga qo'shing → Streamlit Cloud da yangi app
  Main file: streamlit_api.py

.streamlit/secrets.toml:
  BOT_TOKEN          = "123:ABC..."
  BOT_USERNAME       = "QuizMarkerBot"
  ADMIN_IDS          = "123456789"
  STORAGE_CHANNEL_ID = "-1001234567890"
"""

import streamlit as st
import json, time, os
from typing import Optional

st.set_page_config(page_title="TestPro API", page_icon="📡", layout="centered")

# ── Sozlamalar ──
BOT_TOKEN = st.secrets.get("BOT_TOKEN", os.getenv("BOT_TOKEN", ""))
ADMIN_IDS = [int(x) for x in str(st.secrets.get("ADMIN_IDS", "")).split(",") if x.strip().isdigit()]

# ── Bot modullarini import ──
try:
    import sys; sys.path.insert(0, ".")
    from utils import tg_db, ram_cache as ram
    HAS_TG = True
except Exception as e:
    HAS_TG = False

# ── Async wrapper ──
def run_async(coro):
    import asyncio, concurrent.futures
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result(timeout=20)
        return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)

# ── Bot init (bir marta) ──
@st.cache_resource(show_spinner=False)
def init_bot():
    if not HAS_TG or not BOT_TOKEN:
        return False
    try:
        import asyncio
        from aiogram import Bot
        from config import STORAGE_CHANNEL_ID
        bot = Bot(token=BOT_TOKEN)
        asyncio.run(tg_db.init(bot, STORAGE_CHANNEL_ID))
        tests = asyncio.run(tg_db.get_tests())
        if tests:
            ram.set_tests(tests)
        users = asyncio.run(tg_db.get_users())
        if users:
            ram.set_users(users)
        return True
    except Exception as e:
        st.error(f"Bot init xato: {e}")
        return False

ready = init_bot()

# ════════════════════════════════════════
# ROUTER
# ════════════════════════════════════════
p   = st.query_params
ep  = p.get("endpoint", "")

def resp(data):
    """JSON javob"""
    st.json(data)

# ────────────────────────────────────────
# tests/public — RAM dan meta (TEZKOR)
# Sahifa yuklanishida chaqiriladi
# ────────────────────────────────────────
if ep == "tests/public":
    if HAS_TG and ready:
        tests = tg_db.get_tests_meta()
    else:
        tests = []
    public = [
        {k: v for k, v in t.items() if k != "questions"}   # savollar yo'q!
        for t in tests
        if t.get("visibility") == "public" and t.get("is_active", True)
    ]
    resp(sorted(public, key=lambda x: x.get("created_at", 0), reverse=True))

# ────────────────────────────────────────
# tests/my — foydalanuvchi testlari (meta)
# ────────────────────────────────────────
elif ep == "tests/my":
    uid = p.get("uid", "")
    if HAS_TG and ready and uid:
        tests = tg_db.get_tests_meta()
        mine  = [
            {k: v for k, v in t.items() if k != "questions"}
            for t in tests
            if str(t.get("creator_id", "")) == uid
        ]
    else:
        mine = []
    resp(sorted(mine, key=lambda x: x.get("created_at", 0), reverse=True))

# ────────────────────────────────────────
# test/{id}/meta — bitta test meta (RAM)
# ────────────────────────────────────────
elif "/" in ep and ep.endswith("/meta"):
    tid  = ep.split("/")[1]
    meta = tg_db.get_test_meta(tid) if (HAS_TG and ready) else {}
    resp(meta or {"error": "Topilmadi"})

# ────────────────────────────────────────
# test/{id}/full — TO'LIQ (savollar bilan)
# Test boshlanganda chaqiriladi — TG dan lazy load
# ────────────────────────────────────────
elif "/" in ep and ep.endswith("/full"):
    tid  = ep.split("/")[1]
    if HAS_TG and ready:
        full = run_async(tg_db.get_test_full(tid))
        if full and full.get("questions"):
            meta = {k: v for k, v in full.items() if k != "questions"}
            resp({
                "testData":  meta,
                "questions": full["questions"],
                "total":     len(full["questions"])
            })
        else:
            resp({"error": "Test topilmadi yoki savollar yo'q"})
    else:
        resp({"error": "Server tayyor emas"})

# ────────────────────────────────────────
# user/{uid} — foydalanuvchi ma'lumoti
# ────────────────────────────────────────
elif ep.startswith("user/") and ep.count("/") == 1:
    uid  = ep[5:]
    user = None
    if HAS_TG and ready and uid.isdigit():
        user = ram.get_user(int(uid))
    resp(user or {"error": "Topilmadi"})

# ────────────────────────────────────────
# result/save — natija saqlash
# ────────────────────────────────────────
elif ep == "result/save":
    try:
        body = json.loads(p.get("body", "{}") or "{}")
    except:
        body = {}
    if HAS_TG and ready:
        try:
            from utils.db import save_result
            uid   = int(body.get("userId", 0))
            tid   = body.get("testId", "")
            score = {
                "percentage":    body.get("score", 0),
                "correct_count": body.get("correct", 0),
                "total":         body.get("total", 0),
                "time_spent":    body.get("elapsed", 0),
                "mode":          "web",
            }
            run_async(save_result(uid, tid, score))
            resp({"ok": True})
        except Exception as e:
            resp({"ok": False, "error": str(e)})
    else:
        resp({"ok": False, "error": "Server tayyor emas"})

# ────────────────────────────────────────
# results/{uid} — foydalanuvchi natijalari
# ────────────────────────────────────────
elif ep.startswith("results/"):
    uid   = ep[8:]
    limit = int(p.get("limit", 20))
    results = []
    if HAS_TG and ready and uid.isdigit():
        try:
            from utils.db import get_user_results
            results = get_user_results(int(uid)) or []
        except:
            pass
    resp(results[:limit])

# ────────────────────────────────────────
# Dashboard (endpoint yo'q)
# ────────────────────────────────────────
else:
    st.title("📡 TestPro API")
    st.caption("Vercel sayt ↔ Bot RAM ↔ Telegram kanal")

    col1, col2, col3 = st.columns(3)
    if HAS_TG and ready:
        tests = tg_db.get_tests_meta()
        users = ram.get_users()
        col1.metric("Testlar (RAM)",  len(tests))
        col2.metric("Foydalanuvchilar", len(users))
        col3.metric("Status", "✅ Tayyor")
    else:
        col1.metric("Status", "❌ Xato")
        col2.metric("TG DB", "Ulanmagan")
        col3.metric("Bot", "Yuklanmadi")

    st.divider()
    st.markdown("### 📋 Endpoint lar")
    st.markdown("""
| Endpoint | Vazifa | Tezlik |
|----------|--------|--------|
| `tests/public` | Ommaviy testlar meta | ⚡ RAM (tezkor) |
| `tests/my?uid=X` | Mening testlarim meta | ⚡ RAM (tezkor) |
| `test/{id}/meta` | Bitta test meta | ⚡ RAM (tezkor) |
| `test/{id}/full` | To'liq savollar | 🔄 TG lazy load |
| `user/{uid}` | Foydalanuvchi | ⚡ RAM |
| `result/save` | Natija saqlash | 💾 TG |
| `results/{uid}` | Natijalar tarixi | ⚡ RAM |
    """)

    if not HAS_TG:
        st.warning("⚠️ `utils.tg_db` topilmadi — bot papkasida ekanligini tekshiring")
    if not BOT_TOKEN:
        st.warning("⚠️ `BOT_TOKEN` secrets.toml da yo'q")
