"""
TestPro — Streamlit API Server (Mustaqil)
==========================================
Bot bilan bog'liq EMAS. Faqat TG kanal + RAM.

Startup da TG kanaldan barcha testlarni yuklab oladi.
2.5 GB RAM da saqlaydi. Har 5 daqiqada yangilarini tekshiradi.

.streamlit/secrets.toml:
  BOT_TOKEN          = "123:ABC..."
  STORAGE_CHANNEL_ID = "-1001234567890"
  ADMIN_PASSWORD     = "admin123"
"""

import streamlit as st
import json, time, os, datetime, logging
import urllib.request
import concurrent.futures

st.set_page_config(page_title="TestPro API", page_icon="📡", layout="centered")

# ── Sozlamalar ──────────────────────────────────────────────────
BOT_TOKEN  = st.secrets.get("BOT_TOKEN",          os.getenv("BOT_TOKEN", ""))
CHANNEL_ID = st.secrets.get("STORAGE_CHANNEL_ID", os.getenv("STORAGE_CHANNEL_ID", ""))
ADMIN_IDS  = [int(x) for x in str(st.secrets.get("ADMIN_IDS","")).split(",") if x.strip().isdigit()]
ADMIN_PASS = st.secrets.get("ADMIN_PASSWORD", "admin123")
TG         = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ── TG helpers ─────────────────────────────────────────────────
def tg_post(method, data):
    url  = f"{TG}/{method}"
    body = json.dumps(data).encode()
    req  = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tg_get_file(file_id):
    res = tg_post("getFile", {"file_id": file_id})
    if not res.get("ok"):
        return None
    path = res["result"]["file_path"]
    url  = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read())
    except:
        return None

def tg_forward_get(msg_id):
    fwd = tg_post("forwardMessage", {
        "chat_id": CHANNEL_ID, "from_chat_id": CHANNEL_ID,
        "message_id": int(msg_id)
    })
    if not fwd.get("ok"):
        return None
    doc    = fwd["result"].get("document")
    new_id = fwd["result"]["message_id"]
    tg_post("deleteMessage", {"chat_id": CHANNEL_ID, "message_id": new_id})
    if not doc:
        return None
    return tg_get_file(doc["file_id"])

# ════════════════════════════════════════════════════════════════
# RAM Store
# ════════════════════════════════════════════════════════════════
class Store:
    index:     dict  = {}
    meta:      list  = []       # [{test_id, title, ...}] savolsiz
    q_cache:   dict  = {}       # {test_id: [questions]}
    last_sync: float = 0
    ready:     bool  = False

store = Store()

# ── Normalizatsiya ──────────────────────────────────────────────
def norm(t: dict) -> dict:
    out = {k: v for k, v in t.items() if k != "questions"}
    out["id"]       = out.get("id") or out.get("test_id")
    out["authorId"] = out.get("authorId") or str(out.get("creator_id", ""))
    out["subject"]  = out.get("subject")  or out.get("category") or "other"
    out["creator_name"] = out.get("creator_name") or out.get("authorName") or ""
    return out

# ── Startup ─────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def startup():
    if not BOT_TOKEN or not CHANNEL_ID:
        return False

    # Index
    chat = tg_post("getChat", {"chat_id": CHANNEL_ID})
    pin  = chat.get("result", {}).get("pinned_message")
    if not pin or not pin.get("document"):
        return False

    index = tg_get_file(pin["document"]["file_id"])
    if not index or "tests_meta" not in index:
        return False

    store.index = index
    store.meta  = index.get("tests_meta", [])

    # Barcha testlarni savollar bilan yuklash
    total  = len(store.meta)
    prog   = st.progress(0, text=f"⬇️ 0/{total} yuklanmoqda...")
    loaded = 0

    for i, meta in enumerate(store.meta):
        tid    = meta.get("test_id")
        msg_id = index.get(f"test_{tid}")
        if tid and msg_id:
            try:
                full = tg_forward_get(msg_id)
                if full and full.get("questions"):
                    store.q_cache[tid] = full["questions"]
                    loaded += 1
                time.sleep(0.2)
            except:
                pass
        prog.progress((i+1)/max(total,1), text=f"⬇️ {i+1}/{total}: {meta.get('title','?')[:30]}")

    prog.empty()
    store.last_sync = time.time()
    store.ready     = True
    return True

