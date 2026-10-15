"""Unit tests for price parser logic; no network requests are made."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_scraping"))
from price_patch import parse_price


def main():
    tests = [
        ("Est. $200,000 - $275,000", (200000.0, 275000.0, "estimate")),
        ("Estimated price: US$104,995", (104995.0, 104995.0, "estimate")),
        ("$104,995", (104995.0, 104995.0, "listed")),
        ("$250,000 - $200,000", None),
        ("no price here", None),
    ]
    failures = []
    print("=== PRICE PARSER TESTS (NO NETWORK) ===")
    for raw, expected in tests:
        actual = parse_price(raw)
        actual_values = actual[1:] if actual is not None else None
        passed = actual_values == expected
        print(f"{'PASS' if passed else 'FAIL'}: {raw!r} -> {actual_values!r}; expected {expected!r}")
        if not passed:
            failures.append((raw, actual_values, expected))
    print(f"\nPassed: {len(tests) - len(failures)}/{len(tests)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
