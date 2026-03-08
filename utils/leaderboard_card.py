"""
Leaderboard Card — Playwright HTML→PNG renderer
Yuqori sifatli, professional ko'rinish
"""
import asyncio
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def _bar_color(pct, passing):
    if pct >= passing:      return "#3cd28c"
    elif pct >= passing*0.7: return "#f9be28"
    else:                   return "#f05a5a"

def _pct_color(pct, passing):
    return _bar_color(pct, passing)


def _build_html(quiz_title, results, passing_score, total_questions):
    avg    = sum(r["score"] for r in results) / len(results) if results else 0
    passed = sum(1 for r in results if r["score"] >= passing_score)
    n      = len(results)
    top3   = results[:3]
    rest   = results[3:15]

    medal_border = ["#ffbe32", "#a0aac8", "#c8823c"]
    medal_bg     = ["rgba(255,190,50,0.15)", "rgba(160,170,200,0.10)", "rgba(200,130,60,0.12)"]

    top3_html = ""
    for i, r in enumerate(top3):
        pct    = r["score"]
        c      = r["correct"]
        t      = r["total"] or total_questions or 1
        name   = (r.get("first_name") or r.get("username") or "O'quvchi")[:28]
        bc     = medal_border[i]
        bg     = medal_bg[i]
        pc     = _pct_color(pct, passing_score)
        bcolor = _bar_color(pct, passing_score)
        top3_html += f"""
        <div class="card top-card" style="border-color:{bc};background:linear-gradient(135deg,{bg},rgba(26,29,54,0.95))">
          <div class="rank-circle" style="background:{bc};color:#12142a">{i+1}</div>
          <div class="card-body">
            <div class="card-top-row">
              <span class="name">{name}</span>
              <div class="right-info">
                <span class="score-info">{c}/{t}</span>
                <span class="pct" style="color:{pc}">{pct:.0f}%</span>
              </div>
            </div>
            <div class="bar-bg"><div class="bar-fill" style="width:{pct}%;background:{bcolor}"></div></div>
          </div>
        </div>"""

    rest_html = ""
    if rest:
        rest_html += f'<div class="rest-label">Qolgan {len(rest)} ishtirokchi:</div>'
        for i, r in enumerate(rest):
            rank   = i + 4
            pct    = r["score"]
            c      = r["correct"]
            t      = r["total"] or total_questions or 1
            name   = (r.get("first_name") or r.get("username") or "O'quvchi")[:30]
            pc     = _pct_color(pct, passing_score)
            bcolor = _bar_color(pct, passing_score)
            rest_html += f"""
            <div class="card rest-card">
              <span class="rest-rank">{rank}.</span>
              <div class="card-body">
                <div class="card-top-row">
                  <span class="rest-name">{name}</span>
                  <div class="right-info">
                    <span class="score-info">{c}/{t}</span>
                    <span class="rest-pct" style="color:{pc}">{pct:.0f}%</span>
                  </div>
                </div>
                <div class="bar-bg"><div class="bar-fill" style="width:{pct}%;background:{bcolor}"></div></div>
              </div>
            </div>"""

    title_s = quiz_title if len(quiz_title) <= 35 else quiz_title[:33] + "…"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
