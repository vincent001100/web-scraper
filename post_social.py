"""
Post today's data drop to the Solvix Facebook Page and Instagram account.

Runs on GitHub after daily.py has saved and pushed results/<date>_<site>/.
Ways to post (set the secrets in GitHub: Settings → Secrets and variables → Actions):
  0. BUFFER_API_KEY    hand the post to Buffer, which publishes it at an exact time
                       (see buffer_post.py and BUFFER-SETUP.md). If this secret exists it is used
                       INSTEAD of the two ways below; if it does not exist, nothing changes.
  1. MAKE_WEBHOOK_URL  hand the post to a Make.com scenario, which posts it for us
                       (no Meta developer account needed)
  2. META_PAGE_TOKEN + FB_PAGE_ID + IG_USER_ID  post straight to Meta's API ourselves
If none is set it skips posting instead of failing, so the scraping still runs.
"""
import os
import sys
import time

import requests

GRAPH = "https://graph.facebook.com/v23.0"   # Meta's API address (with its version number)
RESULTS = "results"


def latest_folder():
    folders = sorted(f for f in os.listdir(RESULTS) if os.path.isdir(os.path.join(RESULTS, f)))
    return os.path.join(RESULTS, folders[-1])


def check(response):
    """Stop with Meta's own error message if a request failed."""
    data = response.json()
    if "error" in data:
        sys.exit(f"Meta said: {data['error'].get('message')}")
    return data


def post_to_facebook(token, page_id, image_path, caption):
    with open(image_path, "rb") as image:
        data = check(requests.post(f"{GRAPH}/{page_id}/photos",
                                   data={"caption": caption, "access_token": token},
                                   files={"source": image}, timeout=60))
    print(f"✓ Posted to Facebook (post {data.get('post_id', data.get('id'))})")


def post_to_instagram(token, ig_user_id, image_url, caption):
    # Instagram works in 2 steps: upload the picture as a draft, then publish the draft
    draft = check(requests.post(f"{GRAPH}/{ig_user_id}/media",
                                data={"image_url": image_url, "caption": caption, "access_token": token},
                                timeout=60))["id"]
    for _ in range(12):   # wait up to a minute for Instagram to finish fetching the picture
        status = check(requests.get(f"{GRAPH}/{draft}",
                                    params={"fields": "status_code", "access_token": token},
                                    timeout=30)).get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            sys.exit("Instagram could not process the picture.")
        time.sleep(5)
    data = check(requests.post(f"{GRAPH}/{ig_user_id}/media_publish",
                               data={"creation_id": draft, "access_token": token}, timeout=60))
    print(f"✓ Posted to Instagram (post {data['id']})")


def send_to_make(webhook_url, image_url, caption, folder):
    response = requests.post(webhook_url, timeout=60, json={
        "image_url": image_url,
        "caption": caption,
        "title": os.path.basename(folder),
    })
    response.raise_for_status()
    print(f"✓ Sent to Make.com, which posts it to Facebook and Instagram ({response.text.strip()})")


def main():
    # Buffer is switched on by one thing only: the BUFFER_API_KEY secret. buffer_post.py does the
    # whole job, and any problem there ends the run with a red X on GitHub.
    if os.environ.get("BUFFER_API_KEY", "").strip():
        import buffer_post
        sys.exit(buffer_post.main(["daily"]))

    webhook_url = os.environ.get("MAKE_WEBHOOK_URL")
    token = os.environ.get("META_PAGE_TOKEN")
    page_id = os.environ.get("FB_PAGE_ID")
    ig_user_id = os.environ.get("IG_USER_ID")
    if not (webhook_url or (token and page_id and ig_user_id)):
        print("No posting secrets set yet: skipping social posting.")
        return

    folder = latest_folder()
    with open(os.path.join(folder, "caption.txt"), encoding="utf-8") as f:
        caption = f.read()

    # Instagram fetches the picture from a public web address, so we point it at the copy on GitHub
    repo = os.environ.get("GITHUB_REPOSITORY", "vincent001100/web-scraper")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    image_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{folder}/post.jpg"

    if webhook_url:
        send_to_make(webhook_url, image_url, caption, folder)
        return
    post_to_facebook(token, page_id, os.path.join(folder, "post.png"), caption)
    post_to_instagram(token, ig_user_id, image_url, caption)


if __name__ == "__main__":
    main()
