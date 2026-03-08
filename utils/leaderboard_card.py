"""
Leaderboard Card — Pillow renderer (Streamlit Cloud uchun)
"""
import io
import asyncio
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

SCALE = 2  # HD

FONT_BOLD    = "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf"

BG_COLOR     = (18, 20, 40)
CARD_BG      = (26, 29, 54)
ACCENT       = (100, 105, 220)
WHITE        = (255, 255, 255)
GRAY         = (136, 144, 176)
GREEN        = (60, 210, 140)
YELLOW       = (249, 190, 40)
RED          = (240, 90, 90)
BAR_BG       = (40, 44, 75)
BORDER_DEF   = (45, 50, 85)

MEDAL_BORDER = [(255, 190, 50), (160, 170, 200), (200, 130, 60)]


def _font(size, bold=False):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size * SCALE)
    except Exception:
        try:
            path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold \
                   else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            return ImageFont.truetype(path, size * SCALE)
        except Exception:
            return ImageFont.load_default()


def _color(pct, passing):
    if pct >= passing:           return GREEN
    elif pct >= passing * 0.7:   return YELLOW
    else:                        return RED


def _rr(draw, x0, y0, x1, y1, r, fill, outline=None, lw=2):
    draw.rectangle([x0+r, y0, x1-r, y1], fill=fill)
    draw.rectangle([x0, y0+r, x1, y1-r], fill=fill)
    for cx, cy in [(x0, y0), (x1-2*r, y0), (x0, y1-2*r), (x1-2*r, y1-2*r)]:
        draw.ellipse([cx, cy, cx+2*r, cy+2*r], fill=fill)
    if outline:
        draw.arc([x0, y0, x0+2*r, y0+2*r], 180, 270, fill=outline, width=lw)
        draw.arc([x1-2*r, y0, x1, y0+2*r], 270, 360, fill=outline, width=lw)
        draw.arc([x0, y1-2*r, x0+2*r, y1], 90, 180, fill=outline, width=lw)
        draw.arc([x1-2*r, y1-2*r, x1, y1], 0, 90, fill=outline, width=lw)
        draw.line([x0+r, y0, x1-r, y0], fill=outline, width=lw)
        draw.line([x0+r, y1, x1-r, y1], fill=outline, width=lw)
        draw.line([x0, y0+r, x0, y1-r], fill=outline, width=lw)
        draw.line([x1, y0+r, x1, y1-r], fill=outline, width=lw)


def _circle(draw, cx, cy, r, fill, outline=None, lw=3):
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=fill,
                 outline=outline, width=lw if outline else 0)


