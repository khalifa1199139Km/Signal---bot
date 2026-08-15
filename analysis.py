"""
تحليل فني للأسهم والذهب.
البيانات من Twelve Data — يحتاج مفتاح مجاني من twelvedata.com
"""

import os

import pandas as pd
import requests

# الرموز المتابَعة. المفتاح = ما تكتبه أنت، القيمة = رمز Twelve Data
SYMBOLS = {
    "GOLD": "XAU/USD",
    "XAUUSD": "XAU/USD",
    "NVDA": "NVDA",
    "TSLA": "TSLA",
    "AMD": "AMD",
    "MU": "MU",
    "CRDO": "CRDO",
    "CBRS": "CBRS",
    "PLTR": "PLTR",
    "SPCX": "SPCX",
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

# الفريمات المدعومة
TIMEFRAMES = {
    "1h": {"interval": "1h", "size": 400, "label": "ساعة"},
    "4h": {"interval": "4h", "size": 400, "label": "4 ساعات"},
    "1d": {"interval": "1day", "size": 500, "label": "يومي"},
}

API_URL = "https://api.twelvedata.com/time_series"


class NotEnoughData(Exception):
    """البيانات المتاحة أقل من المطلوب لحساب مؤشر موثوق."""


def fetch_candles(symbol_key: str, timeframe: str) -> pd.DataFrame:
    """يجلب الشموع من Twelve Data."""
    api_key = os.environ.get("TWELVE_DATA_KEY")
    if not api_key:
        raise NotEnoughData("مفتاح Twelve Data غير موجود في الإعدادات")

    symbol = SYMBOLS.get(symbol_key.upper(), symbol_key.upper())
    config = TIMEFRAMES[timeframe]

    params = {
        "symbol": symbol,
        "interval": config["interval"],
        "outputsize": config["size"],
        "apikey": api_key,
        "format": "JSON",
    }

    try:
        response = requests.get(API_URL, params=params, timeout=25)
        payload = response.json()
    except Exception as error:
        raise NotEnoughData(f"فشل الاتصال بمزود البيانات: {error}")

    # المزود يرجّع status=error مع رسالة واضحة
    if isinstance(payload, dict) and payload.get("status") == "error":
        message = payload.get("message", "خطأ غير معروف")
        raise NotEnoughData(message)

    values = payload.get("values") if isinstance(payload, dict) else None
    if not values:
        raise NotEnoughData(f"ما فيه بيانات متاحة لـ {symbol_key.upper()}")

    frame = pd.DataFrame(values)
    frame["datetime"] = pd.to_datetime(frame["datetime"])
    frame = frame.set_index("datetime").sort_index()

    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    frame = frame.rename(columns=rename_map)

    for column in ["Open", "High", "Low", "Close"]:
        if column not in frame.columns:
            raise NotEnoughData("البيانات ناقصة أعمدة أساسية")
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    if "Volume" in frame.columns:
        frame["Volume"] = pd.to_numeric(frame["Volume"], errors="coerce").fillna(0)
    else:
        frame["Volume"] = 0

    frame = frame[["Open", "High", "Low", "Close", "Volume"]].dropna()

    if len(frame) < 60:
        raise NotEnoughData(
            f"عدد الشموع المتاحة {len(frame)} فقط — قليل للتحليل"
        )

    return frame


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

    if rsi_value >= 70:
        rsi_state = "تشبع شرائي"
        reasons.append(f"RSI {rsi_value:.0f} — تشبع شرائي")
    elif rsi_value <= 30:
        rsi_state = "تشبع بيعي"
        reasons.append(f"RSI {rsi_value:.0f} — تشبع بيعي")
    else:
        rsi_state = "محايد"

    if trend == "صاعد" and rsi_value < 70:
        signal = "BUY"
    elif trend == "هابط" and rsi_value > 30:
        signal = "SELL"
    else:
        signal = "HOLD"

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
        "last_update": data.index[-1].strftime("%Y-%m-%d %H:%M"),
    }
