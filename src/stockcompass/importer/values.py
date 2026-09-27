"""Turning messy report cells into clean values.

Handles what GIMA, BO and hand-made workbooks throw at us:
- numbers as text with thousand separators, bracket negatives "(1,234)", unicode minus, "PKR"/"Rs"
- percentages "13.%", "(71.0%)", "-17.52%", fractions 0.1447 from Excel-formatted cells
- Excel errors (#DIV/0!, #N/A, #REF!), "NA", "N/A", "-", blank
- dates as YYMMDD (260721), DMMYY with the leading zero dropped (70926), dd/mm/yy, m/d/yyyy h:mm AM,
  "(Thu) 24-Sep-26", Excel serial numbers, real datetime cells. The format is decided per COLUMN,
  by testing every candidate format on all values and keeping the most plausible one.
- codes with lost leading zeros (dept 1 -> "01", section 11 -> "011"), "S011 - Beverage", "01-CGD"
- barcodes destroyed by Excel ("6.2E+11") are detected and dropped (we always key on item code)
"""

from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable

MISSING_TOKENS = {
    "", "-", "--", "—", "–", "NA", "N/A", "N.A", "N.A.", "#N/A", "#DIV/0!", "#DIV/0", "#REF!", "#VALUE!",
    "#NAME?", "#NUM!", "#NULL!", "NULL", "NONE", "NAN", "INF", "-INF", "#N/A N/A", "NIL",
}

_num_clean = re.compile(r"[,\s  ']")
_currency = re.compile(r"^(PKR|RS\.?|RS)\s*", re.I)


def is_missing(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float):
        return math.isnan(v) or math.isinf(v)
    if isinstance(v, str):
        return v.strip().upper() in MISSING_TOKENS
    return False


_SPECIAL_WS = re.compile(r"[\u00a0\u202f\r\n\t\u2018\u2019\u201c\u201d]|  ")


