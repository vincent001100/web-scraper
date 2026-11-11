"""
Pet Shelf weekly queue: books the next day's posts by itself every evening (boss, 11 Nov 2026).

THE FLOW (GitHub Actions, the PC can be off)
  * Once a week the team puts the approved posts in queue/<name>.json on the pet-shelf-media branch:
    date, Lagos time, the finished advert files in ready/, the caption and hashtags.
  * Every evening (and once in the morning as a backup) this robot books every queued post that is due
    in the next 36 hours and not booked yet. Each one goes through the normal order robot
    (pet_shelf_order.run_order), so every rule and check still applies: #ad, link in bio, team adverts only,
    TikTok gets a video, Buffer confirms every channel.
  * Boss's rule (11 Nov 2026): previews go to boss; if there is no reply by 08:00, the posts go out.
    A post boss stops gets "status": "hold" (or is cancelled with the Pet Shelf cancel workflow).
  * A post counts as booked when an orders/*/order.json carries its queue_id and Buffer has it.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pet_shelf_order as robot
from buffer_post import BufferError, now_utc, say, write_summary

QUEUE_DIR = "pet-shelf-queue-checkout"
LAGOS = timezone(timedelta(hours=1))
LOOK_AHEAD = timedelta(hours=36)
MIN_LEAD = timedelta(minutes=40)            # time to make the TikTok video and reach Buffer


class QueueProblem(Exception):
    pass


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise QueueProblem(f"A git step failed (git {args[0]}): {r.stderr[-300:]}")
    return r.stdout.strip()


def due_time(entry):
    day = datetime.strptime(f"{entry['date']} {entry['time']}", "%Y-%m-%d %H:%M")
    return day.replace(tzinfo=LAGOS).astimezone(timezone.utc)


def load_queue(base):
    entries, ids = [], set()
    for path in sorted(glob.glob(os.path.join(base, "queue", "*.json"))):
        with open(path, encoding="utf-8") as f:
            for item in json.load(f)["posts"]:
                if item["id"] in ids:
                    raise QueueProblem(f"The queue id {item['id']} is used twice, so I stopped.")
                ids.add(item["id"])
                entries.append(item)
    return sorted(entries, key=due_time)


def booked_ids(base):
    """queue ids that already have a real Buffer booking (not cancelled)."""
    done = set()
    for order_file in glob.glob(os.path.join(base, "orders", "*", "order.json")):
        with open(order_file, encoding="utf-8") as f:
            qid = json.load(f).get("queue_id")
        record = os.path.join(os.path.dirname(order_file), robot.RECORD)
        if not qid or not os.path.isfile(record):
            continue
        with open(record, encoding="utf-8") as f:
            rec = json.load(f)
        if rec.get("mode") == "post" and any(p.get("status") != "deleted" for p in rec.get("posts", [])):
            done.add(qid)
    return done


def pick(entries, booked, now, only=None):
    if only:
        chosen = [e for e in entries if e["id"] == only]
        if not chosen:
            raise QueueProblem(f"There is no queued post with id {only}.")
        return chosen
    return [e for e in entries
            if e.get("status", "approved") == "approved" and e["id"] not in booked
            and now + MIN_LEAD < due_time(e) <= now + LOOK_AHEAD]


def order_env(entry, base_env, run_id, n, mode):
    env = dict(base_env)
    env.update({
        "ORDER_BRIEF": entry.get("brief") or entry["caption"].replace("\\n", "\n").splitlines()[0],
        "ORDER_TYPE": entry.get("type", "picture"),
        "ORDER_REFERENCE": "",
        "ORDER_WHEN": f"{entry['date']} {entry['time']}",
        "ORDER_MODE": mode,
        "ORDER_PICTURE": entry["picture"],
        "ORDER_PICTURE_AI": entry.get("picture_ai", "yes"),
        "ORDER_CAPTION": entry["caption"],
        "ORDER_HASHTAGS": entry.get("hashtags", ""),
        "ORDER_QUEUE_ID": entry["id"],
        "ORDER_BOARD": entry.get("board", ""),   # Pinterest board; guessed from the words when blank
        "GITHUB_RUN_ID": f"{run_id}q{n}",       # each queued post gets its own orders/ folder
    })
    return env


def main(env=None, clock=now_utc, run=robot.run_order):
    env = os.environ if env is None else env
    mode = (env.get("QUEUE_MODE") or "post").strip().lower()
    only = (env.get("QUEUE_ONLY") or "").strip()
    if mode not in ("post", "draft"):
        raise QueueProblem(f"mode must be post or draft, not '{mode}'.")
    git("fetch", "--depth=1", "origin", robot.MEDIA_BRANCH)
    git("worktree", "add", "--detach", QUEUE_DIR, "FETCH_HEAD")
    entries = load_queue(QUEUE_DIR)
    chosen = pick(entries, booked_ids(QUEUE_DIR), clock(), only)
    if not chosen:
        say("Nothing to book: every approved post due in the next 36 hours is already in Buffer.")
        write_summary("### Pet Shelf queue\nNothing new to book.")
        return 0
    lines, failed = [], []
    run_id = env.get("GITHUB_RUN_ID") or "local"
    for n, entry in enumerate(chosen, 1):
        label = f"{entry['date']} {entry['time']} {entry['id']}"
        try:
            run(order_env(entry, env, run_id, n, mode))
            lines.append(f"booked: {label}")
        except (robot.OrderProblem, BufferError) as problem:
            failed.append(f"FAILED: {label}: {problem}")
        finally:
            shutil.rmtree(robot.MEDIA_DIR, ignore_errors=True)
            subprocess.run(["git", "worktree", "prune"], capture_output=True)
        say((lines + failed)[-1])
    write_summary("### Pet Shelf queue\n" + "\n".join(f"- {line}" for line in lines + failed))
    if failed:
        raise QueueProblem("\n".join(failed))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except (QueueProblem, robot.OrderProblem, BufferError) as problem:
        robot.fail_message(str(problem))
        code = 1
    finally:
        shutil.rmtree(QUEUE_DIR, ignore_errors=True)
    sys.exit(code)
