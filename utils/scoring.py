"""📊 BALL HISOBLASH"""
import re

LT = "ABCDEFGHIJ"

def score(questions, answers) -> dict:
    """
    answers: {str(idx): letter_or_text}
    qaytaradi: {percentage, correct, wrong, skipped, details, grade, emoji}
    """
    total   = len(questions)
    correct = wrong = skipped = 0
    details = []

    for i, q in enumerate(questions):
        ans     = answers.get(str(i))
        is_ok   = False

        if ans is None or str(ans).strip() == "":
            skipped += 1
        else:
            is_ok = _check(q, ans)
            if is_ok: correct += 1
            else:     wrong   += 1

        details.append({
            "i":       i,
            "ok":      is_ok,
            "answer":  ans,
            "correct": q.get("correct"),
            "explain": q.get("explanation", ""),
        })

    pct = round(correct / total * 100, 1) if total else 0.0
    return {
        "percentage": pct,
        "correct":    correct,
        "wrong":      wrong,
        "skipped":    skipped,
        "total":      total,
        "grade":      _grade(pct),
        "emoji":      _emoji(pct),
        "details":    details,
    }


def _check(q, ans) -> bool:
    t    = q.get("type", "multiple_choice")
    corr = q.get("correct")
    if corr is None:
        return False

    if t == "multiple_choice":
        am = re.match(r"^([A-Za-z])", str(ans).strip())
        cm = re.match(r"^([A-Za-z])", str(corr).strip())
        if am and cm:
            return am.group(1).upper() == cm.group(1).upper()
        return str(ans).strip().lower() == str(corr).strip().lower()

    if t == "true_false":
        a = str(ans).strip().lower()
        c = str(corr).strip().lower()
        return a == c or (a in ("a","ha","true","1") and c in ("ha","true","1")) \
               or (a in ("b","yo'q","yoq","false","0") and c in ("yo'q","yoq","false","0"))

    if t in ("text_input", "fill_blank"):
        a  = str(ans).strip().lower()
        c  = str(corr).strip().lower()
        acc = [str(x).strip().lower() for x in q.get("accepted_answers", [])]
        return a == c or a in acc

    return False


def _grade(p):
    if p >= 90: return "A+"
    if p >= 80: return "A"
    if p >= 70: return "B"
    if p >= 60: return "C"
    if p >= 50: return "D"
    return "F"

def _emoji(p):
    if p >= 90: return "🌟"
    if p >= 80: return "🔥"
    if p >= 70: return "👍"
    if p >= 60: return "👌"
    if p >= 50: return "⚠️"
    return "❌"

def fmt_result(res, test) -> str:
    pct    = res.get("percentage", 0)
    passed = pct >= test.get("passing_score", 60)
    holat  = "🎉 O'TDINGIZ!" if passed else f"❌ Yiqildingiz (kerak: {test.get('passing_score',60)}%)"
    m, s   = divmod(res.get("time_spent", 0), 60)
    return (
        f"{res.get('emoji','📝')} <b>TEST NATIJASI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 <b>{test.get('title','Test')}</b>\n"
        f"📁 {test.get('category','')}\n\n"
        f"📊 <b>{pct}%</b> | 🎯 {res.get('grade','F')}\n"
        f"✅ {res.get('correct',0)}  ❌ {res.get('wrong',0)}  ⏭ {res.get('skipped',0)}\n"
        f"⏱ {m}d {s:02d}s\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 {holat}"
    )