def sync():
    """Yangi testlarni tekshirish"""
    if not BOT_TOKEN or not CHANNEL_ID:
        return
    chat = tg_post("getChat", {"chat_id": CHANNEL_ID})
    pin  = chat.get("result", {}).get("pinned_message")
    if not pin or not pin.get("document"):
        return
    index = tg_get_file(pin["document"]["file_id"])
    if not index:
        return
    store.index = index
    for meta in index.get("tests_meta", []):
        tid = meta.get("test_id")
        if not tid:
            continue
        existing = next((t for t in store.meta if t["test_id"] == tid), None)
        if existing:
            existing.update({k:v for k,v in meta.items() if k!="questions"})
        else:
            store.meta.insert(0, meta)
        if tid not in store.q_cache:
            msg_id = index.get(f"test_{tid}")
            if msg_id:
                try:
                    full = tg_forward_get(msg_id)
                    if full and full.get("questions"):
                        store.q_cache[tid] = full["questions"]
                    time.sleep(0.2)
                except:
                    pass
    store.last_sync = time.time()

# ── JSON javob ─────────────────────────────────────────────────
def api_resp(data):
    """
    Proxy.js uchun JSON chiqarish.
    st.json() HTML wrapper bilan chiqaradi — proxy regex bilan oladi.
    Qo'shimcha: hidden div da clean JSON ham chiqaramiz.
    """
    raw = json.dumps(data, ensure_ascii=False)
    # 1. Streamlit native viewer
    st.json(data)
    # 2. Raw JSON — proxy uchun
    st.markdown(
        f'<div id="api-raw" style="display:none">{raw}</div>',
        unsafe_allow_html=True
    )

# ════════════════════════════════════════════════════════════════
# APP
# ════════════════════════════════════════════════════════════════
startup()

p  = st.query_params
ep = p.get("endpoint", "")

# Auto-sync
if ep and time.time() - store.last_sync > 300:
    sync()

# ── API endpoints ───────────────────────────────────────────────
if ep == "tests/public":
    pub = [norm(t) for t in store.meta
           if t.get("visibility") == "public" and t.get("is_active", True) is not False]
    api_resp(sorted(pub, key=lambda x: str(x.get("created_at","")), reverse=True))

elif ep == "tests/my":
    uid  = p.get("uid", "")
    mine = [norm(t) for t in store.meta if str(t.get("creator_id","")) == uid]
    api_resp(sorted(mine, key=lambda x: str(x.get("created_at","")), reverse=True))

elif ep == "tests":
    api_resp([norm(t) for t in store.meta])

elif ep.startswith("test/") and ep.endswith("/full"):
    tid  = ep.split("/")[1]
    meta = next((t for t in store.meta if t.get("test_id") == tid), None)
    if not meta:
        api_resp({"error": "Test topilmadi"})
    else:
        qs = store.q_cache.get(tid)
        if not qs:
            msg_id = store.index.get(f"test_{tid}")
            if msg_id:
                full = tg_forward_get(msg_id)
                if full and full.get("questions"):
                    store.q_cache[tid] = full["questions"]
                    qs = full["questions"]
        if qs:
            api_resp({"testData": norm(meta), "questions": qs, "total": len(qs)})
        else:
            api_resp({"error": "Savollar topilmadi"})

elif ep.startswith("test/") and ep.endswith("/meta"):
    tid  = ep.split("/")[1]
    meta = next((t for t in store.meta if t.get("test_id") == tid), None)
    api_resp(norm(meta) if meta else {"error": "Topilmadi"})

