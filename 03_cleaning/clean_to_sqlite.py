"""
Clean machine data from JSONL / CSV / XLSX, merge price patches,
export a wide clean CSV, and rebuild the SQLite database safely.

Usage:
    python clean_to_sqlite.py
    python clean_to_sqlite.py raw_machines.jsonl
    python clean_to_sqlite.py machine_tool_index.xlsx

Safety notes:
- The wide output is machines_clean.csv.
- Database creation happens in a temporary file; an existing machines.db
  is replaced only after the new database is created and passes integrity_check.
- Price ranges retain low/high values. price_usd is the midpoint for ranges.
- Ambiguous travel and spindle-power values are left NULL instead of guessed.
"""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd


# ============================================================
# FILES
# ============================================================

HERE = Path(__file__).resolve().parent
SRC = sys.argv[1] if len(sys.argv) > 1 else str(HERE / ".." / "02_raw_data" / "raw_machines.jsonl")
PRICE_FILE = str(HERE / ".." / "02_raw_data" / "prices.jsonl")
OUTPUT_CSV = str(HERE / ".." / "07_data_outputs" / "wide" / "machines_clean.csv")
OUTPUT_DB = str(HERE / ".." / "04_database" / "machines.db")


# ============================================================
# HELPERS
# ============================================================

def is_missing(value):
    """Return True for scalar pandas/Python missing values."""
    if value is None:
        return True
    try:
        result = pd.isna(value)
        return bool(result) if not hasattr(result, "__len__") else False
    except (TypeError, ValueError):
        return False


def normalize_text(value):
    """Normalize a scalar text value; return None for blanks/missing values."""
    if is_missing(value):
        return None
    text = str(value).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def fix_mojibake(value):
    """Try to repair common UTF-8 text decoded as Latin-1."""
    if is_missing(value):
        return None
    text = str(value)
    if not text:
        return None
    try:
        return text.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def clean_column_name(column):
    """Trim and normalize whitespace in a column label."""
    text = str(column).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_column_key(column):
    """Normalize punctuation/case for matching similar column headings."""
    return re.sub(r"[^a-z0-9]+", "", str(column).lower())


def find_column(df, names):
    """Find a column by candidate names, preferring exact labels and input order."""
    columns = list(df.columns)
    for name in names:
        exact = str(name).strip().lower()
        for column in columns:
            if str(column).strip().lower() == exact:
                return column
        key = normalize_column_key(name)
        for column in columns:
            if normalize_column_key(column) == key:
                return column
    return None


def find_matching_columns(df, names):
    """Return all columns matching candidate headings, in candidate priority order."""
    result = []
    seen_positions = set()
    columns = list(df.columns)
    for name in names:
        key = normalize_column_key(name)
        for position, column in enumerate(columns):
            if normalize_column_key(column) == key and position not in seen_positions:
                result.append((position, column))
                seen_positions.add(position)
    return result


# These names are generated standardized fields, not raw source headings.
# Some scraped JSONL rows already contain values from an earlier parser run.
# Do not read those old outputs back as if they were fresh source facts.
DERIVED_SPEC_COLUMNS = {
    "x_travel_mm", "y_travel_mm", "z_travel_mm",
    "max_table_load_kg", "machine_weight_kg", "max_spindle_rpm",
    "tool_capacity", "spindle_power_kw", "spindle_taper",
}


def find_source_matching_columns(df, names):
    """Match source headings while excluding exact generated snake_case fields."""
    return [
        (position, column)
        for position, column in find_matching_columns(df, names)
        if str(column).strip().lower() not in DERIVED_SPEC_COLUMNS
    ]


