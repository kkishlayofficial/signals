# 📈 Telegram Trading Signal Automation

Reads trading signals from your Telegram channels in real-time, parses them, and executes trades automatically — in **paper mode** (simulated) or **live mode** (via Angel One SmartAPI).

Switching from paper → real trading is **one line** in your `.env`.

---

## 🧩 What It Does

```
Telegram Signal Channel
        ↓
  [telethon listens]
        ↓
  Signal Parser (regex)
        ↓
  Trade Manager
        ↓
┌─────────────┬─────────────┐
│ PAPER MODE  │  LIVE MODE  │
│ simulated   │  real order │
└─────────────┴─────────────┘
        ↓
  Price Monitor (WebSocket ticks + 5s poll fallback)
        ↓
  Entry → SL / Target / Trailing SL → Exit
        ↓
  Telegram DM back to you
```

**Signal format currently supported:**
```
CRUDEOIL 17 NOV 8050 CE
ABOVE :- 120
STOPLOSS :- 90
Target 135/150
```

The parser is tolerant — it handles variations like `SL`, `TGT`, missing colons, extra whitespace, etc. Extend `KNOWN_SYMBOLS` in `signal_parser.py` for new instruments.

### Signals split across two messages

Many channels post the call first and the target second, as a reply quoting it:

```
message 1:  CRUDEOIL 17 NOV 8050 CE      message 2 (a reply to message 1):
            ABOVE :- 120                   > CRUDEOIL 17 NOV 8050 CE ABOVE :- 120 STOPLOSS :- 90
            STOPLOSS :- 90                 Target 135/150
```

Telethon hands over only the reply's *own* text — `Target 135/150` — with no
instrument and no stoploss in it, so that message can never parse as a signal on
its own. Three things handle this:

1. **Reply linkage.** When a message is a reply, the quoted message is fetched and
   the two are read together.
2. **Target-only messages.** `parse_targets_only()` recognises a bare target line
   and routes it to `TradeManager.on_targets()`, which amends the trade the reply
   points at — or, with no quote, the most recent open trade still on a placeholder.
3. **Amend instead of ignore.** A quoted follow-up re-parses as the same signal, so
   the duplicate guard treats it as an amendment when it carries real targets.

A signal that arrives with no target is registered with a **1.5R placeholder**,
flagged `targets_provisional` in the database, and called out in the Telegram
notification. The placeholder is replaced as soon as the real target arrives.
Targets on the losing side of entry are refused, whenever they arrive.

---

## 🧠 Detailed Logic & Flow (Start to End)

This section walks through **every decision the bot makes**, in the order it
makes it, from the moment the process starts to the moment a position is
closed. File names are given so you can jump straight to the code.

### 1. Startup (`main.py`)

1. `setup_logging()` — logs to both stdout and `logs/app.log`.
2. `db.init_db()` — creates the SQLite schema (`trades.db`) if it doesn't exist.
3. `AngelBroker().login()` — authenticates with Angel One SmartAPI (TOTP or
   interactive OTP), storing a `feed_token` used later for the WebSocket.
4. One Telethon client is created and **shared** between the `TelegramListener`
   (reads signals) and `TelegramNotifier` (sends status DMs) — one login,
   one session file (`telegram.session`).
5. `TradeManager(broker, notifier.send)` is constructed and wired to the
   listener's two callbacks:
   - `listener.on_signal = manager.on_signal` — full signal messages.
   - `listener.on_targets = manager.on_targets` — target-only follow-ups.
6. The dashboard API's `api_runtime` is given read-only references to the
   broker, trade manager, and listener (used by the web dashboard; it never
   drives trading decisions itself).
7. `listener.connect()` resolves every channel in `TELEGRAM_SIGNAL_CHANNELS`
   to a Telethon entity and registers the message handler. If **zero**
   channels resolve, the bot refuses to start (there would be nothing to
   trade on).
8. A startup message ("🚀 Trading bot online…") is sent to
   `TELEGRAM_NOTIFY_USER_ID` (or your own Saved Messages if unset).
9. **No catch-up on restart, by design.** Anything posted while the bot was
   offline is treated as missed on purpose — it is never replayed or
   re-opened. (The listener *does* have a `catch_up()` method for manual use,
   but `main.py`'s normal run path doesn't call it.)
