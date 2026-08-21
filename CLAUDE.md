# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

## What this is

A Telegram bot that runs technical analysis on gold and US stocks on demand.
A user sends `/analyze NVDA 4h`; the bot fetches candles from Twelve Data,
computes indicators with pandas, and replies with a formatted signal
(BUY / SELL / HOLD) including entry, stop loss, and two take-profit levels.

The entire user-facing interface is **Arabic**. The code, identifiers, and
signal keywords are English.

## Layout

The project is intentionally two files — do not introduce a package structure
or extra layers unless a change genuinely needs it.

| File | Role |
| --- | --- |
| `analysis.py` | Data fetching + all indicator math. Pure logic, no Telegram imports. |
| `main.py` | Telegram wiring, command handlers, and message formatting. |
| `requirements.txt` | Pinned deps: `python-telegram-bot`, `pandas`, `requests`. |
| `Procfile` | `worker: python main.py` — deployed as a long-running worker (polling), not a web dyno. |
| `.gitignore` | `.env`, `__pycache__/`, `*.pyc`. |

**Keep the boundary:** `analysis.py` must never import from `telegram` or
produce display strings with markup. `main.py` must never do indicator math.
Everything crosses the boundary through the single dict returned by
`analyze()`.

## Environment variables

Both are required at runtime; neither has a default and neither is committed.

- `BOT_TOKEN` — Telegram bot token. Missing → `main()` exits with `SystemExit`.
- `TWELVE_DATA_KEY` — API key from twelvedata.com. Missing → `fetch_candles()`
  raises `NotEnoughData`, which the user sees as a normal error message.

Locally, put them in a `.env` (git-ignored) and export them, or pass them
inline. There is no dotenv loader in the code — the process must already have
them in its environment.

## Running and checking work

```bash
pip install -r requirements.txt

# Run the bot (long-polling; drops pending updates on startup)
BOT_TOKEN=... TWELVE_DATA_KEY=... python main.py

# Exercise the analysis path without Telegram — the fastest feedback loop
TWELVE_DATA_KEY=... python -c "
from analysis import analyze
from main import build_message
print(build_message(analyze('NVDA', '1d')))
"
```

There is **no test suite, no linter config, and no CI**. Verification is manual:
run the snippet above against a couple of symbols and timeframes, and confirm
the module still imports cleanly (`python -c "import main, analysis"`). Do not
claim a change is tested when it was only imported. Every live check burns API
quota, so prefer one targeted run over a sweep across symbols.

Only one bot process may poll a given token at a time — running `main.py`
locally while a deployment is live will cause Telegram conflict errors.

## The `analyze()` contract

`analyze(symbol_key, timeframe) -> dict` is the one interface between the two
modules. `build_message()` in `main.py` reads these keys directly, so **adding
or renaming a key means updating `build_message()` in the same change**:

`symbol`, `timeframe` (the Arabic label, not the key), `price`, `signal`,
`entry`, `entry_mode`, `zone_low`, `zone_high`, `extension`, `ma20`,
`stop_loss`, `take_profit_1`, `take_profit_2`, `trend`, `rsi`, `rsi_state`,
`atr_percent`, `risk`, `support`, `resistance`, `reasons`, `candles`,
`ma200_available`, `noisy`, `last_update`.

When `signal == "HOLD"`, the five trade-level keys (`entry`, `stop_loss`,
`take_profit_1`, `take_profit_2`, and the zone bounds) are `None`, and
`build_message()` skips that block entirely. Any new consumer must handle that.

`last_update` and `candles` are currently computed but not rendered — they are
available if a message ever needs them.

## Analysis rules as implemented

Change these deliberately; they define the bot's output.

- **Indicators:** SMA 20 / 50 / 200, Wilder RSI(14) via `ewm(alpha=1/14)`,
  Wilder ATR(14) on true range. `find_levels()` takes support/resistance from
  the nearest high above and low below the current price over the last 40 candles.
- **Trend:** +1 if price is above MA50, +1 if above MA200 (−1 each if below).
  Score ≥ 2 → صاعد, ≤ −2 → هابط, else عرضي. If there are fewer than 200 candles,
  MA200 is unavailable, the score cannot reach ±2, and the trend is always عرضي —
  which forces HOLD. This is why `ma200_available` exists and why the message
  carries a reliability warning.
