"""
Solvix Scraper: the scraper as a web page you use in your browser.

Start it with:   python app.py     (then open http://127.0.0.1:5000)
"""
import json
import queue
import tempfile
import threading
import time
import uuid
import webbrowser

from flask import Flask, Response, abort, render_template, request

from daily import allowed_to_scrape
from exports import FORMATS
from scraper import SITES, scrape

app = Flask(__name__)
JOBS = {}  # finished scrapes, kept in memory so they can be downloaded

# How each site appears in the app. A site missing here still works, it just gets the defaults.
LOOKS = {
    "books":     {"category": "Online store", "icon": "book",     "about": "Titles, prices and star ratings"},
    "quotes":    {"category": "Content",      "icon": "quote",    "about": "Quotes, authors and tags"},
    "quotes_js": {"category": "JavaScript",   "icon": "code",     "about": "Quotes from a page drawn by code"},
    "countries": {"category": "Public data",  "icon": "globe",    "about": "Capital, population and area"},
    "hockey":    {"category": "Sports stats", "icon": "chart",    "about": "Wins and losses by season"},
    "laptops":   {"category": "Online store", "icon": "laptop",   "about": "Products, prices and reviews"},
    "tablets":   {"category": "Online store", "icon": "tablet",   "about": "Products, prices and reviews"},
    "phones":    {"category": "Online store", "icon": "phone",    "about": "Products, prices and reviews"},
    "jobs":      {"category": "Job board",    "icon": "briefcase", "about": "Job titles, companies and locations"},
}


def site_cards():
    return [
        {
            "key": key,
            "name": site["name"],
            "url": site["start_url"],
            "fields": list(site["fields"]),
            "paged": "next" in site,
            "js": bool(site.get("js")),
            **{"category": "Website", "icon": "globe", "about": ", ".join(site["fields"]).capitalize()},
            **LOOKS.get(key, {}),
        }
        for key, site in SITES.items()
    ]


@app.get("/")
def home():
    return render_template("index.html", sites=site_cards())


@app.get("/api/scrape")
def run_scrape():
    """Scrape a site and stream live progress to the page, one message per step."""
    name = request.args.get("site")
    if name not in SITES:
        abort(404)
    pages = int(request.args.get("pages", 3)) or None  # 0 means "every page"
    updates = queue.Queue()

    def work():
        started = time.time()
        try:
            updates.put({"type": "check"})
            if not allowed_to_scrape(SITES[name]["start_url"]):
                updates.put({"type": "error", "message": "This website's rules (robots.txt) don't allow scraping it."})
                return
            updates.put({"type": "allowed"})
            on_page = lambda page, found, total: updates.put(
                {"type": "page", "page": page, "found": found, "total": total})
            with tempfile.TemporaryDirectory() as folder:
                rows, _ = scrape(name, folder=folder, max_pages=pages, progress=on_page)
            job = uuid.uuid4().hex[:12]
            JOBS[job] = (name, rows)
            updates.put({"type": "done", "job": job, "rows": rows, "fields": list(SITES[name]["fields"]),
                         "seconds": round(time.time() - started, 1)})
        except Exception as error:
            updates.put({"type": "error", "message": str(error)})
        finally:
            updates.put(None)  # tells the stream below that we're finished

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while (update := updates.get()) is not None:
            yield f"data: {json.dumps(update, ensure_ascii=False)}\n\n"

    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/download/<job>/<extension>")
def download(job, extension):
    if job not in JOBS or extension not in FORMATS:
        abort(404)
    name, rows = JOBS[job]
    make_file, mime = FORMATS[extension]
    data = make_file(rows, list(SITES[name]["fields"]), SITES[name]["name"])
    filename = f"solvix_{name}_{time.strftime('%Y%m%d_%H%M')}.{extension}"
    return Response(data, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


if __name__ == "__main__":
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(port=5000, threaded=True)
