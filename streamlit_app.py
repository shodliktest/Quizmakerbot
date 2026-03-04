"""🎓 QuizBot — Streamlit boshqaruv paneli"""
import streamlit as st
import time

st.set_page_config(
    page_title="QuizBot Panel",
    page_icon="🎓",
    layout="wide",
)

# ── Bot ishga tushirish ────────────────────────────────────
def _start_bot():
    try:
        import bot as _bot_module
        thread = _bot_module.run_in_background()
        return thread
    except Exception as e:
        st.error(f"❌ Bot ishga tushmadi: {e}")
        return None

if "bot_started" not in st.session_state:
    st.session_state.bot_started = False

if not st.session_state.bot_started:
    thread = _start_bot()
    if thread:
        st.session_state.bot_started = True
        st.session_state.bot_thread = thread

# ═══════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════
with st.sidebar:
    st.title("🎓 QuizBot")
    st.divider()

    # Bot holati
    thread = st.session_state.get("bot_thread")
    if thread and thread.is_alive():
        st.success("🟢 Bot ishlayapti")
    else:
        st.error("🔴 Bot to'xtatilgan")
        if st.button("🔄 Qayta ishga tushirish"):
            st.session_state.bot_started = False
            st.rerun()

    st.divider()
    page = st.radio("📋 Bo'lim", [
        "📊 Dashboard",
        "📋 Testlar",
        "👥 Foydalanuvchilar",
        "🏆 Reyting",
        "⚙️ Sozlamalar",
    ])

# ═══════════════════════════════════════════════════════════
# MA'LUMOTLAR
# ═══════════════════════════════════════════════════════════
def get_data():
    try:
        from utils import store
        return {
            "tests":   store.get_all_tests(),
            "users":   store.get_all_users(),
            "lb":      store.get_leaderboard(20),
            "tg_ok":   store.tg_ready(),
            "sessions": len(store._sessions),
        }
    except:
        return {"tests":[],"users":[],"lb":[],"tg_ok":False,"sessions":0}

# ═══════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    st.title("📊 Dashboard")

    d = get_data()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📋 Testlar",          len(d["tests"]))
    c2.metric("👥 Foydalanuvchilar", len(d["users"]))
    c3.metric("🟢 Faol sessiyalar",  d["sessions"])
    c4.metric("💾 TG Kanal", "✅" if d["tg_ok"] else "❌")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📋 So'nggi testlar")
        if d["tests"]:
            for t in d["tests"][:5]:
                vis = {"public":"🌍","link":"🔗","private":"🔒"}.get(t.get("visibility",""),"")
                qc  = t.get("question_count", len(t.get("questions",[])))
                st.write(f"{vis} **{t.get('title','?')}** — {qc} savol | {t.get('solve_count',0)}x")
        else:
            st.info("Hali testlar yo'q")

    with col2:
        st.subheader("🏆 Top 5 reyting")
        medals = ["🥇","🥈","🥉","4.","5."]
        if d["lb"]:
            for i, r in enumerate(d["lb"][:5]):
                m = medals[i] if i < len(medals) else f"{i+1}."
                st.write(f"{m} **{r['name']}** — {r['avg']}% | {r['total']} ta test")
        else:
            st.info("Hali natijalar yo'q")

    if st.button("🔄 Yangilash"):
        st.rerun()

# ═══════════════════════════════════════════════════════════
# TESTLAR
# ═══════════════════════════════════════════════════════════
elif page == "📋 Testlar":
    st.title("📋 Testlar")

    d     = get_data()
    tests = d["tests"]

    if not tests:
        st.info("📭 Hali testlar yo'q. Botda ➕ Test Yaratish tugmasini bosing.")
    else:
        # Qidiruv
        q = st.text_input("🔍 Qidirish (nom yoki fan)", "")
        if q:
            tests = [t for t in tests
                     if q.lower() in str(t.get("title","")).lower()
                     or q.lower() in str(t.get("category","")).lower()]

        st.write(f"**{len(tests)} ta test**")
        st.divider()

        for t in tests:
            tid  = t.get("test_id","?")
            qc   = t.get("question_count", len(t.get("questions",[])))
            vis  = {"public":"🌍 Ommaviy","link":"🔗 Ssilka","private":"🔒 Shaxsiy"}.get(t.get("visibility",""),"")
            diff = {"easy":"🟢","medium":"🟡","hard":"🔴","expert":"⚡"}.get(t.get("difficulty",""),"")

            with st.expander(f"📝 {t.get('title','Nomsiz')} | {qc} savol | {t.get('solve_count',0)}x"):
                c1,c2,c3 = st.columns(3)
                c1.write(f"🆔 `{tid}`")
                c1.write(f"📁 {t.get('category','')}")
                c2.write(f"{diff} {t.get('difficulty','')}")
                c2.write(f"{vis}")
                c3.write(f"⏱ Poll: {t.get('poll_time',30)}s")
                c3.write(f"🎯 O'tish: {t.get('passing_score',60)}%")

                # O'chirish tugmasi
                if st.button(f"🗑 O'chirish", key=f"del_{tid}"):
                    try:
                        import asyncio
                        from utils import store
                        asyncio.run(store.delete_test(tid))
                        st.success(f"✅ '{t.get('title')}' o'chirildi")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ {e}")

