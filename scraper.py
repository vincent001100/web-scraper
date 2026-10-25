import requests
from bs4 import BeautifulSoup
import csv
import os
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

# ============================================================
# SETTINGS: one entry per website.
# To scrape a new site, copy an entry and change the labels.
#   name      : a friendly name for posts and reports
#   start_url : the first page to visit
#   item      : the box that holds ONE item (one book, one quote...)
#   fields    : what to grab from inside each box
#               "css"  = where it is inside the box
#               "attr" = (optional) grab a hidden label instead of the visible text
#               "all"  = (optional) grab every match and join them with commas
#   next      : where the "next page" button is (leave out if there is only one page)
#
# Only add sites that allow scraping (check their robots.txt and terms).
# ============================================================
SITES = {
    "books": {
        "name": "Online Bookstore",
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
        "name": "Famous Quotes",
        "start_url": "https://quotes.toscrape.com/",
        "item": "div.quote",
        "fields": {
            "quote":  {"css": "span.text"},
            "author": {"css": "small.author"},
            "tags":   {"css": "a.tag", "all": True},
        },
        "next": "li.next a",
    },
    "countries": {
        "name": "Countries of the World",
        "start_url": "https://www.scrapethissite.com/pages/simple/",
        "item": "div.country",
        "fields": {
            "country":    {"css": "h3.country-name"},
            "capital":    {"css": "span.country-capital"},
            "population": {"css": "span.country-population"},
            "area_km2":   {"css": "span.country-area"},
        },
    },
    "hockey": {
        "name": "Hockey Team Stats",
        "start_url": "https://www.scrapethissite.com/pages/forms/?page_num=1",
        "item": "tr.team",
        "fields": {
            "team":   {"css": "td.name"},
            "year":   {"css": "td.year"},
            "wins":   {"css": "td.wins"},
            "losses": {"css": "td.losses"},
        },
        "next": 'a[aria-label="Next"]',
    },
    "laptops": {
        "name": "Laptop Store",
        "start_url": "https://webscraper.io/test-sites/e-commerce/static/computers/laptops",
        "item": "div.thumbnail",
        "fields": {
            "product":     {"css": "a.title", "attr": "title"},
            "price":       {"css": "span[itemprop=price]"},
            "description": {"css": "p.description"},
            "reviews":     {"css": "span[itemprop=reviewCount]"},
        },
        "next": 'a[rel="next"]',
    },
    "tablets": {
        "name": "Tablet Store",
        "start_url": "https://webscraper.io/test-sites/e-commerce/static/computers/tablets",
        "item": "div.thumbnail",
        "fields": {
            "product":     {"css": "a.title", "attr": "title"},
            "price":       {"css": "span[itemprop=price]"},
            "description": {"css": "p.description"},
            "reviews":     {"css": "span[itemprop=reviewCount]"},
        },
        "next": 'a[rel="next"]',
    },
    "phones": {
        "name": "Phone Store",
        "start_url": "https://webscraper.io/test-sites/e-commerce/static/phones/touch",
        "item": "div.thumbnail",
        "fields": {
            "product":     {"css": "a.title", "attr": "title"},
            "price":       {"css": "span[itemprop=price]"},
            "description": {"css": "p.description"},
            "reviews":     {"css": "span[itemprop=reviewCount]"},
        },
        "next": 'a[rel="next"]',
    },
    "jobs": {
        "name": "Job Listings",
        "start_url": "https://realpython.github.io/fake-jobs/",
        "item": "div.card-content",
        "fields": {
            "job":      {"css": "h2.title"},
            "company":  {"css": "h3.company"},
            "location": {"css": "p.location"},
            "posted":   {"css": "time"},
        },
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


def scrape(site_name, folder=".", max_pages=None):
    """Scrape one site, save a CSV in `folder`, and return (rows, csv_path)."""
    site = SITES[site_name]
    url = site["start_url"]
    visited = set()
    data = []
    page = 1
    # Keep going as long as there is a new page to visit (and we haven't hit the page limit)
    while url and url not in visited:
        visited.add(url)
        print(f"🔄 Page {page}: connecting...")
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # stop if the site answered with an error
        soup = BeautifulSoup(response.content, 'html.parser')
        items = soup.select(site["item"])
        print(f"✓ Found {len(items)} items")

        for box in items:
            data.append({name: get_value(box, rule) for name, rule in site["fields"].items()})

        # Look for the "next" button; on the last page it doesn't exist, so we stop
        next_button = soup.select_one(site["next"]) if "next" in site else None
        if next_button and (max_pages is None or page < max_pages):
            url = urljoin(url, next_button.get('href'))
            page += 1
            time.sleep(1)  # wait 1 second between pages to be polite to the website
        else:
            url = None

    print(f"✓ Total: {len(data)} items from {page} pages")
    os.makedirs(folder, exist_ok=True)
    filename = os.path.join(folder, f"{site_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(site["fields"]))
        writer.writeheader()
        writer.writerows(data)

    print(f"✓ Saved to {filename}")
    return data, filename


# Which site to scrape comes from the command, e.g.:  python scraper.py quotes
if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in SITES:
        print(f"Usage: python scraper.py <site>   (choose from: {', '.join(SITES)})")
        sys.exit(1)
    try:
        scrape(sys.argv[1])
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)  # tell whoever ran us (e.g. GitHub) that it failed