def to_number(value):
    """Extract the first numeric token from a scalar, for simple numeric specs."""
    if is_missing(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def extract_number(value):
    """Legacy parser; avoid using for model-specific numeric specifications."""
    return to_number(value)


def parse_length_mm(value):
    """Parse one travel magnitude in mm; reject unresolved model variants/ranges.

    Signed Y-axis notation such as +/-60 mm is normalized to the stated extent
    (60 mm), and +35/-40 mm to the largest absolute extent (40 mm). This keeps
    the scalar field non-negative; it does not claim that the full end-to-end
    stroke equals twice that value.
    """
    if is_missing(value):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None

    # A symmetric signed axis extent: +/-60 mm, ±60 mm, -/+60 mm.
    symmetric = re.search(
        r"(?:\+\s*/\s*-|-\s*/\s*\+|±|\+\s*−\s*/\s*−)\s*"
        r"(\d+(?:\.\d+)?)\s*(mm|inches?|inch|in)\b",
        text,
        flags=re.IGNORECASE,
    )
    if symmetric:
        magnitude = float(symmetric.group(1))
        if magnitude <= 0:
            return None
        unit = symmetric.group(2).lower()
        return round(magnitude * 25.4, 4) if unit in {"in", "inch", "inches"} else magnitude

    # An asymmetric signed axis extent: +35/-40 mm.
    asymmetric = re.search(
        r"\+\s*(\d+(?:\.\d+)?)\s*/\s*-\s*(\d+(?:\.\d+)?)\s*"
        r"(mm|inches?|inch|in)\b",
        text,
        flags=re.IGNORECASE,
    )
    if asymmetric:
        magnitude = max(float(asymmetric.group(1)), float(asymmetric.group(2)))
        if magnitude <= 0:
            return None
        unit = asymmetric.group(3).lower()
        return round(magnitude * 25.4, 4) if unit in {"in", "inch", "inches"} else magnitude

    # When the source explicitly labels both MIN and MAX, store the documented
    # maximum as the scalar travel value. Unlabelled model/configuration lists
    # remain ambiguous and are rejected below.
    if re.search(r"\bmin\b", text, flags=re.IGNORECASE) and re.search(r"\bmax\b", text, flags=re.IGNORECASE):
        mm_values = re.findall(
            r"(?<![\w.])(\d+(?:\.\d+)?)\s*mm\b",
            text,
            flags=re.IGNORECASE,
        )
        if mm_values:
            maximum = max(float(number) for number in mm_values)
            return maximum if maximum > 0 else None
        ft_values = re.findall(
            r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:ft|feet|foot)\b",
            text,
            flags=re.IGNORECASE,
        )
        if ft_values:
            maximum = max(float(number) for number in ft_values) * 304.8
            return round(maximum, 4) if maximum > 0 else None
        inch_values = re.findall(
            r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:inches|inch|in)\b",
            text,
            flags=re.IGNORECASE,
        )
        if inch_values:
            maximum = max(float(number) for number in inch_values) * 25.4
            return round(maximum, 4) if maximum > 0 else None

    # Multiple configurations in the same field are not one scalar value.
    # Example: "200 / 190 / 185 mm (LT / RT / RTM)".
    if re.search(
        r"\d+(?:\.\d+)?\s*(?:/\s*\d+(?:\.\d+)?\s*){1,}"
        r"(?:mm|inches?|inch|in)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return None

    # Explicit ranges are ambiguous unless covered by the signed-axis cases above.
    if re.search(
        r"\d+(?:\.\d+)?\s*(?:-|–|—|−|\bto\b)\s*\d",
        text,
        flags=re.IGNORECASE,
    ):
        return None

    if "[" in text or "]" in text:
        return None

    # A lone negative travel is not a physical travel magnitude.
    if re.search(r"(?<!\d)-\s*\d+(?:\.\d+)?\s*(?:mm|inches?|inch|in)\b", text, re.I):
        return None

    mm_values = re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s*mm\b", text, flags=re.IGNORECASE)
    if len(mm_values) == 1:
        number = float(mm_values[0])
        return number if number > 0 else None
    if len(mm_values) > 1:
        return None

    inch_values = re.findall(
        r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:inches|inch|in)\b",
        text,
        flags=re.IGNORECASE,
    )
    if len(inch_values) == 1:
        number = float(inch_values[0])
        return round(number * 25.4, 4) if number > 0 else None
    return None


def _unit_numbers(text, units_pattern):
    """Extract numeric values that are explicitly followed by a chosen unit."""
    cleaned = str(text).replace(",", "")
    return [float(match.group(1)) for match in re.finditer(
        rf"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:{units_pattern})\b",
        cleaned,
        flags=re.IGNORECASE,
    )]


