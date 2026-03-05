"""DB — CRUD operatsiyalar: yangi natija/tahlil logikasi"""
import uuid, logging
from datetime import datetime, timezone
from utils import ram_cache as ram

log = logging.getLogger(__name__)
UTC = timezone.utc


# ══ USERS ══════════════════════════════════════════════

def get_user(tg_id):
    return ram.get_user(tg_id)

async def get_or_create_user(tg_id, name, username=None):
    user = ram.get_user(tg_id)
    if user:
        user["last_active"] = str(datetime.now(UTC))
        ram.upsert_user(tg_id, user)
        return user
    user = {
        "telegram_id": tg_id, "name": name, "username": username,
        "role": "user", "is_blocked": False,
        "total_tests": 0, "total_score": 0.0, "avg_score": 0.0,
        "created_at": str(datetime.now(UTC)),
        "last_active": str(datetime.now(UTC)),
    }
    ram.upsert_user(tg_id, user)
    await _flush_users()
    return user

def update_user(tg_id, data):
    user = ram.get_user(tg_id) or {}
    user.update(data)
    user["last_active"] = str(datetime.now(UTC))
    ram.upsert_user(tg_id, user)

def block_user(tg_id, blocked=True):
    update_user(tg_id, {"is_blocked": blocked})

def get_all_users():
    return list(ram.get_users().values())

async def _flush_users():
    from utils import tg_db
    if tg_db.ready():
        await tg_db.save_users(ram.get_users())
        ram.clear_users_dirty()


# ══ TESTS ══════════════════════════════════════════════

def get_test(tid):
    """Meta qaytaradi (savolsiz). Savollar kerak bo'lsa get_test_full() ishlatilsin"""
    return ram.get_test_by_id(tid)

async def get_test_full(tid):
    """
    To'liq test (savollar bilan):
    1. 12 soat RAM cache dan qidiradi
    2. Topilmasa TG kanaldan yuklab oladi va cache qiladi
    """
    # Cache tekshir
    cached = ram.get_cached_questions(tid)
    if cached:
        return cached
    # TG dan yuklab ol
    from utils import tg_db
    if tg_db.ready():
        full = await tg_db.get_test_full(tid)
        if full:
            ram.cache_questions(tid, full)
            return full
    # Eski format: to'liq test RAM da bo'lishi mumkin
    return ram.get_test_by_id(tid)

def get_all_tests():
    return [t for t in ram.get_tests() if t.get("is_active", True)]

def get_public_tests():
    return [t for t in get_all_tests() if t.get("visibility") == "public"]

def get_my_tests(creator_id):
    return [t for t in get_all_tests() if t.get("creator_id") == creator_id]

async def create_test(creator_id, data):
    tid  = str(uuid.uuid4())[:8].upper()
    test = {
        "test_id": tid, "creator_id": creator_id,
        "title":         data.get("title", "Nomsiz"),
        "category":      data.get("category", "Boshqa"),
        "difficulty":    data.get("difficulty", "medium"),
        "visibility":    data.get("visibility", "public"),
        "time_limit":    data.get("time_limit", 0),
        "poll_time":     data.get("poll_time", 30),
        "passing_score": data.get("passing_score", 60),
        "max_attempts":  data.get("max_attempts", 0),
        "questions":     data.get("questions", []),
        "question_count": len(data.get("questions", [])),
        "solve_count": 0, "avg_score": 0.0, "is_active": True,
        "created_at": str(datetime.now(UTC)),
    }
    # RAM ga meta qo'shamiz (savolsiz)
    ram.add_test(test)
    # TG kanalga to'liq testni alohida fayl sifatida saqlaymiz
    from utils import tg_db
    if tg_db.ready():
        await tg_db.save_test_full(test)
    return tid

async def delete_test(tid):
    # RAM meta dan o'chirish
    ram.delete_test_from_ram(tid)
    # TG kanalda is_active = False
    from utils import tg_db
    if tg_db.ready():
        await tg_db.delete_test_tg(tid)


# ══ NATIJALAR ══════════════════════════════════════════

def save_result(user_id, test_id, result):
    """
    Har test uchun:
    - FAQAT OXIRGI natija saqlanadi (tahlil bilan)
    - Statistika (necha marta, o'rtacha, eng yuqori) yurilib boriladi
    """
    rid = ram.save_result(user_id, test_id, result)
    ram.save_analysis(user_id, rid, result.get("detailed_results", []))

    # Test meta statistikasini yangilash
    meta = ram.get_test_meta(test_id)
    if meta:
        sc  = meta.get("solve_count", 0) + 1
        avg = ((meta.get("avg_score", 0) * (sc - 1)) + result.get("percentage", 0)) / sc
        ram.update_test_meta(test_id, {"solve_count": sc, "avg_score": round(avg, 1)})

    # User statistikasi
    user = ram.get_user(user_id)
    if user:
        tt = user.get("total_tests", 0) + 1
        ts = user.get("total_score", 0.0) + result.get("percentage", 0)
        update_user(user_id, {
            "total_tests": tt, "total_score": ts,
            "avg_score": round(ts / tt, 1),
        })
    return rid

def get_user_results(user_id):
    """Har test uchun bitta oxirgi natija (qisqa)"""
    return ram.get_user_results(user_id)

def get_analysis(user_id, result_id):
    """Oxirgi tahlil — result_id = uid_testid"""
    return ram.get_analysis(user_id, result_id)

def get_test_stats_for_user(user_id, test_id):
    """Bitta test bo'yicha to'liq statistika"""
    return ram.get_test_stats_for_user(user_id, test_id)

def get_leaderboard(limit=20):
    users = [u for u in get_all_users() if u.get("total_tests", 0) > 0]
    users.sort(key=lambda x: x.get("avg_score", 0), reverse=True)
    return users[:limit]
