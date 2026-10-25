#!/bin/bash
# Starts the Solvix Scraper app and opens it in your browser.
# Keep this window open while you use the app; close it to stop the app.
cd "$(dirname "$0")"
source .venv/bin/activate
python app.py
