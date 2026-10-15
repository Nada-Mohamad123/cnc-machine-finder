"""Unit tests for cautious spindle power parsing; no files are changed."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03_cleaning"))
from clean_to_sqlite import parse_power_kw


def main():
    tests = [
        ("22 kW", False, 22.0),
        ("10 kW (13.4 hp)", False, 10.0),
        ("30 hp", False, 30 * 0.745699872),
        ("15000 W", False, 15.0),
        ("15/18.5 kW (S1/S6)", False, None),
        ("22–30 kW", False, None),
        ("unknown", False, None),
        ("7.5", False, None),
        ("7.5", True, 7.5),
    ]
    failures = []
    print("=== POWER PARSER TESTS ===")
    for raw, assume_kw, expected in tests:
        actual = parse_power_kw(raw, assume_kw=assume_kw)
        passed = actual == expected or (
            actual is not None and expected is not None and abs(actual - expected) < 1e-8
        )
        print(f"{'PASS' if passed else 'FAIL'}: {raw!r} -> {actual!r}; expected {expected!r}")
        if not passed:
            failures.append((raw, actual, expected))
    print(f"\nPassed: {len(tests) - len(failures)}/{len(tests)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
