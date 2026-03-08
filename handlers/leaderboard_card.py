"""
Leaderboard Card Generator
==========================
Test tugagach chiroyli rasm kartochka yasaydi va guruhga yuboradi.
Rasm so'ng o'chiriladi (xabarni emas, faylni).

Dizayn:
  - Qora-gradient fon
  - Test nomi + statistika header
  - Top 3 — katta medal + progress bar
  - 4-10 — compact qatorlar
  - Footer: ishtirokchi soni, o'rtacha ball
"""
import io
import logging
import os
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
# RANGLAR VA KONSTANTLAR
# ═══════════════════════════════════════════════════
BG_TOP        = (10, 10, 30)
BG_BOTTOM     = (20, 20, 50)
ACCENT        = (99, 102, 241)       # indigo
GOLD          = (255, 200, 50)
SILVER        = (192, 192, 210)
BRONZE        = (205, 127, 50)
WHITE         = (255, 255, 255)
GRAY          = (150, 155, 180)
DARK_CARD     = (30, 32, 60)
GREEN_BAR     = (72, 199, 142)
RED_BAR       = (252, 100, 100)
YELLOW_BAR    = (251, 191, 36)

MEDAL_COLORS  = [GOLD, SILVER, BRONZE]
MEDAL_EMOJIS  = ["🥇", "🥈", "🥉"]
RANK_EMOJI    = ["4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

# 2x scale — Telegram compress qilganda ham o'qiladi
SCALE         = 2
W, H_BASE     = 900 * SCALE, 200 * SCALE
PADDING       = 40  * SCALE
ROW_H         = 68  * SCALE
TOP3_H        = 88  * SCALE


def _get_font(size: int, bold: bool = False):
    """Font yuklash — tizimda bor birinchi fontdan foydalanadi."""
    try:
        from PIL import ImageFont
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.otf" if bold
            else "/usr/share/fonts/truetype/freefont/FreeSans.otf",
        ]
        for p in paths:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        return ImageFont.load_default()
    except Exception:
        try:
            from PIL import ImageFont
            return ImageFont.load_default()
        except Exception:
            return None