# ═══════════════════════════════════════════════════════════
# FOYDALANUVCHILAR
# ═══════════════════════════════════════════════════════════
elif page == "👥 Foydalanuvchilar":
    st.title("👥 Foydalanuvchilar")

    d     = get_data()
    users = d["users"]

    blocked = [u for u in users if u.get("is_blocked")]
    active  = [u for u in users if not u.get("is_blocked")]

    c1,c2 = st.columns(2)
    c1.metric("✅ Faol",     len(active))
    c2.metric("🚫 Bloklangan", len(blocked))

    st.divider()
    q = st.text_input("🔍 Qidirish (ism yoki @username)", "")
    show = users
    if q:
        show = [u for u in users
                if q.lower() in str(u.get("name","")).lower()
                or q.lower() in str(u.get("username","")).lower()
                or str(u.get("uid","")) == q.strip()]

    for u in show[:50]:
        uid    = u.get("uid","?")
        name   = u.get("name","?")
        uname  = f"@{u.get('username')}" if u.get("username") else "—"
        status = "🚫" if u.get("is_blocked") else "✅"
        avg    = u.get("avg",0)
        total  = u.get("total",0)

        with st.expander(f"{status} {name} | {uname} | {avg}% | {total} test"):
            st.write(f"🆔 `{uid}`")
            st.write(f"📊 O'rtacha: **{avg}%** | Jami: {total} ta")

            from utils import store
            cur = store.get_user(uid)
            if cur:
                is_blocked = cur.get("is_blocked", False)
                btn_label  = "✅ Blokdan chiqarish" if is_blocked else "🚫 Bloklash"
                if st.button(btn_label, key=f"blk_{uid}"):
                    cur["is_blocked"] = not is_blocked
                    store.upsert_user(uid, cur)
                    st.rerun()

# ═══════════════════════════════════════════════════════════
# REYTING
# ═══════════════════════════════════════════════════════════
elif page == "🏆 Reyting":
    st.title("🏆 Global Reyting")

    d      = get_data()
    medals = ["🥇","🥈","🥉"] + [f"{i}." for i in range(4,21)]

    if not d["lb"]:
        st.info("📭 Hali natijalar yo'q.")
    else:
        import pandas as pd
        rows = []
        for i, r in enumerate(d["lb"]):
            rows.append({
                "O'rin":  f"{medals[i] if i<len(medals) else i+1}",
                "Ism":    r["name"],
                "O'rtacha (%)": r["avg"],
                "Testlar": r["total"],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if st.button("🔄 Yangilash"):
        st.rerun()

# ═══════════════════════════════════════════════════════════
# SOZLAMALAR
# ═══════════════════════════════════════════════════════════
elif page == "⚙️ Sozlamalar":
    st.title("⚙️ Sozlamalar")

    st.subheader("💾 Kanalga saqlash")
    c1,c2 = st.columns(2)
    with c1:
        if st.button("👥 Userlarni saqlash"):
            try:
                import asyncio
                from utils import store
                ok = asyncio.run(store.save_users_tg())
                st.success("✅ Saqlandi") if ok else st.error("❌ Kanal ulanmagan")
            except Exception as e:
                st.error(f"❌ {e}")
    with c2:
        if st.button("📊 Natijalarni saqlash"):
            try:
                import asyncio
                from utils import store
                ok = asyncio.run(store.save_results_tg())
                st.success("✅ Saqlandi") if ok else st.error("❌ Kanal ulanmagan")
            except Exception as e:
                st.error(f"❌ {e}")

    st.divider()
    st.subheader("ℹ️ Tizim ma'lumoti")

    try:
        from utils import store
        from config import BOT_TOKEN, STORAGE_CHANNEL_ID, ADMIN_IDS
        st.code(f"""
Bot token    : {'✅ bor' if BOT_TOKEN else '❌ yo\'q'}
Storage kanal: {'✅ ' + str(STORAGE_CHANNEL_ID) if STORAGE_CHANNEL_ID else '❌ sozlanmagan'}
Admin IDs    : {ADMIN_IDS}
TG ulanish   : {'✅' if store.tg_ready() else '❌'}
        """)
    except Exception as e:
        st.error(f"Config o'qishda xato: {e}")
