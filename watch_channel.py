"""
Listen-only channel watcher.  NO TRADING. NO BROKER. NO DATABASE WRITES.

Use this to verify your Telegram wiring and see exactly which messages the
parser accepts before you let the real bot anywhere near an order.

It deliberately does NOT import config.py, because config.py demands Angel One
credentials at import time. All this needs is the three TELEGRAM_* vars.

Usage:
    python watch_channel.py --list                 # show channels you're in
    python watch_channel.py --history 50           # replay last 50 messages
    python watch_channel.py --history 50 --all     # ...including non-signals
    python watch_channel.py                        # live-watch new messages
    python watch_channel.py --channel @somechannel # override the .env channel
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events

from signal_parser import (parse_signal, parse_targets_only,
                           looks_like_signal, SignalParseError)

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
PHONE = os.getenv("TELEGRAM_PHONE")

C_DIM, C_OK, C_WARN, C_ERR, C_HEAD, C_OFF = (
    "\033[2m", "\033[92m", "\033[93m", "\033[91m", "\033[96m", "\033[0m"
)


def _require_creds():
    missing = [k for k, v in (
        ("TELEGRAM_API_ID", API_ID),
        ("TELEGRAM_API_HASH", API_HASH),
        ("TELEGRAM_PHONE", PHONE),
    ) if not v]
    if missing:
        sys.exit(
            f"{C_ERR}Missing in .env: {', '.join(missing)}{C_OFF}\n"
            f"Create it with:  cp .env.example .env\n"
            f"Then fill the TELEGRAM_* values from https://my.telegram.org\n"
            f"(You do NOT need Angel One credentials to run this script.)"
        )
    try:
        int(API_ID)
    except ValueError:
        sys.exit(f"{C_ERR}TELEGRAM_API_ID must be a number, got: {API_ID!r}{C_OFF}")


def _as_peer(raw):
    """
    Telethon resolves numeric chat IDs only as ints -- passed as a string the
    minus sign is stripped and the ID is misread as a phone number. Usernames
    stay strings.
    """
    raw = str(raw).strip()
    if raw.lstrip("-").isdigit():
        val = int(raw)
        if val < 0 and not str(val).startswith("-100") and len(str(-val)) >= 10:
            print(f"{C_WARN}Note: {val} looks like an unmarked channel ID. "
                  f"Telegram channels need the -100 prefix: -100{-val}{C_OFF}")
        return val
    return raw


def _channels_from_env():
    raw = os.getenv("TELEGRAM_SIGNAL_CHANNELS", "") or ""
    return [_as_peer(c) for c in raw.split(",") if c.strip()]


def _client():
    return TelegramClient(str(BASE_DIR / "telegram"), int(API_ID), API_HASH)


def _sanity_warnings(sig):
    """Flag parses that would misbehave if they reached the trade manager."""
    warns = []
    if sig.action == "BUY":
        if sig.stoploss >= sig.entry_price:
            warns.append(f"stoploss {sig.stoploss} is NOT below entry {sig.entry_price}")
        bad = [t for t in sig.targets if t <= sig.entry_price]
        if bad:
            warns.append(f"target(s) {bad} at/below entry -> would exit instantly")
    else:
        if sig.stoploss <= sig.entry_price:
            warns.append(f"stoploss {sig.stoploss} is NOT above entry {sig.entry_price}")
        bad = [t for t in sig.targets if t >= sig.entry_price]
        if bad:
            warns.append(f"target(s) {bad} at/above entry -> would exit instantly")
    if not sig.targets_explicit:
        warns.append(f"no target in this message - {sig.targets} is a 1.5R placeholder; "
                     f"the bot waits for a follow-up to replace it")
    if "SELL" in sig.raw_text.upper() or "SHORT" in sig.raw_text.upper():
        if sig.action == "SELL":
            warns.append("action read as SELL (writing an option) - confirm that's intended")
    return warns


def _report(text, when=None, show_all=False, quoted=None):
    """Print one message and what the parser makes of it. Returns a verdict."""
    stamp = when.strftime("%Y-%m-%d %H:%M") if when else "now"
    targets = parse_targets_only(text)
    combined = f"{quoted}\n{text}" if quoted else None
    maybe = looks_like_signal(text) or (combined and looks_like_signal(combined))

    if not maybe and not targets and not show_all:
        return "skipped"

    print(f"\n{C_HEAD}{'-' * 66}{C_OFF}")
    print(f"{C_DIM}[{stamp}]{C_OFF}")
    if quoted:
        for line in str(quoted).strip().splitlines():
            print(f"  {C_DIM}> {line}{C_OFF}")
    for line in (text or "(empty)").strip().splitlines():
        print(f"  {C_DIM}|{C_OFF} {line}")

    # A bare target line: the channel's second post, amending the first.
    if targets:
        print(f"  {C_OK}-> TARGET FOLLOW-UP{C_OFF}  {targets}")
        if quoted:
            print(f"     applies to the quoted signal above")
        else:
            print(f"     {C_DIM}no quote; would apply to the most recent open "
                  f"trade still on a placeholder{C_OFF}")
        return "amendment"

    if not maybe:
        print(f"  {C_DIM}-> ignored (no CE/PE + entry + SL keywords){C_OFF}")
        return "skipped"

    # Prefer the reading that recovers real targets, as the listener does.
    sig, err, used_quote = None, None, False
    for cand, viaq in ((text, False), (combined, True)):
        if not cand or not looks_like_signal(cand):
            continue
        try:
            got = parse_signal(cand)
        except SignalParseError as e:
            err = e
            continue
        if sig is None or (got.targets_explicit and not sig.targets_explicit):
            sig, used_quote = got, viaq

    if sig is None:
        print(f"  {C_WARN}-> NOT PARSED: {err}{C_OFF}")
        return "rejected"

    if used_quote:
        print(f"  {C_DIM}(read together with the quoted message){C_OFF}")

    print(f"  {C_OK}-> PARSED{C_OFF}  {sig.action} {sig.symbol} "
          f"{int(sig.strike)} {sig.option_type}  exp {sig.expiry_day:02d}/{sig.expiry_month:02d}/{sig.expiry_year}")
    print(f"     entry {sig.entry_condition} {sig.entry_price}   "
          f"SL {sig.stoploss}   targets {sig.targets}")
    print(f"     broker symbol guess: {sig.tradingsymbol}")

    warns = _sanity_warnings(sig)
    for w in warns:
        print(f"  {C_ERR}!! {w}{C_OFF}")
    return "flagged" if warns else "parsed"


async def _resolve(client, peer):
    """
    Resolve a channel to an entity.

    A private channel has no username, and Telethon can only look up a numeric
    ID that is already cached in its session file. On a fresh session
    get_entity(-100...) therefore fails with "Could not find the input
    entity". Walking the dialog list fixes that: it both finds the channel and
    populates the session cache for next time.
    """
    try:
        return await client.get_entity(peer)
    except Exception as first_error:
        want_marked = peer if isinstance(peer, int) else None
        want_bare = abs(want_marked) % 10**10 if want_marked else None

        async for d in client.iter_dialogs():
            if not (d.is_channel or d.is_group):
                continue
            uname = getattr(d.entity, "username", None)
            if want_marked is not None:
                if d.id == want_marked or getattr(d.entity, "id", None) in (
                    abs(want_marked), want_bare
                ):
                    print(f"{C_DIM}(resolved {peer} via dialog scan){C_OFF}")
                    return d.entity
            elif uname and f"@{uname}".lower() == str(peer).lower():
                return d.entity

        raise first_error


async def cmd_list(client):
    print(f"\n{C_HEAD}Channels and groups on this account{C_OFF}")
    print(f"{C_DIM}Use the @username if it has one, otherwise the numeric ID.{C_OFF}\n")
    print(f"  {'ID':>16}  {'@username':<26} Title")
    print(f"  {'-' * 16}  {'-' * 26} {'-' * 30}")
    async for d in client.iter_dialogs():
        if not (d.is_channel or d.is_group):
            continue
        uname = getattr(d.entity, "username", None)
        print(f"  {d.id:>16}  {('@' + uname) if uname else '-':<26} {d.name}")
    print(f"\n{C_DIM}Put your pick in .env as TELEGRAM_SIGNAL_CHANNELS{C_OFF}")


async def cmd_history(client, channels, limit, show_all):
    tally = {}
    for chan in channels:
        try:
            ent = await _resolve(client, chan)
        except Exception as e:
            print(f"{C_ERR}Could not resolve '{chan}': {e}{C_OFF}")
            print(f"{C_DIM}Run --list to see the exact username/ID.{C_OFF}")
            continue

        title = getattr(ent, "title", chan)
        print(f"\n{C_HEAD}=== Last {limit} messages from {title} ==={C_OFF}")
        n = 0
        async for msg in client.iter_messages(ent, limit=limit):
            n += 1
            quoted = None
            if msg.reply_to is not None:
                try:
                    parent = await msg.get_reply_message()
                    if parent is not None:
                        quoted = parent.message or None
                except Exception:
                    pass
            verdict = _report(msg.message or "", msg.date.astimezone(), show_all, quoted)
            tally[verdict] = tally.get(verdict, 0) + 1

        if n == 0:
            print(f"{C_WARN}No messages returned. Is the account a member of it?{C_OFF}")

    print(f"\n{C_HEAD}{'=' * 66}{C_OFF}")
    print(f"{C_HEAD}Summary{C_OFF}  " + "   ".join(
        f"{k}: {v}" for k, v in sorted(tally.items())) or "nothing scanned")
    if tally.get("flagged"):
        print(f"{C_ERR}{tally['flagged']} message(s) parsed into unsafe numbers "
              f"- do not run live until that's fixed.{C_OFF}")
    if tally.get("amendment"):
        print(f"{C_OK}{tally['amendment']} target follow-up(s) detected and linked "
              f"to their signal.{C_OFF}")
    if tally.get("rejected"):
        print(f"{C_WARN}{tally['rejected']} looked like signals but failed to parse "
              f"- the real bot would silently ignore these.{C_OFF}")


async def cmd_watch(client, channels):
    entities = []
    for chan in channels:
        try:
            ent = await _resolve(client, chan)
            entities.append(ent)
            print(f"{C_OK}Watching:{C_OFF} {getattr(ent, 'title', chan)}")
        except Exception as e:
            print(f"{C_ERR}Could not resolve '{chan}': {e}{C_OFF}")

    if not entities:
        sys.exit(f"{C_ERR}No channels resolved. Run --list to find the right name.{C_OFF}")

    @client.on(events.NewMessage(chats=entities))
    async def _h(event):
        quoted = None
        if event.message.reply_to is not None:
            try:
                parent = await event.message.get_reply_message()
                if parent is not None:
                    quoted = parent.message or None
            except Exception:
                pass
        _report(event.message.message or "", event.message.date.astimezone(),
                show_all=True, quoted=quoted)

    print(f"\n{C_DIM}Listening. Nothing is traded. Ctrl+C to stop.{C_OFF}")
    await client.run_until_disconnected()


async def amain(args):
    client = _client()
    await client.start(phone=PHONE)
    me = await client.get_me()
    print(f"{C_OK}Signed in as{C_OFF} @{me.username or me.first_name} (id={me.id})")

    try:
        if args.list:
            await cmd_list(client)
            return

        channels = [_as_peer(args.channel)] if args.channel else _channels_from_env()
        if not channels:
            sys.exit(
                f"{C_ERR}No channel set.{C_OFF} Either set TELEGRAM_SIGNAL_CHANNELS "
                f"in .env, or pass --channel @name. Run --list to see your options."
            )

        if args.history:
            await cmd_history(client, channels, args.history, args.all)
        else:
            await cmd_watch(client, channels)
    finally:
        await client.disconnect()


def main():
    p = argparse.ArgumentParser(
        description="Listen-only Telegram channel watcher. Places no trades.")
    p.add_argument("--list", action="store_true",
                   help="List every channel/group this account can see, then exit")
    p.add_argument("--history", type=int, metavar="N",
                   help="Replay the last N messages instead of waiting for new ones")
    p.add_argument("--all", action="store_true",
                   help="With --history, also show messages that aren't signal-shaped")
    p.add_argument("--channel", metavar="@name",
                   help="Watch this channel instead of the one(s) in .env")
    args = p.parse_args()

    _require_creds()
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
