"""
تحليل فني للأسهم والذهب مبني على كتاب Technical Analysis Explained.

القرار يُبنى على بنية السعر أولاً (قمم وقيعان)، ثم تؤكده المؤشرات:
  • الاتجاه من تسلسل القمم والقيعان — لا من موقع السعر من متوسط.
  • الاتجاه الكبير يحدد جهة الصفقة، والصغير يحدد توقيت الدخول.
  • السوق العرضي = لا صفقة.
  • الدخول من منطقة تصحيح 33-50٪، والخروج إذا تجاوز التصحيح الثلثين.

البيانات من Twelve Data — يحتاج مفتاح مجاني من twelvedata.com
"""

import os

import pandas as pd
import requests

import indicators
import structure

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
    "1m": {"interval": "1min", "size": 400, "label": "دقيقة"},
    "5m": {"interval": "5min", "size": 400, "label": "5 دقائق"},
    "15m": {"interval": "15min", "size": 400, "label": "15 دقيقة"},
    "30m": {"interval": "30min", "size": 400, "label": "30 دقيقة"},
    "45m": {"interval": "45min", "size": 400, "label": "45 دقيقة"},
    "1h": {"interval": "1h", "size": 400, "label": "ساعة"},
    "2h": {"interval": "2h", "size": 400, "label": "ساعتين"},
    "4h": {"interval": "4h", "size": 400, "label": "4 ساعات"},
    "8h": {"interval": "8h", "size": 400, "label": "8 ساعات"},
    "1d": {"interval": "1day", "size": 500, "label": "يومي"},
    "1w": {"interval": "1week", "size": 400, "label": "أسبوعي"},
    "1M": {"interval": "1month", "size": 300, "label": "شهري"},
}

# الفريمات اللي تعطي إشارات كثيرة وضجيج عالي
NOISY_TIMEFRAMES = {"1m", "5m", "15m"}

API_URL = "https://api.twelvedata.com/time_series"

# عرض نافذة القمم والقيعان: الكبيرة تعطي الاتجاه الرئيسي، والصغيرة تعطي التصحيح.
# الكتاب يصنّف الاتجاهات لطويل ومتوسط وقصير، والنافذة الضيقة تلتقط القصير فقط،
# فنجعل عرضها يتناسب مع طول التاريخ المتاح حتى تمثّل الاتجاه الأكبر فعلاً.
MIN_PIVOT_WIDTH = 8
MAX_PIVOT_WIDTH = 18
MINOR_PIVOT_WIDTH = 3

# الحد الأدنى للشموع — نحتاج تاريخاً يكفي لتكوّن قمم وقيعان مؤكدة
MIN_CANDLES = 60


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

    if len(frame) < MIN_CANDLES:
        raise NotEnoughData(
            f"عدد الشموع المتاحة {len(frame)} فقط — قليل للتحليل"
        )

    return frame


