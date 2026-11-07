"""
Solvix official page: one promo post a day at 13:00 Lagos (12:00 UTC). Boss approved 7 Nov 2026.

THE FLOW (GitHub Actions, the PC can be off)
  * The posts (pictures, captions, dates) live on the public branch "solvix-media",
    in promo/<set>/schedule.json, because Buffer fetches pictures from a public web address.
  * Every evening the robot books the NEXT post(s) in Buffer: every post due in the next 36 hours
    that is not booked yet. Booking one day ahead keeps the free plan's queue from filling up,
    and a late GitHub timer still has a whole night to catch up.
  * Each booking is written down in promo/<set>/records/<date>/buffer-posts.json, so a re-run or
    the next evening never books the same day twice.

SAFETY
  * Only BUFFER_API_KEY (the Solvix Buffer). The Pet Shelf key never reaches this robot.
  * mode=draft saves Buffer drafts only and writes no record.
  * Captions are checked (length, hashtags) before anything is sent. Any refusal = red X.

Run by hand: Actions, Solvix promo, Run workflow (day = next or a date like 2026-11-08; mode post/draft).
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

from buffer_post import (Buffer, BufferError, Plan, check_caption, check_picture_is_public, channel_ids_from,
                         human_time, now_utc, pick_channels, read_record_posts, say, schedule_posts, write_summary)

MEDIA_BRANCH = "solvix-media"
MEDIA_DIR = "solvix-media-checkout"
POST_HOUR_UTC = 12                      # 13:00 Lagos, all year (Nigeria has no summer time)
LOOK_AHEAD = timedelta(hours=36)
MIN_LEAD = timedelta(minutes=10)


class PromoProblem(Exception):
    """Something stopped the run. Written for boss, in plain words."""


def git(*args, cwd=None):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise PromoProblem(f"A git step failed (git {args[0]}): {result.stderr[-300:]}")
    return result.stdout.strip()


def due_time(day):
    return datetime(day.year, day.month, day.day, POST_HOUR_UTC, tzinfo=timezone.utc)


def load_schedule(base):
    """Every entry of every promo/<set>/schedule.json, oldest first."""
    entries = []
    promo = os.path.join(base, "promo")
    for name in sorted(os.listdir(promo)) if os.path.isdir(promo) else []:
        path = os.path.join(promo, name, "schedule.json")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            for item in json.load(f)["posts"]:
                entries.append(dict(item, set=name, day=date.fromisoformat(item["date"])))
    days = [e["day"] for e in entries]
    if len(days) != len(set(days)):
        raise PromoProblem("Two posts are planned for the same day in the schedule, so I stopped.")
    return sorted(entries, key=lambda e: e["day"])


def record_folder(base, entry):
    return os.path.join(base, "promo", entry["set"], "records", entry["date"])


def pick_entries(entries, base, now, day="next"):
    """'next' = every post due in the next 36 hours that is not booked yet. Or one exact date."""
    if day and day != "next":
        wanted = [e for e in entries if e["date"] == day]
        if not wanted:
            raise PromoProblem(f"There is no post planned for {day}.")
        if due_time(wanted[0]["day"]) <= now + MIN_LEAD:
            raise PromoProblem(f"The 13:00 Lagos time for {day} has already passed or is too close.")
        return wanted
    return [e for e in entries
            if now + MIN_LEAD < due_time(e["day"]) <= now + LOOK_AHEAD
            and not read_record_posts(record_folder(base, e))]


def image_url(env, entry):
    repo = env.get("GITHUB_REPOSITORY") or "vincent001100/web-scraper"
    return f"https://raw.githubusercontent.com/{repo}/{MEDIA_BRANCH}/promo/{entry['set']}/{entry['image']}"


def book(entry, buffer, targets, env, base, draft, clock):
    caption = entry["caption"]
    check_caption(caption)
    url = image_url(env, entry)
    check_picture_is_public(url, sleep=buffer.sleep)
    plan = Plan("customScheduled", due_time(entry["day"]), entry["day"])
    folder = None if draft else record_folder(base, entry)
    if folder:
        os.makedirs(folder, exist_ok=True)
    skip = {p["service"]: (folder, p["post_id"]) for p in read_record_posts(folder)} if folder else {}
    created = schedule_posts(buffer, targets, caption, url, plan, folder=folder, clock=clock, draft=draft, skip=skip)
    return f"{entry['date']} ({entry['title']}): {len(created)} post(s) {'saved as drafts' if draft else 'booked for ' + human_time(plan.due_at)}"


def main(env=None, clock=now_utc):
    env = os.environ if env is None else env
    day = (env.get("PROMO_DAY") or "next").strip()
    mode = (env.get("PROMO_MODE") or "post").strip().lower()
    if mode not in ("post", "draft"):
        raise PromoProblem(f"mode must be post or draft, not '{mode}'.")
    git("fetch", "--depth=1", "origin", MEDIA_BRANCH)
    git("worktree", "add", "--detach", MEDIA_DIR, "FETCH_HEAD")
    entries = load_schedule(MEDIA_DIR)
    chosen = pick_entries(entries, MEDIA_DIR, clock(), day)
    if not chosen:
        say("Nothing to book: every post due in the next 36 hours is already in Buffer.")
        write_summary("### Solvix promo\nNothing new to book.")
        return
    buffer = Buffer(env.get("BUFFER_API_KEY"))
    targets = pick_channels(buffer.channels(), channel_ids_from(env))
    lines = []
    try:
        for entry in chosen:
            lines.append(book(entry, buffer, targets, env, MEDIA_DIR, mode == "draft", clock))
            say(lines[-1])
    finally:
        git("add", "-A", cwd=MEDIA_DIR)
        if git("status", "--porcelain", cwd=MEDIA_DIR):
            git("-c", "user.name=Solvix", "-c", "user.email=174953671+vincent001100@users.noreply.github.com",
                "commit", "-m", f"Solvix promo records ({day}, {mode})", cwd=MEDIA_DIR)
            git("push", "origin", git("rev-parse", "HEAD", cwd=MEDIA_DIR) + f":refs/heads/{MEDIA_BRANCH}")
    write_summary("### Solvix promo\n" + "\n".join(f"- {line}" for line in lines))


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except (PromoProblem, BufferError) as problem:
        print(f"::error title=Solvix promo failed::{str(problem).replace(chr(10), '%0A')}", flush=True)
        write_summary(f"### Solvix promo FAILED\n{problem}")
        sys.exit(1)
