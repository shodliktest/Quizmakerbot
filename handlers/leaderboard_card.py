"""
Leaderboard Card Generator — Professional Design
=================================================
2-rasmdagi kabi yuqori sifatli leaderboard kartochka.
"""
import io
import logging
import math
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
# FONTLAR
# ═══════════════════════════════════════════════
FONT_BOLD    = "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf"

# ═══════════════════════════════════════════════
# RANGLAR
# ═══════════════════════════════════════════════
BG_COLOR      = (18, 20, 40)        # qorong'i ko'k fon
CARD_BG       = (26, 29, 54)        # karta foni
BORDER_GOLD   = (255, 190, 50)      # 1-o'rin oltin chegara
BORDER_SILVER = (160, 170, 200)     # 2-o'rin kumush
BORDER_BRONZE = (200, 130, 60)      # 3-o'rin bronza
BORDER_DEF    = (45, 50, 85)        # oddiy chegara
ACCENT        = (100, 105, 220)     # indigo aksent
WHITE         = (255, 255, 255)
GRAY          = (130, 140, 175)
GREEN         = (60, 210, 140)
YELLOW        = (250, 190, 40)
RED           = (240, 90, 90)
BAR_BG        = (40, 44, 75)

MEDAL_COLORS  = [BORDER_GOLD, BORDER_SILVER, BORDER_BRONZE]
MEDAL_BG      = [(60, 48, 10), (38, 42, 58), (52, 35, 15)]


def _font(size, bold=False):
    from PIL import ImageFont
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.truetype(FONT_REGULAR, size)
        except Exception:
            return ImageFont.load_default()


def _bar_color(pct, passing):
    if pct >= passing:
        return GREEN
    elif pct >= passing * 0.7:
        return YELLOW
    else:
        return RED


def _pct_color(pct, passing):
    if pct >= passing:
        return GREEN
    elif pct >= passing * 0.7:
        return YELLOW
    else:
        return RED


def _draw_rounded_rect(draw, x0, y0, x1, y1, r, fill, outline=None, outline_width=2):
    """To'ldirilgan yumaloq to'rtburchak."""
    from PIL import ImageDraw
    draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
    draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
    draw.ellipse([x0, y0, x0 + 2*r, y0 + 2*r], fill=fill)
    draw.ellipse([x1 - 2*r, y0, x1, y0 + 2*r], fill=fill)
    draw.ellipse([x0, y1 - 2*r, x0 + 2*r, y1], fill=fill)
    draw.ellipse([x1 - 2*r, y1 - 2*r, x1, y1], fill=fill)
    if outline:
        draw.arc([x0, y0, x0+2*r, y0+2*r], 180, 270, fill=outline, width=outline_width)
        draw.arc([x1-2*r, y0, x1, y0+2*r], 270, 360, fill=outline, width=outline_width)
        draw.arc([x0, y1-2*r, x0+2*r, y1], 90, 180, fill=outline, width=outline_width)
        draw.arc([x1-2*r, y1-2*r, x1, y1], 0, 90, fill=outline, width=outline_width)
        draw.line([x0+r, y0, x1-r, y0], fill=outline, width=outline_width)
        draw.line([x0+r, y1, x1-r, y1], fill=outline, width=outline_width)
        draw.line([x0, y0+r, x0, y1-r], fill=outline, width=outline_width)
        draw.line([x1, y0+r, x1, y1-r], fill=outline, width=outline_width)


def _draw_circle(draw, cx, cy, r, fill, outline=None, outline_width=3):
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=fill,
                 outline=outline, width=outline_width if outline else 0)


