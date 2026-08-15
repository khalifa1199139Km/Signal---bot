"""
تحليل فني للأسهم والذهب.
البيانات من Yahoo Finance عبر مكتبة yfinance.
"""

import pandas as pd
import yfinance as yf

# الرموز المتابَعة. المفتاح = ما تكتبه أنت، القيمة = رمز ياهو
SYMBOLS = {
    "GOLD": "GC=F",      # عقود الذهب الآجلة (COMEX)
    "XAUUSD": "GC=F",    # اسم بديل لنفس الشيء
    "NVDA": "NVDA",
    "TSLA": "TSLA",
    "AMD": "AMD",
    "MU": "MU",          # Micron Technology
    "CRDO": "CRDO",
    "CBRS": "CBRS",      # Cerebras Systems
    "PLTR": "PLTR",
    "SPCX": "SPCX",      # SpaceX
    "AMBA": "AMBA",
    "MRVL": "MRVL",
    "ALAB": "ALAB",
    "ARM": "ARM",
    "AVGO": "AVGO",
    "RKLB": "RKLB",
    "ASTS": "ASTS",
    "NBIS": "NBIS",
    "COHR": "COHR",
    "MSFT": "MSFT",
}

# إعدادات كل فريم: كم يوم نسحب من التاريخ، وأي interval من ياهو
TIMEFRAMES = {
    "1h": {"period": "60d", "interval": "1h", "resample": None, "label": "ساعة"},
    "4h": {"period": "180d", "interval": "1h", "resample": "4h", "label": "4 ساعات"},
    "1d": {"period": "2y", "interval": "1d", "resample": None, "label": "يومي"},
}


class NotEnoughData(Exception):
    """البيانات المتاحة أقل من المطلوب لحساب مؤشر موثوق."""


def fetch_candles(symbol_key: str, timeframe: str) -> pd.DataFrame:
    """يجلب الشموع ويحوّلها للفريم المطلوب."""
    yahoo_symbol = SYMBOLS.get(symbol_key.upper(), symbol_key.upper())
    config = TIMEFRAMES[timeframe]

    data = yf.download(
        yahoo_symbol,
        period=config["period"],
        interval=config["interval"],
        auto_adjust=False,
        progress=False,
    )

    if data is None or data.empty:
        raise NotEnoughData(f"ما وصلت بيانات للرمز {symbol_key}")

    # yfinance أحياناً يرجع أعمدة متعددة المستويات
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data = data.dropna()

    # تجميع شموع الساعة إلى 4 ساعات
    if config["resample"]:
        data = data.resample(config["resample"]).agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).dropna()

    if len(data) < 60:
        raise NotEnoughData(
            f"عدد الشموع المتاحة {len(data)} فقط — قليل للتحليل"
        )

    return data


def moving_average(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """مؤشر القوة النسبية بطريقة Wilder."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def atr(data: pd.DataFrame, length: int = 14) -> pd.Series:
    """متوسط المدى الحقيقي — مقياس التذبذب."""
    high_low = data["High"] - data["Low"]
    high_close = (data["High"] - data["Close"].shift()).abs()
    low_close = (data["Low"] - data["Close"].shift()).abs()

    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / length, adjust=False).mean()


def find_levels(data: pd.DataFrame, lookback: int = 40):
    """أقرب دعم ومقاومة من قمم وقيعان الفترة الأخيرة."""
    recent = data.tail(lookback)
    price = float(data["Close"].iloc[-1])

    highs = recent["High"]
    lows = recent["Low"]

    resistance_candidates = highs[highs > price]
    support_candidates = lows[lows < price]

    resistance = float(resistance_candidates.min()) if not resistance_candidates.empty else float(highs.max())
    support = float(support_candidates.max()) if not support_candidates.empty else float(lows.min())

    return support, resistance


def analyze(symbol_key: str, timeframe: str = "1d") -> dict:
    """يحسب كل المؤشرات ويرجّع نتيجة جاهزة للعرض."""
    data = fetch_candles(symbol_key, timeframe)

    close = data["Close"]
    price = float(close.iloc[-1])

    ma50 = moving_average(close, 50)
    ma200 = moving_average(close, 200)

    ma50_value = float(ma50.iloc[-1]) if not pd.isna(ma50.iloc[-1]) else None
    ma200_value = float(ma200.iloc[-1]) if not pd.isna(ma200.iloc[-1]) else None

    rsi_value = float(rsi(close).iloc[-1])
    atr_value = float(atr(data).iloc[-1])
    atr_percent = (atr_value / price) * 100

    support, resistance = find_levels(data)

    # تحديد الاتجاه
    reasons = []
    trend_score = 0

    if ma50_value is not None:
        if price > ma50_value:
            trend_score += 1
            reasons.append("السعر فوق متوسط 50")
        else:
            trend_score -= 1
            reasons.append("السعر تحت متوسط 50")

    if ma200_value is not None:
        if price > ma200_value:
            trend_score += 1
            reasons.append("السعر فوق متوسط 200")
        else:
            trend_score -= 1
            reasons.append("السعر تحت متوسط 200")
    else:
        reasons.append("متوسط 200 غير متاح — تاريخ السعر قصير")

    if trend_score >= 2:
        trend = "صاعد"
    elif trend_score <= -2:
        trend = "هابط"
    else:
        trend = "عرضي"

    # حالة RSI
    if rsi_value >= 70:
        rsi_state = "تشبع شرائي"
        reasons.append(f"RSI {rsi_value:.0f} — تشبع شرائي")
    elif rsi_value <= 30:
        rsi_state = "تشبع بيعي"
        reasons.append(f"RSI {rsi_value:.0f} — تشبع بيعي")
    else:
        rsi_state = "محايد"

    # القرار
    if trend == "صاعد" and rsi_value < 70:
        signal = "BUY"
    elif trend == "هابط" and rsi_value > 30:
        signal = "SELL"
    else:
        signal = "HOLD"

    # مستويات الصفقة محسوبة من ATR
    if signal == "BUY":
        entry = price
        stop_loss = price - (atr_value * 1.5)
        take_profit_1 = price + (atr_value * 2)
        take_profit_2 = price + (atr_value * 3.5)
    elif signal == "SELL":
        entry = price
        stop_loss = price + (atr_value * 1.5)
        take_profit_1 = price - (atr_value * 2)
        take_profit_2 = price - (atr_value * 3.5)
    else:
        entry = stop_loss = take_profit_1 = take_profit_2 = None

    # مستوى المخاطرة من التذبذب
    if atr_percent < 1.5:
        risk = "منخفضة"
    elif atr_percent < 3.5:
        risk = "متوسطة"
    else:
        risk = "عالية"

    return {
        "symbol": symbol_key.upper(),
        "timeframe": TIMEFRAMES[timeframe]["label"],
        "price": price,
        "signal": signal,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit_1": take_profit_1,
        "take_profit_2": take_profit_2,
        "trend": trend,
        "rsi": rsi_value,
        "rsi_state": rsi_state,
        "atr_percent": atr_percent,
        "risk": risk,
        "support": support,
        "resistance": resistance,
        "reasons": reasons,
        "candles": len(data),
        "ma200_available": ma200_value is not None,
    }