elif ep.startswith("test/") and ep.count("/") == 1:
    tid  = ep[5:]
    meta = next((t for t in store.meta if t.get("test_id") == tid), None)
    api_resp(norm(meta) if meta else {"error": "Topilmadi"})

elif ep == "result/save":
    try:
        body = json.loads(p.get("body","{}") or "{}")
    except:
        body = {}
    tid = body.get("testId","")
    pct = float(body.get("score", body.get("percentage", 0)))
    meta = next((t for t in store.meta if t.get("test_id")==tid), None)
    if meta:
        sc = meta.get("solve_count",0)+1
        meta["solve_count"] = sc
        meta["avg_score"]   = round(((meta.get("avg_score",0)*(sc-1))+pct)/sc, 1)
    api_resp({"ok": True})

elif ep.startswith("results/"):
    api_resp([])

elif ep == "admin/stats":
    tests  = store.meta
    active = [t for t in tests if t.get("is_active",True) is not False]
    pub    = [t for t in active if t.get("visibility")=="public"]
    total_solve = sum(t.get("solve_count",0) for t in tests)
    scored = [t for t in tests if t.get("avg_score")]
    avg_s  = round(sum(t["avg_score"] for t in scored)/len(scored)) if scored else 0
    by_cat = {}
    for t in tests:
        cat = t.get("category") or t.get("subject") or "other"
        if cat not in by_cat: by_cat[cat]={"count":0,"solves":0,"avg":[]}
        by_cat[cat]["count"]+=1; by_cat[cat]["solves"]+=t.get("solve_count",0)
        if t.get("avg_score"): by_cat[cat]["avg"].append(t["avg_score"])
    now   = datetime.datetime.utcnow()
    days7 = [(now-datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6,-1,-1)]
    by_day= {d:{"created":0,"solves":0} for d in days7}
    for t in tests:
        d=str(t.get("created_at",""))[:10]
        if d in by_day: by_day[d]["created"]+=1; by_day[d]["solves"]+=t.get("solve_count",0)
    api_resp({
        "totalTests":len(tests),"activeTests":len(active),"pubTests":len(pub),
        "totalSolve":total_solve,"avgScore":avg_s,
        "categories":[{"name":k,"count":v["count"],"solves":v["solves"],
            "avg":round(sum(v["avg"])/len(v["avg"])) if v["avg"] else 0}
            for k,v in by_cat.items()],
        "topTests":[norm(t) for t in sorted(active,key=lambda x:x.get("solve_count",0),reverse=True)[:5]],
        "timeline":[{"date":d,**by_day[d]} for d in days7],
        "lastSync":store.last_sync, "cachedTests":len(store.q_cache),
    })

# ── Dashboard ───────────────────────────────────────────────────
else:
    st.title("📡 TestPro API")
    st.caption("Mustaqil — Bot bilan bog'liq emas")

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Testlar (meta)",  len(store.meta))
    c2.metric("Savollar cached", len(store.q_cache))
    c3.metric("Status", "✅ Tayyor" if store.ready else "⏳ Yuklanmoqda")
    ago = int(time.time()-store.last_sync)
    c4.metric("Oxirgi sync", f"{ago//60}d {ago%60}s" if store.last_sync else "—")

    st.divider()
    col1, col2 = st.columns(2)
    if col1.button("🔄 Qayta yuklash"):
        sync()
        st.rerun()
    if col2.button("🗑 Cache tozalash"):
        store.q_cache.clear()
        st.rerun()

    if not BOT_TOKEN:
        st.error("❌ BOT_TOKEN yo'q")
    if not CHANNEL_ID:
        st.error("❌ STORAGE_CHANNEL_ID yo'q")

    st.markdown("### Endpointlar")
    st.code("""
tests/public          → Ommaviy testlar
tests/my?uid=X        → Mening testlarim
test/{id}/full        → To'liq savollar (RAM dan)
test/{id}/meta        → Meta
result/save           → Natija saqlash
admin/stats           → Statistika
""")
