# Web Scraper

A reusable Python scraper that follows "next page" links and saves results to a CSV spreadsheet.
One engine, many websites: each site is a short entry in the `SITES` settings.

## Supported sites

| Command | Collects |
|---|---|
| `python scraper.py books` | Title, price and rating of every book on books.toscrape.com (1,000 books, 50 pages) |
| `python scraper.py quotes` | Quote, author and tags from quotes.toscrape.com (100 quotes, 10 pages) |

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Adding a new site

Copy an entry in `SITES`, then set the start URL and the CSS selectors for the item box, its fields and the "next" button.

## Features

- Follows pagination until the last page
- Waits 1 second between pages to be polite to the website
- Missing fields become empty cells instead of crashing
- Timestamped output files

## Automatic daily runs

GitHub runs both scrapers every day at 06:00 UTC (see `.github/workflows/scrape.yml`).
Download the results from the **Actions** tab: open a run and click **scraped-data**.
To run it right away, open **Actions → Daily scrape → Run workflow**.
