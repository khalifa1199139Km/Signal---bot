"""
بوت تنبيهات تيليجرام للذهب والأسهم الأمريكية.
يحلل عند الطلب حسب قواعد التحليل الفني الكلاسيكي ويرسل النتيجة منسّقة.
"""

import logging
import os

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from analysis import SYMBOLS, TIMEFRAMES, NotEnoughData, analyze

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SIGNAL_EMOJI = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}

TREND_EMOJI = {"صاعد": "📈", "هابط": "📉", "عرضي": "➡️", "غير محدد": "❔"}

WELCOME = """<b>📊 بوت تحليل الذهب والأسهم</b>

<b>الاستخدام:</b>
<code>/analyze NVDA</code> — تحليل يومي
<code>/analyze NVDA 4h</code> — فريم 4 ساعات
<code>/analyze GOLD 2h</code> — فريم ساعتين

<b>الفريمات:</b>
<code>1m</code> · <code>5m</code> · <code>15m</code> · <code>30m</code> · <code>45m</code>
<code>1h</code> · <code>2h</code> · <code>4h</code> · <code>8h</code>
<code>1d</code> · <code>1w</code> · <code>1M</code>

<code>/list</code> — الرموز المتابعة
<code>/method</code> — القواعد اللي يشتغل عليها البوت

<i>⚠️ التحليل مبني على مؤشرات فنية فقط. القرار قرارك، والمخاطرة عليك.</i>"""

METHOD = """<b>📐 على أي قواعد يشتغل البوت</b>

<b>1) الاتجاه من القمم والقيعان</b>
مو من موقع السعر من متوسط. صاعد = قمم أعلى وقيعان أعلى.
هابط = قمم أدنى وقيعان أدنى. غير ذلك عرضي.

<b>2) العرضي = وقوف جانباً</b>
أدوات تتبع الاتجاه لا تعمل في سوق بلا اتجاه، والخسائر تجي من محاولة
استخدامها فيه.

<b>3) اتجاهان متداخلان</b>
الاتجاه الكبير يحدد جهة الصفقة، والصغير يحدد توقيت الدخول —
لأن كل اتجاه جزء من اتجاه أكبر منه.

<b>4) الدخول من التصحيح</b>
السوق يصحح عادة ثلث الموجة على الأقل. منطقة <code>33٪—50٪</code>
هي منطقة الدخول، ومستوى <code>66٪</code> هو آخر حد مقبول.

<b>5) الوقف عند تحوّل التصحيح لانعكاس</b>
تجاوز الثلثين معناه أن التصحيح انتهى وصار انعكاساً — فالوقف خلفه.

<b>6) الأهداف من بنية السعر</b>
الهدف الأول قمة الموجة (المقاومة السابقة)، والثاني إسقاط طول
الموجة نفسها من نقطة الدخول.

<b>7) التأكيد قبل الدخول</b>
الحجم يجب أن يزيد مع الاتجاه، وتناقصه إنذار. ويؤكد معه MACD
وميل متوسط 50 وخط الاتجاه وعدد لمساته.

<b>8) موانع الدخول</b>
اختراق خط الاتجاه · قمة أو قاع مزدوج مكتمل · تصحيح تجاوز الثلثين.

<i>المصدر: قواعد التحليل الفني الكلاسيكي — الاتجاه والدعم والمقاومة
وخطوط الاتجاه ونسب التصحيح وأنماط الانعكاس والمؤشرات.</i>"""


def format_price(value: float) -> str:
    """تنسيق السعر حسب حجمه."""
    if value is None:
        return "—"
    if value >= 100:
        return f"{value:,.2f}"
    return f"{value:.2f}"


def structure_line(result: dict) -> str:
    """يوصف بنية السعر بلغة القمم والقيعان."""
    states = {"higher": "أعلى", "lower": "أدنى", "equal": "بنفس المستوى"}
    peak = states.get(result["peak_state"])
    trough = states.get(result["trough_state"])

    if peak and trough:
        return f"قمم {peak} · قيعان {trough}"
    return "لا يوجد تسلسل مؤكد بعد"


def build_trade_block(result: dict) -> list:
    """قسم الصفقة: الدخول والوقف والأهداف."""
    lines = []

    if result["entry_mode"] == "pullback":
        lines += [
            "⏳ <b>ما صحّح كفاية — انتظر</b>",
            f"📍 منطقة الدخول: <code>{format_price(result['zone_low'])}</code>"
            f" — <code>{format_price(result['zone_high'])}</code>",
        ]
    else:
        lines += [
            "✅ <b>السعر داخل منطقة التصحيح — دخول مباشر</b>",
            f"📍 دخول: <code>{format_price(result['entry'])}</code>",
        ]

    lines += [
        f"🛑 وقف: <code>{format_price(result['stop_loss'])}</code>"
        f" <i>(خلف {result['stop_basis']})</i>",
        f"🎯 هدف 1: <code>{format_price(result['take_profit_1'])}</code>"
        f" <i>(قمة/قاع الموجة)</i>",
        f"🎯 هدف 2: <code>{format_price(result['take_profit_2'])}</code>"
        f" <i>(إسقاط الموجة)</i>",
    ]

    if result["risk_reward"] is not None:
        lines.append(f"⚖️ عائد/مخاطرة: <b>{result['risk_reward']:.1f}</b>")

    return lines


