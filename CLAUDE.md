# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

## What this is

A Telegram bot that runs technical analysis on gold and US stocks on demand.
A user sends `/analyze NVDA 4h`; the bot fetches candles from Twelve Data,
reads the price structure, and replies with a formatted signal (BUY / SELL /
HOLD) including an entry zone, stop loss, and two take-profit levels.

The entire user-facing interface is **Arabic**. The code, identifiers, and
signal keywords are English.

**The decision method is classical technical analysis, not indicator
thresholds.** Trend is defined by the sequence of peaks and troughs; moving
averages and oscillators only confirm. Read "Analysis rules as implemented"
below before changing any decision logic — those rules are the product.

## Layout

| File | Role |
| --- | --- |
| `structure.py` | Price structure: pivots, trend from peaks/troughs, support/resistance, trendlines, retracements, reversal patterns. No indicators. |
| `indicators.py` | Indicator math only: SMA/EMA, RSI, ATR, MACD, Stochastic, Bollinger, volume. Pure functions over a DataFrame. |
| `analysis.py` | Data fetching + the decision engine that combines the two above into one result dict. |
| `main.py` | Telegram wiring, command handlers, and message formatting. |
| `selftest.py` | Synthetic-candle tests. No API key, no quota. |
| `requirements.txt` | Pinned deps: `python-telegram-bot`, `pandas`, `requests`. |
| `Procfile` | `worker: python main.py` — deployed as a long-running worker (polling), not a web dyno. |

**Keep the boundaries:**

- `structure.py` and `indicators.py` never import `telegram`, never fetch, and
  never make decisions — they compute and return facts.
- `analysis.py` owns every decision and every Arabic explanation string.
- `main.py` never does math; it only formats the result dict.

Everything crosses into the presentation layer through the single dict
returned by `analyze()`.

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

# Verify the decision rules — no API key needed, no quota burned
python selftest.py

# Inspect a real symbol end to end without Telegram
TWELVE_DATA_KEY=... python -c "
from analysis import analyze
from main import build_message
print(build_message(analyze('NVDA', '1d')))
"
```

`selftest.py` is the first thing to run after touching decision logic. It
builds candles with known structure and asserts the rules hold: named patterns
map to the expected trend and signal, edge cases (zero volume, flat price,
crash) neither crash nor leak `None`/`nan` into the message, and — the property
that matters most — **no signal is ever issued against the true trend** over
180 generated series. If that last number moves off zero, something in the
trend chain broke.

There is no CI and no linter config. Live checks against the API burn quota, so
prefer `selftest.py` and reserve one targeted live run for confirming the
message renders.

Only one bot process may poll a given token at a time — running `main.py`
locally while a deployment is live will cause Telegram conflict errors.

## The `analyze()` contract

`analyze(symbol_key, timeframe) -> dict` is the one interface into the
presentation layer. `build_message()` in `main.py` reads these keys directly,
so **adding or renaming a key means updating `build_message()` in the same
change**:

- Identity: `symbol`, `timeframe` (Arabic label), `price`, `last_update`,
  `candles`, `major_pivots`
- Decision: `signal`, `confidence`, `trend`, `minor_trend`, `peak_state`,
  `trough_state`
- Trade: `entry`, `entry_mode`, `zone_low`, `zone_high`, `stop_loss`,
  `stop_basis`, `take_profit_1`, `take_profit_2`, `risk_reward`
- Structure: `retracement`, `retracement_state`, `invalidation`, `leg_low`,
  `leg_high`, `support`, `resistance`, `trendline`, `pattern`
- Indicators: `rsi`, `rsi_state`, `rsi_overbought`, `rsi_oversold`, `macd`,
  `stochastic`, `bollinger`, `volume`, `ma20`, `ma50`, `ma200`
- Narrative: `reasons`, `confirmations`, `warnings`
- Flags: `atr_percent`, `risk`, `ma200_available`, `noisy`

On `HOLD`, **every key in the Trade group is `None`** and `confidence` is `"—"`;
`build_message()` skips that block entirely. Any new consumer must handle it.
`retracement`, `leg_low`, and `leg_high` are also `None` whenever the trend is
not directional.

`macd`, `stochastic`, `bollinger`, `volume`, `trendline`, and `pattern` are
nested dicts, not scalars. `pattern` is `{}` when no reversal pattern applies.

## Analysis rules as implemented

These are the product. Change them deliberately, and run `selftest.py` after.

**Trend comes from structure, not from indicators.** `find_pivots()` marks a
bar as a peak when its high dominates `width` bars on each side (troughs
mirror it), then `_alternate()` keeps a clean peak/trough zigzag. A trend is
up only when the last two peaks *and* the last two troughs are both higher;
down when both are lower; sideways otherwise. Comparisons use a tolerance of
0.5×ATR, so "equal" means equal within normal bar noise.

**Two degrees of trend.** Wide pivots give the trend that decides the
direction of the trade; `MINOR_PIVOT_WIDTH = 3` gives the correction inside it,
used for entry timing and for the trendline. `pivot_width()` scales the wide
window with history length (`count // 25`, clamped to 8–18). This constant is
calibrated, not guessed: on generated series with known drift, ~16 minimises
reading the trend backwards while keeping "undecided" rare. **Narrowing it
makes the bot mistake short-term swings for the primary trend and trade against
it** — that was a real bug, caught by `selftest.py`.

