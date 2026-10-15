"""
Fetch prices only from existing machine URLs in raw_machines.jsonl.
Does not repeat the specifications scrape.

Usage:
    python price_patch.py
    python price_patch.py --limit 5
    python price_patch.py --limit 5 --retry-empty
    python price_patch.py --retry-empty

Default behavior skips every URL already recorded in prices.jsonl.
With --retry-empty, it retries only URLs that have never produced a numeric price.
Use --limit 5 with --retry-empty for a small test before retrying many pages.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
RAW = str(HERE / ".." / "02_raw_data" / "raw_machines.jsonl")
OUT = str(HERE / ".." / "02_raw_data" / "prices.jsonl")
FAIL = str(HERE / "failed_prices.txt")
DELAY = 2.0

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; MachineDataResearch/1.0)",
})

MONEY = r"(?:US\s*)?\$\s?\d[\d,]*(?:\.\d+)?"
RANGE = re.compile(
    rf"(?P<first>{MONEY})(?:\s*[-–—−]\s*(?P<second>{MONEY}))?",
    re.IGNORECASE,
)


def parse_price(text):
    """Return (price_text, low, high, type), or None if no safe price is found."""
    if not text:
        return None

    match = RANGE.search(str(text))
    if not match:
        return None

    def to_number(value):
        if not value:
            return None
        cleaned = re.sub(r"[^\d.]", "", value)
        if not cleaned:
            return None
        try:
            number = float(cleaned)
        except ValueError:
            return None
        return number if number > 0 else None

    first = to_number(match.group("first"))
    second = to_number(match.group("second"))
    if first is None:
        return None

    if second is None:
        low = high = first
    else:
        low, high = first, second
        if low > high:
            return None

    # The source can say "Estimated price: $...", "Est. $..." or similar.
    prefix = str(text)[max(0, match.start() - 100):match.start()]
    estimate = bool(re.search(r"\b(?:est\.?|estimate|estimated)\b", prefix, re.IGNORECASE))
    if not estimate:
        estimate = bool(re.match(r"\s*est\.?\s*", str(text)[max(0, match.start() - 10):match.start() + 1], re.I))
    price_type = "estimate" if estimate else "listed"

    return match.group(0).strip(), low, high, price_type


def get_price(url, tries=3):
    """Fetch one URL. Return ('ok', parsed_price_or_none) or ('fail', None)."""
    for attempt in range(tries):
        try:
            response = SESSION.get(url, timeout=25)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            soup = BeautifulSoup(response.text, "html.parser")

            h1 = soup.find("h1")
            if h1 is None:
                # The request worked but page structure is not recognized.
                return "ok", None

            # Inspect a small region after the title, where listing pages commonly
            # place price information. We don't parse arbitrary page-wide numbers.
            parts = []
            for element in h1.find_all_next(limit=12):
                text = element.get_text(" ", strip=True)
                if text:
                    parts.append(text)
            chunk = " ".join(parts)[:1200]
            return "ok", parse_price(chunk)

        except requests.RequestException as exc:
            if attempt == tries - 1:
                print(f"  -> REQUEST FAILED: {type(exc).__name__}")
                return "fail", None
            time.sleep(2 * (attempt + 1))
        except Exception as exc:
            if attempt == tries - 1:
                print(f"  -> PARSE FAILED: {type(exc).__name__}: {exc}")
                return "fail", None
            time.sleep(2 * (attempt + 1))

    return "fail", None


def load_urls():
    """Read and deduplicate URLs from raw_machines.jsonl."""
    urls = []
    with open(RAW, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(f"WARNING: Invalid JSON at {RAW}:{line_number}; skipped")
                continue
            if not isinstance(record, dict):
                continue
            url = record.get("URL") or record.get("url")
            if isinstance(url, str) and url.strip():
                urls.append(url.strip())
    return list(dict.fromkeys(urls))


def load_records_by_url():
    """Load the latest saved record for each URL and whether any saved record has a price."""
    latest = {}
    ever_priced = set()
    if not os.path.exists(OUT):
        return latest, ever_priced

    with open(OUT, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(f"WARNING: Invalid JSON at {OUT}:{line_number}; ignored")
                continue
            if not isinstance(record, dict):
                continue
            url = record.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            url = url.strip()
            latest[url] = record
            if record.get("price_low") is not None or record.get("price_high") is not None:
                ever_priced.add(url)
    return latest, ever_priced


def save_record(record):
    """Append a single result to prices.jsonl."""
    with open(OUT, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_failed_url(url):
    with open(FAIL, "a", encoding="utf-8") as file:
        file.write(url + "\n")


def main():
    parser = argparse.ArgumentParser(description="Patch prices for existing machine URLs.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N URLs (useful for a test).")
    parser.add_argument(
        "--retry-empty",
        action="store_true",
        help="Retry URLs that were previously checked but never yielded a numeric price.",
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be a positive integer")
    if not Path(RAW).exists():
        print(f"ERROR: {RAW} is missing")
        return 1

    urls = load_urls()
    latest, ever_priced = load_records_by_url()

    if args.retry_empty:
        done = ever_priced
    else:
        done = set(latest)

    todo = [url for url in urls if url not in done]
    print("=" * 60)
    print("PRICE PATCH")
    print("=" * 60)
    print(f"Total URLs            : {len(urls):,}")
    print(f"URLs already recorded : {len(latest):,}")
    print(f"URLs with a saved price: {len(ever_priced):,}")
    print(f"Remaining              : {len(todo):,}")
    if args.retry_empty:
        print("Mode                   : retry URLs without a saved numeric price")
    if args.limit is not None:
        todo = todo[:args.limit]
        print(f"TEST LIMIT             : {args.limit}")
    print("=" * 60)

    for number, url in enumerate(todo, 1):
        print(f"[{number}/{len(todo)}] {url}")
        status, result = get_price(url)

        if status == "fail":
            append_failed_url(url)
            time.sleep(DELAY)
            continue

        record = {
            "url": url,
            "price_text": None,
            "price_low": None,
            "price_high": None,
            "price_type": None,
        }
        if result:
            record["price_text"], record["price_low"], record["price_high"], record["price_type"] = result
            print(f"  -> PRICE: {record['price_text']} ({record['price_type']})")
        else:
            print("  -> NO PRICE FOUND")
        save_record(record)
        time.sleep(DELAY)

    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