10. Four coroutines run concurrently for the rest of the process's life:
    - `manager.start_monitor()` — the price-monitor loop (section 5 below).
    - `listener.run()` — blocks on Telethon's event loop, invoking the
      message handler on every new channel message.
    - `listener.watchdog()` — detects a silently-stale Telegram connection
      and forces a resync/reconnect (section 2d).
    - `_supervised_dashboard_api()` — runs the FastAPI dashboard, restarting
      it on crash without taking down trading.
11. `SIGINT`/`SIGTERM` trigger a graceful shutdown: the monitor loop is told
    to stop, the Telegram client disconnects, and the broker session is
    logged out. Open positions are **left exactly as they are** — nothing is
    auto-closed on shutdown.

### 2. Reading a Telegram message (`telegram_listener.py`)

Every new message in a monitored channel runs through `_handle_message()`,
**in this exact order**:

**a. Bare-number filter.** If the message is nothing but a number (optionally
with emoji/punctuation stripped), it's almost always a channel posting a
running price update, not an instruction — it's logged as `skipped` and
nothing else runs.

**b. Target-only check** (`parse_targets_only()`). A message is treated as a
*target follow-up*, not a new signal, if **all** of these hold:
- It does **not** contain an option-type (`CE`/`PE`) next to a 3+ digit
  number (that pattern means it's actually a full signal).
- It does **not** contain `ABOVE`/`BELOW`/`ENTRY`/`CMP` (those mean it's
  trying to set an entry, not amend one).
- It does **not** contain a stoploss keyword followed by a number.
- It does **not** contain a status word (`DONE`, `HIT`, `BOOKED`, `EXIT`,
  `PARTIAL`, `TRAIL`, …) — those are commentary on an existing trade, not a
  new target.
- It **does** contain a `TARGET`/`TGT` keyword followed by one or more
  leading numbers on that same line.

  If it matches, the parsed numbers are handed to `manager.on_targets()`
  (section 4) and the function returns — it never reaches the signal parser.

**c. Reply/quote freshness.** If the message is a reply, Telethon fetches the
quoted (parent) message. That quote is only trusted if the parent is **newer
than `TELEGRAM_QUOTE_REPLY_MAX_AGE_MINUTES`** (default 5 min) relative to the
reply. This stops an unrelated reply sent hours later — even a one-word
"Gh" — from being stitched onto a stale, possibly already-rejected signal
and re-parsed as a brand-new one.

**d. Signal parsing attempt.** Two candidate strings are tried, in order:
   1. the message's own text,
   2. `"{quoted}\n{text}"` — the quoted message's text followed by the reply's
      own text (covers the case where a channel replies to its own call with
      extra detail).

   Each candidate is first screened by `looks_like_signal()` — a cheap check
   requiring an option type (`CE`/`PE`) **and** an entry keyword (`ABOVE`,
   `BELOW`, `BUY`, `ENTRY`, `CMP`) **and** a stoploss keyword, to avoid
   wastefully regex-parsing obvious chatter. A candidate that passes this
   screen causes a row to be inserted into the `signals` table
   (status `RECEIVED`) — *before* it's known whether the detailed parse will
   succeed, so even failed parse attempts are auditable.

   `parse_signal()` (section 3) is then run on each surviving candidate. If
   both candidates parse, the one with **explicit** targets wins over one
   that fell back to the 1.5R placeholder. If neither parses, the signal row
   is marked `INVALID` with the parse error(s) attached, and the raw message
   is logged (`channel_messages`, result `ignored`).

**e. Handoff.** A successfully parsed signal is marked `PARSED` in the
signals table (with the full parsed JSON attached) and handed to
`manager.on_signal(sig, signal_id)` (section 4). Whatever trade ID comes
back — or `None` — is used to link the original Telegram message to the
resulting trade row for traceability.

### 2b. The Telegram watchdog (reliability, not trading logic)

Two independent timers, both in `telegram_listener.watchdog()`:

- **Idle watchdog** (`TELEGRAM_WATCHDOG_IDLE_MINUTES`, default 10 min): if
  *nothing at all* — not even channel chatter — has come through in this
  long, the connection is assumed to have silently died (socket open, update
  stream dead). The client is forcibly disconnected and reconnected, which
  re-resolves every channel and re-registers the handler.
- **Catch-up nudge** (`TELEGRAM_CATCHUP_SECONDS`, default 45s of silence):
  a much cheaper local resync (`client.catch_up()`, no disconnect, no
  re-login) that flushes most staleness long before the idle watchdog would
  trigger.

Neither timer affects signal/trade logic directly — they exist purely so a
live signal is never sitting undelivered because the socket looked fine but
wasn't actually receiving updates.

### 3. Parsing a signal (`signal_parser.py` → `parse_signal()`)

Given raw text, in order:

1. **Instrument line.** Tries two regex shapes — `SYMBOL DD MMM STRIKE CE/PE`
   or `SYMBOL STRIKE CE/PE DD MMM` — to pull out `symbol`, `day`, `month`,
   `strike`, `option_type`. The symbol must be in (or fuzzy-match, e.g.
   `CRUDE` → `CRUDEOIL`) the `KNOWN_SYMBOLS` set — this guards against random
   capitalised words in commentary being misread as a ticker.
2. **Expiry year** is inferred: if the stated month/day is already in the
   past relative to today, it's assumed to be next year's expiry.
3. **Entry price & condition.** Tries `ABOVE`, `BELOW`, `BUY (AT/@)`, `ENTRY`,
   `CMP` keywords, in that priority order. `BUY`, `ENTRY`, and `CMP` are all
   treated as an `ABOVE` condition (enter once price reaches/exceeds this
   level).
4. **Stoploss.** `STOPLOSS` / `STOP LOSS` / `SL` followed by a number.
5. **Targets.** Only the text on the *same line* as the `TARGET`/`TGT`
   keyword is scanned, and only the **leading run of numbers** on it
   (`135/150`, `135, 150`, `135-150` all work; a trailing word like `points`
   stops the scan). Scanning was deliberately restricted to one line — the
   old implementation let `\s` cross newlines and could swallow an unrelated
   number from the *next line* of commentary as a bogus extra target.
6. **Action (BUY/SELL).** Defaults to `BUY`. Flips to `SELL` only when
   `SELL`/`SHORT` appears **at the very start of a line**, or immediately
   before `BELOW`/`ABOVE`/`AT`/`@` — not just anywhere in the message. This
   stops something like *"...market weak, sell side bias"* in the commentary
   from flipping a call-buying signal into a short sale (opposite exposure,
   different margin).
7. **Side validation (`_validate_sides`)** — run **before** anything is
   trusted:
   - For a `BUY`: stoploss must be **below** entry, or the signal is rejected
     outright (`SignalParseError`). Any target **not above** entry is
     silently dropped.
   - For a `SELL`: stoploss must be **above** entry; any target **not below**
     entry is dropped.

   This exists because a target below entry on a BUY would be satisfied the
   instant the trade opens — the position would close immediately at a loss
   and get logged as a "target hit", which is exactly backwards.
8. **Fallback target (1.5×R), only after validation.** If every quoted target
   got dropped in step 7 (or none was given at all), one is invented:
   `entry ± 1.5 × |entry − stoploss|`. Running this *after* validation is
   deliberate — a signal that quoted only losing-side targets must still get
   a usable one, or the trade would have no profit-take at all and sit open
   until the stop caught it. `targets_explicit` is set `False` in this case
   so the placeholder can be swapped out later when the real target arrives
   (section 4b).

If any required field (instrument, entry price, stoploss) is missing, or the
side-validation check fails, `SignalParseError` is raised and the message is
treated as not-a-signal (see 2d above) — **no trade is ever created from a
signal that didn't fully and sanely parse.**

### 4. Registering a signal as a trade (`trade_manager.py` → `on_signal()`)

This is the single most important decision point — it decides whether a
parsed signal becomes a live/paper trade, and at what price, **synchronously,
on the spot**. Checks run in this order, and any one of them can reject the
signal outright (each rejection updates the `signals` row with a reason and
stops processing):

1. **Bot paused?** If the dashboard has paused new signal intake
   (`manager.paused`), the signal is dropped. (Already-open positions are
   never affected by this flag.)
2. **Expire stale pending trades first** (`_expire_stale()`) — frees up
   `MAX_OPEN_POSITIONS` slots held by old signals that never triggered,
   *before* checking capacity for the new one.
3. **Capacity check.** If `MAX_OPEN_POSITIONS > 0` and that many trades are
   already open, the signal is rejected (set it to `0` for unlimited).
4. **Instrument resolution** (`broker.find_instrument()`) — looks up the
   exact Angel One token/lot-size/tick-size for this symbol+expiry+strike+
   option-type in the cached instrument master. Failure here (e.g. wrong
   expiry/strike) rejects the signal.
5. **Duplicate detection** (`find_open_duplicate`) — if a trade with the same
   tradingsymbol, action, and entry price is already `PENDING`/`ACTIVE`:
   - If the new message carries **explicit** targets and the existing trade
     is still on its **provisional** 1.5R placeholder, this is treated as an
     *amendment*, not a repost — the real targets are applied to the existing
     trade instead of opening a second position.
   - Otherwise it's a pure repost (e.g. the channel re-sent the same call) and
     is ignored, logged as `DUPLICATE`.
6. **Capital cap** (`MAX_CAPITAL_PER_TRADE`). Estimated cost = `entry_price ×
   quantity × lot_size` (the real premium outlay for a BUY; for a written/SOLD
   option this *under*-estimates the true margin requirement, since the
   premium is a credit, not the real capital at risk). Exceeding the cap
   rejects the signal — raise the cap or lower `DEFAULT_QUANTITY` in `.env`.
7. **Immediate entry-or-discard decision** — a signal's "good" window is
   short, so the bot never parks a trade as "waiting for trigger" the way
   earlier logic (and the now-mostly-vestigial `_check_pending()` fallback)
   did. Instead, it fetches a **fresh LTP right now** and compares it to the
   signal's trigger:
   - **Price hasn't reached the trigger yet** → that's an equal-or-better
     entry than the channel called for (still below an `ABOVE` trigger, or
     still above a `BELOW` trigger), so the trade is entered **immediately**
     at the current market price instead of waiting for price to actually
     touch the quoted level.
   - **Price has already passed the trigger** (`check_trigger_hit()` is
     already true) → the window this call was good for is gone; chasing it
     now is a different trade with different risk, so the signal is
     **discarded** ("🗑 Stale signal discarded…"), never queued, never traded.
8. A `trades` row is inserted with status `PENDING`, the signal is marked
   `VALIDATED`, and the trade is immediately subscribed to the WebSocket
   ticker (so price tracking starts the instant it exists, with no gap
   waiting for the next 5s poll).
9. **Entry executes right away** (`_execute_entry()`, section 4a) using the
   LTP already fetched in step 7 — there's no separate "wait, then enter"
   phase for a freshly-registered signal.

### 4a. Executing the entry (`_execute_entry()`)

1. **Slippage cap.** `limit_cap = trigger × (1 ± MAX_ENTRY_SLIPPAGE_PCT/100)`
   (plus for BUY, minus for SELL). If the current LTP has already moved
   *beyond* that cap, a **LIMIT** order is placed at the cap instead of a
   market order — this stops a fast-moving instrument from filling at a
   wildly worse price than intended. Otherwise a **MARKET** order is used.
   Set `MAX_ENTRY_SLIPPAGE_PCT=0` to always use market orders.
2. **Paper mode:** `PaperBroker.place_market_order()` returns a synthetic
   order ID; the simulated fill price is the LTP, clamped to the slippage
   cap exactly like a real limit order would be.
3. **Live mode:** places the real order via `AngelBroker`, then
   `_await_fill()` polls the order book for up to `ORDER_FILL_TIMEOUT`
   seconds for a `filled` state with a real average price — this is the
   *actual* fill price recorded, not a guess from the last polled LTP (which
   would silently ignore real slippage). If the order dies (`cancelled`/
   `rejected`) that's raised as an error; if it never resolves in time, the
   LTP is used as a fallback with a warning.
   - On any order-placement exception, the attempt is retried up to
     `MAX_ORDER_ATTEMPTS` (3) times; after that the trade is marked
     `CANCELLED` and the signal `REJECTED`, with an explicit notification to
     check the broker for stray orders.
4. The trade row moves to `ACTIVE` (`db.mark_entered`), with the real fill
   price and order ID recorded.
5. **Exchange-side protective stop** (live mode only, if
   `USE_EXCHANGE_STOPLOSS=true`, the default): a real `STOPLOSS_LIMIT` order
   is placed at the broker **immediately after** the entry fills, at the
   signal's stoploss level. The limit price sits `SL_LIMIT_BUFFER_PCT`
   beyond the trigger (so a fast move through the trigger still gets filled
   rather than left resting unmatched). This protects the position even if
   this Python process crashes, the laptop sleeps, or price gaps between two
   poll ticks — it's a *second*, broker-side layer on top of the software
   stop the polling loop also watches. If this order fails to place, you get
   an explicit "⚠️ NO stop at the exchange" warning.
6. A Telegram notification reports the mode, fill price, order type, and the
   slippage versus the originally quoted trigger.

### 4b. Target follow-up messages (`on_targets()`)

When a later message parses as *target-only* (section 2b):

1. It's matched to a trade either by the **quoted message's exact raw
   text** (if it was a reply) or, failing that, the **most recent open trade
   still on a provisional placeholder**.
2. If that trade already has real (non-placeholder) targets, the follow-up
   is ignored — a trade's targets are only ever replaced once.
3. The new targets are filtered to the profitable side of the trade's actual
   entry price (not the original trigger) — anything else is rejected with a
   warning, and the trade keeps its placeholder.
4. Surviving targets are sorted (ascending for BUY, descending for SELL) and
   replace the placeholder; `targets_provisional` is cleared, and a
   notification shows the before/after.

### 5. The price-monitor loop (`start_monitor()` / `_tick()`)

Runs continuously from startup until shutdown, independent of signal
inflow. Two parallel paths feed the same decision logic:

- **WebSocket path (preferred).** `AngelTicker` streams real-time LTP ticks
  over Angel One's SmartStream V2. Every open trade is subscribed by
  instrument token the moment it's created. Ticks arrive on a background
  thread and are handed to the asyncio loop via a queue
  (`_process_tick_queue()`), so each tick is acted on **immediately** —
  there's no polling delay once the WebSocket is live.
- **Polling fallback (`_tick()`), every `PRICE_POLL_INTERVAL` seconds**
  (default 5s; backs off to 30s once the WebSocket is confirmed live). This
  is the only path if the WebSocket couldn't start at all, and otherwise
  exists to catch anything the WebSocket missed (a brand-new instrument not
  yet subscribed, a reconnect gap) and to run the stale-pending sweep every
  tick.

Each tick/poll, for every open (`PENDING` or `ACTIVE`) trade:
- `PENDING` → `_check_pending()` — this is a fallback path only; fresh
  signals from `on_signal()` already decided enter-now-or-discard
  synchronously (section 4, step 7), so a trade is rarely still `PENDING`
  by the time a tick sees it. If one is, the same `check_trigger_hit()` is
  applied and entry fires if crossed.
- `ACTIVE` → `_check_active()` (section 6) — the exit decision.

### 6. Exit decision, every tick (`_check_active()`)

Checked **in this exact priority order** for every active position:

1. **Has the exchange's own resting stop already filled?** (live mode only).
   If Angel One's order book shows the `STOPLOSS_LIMIT` order as `filled`,
   the position is *already flat* at the broker — the bot settles the books
   at that real fill price (`_settle_exchange_stop()`) rather than sending
   a second, redundant closing order (which would open a new position in
   the opposite direction). If that order is instead `dead` (cancelled/
   rejected at the exchange, outside the bot's control), it falls back to
   watching the software stop only, with a warning that it's no longer
   broker-protected.
2. **Software stoploss** (`check_stoploss_hit()`) — checked **first**, ahead
   of targets or trailing, on safety grounds: `LTP ≤ stoploss` for a BUY,
   `LTP ≥ stoploss` for a SELL. If hit, exit immediately with reason
   `STOPLOSS`.
3. **Trailing stop** (only if `TRAILING_SL_ENABLED=true`):
   - If trailing is **already active** on this trade and price has pulled
     back through the current trailing level (`check_trailing_sl_hit()`),
     exit with reason `TRAILING_SL`.
   - If **not yet active**, and `TRAILING_SL_AFTER_TARGET_ONLY=true` (the
     default), trailing only *arms* once price actually reaches the first
     quoted target — before that, the fixed stoploss/target logic applies
     as normal (step 4). With that flag off, trailing arms from the moment
     the trade opens.
   - While armed, `compute_trailing_sl()` recomputes the level every tick:
     for a BUY, `new_tsl = peak_price × (1 − TRAILING_SL_PCT/100)`, where
     `peak_price` is the highest LTP seen since entry; for a SELL it's the
     mirror (`trough_price × (1 + pct/100)`). The level only ever **tightens**
     in the trade's favor — it's discarded if the recomputed value would be
     *worse* than the existing one. The first time it activates, you get a
     one-time "📈 Trailing SL activated" notification.
   - Whenever trailing is active (or just activated this tick), the **fixed**
     target exit below is skipped — once trailing takes over, it's the only
     profit-exit in play. If the activation gate hasn't been satisfied yet,
     execution falls through to step 4.
4. **Fixed target hit** (`check_target_hit()`) — walks the trade's target
   list in order and returns the **first** one crossed (`LTP ≥ target` for a
   BUY, `≤` for a SELL — the bot exits fully on the first target reached; it
   does not scale out across multiple targets). Exits with reason
   `TARGET_<n>` (1-indexed in the notification).

Every exit — `STOPLOSS`, `TRAILING_SL`, `TARGET_n`, or a dashboard-triggered
`MANUAL` close — funnels through the same `_exit_trade()` (section 6a), so
live-order placement, retries, and P&L recording are identical regardless of
*why* the position closed.

### 6a. Executing the exit (`_exit_trade()`)

1. **Live mode — cancel the resting exchange stop FIRST**, before sending the
   closing order. If the stop fired *after* the bot's own market exit, the
   second fill would reverse the position (e.g. sell a long, then the stale
   stop sells again — now short a contract never intended). If the cancel
   attempt instead discovers the stop already filled, that fill is settled
   as the real exit (same path as section 6, step 1) and no new order is
   sent. If the cancel call itself fails, the position is deliberately left
   `ACTIVE` with an urgent alert — better to keep watching it than risk a
   reversal.
2. A market order is placed in the opposite direction (`SELL` closes a
   `BUY`, `BUY` closes a `SELL`) for the full quantity, and
   `_await_fill()` (same mechanism as entry) gets the real fill price.
   - On failure, retried up to `MAX_ORDER_ATTEMPTS`; after that, the trade is
     **left `ACTIVE` on purpose** (the position is still genuinely open at
     the broker) and an escalating "🚨🚨 MANUAL ACTION REQUIRED" alert is
     sent telling you to close it by hand in the Angel One app.
3. **Paper mode** simulates the closing fill at the current LTP with no real
   order.
4. **P&L** (`calculate_pnl()`): `(exit − entry) × quantity × lot_size` for a
   BUY, `(entry − exit) × quantity × lot_size` for a SELL. Fees/brokerage are
   **not** deducted — this is gross P&L only.
5. The trade row moves to `CLOSED`/exited status with the exit price, reason,
   P&L, and exit order ID recorded; the linked signal (if any) is advanced to
   `CLOSED`.
6. A final notification reports the exit reason, fill price, and P&L
   (🟢 for a stop/trail that still ended positive, 🔴 otherwise; 🎯 for a
   target hit).

### 7. Housekeeping that runs alongside trading

- **Stale-pending expiry** (`_expire_stale()`, run both before every new
  signal and on every monitor tick): any `PENDING` trade older than
  `PENDING_TTL_HOURS` (default 12h) whose trigger never came is cancelled
  automatically, so it stops permanently occupying one of your
  `MAX_OPEN_POSITIONS` slots. (In the current flow this mostly guards against
  edge cases, since step 7 of section 4 already resolves most signals to
  enter-now-or-discard on arrival rather than leaving them `PENDING`.)
- **Dashboard pause** (`manager.paused`): stops *new* signals from being
  accepted; never touches positions already open.
- **Manual controls** (triggered from the web dashboard, not Telegram):
  `manual_cancel()` cancels a still-`PENDING` trade; `manual_close()` exits
  an `ACTIVE` one at its last-known LTP through the exact same `_exit_trade()`
  path a stop/target hit would use (so live mode still places a real order).
- **Every state transition** — signal received, parsed, entered, target
  updated, exited, cancelled, error — is logged to the `bot_events` /
  `activity` tables, pushed onto an in-process event bus for the live
  dashboard, and sent as a Telegram DM via `notifier.send()`. The bot never
  changes a trade's state silently.

### 8. Paper vs. Live — what actually differs

Both modes run through **identical** signal parsing, entry-timing, exit
logic, trailing-stop math, and P&L calculation. The only two differences are:
mode-specific order placement (`paper_trading.PaperBroker` returns synthetic
order IDs and simulates fills at the polled LTP, instead of hitting
`AngelBroker`'s real `placeOrder`/order-book calls), and live mode's extra
exchange-side protective stop and real fill-price confirmation. Flipping
`TRADING_MODE` in `.env` is genuinely the only code-level difference — there
is no separate "paper strategy" to keep in sync with a "live strategy".

---

## 🛠 Setup (One-Time)

### 1. Install Python 3.10+
```bash
python3 --version    # should be 3.10 or higher
```

### 2. Create a virtual environment
```bash
cd ~/Desktop/signals
python3 -m venv venv
source venv/bin/activate         # Mac/Linux
# OR on Windows:  venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Create your `.env` file
```bash
cp .env.example .env
```

Then open `.env` in VS Code and fill in:

| Variable | Where to Get It |
|---|---|
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | From [my.telegram.org](https://my.telegram.org) → the app you just created |
| `TELEGRAM_PHONE` | Your phone number with country code, e.g. `+919999999999` |
| `TELEGRAM_SIGNAL_CHANNELS` | The channel usernames (e.g. `@crudeoilsignals`). For multiple, comma-separate. |
| `TELEGRAM_NOTIFY_USER_ID` | Your own Telegram user ID — get it from [@userinfobot](https://t.me/userinfobot) |
| `ANGEL_API_KEY` | From [smartapi.angelbroking.com](https://smartapi.angelbroking.com) → your app |
| `ANGEL_CLIENT_ID` | Your Angel One login ID (e.g. `A123456`) |
| `ANGEL_PASSWORD` | Your Angel One MPIN / trading password |
| `ANGEL_TOTP_SECRET` | The TOTP secret key (if you enabled 2FA). Leave blank if not — you'll be prompted for SMS OTP each login. |
| `TRADING_MODE` | `paper` (default) or `live` |

---

## 🚀 Running

### Watch your channel without trading anything (no Angel One account needed)
```bash
python watch_channel.py --list          # find your channel's @name or numeric ID
python watch_channel.py --history 50    # replay the last 50 messages
python watch_channel.py                 # watch new messages live
```
Listen-only: no broker, no orders, no database writes. It prints every message,
whether the parser accepted it, and flags any parse whose numbers would produce
an unsafe order. Use this first to confirm your channel and signal format.

Note on channel IDs: the ID in a `web.telegram.org` URL is the *unmarked* form.
A channel shown as `#-2928369713` must be written `-1002928369713` in `.env`.

### Test the signal parser
```bash
python main.py --test
```
You should see the sample `CRUDEOIL 17 NOV 8050 CE` signal parsed correctly.
This still reads `.env`, so the file must exist and parse.

### Check today's stats
```bash
python main.py --stats
```

### Start the bot (this is the main command)
```bash
python main.py
```

The **first run** will:
1. Ask Telegram to send a login code to your phone — type it in.
2. Log in to Angel One (and ask for SMS OTP if `ANGEL_TOTP_SECRET` is blank).
3. Download the Angel One instrument master (~1 min, cached for the day).
4. Start listening to your Telegram channel(s).

After that, sessions are persistent — just run `python main.py` and it works.

### Stop the bot
Press `Ctrl+C`. It will finish current operations cleanly.

---

## 🔁 Paper → Live Trading

When you're confident the system works and you want to use real money:

1. Open `.env`
2. Change `TRADING_MODE=paper` → `TRADING_MODE=live`
3. Restart: `python main.py`

That's it. Same code, same signals, same flow — but now real orders go to Angel One.

**⚠️ Strong recommendation:** run `paper` mode for **at least 2 weeks** before switching to `live`, and track the P&L via `python main.py --stats`.

---

## 📂 Project Structure

```
signals/
├── config.py              # Loads all settings from .env
├── signal_parser.py       # Parses signal messages
├── database.py            # SQLite schema + queries
├── angel_broker.py        # Angel One SmartAPI wrapper
├── paper_trading.py       # Paper trading engine
├── trade_manager.py       # Routes signals + runs price monitor
├── telegram_listener.py   # Telethon event listener
├── notifier.py            # Sends updates back to your Telegram
├── main.py                # Entry point
├── watch_channel.py       # Listen-only channel watcher (places no trades)
├── requirements.txt
├── .env.example           # Config template
├── .env                   # YOUR credentials (never commit this)
├── .gitignore
└── trades.db              # SQLite database (auto-created)
```

---

## 🧪 How to Test Safely

1. Start with `TRADING_MODE=paper`
2. Send yourself a test signal via Telegram to a channel you monitor:
   ```
   CRUDEOIL 17 NOV 8050 CE
   ABOVE :- 120
   STOPLOSS :- 90
   Target 135/150
   ```
3. Watch the terminal — you should see the signal registered.
4. When LTP crosses 120, you'll see "ENTERED" notification.
5. On SL or target, you'll see "EXITED" with P&L.

---

## 🛡 Safety Notes

- **Credentials:** `.env` is in `.gitignore`. Never commit it. Never share it.
- **MCX market hours:** Crude Oil trades 9:00 AM – 11:30 PM IST. Outside those hours LTP calls will fail — this is normal.
- **Dynamic IP:** If your home internet IP changes, Angel One will reject API calls. Update the Static IP in your SmartAPI app settings.
- **Session expiry:** Angel One sessions last several hours. If you see auth errors, restart the script.
- **Stoploss:** in live mode a real `STOPLOSS_LIMIT` order is placed at the exchange as
  soon as an entry fills (`USE_EXCHANGE_STOPLOSS=true`), so the position stays protected
  even if this script stops running. The software stop in the polling loop is a second
  layer, not the only one. If the exchange stop can't be placed you get an explicit warning.
- **Lot sizes vs the capital cap:** `MAX_CAPITAL_PER_TRADE` is enforced on the premium
  outlay (`price x lot size x quantity`). CRUDEOIL options have a lot size of 100, so a
  premium of ₹120 costs ₹12,000 and is *skipped* under a ₹10,000 cap. Raise the cap or
  lower `DEFAULT_QUANTITY` to suit.
- **Untriggered signals:** a PENDING signal is auto-cancelled after `PENDING_TTL_HOURS`
  so it stops occupying one of your `MAX_OPEN_POSITIONS` slots.
- **Capital limits:** `MAX_OPEN_POSITIONS` and `MAX_CAPITAL_PER_TRADE` are safety caps. Set them based on your risk tolerance.

---

## 🧰 Extending

### Add a new symbol
Edit `KNOWN_SYMBOLS` in `signal_parser.py`:
```python
KNOWN_SYMBOLS = {
    "CRUDEOIL", "NATURALGAS", ...,
    "YOUR_NEW_SYMBOL",
}
```

### Support a new signal format
Add a regex pattern in `signal_parser.py` → `parse_signal()`.

### Change risk/exit strategy
Edit `paper_trading.py`:
- `check_target_hit()` — currently exits on first target; change to scale out at each.
- `calculate_pnl()` — add brokerage/STT deductions if you want realistic P&L.

---

## 📞 Troubleshooting

| Issue | Fix |
|---|---|
| `Login failed: Invalid totp` | TOTP secret is wrong. Re-enable 2FA in Angel One app, copy the secret key correctly. |
| `No instrument found` | The expiry date / strike may be wrong. Check Angel's instrument master. |
| Telegram asks for code every run | Session file `telegram.session` was deleted or corrupted. It will re-auth; that's fine. |
| `LTP fetch failed` | Market is closed, or static IP changed. Check both. |
| `Not a valid signal` logged for real signals | Format differs from supported patterns — extend `signal_parser.py`. |

---

## 📄 License

Personal use. Use at your own risk — trading involves financial risk.
