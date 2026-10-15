"""Execute read-only SQL scenarios against machines.db, print each result,
and also export every query to its own sheet in an Excel file.

Usage:
    python run_sql_scenarios_xlsx.py        (no arguments needed; paths are found automatically)
"""
from pathlib import Path
import re
import sqlite3
import sys

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit("ERROR: pandas is required. Install it with: python -m pip install pandas") from exc

try:
    import openpyxl  # noqa: F401
except ImportError as exc:
    raise SystemExit("ERROR: openpyxl is required. Install it with: python -m pip install openpyxl") from exc

# Avoid UnicodeEncodeError on Windows when printing characters like r-caron or o-umlaut.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
DB_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else HERE.parent / "04_database" / "machines.db").resolve()
SQL_PATH = Path(sys.argv[2] if len(sys.argv) > 2 else HERE / "sql_scenarios_sqlite.sql").resolve()
XLSX_PATH = Path(sys.argv[3] if len(sys.argv) > 3 else HERE / "results_34.xlsx").resolve()

if not DB_PATH.is_file():
    raise SystemExit(f"ERROR: Database not found: {DB_PATH}")
if not SQL_PATH.is_file():
    raise SystemExit(f"ERROR: SQL file not found: {SQL_PATH}")

sql_text = SQL_PATH.read_text(encoding="utf-8-sig")
statements = [part.strip() for part in sql_text.split(";") if part.strip()]
if not statements:
    raise SystemExit("ERROR: No SQL statements found.")


# This tool is deliberately SELECT-only. Refuse to execute anything else.
def remove_comments(statement: str) -> str:
    statement = re.sub(r"/\*.*?\*/", "", statement, flags=re.S)
    statement = re.sub(r"--[^\n]*", "", statement)
    return statement.strip()


def sheet_name(index: int, title: str) -> str:
    """Excel sheet names: max 31 chars, none of []:*?/\\ ."""
    clean = re.sub(r"[\[\]:*?/\\]", " ", title)
    clean = re.sub(r"\s+", " ", clean).strip()
    return f"Q{index:02d} {clean}"[:31].rstrip()


for index, statement in enumerate(statements, 1):
    executable = remove_comments(statement)
    if not re.match(r"^(SELECT|WITH)\b", executable, flags=re.I):
        raise SystemExit(
            f"SAFETY STOP: Statement {index} is not a SELECT/WITH query. Nothing was executed."
        )

collected = []  # (index, title, sheet, dataframe or None, status, error_text)
sql_by_index = {}  # query number -> SQL text (comments removed)

conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
try:
    print("=" * 78)
    print("READ-ONLY SQL SCENARIOS")
    print(f"Database: {DB_PATH}")
    print(f"Queries: {len(statements)}")
    print("=" * 78)

    for index, statement in enumerate(statements, 1):
        match = re.search(r"--\s*QUERY:\s*(.+)", statement)
        title = match.group(1).strip() if match else f"Query {index}"
        executable = remove_comments(statement)
        sql_by_index[index] = executable
        print(f"\n[{index:02d}] {title}")
        print("-" * 78)
        try:
            result = pd.read_sql_query(executable, conn)
            if result.empty:
                print("(No rows returned)")
            else:
                print(result.to_string(index=False, max_rows=60, max_cols=30))
                if len(result) > 60:
                    print(f"... showing first 60 of {len(result)} rows")
            collected.append((index, title, sheet_name(index, title), result, "OK", ""))
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            print(f"QUERY ERROR: {msg}")
            print("Continuing with the next query; the database was not modified.")
            collected.append((index, title, sheet_name(index, title), None, "ERROR", msg))
finally:
    conn.close()

# ---- Excel export (full results, not limited to 60 rows) ----
ok_count = sum(1 for c in collected if c[4] == "OK")
err_count = len(collected) - ok_count

summary = pd.DataFrame(
    [
        {
            "Query": f"{i:02d}",
            "Title": title,
            "Sheet": sheet,
            "Rows": (len(df) if df is not None else None),
            "Status": status,
            "Error": err,
            "SQL": sql_by_index.get(i, "")[:32000],
        }
        for i, title, sheet, df, status, err in collected
    ]
)

try:
    with pd.ExcelWriter(XLSX_PATH, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        for i, title, sheet, df, status, err in collected:
            out = df if df is not None else pd.DataFrame({"error": [err]})
            out.to_excel(writer, sheet_name=sheet, index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            for col_cells in ws.columns:
                longest = max((len(str(c.value)) for c in col_cells if c.value is not None), default=8)
                ws.column_dimensions[col_cells[0].column_letter].width = min(max(longest + 2, 10), 50)
            ws.auto_filter.ref = ws.dimensions
    print(f"\nEXCEL SAVED: {XLSX_PATH}")
except PermissionError:
    print(f"\nEXCEL ERROR: cannot write {XLSX_PATH}. Close the file if it is open in Excel and run again.")
except Exception as exc:
    print(f"\nEXCEL ERROR: {type(exc).__name__}: {exc}")

print(f"\nSUMMARY: {len(collected)} queries, {ok_count} OK, {err_count} errors.")
print("FINISHED. Database opened read-only; no files were modified.")