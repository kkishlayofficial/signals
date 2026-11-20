"""
Parses trading signals from free-form Telegram messages.

Supports the format:
    CRUDEOIL 17 NOV  8050 CE
    ABOVE :- 120
    STOPLOSS :- 90
    Target 135/150
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

# ---- Known symbols (extend as needed) ----
KNOWN_SYMBOLS = {
    "CRUDEOIL", "CRUDE", "NATURALGAS", "NATGAS", "GOLD", "SILVER",
    "COPPER", "ZINC", "LEAD", "NICKEL", "ALUMINIUM",
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX",
}

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


@dataclass
class ParsedSignal:
    """A parsed buy/sell signal."""
    raw_text: str
    symbol: str                       # e.g. "CRUDEOIL"
    expiry_day: int                   # e.g. 17
    expiry_month: int                 # e.g. 11 (NOV)
    expiry_year: int                  # inferred
    strike: float                     # e.g. 8050
    option_type: str                  # "CE" or "PE"
    entry_condition: str              # "ABOVE" or "BELOW"
    entry_price: float                # trigger price
    stoploss: float
    targets: List[float] = field(default_factory=list)
    action: str = "BUY"               # BUY or SELL
    parsed_at: datetime = field(default_factory=datetime.now)
    # False when the message quoted no usable target and the 1.5R fallback
    # invented one. Signal channels often post the target as a separate reply
    # to the signal, so a provisional target must be replaceable when the
    # follow-up arrives.
    targets_explicit: bool = True

    @property
    def tradingsymbol(self) -> str:
        """Angel One format: CRUDEOIL17NOV268050CE"""
        month_short = {v: k for k, v in MONTHS.items()}[self.expiry_month]
        yy = str(self.expiry_year)[-2:]
        strike_int = int(self.strike) if self.strike == int(self.strike) else self.strike
        return f"{self.symbol}{self.expiry_day:02d}{month_short}{yy}{strike_int}{self.option_type}"

    @property
    def human_summary(self) -> str:
        targets_str = " / ".join(str(t) for t in self.targets)
        return (
            f"{self.action} {self.symbol} {self.expiry_day} "
            f"{list(MONTHS.keys())[self.expiry_month - 1]} {int(self.strike)} {self.option_type}\n"
            f"  Entry: {self.entry_condition} {self.entry_price}\n"
            f"  SL:    {self.stoploss}\n"
            f"  Tgt:   {targets_str}"
        )


class SignalParseError(Exception):
    """Raised when a message is not a valid signal."""


def _leading_numbers(line: str) -> List[float]:
    """
    Numbers at the start of a single line, stopping at the first token that
    isn't one.

    "135/150"              -> [135.0, 150.0]
    "135 , 150"            -> [135.0, 150.0]
    "135-150"              -> [135.0, 150.0]
    "135/150 points soon"  -> [135.0, 150.0]   ("points" ends the run)
    "open target"          -> []
    """
    out: List[float] = []
    for tok in re.split(r"[\s/,&|]+|(?<=\d)-(?=\d)", line.strip()):
        if not tok:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", tok):
            out.append(float(tok))
        else:
            break
    return out


def _validate_sides(action: str, entry: float, stoploss: float,
                    targets: List[float]) -> List[float]:
    """
    Reject a signal whose stoploss sits on the profitable side of entry, and
    drop targets that sit on the losing side.

    Either one means the numbers were misread or the channel made a typo. A
    target below entry on a BUY is satisfied the instant the trade opens, so
    the position would be closed immediately at a loss and logged as a win.
    Refusing to trade a malformed signal is the only safe response.

    Returns the surviving targets.
    """
    if action == "BUY":
        if stoploss >= entry:
            raise SignalParseError(
                f"stoploss {stoploss} is not below entry {entry} for a BUY")
        kept = [t for t in targets if t > entry]
    else:
        if stoploss <= entry:
            raise SignalParseError(
                f"stoploss {stoploss} is not above entry {entry} for a SELL")
        kept = [t for t in targets if t < entry]

    return sorted(kept, reverse=(action == "SELL"))


def _infer_expiry_year(day: int, month: int) -> int:
    """Infer the year of the expiry from today."""
    today = datetime.now()
    # If month is before current month, assume next year
    if month < today.month or (month == today.month and day < today.day):
        return today.year + 1
    return today.year


def parse_signal(text: str) -> ParsedSignal:
    """
    Parse a trading signal message.

    Raises SignalParseError if the text doesn't match a known format.
    """
    if not text or len(text.strip()) < 10:
        raise SignalParseError("Message too short")

    cleaned = text.upper().strip()

    # ---- 1. Find the instrument line ----
    # Pattern: SYMBOL DAY MONTH STRIKE CE/PE
    # e.g. "CRUDEOIL 17 NOV 8050 CE"
    instrument_patterns = [
        # SYMBOL DD MMM STRIKE CE/PE
        r"(?P<symbol>[A-Z]+)\s+(?P<day>\d{1,2})\s+(?P<month>[A-Z]{3,4})\s+(?P<strike>\d+(?:\.\d+)?)\s+(?P<otype>CE|PE)",
        # SYMBOL STRIKE CE/PE DD MMM
        r"(?P<symbol>[A-Z]+)\s+(?P<strike>\d+(?:\.\d+)?)\s+(?P<otype>CE|PE)\s+(?P<day>\d{1,2})\s+(?P<month>[A-Z]{3,4})",
    ]

    instrument_match = None
    for pat in instrument_patterns:
        m = re.search(pat, cleaned)
        if m:
            instrument_match = m
            break

    if not instrument_match:
        raise SignalParseError("No instrument/strike/option-type found")

    symbol = instrument_match.group("symbol")
    # Only accept known symbols (avoid false positives from random words)
    if symbol not in KNOWN_SYMBOLS:
        # Try to fuzzy-match (e.g. CRUDE → CRUDEOIL)
        candidates = [s for s in KNOWN_SYMBOLS if s.startswith(symbol) or symbol.startswith(s)]
        if not candidates:
            raise SignalParseError(f"Unknown symbol: {symbol}")
        symbol = max(candidates, key=len)

    month_str = instrument_match.group("month")[:3]
    if month_str not in MONTHS:
        raise SignalParseError(f"Invalid month: {month_str}")

    day = int(instrument_match.group("day"))
    month = MONTHS[month_str]
    strike = float(instrument_match.group("strike"))
    otype = instrument_match.group("otype")
    year = _infer_expiry_year(day, month)

    # ---- 2. Entry price (ABOVE or BELOW) ----
    # ABOVE :- 120  /  ABOVE 120  /  BUY ABOVE 120
    entry_patterns = [
        (r"ABOVE\s*[:\-]*\s*(\d+(?:\.\d+)?)", "ABOVE"),
        (r"BELOW\s*[:\-]*\s*(\d+(?:\.\d+)?)", "BELOW"),
        (r"BUY\s*(?:AT|@)?\s*[:\-]*\s*(\d+(?:\.\d+)?)", "ABOVE"),
        (r"ENTRY\s*[:\-]*\s*(\d+(?:\.\d+)?)", "ABOVE"),
        (r"CMP\s*[:\-]*\s*(\d+(?:\.\d+)?)", "ABOVE"),
    ]
    entry_condition = None
    entry_price = None
    for pat, cond in entry_patterns:
        m = re.search(pat, cleaned)
        if m:
            entry_condition = cond
            entry_price = float(m.group(1))
            break

    if entry_price is None:
        raise SignalParseError("No entry price found (ABOVE/BELOW/ENTRY)")

    # ---- 3. Stoploss ----
    sl_match = re.search(r"(?:STOPLOSS|STOP\s*LOSS|SL)\s*[:\-]*\s*(\d+(?:\.\d+)?)", cleaned)
    if not sl_match:
        raise SignalParseError("No stoploss found")
    stoploss = float(sl_match.group(1))

    # ---- 4. Targets (one or more, separated by / , or whitespace) ----
    # "Target 135/150" or "Target 135, 150" or "TGT 135 150"
    #
    # Only the REST OF THE TARGET'S OWN LINE is considered, and only the
    # leading run of numbers on it. The old pattern used [\d\.\s/,-]+, whose
    # \s matches newlines, so it swallowed numbers off following lines:
    #   "Target 135/150\n85 points expected"  ->  [135, 150, 85]
    # A target of 85 under an entry of 120 is already satisfied the moment the
    # trade opens, so the position was closed instantly at a loss and reported
    # as "TARGET 3 HIT".
    targets: List[float] = []
    tgt_section = re.search(r"(?:TARGETS?|TGTS?)\s*[:\-]*\s*([^\n]*)", cleaned)
    if tgt_section:
        targets = _leading_numbers(tgt_section.group(1))

    # ---- 5. Action (defaults to BUY) ----
    # SELL must be an actual instruction, not a word in the commentary. The
    # old check was `\bSELL\b` anywhere in the message, so
    #   "CRUDEOIL 8050 PE / ABOVE 120 / SL 90 / market weak, sell side bias"
    # was read as SELL -- writing an option instead of buying one, which is
    # the opposite exposure and a completely different margin requirement.
    # Accept it only at the start of a line, or directly before BELOW/ABOVE/AT.
    action = "BUY"
    if re.search(
        r"^[^A-Z\n]*(?:SELL|SHORT)\b|\b(?:SELL|SHORT)\s+(?:BELOW|ABOVE|AT|@)\b",
        cleaned,
        re.MULTILINE,
    ):
        action = "SELL"

    # ---- 6. Sanity-check the numbers before anyone can trade on them ----
    targets = _validate_sides(action, entry_price, stoploss, targets)

    # ---- 7. Fallback target, AFTER validation ----
    # Runs last on purpose: validation can discard every target it was given
    # (e.g. a signal quoting only targets on the losing side), and a trade with
    # no targets at all can never take profit -- it would sit open until the
    # stoploss caught it. Risk-reward of 1.5x off the validated stop.
    targets_explicit = bool(targets)
    if not targets:
        risk = abs(entry_price - stoploss)
        targets = [round(
            entry_price + risk * 1.5 if action == "BUY" else entry_price - risk * 1.5,
            2,
        )]

    return ParsedSignal(
        raw_text=text,
        symbol=symbol,
        expiry_day=day,
        expiry_month=month,
        expiry_year=year,
        strike=strike,
        option_type=otype,
        entry_condition=entry_condition,
        entry_price=entry_price,
        stoploss=stoploss,
        targets=targets,
        action=action,
        targets_explicit=targets_explicit,
    )


def parse_targets_only(text: str) -> Optional[List[float]]:
    """
    Targets from a message that carries nothing else.

    Signal channels routinely split a call across two posts: the instrument,
    entry and stoploss first, then the target as a reply quoting it. Telethon
    hands us only the reply's own text ("Target 135/150"), which has no
    instrument in it and so can never parse as a signal on its own.

    Returns None when the message isn't a bare target line, including when it
    looks like a full signal in its own right (that belongs to parse_signal).
    """
    if not text:
        return None

    cleaned = text.upper().strip()

    # A full signal carries an option type next to a strike; that's not this.
    if re.search(r"\b(?:CE|PE)\b", cleaned) and re.search(r"\d{3,}", cleaned):
        return None
    # An entry or a stoploss means it's trying to be a signal, not an amendment.
    if re.search(r"\b(?:ABOVE|BELOW|ENTRY|CMP)\b", cleaned):
        return None
    if re.search(r"(?:STOPLOSS|STOP\s*LOSS|\bSL\b)\s*[:\-]*\s*\d", cleaned):
        return None

    # Status updates mention targets but aren't setting them.
    if re.search(r"\b(?:DONE|ACHIEVED|HIT|BOOKED|REACHED|COMPLETED|EXIT|PARTIAL|TRAIL)\b", cleaned):
        return None

    m = re.search(r"(?:TARGETS?|TGTS?)\s*[:\-]*\s*([^\n]*)", cleaned)
    if not m:
        return None

    after = m.group(1).strip()

    values = _leading_numbers(after)
    return values or None


def looks_like_signal(text: str) -> bool:
    """Quick check whether a message *might* be a signal, to avoid wasteful parsing."""
    if not text:
        return False
    upper = text.upper()
    has_option_type = "CE" in upper or "PE" in upper
    has_entry = any(k in upper for k in ("ABOVE", "BELOW", "BUY", "ENTRY", "CMP"))
    has_sl = any(k in upper for k in ("STOPLOSS", "STOP LOSS", "SL "))
    return has_option_type and has_entry and has_sl


# ---- Self-test ----
if __name__ == "__main__":
    sample = """
    CRUDEOIL 17 NOV  8050 CE

    ABOVE :- 120

    STOPLOSS :- 90

    Target 135/150
    """
    sig = parse_signal(sample)
    print(sig.human_summary)
    print("Tradingsymbol:", sig.tradingsymbol)
