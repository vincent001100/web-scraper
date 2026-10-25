# Web Scraper

A reusable Python scraper that follows "next page" links and saves results to a CSV spreadsheet.
One engine, many websites: each site is a short entry in the `SITES` settings.

## The app

A point-and-click version of the scraper that runs in your browser:

1. Start it: `./start_app.sh` (or `python app.py`)
2. Your browser opens at http://127.0.0.1:5000
3. Pick a website, choose how many pages, press **Start collecting**
4. Watch it work live, then download the results as **Excel, CSV, PDF, JSON or Text**

## Supported sites

| Command | Collects |
|---|---|
| `python scraper.py books` | Title, price and rating of every book on books.toscrape.com (1,000 books, 50 pages) |
| `python scraper.py quotes` | Quote, author and tags from quotes.toscrape.com (100 quotes, 10 pages) |
| `python scraper.py quotes_js` | The same quotes from a JavaScript site (data drawn by the page's own code), read with an invisible browser |
| `python scraper.py countries` | Name, capital, population and area of 250 countries |
| `python scraper.py hockey` | Hockey team results by season |
| `python scraper.py laptops` / `tablets` / `phones` | Product, price, description and reviews from a test online store |
| `python scraper.py jobs` | Job title, company, location and date from a job board |

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Adding a new site

Copy an entry in `SITES`, then set the start URL and the CSS selectors for the item box, its fields and the "next" button.

## Features

- Follows pagination until the last page
- Waits 1 second between pages to be polite to the website
- Missing fields become empty cells instead of crashing
- Timestamped output files
- JavaScript sites: set `"js": True` and the page is opened in an invisible Chrome browser first

## Daily data drop

Every morning at 06:00 UTC (07:00 Lagos time) GitHub runs `daily.py`, which:

1. Picks a random website from the menu in `scraper.py`
2. Checks the site's robots.txt to make sure scraping is allowed
3. Scrapes up to 5 pages and saves the data as a spreadsheet (CSV)
4. Takes a screenshot of the website
5. Makes a ready-to-post image and caption for Instagram, Facebook and TikTok

Everything is saved in the [`results`](results/README.md) folder, newest first.
To run it right away, open **Actions → Daily data drop → Run workflow**.
