"""
المؤشرات الفنية من الفصل الرابع من الكتاب.
حسابات صرفة على DataFrame — بدون قرارات ولا تنسيق.
"""

import pandas as pd


def sma(series: pd.Series, length: int) -> pd.Series:
    """المتوسط المتحرك البسيط — مؤشر متأخر يتتبع الاتجاه."""
    return series.rolling(window=length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    """المتوسط الأسي — أسرع استجابة للسعر الجديد من البسيط."""
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """مؤشر القوة النسبية بطريقة Wilder — مذبذب بين 0 و 100."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    value = 100 - (100 / (1 + rs))

    # لا خسائر في النافذة = قوة قصوى، ولا حركة إطلاقاً = محايد
    value = value.mask(avg_loss == 0, 100.0)
    value = value.mask((avg_loss == 0) & (avg_gain == 0), 50.0)

    return pd.to_numeric(value, errors="coerce")


def atr(data: pd.DataFrame, length: int = 14) -> pd.Series:
    """متوسط المدى الحقيقي — مقياس التذبذب، يستخدم كوحدة قياس للمسافات."""
    high_low = data["High"] - data["Low"]
    high_close = (data["High"] - data["Close"].shift()).abs()
    low_close = (data["Low"] - data["Close"].shift()).abs()

    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / length, adjust=False).mean()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """
    MACD = متوسط قصير − متوسط طويل.
    الكتاب: تقاطع الخط فوق خط الإشارة = شراء، وتحته = بيع.
    والهيستوجرام يقيس قوة الزخم؛ تراجعه فوق الصفر يعني ضعف الصعود.
    """
    line = ema(series, fast) - ema(series, slow)
    signal_line = ema(line, signal)
    histogram = line - signal_line

    return {
        "line": float(line.iloc[-1]),
        "signal": float(signal_line.iloc[-1]),
        "histogram": float(histogram.iloc[-1]),
        "histogram_prev": float(histogram.iloc[-2]) if len(histogram) > 1 else 0.0,
        "bullish": bool(line.iloc[-1] > signal_line.iloc[-1]),
        "above_zero": bool(line.iloc[-1] > 0),
    }


def stochastic(data: pd.DataFrame, length: int = 14, smooth: int = 3) -> dict:
    """
    مذبذب ستوكاستك: في الصعود يغلق السعر قرب قمة المدى، وفي الهبوط قرب قاعه.
    الكتاب: تحت 20 تشبع بيعي، وفوق 80 تشبع شرائي، و%D هو الأهم.
    """
    lowest = data["Low"].rolling(window=length).min()
    highest = data["High"].rolling(window=length).max()

    span = (highest - lowest).replace(0, pd.NA)
    k_raw = 100 * (data["Close"] - lowest) / span
    k = k_raw.rolling(window=smooth).mean()
    d = k.rolling(window=smooth).mean()

    k_value = float(k.iloc[-1]) if not pd.isna(k.iloc[-1]) else 50.0
    d_value = float(d.iloc[-1]) if not pd.isna(d.iloc[-1]) else 50.0

    if d_value >= 80:
        state = "تشبع شرائي"
    elif d_value <= 20:
        state = "تشبع بيعي"
    else:
        state = "محايد"

    return {"k": k_value, "d": d_value, "state": state}


def bollinger(series: pd.Series, length: int = 20, deviations: float = 2.0) -> dict:
    """
    نطاقات بولنجر حول متوسط 20.
    الكتاب: قرب النطاق العلوي = تشبع شرائي، وقرب السفلي = تشبع بيعي،
    وضيق النطاق إشارة أن التذبذب على وشك الزيادة.
    """
    middle = sma(series, length)
    spread = series.rolling(window=length).std()

    upper = middle + (spread * deviations)
    lower = middle - (spread * deviations)

    price = float(series.iloc[-1])
    upper_value = float(upper.iloc[-1])
    lower_value = float(lower.iloc[-1])
    middle_value = float(middle.iloc[-1])

    width = upper_value - lower_value
    position = (price - lower_value) / width if width else 0.5

    # عرض النطاق الحالي مقارنة بمتوسط عرضه — أقل من 1 يعني انكماش
    bandwidth = (upper - lower) / middle
    bandwidth_now = float(bandwidth.iloc[-1])
    bandwidth_mean = float(bandwidth.tail(length * 3).mean())
    squeeze = bool(bandwidth_mean and bandwidth_now < bandwidth_mean * 0.7)

    return {
        "upper": upper_value,
        "middle": middle_value,
        "lower": lower_value,
        "position": position,
        "squeeze": squeeze,
    }


def volume_profile(data: pd.DataFrame, recent: int = 10, base: int = 50) -> dict:
    """
    الحجم يؤكد الاتجاه (الفصل 3.4): مع الاتجاه الصاعد يفترض أن يزيد،
    وتناقصه أثناء الصعود إنذار بأن الصعود على وشك الانتهاء.
    بعض الرموز (الذهب الفوري) ترجع حجماً صفرياً — نعتبره غير متاح.
    """
    volume = data["Volume"]

    if volume.tail(base).sum() <= 0:
        return {"available": False, "ratio": None, "state": "غير متاح"}

    recent_mean = float(volume.tail(recent).mean())
    base_mean = float(volume.tail(base).mean())

    if not base_mean:
        return {"available": False, "ratio": None, "state": "غير متاح"}

    ratio = recent_mean / base_mean

    if ratio >= 1.2:
        state = "مرتفع"
    elif ratio <= 0.8:
        state = "متناقص"
    else:
        state = "طبيعي"

    return {"available": True, "ratio": ratio, "state": state}
