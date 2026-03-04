# 🎓 QuizBot

Telegram test boti — Streamlit boshqaruv paneli bilan.

## ⚡ Ishga tushirish

### 1. Secrets sozlash

`.streamlit/secrets.toml.example` → `.streamlit/secrets.toml` ga nusxa oling:

```toml
BOT_TOKEN = "your_bot_token_here"
STORAGE_CHANNEL_ID = "-100xxxxxxxxxx"
ADMIN_IDS = "123456789"
```

### 2. O'rnatish va ishga tushirish

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Bot avtomatik background'da ishga tushadi!

---

## ☁️ Streamlit Cloud (GitHub orqali)

1. Bu reponi GitHub'ga push qiling
2. [share.streamlit.io](https://share.streamlit.io) ga kiring
3. Repo → `streamlit_app.py` tanlang
4. **Secrets** bo'limiga `secrets.toml` ni qo'ying
5. Deploy!

> ⚠️ `.streamlit/secrets.toml` ni hech qachon GitHub'ga push qilmang!  
> `.gitignore` da allaqachon qo'shilgan.

---

## 📁 Fayl strukturasi

```
QuizBot/
├── streamlit_app.py        ← Streamlit boshqaruv paneli
├── bot.py                  ← Telegram bot (background)
├── config.py               ← Konfiguratsiya
├── requirements.txt
├── .gitignore
├── .streamlit/
│   ├── config.toml         ← UI sozlamalari
│   └── secrets.toml        ← 🔒 (gitignore'd)
├── handlers/
│   ├── start.py            — /start, yordam
│   ├── tests.py            — katalog + inline test
│   ├── poll_test.py        — private poll test
│   ├── group.py            — guruh test
│   ├── create_test.py      — test yaratish
│   ├── profile.py          — profil, natijalar
│   ├── admin.py            — admin panel
│   └── inline_mode.py      — inline query
├── keyboards/kb.py         — barcha klaviaturalar
├── utils/
│   ├── store.py            — RAM + TG kanal storage
│   ├── scoring.py          — ball hisoblash
│   ├── states.py           — FSM states
│   └── parser.py           — TXT/PDF/DOCX parser
└── samples/                — namuna fayllar
```

## 🤖 Bot imkoniyatlari

| Funksiya | Tavsif |
|----------|--------|
| ▶️ Inline test | A/B/C/D tugmalar, avto-o'tish, tahlil |
| 📊 Poll test | Telegram viktorina, timer, pauza |
| 👥 Guruh test | Inline + Poll rejim, reyting |
| ➕ Test yaratish | TXT/PDF/DOCX, matn, @QuizBot forward |
| 🔍 Inline query | Guruhga test yuborish |
| 👑 Admin panel | Broadcast, bloklash, statistika |
| 💾 TG kanal storage | Restart keyin ham ma'lumot saqlanadi |
