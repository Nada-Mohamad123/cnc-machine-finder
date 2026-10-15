"""
scrape_all.py

Full scraper for machinetoolindex.com

هذا الملف للاستخدام فقط إذا احتجنا لاحقًا
إعادة جمع بيانات الماكينات من البداية.

لا تشغله الآن طالما raw_machines.jsonl
يحتوي بالفعل على الماكينات.

الاستخدام:
    python scrape_all.py

أو تقسيم الـ categories:
    python scrape_all.py 0 4
    python scrape_all.py 4 8

المخرج:
    raw_machines.jsonl
    failed_urls.txt
"""

import json
import os
import sys
import time

import requests

from bs4 import BeautifulSoup
from urllib.parse import urljoin


BASE = "https://www.machinetoolindex.com"

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "02_raw_data", "raw_machines.jsonl")

FAIL = os.path.join(HERE, "failed_urls.txt")


S = requests.Session()

S.headers.update({
    "User-Agent": "Mozilla/5.0"
})


# ============================================================
# REQUEST
# ============================================================

def soup(url, tries=3):

    for attempt in range(tries):

        try:

            response = S.get(
                url,
                timeout=20
            )

            response.raise_for_status()

            response.encoding = "utf-8"

            return BeautifulSoup(
                response.text,
                "html.parser"
            )

        except Exception:

            if attempt < tries - 1:

                time.sleep(
                    2 * (attempt + 1)
                )

    with open(
        FAIL,
        "a",
        encoding="utf-8"
    ) as file:

        file.write(
            url + "\n"
        )

    return None


# ============================================================
# CATEGORIES
# ============================================================

def categories():

    page = soup(
        BASE + "/categories"
    )

    if not page:
        return []

    seen = set()

    result = []

    for link in page.select(
        "a[href*='/categories/']"
    ):

        href = link.get("href")

        if not href:
            continue

        url = urljoin(
            BASE,
            href
        ).rstrip("/")

        if url in seen:
            continue

        if url.endswith(
            "/categories"
        ):

            continue

        seen.add(url)

        category_name = (
            url
            .split("/")[-1]
            .replace("-", " ")
            .title()
        )

        result.append({
            "category": category_name,
            "url": url
        })

    return result


# ============================================================
# MACHINE LINKS
# ============================================================

def machine_links(category_url):

    links = []

    page_number = 1

    while True:

        if page_number == 1:

            url = category_url

        else:

            url = (
                f"{category_url}"
                f"?page={page_number}"
            )

        page = soup(url)

        if not page:
            break

        new_links = []

        for link in page.select(
            "a[href*='/machines/']"
        ):

            href = link.get("href")

            if not href:
                continue

            machine_url = urljoin(
                BASE,
                href
            )

            new_links.append(
                machine_url
            )

        new_links = list(
            dict.fromkeys(
                new_links
            )
        )

        new_links = [
            url
            for url in new_links
            if url not in links
        ]

        if not new_links:
            break

        links.extend(
            new_links
        )

        has_next = any(
            link.get_text(
                strip=True
            ).lower() == "next"
            for link in page.find_all(
                "a",
                href=True
            )
        )

        if not has_next:
            break

        page_number += 1

        time.sleep(1)

    return links


# ============================================================
# MACHINE
# ============================================================

def machine(url, category):

    page = soup(url)

    if not page:
        return None

    data = {

        "URL": url,

        "Category": category,

        "Machine Name": "",

        "Manufacturer": "",

        "Price": "",

        "Description": ""
    }

    # --------------------------------------------------------
    # Machine Name
    # --------------------------------------------------------

    h1 = page.find("h1")

    if h1:

        data["Machine Name"] = (
            h1.get_text(
                " ",
                strip=True
            )
        )

    # --------------------------------------------------------
    # Manufacturer
    # --------------------------------------------------------

    manufacturer = page.select_one(
        "a[href*='/manufacturers/']"
    )

    if manufacturer:

        data["Manufacturer"] = (
            manufacturer.get_text(
                " ",
                strip=True
            )
        )

    # --------------------------------------------------------
    # Price
    # --------------------------------------------------------

    import re

    chunk = ""

    if h1:

        for element in h1.find_all_next(
            limit=12
        ):

            chunk += (
                " "
                + element.get_text(
                    " ",
                    strip=True
                )
            )

    chunk = chunk[:600]

    price_pattern = re.compile(
        r"(Est\.?)?\s*"
        r"((?:US)?\$\s?\d[\d,]*(?:\.\d+)?)"
        r"(?:\s*[-–—]\s*"
        r"((?:US)?\$\s?\d[\d,]*(?:\.\d+)?))?",
        re.I
    )

    price_match = price_pattern.search(
        chunk
    )

    if price_match:

        data["Price"] = (
            price_match
            .group(0)
            .strip()
        )

    # --------------------------------------------------------
    # Description
    # --------------------------------------------------------

    for paragraph in page.find_all("p"):

        text = paragraph.get_text(
            " ",
            strip=True
        )

        if len(text) > 50:

            data["Description"] = text

            break

    # --------------------------------------------------------
    # Specifications
    # --------------------------------------------------------

    for row in page.select(
        "table tr"
    ):

        cells = row.find_all(
            ["th", "td"]
        )

        if len(cells) < 2:
            continue

        key = cells[0].get_text(
            " ",
            strip=True
        )

        value = cells[1].get_text(
            " ",
            strip=True
        )

        if not key or not value:
            continue

        if key == "Parameter":
            continue

        data[key] = value

    return data


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    # --------------------------------------------------------
    # category range
    # --------------------------------------------------------

    low = (
        int(sys.argv[1])
        if len(sys.argv) > 1
        else 0
    )

    high = (
        int(sys.argv[2])
        if len(sys.argv) > 2
        else None
    )

    # --------------------------------------------------------
    # already scraped URLs
    # --------------------------------------------------------

    done = set()

    if os.path.exists(OUT):

        with open(
            OUT,
            encoding="utf-8"
        ) as file:

            for line in file:

                if not line.strip():
                    continue

                try:

                    record = json.loads(
                        line
                    )

                    url = record.get(
                        "URL"
                    )

                    if url:
                        done.add(url)

                except json.JSONDecodeError:

                    continue

    # --------------------------------------------------------
    # categories
    # --------------------------------------------------------

    all_categories = categories()

    selected_categories = (
        all_categories[low:high]
    )

    print()
    print("=" * 60)
    print("FULL SCRAPER")
    print("=" * 60)

    print(
        f"Categories selected: "
        f"{len(selected_categories)}"
    )

    print(
        f"Already scraped: "
        f"{len(done)}"
    )

    print("=" * 60)

    # --------------------------------------------------------
    # scraping
    # --------------------------------------------------------

    for category in selected_categories:

        links = machine_links(
            category["url"]
        )

        links = [
            url
            for url in links
            if url not in done
        ]

        print()
        print(
            f"{category['category']}: "
            f"{len(links)} to scrape"
        )

        for number, url in enumerate(
            links,
            1
        ):

            data = machine(
                url,
                category["category"]
            )

            if data:

                with open(
                    OUT,
                    "a",
                    encoding="utf-8"
                ) as file:

                    file.write(
                        json.dumps(
                            data,
                            ensure_ascii=False
                        ) + "\n"
                    )

            if number % 25 == 0:

                print(
                    f"  {number}/{len(links)}"
                )

            time.sleep(2)

    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)