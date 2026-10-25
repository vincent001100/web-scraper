import requests
from bs4 import BeautifulSoup
import csv
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

# ============================================================
# SETTINGS: one entry per website.
# To scrape a new site, copy an entry and change the labels.
#   start_url : the first page to visit
#   item      : the box that holds ONE item (one book, one quote...)
#   fields    : what to grab from inside each box
#               "css"  = where it is inside the box
#               "attr" = (optional) grab a hidden label instead of the visible text
#   next      : where the "next page" button is
# ============================================================
SITES = {
    "books": {
        "start_url": "http://books.toscrape.com/catalogue/page-1.html",
        "item": "article.product_pod",
        "fields": {
            "title":  {"css": "h3 a", "attr": "title"},
            "price":  {"css": "p.price_color"},
            "rating": {"css": "p.star-rating", "attr": "class"},
        },
        "next": "li.next a",
    },
    "quotes": {
        "start_url": "https://quotes.toscrape.com/",
        "item": "div.quote",
        "fields": {
            "quote":  {"css": "span.text"},
            "author": {"css": "small.author"},
            "tags":   {"css": "a.tag", "all": True},
        },
        "next": "li.next a",
    },
}


# ============================================================
# ENGINE: the same for every website. You rarely need to touch this.
# ============================================================
def get_value(box, rule):
    # "all" means there can be several (like tags), so join them with commas
    if rule.get("all"):
        return ", ".join(el.get_text(strip=True) for el in box.select(rule["css"]))

    el = box.select_one(rule["css"])
    if el is None:
        return ""  # not found on this item: leave the cell empty instead of crashing
    if "attr" in rule:
        value = el.get(rule["attr"], "")
        # Some labels hold several words (e.g. class="star-rating Three"); keep the last one
        return value[-1] if isinstance(value, list) else value
    return el.get_text(strip=True)


def scrape(site_name):
    site = SITES[site_name]
    url = site["start_url"]
    data = []
    page = 1
    try:
        # Keep going as long as there is a page to visit
        while url:
            print(f"🔄 Page {page}: connecting...")
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            items = soup.select(site["item"])
            print(f"✓ Found {len(items)} items")

            for box in items:
                data.append({name: get_value(box, rule) for name, rule in site["fields"].items()})

            # Look for the "next" button; on the last page it doesn't exist, so we stop
            next_button = soup.select_one(site["next"])
            if next_button:
                url = urljoin(url, next_button.get('href'))
                page += 1
                time.sleep(1)  # wait 1 second between pages to be polite to the website
            else:
                url = None

        print(f"✓ Total: {len(data)} items from {page} pages")
        filename = f"{site_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(site["fields"]))
            writer.writeheader()
            writer.writerows(data)

        print(f"✓ Saved to {filename}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)  # tell whoever ran us (e.g. GitHub) that it failed


# Which site to scrape comes from the command, e.g.:  python scraper.py quotes
if len(sys.argv) < 2 or sys.argv[1] not in SITES:
    print(f"Usage: python scraper.py <site>   (choose from: {', '.join(SITES)})")
else:
    scrape(sys.argv[1])
