import json
import os
import tempfile
import unittest

import pet_shelf_cancel as cancel_tool
import pet_shelf_order as robot

CHANNELS = [{"id": "fb1", "service": "facebook", "name": "Solvix Pet Shelf", "paused": False},
            {"id": "ig1", "service": "instagram", "name": "solvixpetshelf", "paused": False},
            {"id": "tt1", "service": "tiktok", "name": "solvixpetshelf", "paused": False}]
FOLDER = "2026-11-07-dog-paw-cleaner-cup-a-42333996838"


class FakeBuffer:
    def __init__(self, statuses, channels=CHANNELS):
        self.statuses, self._channels, self.deleted = statuses, channels, []

    def channels(self):
        return self._channels

    def ask(self, query, variables=None, changes_something=False):
        if "deletePost" in query:
            self.deleted.append(variables["input"]["id"])
            return {"deletePost": {"__typename": "DeletePostSuccess"}}
        post_id = query.split('id: "')[1].split('"')[0]
        return {"post": {"__typename": "Post", "status": self.statuses[post_id]}}


def write_record(base, posts):
    path = os.path.join(base, "orders", FOLDER)
    os.makedirs(path)
    with open(os.path.join(path, robot.RECORD), "w") as f:
        json.dump({"mode": "post", "posts": posts}, f)
    return os.path.join(path, robot.RECORD)


POSTS = [{"service": "instagram", "channel_id": "ig1", "post_id": "p1", "status": "scheduled"},
         {"service": "facebook", "channel_id": "fb1", "post_id": "p2", "status": "scheduled"},
         {"service": "tiktok", "channel_id": "tt1", "post_id": "p3", "status": "scheduled"}]


class Cancel(unittest.TestCase):
    def test_cancels_scheduled_posts_and_marks_the_record(self):
        with tempfile.TemporaryDirectory() as base:
            path = write_record(base, [dict(p) for p in POSTS])
            buffer = FakeBuffer({"p1": "scheduled", "p2": "scheduled", "p3": "sent"})
            done = cancel_tool.cancel(FOLDER, buffer, base)
            self.assertEqual(buffer.deleted, ["p1", "p2"])          # the sent one is never touched
            self.assertIn("NOT cancelled", done[2])
            saved = json.load(open(path))["posts"]
            self.assertEqual([p["status"] for p in saved], ["deleted", "deleted", "scheduled"])
            # running again does nothing new for the cancelled ones
            buffer2 = FakeBuffer({"p3": "sent"})
            cancel_tool.cancel(FOLDER, buffer2, base)
            self.assertEqual(buffer2.deleted, [])

    def test_stops_on_a_solvix_key_or_a_strange_channel(self):
        with tempfile.TemporaryDirectory() as base:
            write_record(base, [dict(p) for p in POSTS])
            solvix = CHANNELS + [{"id": next(iter(robot.SOLVIX_CHANNEL_IDS)), "service": "facebook",
                                  "name": "Solvix", "paused": False}]
            buffer = FakeBuffer({"p1": "scheduled"}, channels=solvix)
            with self.assertRaises(robot.OrderProblem):
                cancel_tool.cancel(FOLDER, buffer, base)
            self.assertEqual(buffer.deleted, [])
        with tempfile.TemporaryDirectory() as base:
            write_record(base, [dict(POSTS[0], channel_id="someone-else")])
            buffer = FakeBuffer({"p1": "scheduled"})
            with self.assertRaises(robot.OrderProblem):
                cancel_tool.cancel(FOLDER, buffer, base)
            self.assertEqual(buffer.deleted, [])

    def test_a_post_already_gone_counts_as_cancelled(self):
        class Gone(FakeBuffer):
            def ask(self, query, variables=None, changes_something=False):
                if "deletePost" not in query and 'id: "p1"' in query:
                    raise cancel_tool.BufferError("Buffer refused the request: Post not found for id: p1")
                return super().ask(query, variables, changes_something)
        with tempfile.TemporaryDirectory() as base:
            path = write_record(base, [dict(p) for p in POSTS])
            buffer = Gone({"p2": "scheduled", "p3": "scheduled"})
            done = cancel_tool.cancel(FOLDER, buffer, base)
            self.assertEqual(buffer.deleted, ["p2", "p3"])
            self.assertIn("already gone", done[0])
            self.assertEqual([p["status"] for p in json.load(open(path))["posts"]], ["deleted"] * 3)

    def test_folder_name_is_checked(self):
        for bad in ("", "../x", "orders/2026-11-07-a-1", "2026-11-07-a"):
            with self.assertRaises(robot.OrderProblem):
                cancel_tool.cancel(bad, FakeBuffer({}), "/nonexistent")


if __name__ == "__main__":
    unittest.main()