def _tw(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


def generate_leaderboard_image(
    quiz_title: str,
    results: List[Dict],
    passing_score: float = 60.0,
    total_questions: int = 0,
) -> Optional[bytes]:
    if not results:
        return None
    try:
        from PIL import Image, ImageDraw

        S = SCALE
        W   = 900 * S
        PAD = 36  * S
        GAP = 10  * S

        HEADER_H = 120 * S
        STATS_H  = 40  * S
        DIV_H    = 2   * S
        TOP3_H   = 100 * S
        REST_H   = 68  * S
        FOOTER_H = 50  * S

        top3   = results[:3]
        rest   = results[3:15]
        n_rest = len(rest)
        avg    = sum(r["score"] for r in results) / len(results) if results else 0
        passed = sum(1 for r in results if r["score"] >= passing_score)
        n      = len(results)

        total_h = (
            PAD
            + HEADER_H + GAP
            + STATS_H  + GAP
            + DIV_H    + GAP
            + len(top3) * (TOP3_H + GAP)
            + (32*S + GAP if n_rest else 0)
            + n_rest * (REST_H + GAP)
            + DIV_H + GAP
            + FOOTER_H
            + PAD
        )

        img  = Image.new("RGB", (W, total_h), BG_COLOR)
        draw = ImageDraw.Draw(img)

        y = PAD

        # ── HEADER ──
        ICON_R = 34 * S
        icx    = PAD + ICON_R
        icy    = y + HEADER_H // 2
        _circle(draw, icx, icy, ICON_R, ACCENT, outline=WHITE, lw=3*S)
        draw.text((icx, icy), "#", font=_font(28, bold=True), fill=WHITE, anchor="mm")

        title = quiz_title[:32] + "…" if len(quiz_title) > 33 else quiz_title
        draw.text((icx + ICON_R + 18*S, icy - 20*S), title,
                  font=_font(38, bold=True), fill=WHITE)
        y += HEADER_H + GAP

        # ── STATS ──
        items = [
            (f"{n} ishtirokchi",  WHITE),
            (f"{passed} o'tdi ({passed*100//n if n else 0}%)", GREEN),
            (f"O'rtacha: {avg:.0f}%", GRAY),
        ]
        sx = PAD
        for txt, col in items:
            f = _font(24)
            draw.text((sx, y + 6*S), txt, font=f, fill=col)
            sx += _tw(draw, txt, f) + 28*S
        y += STATS_H + GAP

        # ── DIVIDER ──
        draw.rectangle([PAD, y, W-PAD, y+DIV_H], fill=ACCENT)
        y += DIV_H + GAP

        # ── TOP 3 ──
        for i, r in enumerate(top3):
            pct  = r["score"]
            cor  = r["correct"]
            tot  = r["total"] or total_questions or 1
            name = (r.get("first_name") or r.get("username") or "O'quvchi")[:24]
            bc   = MEDAL_BORDER[i]
            col  = _color(pct, passing_score)

            _rr(draw, PAD, y, W-PAD, y+TOP3_H, 12*S,
                fill=CARD_BG, outline=bc, lw=3*S)

            rk_cx = PAD + 46*S
            rk_cy = y + TOP3_H // 2
            _circle(draw, rk_cx, rk_cy, 26*S, bc)
            draw.text((rk_cx, rk_cy), str(i+1),
                      font=_font(26, bold=True), fill=BG_COLOR, anchor="mm")

            name_x = rk_cx + 38*S
            name_y = y + 18*S

            # Foiz (o'ng)
            f_pct   = _font(34, bold=True)
            pct_txt = f"{pct:.0f}%"
            pct_w   = _tw(draw, pct_txt, f_pct)
            pct_x   = W - PAD - 16*S - pct_w
            draw.text((pct_x, name_y), pct_txt, font=f_pct, fill=col)

            # correct/total — foizdan chapda
            f_info   = _font(22)
            info_txt = f"{cor}/{tot}"
            info_w   = _tw(draw, info_txt, f_info)
            draw.text((pct_x - info_w - 18*S, name_y + 6*S),
                      info_txt, font=f_info, fill=GRAY)

            # Ism
            draw.text((name_x, name_y), name, font=_font(28, bold=True), fill=WHITE)

            # Bar
            bar_x0 = name_x
            bar_x1 = W - PAD - 16*S
            bar_y  = name_y + 46*S
            _rr(draw, bar_x0, bar_y, bar_x1, bar_y+10*S, 5*S, fill=BAR_BG)
            fw = int((bar_x1 - bar_x0) * pct / 100)
            if fw > 8*S:
                _rr(draw, bar_x0, bar_y, bar_x0+fw, bar_y+10*S, 5*S, fill=col)

            y += TOP3_H + GAP

        # ── QOLGANLAR ──
        if rest:
            draw.text((PAD, y + 4*S), f"Qolgan {n_rest} ishtirokchi:",
                      font=_font(22), fill=GRAY)
            y += 32*S + GAP

            for i, r in enumerate(rest):
                rank = i + 4
                pct  = r["score"]
                cor  = r["correct"]
                tot  = r["total"] or total_questions or 1
                name = (r.get("first_name") or r.get("username") or "O'quvchi")[:26]
                col  = _color(pct, passing_score)

                _rr(draw, PAD, y, W-PAD, y+REST_H, 10*S,
                    fill=CARD_BG, outline=BORDER_DEF, lw=1*S)

                name_x = PAD + 54*S
                name_y = y + 12*S

                draw.text((PAD + 14*S, name_y + 2*S), f"{rank}.",
                          font=_font(20), fill=GRAY)

                f_rpct  = _font(26, bold=True)
                pct_txt = f"{pct:.0f}%"
                pct_w   = _tw(draw, pct_txt, f_rpct)
                pct_x   = W - PAD - 16*S - pct_w
                draw.text((pct_x, name_y + 2*S), pct_txt, font=f_rpct, fill=col)

                f_ri    = _font(20)
                info_txt = f"{cor}/{tot}"
                info_w  = _tw(draw, info_txt, f_ri)
                draw.text((pct_x - info_w - 16*S, name_y + 4*S),
                          info_txt, font=f_ri, fill=GRAY)

                draw.text((name_x, name_y), name,
                          font=_font(24, bold=True), fill=WHITE)

                bar_x0 = name_x
                bar_x1 = W - PAD - 16*S
                bar_y  = name_y + 34*S
                _rr(draw, bar_x0, bar_y, bar_x1, bar_y+8*S, 4*S, fill=BAR_BG)
                fw = int((bar_x1 - bar_x0) * pct / 100)
                if fw > 8*S:
                    _rr(draw, bar_x0, bar_y, bar_x0+fw, bar_y+8*S, 4*S, fill=col)

                y += REST_H + GAP

        # ── FOOTER ──
        draw.rectangle([PAD, y, W-PAD, y+DIV_H], fill=BORDER_DEF)
        y += DIV_H + GAP

        f_foot = _font(22)
        draw.text((PAD, y + 12*S), f"O'tish bali: {passing_score:.0f}%",
                  font=f_foot, fill=GRAY)
        tq_txt = f"{total_questions} ta savol"
        tq_w   = _tw(draw, tq_txt, f_foot)
        draw.text((W - PAD - tq_w, y + 12*S), tq_txt, font=f_foot, fill=GRAY)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf.read()

    except Exception as e:
        logger.error(f"Leaderboard xato: {e}")
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
    from aiogram.types import BufferedInputFile

    loop      = asyncio.get_event_loop()
    img_bytes = await loop.run_in_executor(
        None, generate_leaderboard_image,
        quiz_title, results, passing_score, total_questions
    )
    if not img_bytes:
        return None
    try:
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=BufferedInputFile(img_bytes, filename="leaderboard.png"),
            caption=caption or None,
            parse_mode="HTML" if caption else None,
        )
        logger.info(f"✅ Leaderboard yuborildi: chat={chat_id}")
        if delete_after > 0:
            async def _del():
                await asyncio.sleep(delete_after)
                try: await bot.delete_message(chat_id, msg.message_id)
                except: pass
            asyncio.create_task(_del())
        return msg.message_id
    except Exception as e:
        logger.error(f"Yuborishda xato: {e}")
        return None
