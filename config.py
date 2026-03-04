"""⚙️ KONFIGURATSIYA"""
import os

def _s(key, default=None):
    try:
        import streamlit as st
        if "." in key:
            sec, sub = key.split(".", 1)
            return st.secrets[sec][sub]
        return st.secrets[key]
    except Exception:
        return os.environ.get(key.replace(".", "_").upper(), default)

BOT_TOKEN          = _s("BOT_TOKEN", "")
STORAGE_CHANNEL_ID = int(_s("STORAGE_CHANNEL_ID", "0"))
_raw               = str(_s("ADMIN_IDS", "123456789"))
ADMIN_IDS          = [int(x.strip()) for x in _raw.split(",") if x.strip().isdigit()]

SUBJECTS = [
    "Matematika","Fizika","Kimyo","Biologiya","Tarix",
    "Geografiya","Ingliz tili","Rus tili","Ona tili",
    "Informatika","Adabiyot","Huquq","Iqtisodiyot","Boshqa",
]
DIFFICULTY = {
    "easy":   "🟢 Oson",
    "medium": "🟡 O'rtacha",
    "hard":   "🔴 Qiyin",
    "expert": "⚡ Ekspert",
}
