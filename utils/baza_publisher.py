"""
📦 BAZA PUBLISHER
=================
Har yangi test yaratilganda Baza Guruhiga avtomatik e'lon qilish.

Jarayon:
  1. Test yaratildi (bot/sayt/fayl/quiz forward — qayerdan bo'lmasin)
  2. Savollar → DOCX formatida fayl yaratiladi
  3. Guruhga DOCX yuboriladi
  4. Faylga reply: test kartasi + Ulashish tugmasi
"""
import io
import logging
import os
import re
import tempfile

log = logging.getLogger(__name__)

LETTERS = list("ABCDEFGH")


# ═══════════════════════════════════════════════════════════════
# DOCX YARATISH
# ═══════════════════════════════════════════════════════════════

def _make_docx(questions: list, title: str = "", tid: str = "",
               category: str = "", creator_name: str = "") -> bytes:
    """
    Savollardan DOCX fayl yaratadi.
    Format:
        1. Savol matni
        A) variant
        *B) to'g'ri javob   ← yulduzcha
        Izoh: ...
    """
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        return _make_txt(questions, title, tid, creator_name).encode("utf-8")

    doc = Document()

    h = doc.add_heading(title or "Test", level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER

    meta_lines = []
    if tid:          meta_lines.append(f"🆔 Kod: {tid}")
    if category:     meta_lines.append(f"📁 Fan: {category}")
    if creator_name: meta_lines.append(f"👤 Yaratuvchi: {creator_name}")
    meta_lines.append(f"📋 Savollar soni: {len(questions)} ta")

    meta_p = doc.add_paragraph("\n".join(meta_lines))
    meta_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in meta_p.runs:
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    doc.add_paragraph("─" * 40)

    for i, q in enumerate(questions, 1):
        qt   = q.get("question") or q.get("text") or q.get("q") or ""
        opts = q.get("options", [])
        expl = q.get("explanation", "") or ""

        correct_idx = _resolve_correct_idx(q, opts)

        qp = doc.add_paragraph()
        qr = qp.add_run(f"{i}. {qt}")
        qr.bold = True
        qr.font.size = Pt(11)

        for j, opt in enumerate(opts):
            clean = re.sub(r'^[A-H]\s*[).]\s*', '', str(opt)).strip()
            lbl   = LETTERS[j] if j < len(LETTERS) else str(j)
            is_ok = (j == correct_idx)

            op = doc.add_paragraph()
            prefix = "*" if is_ok else " "
            or_ = op.add_run(f"  {prefix}{lbl}) {clean}")
            or_.font.size = Pt(10.5)
            if is_ok:
                or_.bold = True
                or_.font.color.rgb = RGBColor(0x00, 0x80, 0x00)

        if expl:
            ep = doc.add_paragraph()
            er = ep.add_run(f"  💡 Izoh: {expl}")
            er.italic = True
            er.font.size = Pt(9.5)
            er.font.color.rgb = RGBColor(0x44, 0x44, 0x88)

        doc.add_paragraph()

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_txt(questions: list, title: str = "", tid: str = "",
              creator_name: str = "") -> str:
    """DOCX bo'lmasa TXT fallback"""
    lines = []
    if title:
        lines.append(f"📝 {title}")
    if tid:
        lines.append(f"🆔 {tid}")
    if creator_name:
        lines.append(f"👤 {creator_name}")
    lines.append(f"📋 {len(questions)} ta savol")
    lines.append("=" * 32)
    lines.append("")

    for i, q in enumerate(questions, 1):
        qt   = q.get("question") or q.get("text") or q.get("q") or ""
        opts = q.get("options", [])
        expl = q.get("explanation", "") or ""
        correct_idx = _resolve_correct_idx(q, opts)

        lines.append(f"{i}. {qt}")
        for j, opt in enumerate(opts):
            clean = re.sub(r'^[A-H]\s*[).]\s*', '', str(opt)).strip()
            lbl   = LETTERS[j] if j < len(LETTERS) else str(j)
            prefix = "*" if j == correct_idx else ""
            lines.append(f"{prefix}{lbl}) {clean}")
        if expl:
            lines.append(f"Izoh: {expl}")
        lines.append("")

    return "\n".join(lines)


def _resolve_correct_idx(q: dict, opts: list) -> int:
    """To'g'ri javob indeksini aniqlash"""
    corr = q.get("correct", "")
    if isinstance(corr, int):
        return corr

    ci = q.get("correct_index")
    if isinstance(ci, int):
        return ci

    if isinstance(corr, str):
        m = re.match(r'^([A-H])\s*[).]', corr.strip(), re.IGNORECASE)
        if m:
            return ord(m.group(1).upper()) - 65

        corr_clean = re.sub(r'^[A-H]\s*[).]\s*', '', corr).strip()
        for j, opt in enumerate(opts):
            opt_clean = re.sub(r'^[A-H]\s*[).]\s*', '', str(opt)).strip()
            if opt_clean == corr_clean or corr_clean in opt_clean or opt_clean in corr_clean:
                return j
    return 0


# ═══════════════════════════════════════════════════════════════
# ASOSIY FUNKSIYA
# ═══════════════════════════════════════════════════════════════

async def publish_to_baza(
    bot,
    tid: str,
    title: str,
    questions: list,
    creator_id: int,
    creator_name: str = "",
    bot_username: str = "",
    category: str = "",
    difficulty: str = "medium",
    passing_score: int = 60,
):
    """
    Baza Guruhiga e'lon qilish:
      1. DOCX fayl yuborish
      2. Faylga reply — test kartasi + Ulashish

    MUHIM: "Web test" va "Quiz Poll" tugmalari bot-deep-link orqali
    ishlaydi (?start=webtest_TID / ?start=poll_TID). Guruh xabarida
    web_app tugmasi ishlamaydi (Telegram cheklovi) — shuning uchun
    bosilganda avtomatik bot shaxsiy chatiga o'tkaziladi, u yerda
    bot darhol Mini App / Poll tugmasini taqdim etadi.
    """
    try:
        from config import BAZA_GROUP_ID
        gid = int(BAZA_GROUP_ID or 0)
    except Exception:
        gid = 0

    if not gid:
        log.info("BAZA_GROUP_ID yo'q — chiqib ketdi")
        return

    try:
        from aiogram.types import BufferedInputFile
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton

        diff_map = {
            "easy":   "🟢 Oson",
            "medium": "🟡 O'rtacha",
            "hard":   "🔴 Qiyin",
            "expert": "⚡ Ekspert",
        }
        diff_txt = diff_map.get(difficulty, "🟡 O'rtacha")
        qc       = len(questions)

        # ── 1. DOCX fayl tayyorlash ──
        try:
            docx_bytes = _make_docx(
                questions, title=title, tid=tid,
                category=category, creator_name=creator_name,
            )
            filename = f"test_{tid}.docx"
        except Exception as de:
            log.warning(f"DOCX xato, TXT ga o'tish: {de}")
            docx_bytes = _make_txt(questions, title, tid, creator_name).encode("utf-8")
            filename   = f"test_{tid}.txt"

        doc_file = BufferedInputFile(docx_bytes, filename=filename)

        caption = (
            f"📄 <b>{title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <code>{tid}</code>\n"
            f"📁 {category or 'Boshqa'}\n"
            f"📊 {diff_txt}\n"
            f"📋 <b>{qc} ta savol</b>\n"
            f"🎯 O'tish: {passing_score}%\n"
            f"\U0001F464 {creator_name or 'Nomalum'}"
        )

        # ── 2. Faylni guruhga yuborish ──
        file_msg = await bot.send_document(
            chat_id=gid,
            document=doc_file,
            caption=caption,
        )

        # ── 3. Faylga reply — test kartasi + tugmalar ──
        # Web test / Quiz Poll — bot deep-link orqali (bot chatiga olib o'tadi)
        bu = bot_username or ""
        if not bu:
            try:
                me = await bot.me()
                bu = me.username
            except Exception:
                bu = ""

        bld = InlineKeyboardBuilder()
        if bu:
            bld.row(
                InlineKeyboardButton(text="🌐 Web test",
                    url=f"https://t.me/{bu}?start=webtest_{tid}"),
                InlineKeyboardButton(text="📊 Quiz Poll",
                    url=f"https://t.me/{bu}?start=poll_{tid}"),
            )
        bld.row(
            InlineKeyboardButton(
                text="📨 Testni ulashish",
                switch_inline_query=f"test_{tid}",
            )
        )

        card = (
            f"📌 <b>Yangi test!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 <b>{title}</b>\n"
            f"📋 {qc} savol | {diff_txt} | {category or 'Boshqa'}\n"
            f"🆔 <code>{tid}</code>\n\n"
            f"👆 Fayl yuqorida\n"
            f"👇 Boshlash:"
        )

        await bot.send_message(
            chat_id=gid,
            text=card,
            reply_to_message_id=file_msg.message_id,
            reply_markup=bld.as_markup(),
        )

        log.info(f"✅ Baza publish: {tid} → guruh {gid}")

    except Exception as e:
        log.error(f"❌ publish_to_baza xato: {e}", exc_info=True)