**Sideways means no trade.** Trend-following tools do not work in a trendless
market, so the bot stands aside rather than trading the range.

**Entry comes from the retracement, not from the current price.** The last
impulse leg runs from the most recent confirmed trough to the highest high
since it (mirrored in a downtrend). The 33%–50% retracement band is the entry
zone; 66% is the last acceptable level. `retracement_state` is one of
`shallow` (hasn't corrected yet → quote the zone and wait), `zone` (preferred
→ enter now), `deep` (past 50% but within 66% → enter, flagged), or `broken`
(past 66% → the correction became a reversal, no trade).

**Stop marks where the read is wrong**, not a fixed ATR multiple: just beyond
the 66% level, falling back to the leg's own extreme when that would sit within
0.5×ATR of the entry. `stop_basis` records which one was used and the message
must quote it — never hardcode the label.

**Targets come from structure**: target 1 is the leg's peak/trough (the level
that must break for the trend to continue), target 2 projects the leg's own
length from the entry. `risk_reward` is computed against target 1.

**Four things block a trade outright:** a sideways or undecided trend, a
retracement past 66%, a completed double top/bottom against the trend, and a
break of an *established* trendline (3+ touches). A break of a tentative
2-touch line is only a warning — the first break is not yet a reversal.

**Indicators confirm; they never decide.** MACD direction, MA50 slope, price
vs MA200, trendline touches, volume, and the minor trend each add a line to
`confirmations` or `warnings`; `confidence` is their net score. The one place
indicators can veto is `moving_average_conflict()`: when *both* the MA200
position and the MA50 slope oppose the structural trend, the trend is treated
as unresolved and no trade is issued.

**RSI thresholds move with the trend**: 80/30 in an uptrend, 70/20 in a
downtrend, 70/30 otherwise — an overbought reading means less in a bull market.

**Volume is optional.** Spot gold returns zero volume from the provider, so
`volume_profile()` reports `available: False` and the engine degrades to a
warning about the missing confirmation rather than failing.

## Symbols and timeframes

**Adding a symbol:** add an entry to `SYMBOLS` in `analysis.py` — key is what the
user types (uppercased), value is the Twelve Data symbol (e.g. `"GOLD": "XAU/USD"`).
The dict is a convenience alias table, not a whitelist: `fetch_candles()` falls
back to the uppercased user input, so any symbol Twelve Data knows already works.
`/list` shows only the dict keys, and says so.

**Adding a timeframe:** add to `TIMEFRAMES` with a valid Twelve Data `interval`,
an `outputsize`, and an Arabic `label`. Then update the timeframe list in
`WELCOME` in `main.py`, and add it to `NOISY_TIMEFRAMES` if it is short enough to
be mostly noise. Keep `size` at 200+ or MA200 will never be available, and well above `MIN_CANDLES` (60) or there will be too few pivots to read a trend.

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
