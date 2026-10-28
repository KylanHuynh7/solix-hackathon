"""Deterministic parsers for regulated and commercial fields. No model calls, no network.

Every parser returns a contracts Field. Nothing is guessed: when a value cannot be
determined it is None, status is needs_review, and reason says why in plain English.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date

from contracts.schemas import Field, FieldStatus

_V = FieldStatus.verified
_R = FieldStatus.needs_review


def _field(value, raw, status, reason=None, unit=None) -> Field:
    return Field(value=value, unit=unit, raw=raw, evidence=raw, status=status, reason=reason)


# --- email cleaning -------------------------------------------------------

_ATTRIBUTION = re.compile(r"^On .* wrote:$")
_SIGN_OFF = re.compile(
    r"^(?:(?:best|best regards|regards|thanks|sincerely),?|--\s?)$", re.IGNORECASE
)


@dataclass
class CleanedEmail:
    new_text: str
    quoted_text: str
    signature: str


def clean_email(body: str) -> CleanedEmail:
    lines = body.splitlines()
    kept: list[str] = []
    quoted: list[str] = []
    in_quote = False
    for line in lines:
        if not in_quote and _ATTRIBUTION.match(line.strip()):
            in_quote = True
        if in_quote or line.startswith(">"):
            quoted.append(line)
        else:
            kept.append(line)

    sig_start = next((i for i, ln in enumerate(kept) if _SIGN_OFF.match(ln.strip())), None)
    if sig_start is None:
        new_lines, sig_lines = kept, []
    else:
        new_lines, sig_lines = kept[:sig_start], kept[sig_start:]

    return CleanedEmail(
        new_text="\n".join(new_lines).strip(),
        quoted_text="\n".join(quoted).strip(),
        signature="\n".join(sig_lines).strip(),
    )


# --- NDC ------------------------------------------------------------------

_HYPHEN_SHAPES = {(4, 4, 2), (5, 3, 2), (5, 4, 1)}
_NDC_PREFIX = re.compile(r"^\s*NDC\s*:?\s*", re.IGNORECASE)


def _ten_digit_candidates(digits: str) -> list[str]:
    return [f"{digits[:a]}-{digits[a:a + b]}-{digits[a + b:]}" for a, b, _ in sorted(_HYPHEN_SHAPES)]


def parse_ndc(raw: str, known_ndcs: set[str]) -> Field:
    text = _NDC_PREFIX.sub("", raw or "").strip()

    if re.fullmatch(r"\d+-\d+-\d+", text):
        segs = text.split("-")
        shape = tuple(len(s) for s in segs)
        if shape in _HYPHEN_SHAPES:
            reason = None if text in known_ndcs else "NDC is well-formed but not in the known NDC list"
            return _field(text, raw, _V, reason)
        if shape == (5, 4, 2):
            return _from_eleven_digit(segs, raw, known_ndcs)
        return _field(None, raw, _R, "hyphenated NDC does not match a recognised 4-4-2, 5-3-2, 5-4-1 or 5-4-2 layout")

    if re.fullmatch(r"\d{11}", text):
        return _from_eleven_digit([text[:5], text[5:9], text[9:]], raw, known_ndcs)

    if re.fullmatch(r"\d{10}", text):
        found = [c for c in _ten_digit_candidates(text) if c in known_ndcs]
        if len(found) == 1:
            return _field(found[0], raw, _R, "unhyphenated 10-digit NDC is ambiguous to segment; only one layout matches a known NDC, confirm it")
        return _field(None, raw, _R, "unhyphenated 10-digit NDC is ambiguous to segment and no single known NDC matches")

    return _field(None, raw, _R, "could not recognise an NDC in this text")


def _from_eleven_digit(segs: list[str], raw: str, known_ndcs: set[str]) -> Field:
    candidates: list[str] = []
    for i, seg in enumerate(segs):
        if seg.startswith("0"):
            trimmed = segs[:i] + [seg[1:]] + segs[i + 1:]
            cand = "-".join(trimmed)
            if cand not in candidates:
                candidates.append(cand)
    found = [c for c in candidates if c in known_ndcs]
    if len(found) == 1:
        return _field(found[0], raw, _V, "11-digit 5-4-2 NDC converted to 10-digit; exactly one candidate is a known NDC")
    if not found:
        return _field(None, raw, _R, "11-digit NDC has no candidate 10-digit form in the known NDC list")
    return _field(None, raw, _R, "11-digit NDC matches more than one known NDC")


# --- expiry ---------------------------------------------------------------

_MONTHS = {
    name.lower(): i
    for i, name in enumerate(calendar.month_name) if name
} | {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}


def _month_end(year: int, month: int) -> str:
    return date(year, month, calendar.monthrange(year, month)[1]).isoformat()


def _expiry_exact(raw: str) -> Field:
    text = (raw or "").strip()

    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text):
        y, mo, d = map(int, m.groups())
        try:
            return _field(date(y, mo, d).isoformat(), raw, _V)
        except ValueError:
            return _field(None, raw, _R, "not a valid calendar date")

    if m := re.fullmatch(r"(\d{4})-(\d{2})", text):
        y, mo = map(int, m.groups())
        if 1 <= mo <= 12:
            return _field(_month_end(y, mo), raw, _V, "no day given; used last day of month")

    if m := re.fullmatch(r"(\d{1,2})/(\d{2})", text):
        mo, yy = map(int, m.groups())
        if 1 <= mo <= 12:
            return _field(_month_end(2000 + yy, mo), raw, _V, "MM/YY pharma convention")
        return _field(None, raw, _R, "month is not between 1 and 12")

    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", text):
        mo, y = map(int, m.groups())
        if 1 <= mo <= 12:
            return _field(_month_end(y, mo), raw, _V, "no day given; used last day of month")
        return _field(None, raw, _R, "month is not between 1 and 12")

    if m := re.fullmatch(r"([A-Za-z]+)\.?,?\s+(\d{4})", text):
        mo = _MONTHS.get(m.group(1).lower())
        if mo:
            return _field(_month_end(int(m.group(2)), mo), raw, _V, "no day given; used last day of month")

    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text):
        a, b, y = map(int, m.groups())
        if a <= 12 and b <= 12:
            return _field(None, raw, _R, "day/month order ambiguous")
        if a > 12 and b <= 12:
            day, month, order = a, b, "DD/MM/YYYY"
        elif b > 12 and a <= 12:
            day, month, order = b, a, "MM/DD/YYYY"
        else:
            return _field(None, raw, _R, "neither part is a valid month")
        try:
            return _field(date(y, month, day).isoformat(), raw, _R, f"day/month order assumed {order} because one part is greater than 12")
        except ValueError:
            return _field(None, raw, _R, "not a valid calendar date")

    return _field(None, raw, _R, "unrecognised expiry format")


# --- quantity and price ---------------------------------------------------

_UNITS = {
    "pen": "pen", "pens": "pen",
    "tablet": "tablet", "tablets": "tablet",
    "carton": "carton", "cartons": "carton",
    "syringe": "syringe", "syringes": "syringe",
    "unit": "unit", "units": "unit",
}


def _quantity_exact(raw: str) -> Field:
    text = (raw or "").strip()
    m = re.fullmatch(r"(\d{1,3}(?:,\d{3})+|\d+)\s*([A-Za-z]+)?", text)
    if not m:
        return _field(None, raw, _R, "could not find a whole-number quantity")
    value = int(m.group(1).replace(",", ""))
    word = m.group(2)
    if word is None:
        return _field(value, raw, _R, "no counting unit stated")
    unit = _UNITS.get(word.lower())
    if unit is None:
        return _field(value, raw, _R, f"unknown unit '{word}'")
    return _field(value, raw, _V, unit=unit)


def _price_exact(raw: str) -> Field:
    text = (raw or "").strip()
    m = re.fullmatch(
        r"(?:(USD)\s*|(\$)\s*)(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*(?:per|/)\s*([A-Za-z]+))?",
        text,
        re.IGNORECASE,
    )
    if not m:
        return _field(None, raw, _R, "could not find a USD price")
    value = float(m.group(3).replace(",", ""))
    basis = m.group(4)
    if basis is None:
        return _field(value, raw, _R, "no pricing basis (per what) stated")
    unit = _UNITS.get(basis.lower())
    if unit is None:
        return _field(value, raw, _R, f"unknown pricing basis '{basis}'")
    return _field(value, raw, _V, unit=f"USD/{unit}")


# --- searching inside a longer quote ---------------------------------------

_MULTIPLE = "multiple candidate values in quote"
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
_UNIT_WORDS = "|".join(sorted(_UNITS, key=len, reverse=True))
_QTY_KNOWN = re.compile(rf"(?<![\w,.]){_NUM}\s*(?:{_UNIT_WORDS})\b", re.IGNORECASE)
_QTY_ANY = re.compile(rf"(?<![\w,.]){_NUM}(?:\s*[A-Za-z]+)?\b", re.IGNORECASE)
_PRICE = re.compile(
    rf"(?<![A-Za-z])(?:USD\s*|\$\s*){_NUM}(?:\.\d+)?(?:\s*(?:per\b|/)\s*[A-Za-z]+)?",
    re.IGNORECASE,
)
_MONTH_WORDS = "|".join(sorted(_MONTHS, key=len, reverse=True))
_EXPIRY = re.compile(
    r"(?<![\w/-])(?:"
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
    r"|\d{1,2}/\d{4}"
    r"|\d{1,2}/\d{2}"
    r"|\d{4}-\d{2}"
    rf"|(?:{_MONTH_WORDS})\.?,?\s+\d{{4}}"
    r")(?![\w/-])",
    re.IGNORECASE,
)


def _search(raw: str, matches: list[str], exact) -> Field:
    """Parse the single distinct match inside the quote; evidence stays the whole quote."""
    parsed = {}
    for m in matches:
        f = exact(m)
        key = (f.value, f.unit, m if f.value is None else None)
        parsed.setdefault(key, (m, f))
    if len(parsed) > 1:
        return _field(None, raw, _R, _MULTIPLE)
    m, f = next(iter(parsed.values()))
    return f.model_copy(update={"raw": m, "evidence": raw})


def parse_quantity(raw: str) -> Field:
    text = raw or ""
    matches = [m.group(0) for m in _QTY_KNOWN.finditer(text)] or [
        m.group(0) for m in _QTY_ANY.finditer(text)
    ]
    return _search(raw, matches, _quantity_exact) if matches else _quantity_exact(raw)


def parse_price(raw: str) -> Field:
    matches = [m.group(0) for m in _PRICE.finditer(raw or "")]
    return _search(raw, matches, _price_exact) if matches else _price_exact(raw)


def parse_expiry(raw: str) -> Field:
    matches = [m.group(0) for m in _EXPIRY.finditer(raw or "")]
    return _search(raw, matches, _expiry_exact) if matches else _expiry_exact(raw)
