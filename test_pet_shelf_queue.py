import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

import pet_shelf_queue as q


def entry(i, date, time, **extra):
    return dict({"id": f"p{i}", "date": date, "time": time, "picture": "ready/a.jpg", "caption": "Line one\\nLine two"}, **extra)


class Queue(unittest.TestCase):
    def test_lagos_time_and_36_hour_window(self):
        self.assertEqual(q.due_time(entry(1, "2026-11-12", "09:00")), datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc))
        es = [entry(1, "2026-11-12", "09:00"), entry(2, "2026-11-12", "19:30"), entry(3, "2026-11-14", "09:00"),
              entry(4, "2026-11-12", "12:30", status="hold")]
        evening = datetime(2026, 11, 11, 17, 13, tzinfo=timezone.utc)
        self.assertEqual([e["id"] for e in q.pick(es, set(), evening)], ["p1", "p2"])
        self.assertEqual([e["id"] for e in q.pick(es, {"p1"}, evening)], ["p2"])
        too_close = datetime(2026, 11, 12, 7, 40, tzinfo=timezone.utc)      # 09:00 Lagos is 20 min away
        self.assertNotIn("p1", [e["id"] for e in q.pick(es, set(), too_close)])
        self.assertEqual([e["id"] for e in q.pick(es, set(), evening, only="p3")], ["p3"])
        with self.assertRaises(q.QueueProblem):
            q.pick(es, set(), evening, only="nope")

    def test_booked_means_a_live_buffer_record_with_the_queue_id(self):
        with tempfile.TemporaryDirectory() as base:
            for name, qid, statuses, mode in (("a-1", "p1", ["scheduled"], "post"), ("b-2", "p2", ["deleted"], "post"),
                                              ("c-3", "p3", ["draft"], "draft"), ("d-4", "", ["scheduled"], "post")):
                os.makedirs(os.path.join(base, "orders", name))
                json.dump({"queue_id": qid}, open(os.path.join(base, "orders", name, "order.json"), "w"))
                json.dump({"mode": mode, "posts": [{"status": s} for s in statuses]},
                          open(os.path.join(base, "orders", name, "buffer-posts.json"), "w"))
            self.assertEqual(q.booked_ids(base), {"p1"})

    def test_queue_file_and_order_settings(self):
        with tempfile.TemporaryDirectory() as base:
            os.makedirs(os.path.join(base, "queue"))
            json.dump({"posts": [entry(1, "2026-11-12", "09:00"), entry(2, "2026-11-12", "08:00")]},
                      open(os.path.join(base, "queue", "w46.json"), "w"))
            self.assertEqual([e["id"] for e in q.load_queue(base)], ["p2", "p1"])
            json.dump({"posts": [entry(1, "2026-11-13", "09:00")]}, open(os.path.join(base, "queue", "w47.json"), "w"))
            with self.assertRaises(q.QueueProblem):
                q.load_queue(base)
        env = q.order_env(entry(7, "2026-11-12", "16:00", hashtags="cats"), {"KEEP": "1"}, "99", 2, "post")
        self.assertEqual((env["ORDER_WHEN"], env["ORDER_QUEUE_ID"], env["GITHUB_RUN_ID"], env["ORDER_BRIEF"], env["KEEP"]),
                         ("2026-11-12 16:00", "p7", "99q2", "Line one", "1"))
        import pet_shelf_order as robot
        order = robot.read_order(env)
        self.assertEqual((order["queue_id"], order["picture"], order["mode"]), ("p7", "ready/a.jpg", "post"))


if __name__ == "__main__":
    unittest.main()
