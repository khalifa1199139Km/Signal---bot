"""
بنية السعر من الفصل الثاني من الكتاب.

الفكرة الأساس: الاتجاه ليس موقع السعر من متوسط، بل تسلسل القمم والقيعان.
صاعد = قمم أعلى وقيعان أعلى. هابط = قمم أدنى وقيعان أدنى. غير ذلك عرضي.
"""

from dataclasses import dataclass

import pandas as pd

# نسب التصحيح: الثلث والنصف والثلثين (نظرية داو) و 38٪ و 62٪ (فيبوناتشي/إليوت)
RETRACEMENT_LEVELS = (0.333, 0.382, 0.5, 0.618, 0.666)

# الحد الأدنى والأقصى للتصحيح المقبول قبل أن ينقلب لانعكاس
MIN_RETRACEMENT = 0.333
PREFERRED_RETRACEMENT = 0.5
MAX_RETRACEMENT = 0.666


@dataclass
class Pivot:
    """نقطة انعكاس مؤكدة: قمة أو قاع."""

    position: int
    price: float
    kind: str  # "peak" أو "trough"


def find_pivots(data: pd.DataFrame, width: int) -> list:
    """
    يستخرج القمم والقيعان: الشمعة قمة إذا كان أعلاها يفوق ما حولها بعرض width.
    تحتاج width شمعة بعدها للتأكيد، فآخر width شمعة لا تكوّن نقاطاً بعد.
    """
    highs = data["High"].tolist()
    lows = data["Low"].tolist()
    count = len(data)

    pivots = []
    for i in range(width, count - width):
        left_h = highs[i - width:i]
        right_h = highs[i + 1:i + width + 1]
        if highs[i] > max(left_h) and highs[i] >= max(right_h):
            pivots.append(Pivot(i, highs[i], "peak"))
            continue

        left_l = lows[i - width:i]
        right_l = lows[i + 1:i + width + 1]
        if lows[i] < min(left_l) and lows[i] <= min(right_l):
            pivots.append(Pivot(i, lows[i], "trough"))

    return _alternate(pivots)


def _alternate(pivots: list) -> list:
    """
    يبقي تعاقباً منتظماً قمة/قاع. لو تتالت قمتان نُبقي الأعلى،
    ولو تتالى قاعان نُبقي الأدنى — حتى تبقى الزيجزاج نظيفة.
    """
    cleaned = []
    for pivot in pivots:
        if not cleaned or cleaned[-1].kind != pivot.kind:
            cleaned.append(pivot)
            continue

        last = cleaned[-1]
        if pivot.kind == "peak" and pivot.price > last.price:
            cleaned[-1] = pivot
        elif pivot.kind == "trough" and pivot.price < last.price:
            cleaned[-1] = pivot

    return cleaned


def classify_trend(pivots: list, tolerance: float) -> dict:
    """
    يصنّف الاتجاه من آخر قمتين وآخر قاعين.
    tolerance بوحدة السعر: الفرق الأصغر منها يعتبر «نفس المستوى».
    """
    peaks = [p for p in pivots if p.kind == "peak"]
    troughs = [p for p in pivots if p.kind == "trough"]

    if len(peaks) < 2 or len(troughs) < 2:
        return {
            "trend": "غير محدد",
            "peaks": peaks,
            "troughs": troughs,
            "peak_state": None,
            "trough_state": None,
            "reason": "عدد القمم والقيعان المؤكدة غير كافٍ لتحديد الاتجاه",
        }

    peak_state = _compare(peaks[-2].price, peaks[-1].price, tolerance)
    trough_state = _compare(troughs[-2].price, troughs[-1].price, tolerance)

    if peak_state == "higher" and trough_state == "higher":
        trend = "صاعد"
        reason = "قمم أعلى وقيعان أعلى — اتجاه صاعد"
    elif peak_state == "lower" and trough_state == "lower":
        trend = "هابط"
        reason = "قمم أدنى وقيعان أدنى — اتجاه هابط"
    else:
        trend = "عرضي"
        reason = "القمم والقيعان بلا تسلسل واضح — سوق عرضي"

    return {
        "trend": trend,
        "peaks": peaks,
        "troughs": troughs,
        "peak_state": peak_state,
        "trough_state": trough_state,
        "reason": reason,
    }


def _compare(previous: float, current: float, tolerance: float) -> str:
    if current > previous + tolerance:
        return "higher"
    if current < previous - tolerance:
        return "lower"
    return "equal"


def support_resistance(data: pd.DataFrame, pivots: list, price: float) -> dict:
    """
    الدعم من القيعان السابقة والمقاومة من القمم السابقة (الفصل 2.3).
    نأخذ أقرب قاع تحت السعر وأقرب قمة فوقه.
    """
    peaks_above = [p.price for p in pivots if p.kind == "peak" and p.price > price]
    troughs_below = [p.price for p in pivots if p.kind == "trough" and p.price < price]

    resistance = min(peaks_above) if peaks_above else float(data["High"].max())
    support = max(troughs_below) if troughs_below else float(data["Low"].min())

    return {"support": support, "resistance": resistance}


