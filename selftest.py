"""
اختبار ذاتي بشموع مولّدة — بدون مفتاح API وبدون استهلاك حصة المزود.

يتحقق من أن قواعد الكتاب مطبّقة فعلاً:
  • الاتجاه يُقرأ من تسلسل القمم والقيعان.
  • السوق العرضي لا يعطي صفقة.
  • التصحيح المتجاوز للثلثين يلغي الصفقة.
  • ولا تصدر إشارة في الجهة المعاكسة للاتجاه الحقيقي.

التشغيل:  python selftest.py
"""

import random
import sys

import pandas as pd

import analysis
from main import build_message


def to_frame(closes: list, volume: int = 1000) -> pd.DataFrame:
    """يبني شموع OHLC من سلسلة إغلاق مع ظلال صغيرة."""
    rows = []
    for i, close in enumerate(closes):
        previous = closes[i - 1] if i else close
        rows.append(
            {
                "Open": previous,
                "High": max(previous, close) * 1.006,
                "Low": min(previous, close) * 0.994,
                "Close": close,
                "Volume": volume,
            }
        )
    index = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(rows, index=index)


def zigzag(points: list, per_leg: int, seed: int = 7) -> list:
    """سلسلة تمر بنقاط محددة — لبناء أنماط قمم وقيعان معروفة سلفاً."""
    random.seed(seed)
    out = [points[0]]
    for target in points[1:]:
        start = out[-1]
        for step in range(1, per_leg + 1):
            base = start + (target - start) * step / per_leg
            out.append(base * (1 + random.uniform(-0.0015, 0.0015)))
    return out


def drifting(drift: float, volatility: float, count: int, seed: int) -> pd.DataFrame:
    """مشية عشوائية بميل معلوم — لقياس جودة الإشارة إحصائياً."""
    random.seed(seed)
    price, previous, rows = 100.0, 100.0, []
    for _ in range(count):
        price *= 1 + random.gauss(drift, volatility)
        rows.append(
            {
                "Open": previous,
                "High": max(previous, price) * 1.006,
                "Low": min(previous, price) * 0.994,
                "Close": price,
                "Volume": random.randint(800, 1400),
            }
        )
        previous = price
    index = pd.date_range("2024-01-01", periods=count, freq="D")
    return pd.DataFrame(rows, index=index)


def run(frame: pd.DataFrame) -> dict:
    """يشغّل التحليل على شموع جاهزة بدل جلبها من المزود."""
    analysis.fetch_candles = lambda *args, **kwargs: frame
    return analysis.analyze("TEST", "1d")


# النمط -> (الاتجاه المتوقع، الإشارة المتوقعة)
PATTERNS = {
    "صاعد وتصحيح داخل المنطقة": (
        zigzag([100, 120, 110, 140, 128, 165, 150], 22), "صاعد", "BUY",
    ),
    "صاعد وتصحيح ضحل": (
        zigzag([100, 120, 110, 140, 128, 165, 162], 22), "صاعد", "BUY",
    ),
    "صاعد وتصحيح تجاوز الثلثين": (
        zigzag([100, 120, 110, 140, 128, 165, 131], 22), "صاعد", "HOLD",
    ),
    "هابط وارتداد داخل المنطقة": (
        zigzag([165, 140, 152, 120, 132, 100, 112], 22), "هابط", "SELL",
    ),
    "سوق عرضي": (
        zigzag([100, 112, 100, 112, 100, 112, 106], 22), "عرضي", "HOLD",
    ),
}

EDGES = {
    "حجم صفري (ذهب)": to_frame([100 * 1.004 ** i for i in range(300)], volume=0),
    "سعر ثابت": to_frame([50.0] * 200),
    "انهيار حاد": to_frame([100 * 0.97 ** i for i in range(200)]),
}


def main() -> int:
    failures = []

    print("أنماط بنية السعر")
    print("-" * 58)
    for name, (closes, want_trend, want_signal) in PATTERNS.items():
        result = run(to_frame(closes))
        ok = result["trend"] == want_trend and result["signal"] == want_signal
        print(
            f"  {'✅' if ok else '❌'} {name}: "
            f"{result['trend']} / {result['signal']}"
        )
        if not ok:
            failures.append(f"{name}: توقعنا {want_trend}/{want_signal}")

    print("\nحالات حدّية — المطلوب ألا تنكسر ولا تسرّب قيمة فارغة")
    print("-" * 58)
    for name, frame in EDGES.items():
        try:
            message = build_message(run(frame))
            leaked = "None" in message or "nan" in message.lower()
            print(f"  {'❌' if leaked else '✅'} {name}")
            if leaked:
                failures.append(f"{name}: تسربت قيمة فارغة للرسالة")
        except Exception as error:  # noqa: BLE001 — الاختبار يبلّغ عن أي عطل
            print(f"  ❌ {name}: {type(error).__name__}: {error}")
            failures.append(f"{name}: {error}")

    print("\nجودة الإشارة على ميل معلوم (60 سلسلة لكل حالة)")
    print("-" * 58)
    wanted = {"صاعد": ("BUY", 0.0025), "هابط": ("SELL", -0.0025), "عرضي": (None, 0.0)}
    against = 0
    for truth, (want, drift) in wanted.items():
        counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
        for seed in range(60):
            result = run(drifting(drift, 0.014, 400, seed))
            counts[result["signal"]] += 1
            if want and result["signal"] not in ("HOLD", want):
                against += 1
        print(
            f"  {truth:>6}: شراء {counts['BUY']:>3} · "
            f"بيع {counts['SELL']:>3} · وقوف {counts['HOLD']:>3}"
        )

    print(f"\n  إشارات في الجهة المعاكسة للاتجاه الحقيقي: {against}")
    if against:
        failures.append(f"{against} إشارة ضد الاتجاه الحقيقي")

    print("\n" + "=" * 58)
    if failures:
        print(f"❌ فشل {len(failures)}:")
        for item in failures:
            print("   ·", item)
        return 1

    print("✅ كل الاختبارات نجحت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
