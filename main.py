"""
بوت تنبيهات تيليجرام للذهب والأسهم الأمريكية.
يحلل عند الطلب ويرسل النتيجة منسّقة.
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

<i>⚠️ التحليل مبني على مؤشرات فنية فقط. القرار قرارك، والمخاطرة عليك.</i>"""


def format_price(value: float) -> str:
    """تنسيق السعر حسب حجمه."""
    if value is None:
        return "—"
    if value >= 100:
        return f"{value:,.2f}"
    return f"{value:.2f}"


def build_message(result: dict) -> str:
    """يحوّل نتيجة التحليل لرسالة تيليجرام."""
    emoji = SIGNAL_EMOJI[result["signal"]]

    lines = [
        f"<b>📊 {result['symbol']} — {result['timeframe']}</b>",
        "",
        f"السعر الحالي: <b>{format_price(result['price'])}</b>",
        "",
        f"{emoji} <b>{result['signal']}</b>",
    ]

    if result["signal"] != "HOLD":
        lines += [
            "",
            f"📍 دخول: <code>{format_price(result['entry'])}</code>",
            f"🛑 وقف الخسارة: <code>{format_price(result['stop_loss'])}</code>",
            f"🎯 هدف 1: <code>{format_price(result['take_profit_1'])}</code>",
            f"🎯 هدف 2: <code>{format_price(result['take_profit_2'])}</code>",
        ]

    lines += [
        "",
        f"📈 الاتجاه: <b>{result['trend']}</b>",
        f"📉 RSI: {result['rsi']:.0f} — {result['rsi_state']}",
        f"🔻 دعم: {format_price(result['support'])}",
        f"🔺 مقاومة: {format_price(result['resistance'])}",
        f"⚠️ المخاطرة: <b>{result['risk']}</b> (تذبذب {result['atr_percent']:.1f}%)",
        "",
        "<b>📋 على أي أساس:</b>",
    ]

    for reason in result["reasons"]:
        lines.append(f"• {reason}")

    if not result["ma200_available"]:
        lines += [
            "",
            "<i>⚠️ تاريخ السعر قصير — التحليل أقل موثوقية.</i>",
        ]

    if result.get("noisy"):
        lines += [
            "",
            "<i>⚠️ فريم قصير — إشارات كثيرة وأغلبها ضجيج.</i>",
        ]

    lines += [
        "",
        "<i>مؤشرات فنية فقط، مو توصية. تحقق بنفسك قبل أي صفقة.</i>",
    ]

    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


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
    except Exception as error:
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
    app.add_handler(CommandHandler("list", list_symbols))
    app.add_handler(CommandHandler("analyze", analyze_command))

    logger.info("البوت بدأ العمل")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