def _mass_candidates_kg(value):
    """Extract labelled mass/load candidates normalized to kg.

    Metric values explicitly present in the source take priority over pound
    conversions when both are alternate units for the same quantity. Distinct
    weights/options remain distinct; this lets parse_mass_kg reject ambiguity
    and parse_table_load_kg select the maximum load capability.
    Areal-load units (kg/m², lb/ft²) are excluded.
    """
    if is_missing(value):
        return []
    text = str(value).strip()
    if not text:
        return []

    if re.search(r"\bkg\s*/\s*m(?:\s*\^?\s*2|²)\b|\blb(?:s)?\s*/\s*ft(?:\s*\^?\s*2|²)\b", text, re.I):
        return []

    normalized = text.replace(",", "")
    token = re.compile(
        r"(?<![\w.])(?P<number>\d+(?:\.\d+)?)\s*"
        r"(?P<unit>kilograms?|kgs?|lbs?|pounds?)\b",
        flags=re.IGNORECASE,
    )

    # Each cluster represents one physical quantity written in alternative
    # units (e.g. 6,420 lb (2,915 kg)). Prefer the explicitly written kg value
    # inside a cluster. Do not collapse clearly different options.
    clusters = []
    for match in token.finditer(normalized):
        number = float(match.group("number"))
        unit = match.group("unit").lower()
        is_metric = unit in {"kg", "kgs", "kilogram", "kilograms"}
        kg_value = number if is_metric else number * 0.45359237
        if kg_value <= 0:
            continue

        matching_cluster = None
        for cluster in clusters:
            tolerance = max(2.0, 0.01 * max(kg_value, cluster["value"]))
            if abs(kg_value - cluster["value"]) <= tolerance:
                matching_cluster = cluster
                break

        if matching_cluster is None:
            clusters.append({"value": kg_value, "metric": is_metric})
        elif is_metric and not matching_cluster["metric"]:
            matching_cluster["value"] = kg_value
            matching_cluster["metric"] = True

    return [cluster["value"] for cluster in clusters]


def _parse_mass_kg(value):
    """Parse one unambiguous machine weight into kg; reject ranges/options."""
    if is_missing(value):
        return None
    text = str(value).strip()
    if not text:
        return None

    range_pattern = (
        r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?\s*"
        r"(?:-|–|—|−|\bto\b)\s*\d+(?:,\d{3})*(?:\.\d+)?\s*"
        r"(?:kg|kgs|kilograms?|lb|lbs|pounds?)\b"
    )
    if re.search(range_pattern, text, flags=re.IGNORECASE):
        return None

    candidates = _mass_candidates_kg(value)
    if candidates:
        return candidates[0] if len(candidates) == 1 else None

    if re.fullmatch(r"\s*\+?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*", text):
        number = float(text.replace(",", "").strip())
        return number if number > 0 else None
    return None


def parse_mass_kg(value):
    """Parse a single unambiguous machine weight into kg."""
    return _parse_mass_kg(value)


