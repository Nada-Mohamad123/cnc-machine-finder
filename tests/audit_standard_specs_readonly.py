"""Compare current SQLite standardized specs with proposed parser results.

Reads raw_machines.jsonl and machines.db only. Writes no files and performs no DDL.
"""
from pathlib import Path
import sqlite3
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_cleaning"))
from clean_to_sqlite import (
    load_source,
    clean_dataframe,
    merge_duplicate_columns,
    create_standard_specs,
    find_source_matching_columns,
)

RAW = Path(__file__).resolve().parents[1] / "02_raw_data" / "raw_machines.jsonl"
DB = Path(__file__).resolve().parents[1] / "04_database" / "machines.db"
METRICS = [
    "x_travel_mm", "y_travel_mm", "z_travel_mm",
    "max_table_load_kg", "machine_weight_kg", "max_spindle_rpm", "tool_capacity", "spindle_power_kw",
]
SOURCE_HEADINGS = {
    "x_travel_mm": ["X-Axis Travel", "X Axis Travel", "X Travel (mm)", "X Travel"],
    "y_travel_mm": ["Y-Axis Travel", "Y Axis Travel", "Y Travel (mm)", "Y Travel"],
    "z_travel_mm": ["Z-Axis Travel", "Z Axis Travel", "Z Travel (mm)", "Z Travel"],
    "max_table_load_kg": ["Max Table Load", "Maximum Table Load", "Table Load"],
    "machine_weight_kg": ["Machine Weight", "Weight", "Machine Weight (kg)"],
    "max_spindle_rpm": ["Max Spindle Speed", "Maximum Spindle Speed", "Max RPM", "Maximum RPM"],
    "tool_capacity": ["Tool Capacity", "Number of Tools", "Tool Magazine Capacity", "Tool Magazine", "Tool Pockets", "Number of Tool Positions", "Tool Positions"],
    "spindle_power_kw": ["Main Spindle Power (kW)", "Main Spindle Power", "Spindle Power (kW)", "Spindle Power", "Spindle Motor Power (kW)", "Spindle Motor Power"],
}


def num(series):
    return pd.to_numeric(series, errors="coerce")


def equal_with_missing(a, b):
    both_missing = a.isna() & b.isna()
    both_present_equal = a.notna() & b.notna() & ((a - b).abs() < 1e-8)
    return both_missing | both_present_equal


def main():
    if not RAW.exists() or not DB.exists():
        raise SystemExit("ERROR: raw_machines.jsonl and machines.db must both exist in this folder.")

    print("=== READ-ONLY STANDARD-SPEC AUDIT ===")
    print("Loading raw data in memory; no output files will be saved.")
    raw = load_source(str(RAW))
    raw = clean_dataframe(raw)
    raw = merge_duplicate_columns(raw)
    proposed = create_standard_specs(raw)

    with sqlite3.connect(f"file:{DB.resolve().as_posix()}?mode=ro", uri=True) as conn:
        current = pd.read_sql_query(
            'SELECT URL, "Machine Name", '
            'x_travel_mm, y_travel_mm, z_travel_mm, max_table_load_kg, '
            'machine_weight_kg, max_spindle_rpm, tool_capacity, spindle_power_kw '
            'FROM machines', conn
        )

    if "URL" not in proposed.columns:
        raise SystemExit("ERROR: URL column missing from raw data.")
    new = proposed[["URL"] + [col for col in METRICS if col in proposed.columns]].copy()
    merged = current.merge(new, on="URL", how="left", suffixes=("_old", "_new"), validate="one_to_one")
    print(f"Current DB rows: {len(current):,}; raw/proposed rows: {len(proposed):,}; matched: {merged['URL'].notna().sum():,}")

    change_frames = {}
    print("\n=== CURRENT VS PROPOSED COUNTS ===")
    for metric in METRICS:
        old_col = f"{metric}_old"
        new_col = f"{metric}_new"
        if old_col not in merged.columns or new_col not in merged.columns:
            print(f"{metric}: column missing in current or proposed data")
            continue
        old_values, new_values = num(merged[old_col]), num(merged[new_col])
        unchanged = equal_with_missing(old_values, new_values)
        changed = ~unchanged
        change_frames[metric] = changed
        print(
            f"{metric}: old populated={old_values.notna().sum():,}; "
            f"proposed populated={new_values.notna().sum():,}; "
            f"changed={int(changed.sum()):,}; "
            f"old non-positive={int((old_values.notna() & (old_values <= 0)).sum()):,}; "
            f"proposed non-positive={int((new_values.notna() & (new_values <= 0)).sum()):,}"
        )

    print("\n=== SAMPLE CHANGES WITH ORIGINAL SOURCE TEXT ===")
    raw_by_url = proposed.set_index("URL", drop=False)
    for metric, changed in change_frames.items():
        rows = merged.loc[changed].copy()
        if rows.empty:
            continue
        print(f"\n--- {metric} ---")
        printed_for_metric = 0
        for _, row in rows.iterrows():
            url = row["URL"]
            raw_row = raw_by_url.loc[url] if url in raw_by_url.index else None
            if raw_row is None:
                continue
            print(
                f"{row.get('Machine Name', '')} | old={row.get(metric + '_old')} "
                f"-> proposed={row.get(metric + '_new')} | {url}"
            )
            for position, source_name in find_source_matching_columns(raw_row.to_frame().T, SOURCE_HEADINGS[metric])[:3]:
                value = raw_row.iloc[position]
                if pd.notna(value) and str(value).strip():
                    print(f"  SOURCE [{source_name}]: {str(value)[:220]}")
            printed_for_metric += 1
            if printed_for_metric >= 3:
                break

    print("\nREAD-ONLY AUDIT COMPLETE. No files were modified.")
    print("Review the printed source examples before rebuilding the database/CSV.")


if __name__ == "__main__":
    main()
