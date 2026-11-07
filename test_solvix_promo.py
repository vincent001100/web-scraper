import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

import solvix_promo as promo


def make_base(tmp, dates):
    os.makedirs(os.path.join(tmp, "promo", "2026-11"))
    posts = [{"date": d, "title": f"post {i}", "image": f"p{i}.jpg", "caption": "Hello #solvix"} for i, d in enumerate(dates)]
    with open(os.path.join(tmp, "promo", "2026-11", "schedule.json"), "w") as f:
        json.dump({"posts": posts}, f)
    return promo.load_schedule(tmp)


class Picking(unittest.TestCase):
    def test_next_books_only_unbooked_posts_in_the_next_36_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = make_base(tmp, ["2026-11-08", "2026-11-09", "2026-11-10"])
            evening = datetime(2026, 11, 7, 17, 30, tzinfo=timezone.utc)
            self.assertEqual([e["date"] for e in promo.pick_entries(entries, tmp, evening)], ["2026-11-08"])
            morning = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)     # late timer: 8th still ahead, 9th too
            self.assertEqual([e["date"] for e in promo.pick_entries(entries, tmp, morning)], ["2026-11-08", "2026-11-09"])
            folder = promo.record_folder(tmp, entries[0])
            os.makedirs(folder)
            with open(os.path.join(folder, "buffer-posts.json"), "w") as f:
                json.dump({"posts": [{"service": "facebook", "post_id": "x"}]}, f)
            self.assertEqual([e["date"] for e in promo.pick_entries(entries, tmp, morning)], ["2026-11-09"])
            too_late = datetime(2026, 11, 8, 11, 55, tzinfo=timezone.utc)
            self.assertNotIn("2026-11-08", [e["date"] for e in promo.pick_entries(entries, tmp, too_late)])

    def test_exact_day_and_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = make_base(tmp, ["2026-11-08", "2026-11-09"])
            now = datetime(2026, 11, 7, 8, 0, tzinfo=timezone.utc)
            self.assertEqual(promo.pick_entries(entries, tmp, now, "2026-11-09")[0]["title"], "post 1")
            with self.assertRaises(promo.PromoProblem):
                promo.pick_entries(entries, tmp, now, "2026-12-01")
            with self.assertRaises(promo.PromoProblem):
                promo.pick_entries(entries, tmp, datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc), "2026-11-09")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(promo.PromoProblem):
                make_base(tmp, ["2026-11-08", "2026-11-08"])

    def test_image_address_is_on_the_public_media_branch(self):
        entry = {"set": "2026-11", "image": "p1.jpg"}
        self.assertEqual(promo.image_url({}, entry),
                         "https://raw.githubusercontent.com/vincent001100/web-scraper/solvix-media/promo/2026-11/p1.jpg")


if __name__ == "__main__":
    unittest.main()