def pivot_width(count: int) -> int:
    """
    عرض نافذة القمم الكبرى.

    معايرة على سلاسل مولّدة بميل معلوم: العرض ~16 على 400 شمعة يقلّل
    أخطر خطأ ممكن — أن يُقرأ الاتجاه معكوساً — دون أن يكثر «غير محدد».
    النوافذ الأضيق تلتقط الاتجاه القصير وتظنه الاتجاه الرئيسي.
    """
    return max(MIN_PIVOT_WIDTH, min(MAX_PIVOT_WIDTH, count // 25))


def moving_average_conflict(trend: str, price: float, ma200: float, ma50_rising: bool) -> bool:
    """
    المتوسط المتحرك مؤشر اتجاه متأخر: صعوده يدل على اتجاه صاعد ونزوله على هابط.
    فإذا عاكس الدليلان معاً (موقع السعر من متوسط 200 وميل متوسط 50) ما تقوله
    بنية السعر، فالاتجاه غير محسوم — والكتاب يحذّر من التداول ضد الاتجاه.
    """
    if ma200 is None or ma50_rising is None:
        return False

    bullish = trend == "صاعد"
    return (price > ma200) != bullish and ma50_rising != bullish


def rsi_thresholds(trend: str) -> tuple:
    """
    الكتاب: 70/30 هي العتبات المعتادة، لكن في السوق الصاعد يُعتبر 80
    هو التشبع الشرائي، وفي السوق الهابط يُعتبر 20 هو التشبع البيعي.
    """
    if trend == "صاعد":
        return 80.0, 30.0
    if trend == "هابط":
        return 70.0, 20.0
    return 70.0, 30.0


def _build_trade(trend: str, price: float, leg: dict, retr: dict, atr_value: float) -> dict:
    """
    يبني الصفقة من بنية السعر:
      • الدخول من منطقة التصحيح 33-50٪.
      • الوقف خلف مستوى الثلثين — تجاوزه يعني أن التصحيح صار انعكاساً.
      • الهدف الأول قمة/قاع الموجة، والثاني إسقاط طول الموجة من الدخول.
    """
    zone_low = min(retr["entry_low"], retr["entry_high"])
    zone_high = max(retr["entry_low"], retr["entry_high"])

    if retr["state"] == "shallow":
        # لم يصحح بعد بالقدر الكافي — ننتظره داخل المنطقة
        entry_mode = "pullback"
        entry = (zone_low + zone_high) / 2
    else:
        entry_mode = "now"
        entry = price

    invalidation = retr["invalidation"]
    buffer = atr_value * 0.25

    stop_basis = "مستوى 66٪"

    if trend == "صاعد":
        stop_loss = invalidation - buffer
        # لو صار الوقف قريباً جداً من الدخول نرجع للقاع البنيوي للموجة:
        # كسره يعني قاعاً أدنى، أي انكسار تسلسل القيعان الصاعدة
        if entry - stop_loss < atr_value * 0.5:
            stop_loss = leg["low"] - buffer
            stop_basis = "قاع الموجة"
        take_profit_1 = leg["high"]
        take_profit_2 = entry + retr["span"]
    else:
        stop_loss = invalidation + buffer
        if stop_loss - entry < atr_value * 0.5:
            stop_loss = leg["high"] + buffer
            stop_basis = "قمة الموجة"
        take_profit_1 = leg["low"]
        take_profit_2 = entry - retr["span"]

    risk_size = abs(entry - stop_loss)
    reward_size = abs(take_profit_1 - entry)
    risk_reward = reward_size / risk_size if risk_size else 0.0

    return {
        "entry": entry,
        "entry_mode": entry_mode,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "stop_loss": stop_loss,
        "stop_basis": stop_basis,
        "take_profit_1": take_profit_1,
        "take_profit_2": take_profit_2,
        "risk_reward": risk_reward,
    }


def analyze(symbol_key: str, timeframe: str = "1d") -> dict:
    """يقرأ بنية السعر ويؤكدها بالمؤشرات ويرجّع نتيجة جاهزة للعرض."""
    data = fetch_candles(symbol_key, timeframe)

    close = data["Close"]
    price = float(close.iloc[-1])
    last_position = len(data) - 1

    atr_value = float(indicators.atr(data).iloc[-1])
    atr_percent = (atr_value / price) * 100 if price else 0.0
    # هامش نعتبر ضمنه المستويين «متساويين» — نصف مدى الشمعة المعتاد
    tolerance = atr_value * 0.5

    # ── بنية السعر: الاتجاه الكبير يقرر الجهة، والصغير يقرر التوقيت ──
    major_pivots = structure.find_pivots(data, pivot_width(len(data)))
    minor_pivots = structure.find_pivots(data, MINOR_PIVOT_WIDTH)

    major = structure.classify_trend(major_pivots, tolerance)
    minor = structure.classify_trend(minor_pivots, tolerance)
    trend = major["trend"]

    levels = structure.support_resistance(data, major_pivots or minor_pivots, price)

    # ── المؤشرات المؤكدة ──
    ma20 = indicators.sma(close, 20)
    ma50 = indicators.sma(close, 50)
    ma200 = indicators.sma(close, 200)

    ma50_value = None if pd.isna(ma50.iloc[-1]) else float(ma50.iloc[-1])
    ma200_value = None if pd.isna(ma200.iloc[-1]) else float(ma200.iloc[-1])
    ma20_value = price if pd.isna(ma20.iloc[-1]) else float(ma20.iloc[-1])

    # ميل متوسط 50: الكتاب يعتبر اتجاه المتوسط نفسه دليل اتجاه
    ma50_rising = None
    if ma50_value is not None and len(ma50.dropna()) > 5:
        ma50_rising = bool(ma50.iloc[-1] > ma50.iloc[-6])

    rsi_value = float(indicators.rsi(close).iloc[-1])
    overbought, oversold = rsi_thresholds(trend)
    if rsi_value >= overbought:
        rsi_state = "تشبع شرائي"
    elif rsi_value <= oversold:
        rsi_state = "تشبع بيعي"
    else:
        rsi_state = "محايد"

    macd_info = indicators.macd(close)
    stoch_info = indicators.stochastic(data)
    bands = indicators.bollinger(close)
    volume_info = indicators.volume_profile(data)

    line = structure.trendline(
        minor_pivots,
        "trough" if trend == "صاعد" else "peak",
        last_position,
        price,
        tolerance,
    )
    pattern = structure.reversal_pattern(major, trend, price, tolerance)

    confirmations = []
    warnings = []
    signal = "HOLD"
    reasons = [major["reason"]]

    # ── القرار ──
    if trend in ("عرضي", "غير محدد"):
        if trend == "عرضي":
            reasons.append("في السوق العرضي أدوات تتبع الاتجاه لا تعمل — الأفضل الوقوف جانباً")
        signal = "HOLD"
        leg = retr = {}
        trade = {}
    else:
        leg = structure.current_leg(data, major, trend)
        retr = structure.retracement(leg, price, trend) if leg else {}

        if not retr:
            reasons.append("تعذّر قياس الموجة الأخيرة — لا صفقة")
            trade = {}
        elif retr["state"] == "broken":
            signal = "HOLD"
            reasons.append(
                f"التصحيح بلغ {retr['percent'] * 100:.0f}٪ وتجاوز الثلثين — "
                "التصحيح تحوّل إلى انعكاس"
            )
            trade = {}
        elif pattern and pattern.get("complete") and pattern["direction"] != trend:
            signal = "HOLD"
            reasons.append(
                f"{pattern['name']} مكتمل بكسر خط العنق — نمط انعكاسي ضد الاتجاه"
            )
            trade = {}
        elif moving_average_conflict(trend, price, ma200_value, ma50_rising):
            signal = "HOLD"
            reasons.append(
                "بنية السعر تشير لاتجاه والمتوسطات تشير لعكسه — الاتجاه غير محسوم"
            )
            trade = {}
        elif line.get("available") and line.get("broken") and line.get("valid"):
            signal = "HOLD"
            reasons.append(
                f"خط اتجاه معتمد ({line['touches']} لمسات) مُخترق — "
                "من أقوى إنذارات تغيّر الاتجاه"
            )
            trade = {}
        else:
            signal = "BUY" if trend == "صاعد" else "SELL"
            trade = _build_trade(trend, price, leg, retr, atr_value)

            if retr["state"] == "shallow":
                reasons.append(
                    f"التصحيح {retr['percent'] * 100:.0f}٪ فقط — "
                    "ننتظر نزوله لمنطقة الثلث/النصف"
                )
            elif retr["state"] == "zone":
                reasons.append(
                    f"التصحيح {retr['percent'] * 100:.0f}٪ — داخل منطقة الدخول المفضلة"
                )
            else:
                reasons.append(
                    f"التصحيح {retr['percent'] * 100:.0f}٪ — منطقة الثلثين، "
                    "أقل مخاطرة لكنها آخر حد مقبول"
                )

    # ── التأكيدات والتحذيرات ──
    if signal != "HOLD":
        bullish = signal == "BUY"

        if macd_info["bullish"] == bullish:
            confirmations.append("MACD يؤكد الزخم في نفس الجهة")
        else:
            warnings.append("MACD في الجهة المعاكسة — الزخم لا يؤكد")

        if ma50_rising is not None:
            if ma50_rising == bullish:
                confirmations.append("ميل متوسط 50 مع الاتجاه")
            else:
                warnings.append("ميل متوسط 50 ضد الاتجاه")

        if ma200_value is not None:
            if (price > ma200_value) == bullish:
                confirmations.append("السعر في الجهة الصحيحة من متوسط 200")
            else:
                warnings.append("السعر في الجهة المعاكسة من متوسط 200")

        if line.get("available"):
            if line["broken"]:
                # مبدأ المروحة: أول اختراق ليس انعكاساً، لكنه إنذار يُحسب
                warnings.append("خط الاتجاه المبدئي مُخترق — أول إنذار بتغيّر الاتجاه")
            elif line["valid"]:
                confirmations.append(
                    f"خط اتجاه معتمد صامد — {line['touches']} لمسات عبر {line['bars']} شمعة"
                )

        if volume_info["available"]:
            if volume_info["state"] == "متناقص":
                warnings.append("الحجم متناقص — الكتاب يعتبره إنذاراً بقرب انتهاء الاتجاه")
            elif volume_info["state"] == "مرتفع":
                confirmations.append("الحجم مرتفع ويؤكد الحركة")
        else:
            warnings.append("الحجم غير متاح لهذا الرمز — تأكيد ناقص")

        if minor["trend"] == major["trend"]:
            confirmations.append("الاتجاه الصغير عاد مع الكبير — التصحيح انتهى")
        elif minor["trend"] not in ("عرضي", "غير محدد"):
            reasons.append("الاتجاه الصغير ضد الكبير — هذا هو التصحيح نفسه")

        if bullish and stoch_info["state"] == "تشبع شرائي":
            warnings.append("ستوكاستك في تشبع شرائي — الدخول الآن متأخر")
        elif not bullish and stoch_info["state"] == "تشبع بيعي":
            warnings.append("ستوكاستك في تشبع بيعي — البيع الآن متأخر")

        if bullish and rsi_value >= overbought:
            warnings.append(f"RSI {rsi_value:.0f} فوق {overbought:.0f} — تشبع شرائي")
        elif not bullish and rsi_value <= oversold:
            warnings.append(f"RSI {rsi_value:.0f} تحت {oversold:.0f} — تشبع بيعي")

        if pattern and not pattern.get("complete") and pattern["direction"] != trend:
            warnings.append(f"{pattern['name']} قيد التكوّن — راقب خط العنق")

        if bands["squeeze"]:
            reasons.append("نطاقات بولنجر منكمشة — التذبذب على وشك الزيادة")

        if trade and trade["risk_reward"] < 1:
            warnings.append(
                f"العائد مقابل المخاطرة {trade['risk_reward']:.1f} — الهدف أقرب من الوقف"
            )

    score = len(confirmations) - len(warnings)
    if signal == "HOLD":
        confidence = "—"
    elif score >= 3:
        confidence = "عالية"
    elif score >= 0:
        confidence = "متوسطة"
    else:
        confidence = "ضعيفة"

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
        "confidence": confidence,
        "trend": trend,
        "minor_trend": minor["trend"],
        "peak_state": major["peak_state"],
        "trough_state": major["trough_state"],
        "entry": trade.get("entry"),
        "entry_mode": trade.get("entry_mode", "now"),
        "zone_low": trade.get("zone_low"),
        "zone_high": trade.get("zone_high"),
        "stop_loss": trade.get("stop_loss"),
        "stop_basis": trade.get("stop_basis"),
        "take_profit_1": trade.get("take_profit_1"),
        "take_profit_2": trade.get("take_profit_2"),
        "risk_reward": trade.get("risk_reward"),
        "retracement": retr.get("percent") if retr else None,
        "retracement_state": retr.get("state") if retr else None,
        "invalidation": retr.get("invalidation") if retr else None,
        "leg_low": leg.get("low") if leg else None,
        "leg_high": leg.get("high") if leg else None,
        "support": levels["support"],
        "resistance": levels["resistance"],
        "rsi": rsi_value,
        "rsi_state": rsi_state,
        "rsi_overbought": overbought,
        "rsi_oversold": oversold,
        "macd": macd_info,
        "stochastic": stoch_info,
        "bollinger": bands,
        "volume": volume_info,
        "trendline": line,
        "pattern": pattern,
        "ma20": ma20_value,
        "ma50": ma50_value,
        "ma200": ma200_value,
        "atr_percent": atr_percent,
        "risk": risk,
        "reasons": reasons,
        "confirmations": confirmations,
        "warnings": warnings,
        "candles": len(data),
        "major_pivots": len(major_pivots),
        "ma200_available": ma200_value is not None,
        "noisy": timeframe in NOISY_TIMEFRAMES,
        "last_update": data.index[-1].strftime("%Y-%m-%d %H:%M"),
    }
