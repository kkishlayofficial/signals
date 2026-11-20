"""Central configuration loaded from .env."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")


def _env(key: str, default=None, required: bool = False, cast=str):
    val = os.getenv(key, default)
    if required and (val is None or val == ""):
        raise RuntimeError(f"Missing required env var: {key}")
    if val is None:
        return None
    try:
        return cast(val)
    except Exception as e:
        raise RuntimeError(f"Invalid value for {key}: {val}") from e


# ---- Telegram ----
TELEGRAM_API_ID = _env("TELEGRAM_API_ID", required=True, cast=int)
TELEGRAM_API_HASH = _env("TELEGRAM_API_HASH", required=True)
TELEGRAM_PHONE = _env("TELEGRAM_PHONE", required=True)

def _parse_channel(raw: str):
    """
    Normalise one channel entry.

    Telethon resolves numeric chat IDs only when they are passed as *ints* —
    as a string, `utils.parse_phone` strips the minus sign and the ID gets
    misread as a phone number, so resolution silently fails. Usernames must
    stay strings.

    Channel/supergroup IDs must be in the "marked" -100<id> form. The ID shown
    in a web.telegram.org URL (e.g. #-2928369713) is the *unmarked* form and
    needs the -100 prefix: -1002928369713.
    """
    raw = raw.strip()
    if not raw:
        return None
    if raw.lstrip("-").isdigit():
        val = int(raw)
        if val < 0 and not str(val).startswith("-100") and len(str(-val)) >= 10:
            import warnings
            warnings.warn(
                f"Channel ID {val} looks like an unmarked channel ID. "
                f"Telegram channels need the -100 prefix: -100{-val}",
                stacklevel=2,
            )
        return val
    return raw


_channels = _env("TELEGRAM_SIGNAL_CHANNELS", default="")
TELEGRAM_SIGNAL_CHANNELS = [
    c for c in (_parse_channel(p) for p in _channels.split(",")) if c is not None
]

def _parse_notify_target(raw):
    """
    Where trade notifications go. Accepts either a numeric user ID (from
    @userinfobot) or a @username -- Telethon's get_entity resolves both, and
    requiring the numeric form only meant a username crashed config at import.
    Empty falls back to the user's own Saved Messages (see notifier.py).
    """
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw if raw.startswith("@") else f"@{raw}"


TELEGRAM_NOTIFY_USER_ID = _parse_notify_target(_env("TELEGRAM_NOTIFY_USER_ID", default=""))

# If no channel message at all (not even chatter) arrives for this many
# minutes, the listener assumes its event handler went silently stale after
# a reconnect and forces a fresh one. 0 disables the watchdog.
TELEGRAM_WATCHDOG_IDLE_MINUTES = _env("TELEGRAM_WATCHDOG_IDLE_MINUTES", default="10", cast=float)

# Telethon's live update stream can stall silently (socket stays open, but
# nothing from the channel gets delivered) long before the idle watchdog
# above would notice. Every this-many-seconds the watchdog nudges the
# client with catch_up() -- a cheap local resync (no disconnect, no
# re-login) that flushes any backlog far faster than waiting for the full
# reconnect. 0 disables the nudge.
TELEGRAM_CATCHUP_SECONDS = _env("TELEGRAM_CATCHUP_SECONDS", default="45", cast=float)

# A reply to an older channel message is only stitched onto that quoted
# text (quoted + reply) when the quoted message is this fresh. Without a
# cap, a reply sent hours later to an old (possibly already-rejected)
# signal gets replayed as a brand-new signal -- the reply text itself can
# be anything, e.g. a one-word "Gh".
TELEGRAM_QUOTE_REPLY_MAX_AGE_MINUTES = _env(
    "TELEGRAM_QUOTE_REPLY_MAX_AGE_MINUTES", default="5", cast=float)

# ---- Angel One ----
ANGEL_API_KEY = _env("ANGEL_API_KEY", required=True)
ANGEL_CLIENT_ID = _env("ANGEL_CLIENT_ID", required=True)
ANGEL_PASSWORD = _env("ANGEL_PASSWORD", required=True)
ANGEL_TOTP_SECRET = _env("ANGEL_TOTP_SECRET", default="")

# ---- Trading ----
TRADING_MODE = _env("TRADING_MODE", default="paper").lower()
assert TRADING_MODE in ("paper", "live"), "TRADING_MODE must be 'paper' or 'live'"

DEFAULT_QUANTITY = _env("DEFAULT_QUANTITY", default="1", cast=int)
MAX_OPEN_POSITIONS = _env("MAX_OPEN_POSITIONS", default="3", cast=int)
MAX_CAPITAL_PER_TRADE = _env("MAX_CAPITAL_PER_TRADE", default="10000", cast=float)
PRICE_POLL_INTERVAL = _env("PRICE_POLL_INTERVAL", default="5", cast=int)

# Place a real STOPLOSS_LIMIT order at the exchange as soon as a live entry
# fills, so the position is protected even if this script dies. Only ever
# disable this if you intend to babysit positions manually.
USE_EXCHANGE_STOPLOSS = _env("USE_EXCHANGE_STOPLOSS", default="true").lower() in (
    "1", "true", "yes", "on")

# A stop-LIMIT needs a limit price worse than the trigger, or it may never
# fill in a fast move. This is that gap, as a percentage of the trigger.
SL_LIMIT_BUFFER_PCT = _env("SL_LIMIT_BUFFER_PCT", default="0.5", cast=float)

# How long to wait for a placed order to reach a terminal state before giving
# up on reading its real fill price (seconds).
ORDER_FILL_TIMEOUT = _env("ORDER_FILL_TIMEOUT", default="20", cast=int)

# A PENDING signal whose trigger never came is cancelled after this long, so
# untriggered trades stop consuming MAX_OPEN_POSITIONS forever.
PENDING_TTL_HOURS = _env("PENDING_TTL_HOURS", default="12", cast=float)

# Maximum slippage allowed on entry as a percentage of the trigger price.
# If LTP has moved more than this beyond the trigger, a limit order is placed
# at trigger + slippage instead of a market order. Set to 0 to always use market.
MAX_ENTRY_SLIPPAGE_PCT = _env("MAX_ENTRY_SLIPPAGE_PCT", default="2", cast=float)

# How far (in price points) the LTP is allowed to have already passed the
# entry trigger, at the moment a signal arrives, before it's treated as
# stale and discarded instead of entered. e.g. trigger ABOVE 130 with
# ENTRY_STALE_TOLERANCE_POINTS=3 still enters up to a 130-133 print; above
# that the entry window is considered missed.
ENTRY_STALE_TOLERANCE_POINTS = _env("ENTRY_STALE_TOLERANCE_POINTS", default="3", cast=float)

# ---- Trailing Stop ----
TRAILING_SL_ENABLED = _env("TRAILING_SL_ENABLED", default="false").lower() in (
    "1", "true", "yes", "on")
# Trail distance as a percentage of the peak price.
TRAILING_SL_PCT = _env("TRAILING_SL_PCT", default="5", cast=float)
# Only start trailing once the first target has actually been hit, instead of
# exiting there -- before that the fixed stoploss/target exits apply as usual.
TRAILING_SL_AFTER_TARGET_ONLY = _env("TRAILING_SL_AFTER_TARGET_ONLY", default="true").lower() in (
    "1", "true", "yes", "on")

# ---- Dashboard API ----
DASHBOARD_API_TOKEN = _env("DASHBOARD_API_TOKEN", default="")
DASHBOARD_API_HOST = _env("DASHBOARD_API_HOST", default="127.0.0.1")
DASHBOARD_API_PORT = _env("DASHBOARD_API_PORT", default="8000", cast=int)
DEV_TOOLS = _env("DEV_TOOLS", default="false").lower() in ("1", "true", "yes", "on")

# ---- Paths ----
DB_PATH = BASE_DIR / "trades.db"
SESSION_PATH = BASE_DIR / "telegram.session"
LOG_PATH = BASE_DIR / "logs" / "app.log"
LOG_PATH.parent.mkdir(exist_ok=True)


def summary() -> str:
    """Printable config summary (masks secrets)."""
    def mask(s):
        if not s:
            return "(not set)"
        return s[:3] + "***" + s[-2:] if len(s) > 6 else "***"

    return f"""
    ┌─ CONFIG ──────────────────────────────────────
    │ Mode:              {TRADING_MODE.upper()}
    │ Default quantity:  {DEFAULT_QUANTITY} lot(s)
    │ Max positions:     {MAX_OPEN_POSITIONS}
    │ Max capital/trade: ₹{MAX_CAPITAL_PER_TRADE:,.0f}
    │ Poll interval:     {PRICE_POLL_INTERVAL}s
    │ Exchange stoploss: {'ON' if USE_EXCHANGE_STOPLOSS else 'OFF  <-- UNPROTECTED'}
    │ Entry slippage:    {MAX_ENTRY_SLIPPAGE_PCT}%
    │ Stale tolerance:   {ENTRY_STALE_TOLERANCE_POINTS} pts
    │ Trailing SL:       {'ON (' + str(TRAILING_SL_PCT) + '%)' if TRAILING_SL_ENABLED else 'OFF'}
    │ Pending TTL:       {PENDING_TTL_HOURS}h
    │ Telegram watchdog: {'ON (' + str(TELEGRAM_WATCHDOG_IDLE_MINUTES) + 'min idle)' if TELEGRAM_WATCHDOG_IDLE_MINUTES > 0 else 'OFF'}
    │ Telegram catch-up: {'ON (every ' + str(TELEGRAM_CATCHUP_SECONDS) + 's)' if TELEGRAM_CATCHUP_SECONDS > 0 else 'OFF'}
    │ Telegram channels: {', '.join(str(c) for c in TELEGRAM_SIGNAL_CHANNELS) or '(none)'}
    │ Angel Client ID:   {mask(ANGEL_CLIENT_ID)}
    │ TOTP enabled:      {bool(ANGEL_TOTP_SECRET)}
    └───────────────────────────────────────────────
    """
