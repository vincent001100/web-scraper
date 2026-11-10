"""
Pet Shelf check (read-only): what did Buffer really do with every Pet Shelf post we booked?
For each real order on the pet-shelf-media branch it asks Buffer for each channel's status
(sent, scheduled, error...) and Buffer's error message, and writes a table to the run summary.
Changes nothing: no posts are created, edited or deleted, and nothing is pushed.
From the phone: Actions, Pet Shelf check, Run workflow.
"""
import json
import os
import sys

from buffer_post import Buffer, BufferError, LABEL, say, write_summary
import pet_shelf_order as robot


def collect(base):
    rows = []
    orders = os.path.join(base, "orders")
    for folder in sorted(os.listdir(orders)) if os.path.isdir(orders) else []:
        path = os.path.join(orders, folder, robot.RECORD)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
        if record.get("mode") != "post":
            continue
        for item in record.get("posts", []):
            if item.get("status") != "deleted":
                rows.append((folder, item))
    return rows


def main():
    try:
        buffer = Buffer(os.environ.get("PET_SHELF_BUFFER_API_KEY"))
        robot.open_media_branch()
        lines = ["| Order | App | Due (UTC) | Buffer status | Problem |", "|---|---|---|---|---|"]
        counts = {}
        for folder, item in collect(robot.MEDIA_DIR):
            try:
                info = buffer.post_status(item["post_id"])
                status, problem = info.get("status", "?"), info.get("problem") or ""
            except BufferError as error:
                status, problem = "unknown", str(error)
            label = LABEL.get(item["service"], item["service"])
            counts.setdefault(label, {}).setdefault(status, 0)
            counts[label][status] += 1
            lines.append(f"| {folder[:48]} | {label} | {(item.get('due_at') or '')[:16]} | {status} | {problem[:200]} |")
            say(f"{label:<9} {status:<10} {folder}  {problem}")
        summary = "\n".join(f"- {app}: " + ", ".join(f"{n} {s}" for s, n in sorted(c.items())) for app, c in counts.items())
        write_summary("### Pet Shelf check\n" + summary + "\n\n" + "\n".join(lines))
        say("TOTALS\n" + summary)
        return 0
    except (robot.OrderProblem, BufferError) as problem:
        robot.fail_message(str(problem))
        return 1


if __name__ == "__main__":
    sys.exit(main())