* {{margin:0;padding:0;box-sizing:border-box}}
body {{
  font-family: 'Segoe UI', Arial, sans-serif;
  background:#12142a; width:900px; padding:36px; color:#fff;
}}
.header {{display:flex;align-items:center;gap:18px;margin-bottom:18px}}
.icon-circle {{
  width:72px;height:72px;border-radius:50%;background:#6469dc;
  border:3px solid #fff;display:flex;align-items:center;
  justify-content:center;font-size:32px;font-weight:800;
  color:#fff;flex-shrink:0
}}
.quiz-title {{font-size:36px;font-weight:800;color:#fff;line-height:1.2}}
.stats {{display:flex;gap:28px;margin-bottom:14px;font-size:22px}}
.sp {{color:#fff}} .sg {{color:#3cd28c}} .sa {{color:#8890b0}}
.divider {{height:2px;background:#6469dc;margin-bottom:16px;border-radius:2px}}
.divider-light {{height:1px;background:#2d3255;margin:14px 0;border-radius:1px}}
.card {{
  display:flex;align-items:center;gap:16px;
  background:#1a1d36;border:2px solid #2d3255;
  border-radius:14px;padding:16px 20px;margin-bottom:10px
}}
.top-card {{border-width:2.5px;padding:18px 22px}}
.rank-circle {{
  width:56px;height:56px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  font-size:24px;font-weight:800;flex-shrink:0
}}
.card-body {{flex:1;display:flex;flex-direction:column;gap:10px}}
.card-top-row {{display:flex;align-items:center;justify-content:space-between}}
.name {{font-size:28px;font-weight:700;color:#fff}}
.right-info {{display:flex;align-items:center;gap:18px}}
.score-info {{font-size:22px;font-weight:500;color:#8890b0}}
.pct {{font-size:32px;font-weight:800;min-width:80px;text-align:right}}
.bar-bg {{
  width:100%;height:10px;background:#282c4b;
  border-radius:6px;overflow:hidden;margin-top:2px
}}
.bar-fill {{height:100%;border-radius:6px;min-width:6px}}
.rest-label {{font-size:22px;color:#8890b0;margin:6px 0 10px 0}}
.rest-card {{padding:12px 18px;border-radius:10px;border-width:1px}}
.rest-rank {{font-size:20px;color:#8890b0;width:36px;flex-shrink:0}}
.rest-name {{font-size:24px;font-weight:600;color:#fff}}
.rest-pct {{font-size:24px;font-weight:700;min-width:64px;text-align:right}}
.footer {{
  display:flex;justify-content:space-between;
  font-size:22px;color:#8890b0;margin-top:6px
}}
</style></head>
<body>
  <div class="header">
    <div class="icon-circle">#</div>
    <div class="quiz-title">{title_s}</div>
  </div>
  <div class="stats">
    <span class="sp">&#128101; {n} ishtirokchi</span>
    <span class="sg">&#9989; {passed} o'tdi ({passed*100//n if n else 0}%)</span>
    <span class="sa">&#128202; O'rtacha: {avg:.0f}%</span>
  </div>
  <div class="divider"></div>
  {top3_html}
  {rest_html}
  <div class="divider-light"></div>
  <div class="footer">
    <span>&#127919; O'tish bali: {passing_score:.0f}%</span>
    <span>&#128203; {total_questions} ta savol</span>
  </div>
</body></html>"""


def _find_chromium():
    """Streamlit Cloud va local uchun Chromium path topish."""
    import shutil, os
    # 1. packages.txt orqali o'rnatilgan
    for path in ["/usr/bin/chromium", "/usr/bin/chromium-browser",
                 "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"]:
        if os.path.exists(path):
            return path
    # 2. shutil orqali
    for name in ["chromium", "chromium-browser", "google-chrome"]:
        found = shutil.which(name)
        if found:
            return found
    return None


def generate_leaderboard_image(quiz_title, results, passing_score=60.0, total_questions=0):
    if not results:
        return None
    try:
        from playwright.sync_api import sync_playwright
        html       = _build_html(quiz_title, results, passing_score, total_questions)
        chrome_path = _find_chromium()

        with sync_playwright() as p:
            launch_opts = {
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                ]
            }
            if chrome_path:
                launch_opts["executable_path"] = chrome_path
                logger.info(f"Chromium: {chrome_path}")

            browser = p.chromium.launch(**launch_opts)
            page    = browser.new_page()
            page.set_viewport_size({"width": 900, "height": 1200})
            page.set_content(html, wait_until="domcontentloaded")
            height = page.evaluate("document.body.scrollHeight")
            page.set_viewport_size({"width": 900, "height": height + 20})
            img = page.screenshot(full_page=True, type="png")
            browser.close()
        return img
    except Exception as e:
        logger.error(f"Playwright xato: {e}")
        import traceback; traceback.print_exc()
        return None


async def send_leaderboard_card(
    bot, chat_id, quiz_title, results,
    passing_score=60.0, total_questions=0,
    caption=None, delete_after=0,
):
    from aiogram.types import BufferedInputFile
    loop      = asyncio.get_event_loop()
    img_bytes = await loop.run_in_executor(
        None, generate_leaderboard_image,
        quiz_title, results, passing_score, total_questions
    )
    if not img_bytes:
        return None
    try:
        msg = await bot.send_document(
            chat_id=chat_id,
            document=BufferedInputFile(img_bytes, filename="leaderboard.png"),
            caption=caption or None,
            parse_mode="HTML" if caption else None,
        )
        logger.info(f"✅ Leaderboard HD yuborildi: chat={chat_id}")
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