def clean_text(v: Any) -> str:
    if v is None:
        return ""
    if type(v) is str and not _SPECIAL_WS.search(v):
        return v.strip()
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        if v.is_integer():
            return str(int(v))
        return repr(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    s = str(v).replace(" ", " ").replace(" ", " ").replace("\r", " ").replace("\n", " ")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Num:
    value: float | None
    percent: bool = False  # the text carried a % sign


def parse_num(v: Any) -> Num:
    """Parse one cell as a number. Never raises."""
    if v is None or isinstance(v, bool):
        return Num(None)
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return Num(None)
        return Num(float(v))
    if isinstance(v, (datetime, date, timedelta)):
        return Num(None)
    s = clean_text(v)
    if s.upper() in MISSING_TOKENS:
        return Num(None)
    neg = False
    s = s.replace("−", "-")
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    s = _currency.sub("", s)
    pct = False
    if s.endswith("%"):
        pct, s = True, s[:-1].strip()
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    if s.endswith("-") and s[:-1].replace(".", "").replace(",", "").isdigit():  # "123-" trailing minus
        neg, s = True, s[:-1]
    s = _num_clean.sub("", s)
    if s.endswith("."):
        s = s[:-1]  # "13.%" -> "13"
    if not s:
        return Num(None, pct)
    try:
        x = float(s)
    except ValueError:
        return Num(None, pct)
    if math.isnan(x) or math.isinf(x):
        return Num(None, pct)
    return Num(-x if neg else x, pct)


def num(v: Any) -> float | None:
    return parse_num(v).value


def num0(v: Any) -> float:
    x = parse_num(v).value
    return 0.0 if x is None else x


def percent_column(values: Iterable[Any]) -> list[float | None]:
    """Parse a column of percentages into percent units (14.47 = 14.47%).

    Text cells like "14%" are already in percent units. Excel cells formatted as % arrive as fractions
    (0.1447). If no cell carried a % sign and every magnitude is <= 1.5, the column is a fraction column.
    """
    parsed = [parse_num(v) for v in values]
    nums = [p.value for p in parsed if p.value is not None]
    any_pct_text = any(p.percent for p in parsed)
    fraction = bool(nums) and not any_pct_text and all(abs(x) <= 1.5 for x in nums) and any(x != 0 for x in nums)
    out: list[float | None] = []
    for p in parsed:
        if p.value is None:
            out.append(None)
        elif p.percent:
            out.append(p.value)
        else:
            out.append(p.value * 100 if fraction else p.value)
    return out


def pct_value(v: Any, fraction_hint: bool | None = None) -> float | None:
    """Single-cell percent. fraction_hint=True means bare numbers <=1.5 are fractions."""
    p = parse_num(v)
    if p.value is None:
        return None
    if p.percent:
        return p.value
    if fraction_hint or (fraction_hint is None and isinstance(v, float) and abs(p.value) <= 1.5):
        return p.value * 100
    return p.value


# ---------------------------------------------------------------------------------------------
# Codes
# ---------------------------------------------------------------------------------------------

def code_text(v: Any) -> str:
    """A code as text: 235385.0 -> '235385'. Keeps letters (P03, PA6)."""
    if v is None:
        return ""
    if type(v) is int:
        return str(v)
    if type(v) is float and v.is_integer():
        return str(int(v))
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        return str(int(v)) if v.is_integer() else clean_text(v)
    if isinstance(v, int):
        return str(v)
    if type(v) is str:
        return _code_str(v)
    s = clean_text(v)
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s


@functools.lru_cache(maxsize=262144)
def _code_str(v: str) -> str:
    """Text codes repeat a lot in big reports (sections, families, suppliers): remember them."""
    s = clean_text(v)
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s


def item_code(v: Any) -> str:
    s = code_text(v)
    if not s or s.upper() in MISSING_TOKENS:
        return ""
    if re.fullmatch(r"\d+", s):
        return s.lstrip("0") or "0"
    return s.upper()


_dept_re = re.compile(r"^\s*0?([1-9])\b")


def dept_code(v: Any) -> str:
    """'01', '1', 1.0, '01-CGD', '01-FMCG', 'CGD' -> '01'."""
    s = code_text(v).upper()
    if not s or s in MISSING_TOKENS:
        return ""
    m = re.match(r"^0?(\d)(?:\D|$)", s)
    if m:
        return "0" + m.group(1)
    from stockcompass.master.seed import DEPARTMENTS

    for d in DEPARTMENTS:
        for a in d["aliases"] + [d["short"], d["name"].upper()]:
            if s == a.upper() or s.startswith(a.upper() + " "):
                return d["code"]
    return ""


def section_code(v: Any) -> str:
    """'011', 11, '11', 'S011', 'S011 - Beverage', 'S012-DPH' -> '011'."""
    s = code_text(v).upper()
    if not s or s in MISSING_TOKENS:
        return ""
    m = re.match(r"^S?\s*0?(\d{2,3})(?:\D|$)", s)
    if m:
        return m.group(1).zfill(3)
    return ""


def family_code(v: Any) -> str:
    s = code_text(v)
    m = re.match(r"^\s*(\d{1,4})", s)
    return m.group(1).zfill(3) if m else ""


def is_destroyed_barcode(v: Any) -> bool:
    s = clean_text(v).upper()
    return bool(re.fullmatch(r"\d(\.\d+)?E\+\d+", s))


def barcode(v: Any) -> str:
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        # a float with >=12 digits cannot be trusted if it was shown in E notation; keep if exact int
        return str(int(v)) if v.is_integer() and v < 1e14 else ""
    s = clean_text(v)
    if is_destroyed_barcode(s):
        return ""
    return s if re.fullmatch(r"\d{6,14}", s) else ""


# ---------------------------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------------------------
_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}
EXCEL_EPOCH = datetime(1899, 12, 30)
DATE_SENTINELS = {"0", "999999", "99999999", "000000", "00000000"}