def parse_table_load_kg(value):
    """Parse maximum table load in kg; for explicit options choose the maximum.

    This is appropriate for a max-load field. Area loads such as kg/m² are not
    converted into total kg, because the table area is needed for that conversion.
    """
    if is_missing(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.search(r"\bkg\s*/\s*m(?:\s*\^?\s*2|²)\b|\blb(?:s)?\s*/\s*ft(?:\s*\^?\s*2|²)\b", text, re.I):
        return None

    candidates = _mass_candidates_kg(value)
    if candidates:
        return max(candidates)

    # Same bare numeric rule as other specs; zero is not treated as a measured load.
    if re.fullmatch(r"\s*\+?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*", text):
        number = float(text.replace(",", "").strip())
        return number if number > 0 else None
    return None


def parse_rpm(value):
    """Parse maximum available spindle RPM from explicitly labelled speed text.

    Since the normalized column is max_spindle_rpm, the maximum among explicit
    standard/optional values is retained. Negative/zero values are rejected.
    """
    if is_missing(value):
        return None
    original = str(value).strip()
    if not original:
        return None
    text = original.replace(",", "")
    number = r"\d+(?:\.\d+)?"
    unit = (
        r"rpm\b|r\s*/\s*min\b|"
        r"rev(?:olutions?)?\s*(?:/|per)\s*min(?:ute)?\b|"
        r"min\s*[-−]?\s*1\b|min⁻¹\b|1\s*/\s*min\b"
    )
    # Handle lists such as 40,000 | 50,000 rpm and parenthesized alternatives
    # such as 12,000 (15,000) rpm. Only positive numbers immediately connected
    # to a speed unit are collected; a leading negative sign is not accepted.
    pattern = re.compile(
        rf"(?<![\w.\-])(?P<chain>{number}(?:\s*(?:\|\s*|/\s*|\bor\s+){number}|\s*\(\s*{number}\s*\))*)\s*(?:{unit})",
        flags=re.IGNORECASE,
    )
    found = []
    for match in pattern.finditer(text):
        for token in re.findall(number, match.group("chain")):
            candidate = float(token)
            if candidate > 0:
                found.append(candidate)

    if found:
        return max(found)

    # Unitless values are accepted only if the complete field is one positive number.
    if re.fullmatch(r"\s*\+?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*", original):
        candidate = float(original.replace(",", "").strip())
        return candidate if candidate > 0 else None
    return None


def parse_tool_capacity(value):
    """Parse maximum supported tool-magazine capacity from source text.

    For Haas-style N+1 notation, N is the magazine's pocket count and the +1 is
    the tool held in the spindle, so only N is stored in this numeric field.
    For explicitly labelled alternatives, the largest capacity is retained.
    """
    if is_missing(value):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None

    plus_one = re.fullmatch(r"\s*(\d+)\s*\+\s*1\s*", text)
    if plus_one:
        number = int(plus_one.group(1))
        return number if 0 < number <= 1000 else None

    number = r"\d+(?:\.\d+)?"
    unit_pattern = r"T\b|tools?\b|tool\s+positions?\b|stations?\b|pockets?\b"
    labelled = re.findall(
        rf"(?<![\w.])({number})\s*(?:{unit_pattern})",
        text,
        flags=re.IGNORECASE,
    )
    if labelled:
        values = [float(item) for item in labelled if 0 < float(item) <= 1000]
        return max(values) if values else None

    # A bare option-list such as "60 | 100" is interpreted as the maximum
    # magazine capacity supported by the listed configurations.
    if re.fullmatch(rf"\s*{number}(?:\s*(?:\||/|\bor\b)\s*{number})+\s*", text, re.I):
        values = [float(item) for item in re.findall(number, text)]
        values = [item for item in values if 0 < item <= 1000]
        return max(values) if values else None

    # Bare values are allowed when plausible, but suspicious model-like numbers
    # and zeros are intentionally ignored.
    if re.fullmatch(r"\s*\+?\s*\d+(?:\.\d+)?\s*", text):
        number_value = float(text)
        return number_value if 0 < number_value <= 1000 else None
    return None


def parse_power_kw(value, assume_kw=False):
    """Parse a single spindle power value and return kW; ambiguous values stay NULL."""
    if is_missing(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace(",", "")

    # Values such as "15/18.5 kW" or "22-30 kW" can describe S1/S6 ratings
    # or ranges. Do not arbitrarily choose either number.
    if re.search(
        r"\d+(?:\.\d+)?\s*(?:/|-|–|—|−|\bto\b)\s*\d+(?:\.\d+)?\s*"
        r"(?:kW|kilowatts?|W|watts?|hp|horsepower|PS)\b",
        normalized,
        flags=re.IGNORECASE,
    ):
        return None

    tokens = re.findall(
        r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>kW|kilowatts?|W|watts?|hp|horsepower|PS)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if tokens:
        kw_values = []
        hp_values = []
        watt_values = []
        ps_values = []
        for number, unit in tokens:
            number = float(number)
            unit_lower = unit.lower()
            if unit_lower in {"kw", "kilowatt", "kilowatts"}:
                kw_values.append(number)
            elif unit_lower in {"w", "watt", "watts"}:
                watt_values.append(number / 1000.0)
            elif unit_lower in {"hp", "horsepower"}:
                hp_values.append(number * 0.745699872)
            elif unit_lower == "ps":
                ps_values.append(number * 0.73549875)

        # Prefer one explicit kW value if any; multiple values in the same unit
        # are ambiguous unless a range was explicitly resolvable (not handled here).
        if len(kw_values) == 1:
            return kw_values[0]
        if len(kw_values) > 1:
            return None
        alternatives = watt_values + hp_values + ps_values
        if len(alternatives) == 1:
            return alternatives[0]
        return None

    # Only infer kW when the column heading explicitly contains (kW).
    if assume_kw:
        values = re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", normalized)
        if len(values) == 1 and not re.search(r"[/–—]|\bto\b", normalized, re.I):
            return float(values[0])
    return None


# ============================================================
# LOAD SOURCE DATA
# ============================================================

def load_source(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Source file not found: {path}")

    extension = os.path.splitext(path)[1].lower()
    print("\n" + "=" * 60)
    print("LOADING SOURCE DATA")
    print("=" * 60)
    print(f"Source: {path}")

    if extension == ".jsonl":
        df = pd.read_json(path, lines=True)
    elif extension == ".json":
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        df = pd.DataFrame(data)
    elif extension == ".csv":
        df = pd.read_csv(path)
    elif extension in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        raise ValueError(f"Unsupported file type: {extension}")

    print(f"Rows loaded: {len(df):,}")
    print(f"Columns loaded: {len(df.columns):,}")
    return df


# ============================================================
# BASIC CLEANING
# ============================================================

def clean_dataframe(df):
    print("\n" + "=" * 60)
    print("CLEANING DATA")
    print("=" * 60)

    df = df.copy()
    df.columns = [clean_column_name(column) for column in df.columns]

    for position in range(len(df.columns)):
        # Positional access also handles duplicate column labels safely.
        series = df.iloc[:, position]
        if series.dtype == "object" or pd.api.types.is_string_dtype(series.dtype):
            df.isetitem(position, series.map(normalize_text).map(fix_mojibake))

    df = df.dropna(how="all").copy()
    before = len(df)
    df = df.drop_duplicates().copy()
    removed = before - len(df)
    if removed:
        print(f"Duplicate rows removed: {removed:,}")

    parameter_positions = [
        i for i, column in enumerate(df.columns)
        if str(column).strip().lower() == "parameter"
    ]
    if parameter_positions:
        keep_positions = [i for i in range(len(df.columns)) if i not in parameter_positions]
        df = df.iloc[:, keep_positions].copy()
        print(f"Removed Parameter columns: {len(parameter_positions)}")

    return df


# ============================================================
# CATEGORY CLEANING
# ============================================================

def clean_category(df):
    column = find_column(df, ["Category", "Machine Category"])
    if column is None:
        return df
    df[column] = df[column].map(normalize_text)
    return df


# ============================================================
# MERGE EXACT DUPLICATE COLUMNS
# ============================================================

def merge_duplicate_columns(df):
    """Merge columns with same case/whitespace-normalized label, including blank cells."""
    df = df.copy()
    kept_positions = []
    first_position_by_key = {}

    for position, column in enumerate(df.columns):
        key = str(column).strip().lower()
        if key not in first_position_by_key:
            first_position_by_key[key] = position
            kept_positions.append(position)
            continue

        target_position = first_position_by_key[key]
        primary = df.iloc[:, target_position].copy()
        extra = df.iloc[:, position]
        blank_primary = primary.isna()
        try:
            blank_primary = blank_primary | primary.astype("string").str.strip().eq("").fillna(False)
        except (TypeError, ValueError):
            pass
        df.isetitem(target_position, primary.where(~blank_primary, extra))

    return df.iloc[:, kept_positions].copy()


# ============================================================
# PRICE PATCH
# ============================================================

def load_prices():
    if not os.path.exists(PRICE_FILE):
        print(f"\nPrice file not found: {PRICE_FILE}")
        return pd.DataFrame()

    rows = []
    with open(PRICE_FILE, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(f"WARNING: Invalid JSON at {PRICE_FILE}:{line_number}; skipped")
                continue
            if isinstance(record, dict):
                rows.append(record)

    prices = pd.DataFrame(rows)
    if prices.empty:
        return prices

    if "url" not in prices.columns:
        print("WARNING: prices.jsonl has no 'url' field; prices were not merged.")
        return pd.DataFrame()

    prices["url"] = prices["url"].map(normalize_text)
    prices = prices[prices["url"].notna()].copy()

    for column in ["price_low", "price_high"]:
        if column not in prices.columns:
            prices[column] = pd.NA
        prices[column] = pd.to_numeric(prices[column], errors="coerce")

    for column in ["price_text", "price_type"]:
        if column not in prices.columns:
            prices[column] = pd.NA

    # If a URL has both an empty attempt and a priced attempt, preserve the
    # latest priced attempt rather than allowing a later empty retry to erase it.
    prices["__order"] = range(len(prices))
    prices["__has_price"] = prices["price_low"].notna() | prices["price_high"].notna()
    duplicates = int(prices.duplicated(subset=["url"], keep=False).sum())
    if duplicates:
        print(f"WARNING: {duplicates:,} price rows belong to duplicate URLs; resolving safely.")
    prices = (
        prices.sort_values(["url", "__has_price", "__order"])
        .drop_duplicates(subset=["url"], keep="last")
        .sort_values("__order")
        .drop(columns=["__order", "__has_price"])
    )

    print("\n" + "=" * 60)
    print("PRICE PATCH")
    print("=" * 60)
    print(f"Price records loaded: {len(prices):,}")
    return prices


def merge_prices(df):
    prices = load_prices()
    if prices.empty:
        # Keep the standardized price schema even if no patch file exists.
        for column in ["price_text", "price_type", "price_usd", "price_low_usd", "price_high_usd", "price_mid_usd"]:
            if column not in df.columns:
                df[column] = pd.NA
        return df

    url_column = find_column(df, ["URL", "Link"])
    if url_column is None:
        print("WARNING: URL column not found. Prices were not merged.")
        return df

    work_prices = prices[["url", "price_text", "price_low", "price_high", "price_type"]].copy()
    work_prices = work_prices.rename(columns={
        "url": "__patch_url",
        "price_text": "__patch_price_text",
        "price_low": "__patch_price_low",
        "price_high": "__patch_price_high",
        "price_type": "__patch_price_type",
    })

    df = df.copy()
    df[url_column] = df[url_column].map(normalize_text)
    work_prices["__patch_url"] = work_prices["__patch_url"].map(normalize_text)
    df = df.merge(
        work_prices,
        how="left",
        left_on=url_column,
        right_on="__patch_url",
        validate="many_to_one",
    )

    for target, patch in [
        ("price_text", "__patch_price_text"),
        ("price_type", "__patch_price_type"),
    ]:
        patch_values = df[patch] if patch in df.columns else pd.Series(pd.NA, index=df.index)
        if target in df.columns:
            df[target] = patch_values.combine_first(df[target])
        else:
            df[target] = patch_values

    low_patch = pd.to_numeric(df.get("__patch_price_low"), errors="coerce")
    high_patch = pd.to_numeric(df.get("__patch_price_high"), errors="coerce")

    # Existing standardized fields, if present in a source file, are fallback only.
    if "price_low_usd" in df.columns:
        low_patch = low_patch.combine_first(pd.to_numeric(df["price_low_usd"], errors="coerce"))
    elif "price_low" in df.columns:
        low_patch = low_patch.combine_first(pd.to_numeric(df["price_low"], errors="coerce"))

    if "price_high_usd" in df.columns:
        high_patch = high_patch.combine_first(pd.to_numeric(df["price_high_usd"], errors="coerce"))
    elif "price_high" in df.columns:
        high_patch = high_patch.combine_first(pd.to_numeric(df["price_high"], errors="coerce"))

    low_patch = low_patch.combine_first(high_patch)
    high_patch = high_patch.combine_first(low_patch)
    invalid_ranges = low_patch.notna() & high_patch.notna() & (low_patch > high_patch)
    invalid_count = int(invalid_ranges.sum())
    if invalid_count:
        print(f"WARNING: {invalid_count:,} records have price_low > price_high; those ranges were nulled.")
        low_patch.loc[invalid_ranges] = pd.NA
        high_patch.loc[invalid_ranges] = pd.NA

    df["price_low_usd"] = low_patch
    df["price_high_usd"] = high_patch
    df["price_mid_usd"] = (low_patch + high_patch) / 2
    # A representative single price for analysis: midpoint of a range, or the listed price.
    df["price_usd"] = df["price_mid_usd"]

    df = df.drop(columns=[
        column for column in [
            "__patch_url", "__patch_price_text", "__patch_price_low",
            "__patch_price_high", "__patch_price_type"
        ] if column in df.columns
    ])
    return df


# ============================================================
# STANDARD MACHINE SPECIFICATIONS
# ============================================================

def create_standard_specs(df):
    df = df.copy()

    def parse_travel_values(values):
        present = [value for value in values if normalize_text(value) is not None]
        if not present:
            return False, None
        parsed = [parse_length_mm(value) for value in present]
        if any(value is None for value in parsed):
            return True, None
        if len(set(parsed)) != 1:
            return True, None
        return True, parsed[0]

    # Match punctuation variants to their normalized heading, but keep travel
    # variants separate and compare their values rather than overwriting one.
    for axis in ["X", "Y", "Z"]:
        standard_name = f"{axis.lower()}_travel_mm"
        primary = find_source_matching_columns(df, [f"{axis}-Axis Travel", f"{axis} Axis Travel"])
        fallback = find_source_matching_columns(df, [f"{axis} Travel (mm)", f"{axis} Travel"])
        primary_positions = [position for position, _ in primary]
        fallback_positions = [position for position, _ in fallback]
        result_values = []

        relevant_positions = list(dict.fromkeys(primary_positions + fallback_positions))
        if not relevant_positions:
            df[standard_name] = pd.NA
            continue

        primary_set = set(primary_positions)
        fallback_set = set(fallback_positions)
        subset = df.iloc[:, relevant_positions]
        for row_values in subset.itertuples(index=False, name=None):
            by_position = dict(zip(relevant_positions, row_values))
            found, parsed = parse_travel_values([by_position[p] for p in primary_positions])
            if not found:
                parsed_found, parsed = parse_travel_values([by_position[p] for p in fallback_positions])
                found = parsed_found
            result_values.append(parsed if found else None)
        df[standard_name] = result_values

    numeric_spec_mapping = {
        "max_table_load_kg": ([
            "Max Table Load", "Maximum Table Load", "Table Load",
            "Max Weight on Table", "Maximum Weight on Table",
            "Table Load Capacity", "Maximum Table Load Capacity",
            "Max Table Capacity", "Max Payload", "Maximum Payload",
        ], parse_table_load_kg),
        "machine_weight_kg": ([
            "Machine Weight", "Weight", "Machine Weight (kg)",
            "Machine Mass", "Net Weight",
        ], parse_mass_kg),
        "max_spindle_rpm": ([
            "Max Spindle Speed", "Maximum Spindle Speed", "Max RPM", "Maximum RPM",
            "Main Spindle Speed", "Spindle Speed", "Spindle RPM", "Max Spindle RPM",
        ], parse_rpm),
        "tool_capacity": ([
            "Tool Capacity", "Number of Tools", "Tool Magazine Capacity",
            "Number of Tools Max", "Maximum Number of Tools", "Max Tool Capacity",
            "Tool Changer Capacity", "Number of Tool Positions", "Tool Positions",
            "Magazine Capacity", "Tool Magazine", "Tool Pockets",
        ], parse_tool_capacity),
    }

    # Parse by units and explicit context, not simply the first number in a string.
    # If multiple matching source columns produce conflicting parsed numbers, leave
    # the standardized value missing instead of arbitrarily selecting one.
    for standard_name, (possible_names, parser) in numeric_spec_mapping.items():
        candidates = find_source_matching_columns(df, possible_names)
        positions = [position for position, _ in candidates]
        if not positions:
            df[standard_name] = pd.NA
            continue

        output_values = []
        subset = df.iloc[:, positions]
        for row_values in subset.itertuples(index=False, name=None):
            parsed_values = []
            for raw_value in row_values:
                if normalize_text(raw_value) is None:
                    continue
                parsed = parser(raw_value)
                if parsed is not None:
                    parsed_values.append(parsed)
            distinct = set(parsed_values)
            if len(distinct) == 1:
                output_values.append(next(iter(distinct)))
            elif distinct and standard_name in {"max_table_load_kg", "max_spindle_rpm", "tool_capacity"}:
                # These fields describe maximum available capability; if reliable
                # source headings disagree, retain the largest explicitly parsed value.
                output_values.append(max(distinct))
            else:
                output_values.append(None)
        df[standard_name] = output_values

    taper_candidates = find_source_matching_columns(df, ["Spindle Taper", "Spindle Taper Type", "Taper"])
    taper_column = taper_candidates[0][1] if taper_candidates else None
    if taper_column is not None:
        df["spindle_taper"] = df[taper_column].map(normalize_text)
    else:
        df["spindle_taper"] = pd.NA

    # Power is handled separately. Prefer a clear main-spindle value; fall back
    # to motor power only when a higher-priority field cannot be parsed safely.
    power_candidates = find_source_matching_columns(df, [
        "Main Spindle Power (kW)",
        "Main Spindle Power",
        "Spindle Power (kW)",
        "Spindle Power",
        "Spindle Motor Power (kW)",
        "Spindle Motor Power",
    ])
    power_positions = [position for position, _ in power_candidates]
    power_names = {position: str(name) for position, name in power_candidates}
    power_values = []
    if power_positions:
        power_subset = df.iloc[:, power_positions]
        for row_values in power_subset.itertuples(index=False, name=None):
            result = None
            for position, raw_value in zip(power_positions, row_values):
                heading = power_names[position].lower()
                assume_kw = "(kw)" in heading
                result = parse_power_kw(raw_value, assume_kw=assume_kw)
                if result is not None:
                    break
            power_values.append(result)
    else:
        power_values = [None] * len(df)
    df["spindle_power_kw"] = power_values

    return df


# ============================================================
# SQLITE
# ============================================================

def create_sqlite(df):
    """Build a temporary SQLite database, verify it, then atomically replace output."""
    print("\n" + "=" * 60)
    print("CREATING SQLITE DATABASE")
    print("=" * 60)

    output_path = Path(OUTPUT_DB)
    temp_path = output_path.with_name(output_path.name + ".building")
    if temp_path.exists():
        temp_path.unlink()

    preferred_columns = [
        "URL", "Name", "Machine Name", "Manufacturer", "Brand", "Category", "Description",
        "price_text", "price_usd", "price_low_usd", "price_high_usd", "price_mid_usd", "price_type",
        "x_travel_mm", "y_travel_mm", "z_travel_mm", "max_table_load_kg", "machine_weight_kg",
        "spindle_power_kw", "max_spindle_rpm", "tool_capacity", "spindle_taper",
    ]
    selected_columns = []
    for wanted in preferred_columns:
        real_column = find_column(df, [wanted])
        if real_column is not None and real_column not in selected_columns:
            selected_columns.append(real_column)

    if not selected_columns:
        raise ValueError("No recognized columns available for the machines table.")

    machines_df = df[selected_columns].copy()
    print(f"Columns in machines table: {len(machines_df.columns):,}")

    connection = None
    try:
        connection = sqlite3.connect(str(temp_path))
        machines_df.to_sql("machines", connection, if_exists="replace", index=False)

        id_column = find_column(df, ["URL", "Name", "Machine Name"])
        specification_columns = [
            column for column in [
                "x_travel_mm", "y_travel_mm", "z_travel_mm", "max_table_load_kg",
                "machine_weight_kg", "spindle_power_kw", "max_spindle_rpm", "tool_capacity", "spindle_taper",
            ] if column in df.columns
        ]

        spec_rows = []
        if id_column is not None and specification_columns:
            values_df = df[[id_column] + specification_columns]
            for values in values_df.itertuples(index=False, name=None):
                machine_id = values[0]
                if is_missing(machine_id):
                    continue
                for spec, value in zip(specification_columns, values[1:]):
                    if is_missing(value):
                        continue
                    spec_rows.append({
                        "machine_id": str(machine_id),
                        "spec_name": spec,
                        "spec_value": str(value),
                    })

        specs_df = pd.DataFrame(spec_rows, columns=["machine_id", "spec_name", "spec_value"])
        specs_df.to_sql("specs_long", connection, if_exists="replace", index=False)

        machine_columns = {row[1] for row in connection.execute("PRAGMA table_info(machines)").fetchall()}
        if "URL" in machine_columns:
            connection.execute("CREATE INDEX IF NOT EXISTS idx_machines_url ON machines(URL)")
        if "Category" in machine_columns:
            connection.execute("CREATE INDEX IF NOT EXISTS idx_machines_category ON machines(Category)")
        connection.commit()
        print(f"Rows in specs_long: {len(specs_df):,}")
    except Exception:
        if connection is not None:
            connection.close()
            connection = None
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        if connection is not None:
            connection.close()

    # IMPORTANT: sqlite3.Connection's context manager handles transactions,
    # but it does NOT close the connection. Explicitly close it before os.replace,
    # otherwise Windows may keep machines.db.building locked (WinError 32).
    check_connection = sqlite3.connect(str(temp_path))
    try:
        integrity = check_connection.execute("PRAGMA integrity_check").fetchone()[0]
        new_count = check_connection.execute("SELECT COUNT(*) FROM machines").fetchone()[0]
    finally:
        check_connection.close()

    # Do not touch the existing DB unless the temporary DB is healthy.
    if integrity != "ok" or new_count != len(df):
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Temporary database validation failed: integrity={integrity!r}, rows={new_count}, expected={len(df)}. Existing DB retained."
        )

    os.replace(temp_path, output_path)
    print(f"SQLite database created safely: {OUTPUT_DB}")


# ============================================================
# MAIN
# ============================================================

def main():
    print("\n" + "=" * 60)
    print("MACHINE DATA CLEANING PIPELINE")
    print("=" * 60)

    df = load_source(SRC)
    df = clean_dataframe(df)
    df = merge_duplicate_columns(df)
    df = clean_category(df)
    df = merge_prices(df)
    df = create_standard_specs(df)
    df = df.drop_duplicates().copy()

    # Stage the CSV so a failed DB build does not overwrite the current CSV.
    csv_path = Path(OUTPUT_CSV)
    temp_csv = csv_path.with_name(csv_path.name + ".building")
    temp_csv.unlink(missing_ok=True)
    try:
        df.to_csv(temp_csv, index=False, encoding="utf-8-sig")
        create_sqlite(df)
        os.replace(temp_csv, csv_path)
    except Exception:
        temp_csv.unlink(missing_ok=True)
        raise

    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"Rows   : {len(df):,}")
    print(f"Columns: {len(df.columns):,}")
    print(f"CSV    : {OUTPUT_CSV}")
    print(f"SQLite : {OUTPUT_DB}")
    if "price_usd" in df.columns:
        print(f"Machines with representative price: {pd.to_numeric(df['price_usd'], errors='coerce').notna().sum():,}")
    if "price_low_usd" in df.columns:
        print(f"Machines with price low: {pd.to_numeric(df['price_low_usd'], errors='coerce').notna().sum():,}")
    if "spindle_power_kw" in df.columns:
        print(f"Machines with unambiguous spindle power: {pd.to_numeric(df['spindle_power_kw'], errors='coerce').notna().sum():,}")
    print("\nDONE")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