def build_message(result: dict) -> str:
    """يحوّل نتيجة التحليل لرسالة تيليجرام."""
    emoji = SIGNAL_EMOJI[result["signal"]]
    trend_emoji = TREND_EMOJI.get(result["trend"], "❔")

    lines = [
        f"<b>📊 {result['symbol']} — {result['timeframe']}</b>",
        "",
        f"السعر الحالي: <b>{format_price(result['price'])}</b>",
        "",
        f"{emoji} <b>{result['signal']}</b>",
    ]

    if result["signal"] != "HOLD":
        lines[-1] += f" · ثقة <b>{result['confidence']}</b>"

    lines += [
        "",
        f"{trend_emoji} <b>البنية:</b> {result['trend']}",
        f"    {structure_line(result)}",
    ]

    if result["leg_low"] is not None:
        lines.append(
            f"    الموجة: <code>{format_price(result['leg_low'])}</code>"
            f" ↔ <code>{format_price(result['leg_high'])}</code>"
        )

    if result["retracement"] is not None:
        lines.append(f"    التصحيح: <b>{result['retracement'] * 100:.0f}٪</b>")

    if result["minor_trend"] not in (result["trend"], "غير محدد"):
        lines.append(f"    الاتجاه الصغير: {result['minor_trend']}")

    if result["signal"] != "HOLD":
        lines.append("")
        lines += build_trade_block(result)

    lines += [
        "",
        f"🔻 دعم: <code>{format_price(result['support'])}</code>"
        f"    🔺 مقاومة: <code>{format_price(result['resistance'])}</code>",
    ]

    macd = result["macd"]
    stoch = result["stochastic"]
    lines += [
        f"📉 RSI: {result['rsi']:.0f} — {result['rsi_state']}"
        f" <i>(عتبات {result['rsi_oversold']:.0f}/{result['rsi_overbought']:.0f})</i>",
        f"📊 MACD: {'صاعد' if macd['bullish'] else 'هابط'}"
        f"    ستوكاستك: {stoch['d']:.0f} — {stoch['state']}",
        f"🔊 الحجم: {result['volume']['state']}",
        f"⚠️ المخاطرة: <b>{result['risk']}</b> (تذبذب {result['atr_percent']:.1f}%)",
    ]

    lines += ["", "<b>📋 على أي أساس:</b>"]
    for reason in result["reasons"]:
        lines.append(f"• {reason}")

    if result["confirmations"]:
        lines += ["", "<b>✅ يؤكد الإشارة:</b>"]
        for item in result["confirmations"]:
            lines.append(f"• {item}")

    if result["warnings"]:
        lines += ["", "<b>⚠️ ينقص أو يعاكس:</b>"]
        for item in result["warnings"]:
            lines.append(f"• {item}")

    if not result["ma200_available"]:
        lines += ["", "<i>⚠️ تاريخ السعر قصير — التحليل أقل موثوقية.</i>"]

    if result.get("noisy"):
        lines += ["", "<i>⚠️ فريم قصير — إشارات كثيرة وأغلبها ضجيج.</i>"]

    lines += [
        "",
        f"<i>آخر تحديث: {result['last_update']} · {result['candles']} شمعة</i>",
        "<i>مؤشرات فنية فقط، مو توصية. الارتداد قد لا يجي — لو اخترق صعوداً بقوة، الصفقة تفوت.</i>",
    ]

    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(METHOD, parse_mode=ParseMode.HTML)


async def list_symbols(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    names = sorted(set(SYMBOLS.keys()))
    text = "<b>الرموز المتابعة:</b>\n\n" + " · ".join(f"<code>{n}</code>" for n in names)
    text += "\n\n<i>تقدر تحلل أي رمز آخر بنفس الأمر.</i>"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "اكتب الرمز بعد الأمر. مثال:\n<code>/analyze NVDA 4h</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    symbol = context.args[0].upper()
    if len(context.args) > 1:
        raw = context.args[1]
        timeframe = raw if raw in TIMEFRAMES else raw.lower()
    else:
        timeframe = "1d"

    if timeframe not in TIMEFRAMES:
        available = " · ".join(TIMEFRAMES.keys())
        await update.message.reply_text(
            f"الفريم <code>{timeframe}</code> غير مدعوم.\nالمتاح: {available}",
            parse_mode=ParseMode.HTML,
        )
        return

    waiting = await update.message.reply_text(f"⚡ أحلل {symbol}...")

    try:
        result = analyze(symbol, timeframe)
        await waiting.edit_text(build_message(result), parse_mode=ParseMode.HTML)
    except NotEnoughData as error:
        await waiting.edit_text(f"⚠️ {error}")
    except Exception:
        logger.exception("فشل تحليل %s", symbol)
        await waiting.edit_text(
            f"❌ ما قدرت أحلل {symbol}.\nتأكد من الرمز وجرّب مرة ثانية."
        )


def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN غير موجود في متغيرات البيئة")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("method", method))
    app.add_handler(CommandHandler("list", list_symbols))
    app.add_handler(CommandHandler("analyze", analyze_command))

    logger.info("البوت بدأ العمل")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