def current_leg(data: pd.DataFrame, trend_info: dict, trend: str) -> dict:
    """
    يحدد آخر موجة دافعة لقياس التصحيح عليها.
    في الصعود: من آخر قاع مؤكد إلى أعلى قمة بعده (حتى لو لم تتأكد بعد).
    في الهبوط: من آخر قمة مؤكدة إلى أدنى قاع بعدها.
    """
    highs = data["High"]
    lows = data["Low"]

    if trend == "صاعد":
        anchor = trend_info["troughs"][-1]
        segment = highs.iloc[anchor.position:]
        return {
            "low": anchor.price,
            "high": float(segment.max()),
            "anchor_position": anchor.position,
        }

    if trend == "هابط":
        anchor = trend_info["peaks"][-1]
        segment = lows.iloc[anchor.position:]
        return {
            "low": float(segment.min()),
            "high": anchor.price,
            "anchor_position": anchor.position,
        }

    return {}


def retracement(leg: dict, price: float, trend: str) -> dict:
    """
    يقيس كم صحّح السعر من الموجة، ويحسب مستويات 33٪ و 50٪ و 66٪ (الفصل 2.7).

    الكتاب: السوق يصحح عادة ثلث الموجة على الأقل، ومنطقة 33-50٪ هي
    منطقة الشراء المفضلة في الصعود. وتجاوز الثلثين يحوّل التصحيح لانعكاس.
    """
    span = leg["high"] - leg["low"]
    if span <= 0:
        return {}

    if trend == "صاعد":
        # التصحيح يُقاس نزولاً من قمة الموجة
        percent = (leg["high"] - price) / span
        levels = {pct: leg["high"] - (span * pct) for pct in RETRACEMENT_LEVELS}
    else:
        # في الهبوط الارتداد يُقاس صعوداً من قاع الموجة
        percent = (price - leg["low"]) / span
        levels = {pct: leg["low"] + (span * pct) for pct in RETRACEMENT_LEVELS}

    if percent < MIN_RETRACEMENT:
        state = "shallow"
    elif percent <= PREFERRED_RETRACEMENT:
        state = "zone"
    elif percent <= MAX_RETRACEMENT:
        state = "deep"
    else:
        state = "broken"

    return {
        "span": span,
        "percent": percent,
        "levels": levels,
        "state": state,
        "entry_low": levels[PREFERRED_RETRACEMENT] if trend == "صاعد" else levels[MIN_RETRACEMENT],
        "entry_high": levels[MIN_RETRACEMENT] if trend == "صاعد" else levels[PREFERRED_RETRACEMENT],
        "invalidation": levels[MAX_RETRACEMENT],
    }


def trendline(pivots: list, kind: str, last_position: int, price: float, tolerance: float) -> dict:
    """
    خط الاتجاه (الفصل 2.5): يُرسم تحت القيعان الصاعدة أو فوق القمم الهابطة.
    نقطتان تكفيان لخط مبدئي، والثالثة تجعله خطاً معتمداً،
    وأهميته تزيد بعدد اللمسات وبطول صموده. واختراقه من أقوى إنذارات تغيّر الاتجاه.

    ويُرسم على قيعان أو قمم الارتداد الصغيرة، لا على النقاط الكبرى وحدها،
    وإلا لم تجتمع له لمسات تكفي للحكم عليه.
    """
    points = [p for p in pivots if p.kind == kind]
    if len(points) < 2:
        return {"available": False}

    first, second = points[-2], points[-1]
    run = second.position - first.position
    if run <= 0:
        return {"available": False}

    slope = (second.price - first.price) / run
    value_now = second.price + slope * (last_position - second.position)

    touches = 0
    for point in points:
        expected = second.price + slope * (point.position - second.position)
        if abs(point.price - expected) <= tolerance:
            touches += 1

    if kind == "trough":
        broken = price < value_now - tolerance
    else:
        broken = price > value_now + tolerance

    return {
        "available": True,
        "value": value_now,
        "slope": slope,
        "touches": touches,
        "valid": touches >= 3,
        "broken": bool(broken),
        "bars": last_position - first.position,
    }


def reversal_pattern(trend_info: dict, trend: str, price: float, tolerance: float) -> dict:
    """
    القمة والقاع المزدوجان (الفصل 2.4 و 3.3.1).

    قمة مزدوجة: قمتان عند نفس المستوى تقريباً، والنمط لا يكتمل
    إلا إذا كسر السعر القاع الفاصل بينهما. والعكس للقاع المزدوج.

    الكتاب يشترط وجود اتجاه سابق: بلا اتجاه لا يوجد ما ينعكس،
    فقمتان متساويتان داخل سوق عرضي هما حدّا نطاق لا نمط انعكاسي.
    """
    if trend not in ("صاعد", "هابط"):
        return {}

    peaks = trend_info["peaks"]
    troughs = trend_info["troughs"]

    if trend == "صاعد" and len(peaks) >= 2 and abs(peaks[-1].price - peaks[-2].price) <= tolerance:
        between = [
            t for t in troughs
            if peaks[-2].position < t.position < peaks[-1].position
        ]
        if between:
            neckline = min(t.price for t in between)
            return {
                "name": "قمة مزدوجة",
                "direction": "هابط",
                "neckline": neckline,
                "complete": price < neckline,
            }

    if trend == "هابط" and len(troughs) >= 2 and abs(troughs[-1].price - troughs[-2].price) <= tolerance:
        between = [
            p for p in peaks
            if troughs[-2].position < p.position < troughs[-1].position
        ]
        if between:
            neckline = max(p.price for p in between)
            return {
                "name": "قاع مزدوج",
                "direction": "صاعد",
                "neckline": neckline,
                "complete": price > neckline,
            }

    return {}
