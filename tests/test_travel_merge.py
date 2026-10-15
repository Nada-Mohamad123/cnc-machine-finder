"""Read-only smoke test for travel extraction over raw_machines.jsonl."""

from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_cleaning"))
from clean_to_sqlite import (
    clean_category,
    clean_dataframe,
    create_standard_specs,
    load_source,
    merge_duplicate_columns,
)

SOURCE = Path(__file__).resolve().parents[1] / "02_raw_data" / "raw_machines.jsonl"


def main():
    if not SOURCE.exists():
        print(f"ERROR: Missing source file: {SOURCE}")
        return 1

    print("Loading raw source data (read only)...")
    df = load_source(str(SOURCE))
    df = clean_dataframe(df)
    df = merge_duplicate_columns(df)
    df = clean_category(df)

    print("Testing travel extraction without saving files...")
    df = create_standard_specs(df)
    print("\n===== TRAVEL EXTRACTION RESULTS =====")
    for column in ["x_travel_mm", "y_travel_mm", "z_travel_mm"]:
        count = int(df[column].notna().sum()) if column in df.columns else 0
        print(f"{column}: {count:,}/{len(df):,}")
        if column not in df.columns:
            print(f"WARNING: {column} was not created")

    print("\n===== SAMPLE VALUES =====")
    for column in ["x_travel_mm", "y_travel_mm", "z_travel_mm"]:
        if column in df.columns:
            print(f"{column}: {df[column].dropna().head(10).to_list()}")

    print("\nTest finished. CSV and database were not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
