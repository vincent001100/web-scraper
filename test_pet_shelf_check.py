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
