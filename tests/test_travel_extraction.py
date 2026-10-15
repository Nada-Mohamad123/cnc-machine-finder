"""Unit tests and optional read-only scan of raw travel fields."""

import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_cleaning"))
from clean_to_sqlite import normalize_column_key, parse_length_mm

SOURCE = Path(__file__).resolve().parents[1] / "02_raw_data" / "raw_machines.jsonl"


def main():
    tests = {
        "15 in (381 mm)": 381.0,
        "150 in (3,810 mm)": 3810.0,
        "170 mm": 170.0,
        "750 mm (29.5 in)": 750.0,
        "12 in": 304.8,
        "4,000 - 10,000+ mm (157.5 - 393.7+ in) configurable": None,
        "4,000 – 10,000 mm": None,
        "1,080 [1,530] mm (42.52 [60.24] in)": None,
        "unknown": None,
        "": None,
        None: None,
    }

    print("=== TRAVEL PARSER UNIT TESTS ===")
    failures = []
    for raw, expected in tests.items():
        actual = parse_length_mm(raw)
        passed = actual == expected
        print(f"{'PASS' if passed else 'FAIL'}: {raw!r} -> {actual!r}; expected {expected!r}")
        if not passed:
            failures.append((raw, actual, expected))
    print(f"Passed: {len(tests) - len(failures)}/{len(tests)}")

    if not SOURCE.exists():
        print(f"\nRaw file not found ({SOURCE}); skipped dataset scan.")
        return 1 if failures else 0

    print("\n=== READ-ONLY RAW DATA SCAN ===")
    rows = []
    with SOURCE.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(f"WARNING: Invalid JSON on line {line_number}; skipped")
                continue
            if isinstance(record, dict):
                rows.append(record)

    print(f"Machines in raw file: {len(rows):,}")
    all_columns = []
    seen_columns = set()
    for record in rows:
        for key in record.keys():
            if key not in seen_columns:
                all_columns.append(key)
                seen_columns.add(key)

    for axis in ["X", "Y", "Z"]:
        keys = {
            normalize_column_key(f"{axis}-Axis Travel"),
            normalize_column_key(f"{axis} Axis Travel"),
            normalize_column_key(f"{axis} Travel (mm)"),
            normalize_column_key(f"{axis} Travel"),
        }
        source_fields = [key for key in all_columns if normalize_column_key(key) in keys]
        values = [
            record.get(column)
            for record in rows
            for column in source_fields
            if record.get(column) is not None and str(record.get(column)).strip()
        ]
        parsed = [value for value in values if parse_length_mm(value) is not None]
        print(f"{axis}-axis travel: {len(parsed):,}/{len(values):,} populated values parsed from {len(source_fields)} source columns")

    print("\nTravel test finished. No CSV or database files were modified.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
