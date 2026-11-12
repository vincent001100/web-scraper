"""
Cancel a Pet Shelf order that is booked in Buffer but not yet published (boss, 7 Nov 2026).

From the phone: Actions, Pet Shelf cancel, Run workflow, paste the order folder name
(for example 2026-11-07-dog-paw-cleaner-cup-a-42333996838, from orders/ on the pet-shelf-media branch).

SAFETY
  * Only PET_SHELF_BUFFER_API_KEY. If the key can see a Solvix channel, nothing is deleted.
  * Only the posts this order saved in its buffer-posts.json, and only on the Pet Shelf channels.
  * A post Buffer has already published ("sent") is never touched: delete it in the app if needed.
  * The record is updated, so a later re-run of the old order cannot post it again.
"""
import json
import os
import re
import sys

from buffer_post import Buffer, BufferError, say, write_summary
import pet_shelf_order as robot

FOLDER = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+-\d+(?:q\d+)?$")
CANCELLABLE = {"scheduled", "draft"}      # "sending" and "sent" are already on their way out


def cancel(folder, buffer, base, env=None, make_buffer=None):
    if not FOLDER.match(folder or ""):
        raise robot.OrderProblem("Give the order folder name, like 2026-11-07-dog-paw-cleaner-cup-a-42333996838.")
    path = os.path.join(base, "orders", folder, robot.RECORD)
    if not os.path.isfile(path):
        raise robot.OrderProblem(f"There is no Buffer record for {folder}, so there is nothing to cancel.")
    with open(path, encoding="utf-8") as f:
        record = json.load(f)

    targets = robot.pick_channels(buffer.channels())                               # stops on a Solvix key
    pin_buffer = robot.connect_pinterest(env or {}, targets, make_buffer)          # pins: the Pinterest Buffer account
    allowed = {c["id"] for c in targets.values()}

    def account(item):
        return pin_buffer if item.get("service") == robot.PINTEREST and pin_buffer is not None else buffer
    done = []
    for item in record.get("posts", []):
        label = item.get("service", "?")
        if item.get("status") == "deleted":
            done.append(f"{label}: already cancelled")
            continue
        if item.get("channel_id") not in allowed:
            raise robot.OrderProblem(f"The {label} post is not on a Pet Shelf channel, so I stopped.")
        try:
            status = robot.read_post(account(item), item["post_id"])["status"].lower()
        except BufferError as problem:
            if "not found" in str(problem).lower():       # already gone (e.g. an earlier try deleted it)
                item["status"] = "deleted"
                done.append(f"{label}: already gone from Buffer")
                continue
            raise
        if status not in CANCELLABLE:
            done.append(f"{label}: NOT cancelled, Buffer says '{status}' (already out or failed)")
            continue
        robot.delete_post(account(item), item["post_id"])
        item["status"] = "deleted"
        done.append(f"{label}: cancelled")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    return done


def main():
    folder = (os.environ.get("CANCEL_FOLDER") or "").strip()
    try:
        buffer = Buffer(os.environ.get("PET_SHELF_BUFFER_API_KEY"))
        robot.open_media_branch()
        try:
            done = cancel(folder, buffer, robot.MEDIA_DIR, os.environ)
        finally:
            robot.save_media(f"Cancelled Buffer posts for {folder}")
        text = "\n".join(f"- {line}" for line in done)
        say(f"Pet Shelf cancel for {folder}:\n{text}")
        write_summary(f"### Pet Shelf cancel: {folder}\n{text}")
        return 1 if any("NOT cancelled" in line for line in done) else 0
    except (robot.OrderProblem, BufferError) as problem:
        robot.fail_message(str(problem))
        return 1


if __name__ == "__main__":
    sys.exit(main())
