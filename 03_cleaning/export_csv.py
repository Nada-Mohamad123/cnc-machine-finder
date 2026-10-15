"""Export the compact SQLite tables without overwriting the wide raw-preserving CSV."""

import sqlite3
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DB_FILE = HERE / ".." / "04_database" / "machines.db"
MACHINES_OUTPUT = HERE / ".." / "07_data_outputs" / "machines_core.csv"
SPECS_OUTPUT = HERE / ".." / "07_data_outputs" / "machine_specs.csv"


def main():
    if not DB_FILE.exists():
        raise FileNotFoundError(f"Database file not found: {DB_FILE}")

    with sqlite3.connect(DB_FILE) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "machines" not in tables:
            raise RuntimeError("Table 'machines' is missing from machines.db")
        if "specs_long" not in tables:
            raise RuntimeError("Table 'specs_long' is missing from machines.db")

        machines = pd.read_sql_query("SELECT * FROM machines", connection)
        machine_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(machines)").fetchall()
        }
        if "URL" not in machine_columns:
            raise RuntimeError("The machines table has no 'URL' column; cannot link specs safely")

        if "Machine Name" in machine_columns:
            machine_name = 'm."Machine Name"'
        elif "Name" in machine_columns:
            machine_name = 'm."Name"'
        else:
            machine_name = "NULL"

        specs_query = f"""
            SELECT
                m."URL" AS URL,
                {machine_name} AS "Machine Name",
                s.spec_name,
                s.spec_value
            FROM specs_long AS s
            JOIN machines AS m ON s.machine_id = m."URL"
            ORDER BY m."URL", s.spec_name
        """
        specs = pd.read_sql_query(specs_query, connection)

    # Important: this is a compact export. It must not overwrite the wide
    # machines_clean.csv created by clean_to_sqlite.py.
    machines.to_csv(MACHINES_OUTPUT, index=False, encoding="utf-8-sig")
    specs.to_csv(SPECS_OUTPUT, index=False, encoding="utf-8-sig")

    print("Export completed successfully.")
    print(f"Machines: {len(machines):,} rows, {len(machines.columns):,} columns -> {MACHINES_OUTPUT}")
    print(f"Specifications: {len(specs):,} rows, {len(specs.columns):,} columns -> {SPECS_OUTPUT}")
    print("The wide machines_clean.csv was not modified.")


if __name__ == "__main__":
    main()
