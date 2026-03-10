"""
TestPro — Streamlit API (Mustaqil, Dashboard bilan)
====================================================
Bot bilan bog'liq EMAS.
Startup da TG kanaldan barcha testlarni o'zi yuklab oladi.

.streamlit/secrets.toml:
  BOT_TOKEN          = "123:ABC..."
  STORAGE_CHANNEL_ID = "-1001234567890"
  ADMIN_IDS          = "123456789"
  ADMIN_PASSWORD     = "admin123"
"""

import streamlit as st
import json, time, os, sys, datetime, math, uuid
import urllib.request, urllib.error

st.set_page_config(
    page_title="TestPro API",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""<style>
[data-testid="stAppViewContainer"] { background: #f8fafc; }
.card {
    background: white; border-radius: 14px; padding: 1.1rem 1.3rem;
    box-shadow: 0 1px 4px rgba(0,0,0,.07); margin-bottom: .6rem;
}
.stat-card {
    background: white; border-radius: 14px; padding: 1rem 1.1rem;
    box-shadow: 0 1px 4px rgba(0,0,0,.07); text-align: center;
}
.stat-val { font-size: 2rem; font-weight: 800; }
.stat-lbl { font-size: .72rem; color: #6b7280; margin-top: .1rem; }
.ram-track { height: 12px; border-radius: 99px; background: #e5e7eb; overflow: hidden; margin: .4rem 0; }
.ram-fill  { height: 100%; border-radius: 99px; transition: width .5s; }
.badge { display:inline-block; padding:.1rem .45rem; border-radius:99px; font-size:.68rem; font-weight:700; }
.ok  { color:#059669 } .err { color:#dc2626 }
.test-row {
    background: white; border-radius: 10px; padding: .65rem 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,.05); margin-bottom: .35rem;
    border-left: 4px solid #6366f1;
}
.test-row.priv { border-left-color: #f59e0b; }
.test-row.web  { border-left-color: #10b981; }
</style>""", unsafe_allow_html=True)

# ── Secrets ─────────────────────────────────────────────────────
BOT_TOKEN  = st.secrets.get("BOT_TOKEN",          os.getenv("BOT_TOKEN",""))
CHANNEL_ID = st.secrets.get("STORAGE_CHANNEL_ID", os.getenv("STORAGE_CHANNEL_ID",""))
ADMIN_IDS  = [int(x) for x in str(st.secrets.get("ADMIN_IDS","")).split(",") if x.strip().isdigit()]
ADMIN_PASS = st.secrets.get("ADMIN_PASSWORD", "admin123")
TG         = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ════════════════════════════════════════════════════════════════
# TG helpers
# ════════════════════════════════════════════════════════════════
def tg_post(method, data, timeout=15):
    url  = f"{TG}/{method}"
    body = json.dumps(data).encode()
    req  = urllib.request.Request(url, body, {"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tg_get_file(file_id, timeout=20):
    res = tg_post("getFile", {"file_id": file_id})
    if not res.get("ok"): return None
    path = res["result"]["file_path"]
    try:
        with urllib.request.urlopen(
            f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}", timeout=timeout
        ) as r:
            return json.loads(r.read())
    except: return None

def tg_forward_get(msg_id):
    """Kanaldan fayl yuklab olish"""
    fwd = tg_post("forwardMessage", {
        "chat_id": CHANNEL_ID, "from_chat_id": CHANNEL_ID, "message_id": int(msg_id)
    })
    if not fwd.get("ok"): return None
    doc    = fwd["result"].get("document")
    new_id = fwd["result"]["message_id"]
    tg_post("deleteMessage", {"chat_id": CHANNEL_ID, "message_id": new_id})
    return tg_get_file(doc["file_id"]) if doc else None

def tg_send_doc(filename, data, caption):
    """Kanalga JSON fayl yuborish — multipart/form-data"""
    content  = json.dumps(data, ensure_ascii=False, indent=2).encode()
    boundary = f"TBnd{int(time.time()*1000)}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{CHANNEL_ID}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        f"Content-Type: application/json\r\n\r\n"
    ).encode() + content + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="disable_notification"\r\n\r\ntrue\r\n'
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        f"{TG}/sendDocument", body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ════════════════════════════════════════════════════════════════
# RAM Store
# ════════════════════════════════════════════════════════════════
class Store:
    index:      dict  = {}
    meta:       list  = []       # test meta ro'yxati (savolsiz)
    q_cache:    dict  = {}       # {test_id: [questions]}
    errors:     list  = []       # [(timestamp, msg)]
    last_sync:  float = 0
    ready:      bool  = False

store = Store()

def norm(t: dict) -> dict:
    out = {k:v for k,v in t.items() if k!="questions"}
    out["id"]           = out.get("id")       or out.get("test_id")
    out["authorId"]     = out.get("authorId") or str(out.get("creator_id",""))
    out["subject"]      = out.get("subject")  or out.get("category") or "other"
    out["creator_name"] = out.get("creator_name") or out.get("authorName") or ""
    return out

def save_index():
    """Yangilangan indexni kanalga yuboradi va pin qiladi"""
    idx = dict(store.index)
    idx["tests_meta"] = store.meta
    d = tg_send_doc("index.json", idx, "📋 INDEX | " + datetime.datetime.utcnow().isoformat()[:16])
    if d.get("ok"):
        tg_post("pinChatMessage", {
            "chat_id": CHANNEL_ID,
            "message_id": d["result"]["message_id"],
            "disable_notification": True
        })
        store.index = idx
    return d.get("ok", False)

# ════════════════════════════════════════════════════════════════
# Startup — TG dan yuklab olish
# ════════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def startup():
    if not BOT_TOKEN or not CHANNEL_ID:
        store.errors.append((time.time(), "BOT_TOKEN yoki CHANNEL_ID yo'q"))
        return False
    try:
        chat = tg_post("getChat", {"chat_id": CHANNEL_ID})
        pin  = chat.get("result",{}).get("pinned_message")
        if not pin or not pin.get("document"):
            store.errors.append((time.time(), "Pinned message topilmadi"))
            return False
        index = tg_get_file(pin["document"]["file_id"])
        if not index or "tests_meta" not in index:
            store.errors.append((time.time(), "Index yuklanmadi"))
            return False
        store.index = index
        store.meta  = index.get("tests_meta", [])
        total = len(store.meta)
        prog  = st.progress(0, text=f"⬇️  0/{total} yuklanmoqda...")
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
                except Exception as e:
                    store.errors.append((time.time(), f"{tid}: {e}"))
            prog.progress((i+1)/max(total,1),
                text=f"⬇️  {i+1}/{total}: {meta.get('title','?')[:35]}")
        prog.empty()
        store.last_sync = time.time()
        store.ready     = True
        return True
    except Exception as e:
        store.errors.append((time.time(), f"Startup: {e}"))
        return False

def do_sync():
    if not BOT_TOKEN or not CHANNEL_ID: return
    try:
        chat = tg_post("getChat", {"chat_id": CHANNEL_ID})
        pin  = chat.get("result",{}).get("pinned_message")
        if not pin or not pin.get("document"): return
        index = tg_get_file(pin["document"]["file_id"])
        if not index: return
        store.index = index
        for meta in index.get("tests_meta", []):
            tid = meta.get("test_id")
            if not tid: continue
            ex = next((t for t in store.meta if t["test_id"]==tid), None)
            if ex:
                ex.update({k:v for k,v in meta.items() if k!="questions"})
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
                    except Exception as e:
                        store.errors.append((time.time(), f"sync {tid}: {e}"))
        store.last_sync = time.time()
    except Exception as e:
        store.errors.append((time.time(), f"Sync: {e}"))

# ════════════════════════════════════════════════════════════════
# RAM o'lchash
# ════════════════════════════════════════════════════════════════
def get_ram():
    info = {"total":0,"used":0,"avail":0,"pct":0,"src":"?"}
    try:
        import psutil
        vm = psutil.virtual_memory()
        info.update(total=vm.total, used=vm.used,
                    avail=vm.available, pct=round(vm.percent,1), src="psutil")
    except ImportError:
        # /proc/meminfo (Linux)
        try:
            with open("/proc/meminfo") as f:
                lines = {l.split(":")[0].strip(): int(l.split(":")[1].strip().split()[0])
                         for l in f if ":" in l}
            total = lines.get("MemTotal",0)*1024
            avail = lines.get("MemAvailable",0)*1024
            used  = total-avail
            info.update(total=total, used=used, avail=avail,
                        pct=round(used/max(total,1)*100,1), src="/proc/meminfo")
        except:
            info["src"] = "unavailable"
    return info

def get_pkg_sizes():
    """Importlangan kutubxonalar xotiradan foydalanishi"""
    sizes = {}
    for name, mod in list(sys.modules.items()):
        if name.startswith("_") or "." in name: continue
        try:
            f = getattr(mod,"__file__",None)
            if f and os.path.isfile(f):
                s = os.path.getsize(f)
                if s > 10_000:
                    sizes[name] = s
        except: pass
    return dict(sorted(sizes.items(), key=lambda x:-x[1])[:12])

def store_bytes():
    m = len(json.dumps(store.meta,ensure_ascii=False).encode())
    q = len(json.dumps(store.q_cache,ensure_ascii=False).encode())
    return m, q

# ════════════════════════════════════════════════════════════════
# JSON API javob
# ════════════════════════════════════════════════════════════════
def api_resp(data):
    """
    JSON javob — proxy.js uchun 3 xil usulda chiqaradi:
    1. <script type="application/json" id="__api__"> — SSR da ishlaydi
    2. <div id="api-raw"> — fallback
    3. st.json() — dashboard da ko'rish uchun
    """
    raw = json.dumps(data, ensure_ascii=False)
    # 1. script tag — SSR safe, proxy regex bilan oladi
    st.markdown(
        f'<script type="application/json" id="__api__">{raw}</script>',
        unsafe_allow_html=True
    )
    # 2. hidden div — fallback
    st.markdown(
        f'<div id="api-raw" style="display:none">{raw}</div>',
        unsafe_allow_html=True
    )
    # 3. Visual viewer
    st.json(data)

# ════════════════════════════════════════════════════════════════
# Router
# ════════════════════════════════════════════════════════════════
startup()

p  = st.query_params
ep = p.get("endpoint","")

if ep and time.time()-store.last_sync > 300:
    do_sync()

# ── tests/public ─────────────────────────────────────────────────
if ep == "tests/public":
    pub = [norm(t) for t in store.meta
           if t.get("visibility")=="public" and t.get("is_active",True) is not False]
    api_resp(sorted(pub, key=lambda x:str(x.get("created_at","")), reverse=True))

# ── tests/my ─────────────────────────────────────────────────────
elif ep == "tests/my":
    uid  = p.get("uid","")
    mine = [norm(t) for t in store.meta if str(t.get("creator_id",""))==uid]
    api_resp(sorted(mine, key=lambda x:str(x.get("created_at","")), reverse=True))

# ── tests (admin) ────────────────────────────────────────────────
elif ep == "tests":
    api_resp([norm(t) for t in store.meta])

# ── test/{id}/full ───────────────────────────────────────────────
elif ep.startswith("test/") and ep.endswith("/full"):
    tid  = ep.split("/")[1]
    meta = next((t for t in store.meta if t.get("test_id")==tid), None)
    if not meta:
        api_resp({"error":"Test topilmadi"})
    else:
        qs = store.q_cache.get(tid)
        if not qs:
            msg_id = store.index.get(f"test_{tid}")
            if msg_id:
                full = tg_forward_get(msg_id)
                if full and full.get("questions"):
                    store.q_cache[tid] = full["questions"]
                    qs = full["questions"]
        api_resp({"testData":norm(meta),"questions":qs or [],"total":len(qs or [])})

# ── test/{id}/meta ───────────────────────────────────────────────
elif ep.startswith("test/") and ep.endswith("/meta"):
    tid  = ep.split("/")[1]
    meta = next((t for t in store.meta if t.get("test_id")==tid), None)
    api_resp(norm(meta) if meta else {"error":"Topilmadi"})

# ── test/{id} bare ───────────────────────────────────────────────
elif ep.startswith("test/") and ep.count("/")==1:
    meta = next((t for t in store.meta if t.get("test_id")==ep[5:]), None)
    api_resp(norm(meta) if meta else {"error":"Topilmadi"})

# ── test/create ──────────────────────────────────────────────────
elif ep == "test/create":
    try: body = json.loads(p.get("body","{}") or "{}")
    except: body = {}
    tid = str(uuid.uuid4())[:8].upper()
    test_doc = {
        "test_id": tid,
        "creator_id": int(body.get("authorId",0)) if str(body.get("authorId","")).isdigit() else 0,
        "creator_name": body.get("authorName",""),
        "title":         body.get("title","Nomsiz"),
        "description":   body.get("description",""),
        "category":      body.get("category") or body.get("subject") or "Boshqa",
        "visibility":    body.get("visibility","public"),
        "difficulty":    body.get("difficulty","medium"),
        "time_limit":    int(body.get("timeLimit",0) or 0),
        "passing_score": int(body.get("passScore",60) or 60),
        "max_attempts":  int(body.get("max_attempts",0) or 0),
        "questions":     body.get("questions",[]),
        "question_count":len(body.get("questions",[])),
        "solve_count":   0,
        "avg_score":     0.0,
        "is_active":     True,
        "is_paused":     False,
        "created_at":    datetime.datetime.utcnow().isoformat(),
        "source":        "web",
        "accessCode":    body.get("accessCode",""),
    }
    # Kanalga yuborish
    d = tg_send_doc(f"test_{tid}.json", test_doc,
                    f"📝 TEST | {test_doc['title']} | {tid}")
    if not d.get("ok"):
        api_resp({"error": d.get("error","Kanalga yuborishda xato")})
    else:
        msg_id = d["result"]["message_id"]
        # Meta saqlash (savolsiz)
        meta = {k:v for k,v in test_doc.items() if k!="questions"}
        store.meta.insert(0, meta)
        if test_doc["questions"]:
            store.q_cache[tid] = test_doc["questions"]
        # Index yangilash
        store.index[f"test_{tid}"] = msg_id
        save_index()
        api_resp({"ok":True,"id":tid,"test_id":tid,"accessCode":test_doc["accessCode"]})

# ── test/{id}/questions GET ──────────────────────────────────────
elif ep.startswith("test/") and ep.endswith("/questions"):
    tid = ep.split("/")[1]
    qs  = store.q_cache.get(tid,[])
    if not qs:
        msg_id = store.index.get(f"test_{tid}")
        if msg_id:
            full = tg_forward_get(msg_id)
            if full and full.get("questions"):
                store.q_cache[tid] = full["questions"]
                qs = full["questions"]
    api_resp(qs)

# ── test/{id}/update ─────────────────────────────────────────────
elif ep.startswith("test/") and ep.endswith("/update"):
    try: body = json.loads(p.get("body","{}") or "{}")
    except: body = {}
    tid  = ep.split("/")[1]
    meta = next((t for t in store.meta if t.get("test_id")==tid), None)
    if meta:
        for k in ["title","category","visibility","time_limit","passing_score","is_paused","description"]:
            if k in body: meta[k] = body[k]
        save_index()
    api_resp({"ok":True})

# ── test/{id}/delete ─────────────────────────────────────────────
elif ep.startswith("test/") and ep.endswith("/delete"):
    tid = ep.split("/")[1]
    store.meta = [t for t in store.meta if t.get("test_id")!=tid]
    store.q_cache.pop(tid, None)
    store.index.pop(f"test_{tid}", None)
    save_index()
    api_resp({"ok":True})

# ── result/save ──────────────────────────────────────────────────
elif ep == "result/save":
    try: body = json.loads(p.get("body","{}") or "{}")
    except: body = {}
    tid = body.get("testId","")
    pct = float(body.get("score", body.get("percentage", 0)))
    meta = next((t for t in store.meta if t.get("test_id")==tid), None)
    if meta:
        sc = meta.get("solve_count",0)+1
        meta["solve_count"] = sc
        meta["avg_score"]   = round(((meta.get("avg_score",0)*(sc-1))+pct)/sc, 1)
    # Natijani kanalga yuborish
    rid = f"{body.get('userId','?')}_{tid}_{int(time.time())}"
    tg_send_doc(f"result_{rid}.json", {**body, "result_id":rid,
        "completed_at": datetime.datetime.utcnow().isoformat()},
        f"📊 RESULT | {body.get('userName','')} | {tid} | {round(pct)}%")
    api_resp({"ok":True,"result_id":rid})

# ── results/{uid} ────────────────────────────────────────────────
elif ep.startswith("results/"):
    api_resp([])

# ── admin/stats ──────────────────────────────────────────────────
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
        "topTests":[norm(t) for t in sorted(active,
            key=lambda x:x.get("solve_count",0),reverse=True)[:5]],
        "timeline":[{"date":d,**by_day[d]} for d in days7],
        "lastSync":store.last_sync,"cachedTests":len(store.q_cache),
    })

# ── admin/test/{id}/pause ────────────────────────────────────────
elif ep.startswith("admin/test/") and ep.endswith("/pause"):
    tid  = ep.split("/")[2]
    meta = next((t for t in store.meta if t.get("test_id")==tid), None)
    if meta:
        meta["is_paused"] = not meta.get("is_paused",False)
        save_index()
    api_resp({"ok":True,"is_paused":meta.get("is_paused",False) if meta else False})

# ── admin/test/{id}/delete ───────────────────────────────────────
elif ep.startswith("admin/test/") and ep.endswith("/delete"):
    tid = ep.split("/")[2]
    store.meta = [t for t in store.meta if t.get("test_id")!=tid]
    store.q_cache.pop(tid,None)
    store.index.pop(f"test_{tid}",None)
    save_index()
    api_resp({"ok":True})

# ════════════════════════════════════════════════════════════════
# DASHBOARD
# ════════════════════════════════════════════════════════════════
else:
    ram     = get_ram()
    mb      = lambda b: round(b/1024**2, 1)
    gb      = lambda b: round(b/1024**3, 2)
    meta_b, q_b = store_bytes()
    data_mb = mb(meta_b + q_b)

    # ── Header ────────────────────────────────────────────────
    h1, h2 = st.columns([5,1])
    h1.markdown("## 📡 TestPro API Dashboard")
    ago = int(time.time()-store.last_sync) if store.last_sync else 0
    h1.caption(
        f"{'✅ Tayyor' if store.ready else '⏳ Yuklanmoqda...'} · "
        f"Sync: {ago//60}d {ago%60}s oldin · "
        f"Python {sys.version[:6]}"
    )
    if h2.button("🔄 Sync", use_container_width=True, type="primary"):
        do_sync(); st.rerun()

    st.divider()

    # ── RAM kartochkalar ──────────────────────────────────────
    st.markdown("#### 💾 RAM holati")

    total_mb = mb(ram["total"])
    used_mb  = mb(ram["used"])
    avail_mb = mb(ram["avail"])
    pct      = ram["pct"]
    ram_color = "#10b981" if pct<60 else "#f59e0b" if pct<80 else "#ef4444"
    ram_src   = ram["src"]

    rc1,rc2,rc3,rc4 = st.columns(4)
    for col, val, lbl, color in [
        (rc1, f"{total_mb} MB" if total_mb<1900 else f"{gb(ram['total'])} GB",
              f"Jami RAM ({ram_src})", "#6366f1"),
        (rc2, f"{used_mb} MB", f"Ishlatilgan ({pct}%)", ram_color),
        (rc3, f"{avail_mb} MB", "Bo'sh",                "#059669"),
        (rc4, f"{data_mb} MB", "Ma'lumotlar (RAM)",      "#7c3aed"),
    ]:
        col.markdown(f"""
        <div class="stat-card">
          <div class="stat-val" style="color:{color}">{val}</div>
          <div class="stat-lbl">{lbl}</div>
        </div>""", unsafe_allow_html=True)

    # Progress bar
    st.markdown(f"""
    <div style="margin:.7rem 0 .3rem">
      <div style="display:flex;justify-content:space-between;font-size:.73rem;color:#6b7280;margin-bottom:.3rem">
        <span>RAM bandligi</span>
        <span>{used_mb} / {total_mb} MB</span>
      </div>
      <div class="ram-track">
        <div class="ram-fill" style="width:{pct}%;background:{ram_color}"></div>
      </div>
      <div style="display:flex;gap:1.5rem;font-size:.7rem;color:#9ca3af;margin-top:.3rem">
        <span>🗂 Meta: {mb(meta_b)} MB ({len(store.meta)} test)</span>
        <span>📝 Savollar: {mb(q_b)} MB ({len(store.q_cache)} test cached,
              {sum(len(v) for v in store.q_cache.values())} savol)</span>
        <span>📌 Index: {mb(len(json.dumps(store.index).encode()))} MB</span>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── Kutubxonalar ──────────────────────────────────────────
    with st.expander("📦 Kutubxonalar (.py fayl hajmi, Top 12)", expanded=False):
        pkgs = get_pkg_sizes()
        if pkgs:
            pkg_cols = st.columns(4)
            for i,(name,size) in enumerate(pkgs.items()):
                pkg_cols[i%4].metric(name, f"{round(size/1024)} KB")
        else:
            st.caption("Kutubxona ma'lumoti topilmadi")

    st.divider()

    # ── Asosiy statistika ─────────────────────────────────────
    st.markdown("#### 📊 Statistika")
    tests      = store.meta
    pub_tests  = [t for t in tests if t.get("visibility")=="public"]
    priv_tests = [t for t in tests if t.get("visibility")=="private"]
    web_tests  = [t for t in tests if t.get("source")=="web"]
    bot_tests  = [t for t in tests if t.get("source","bot")=="bot"]
    total_solve= sum(t.get("solve_count",0) for t in tests)
    scored_    = [t for t in tests if t.get("avg_score")]
    avg_score_ = round(sum(t["avg_score"] for t in scored_)/len(scored_)) if scored_ else 0

    sc1,sc2,sc3,sc4,sc5,sc6 = st.columns(6)
    for col,val,lbl,color in [
        (sc1, len(tests),      "Jami testlar",    "#6366f1"),
        (sc2, len(pub_tests),  "Ommaviy",          "#10b981"),
        (sc3, len(priv_tests), "Yopiq",            "#f59e0b"),
        (sc4, len(web_tests),  "Saytdan",          "#8b5cf6"),
        (sc5, total_solve,     "Yechilgan",         "#3b82f6"),
        (sc6, f"{avg_score_}%","O'rtacha ball",    "#ec4899"),
    ]:
        col.markdown(f"""
        <div class="stat-card">
          <div class="stat-val" style="color:{color};font-size:1.6rem">{val}</div>
          <div class="stat-lbl">{lbl}</div>
        </div>""", unsafe_allow_html=True)

    st.divider()

    # ── Testlar ro'yxati ──────────────────────────────────────
    st.markdown("#### 📋 Testlar ro'yxati")

    f1,f2,f3 = st.columns([3,1,1])
    search = f1.text_input("🔍", placeholder="Qidirish (nomi yoki ID)...",
                           label_visibility="collapsed")
    vis_f  = f2.selectbox("Ko'rinish", ["Barchasi","public","private","link"],
                          label_visibility="collapsed")
    src_f  = f3.selectbox("Manba", ["Barchasi","web","bot"],
                          label_visibility="collapsed")

    filtered = tests
    if search:
        s = search.lower()
        filtered = [t for t in filtered
                    if s in t.get("title","").lower() or s in t.get("test_id","").lower()]
    if vis_f != "Barchasi":
        filtered = [t for t in filtered if t.get("visibility")==vis_f]
    if src_f != "Barchasi":
        filtered = [t for t in filtered if t.get("source","bot")==src_f]

    st.caption(f"{len(filtered)} / {len(tests)} test ko'rsatilmoqda")

    # Sarlavha
    hr1,hr2,hr3,hr4,hr5,hr6 = st.columns([3,1,1,1,1,1])
    for col,lbl in [(hr1,"Nomi"),(hr2,"ID"),(hr3,"Ko'rinish"),
                    (hr4,"Savol"),(hr5,"Yechilgan"),(hr6,"Cached")]:
        col.markdown(f"<span style='font-size:.72rem;color:#9ca3af;font-weight:700'>{lbl}</span>",
                     unsafe_allow_html=True)

    for t in filtered[:100]:
        tid     = t.get("test_id","")
        title   = t.get("title","?")
        vis     = t.get("visibility","public")
        src     = t.get("source","bot")
        q_count = t.get("question_count",0) or len(store.q_cache.get(tid,[]))
        solves  = t.get("solve_count",0)
        avg     = t.get("avg_score",0)
        cached  = tid in store.q_cache
        paused  = t.get("is_paused",False)

        vis_color = {"public":"#10b981","private":"#f59e0b","link":"#6366f1"}.get(vis,"#6b7280")
        src_color = "#8b5cf6" if src=="web" else "#f97316"

        c1,c2,c3,c4,c5,c6 = st.columns([3,1,1,1,1,1])
        c1.markdown(
            f"{'⏸ ' if paused else ''}"
            f"**{title[:40]}**"
            f"<span style='font-size:.68rem;color:{src_color};margin-left:.4rem'>[{src}]</span>",
            unsafe_allow_html=True)
        c2.markdown(f"<code style='font-size:.72rem'>{tid}</code>", unsafe_allow_html=True)
        c3.markdown(
            f"<span class='badge' style='background:{vis_color}22;color:{vis_color}'>"
            f"{vis}</span>", unsafe_allow_html=True)
        c4.markdown(f"<span style='font-size:.85rem'>{q_count}</span>", unsafe_allow_html=True)
        c5.markdown(f"<span style='font-size:.85rem'>{solves}x {'·'+str(avg)+'%' if avg else ''}</span>",
                    unsafe_allow_html=True)
        c6.markdown("✅" if cached else "⬜", unsafe_allow_html=True)

    if len(filtered) > 100:
        st.caption(f"... yana {len(filtered)-100} ta test (qidiruv orqali toping)")

    st.divider()

    # ── Xatoliklar ────────────────────────────────────────────
    if store.errors:
        with st.expander(f"⚠️  Xatoliklar — {len(store.errors)} ta", expanded=False):
            for ts,msg in list(reversed(store.errors))[:20]:
                t_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
                st.markdown(
                    f"<span style='color:#ef4444;font-size:.78rem'>[{t_str}] {msg}</span>",
                    unsafe_allow_html=True)
        if st.button("🗑 Xatolarni tozalash"):
            store.errors.clear(); st.rerun()

    # ── Holat va tugmalar ─────────────────────────────────────
    st.markdown("#### ⚙️ Tizim holati")
    sc1,sc2,sc3 = st.columns(3)
    sc1.markdown(f"""
    **BOT_TOKEN:** {'<span class="ok">✅</span>' if BOT_TOKEN else '<span class="err">❌ yo\'q</span>'}<br>
    **CHANNEL_ID:** {'<span class="ok">✅</span>' if CHANNEL_ID else '<span class="err">❌ yo\'q</span>'}<br>
    **Store ready:** {'<span class="ok">✅</span>' if store.ready else '<span class="err">❌</span>'}
    """, unsafe_allow_html=True)
    sync_str = (datetime.datetime.fromtimestamp(store.last_sync).strftime("%d-%m %H:%M:%S")
                if store.last_sync else "—")
    sc2.markdown(f"""
    **Oxirgi sync:** {sync_str}<br>
    **Cached testlar:** {len(store.q_cache)}<br>
    **Jami savollar:** {sum(len(v) for v in store.q_cache.values())}
    """)
    sc3.markdown(f"""
    **Xatoliklar:** {len(store.errors)}<br>
    **Python:** {sys.version[:6]}<br>
    **Uptime:** {ago//3600}s {(ago%3600)//60}d
    """)

    b1,b2,b3 = st.columns(3)
    if b1.button("🔄 Qayta yuklash (sync)", use_container_width=True):
        do_sync(); st.rerun()
    if b2.button("🗑 Savol cache tozalash", use_container_width=True):
        store.q_cache.clear(); st.rerun()
    if b3.button("🔁 To'liq restart", use_container_width=True, type="secondary"):
        st.cache_resource.clear(); st.rerun()