def _gradient_bg(draw, w: int, h: int):
    """Vertikal gradient fon."""
    for y in range(h):
        t  = y / h
        r  = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g  = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b  = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def _bar(draw, x: int, y: int, w: int, h: int, pct: float, passing: float = 60.0):
    """Progress bar — foizga qarab rang."""
    draw.rounded_rectangle([x, y, x + w, y + h],
                            radius=h // 2, fill=(40, 42, 70))
    fill_w = max(4, int(w * pct / 100))
    color  = GREEN_BAR if pct >= passing else (
             YELLOW_BAR if pct >= 40 else RED_BAR)
    draw.rounded_rectangle([x, y, x + fill_w, y + h],
                            radius=h // 2, fill=color)


def _truncate(text: str, font, max_w: int) -> str:
    """Matnni belgilangan kenglikka sig'diradi."""
    try:
        from PIL import ImageDraw as ID
        import PIL.Image as PI
        tmp_img  = PI.new("RGB", (1, 1))
        tmp_draw = ID.Draw(tmp_img)
        while len(text) > 1:
            bbox = tmp_draw.textbbox((0, 0), text, font=font)
            if (bbox[2] - bbox[0]) <= max_w:
                break
            text = text[:-2] + "…"
        return text
    except Exception:
        return text[:30]


def generate_leaderboard_image(
    quiz_title: str,
    results: List[Dict],
    passing_score: float = 60.0,
    total_questions: int = 0,
) -> Optional[bytes]:
    """
    Leaderboard rasmini bytes formatida qaytaradi.

    results = [
      {
        "first_name": "Ali",
        "username": "ali_uz",
        "score": 85.0,
        "correct": 17,
        "total": 20,
      }, ...
    ]
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Pillow yo'q — rasm yasalmaydik")
        return None

    if not results:
        return None

    top10    = results[:15]
    top3     = top10[:3]
    rest     = top10[3:]

    # ── Rasm balandligini hisoblash ─────────────────
    H = (
        PADDING                        # yuqori bo'sh joy
        + 90                           # header (test nomi)
        + 30                           # bo'sh joy
        + len(top3) * TOP3_H           # top 3
        + (20 if rest else 0)          # separator
        + len(rest) * ROW_H            # 4-10
        + 80                           # footer
        + PADDING                      # pastki bo'sh joy
    )
    H = max(H, 400)

    img  = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)

    _gradient_bg(draw, W, H)

    # ── Yuqori chiziq (accent) ──────────────────────
    draw.rectangle([0, 0, W, 5], fill=ACCENT)

    # ── Shrift yuklash ──────────────────────────────
    f_title   = _get_font(64, bold=True)
    f_big     = _get_font(56, bold=True)
    f_med     = _get_font(44, bold=False)
    f_small   = _get_font(36, bold=False)
    f_footer  = _get_font(40, bold=False)

    # ── HEADER ─────────────────────────────────────
    y = PADDING

    # Trophy icon area
    draw.ellipse([PADDING, y, PADDING + 50, y + 50],
                 fill=(40, 42, 80), outline=ACCENT, width=4)
    draw.text((PADDING + 13, y + 8), "🏆", font=_get_font(56), fill=WHITE)

    title_text = _truncate(quiz_title, f_title, W - PADDING * 2 - 70)
    draw.text((PADDING + 60, y + 8), title_text, font=f_title, fill=WHITE)

    y += 60
    # Stat chiziqlar
    passed    = sum(1 for r in results if r.get("score", 0) >= passing_score)
    avg_score = sum(r.get("score", 0) for r in results) / len(results) if results else 0
    stat_text = (
        f"👥 {len(results)} ishtirokchi   "
        f"✅ {passed} o'tdi ({passed*100//max(len(results),1)}%)   "
        f"📊 O'rtacha: {avg_score:.0f}%"
    )
    draw.text((PADDING, y), stat_text, font=f_small, fill=GRAY)
    y += 30

    # ── Divider ─────────────────────────────────────
    draw.rectangle([PADDING, y, W - PADDING, y + 2],
                   fill=(50, 55, 90))
    y += 20

    # ── TOP 3 ────────────────────────────────────────
    for i, r in enumerate(top3):
        name   = (r.get("username") or r.get("first_name") or "O'quvchi")
        score  = float(r.get("score", 0))
        correct= int(r.get("correct", 0))
        total  = int(r.get("total", total_questions or 1))
        color  = MEDAL_COLORS[i]

        # Karta foni
        card_x1 = PADDING
        card_x2 = W - PADDING
        card_y1 = y
        card_y2 = y + TOP3_H - 8
        draw.rounded_rectangle(
            [card_x1, card_y1, card_x2, card_y2],
            radius=12,
            fill=(28, 30, 58),
            outline=(*color[:3], 80),
            width=2
        )

        # Medal doira
        cx, cy, cr = card_x1 + 36, card_y1 + TOP3_H // 2 - 4, 22
        draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr],
                     fill=color, outline=WHITE, width=2)
        rank_txt = str(i + 1)
        draw.text((cx - 6 if i < 9 else cx - 9, cy - 11),
                  rank_txt, font=f_med, fill=(20, 20, 40))

        # Ism
        tx = card_x1 + 75
        name_disp = _truncate(name, f_big, W - tx - 220)
        draw.text((tx, card_y1 + 10), name_disp, font=f_big, fill=WHITE)

        # To'g'ri javob
        score_color = GREEN_BAR if score >= passing_score else (
                      YELLOW_BAR if score >= 40 else RED_BAR)
        score_txt = f"{score:.0f}%"
        draw.text((W - PADDING - 160, card_y1 + 8),
                  f"✅ {correct}/{total}", font=f_med, fill=GRAY)
        draw.text((W - PADDING - 70, card_y1 + 8),
                  score_txt, font=f_big, fill=score_color)

        # Progress bar
        _bar(draw, tx, card_y1 + 46, W - tx - PADDING - 10,
             14, score, passing_score)

        y += TOP3_H

    # ── Separator ────────────────────────────────────
    if rest:
        y += 10
        draw.rectangle([PADDING, y, W - PADDING, y + 1],
                       fill=(45, 48, 80))
        draw.text((PADDING, y + 4),
                  f"Qolgan {len(rest)} ishtirokchi:",
                  font=f_small, fill=GRAY)
        y += 28

    # ── 4-10 QATORLAR ────────────────────────────────
    for i, r in enumerate(rest):
        rank   = i + 4
        name   = (r.get("username") or r.get("first_name") or "O'quvchi")
        score  = float(r.get("score", 0))
        correct= int(r.get("correct", 0))
        total  = int(r.get("total", total_questions or 1))

        # Alternating row bg
        if i % 2 == 0:
            draw.rectangle([PADDING, y, W - PADDING, y + ROW_H - 6],
                           fill=(25, 27, 52))

        # Rank
        draw.text((PADDING + 5, y + 16),
                  f"{rank}.", font=f_med, fill=GRAY)

        # Ism
        name_disp = _truncate(name, f_med, W - PADDING * 2 - 220)
        draw.text((PADDING + 38, y + 16),
                  name_disp, font=f_med, fill=WHITE)

        # Natija
        score_color = GREEN_BAR if score >= passing_score else (
                      YELLOW_BAR if score >= 40 else RED_BAR)
        draw.text((W - PADDING - 150, y + 16),
                  f"{correct}/{total}", font=f_med, fill=GRAY)
        draw.text((W - PADDING - 65, y + 16),
                  f"{score:.0f}%", font=f_med, fill=score_color)

        # Mini bar
        _bar(draw, PADDING + 38, y + 46, W - PADDING * 2 - 120,
             10, score, passing_score)

        y += ROW_H

    # ── FOOTER ──────────────────────────────────────
    y += 20
    draw.rectangle([PADDING, y, W - PADDING, y + 1],
                   fill=(50, 55, 90))
    y += 12

    # Passing score ko'rsatish
    footer_left  = f"🎯 O'tish bali: {passing_score:.0f}%"
    footer_right = f"📝 {total_questions} ta savol" if total_questions else ""
    draw.text((PADDING, y), footer_left, font=f_footer, fill=GRAY)
    if footer_right:
        bbox = draw.textbbox((0, 0), footer_right, font=f_footer)
        fw   = bbox[2] - bbox[0]
        draw.text((W - PADDING - fw, y), footer_right, font=f_footer, fill=GRAY)

    # ── Pastki accent chiziq ─────────────────────────
    draw.rectangle([0, H - 5, W, H], fill=ACCENT)

    # ── PNG bytes ───────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()


async def send_leaderboard_card(
    bot,
    chat_id: int,
    quiz_title: str,
    results: List[Dict],
    passing_score: float = 60.0,
    total_questions: int = 0,
    caption: str = "",
    delete_after: int = 0,
) -> Optional[int]:
    """
    Leaderboard rasmini guruhga yuboradi.
    delete_after > 0 bo'lsa, shu soniyadan keyin xabarni o'chiradi.
    Qaytaradi: yuborilgan xabar message_id yoki None.
    """
    import asyncio
    from aiogram.types import BufferedInputFile

    img_bytes = generate_leaderboard_image(
        quiz_title, results, passing_score, total_questions
    )

    if not img_bytes:
        # Fallback: oddiy matn
        logger.warning("Rasm yasalmas — matn yuboriladi")
        return None

    try:
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=BufferedInputFile(img_bytes, filename="leaderboard.png"),
            caption=caption if caption else None,
            parse_mode="HTML"
        )
        logger.info(f"✅ Leaderboard rasm yuborildi: {chat_id} msg={msg.message_id}")

        if delete_after > 0:
            async def _del():
                await asyncio.sleep(delete_after)
                try:
                    await bot.delete_message(chat_id, msg.message_id)
                    logger.info(f"🗑 Leaderboard rasm o'chirildi: msg={msg.message_id}")
                except Exception as e:
                    logger.warning(f"Rasm o'chirishda xato: {e}")
            asyncio.create_task(_del())

        return msg.message_id

    except Exception as e:
        logger.error(f"Leaderboard rasm yuborishda xato: {e}")
        return None
