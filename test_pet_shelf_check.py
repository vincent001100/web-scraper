import json
import os
import tempfile
import unittest

import pet_shelf_check as check


class Collect(unittest.TestCase):
    def test_only_real_posts_that_were_not_cancelled(self):
        with tempfile.TemporaryDirectory() as base:
            for name, mode, statuses in (("a-1", "post", ["scheduled", "deleted"]), ("b-2", "draft", ["draft"])):
                os.makedirs(os.path.join(base, "orders", name))
                posts = [{"service": "tiktok", "post_id": f"{name}{i}", "status": s} for i, s in enumerate(statuses)]
                with open(os.path.join(base, "orders", name, "buffer-posts.json"), "w") as f:
                    json.dump({"mode": mode, "posts": posts}, f)
            rows = check.collect(base)
            self.assertEqual([(folder, item["post_id"]) for folder, item in rows], [("a-1", "a-10")])



class Accounts(unittest.TestCase):
    def test_pins_are_read_from_the_pinterest_account(self):
        import pet_shelf_check as check
        self.assertEqual(check.account_for({"service": "pinterest"}, "main", "pins"), "pins")
        self.assertEqual(check.account_for({"service": "instagram"}, "main", "pins"), "main")
        self.assertEqual(check.account_for({"service": "pinterest"}, "main", None), "main")


if __name__ == "__main__":
    unittest.main()


class Recent(unittest.TestCase):
    def test_only_recent_order_folders_are_checked(self):
        import json, os, tempfile
        import pet_shelf_check as check
        with tempfile.TemporaryDirectory() as base:
            for name in ("2026-11-10-old-1", "2026-11-22-new-2"):
                os.makedirs(os.path.join(base, "orders", name))
                json.dump({"mode": "post", "posts": [{"service": "instagram", "post_id": name}]},
                          open(os.path.join(base, "orders", name, check.robot.RECORD), "w"))
            self.assertEqual([f for f, _ in check.collect(base, "2026-11-20")], ["2026-11-22-new-2"])
            self.assertEqual(len(check.collect(base)), 2)



def test_metrics_report_sorts_best_first(tmp_path, monkeypatch):
    import pet_shelf_check as check
    monkeypatch.chdir(tmp_path)
    numbers = {"a": {"Likes": 2, "Reach": 900}, "b": {"Likes": 9, "Reach": 10}}
    class FakeBuffer:
        def post_metrics(self, post_id):
            return {"status": "sent", "link": None, "updated": None, "metrics": numbers[post_id]}
    monkeypatch.setattr(check, "write_summary", lambda text: None)
    rows = [("2026-11-20-a", {"service": "instagram", "post_id": "a"}),
            ("2026-11-21-b", {"service": "instagram", "post_id": "b"})]
    check.metrics_report(rows, FakeBuffer(), None)
    lines = (tmp_path / "results.csv").read_text().splitlines()
    assert lines[1].startswith("2026-11-21-b")
