"""Read-only validation for machines.db and the wide machines_clean.csv."""

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_FILE = ROOT / "04_database" / "machines.db"
CSV_FILE = ROOT / "07_data_outputs" / "wide" / "machines_clean.csv"
TRAVEL_COLUMNS = ["x_travel_mm", "y_travel_mm", "z_travel_mm"]
SPEC_COLUMNS = [
    "x_travel_mm", "y_travel_mm", "z_travel_mm", "max_table_load_kg",
    "machine_weight_kg", "spindle_power_kw", "max_spindle_rpm", "tool_capacity", "spindle_taper",
]


def main():
    print("=" * 60)
    print("OUTPUT VALIDATION (READ ONLY)")
    print("=" * 60)

    for path in [DB_FILE, CSV_FILE]:
        print(f"{path.name} exists: {path.exists()}")
        if not path.exists():
            print(f"ERROR: Missing {path.name}")
            return 1

    with sqlite3.connect(DB_FILE) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if not {"machines", "specs_long"}.issubset(tables):
            print(f"ERROR: Missing expected tables. Found: {sorted(tables)}")
            return 1

        machine_count = conn.execute("SELECT COUNT(*) FROM machines").fetchone()[0]
        specs_count = conn.execute("SELECT COUNT(*) FROM specs_long").fetchone()[0]
        machine_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(machines)").fetchall()
        }
        print("\n=== SQLITE ===")
        print(f"Integrity check: {integrity}")
        print(f"Machines rows: {machine_count:,}")
        print(f"specs_long rows: {specs_count:,}")
        print(f"Machines columns: {len(machine_columns):,}")

        for column in TRAVEL_COLUMNS:
            if column in machine_columns:
                count = conn.execute(
                    f'SELECT COUNT(*) FROM machines WHERE "{column}" IS NOT NULL'
                ).fetchone()[0]
                print(f"{column}: {count:,}")
            else:
                print(f"ERROR: Missing column {column}")

        if {"price_low_usd", "price_high_usd"}.issubset(machine_columns):
            invalid_ranges = conn.execute(
                """SELECT COUNT(*) FROM machines
                   WHERE price_low_usd IS NOT NULL
                     AND price_high_usd IS NOT NULL
                     AND price_low_usd > price_high_usd"""
            ).fetchone()[0]
            print(f"Invalid price ranges: {invalid_ranges:,}")
        else:
            invalid_ranges = None
            print("WARNING: Price range columns are missing")

        if "URL" in machine_columns:
            duplicate_urls = conn.execute(
                """SELECT COUNT(*) FROM (
                       SELECT URL FROM machines WHERE URL IS NOT NULL
                       GROUP BY URL HAVING COUNT(*) > 1
                   )"""
            ).fetchone()[0]
            print(f"URLs appearing more than once: {duplicate_urls:,}")
        else:
            duplicate_urls = None
            print("WARNING: URL column is missing")

        print("\nStandard specs coverage in specs_long:")
        rows = conn.execute(
            "SELECT spec_name, COUNT(*) FROM specs_long GROUP BY spec_name ORDER BY spec_name"
        ).fetchall()
        for name, count in rows:
            print(f"{name}: {count:,}")

    print("\n=== CSV ===")
    # Read only the header first; the full CSV may contain thousands of columns.
    csv_header = pd.read_csv(CSV_FILE, encoding="utf-8-sig", nrows=0).columns.tolist()
    csv_rows = sum(1 for _ in open(CSV_FILE, "r", encoding="utf-8-sig")) - 1
    print(f"CSV rows: {csv_rows:,}")
    print(f"CSV columns: {len(csv_header):,}")
    for column in TRAVEL_COLUMNS:
        print(f"{column} present in CSV: {column in csv_header}")

    wide_csv_warning = len(csv_header) < 100
    checks = {
        "SQLite integrity is OK": integrity == "ok",
        "CSV row count matches database": csv_rows == machine_count,
        "Travel columns exist in CSV": all(column in csv_header for column in TRAVEL_COLUMNS),
        "CSV appears to remain wide (100+ columns)": not wide_csv_warning,
        "No duplicate machine URLs": duplicate_urls == 0 if duplicate_urls is not None else False,
        "No invalid low/high price ranges": invalid_ranges == 0 if invalid_ranges is not None else False,
    }
    print("\n=== CHECKS ===")
    for label, passed in checks.items():
        print(f"{'PASS' if passed else 'CHECK'}: {label}")
    print("\nValidation complete. No files were modified.")
    return 0 if all(checks.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
