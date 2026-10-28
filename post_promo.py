"""
Post the Solvix advert (brand/promo/) to Facebook and Instagram.

Runs on GitHub once a week (see .github/workflows/weekly-promo.yml).
Two ways to post:
  * BUFFER_API_KEY secret set  -> through Buffer (see buffer_post.py and BUFFER-SETUP.md)
  * otherwise MAKE_WEBHOOK_URL -> through Make.com, exactly as before
"""
import os
import sys

from post_social import send_to_make

FOLDER = "brand/promo"


def main():
    # Buffer is switched on by one thing only: the BUFFER_API_KEY secret.
    if os.environ.get("BUFFER_API_KEY", "").strip():
        import buffer_post
        sys.exit(buffer_post.main(["promo"]))

    webhook_url = os.environ.get("MAKE_WEBHOOK_URL")
    if not webhook_url:
        print("No MAKE_WEBHOOK_URL set: skipping the advert.")
        return
    with open(os.path.join(FOLDER, "caption.txt"), encoding="utf-8") as f:
        caption = f.read()
    # Instagram fetches the picture from a public web address, so we point it at the copy on GitHub
    repo = os.environ.get("GITHUB_REPOSITORY", "vincent001100/web-scraper")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    image_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{FOLDER}/automation-post.jpg"
    send_to_make(webhook_url, image_url, caption, FOLDER)


if __name__ == "__main__":
    main()