def generate_leaderboard_image(
    quiz_title: str,
    results: List[Dict],
    passing_score: float = 60.0,
    total_questions: int = 0,
) -> Optional[bytes]:
    try:
        from PIL import Image, ImageDraw

        W = 900
        PAD = 36

        # ── O'lchamlar ──
        HEADER_H  = 130
        STATS_H   = 44
        DIVIDER_H = 2
        TOP3_H    = 96
        ROW_H     = 72
        FOOTER_H  = 56
        GAP       = 12

        top3    = results[:3]
        rest    = results[3:15]
        n_rest  = len(rest)

        total_h = (
            PAD
            + HEADER_H + GAP
            + STATS_H  + GAP
            + DIVIDER_H + GAP
            + len(top3) * (TOP3_H + GAP)
            + (30 + GAP if n_rest else 0)
            + n_rest * (ROW_H + GAP)
            + DIVIDER_H + GAP
            + FOOTER_H
            + PAD
        )

        img  = Image.new("RGB", (W, total_h), BG_COLOR)
        draw = ImageDraw.Draw(img)

        y = PAD

        # ══════════════════════════════════════════
        # HEADER — icon + sarlavha
        # ══════════════════════════════════════════
        ICON_R = 36
        cx = PAD + ICON_R
        cy = y + HEADER_H // 2
        _draw_circle(draw, cx, cy, ICON_R, ACCENT, outline=WHITE, outline_width=3)
        icon_txt = "🏆"
        # Emoji o'rniga oddiy matn (Pillow emoji ko'rsatmaydi)
        f_icon = _font(28, bold=True)
        draw.text((cx, cy), "#", font=f_icon, fill=WHITE, anchor="mm")

        # Test nomi
        f_title = _font(42, bold=True)
        title_x = cx + ICON_R + 20
        # Uzun nomni kesish
        title = quiz_title if len(quiz_title) <= 28 else quiz_title[:26] + "..."
        draw.text((title_x, cy - 18), title, font=f_title, fill=WHITE)

        y += HEADER_H + GAP

        # ══════════════════════════════════════════
        # STATISTIKA QATORI
        # ══════════════════════════════════════════
        avg     = sum(r["score"] for r in results) / len(results) if results else 0
        passed  = sum(1 for r in results if r["score"] >= passing_score)
        n_total = len(results)

        f_stats = _font(26)
        f_statsb = _font(26, bold=True)

        stats_items = [
            (f"👥 {n_total} ishtirokchi", WHITE),
            (f"✅ {passed} o'tdi ({passed*100//n_total if n_total else 0}%)", GREEN),
            (f"📊 O'rtacha: {avg:.0f}%", GRAY),
        ]
        sx = PAD
        for txt, col in stats_items:
            draw.text((sx, y), txt, font=f_stats, fill=col)
            bbox = draw.textbbox((sx, y), txt, font=f_stats)
            sx = bbox[2] + 30

        y += STATS_H + GAP

        # Divider
        draw.rectangle([PAD, y, W-PAD, y+DIVIDER_H], fill=ACCENT)
        y += DIVIDER_H + GAP

        # ══════════════════════════════════════════
        # TOP 3 — katta kartalar
        # ══════════════════════════════════════════
        f_rank   = _font(28, bold=True)
        f_name   = _font(30, bold=True)
        f_score  = _font(30, bold=True)
        f_info   = _font(22)
        f_sub    = _font(20)

        for i, r in enumerate(top3):
            pct     = r["score"]
            correct = r["correct"]
            total   = r["total"] or total_questions or 1
            name    = (r.get("first_name") or r.get("username") or "O'quvchi")[:22]
            border  = MEDAL_COLORS[i]
            bg      = MEDAL_BG[i]

            # Karta foni
            _draw_rounded_rect(draw, PAD, y, W-PAD, y+TOP3_H, 12,
                                fill=CARD_BG, outline=border, outline_width=3)

            # Rank doira
            rk_cx = PAD + 48
            rk_cy = y + TOP3_H // 2
            _draw_circle(draw, rk_cx, rk_cy, 28, border)
            draw.text((rk_cx, rk_cy), str(i+1), font=f_rank,
                      fill=BG_COLOR, anchor="mm")

            # Ism + correct/total — yuqori qatorda
            name_x  = rk_cx + 40
            pct_col = _pct_color(pct, passing_score)
            pct_txt = f"{pct:.0f}%"
            f_pct   = _font(32, bold=True)
            pct_bbox = draw.textbbox((0, 0), pct_txt, font=f_pct)
            pct_w    = pct_bbox[2] - pct_bbox[0]

            info_txt  = f"{correct}/{total}"
            f_info2   = _font(22)
            info_bbox = draw.textbbox((0, 0), info_txt, font=f_info2)
            info_w    = info_bbox[2] - info_bbox[0]

            # Ism — yuqori chap, vertikal markazda
            name_y = y + TOP3_H // 2 - 28
            draw.text((name_x, name_y), name, font=f_name, fill=WHITE)

            # correct/total — ismning o'ng tomonida, foizdan chapda
            info_x = W - PAD - 16 - pct_w - 20 - info_w - 16
            info_y = name_y + 4
            draw.text((info_x, info_y), info_txt, font=f_info2, fill=GRAY)

            # Foiz — o'ng yuqori
            draw.text((W - PAD - 16 - pct_w, name_y),
                      pct_txt, font=f_pct, fill=pct_col)

            # Progress bar — pastda, matndan 14px past
            bar_x0 = name_x
            bar_x1 = W - PAD - 16
            bar_y  = name_y + 42
            bar_w  = bar_x1 - bar_x0
            _draw_rounded_rect(draw, bar_x0, bar_y, bar_x1, bar_y + 10, 5, fill=BAR_BG)
            filled_w = int(bar_w * pct / 100)
            if filled_w > 10:
                col = _bar_color(pct, passing_score)
                _draw_rounded_rect(draw, bar_x0, bar_y, bar_x0 + filled_w, bar_y + 10, 5, fill=col)

            y += TOP3_H + GAP

        # ══════════════════════════════════════════
        # QOLGAN ISHTIROKCHILAR
        # ══════════════════════════════════════════
        if rest:
            f_sec = _font(24)
            draw.text((PAD, y + 4), f"Qolgan {n_rest} ishtirokchi:", font=f_sec, fill=GRAY)
            y += 30 + GAP

            f_rname = _font(26, bold=True)
            f_rinfo = _font(24)
            f_rpct  = _font(26, bold=True)

            for i, r in enumerate(rest):
                rank    = i + 4
                pct     = r["score"]
                correct = r["correct"]
                total   = r["total"] or total_questions or 1
                name    = (r.get("first_name") or r.get("username") or "O'quvchi")[:24]
                col     = _bar_color(pct, passing_score)
                pct_col = _pct_color(pct, passing_score)

                row_y0 = y
                row_y1 = y + ROW_H

                # Fon
                _draw_rounded_rect(draw, PAD, row_y0, W-PAD, row_y1, 8,
                                   fill=CARD_BG, outline=BORDER_DEF, outline_width=1)

                # Rank raqam
                draw.text((PAD + 16, row_y0 + 16), f"{rank}.", font=f_sub, fill=GRAY)

                name_x = PAD + 56

                # Foiz — o'ng yuqori
                pct_txt  = f"{pct:.0f}%"
                pct_bbox = draw.textbbox((0, 0), pct_txt, font=f_rpct)
                pct_w    = pct_bbox[2] - pct_bbox[0]
                draw.text((W - PAD - 16 - pct_w, row_y0 + 12),
                          pct_txt, font=f_rpct, fill=pct_col)

                # correct/total — foizdan chapda
                info_txt  = f"{correct}/{total}"
                info_bbox = draw.textbbox((0, 0), info_txt, font=f_rinfo)
                info_w    = info_bbox[2] - info_bbox[0]
                draw.text((W - PAD - 16 - pct_w - 16 - info_w, row_y0 + 14),
                          info_txt, font=f_rinfo, fill=GRAY)

                # Ism — chap yuqori
                draw.text((name_x, row_y0 + 12), name, font=f_rname, fill=WHITE)

                # Bar — pastda, ismdan 12px past
                bar_x0 = name_x
                bar_x1 = W - PAD - 16
                bar_y  = row_y0 + 46
                bar_w  = bar_x1 - bar_x0
                _draw_rounded_rect(draw, bar_x0, bar_y, bar_x1, bar_y + 8, 4, fill=BAR_BG)
                fw = int(bar_w * pct / 100)
                if fw > 8:
                    _draw_rounded_rect(draw, bar_x0, bar_y, bar_x0 + fw, bar_y + 8, 4, fill=col)

                y += ROW_H + GAP

        # ══════════════════════════════════════════
        # FOOTER
        # ══════════════════════════════════════════
        draw.rectangle([PAD, y, W-PAD, y+DIVIDER_H], fill=BORDER_DEF)
        y += DIVIDER_H + GAP

        f_foot = _font(24)
        draw.text((PAD, y + 14),
                  f"O'tish bali: {passing_score:.0f}%",
                  font=f_foot, fill=GRAY)

        tq_txt = f"{total_questions} ta savol"
        tq_bbox = draw.textbbox((0,0), tq_txt, font=f_foot)
        tq_w = tq_bbox[2] - tq_bbox[0]
        draw.text((W - PAD - tq_w, y + 14),
                  tq_txt, font=f_foot, fill=GRAY)

        # ── PNG sifatida saqlash ──
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        buf.seek(0)
        return buf.read()

    except Exception as e:
        logger.error(f"Leaderboard rasm xatosi: {e}")
        import traceback; traceback.print_exc()
        return None


async def send_leaderboard_card(
    bot,
    chat_id: int,
    quiz_title: str,
    results: List[Dict],
    passing_score: float = 60.0,
    total_questions: int = 0,
    caption: str = None,
    delete_after: int = 0,
) -> Optional[int]:
    import asyncio
    from aiogram.types import BufferedInputFile

    img_bytes = generate_leaderboard_image(
        quiz_title, results, passing_score, total_questions
    )
    if not img_bytes:
        return None

    try:
        # Document sifatida — Telegram siqmaydi, HD sifat saqlanadi
        msg = await bot.send_document(
            chat_id=chat_id,
            document=BufferedInputFile(img_bytes, filename="leaderboard.png"),
            caption=caption if caption else None,
            parse_mode="HTML" if caption else None,
        )
        logger.info(f"✅ Leaderboard (HD doc) yuborildi: {chat_id} msg={msg.message_id}")

        if delete_after > 0:
            async def _del():
                await asyncio.sleep(delete_after)
                try:
                    await bot.delete_message(chat_id, msg.message_id)
                except Exception: pass
            asyncio.create_task(_del())

        return msg.message_id

    except Exception as e:
        logger.error(f"Leaderboard yuborishda xato: {e}")
        return None
