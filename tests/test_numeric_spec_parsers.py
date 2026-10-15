"""Unit tests for defensive parsing of machine specification values."""
import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_cleaning"))
from clean_to_sqlite import (
    create_standard_specs,
    parse_length_mm,
    parse_mass_kg,
    parse_table_load_kg,
    parse_rpm,
    parse_tool_capacity,
)


def run_tests():
    groups = {
        "travel": (parse_length_mm, [
            ("15 in (381 mm)", 381.0),
            ("+/-60 mm (+/-2.36 in)", 60.0),
            ("5 ft min / 12 ft max (1,524 / 3,658 mm)", 3658.0),
            ("±60 mm", 60.0),
            ("+35/-40 mm (+1.38/-1.57 in)", 40.0),
            ("200 / 190 / 185 mm (LT / RT / RTM)", None),
            ("4,000 - 10,000 mm", None),
            ("-125 mm", None),
            ("0 mm", None),
        ]),
        "weight": (parse_mass_kg, [
            ("4,500 kg (9,921 lb)", 4500.0),
            ("6,420 lb (2,915 kg)", 2915.0),
            ("15,510 lb (7,050 kg)", 7050.0),
            ("STA-3860: 24,400 lb (11,068 kg); STA-3880: 25,600 lb (11,612 kg)", None),
            ("TT-2100G: 5,200 kg (11,464 lb); TT-2100CMG: 5,400 kg (11,905 lb)", None),
            ("-3860", None),
            ("5200", 5200.0),
            ("0 kg", None),
        ]),
        "table load": (parse_table_load_kg, [
            ("0° : 75 kg", 75.0),
            ("0° : 200 kg", 200.0),
            ("4500 kg (9921 lb)", 4500.0),
            ("1,500 kg (3,307 lb); optional 2,000 kg (4,409 lb) per table", 2000.0),
            ("1,500 kg/m² (307 lb/ft²); optional 2,000 kg/m² (410 lb/ft²)", None),
            ("0", None),
        ]),
        "rpm": (parse_rpm, [
            ("12,000 rpm (15,000 rpm opt.)", 15000.0),
            ("12,000 (15,000) rpm", 15000.0),
            ("40,000 | 50,000 rpm", 50000.0),
            ("0 - 5,000 min-1", 5000.0),
            ("3,500 RPM max", 3500.0),
            ("4,500 rpm max; option 6,000 rpm", 6000.0),
            ("120000 rpm", 120000.0),
            ("-20", None),
            ("-20 rpm", None),
            ("0", None),
        ]),
        "tool capacity": (parse_tool_capacity, [
            ("24 T (30 T / 40 T opt.)", 40.0),
            ("Wheel magazine with 453 tool pockets; tool replenishment time max. 5.6 sec", 453.0),
            ("18+1", 18.0),
            ("50+1", 50.0),
            ("60 | 100", 100.0),
            ("12 tools", 12.0),
            ("Tool capacity: 40 tool positions", 40.0),
            ("HD3100A/MA", None),
            ("3100", None),
            ("0", None),
        ]),
    }

    total = 0
    failures = 0
    for group_name, (parser, cases) in groups.items():
        print(f"\n=== {group_name.upper()} ===")
        for raw, expected in cases:
            actual = parser(raw)
            ok = actual == expected or (
                actual is not None and expected is not None and abs(actual - expected) < 1e-6
            )
            total += 1
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'}: {raw!r} -> {actual!r}; expected {expected!r}")

    print("\n=== IGNORE STALE GENERATED COLUMNS ===")
    frame = pd.DataFrame({
        "URL": ["range", "simple"],
        "Machine Name": ["Variant family", "Single machine"],
        "Machine Weight": [
            "min. 26,000 – 30,000 kg (57,200 – 66,000 lb)",
            "4,500 kg (9,921 lb)",
        ],
        "machine_weight_kg": [30000.0, 999.0],
        "Tool Capacity": ["HD3100A/MA", "24 T"],
        "tool_capacity": [3100.0, 3100.0],
        "Spindle Power (kW)": ["15/18.5 kW", "22 kW"],
        "spindle_power_kw": [55.0, 55.0],
    })
    normalized = create_standard_specs(frame)
    leakage_cases = [
        ("ambiguous weight must stay missing", pd.isna(normalized.loc[0, "machine_weight_kg"])),
        ("clear weight should be 4500 kg", normalized.loc[1, "machine_weight_kg"] == 4500.0),
        ("model name must not become tool capacity", pd.isna(normalized.loc[0, "tool_capacity"])),
        ("explicit 24 T tool capacity retained", normalized.loc[1, "tool_capacity"] == 24.0),
        ("ambiguous power must stay missing", pd.isna(normalized.loc[0, "spindle_power_kw"])),
        ("clear 22 kW power retained", normalized.loc[1, "spindle_power_kw"] == 22.0),
    ]
    for label, ok in leakage_cases:
        total += 1
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}: {label}")

    print("\n=== FIELD MAPPING AND MAX-CAPABILITY SEMANTICS ===")
    mapped = pd.DataFrame({
        "URL": ["rpm-options", "tool-plus-one", "tool-options", "load-options", "area-load", "tool-magazine"],
        "Machine Name": ["RPM options", "Magazine 18+1", "Magazine options", "Load options", "Area load", "Tool magazine"],
        "Main Spindle Speed": ["40,000 | 50,000 rpm", None, None, None, None, None],
        "Tool Capacity": [None, "18+1", "60 | 100", None, None, None],
        "Tool Magazine": [None, None, None, None, None, "Wheel magazine with 453 tool pockets; tool replenishment time max. 5.6 sec"],
        "Number of Tools Max": [None, None, None, None, None, None],
        "Max Table Load": [None, None, None,
                           "1,500 kg (3,307 lb); optional 2,000 kg (4,409 lb) per table",
                           "1,500 kg/m² (307 lb/ft²); optional 2,000 kg/m² (410 lb/ft²)", None],
    })
    mapped = create_standard_specs(mapped)
    mapping_cases = [
        ("speed alternatives use documented max", mapped.loc[0, "max_spindle_rpm"] == 50000.0),
        ("N+1 capacity counts magazine pockets only", mapped.loc[1, "tool_capacity"] == 18.0),
        ("tool capacity alternatives use maximum", mapped.loc[2, "tool_capacity"] == 100.0),
        ("table-load alternatives use maximum kg", mapped.loc[3, "max_table_load_kg"] == 2000.0),
        ("areal load does not become total kg", pd.isna(mapped.loc[4, "max_table_load_kg"])),
        ("tool-pocket description maps to pocket capacity", mapped.loc[5, "tool_capacity"] == 453.0),
    ]
    for label, ok in mapping_cases:
        total += 1
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}: {label}")

    print(f"\nResult: {total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
