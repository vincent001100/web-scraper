"""
Daily data drop: pick a random website from the menu in scraper.py,
check it allows scraping, scrape it, then make pictures ready for social media.

Everything for one day lands in results/<date>_<site>/:
  data.csv     the scraped data
  website.png  a screenshot of the website
  post.png     a ready-to-post image (Instagram / Facebook / TikTok photo)
  caption.txt  text to paste under the post
"""
import os
import random
import shutil
import sys
import textwrap
from datetime import datetime, timezone
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from PIL import Image, ImageDraw, ImageFont

from scraper import SITES, scrape

BRAND = "SOLVIX"
MAX_PAGES = 5          # keep each daily run small and polite
RESULTS = "results"

# Post colours: warm paper, deep ink, forest green brand, terracotta accent
BG, CARD, TEXT, MUTED = "#f4efe6", "#e8e0d0", "#1f2a24", "#6b675c"
BRAND_COLOUR, ACCENT = "#2f4a3a", "#b5532a"


def allowed_to_scrape(url):
    """Read the site's robots.txt (its rules for robots) and check we may visit url."""
    rules = RobotFileParser()
    try:
        response = requests.get(urljoin(url, "/robots.txt"), timeout=10)
    except requests.RequestException:
        return False  # can't reach the site at all: skip it today
    if response.status_code >= 400:
        return True   # no rules file means no restrictions
    rules.parse(response.text.splitlines())
    return rules.can_fetch("*", url)


def pick_site():
    """Try the menu in random order and return the first site that allows scraping."""
    names = list(SITES)
    random.shuffle(names)
    for name in names:
        if allowed_to_scrape(SITES[name]["start_url"]):
            return name
        print(f"⏭️  {name}: robots.txt says no, skipping")
    return None


def take_screenshot(url, path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.screenshot(path=path)
        browser.close()


def font(size, bold=False, serif=False):
    # DejaVu fonts come with most Linux systems (including GitHub's); fall back to Pillow's own
    family = "DejaVuSerif" if serif else "DejaVuSans"
    name = f"{family}-Bold.ttf" if bold else f"{family}.ttf"
    try:
        return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)
    except OSError:
        return ImageFont.load_default(size)


def shorten(text, width):
    return textwrap.shorten(str(text), width=width, placeholder="…")


def make_post(site, rows, screenshot_path, path, date_text):
    """Draw a 1080x1350 image (the portrait size Instagram, Facebook and TikTok all accept)."""
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Header: brand + date
    d.text((60, 55), BRAND, font=font(56, bold=True, serif=True), fill=BRAND_COLOUR)
    d.text((W - 60, 72), date_text, font=font(30), fill=MUTED, anchor="ra")
    d.text((60, 135), "Daily Data Drop", font=font(34), fill=MUTED)

    # Screenshot of the website, in a rounded frame
    shot = Image.open(screenshot_path).convert("RGB")
    shot = shot.resize((960, 600))
    mask = Image.new("L", shot.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *shot.size), radius=24, fill=255)
    img.paste(shot, (60, 200), mask)

    # Headline numbers
    columns = list(site["fields"])
    d.text((60, 835), site["name"], font=font(52, bold=True, serif=True), fill=TEXT)
    d.text((60, 905), f"{len(rows):,} records collected automatically  •  {len(columns)} data fields",
           font=font(28), fill=ACCENT)

    # A small preview table: first 2 columns of the first 5 rows
    d.rounded_rectangle((60, 965, W - 60, 1215), radius=20, fill=CARD)
    show = columns[:2]
    d.text((90, 985), shorten(show[0].upper(), 30), font=font(22, bold=True), fill=MUTED)
    if len(show) > 1:
        d.text((W - 90, 985), shorten(show[1].upper(), 20), font=font(22, bold=True), fill=MUTED, anchor="ra")
    for i, row in enumerate(rows[:5]):
        y = 1025 + i * 36
        d.text((90, y), shorten(row[show[0]], 44), font=font(26), fill=TEXT)
        if len(show) > 1:
            d.text((W - 90, y), shorten(row[show[1]], 22), font=font(26), fill=TEXT, anchor="ra")

    # Footer: the offer
    d.text((W // 2, 1260), "Need data from the web? I build custom scrapers.",
           font=font(30, bold=True, serif=True), fill=BRAND_COLOUR, anchor="ma")
    d.text((W // 2, 1302), "Web scraping  •  Automation  •  Python", font=font(24), fill=MUTED, anchor="ma")

    img.save(path)


def write_caption(site, rows, path):
    fields = ", ".join(site["fields"])
    caption = f"""📊 Daily Data Drop: {site['name']}

My scraper collected {len(rows):,} records today, fully automatic ({fields}).
Every morning it picks a website, checks it's allowed, collects the data and delivers a clean spreadsheet.

Need prices, products, leads or listings collected for your business? DM me.

#webscraping #python #automation #dataextraction #freelancer #{BRAND.lower()}
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(caption)


def add_to_index(folder, site, rows, date_text):
    """Put today's result at the top of results/README.md, a gallery of every run."""
    index = os.path.join(RESULTS, "README.md")
    header = "# Daily Data Drops\n\nA new website is scraped automatically every morning. Newest first.\n\n"
    old = ""
    if os.path.exists(index):
        old = open(index, encoding="utf-8").read().replace(header, "", 1)
    rel = os.path.basename(folder)
    entry = (f"## {date_text}: {site['name']} ({len(rows):,} records)\n\n"
             f"[Data (CSV)]({rel}/data.csv) · [Caption]({rel}/caption.txt)\n\n"
             f"![{site['name']}]({rel}/post.png)\n\n")
    with open(index, "w", encoding="utf-8") as f:
        f.write(header + entry + old)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else pick_site()
    if name is None:
        print("No site in the menu allows scraping today.")
        sys.exit(1)
    site = SITES[name]
    now = datetime.now(timezone.utc)
    date_text = now.strftime("%d %b %Y")
    folder = os.path.join(RESULTS, f"{now:%Y-%m-%d}_{name}")
    print(f"🎲 Today's site: {site['name']} ({site['start_url']})")

    rows, csv_path = scrape(name, folder=folder, max_pages=MAX_PAGES)
    if not rows:
        print("Scraped 0 records: the site may have changed its layout.")
        sys.exit(1)
    shutil.move(csv_path, os.path.join(folder, "data.csv"))

    shot = os.path.join(folder, "website.png")
    take_screenshot(site["start_url"], shot)
    make_post(site, rows, shot, os.path.join(folder, "post.png"), date_text)
    write_caption(site, rows, os.path.join(folder, "caption.txt"))
    add_to_index(folder, site, rows, date_text)
    print(f"✓ Results saved in {folder}")


if __name__ == "__main__":
    main()
