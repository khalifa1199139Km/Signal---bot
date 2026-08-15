"""
تحليل فني للأسهم والذهب.
البيانات من Stooq — مجاني، بدون مفتاح، ويشتغل من سيرفرات السحابة.
"""

import io
from datetime import datetime, timedelta

import pandas as pd
import requests

# الرموز المتابَعة. المفتاح = ما تكتبه أنت، القيمة = رمز Stooq
SYMBOLS = {
    "GOLD": "xauusd",     # الذهب مقابل الدولار
    "XAUUSD": "xauusd",
    "NVDA": "nvda.us",
    "TSLA": "tsla.us",
    "AMD": "amd.us",
    "MU": "mu.us",
    "CRDO": "crdo.us",
    "CBRS": "cbrs.us",
    "PLTR": "pltr.us",
    "SPCX": "spcx.us",
    "AMBA": "amba.us",
    "MRVL": "mrvl.us",
    "ALAB": "alab.us",
    "ARM": "arm.us",
    "AVGO": "avgo.us",
    "RKLB": "rklb.us",
    "ASTS": "asts.us",
    "NBIS": "nbis.us",
    "COHR": "cohr.us",
    "MSFT": "msft.us",
}

# إعدادات الفريمات
# Stooq يوفر: d (يومي) و 60 دقيقة للفريمات الأصغر
TIMEFRAMES = {
    "1h": {"interval": "60", "resample": None, "days": 120, "label": "ساعة"},
    "4h": {"interval": "60", "resample": "4h", "days": 400, "label": "4 ساعات"},
    "1d": {"interval": "d", "resample": None, "days": 900, "label": "يومي"},
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


class NotEnoughData(Exception):
    """البيانات المتاحة أقل من المطلوب لحساب مؤشر موثوق."""


def _download_daily(symbol: str) -> pd.DataFrame:
    """تحميل الشموع اليومية من Stooq."""
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()

    text = response.text.strip()
    if not text or text.lower().startswith("no data") or "Date" not in text[:100]:
        raise NotEnoughData(f"ما فيه بيانات متاحة للرمز")

    frame = pd.read_csv(io.StringIO(text), parse_dates=["Date"])
    frame = frame.set_index("Date").sort_index()
    return frame


def _download_intraday(symbol: str) -> pd.DataFrame:
    """تحميل شموع الساعة من Stooq."""
    url = f"https://stooq.com/q/l/?s={symbol}&i=60"
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()

    text = response.text.strip()
    if not text or "Date" not in text[:100]:
        raise NotEnoughData("ما فيه بيانات ساعية متاحة لهذا الرمز")

    frame = pd.read_csv(io.StringIO(text))

    if "Date" in frame.columns and "Time" in frame.columns:
        frame["Datetime"] = pd.to_datetime(
            frame["Date"].astype(str) + " " + frame["Time"].astype(str)
        )
        frame = frame.set_index("Datetime").sort_index()
        frame = frame.drop(columns=["Date", "Time"], errors="ignore")
    else:
        raise NotEnoughData("صيغة البيانات الساعية غير متوقعة")

    return frame


def fetch_candles(symbol_key: str, timeframe: str) -> pd.DataFrame:
    """يجلب الشموع ويحوّلها للفريم المطلوب."""
    stooq_symbol = SYMBOLS.get(symbol_key.upper())
    if stooq_symbol is None:
        # رمز غير مسجّل — نفترض أنه سهم أمريكي
        stooq_symbol = f"{symbol_key.lower()}.us"

    config = TIMEFRAMES[timeframe]

    try:
        if config["interval"] == "d":
            data = _download_daily(stooq_symbol)
        else:
            data = _download_intraday(stooq_symbol)
    except NotEnoughData:
        raise
    except Exception as error:
        raise NotEnoughData(f"ما قدرت أجيب البيانات: {error}")

    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(set(data.columns)):
        raise NotEnoughData("البيانات ناقصة أعمدة أساسية")

    if "Volume" not in data.columns:
        data["Volume"] = 0

    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

    # قص الفترة المطلوبة
    cutoff = datetime.now() - timedelta(days=config["days"])
    data = data[data.index >= cutoff]

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

    last_candle = data.index[-1]

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
        "last_update": last_candle.strftime("%Y-%m-%d"),
    }
