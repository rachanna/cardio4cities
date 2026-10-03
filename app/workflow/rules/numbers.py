"""Number parsing (LLD-2 §4.2, LD-04). Models copy `value_as_written`; code parses it.

A range is never collapsed to a midpoint (WD-04). Anything not matched exactly is
`unparsed`: the figure is shown only as written and never compared.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

PERCENT, PER_100K, COUNT = "percent", "per_100k", "count"


@dataclass(frozen=True)
class ParsedValue:
    value_num: Decimal | None
    unit: str | None
    lower: Decimal | None = None
    upper: Decimal | None = None
    unparsed: bool = False


UNPARSED = ParsedValue(None, None, unparsed=True)

_NUM = r"\d[\d., ]*\d|\d"
_PCT = r"(?:%|per ?cent|percent)"
_TO = r"(?:-|to)"

_WITH_CI = re.compile(
    rf"^(?P<v>{_NUM})\s*(?P<pct>{_PCT})?\s*\(\s*95\s*%\s*ci\s*:?\s*"
    rf"(?P<lo>{_NUM})\s*{_PCT}?\s*{_TO}\s*(?P<hi>{_NUM})\s*{_PCT}?\s*\)$"
)
_RANGE_PCT = re.compile(rf"^(?P<lo>{_NUM})\s*{_PCT}?\s*{_TO}\s*(?P<hi>{_NUM})\s*{_PCT}$")
_PERCENT = re.compile(rf"^(?P<v>{_NUM})\s*{_PCT}$")
_PER_100K = re.compile(rf"^(?P<v>{_NUM})\s*per\s*100(?:[ ,.]?000)$")
_GROUPED_INT = re.compile(r"^\d{1,3}(?:(?:,\d{3})+|(?:\.\d{3})+|(?: \d{3})+)$")


def parse_number(token: str) -> Decimal | None:
    """One number: thousands separators (',' '.' ' '), decimal point or decimal comma.

    Ambiguous '1,234' or '1.234' is thousands: exactly three digits follow and no
    other separator appears. Anything else ambiguous is None.
    """
    t = token.strip()
    if re.fullmatch(r"\d+", t):
        return Decimal(t)
    if _GROUPED_INT.fullmatch(t):
        return Decimal(re.sub(r"[,. ]", "", t))
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+\.\d+", t):  # 1,234.5
        return Decimal(t.replace(",", ""))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d+", t):  # 1.234,5
        return Decimal(t.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d+\.\d+", t):
        return Decimal(t)
    if re.fullmatch(r"\d+,\d{1,2}", t):  # decimal comma: 1-2 digits, no dot
        return Decimal(t.replace(",", "."))
    return None


_COUNT = re.compile(r"\d{1,3}(?:(?:,\d{3})+|(?:\.\d{3})+|(?: \d{3})+)(?!\d)|\d+")


def read_sample_size(as_written: str | None) -> int | None:
    """The number of people in "n = 1,204", "1 204 adults" or "300": exactly one whole
    number, or None (BD-22: models never produce numbers, LD-04)."""
    if not as_written:
        return None
    text = as_written.replace("\u202f", " ").replace("\u00a0", " ")
    found = _COUNT.findall(text)
    if len(found) != 1 or re.search(r"\d[.,]\d{1,2}(?!\d)", text):
        return None  # several numbers, or a decimal: not a count
    value = parse_number(found[0])
    return int(value) if value is not None and value > 0 else None


def _clean(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"[   ]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _numbers(*tokens: str) -> list[Decimal] | None:
    parsed = [parse_number(t) for t in tokens]
    return None if any(p is None for p in parsed) else [p for p in parsed if p is not None]


def parse_value(value_as_written: str) -> ParsedValue:
    text = _clean(value_as_written)

    if m := _WITH_CI.match(text):
        nums = _numbers(m["v"], m["lo"], m["hi"])
        if nums:
            return ParsedValue(nums[0], PERCENT if m["pct"] else None, nums[1], nums[2])
        return UNPARSED
    if m := _RANGE_PCT.match(text):
        nums = _numbers(m["lo"], m["hi"])
        return ParsedValue(None, PERCENT, nums[0], nums[1]) if nums else UNPARSED
    if m := _PERCENT.match(text):
        nums = _numbers(m["v"])
        return ParsedValue(nums[0], PERCENT) if nums else UNPARSED
    if m := _PER_100K.match(text):
        nums = _numbers(m["v"])
        return ParsedValue(nums[0], PER_100K) if nums else UNPARSED
    if _GROUPED_INT.fullmatch(text):  # a bare '2019' is a year, not a value: unparsed
        nums = _numbers(text)
        return ParsedValue(nums[0], COUNT) if nums else UNPARSED
    return UNPARSED