def _mk(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000 if y < 70 else 1900
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _digits(v: Any) -> str | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and v >= 0 else None
    s = clean_text(v)
    return s if re.fullmatch(r"\d{4,8}", s) else None


def _p_yymmdd(v):
    s = _digits(v)
    if not s or len(s) != 6:
        return None
    return _mk(int(s[:2]), int(s[2:4]), int(s[4:]))


def _p_ddmmyy(v):
    s = _digits(v)
    if not s or len(s) not in (5, 6):
        return None
    s = s.zfill(6)
    return _mk(int(s[4:]), int(s[2:4]), int(s[:2]))


def _p_mmddyy(v):
    s = _digits(v)
    if not s or len(s) not in (5, 6):
        return None
    s = s.zfill(6)
    return _mk(int(s[4:]), int(s[:2]), int(s[2:4]))


def _p_yyyymmdd(v):
    s = _digits(v)
    if not s or len(s) != 8:
        return None
    return _mk(int(s[:4]), int(s[4:6]), int(s[6:]))


def _p_serial(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        s = clean_text(v)
        if not re.fullmatch(r"\d{5}(\.\d+)?", s):
            return None
        v = float(s)
    if 20000 <= v <= 80000:
        return (EXCEL_EPOCH + timedelta(days=float(v))).date()
    return None


_slash = re.compile(r"^(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AP]M)?)?$", re.I)
_named = re.compile(r"(?:\(\w{3}\)\s*)?(\d{1,2})[\s\-/]([A-Za-z]{3})[A-Za-z]*[\s\-/,]*(\d{2,4})")
_named2 = re.compile(r"([A-Za-z]{3})[A-Za-z]*\s+(\d{1,2}),?\s+(\d{2,4})")


def _slash_parts(v):
    if isinstance(v, (datetime, date)):
        return None
    m = _slash.match(clean_text(v))
    if not m:
        return None
    a, b, c = m.group(1), m.group(2), m.group(3)
    return a, b, c, bool(m.group(7))


def _p_dmy(v):
    p = _slash_parts(v)
    if not p:
        return None
    a, b, c, _ = p
    if len(a) == 4:
        return _mk(int(a), int(b), int(c))
    return _mk(int(c), int(b), int(a))


def _p_mdy(v):
    p = _slash_parts(v)
    if not p:
        return None
    a, b, c, _ = p
    if len(a) == 4:
        return _mk(int(a), int(b), int(c))
    return _mk(int(c), int(a), int(b))


def _p_named(v):
    s = clean_text(v)
    m = _named.search(s)
    if m and m.group(2).upper() in _MONTHS:
        return _mk(int(m.group(3)), _MONTHS[m.group(2).upper()], int(m.group(1)))
    m = _named2.search(s)
    if m and m.group(1).upper() in _MONTHS:
        return _mk(int(m.group(3)), _MONTHS[m.group(1).upper()], int(m.group(2)))
    return None


def _p_native(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


DATE_FORMATS = {
    "native": _p_native,
    "yymmdd": _p_yymmdd,
    "ddmmyy": _p_ddmmyy,
    "mmddyy": _p_mmddyy,
    "yyyymmdd": _p_yyyymmdd,
    "d/m/y": _p_dmy,
    "m/d/y": _p_mdy,
    "d-mon-y": _p_named,
    "excel": _p_serial,
}


def is_date_sentinel(v: Any) -> bool:
    if v is None:
        return True
    s = code_text(v)
    return s in DATE_SENTINELS or s.upper() in MISSING_TOKENS


@dataclass
class DateGuess:
    fmt: str | None
    score: float
    parsed: int
    total: int


def infer_date_format(values: Iterable[Any], ref: date | None = None, prefer: list[str] | None = None) -> DateGuess:
    """Pick the date format that explains the most values most plausibly.

    Plausible = inside [ref - 25y, ref + 3y]. Among formats that parse the same share of values,
    prefer tighter spread and dates closer to the reference date. 5-digit values can only be the
    'leading zero dropped' family (ddmmyy / mmddyy), which settles YYMMDD vs DDMMYY.
    """
    ref = ref or date.today()
    vals = [v for v in values if not is_date_sentinel(v)]
    if len(vals) > 3000:  # a spread-out sample decides the format just as well
        uniq = list(dict.fromkeys(vals))
        step = max(1, len(uniq) // 3000)
        vals = uniq[::step][:3000]
    if not vals:
        return DateGuess(None, 0.0, 0, 0)
    lo, hi = date(ref.year - 25, 1, 1), date(ref.year + 3, 12, 31)
    best = DateGuess(None, 0.0, 0, len(vals))
    for name, fn in DATE_FORMATS.items():
        ds = []
        for v in vals:
            try:
                d = fn(v)
            except Exception:
                d = None
            if d is not None and lo <= d <= hi:
                ds.append(d)
        if not ds:
            continue
        share = len(ds) / len(vals)
        ords = sorted(x.toordinal() for x in ds)
        spread = (ords[-1] - ords[0]) / 365.0
        median = ords[len(ords) // 2]
        dist = abs(median - ref.toordinal()) / 365.0
        score = share * 100 - min(spread, 30) * 0.3 - min(dist, 30) * 0.4
        if name == "native":
            score += 5
        if prefer and name in prefer:
            score += 2
        if name in ("d/m/y", "m/d/y"):
            # evidence from a component > 12 decides day-first vs month-first outright
            firsts = [p for p in (_slash_parts(v) for v in vals) if p]
            day_first_proof = any(len(a) <= 2 and int(a) > 12 for a, b, c, _ in firsts)
            month_first_proof = any(len(a) <= 2 and int(b) > 12 for a, b, c, _ in firsts)
            if name == "d/m/y" and month_first_proof:
                score -= 50
            if name == "m/d/y" and day_first_proof:
                score -= 50
            if name == "m/d/y" and any(ampm for *_, ampm in firsts):
                score += 1  # "9/1/2026 12:00:00 AM" is the US style used by BO
        if score > best.score:
            best = DateGuess(name, score, len(ds), len(vals))
    return best


def parse_date(v: Any, fmt: str | None = None, ref: date | None = None) -> date | None:
    """Parse one value. With no format given, try the formats in a sensible order."""
    if is_date_sentinel(v):
        return None
    if fmt:
        try:
            return DATE_FORMATS[fmt](v)
        except Exception:
            return None
    g = infer_date_format([v], ref=ref, prefer=["d/m/y", "yymmdd"])
    return DATE_FORMATS[g.fmt](v) if g.fmt else None


def date_column(values: list[Any], ref: date | None = None, prefer: list[str] | None = None) -> tuple[list[date | None], DateGuess]:
    g = infer_date_format(values, ref=ref, prefer=prefer)
    if not g.fmt:
        return [None] * len(values), g
    fn = DATE_FORMATS[g.fmt]
    out = []
    cache: dict = {}
    for v in values:
        try:
            key = (type(v), v)
            hit = cache.get(key, cache)
        except TypeError:
            key, hit = None, cache
        if hit is not cache:
            out.append(hit)
            continue
        if is_date_sentinel(v):
            d = None
        else:
            try:
                d = fn(v)
            except Exception:
                d = None
        if key is not None:
            cache[key] = d
        out.append(d)
    return out, g


_range_re = re.compile(
    r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\s*(?:-|to|–|until)\s*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})", re.I)


def find_date_range(text: str) -> tuple[date, date] | None:
    """'Report Period : 24/09/2026 - 24/09/2026' or '(17-09-2026 to 07-10-2026)'."""
    m = _range_re.search(text)
    if not m:
        return None
    a, b = m.group(1), m.group(2)
    g = infer_date_format([a, b], prefer=["d/m/y"])
    if not g.fmt:
        return None
    da, db = parse_date(a, g.fmt), parse_date(b, g.fmt)
    if da and db:
        return (min(da, db), max(da, db))
    return None


def find_dates(text: str) -> list[date]:
    """All dates in a piece of text. Numeric dates are read together, so '8/1/2026 - 8/29/2026' is
    understood as month-first because 29 cannot be a month."""
    out = []
    toks = [re.sub(r"\s+\d{1,2}:.*$", "", t) for t in
            re.findall(r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?\s*[AP]M)?", text)]
    if toks:
        g = infer_date_format(toks, prefer=["d/m/y"])
        for tok in toks:
            d = parse_date(tok, g.fmt) if g.fmt else parse_date(tok)
            if d:
                out.append(d)
    for m in _named.finditer(text):
        d = _p_named(m.group(0))
        if d:
            out.append(d)
    return out