- **Signal:** BUY when trend is صاعد and RSI < 70; SELL when هابط and RSI > 30;
  otherwise HOLD.
- **Extension / entry mode:** `extension = (price − MA20) / ATR`. Past
  `EXTENSION_LIMIT = 1.0` ATR in the signal's direction, `entry_mode` becomes
  `"pullback"` and the bot quotes an entry *zone* instead of a price; otherwise
  `"now"` with a direct entry at the current price.
- **Levels:** stop loss at 1.5× ATR against the entry, targets at 2× and 3.5× ATR
  in favor. All derived from `entry`, not from `price` — so pullback entries move
  the whole set.
- **Risk label:** by `atr_percent` — < 1.5% منخفضة, < 3.5% متوسطة, else عالية.
- **`reasons`** is an ordered list of Arabic strings built up during analysis and
  rendered as bullets. Append to it when adding a rule so the user sees the "why".

## Symbols and timeframes

**Adding a symbol:** add an entry to `SYMBOLS` in `analysis.py` — key is what the
user types (uppercased), value is the Twelve Data symbol (e.g. `"GOLD": "XAU/USD"`).
The dict is a convenience alias table, not a whitelist: `fetch_candles()` falls
back to the uppercased user input, so any symbol Twelve Data knows already works.
`/list` shows only the dict keys, and says so.

**Adding a timeframe:** add to `TIMEFRAMES` with a valid Twelve Data `interval`,
an `outputsize`, and an Arabic `label`. Then update the timeframe list in
`WELCOME` in `main.py`, and add it to `NOISY_TIMEFRAMES` if it is short enough to
be mostly noise. Keep `size` at 200+ or MA200 will never be available.

**Case gotcha:** `1M` (monthly) and `1m` (one minute) differ only by case.
`analyze_command()` keeps the raw argument when it matches a `TIMEFRAMES` key
exactly and lowercases it otherwise — so `1M` stays monthly while `1D` still
resolves to `1d`. Preserve that behavior when touching argument parsing.

## Error handling convention

`NotEnoughData` is the *expected* failure channel. Its message is shown to the
user verbatim, so it must always be written in Arabic and be actionable. It is
raised for: a missing API key, a network/parse failure, a provider
`status=error` payload (including rate-limit and unknown-symbol responses),
missing OHLC columns, and fewer than 60 usable candles.

Anything else escaping `analyze()` is caught by the broad `except Exception` in
`analyze_command()`, logged with `logger.exception`, and shown as a generic
"couldn't analyze" message. Do not let internal detail reach the user through
that path.

The bot posts a "⚡ أحلل…" placeholder first and then **edits** it with the
result or the error. Keep that pattern for new commands that do slow work.

## Style conventions

- Module and function docstrings are Arabic one-liners; inline comments are
  Arabic. Match that — do not translate existing comments to English.
- All user-facing strings are Arabic and are sent with
  `parse_mode=ParseMode.HTML` (`<b>`, `<code>`, `<i>` — not Markdown). Escape or
  avoid raw `<`/`&` in interpolated values.
- Signal keywords stay English (`BUY` / `SELL` / `HOLD`) and are the keys of
  `SIGNAL_EMOJI`; trend and risk labels stay Arabic.
- Prices are rendered only through `format_price()` (thousands separator at
  ≥ 100, two decimals, `—` for `None`). Never f-string a raw price into a message.
- Type hints on function signatures; handlers are `async def` taking
  `(update, context)` and registered via `CommandHandler` in `main()`.
- Every analysis message ends with the "technical indicators only, not advice"
  disclaimer. Keep it — do not soften or remove it, and do not add language that
  frames output as financial advice.
- 4-space indent, snake_case, standard library → third party → local import order.

## Git workflow

Commit messages in this repo are short imperative English summaries
("Update main.py", "Enhance timeframe handling and add warnings"). Match that.

Work on the branch you were assigned, commit, and push with
`git push -u origin <branch>`. Never commit `.env` or a real `BOT_TOKEN` /
`TWELVE_DATA_KEY`; if a key appears in a diff, stop and flag it rather than
committing.
