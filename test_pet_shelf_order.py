"""Tests for the Pet Shelf order robot. Run: python -m unittest test_pet_shelf_order
No internet and no keys: Buffer, Gemini and Cloudflare are all pretend versions here."""
import base64
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from PIL import Image

import pet_shelf_order as robot
from buffer_post import BufferError, Plan, plan_now

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
CHANNELS = [
    {"id": "tt", "name": "solvixpetshelf", "service": "tiktok", "paused": False},
    {"id": "ig", "name": "solvixpetshelf", "service": "instagram", "paused": False},
    {"id": "fb", "name": "Solvix Pet Shelf", "service": "facebook", "paused": False},
]
TARGETS = robot.pick_channels(CHANNELS)
URLS = {"picture": "https://example.com/post.jpg"}
GOOD = {"hook": "Slow down, speedy eater", "caption": "Some dogs eat like it is a race. Ridges make dinner last.",
        "hashtags": ["dogs", "#Amazon", "ad", "petcare"], "picture_prompt": "A dog bowl."}


class FakeBuffer:
    """A pretend Buffer that stores posts and can refuse a channel."""

    def __init__(self, refuse=(), status=None):
        self.created, self.deleted, self.refuse, self.status = [], [], set(refuse), status

    def sleep(self, _):
        pass

    def create_post(self, post):
        if post["channelId"] in self.refuse:
            raise BufferError("the channel said no")
        self.created.append(post)
        return {"id": f"p{len(self.created)}"}

    def ask(self, query, variables=None, changes_something=False):
        if "deletePost" in query:
            self.deleted.append(variables["input"]["id"])
            return {"deletePost": {"__typename": "DeletePostSuccess"}}
        post = self.created[int(query.split('"p')[1].split('"')[0]) - 1]
        return {"post": {"status": self.status or ("draft" if post.get("saveToDraft") else "scheduled"),
                         "text": post["text"], "channelId": post["channelId"], "dueAt": post.get("dueAt"),
                         "assets": [{"type": "image", "source": "x"}]}}

    def post_status(self, post_id):
        return {"status": self.status or "scheduled", "due_at": None, "sent_at": None, "link": None, "problem": None}


def send(buffer, draft=True, plan=None, earlier=(), urls=URLS):
    plan = plan or plan_now(NOW)
    return robot.send_to_buffer(buffer, TARGETS, "#ad hello", urls, "Hook", True, plan, draft,
                                list(earlier), lambda posts: None, lambda: NOW)


class OrderInput(unittest.TestCase):
    def test_a_blank_mode_never_becomes_a_real_post(self):
        with self.assertRaises(robot.OrderProblem):
            robot.read_order({"ORDER_BRIEF": "x", "ORDER_MODE": ""})

    def test_needs_a_brief_and_a_known_type(self):
        for env in ({"ORDER_MODE": "draft"}, {"ORDER_BRIEF": "x", "ORDER_MODE": "draft", "ORDER_TYPE": "gif"}):
            with self.assertRaises(robot.OrderProblem):
                robot.read_order(env)


class Timing(unittest.TestCase):
    def test_default_is_the_next_1930_lagos(self):
        self.assertEqual(robot.plan_time("", NOW).due_at, datetime(2026, 11, 4, 18, 30, tzinfo=timezone.utc))

    def test_default_moves_to_tomorrow_when_too_close(self):
        late = NOW.replace(hour=18, minute=10)
        self.assertEqual(robot.plan_time("next", late).due_at.day, 5)

    def test_a_written_time_is_lagos_time(self):
        self.assertEqual(robot.plan_time("2026-11-06 19:30", NOW).due_at.hour, 18)

    def test_now_and_bad_times(self):
        self.assertEqual(robot.plan_time("now", NOW).mode, "shareNow")
        for text in ("tomorrow", "2026-11-01 19:30"):
            with self.assertRaises(robot.OrderProblem):
                robot.plan_time(text, NOW)


class Rules(unittest.TestCase):
    def check(self, caption, hint=""):
        return robot.rule_problems({"hook": "A hook", "caption": caption, "picture_prompt": "A bowl."}, hint)

    def test_clean_words_pass(self):
        self.assertEqual(self.check(GOOD["caption"]), [])

    def test_prices_are_refused(self):
        for text in ("Only $12 today", "Just 20 dollars", "A great price", "20% off now", "It costs little"):
            self.assertTrue(self.check(text), text)

    def test_reviews_are_refused(self):
        for text in ("Five-star bowl", "Customers love it", "My dog loves it", "Read the reviews", "4.8 stars",
                     "I bought one", "We tested it"):
            self.assertTrue(self.check(text), text)

    def test_links_and_hashtags_are_refused(self):
        for text in ("See https://a.example/x", "Go to petstore.com", "So #cute"):
            self.assertTrue(self.check(text), text)

    def test_copied_words_are_refused(self):
        hint = "The very best way to stop your dog gulping food down fast"
        self.assertTrue(self.check("Try the very best way to stop your dog gulping tonight.", hint))
        self.assertEqual(self.check("Dinner should not be a race.", hint), [])

    def test_a_refused_answer_is_asked_again_then_gives_up(self):
        bad = dict(GOOD, caption="Only $5!")
        answers = iter([bad, GOOD])
        self.assertEqual(robot.write_post({"brief": "x"}, "", "k", lambda p, k: next(answers))["caption"], GOOD["caption"])
        with self.assertRaises(robot.OrderProblem):
            robot.write_post({"brief": "x"}, "", "k", lambda p, k: bad)

    def test_caption_starts_with_ad_and_has_no_earnings_or_ai_lines(self):
        ai, card = robot.compose_caption(GOOD, True), robot.compose_caption(GOOD, False)
        self.assertTrue(ai.startswith("#ad "))
        for text in (ai, card):     # boss, 7 Nov 2026: no earnings or Amazon lines in captions
            self.assertNotIn("earn", text.lower())
            self.assertNotIn("commission", text.lower())
            self.assertNotIn("amazon", text.lower())
        self.assertNotIn("made with AI", ai)      # boss, 7 Nov 2026: no visible AI line
        self.assertNotIn("made with AI", card)
        self.assertIn("#dogs #petcare", ai)
        self.assertNotIn("#Amazon", ai.lower().replace("amazon associate", ""))


class ReadyPictures(unittest.TestCase):
    """Boss, 7 Nov 2026: the team can hand the robot a finished advert instead of an AI drawing."""

    def test_only_files_in_ready_are_accepted(self):
        base = {"ORDER_BRIEF": "x", "ORDER_MODE": "draft"}
        self.assertEqual(robot.read_order(dict(base, ORDER_PICTURE="ready/ad-1.jpg"))["picture"], "ready/ad-1.jpg")
        for bad in ("../secret.jpg", "ready/../x.jpg", "orders/x.jpg", "https://example.com/a.jpg", "ready/a.gif"):
            with self.assertRaises(robot.OrderProblem):
                robot.read_order(dict(base, ORDER_PICTURE=bad))
        with self.assertRaises(robot.OrderProblem):
            robot.read_order(dict(base, ORDER_PICTURE="ready/a.jpg", ORDER_PICTURE_AI="maybe"))

    def test_ready_picture_is_opened_and_sized(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "ready"))
            Image.new("RGBA", (2160, 2700), "white").save(os.path.join(tmp, "ready", "ad.png"))
            picture = robot.load_ready_picture("ready/ad.png", base=tmp)
            self.assertEqual((picture.mode, picture.size), ("RGB", (1080, 1350)))
            Image.new("RGB", (1600, 400)).save(os.path.join(tmp, "ready", "wide.jpg"))
            with self.assertRaises(robot.OrderProblem):
                robot.load_ready_picture("ready/wide.jpg", base=tmp)
            with self.assertRaises(robot.OrderProblem):
                robot.load_ready_picture("ready/missing.jpg", base=tmp)


class TeamCaptions(unittest.TestCase):
    """Boss, 7 Nov 2026: 'link in bio' in the caption, and easy words (the team may write them)."""

    def test_team_caption_is_used_with_link_in_bio(self):
        from PIL import Image
        env = {"ORDER_BRIEF": "x", "ORDER_MODE": "draft", "ORDER_PICTURE": "ready/a.png",
               "ORDER_CAPTION": "Muddy paws in the car?\\nYour seats stay clean.", "ORDER_HASHTAGS": "dogs, roadtrip"}
        with tempfile.TemporaryDirectory() as media, tempfile.TemporaryDirectory() as out, \
                mock.patch.object(robot, "MEDIA_DIR", media), \
                mock.patch.object(robot, "write_post", side_effect=AssertionError("Gemini not needed")):
            os.makedirs(os.path.join(media, "ready"))
            Image.new("RGB", (1080, 1350)).save(os.path.join(media, "ready", "a.png"))
            details = robot.make_content(robot.read_order(env), {}, out)
        self.assertEqual(details["caption"],
                         "#ad Muddy paws in the car?\nYour seats stay clean.\n\n👉 Link in bio\n\n#dogs #roadtrip")

    def test_order_details_never_overwrite_the_final_caption(self):
        # 7 Nov 2026: details.update(order) once replaced the caption with the bare team words (no #ad).
        order = robot.read_order({"ORDER_BRIEF": "x", "ORDER_MODE": "draft", "ORDER_PICTURE": "ready/a.png",
                                  "ORDER_CAPTION": "Hello there."})
        details = {"caption": "#ad Hello there.\n\n👉 Link in bio"}
        details.update(order)
        self.assertTrue(details["caption"].startswith("#ad "))

    def test_team_caption_follows_the_rules(self):
        env = {"ORDER_BRIEF": "x", "ORDER_MODE": "draft", "ORDER_PICTURE": "ready/a.png",
               "ORDER_CAPTION": "Only $5 today! Visit https://example.com"}
        with tempfile.TemporaryDirectory() as out, self.assertRaises(robot.OrderProblem):
            robot.make_content(robot.read_order(env), {}, out)


class TikTokGetsVideo(unittest.TestCase):
    """7-9 Nov 2026: TikTok refused every single-picture post, but took videos and slides."""

    def test_tiktok_gets_the_video_while_facebook_and_instagram_keep_the_picture(self):
        plan = robot.Plan("customScheduled", datetime(2030, 1, 1, tzinfo=timezone.utc), None)
        urls = {"picture": "https://x/post.jpg", "tiktok_video": "https://x/tiktok.mp4"}
        tiktok = robot.build_post("tiktok", "tt1", "#ad hi", urls, "hook", True, plan, False)
        self.assertEqual(tiktok["assets"][0]["video"]["url"], "https://x/tiktok.mp4")
        for service in ("facebook", "instagram"):
            post = robot.build_post(service, "c1", "#ad hi", urls, "hook", True, plan, False)
            self.assertEqual(post["assets"], [{"image": {"url": "https://x/post.jpg"}}])


class TeamAdvertsOnly(unittest.TestCase):
    def test_a_post_without_a_team_advert_is_refused(self):
        with self.assertRaises(robot.OrderProblem):
            robot.read_order({"ORDER_BRIEF": "x", "ORDER_MODE": "post"})
        self.assertEqual(robot.read_order({"ORDER_BRIEF": "x", "ORDER_MODE": "post", "ORDER_ALLOW_DRAWING": "yes"})["picture"], "")


class SlidesAndSound(unittest.TestCase):
    """Boss, 7 Nov 2026: post slides, and add sound (our slideshow video with our own music)."""
    base = {"ORDER_BRIEF": "x", "ORDER_MODE": "draft"}

    def test_reading_slides_and_video_orders(self):
        o = robot.read_order(dict(self.base, ORDER_PICTURE="ready/a/s1.png, ready/a/s2.png,ready/a/s3.png"))
        self.assertEqual((o["ready_pictures"], o["ready_video"], o["type"]),
                         (["ready/a/s1.png", "ready/a/s2.png", "ready/a/s3.png"], "", "picture"))
        o = robot.read_order(dict(self.base, ORDER_PICTURE="ready/a/v.mp4,ready/a/s1.png"))
        self.assertEqual((o["ready_video"], o["type"]), ("ready/a/v.mp4", "video"))
        for bad in ("ready/a/v.mp4", "ready/a/v.mp4,ready/b/w.mp4,ready/c.png", "ready/a/../../x.png",
                    ",".join(f"ready/s{i}.png" for i in range(11))):
            with self.assertRaises(robot.OrderProblem):
                robot.read_order(dict(self.base, ORDER_PICTURE=bad))

    def test_only_limits_an_order_to_the_apps_named(self):
        base = dict(self.base, ORDER_PICTURE="ready/a.jpg")
        self.assertEqual(robot.read_order(base)["only"], [])
        self.assertEqual(robot.read_order(dict(base, ORDER_ONLY="Instagram, pinterest"))["only"],
                         ["instagram", "pinterest"])
        with self.assertRaises(robot.OrderProblem):
            robot.read_order(dict(base, ORDER_ONLY="twitter"))
        self.assertEqual(set(robot.limit_targets(dict(TARGETS), [])), {"instagram", "facebook", "tiktok"})
        self.assertEqual(set(robot.limit_targets(dict(TARGETS), ["instagram"])), {"instagram"})
        with self.assertRaises(robot.OrderProblem):
            robot.limit_targets(dict(TARGETS), ["pinterest"])          # not connected here

    def test_an_instagram_only_resend_never_touches_the_other_apps(self):
        buffer = FakeBuffer()
        posts = robot.send_to_buffer(buffer, robot.limit_targets(dict(TARGETS), ["instagram"]), "#ad hello", URLS,
                                     "Hook", True, plan_now(NOW), True, [], lambda p: None, lambda: NOW)
        self.assertEqual([p["service"] for p in posts], ["instagram"])
        self.assertEqual([p["channelId"] for p in buffer.created], ["ig"])

    def test_slides_become_one_picture_per_item(self):
        plan = robot.Plan("customScheduled", datetime(2030, 1, 1, tzinfo=timezone.utc), None)
        urls = {"picture": "https://x/1.jpg", "slides": ["https://x/1.jpg", "https://x/2.jpg"]}
        post = robot.build_post("instagram", "ig1", "#ad hi", urls, "hook", True, plan, False)
        self.assertEqual(post["assets"], [{"image": {"url": "https://x/1.jpg"}}, {"image": {"url": "https://x/2.jpg"}}])

    def test_ready_video_and_slides_are_saved(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as media, tempfile.TemporaryDirectory() as out, \
                mock.patch.object(robot, "MEDIA_DIR", media), \
                mock.patch.object(robot, "write_post", return_value=dict(GOOD)), \
                mock.patch.object(robot, "draw_cloudflare_picture", side_effect=AssertionError("no drawing")):
            os.makedirs(os.path.join(media, "ready", "a"))
            for n in (1, 2):
                Image.new("RGB", (1080, 1350), "white").save(os.path.join(media, "ready", "a", f"s{n}.png"))
            with open(os.path.join(media, "ready", "a", "v.mp4"), "wb") as f:
                f.write(b"fake video")
            slides = robot.read_order(dict(self.base, ORDER_PICTURE="ready/a/s1.png,ready/a/s2.png"))
            details = robot.make_content(slides, {}, os.path.join(out, "one"))
            self.assertEqual(details["slides"], 2)
            self.assertTrue(os.path.exists(os.path.join(out, "one", "slide-2.jpg")))
            video = robot.read_order(dict(self.base, ORDER_PICTURE="ready/a/v.mp4,ready/a/s1.png"))
            details = robot.make_content(video, {}, os.path.join(out, "two"))
            with open(os.path.join(out, "two", "video.mp4"), "rb") as f:
                self.assertEqual(f.read(), b"fake video")
            self.assertNotIn("made with AI", details["caption"])


class Reply:
    def __init__(self, status, payload=None, content=b"", kind="application/json"):
        self.status_code, self.payload, self.content = status, payload, content
        self.headers = {"Content-Type": kind}

    def json(self):
        if self.payload is None:
            raise ValueError
        return self.payload


class Gemini(unittest.TestCase):
    def test_busy_models_are_retried_then_it_works(self):
        good = Reply(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(GOOD)}]}}]})
        replies = iter([Reply(503, {})] * len(robot.GEMINI_MODELS) + [Reply(429, {}), good])
        waits = []
        answer = robot.ask_gemini("p", "key", post=lambda *a, **k: next(replies), sleep=waits.append)
        self.assertEqual(answer["hook"], GOOD["hook"])
        self.assertEqual(waits, [10])

    def test_always_busy_is_a_loud_failure(self):
        with self.assertRaises(robot.OrderProblem):
            robot.ask_gemini("p", "key", post=lambda *a, **k: Reply(503, {}), sleep=lambda s: None)

    def test_the_key_goes_in_a_header_not_the_address(self):
        seen = {}

        def post(url, **kwargs):
            seen.update(url=url, headers=kwargs["headers"])
            return Reply(401, {})
        with self.assertRaises(robot.OrderProblem) as caught:
            robot.ask_gemini("p", "secret-key", post=post)
        self.assertNotIn("secret-key", seen["url"] + str(caught.exception))
        self.assertEqual(seen["headers"]["x-goog-api-key"], "secret-key")


class Pictures(unittest.TestCase):
    def jpeg(self):
        data = io.BytesIO()
        Image.new("RGB", (1024, 1024), "red").save(data, "JPEG")
        return base64.b64encode(data.getvalue()).decode()

    def test_cloudflare_picture_is_read(self):
        reply = Reply(200, {"success": True, "result": {"image": self.jpeg()}})
        picture, reason = robot.draw_cloudflare_picture("dog", "acc", "tok", post=lambda *a, **k: reply)
        self.assertEqual(picture.size, (1024, 1024))
        self.assertIsNone(reason)

    def test_a_missing_secret_or_refusal_gives_a_reason_not_a_crash(self):
        self.assertIn("secret is missing", robot.draw_cloudflare_picture("dog", "", "tok")[1])
        reply = Reply(403, {"success": False, "errors": [{"message": "no access"}]})
        picture, reason = robot.draw_cloudflare_picture("dog", "a", "t", post=lambda *a, **k: reply)
        self.assertIsNone(picture)
        self.assertIn("no access", reason)

    def test_failed_drawing_falls_back_to_the_card_without_an_ai_label(self):
        order = {"brief": "x", "type": "picture", "reference": ""}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(robot, "write_post", return_value=dict(GOOD)), \
                mock.patch.object(robot, "draw_cloudflare_picture", return_value=(None, "busy")):
            details = robot.make_content(order, {}, folder)
            self.assertTrue(os.path.exists(os.path.join(folder, "post.jpg")))
        self.assertFalse(details["ai_picture"])
        self.assertIn("free card", details["picture_source"])
        self.assertNotIn("made with AI", details["caption"])

    def test_the_brief_is_never_sent_to_the_picture_maker(self):
        order = {"brief": "Advert words here", "type": "picture", "reference": ""}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(robot, "write_post", return_value=dict(GOOD)), \
                mock.patch.object(robot, "draw_cloudflare_picture", return_value=(None, "busy")) as draw:
            robot.make_content(order, {}, folder)
        self.assertEqual(draw.call_args[0][0], "A dog bowl.")

    def test_video_is_a_real_vertical_mp4(self):
        import imageio_ffmpeg
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "v.mp4")
            robot.make_video(Image.new("RGB", (1024, 1024), "red"), "Hook", True, path)
            info = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", path], capture_output=True, text=True).stderr
        self.assertIn("1080x1920", info)
        self.assertIn("h264", info)
        self.assertIn("aac", info)
        self.assertIn("00:00:10", info)


class Channels(unittest.TestCase):
    def test_a_solvix_channel_stops_everything(self):
        solvix = {"id": "6ae9def0e29c69a1714a5301", "name": "solvix0", "service": "instagram", "paused": False}
        with self.assertRaises(robot.OrderProblem):
            robot.pick_channels(CHANNELS + [solvix])

    def test_an_unknown_name_or_missing_channel_stops(self):
        renamed = [dict(c, name="Something else") if c["service"] == "facebook" else c for c in CHANNELS]
        for channels in (renamed, CHANNELS[1:]):
            with self.assertRaises(robot.OrderProblem):
                robot.pick_channels(channels)

    def test_the_robot_is_only_given_the_pet_shelf_key(self):
        with open(".github/workflows/pet-shelf-order.yml", encoding="utf-8") as f:
            workflow = f.read()
        self.assertIn("secrets.PET_SHELF_BUFFER_API_KEY", workflow)
        self.assertNotIn("secrets.BUFFER_API_KEY", workflow)


class Sending(unittest.TestCase):
    def test_draft_goes_to_all_three_as_drafts(self):
        buffer = FakeBuffer()
        posts = send(buffer)
        self.assertEqual({p["service"] for p in posts}, {"facebook", "instagram", "tiktok"})
        self.assertTrue(all(p["saveToDraft"] for p in buffer.created))
        self.assertTrue(all(p["status"] == "draft" for p in posts))

    def test_a_post_that_is_not_a_draft_is_deleted_and_goes_red(self):
        buffer = FakeBuffer(status="scheduled")
        with self.assertRaises(robot.OrderProblem):
            send(buffer)
        self.assertEqual(len(buffer.deleted), 3)

    def test_one_refusal_goes_red_but_the_others_are_tried(self):
        buffer = FakeBuffer(refuse={"ig"})
        with self.assertRaises(robot.OrderProblem) as caught:
            send(buffer)
        self.assertIn("Instagram: the channel said no", str(caught.exception))
        self.assertEqual({p["channelId"] for p in buffer.created}, {"fb", "tt"})

    def test_a_rerun_only_sends_what_is_missing(self):
        buffer = FakeBuffer()
        earlier = [{"service": "instagram", "channel_id": "ig", "channel_name": "x", "post_id": "old"}]
        send(buffer, earlier=earlier)
        self.assertEqual({p["channelId"] for p in buffer.created}, {"fb", "tt"})

    def test_real_mode_schedules_at_the_exact_time(self):
        buffer = FakeBuffer()
        plan = Plan("customScheduled", datetime(2026, 11, 4, 18, 30, tzinfo=timezone.utc), NOW.date())
        send(buffer, draft=False, plan=plan)
        self.assertTrue(all(p["dueAt"] == "2026-11-04T18:30:00.000Z" for p in buffer.created))
        self.assertFalse(any(p.get("saveToDraft") for p in buffer.created))

    def test_a_buffer_error_status_goes_red(self):
        plan = Plan("customScheduled", datetime(2026, 11, 4, 18, 30, tzinfo=timezone.utc), NOW.date())
        with self.assertRaises(robot.OrderProblem):
            send(FakeBuffer(status="error"), draft=False, plan=plan)

    def test_video_shape(self):
        urls = dict(URLS, video="https://example.com/v.mp4")
        post = robot.build_post("instagram", "ig", "#ad x", urls, "Hook", True, plan_now(NOW), True)
        self.assertEqual(post["assets"][0]["video"]["url"], urls["video"])
        self.assertNotIn("thumbnailUrl", post["assets"][0]["video"])     # Buffer refuses it
        self.assertEqual(post["metadata"]["instagram"]["type"], "reel")
        self.assertTrue(post["metadata"]["instagram"]["isAiGenerated"])
        tiktok = robot.build_post("tiktok", "tt", "#ad x", urls, "Hook", False, plan_now(NOW), True)
        self.assertFalse(tiktok["metadata"]["tiktok"]["isAiGenerated"])

    def test_health_hashtags_are_dropped(self):
        self.assertEqual(robot.clean_hashtags(["doghealth", "VetTips", "slowfeeder"]), ["slowfeeder"])

    def test_tiktok_photos_do_not_send_the_ai_switch(self):
        post = robot.build_post("tiktok", "tt", "#ad x", URLS, "Hook", True, plan_now(NOW), True)
        self.assertNotIn("isAiGenerated", post["metadata"]["tiktok"])


BOARDS = [{"serviceId": "b-dog", "name": "Dog Gear That Fixes Things"},
          {"serviceId": "b-cat", "name": "Indoor Cat Must-Haves"},
          {"serviceId": "b-walk", "name": "Dog Walking Essentials"},
          {"serviceId": "b-small", "name": "Small Pet & Hamster Cage Ideas"}]
PIN_CHANNEL = {"id": "pin", "name": "solvixpetsupplies", "service": "pinterest", "paused": False}


class Pinterest(unittest.TestCase):
    def test_pinterest_is_optional_and_must_be_ours(self):
        self.assertNotIn("pinterest", robot.pick_channels(CHANNELS))
        self.assertEqual(robot.pick_channels(CHANNELS + [PIN_CHANNEL])["pinterest"]["id"], "pin")
        with self.assertRaises(robot.OrderProblem):
            robot.pick_channels(CHANNELS + [dict(PIN_CHANNEL, name="someone else")])
        with self.assertRaises(robot.OrderProblem):
            robot.pick_channels(CHANNELS + [PIN_CHANNEL, dict(PIN_CHANNEL, id="pin2")])

    def test_the_board_follows_the_product(self):
        pick = lambda words, wanted="": robot.choose_board(BOARDS, wanted, words)["serviceId"]
        self.assertEqual(pick("Height-adjustable raised dog bowls."), "b-dog")
        self.assertEqual(pick("Cat window perch for indoor cats"), "b-cat")
        self.assertEqual(pick("No-pull dog harness"), "b-walk")
        self.assertEqual(pick("Rabbit litter box with drawer"), "b-small")
        self.assertEqual(pick("Cat window perch", "Dog Walking Essentials"), "b-walk")   # the order wins
        self.assertIsNone(robot.choose_board([], "", "dog"))

    def test_a_refused_board_is_never_used_and_the_newest_twin_wins(self):
        old_gear, new_gear = BOARDS[0], {"serviceId": "999", "name": "Dog Gear That Fixes Things"}
        pick = lambda boards, words, dead=(): robot.choose_board(boards, "", words, dead)
        # the board was deleted and made again: Buffer lists both, the newest number wins
        self.assertEqual(pick(BOARDS + [new_gear], "Raised dog bowls")["serviceId"], "999")
        # only the dead one is listed: a dog product stays on a dog board, never a random one
        self.assertEqual(pick(BOARDS, "Raised dog bowls", {"b-dog"})["serviceId"], "b-walk")
        self.assertEqual(pick(BOARDS, "Cat window perch", {"b-cat"}), None)        # no other cat board here
        self.assertEqual(pick(BOARDS, "Aquarium net", {"b-dog"}), None)            # no pin beats a wrong board
        self.assertEqual(old_gear["serviceId"], "b-dog")

    def test_the_robot_learns_dead_boards_from_refused_pins(self):
        class Pins:
            asked = []
            def ask(self, query, variables=None):
                post_id = query.split('id: "')[1].split('"')[0]
                self.asked.append(post_id)
                return {"post": {
                    "gone": {"status": "error", "error": {"message": "So sorry, it seems this board doesn't exist in Pinterest anymore"},
                             "metadata": {"board": {"serviceId": "b-dog", "name": "Dog Gear That Fixes Things"}}},
                    "fine": {"status": "sent", "error": None, "metadata": {"board": {"serviceId": "b-cat", "name": "x"}}},
                    "wait": {"status": "scheduled", "error": None, "metadata": {}},
                    "other": {"status": "error", "error": {"message": "Something else broke"},
                              "metadata": {"board": {"serviceId": "b-walk", "name": "y"}}}}[post_id]}
        with tempfile.TemporaryDirectory() as base:
            for n, post_id in enumerate(("gone", "fine", "wait", "other")):
                folder = os.path.join(base, "orders", f"2026-11-12-pin-{n}")
                os.makedirs(folder)
                with open(os.path.join(folder, robot.RECORD), "w") as f:
                    json.dump({"mode": "post", "posts": [{"service": "instagram", "post_id": "ig"},
                                                         {"service": "pinterest", "post_id": post_id}]}, f)
            pins = Pins()
            dead = robot.learn_dead_boards(pins, base)
            self.assertEqual(list(dead), ["b-dog"])                       # only "board doesn't exist" counts
            self.assertEqual(robot.load_dead_boards(base), dead)          # remembered on the media branch
            self.assertEqual(sorted(pins.asked), ["fine", "gone", "other", "wait"])   # never asks about Instagram
            pins.asked.clear()
            self.assertEqual(list(robot.learn_dead_boards(pins, base)), ["b-dog"])
            self.assertEqual(pins.asked, ["wait"])                        # finished pins are asked about once

    def test_the_pin_record_keeps_its_board(self):
        buffer = FakeBuffer()
        targets = robot.pick_channels(CHANNELS + [PIN_CHANNEL])
        posts = robot.send_to_buffer(buffer, robot.limit_targets(targets, ["pinterest"]), "#ad hello", URLS, "Hook",
                                     True, plan_now(NOW), True, [], lambda p: None, lambda: NOW,
                                     {"board": BOARDS[1], "title": "T"})
        self.assertEqual((posts[0]["board"], posts[0]["board_service_id"]), ("Indoor Cat Must-Haves", "b-cat"))

    def test_a_pin_has_one_picture_a_board_a_title_and_the_shop_link(self):
        urls = dict(URLS, video="https://example.com/v.mp4",
                    slides=["https://example.com/post.jpg", "https://example.com/slide-2.jpg"])
        pin = {"board": BOARDS[0], "title": "Raised dog bowls"}
        caption = "#ad Big dog bends low to eat?\n\n👉 Link in bio\n\n#dogs"
        post = robot.build_post("pinterest", "pin", caption, urls, "Hook", True, plan_now(NOW), True, pin)
        self.assertEqual(post["assets"], [{"image": {"url": URLS["picture"]}}])
        self.assertEqual(post["metadata"], {"pinterest": {"boardServiceId": "b-dog", "title": "Raised dog bowls",
                                                          "url": "https://solvix-shelf.pages.dev/?src=pin"}})
        self.assertTrue(post["text"].startswith("#ad "))
        self.assertNotIn("Link in bio", post["text"])
        self.assertTrue(post["saveToDraft"])

    def test_title_and_text_fit_pinterest_limits(self):
        self.assertEqual(robot.pin_title("Raised dog bowls.", ""), "Raised dog bowls")
        self.assertLessEqual(len(robot.pin_title("word " * 60, "")), 100)
        self.assertLessEqual(len(robot.pin_text("#ad " + "word " * 200)), 500)

    def test_pinterest_is_sent_with_the_others_and_checked_as_one_picture(self):
        buffer = FakeBuffer()
        targets = robot.pick_channels(CHANNELS + [PIN_CHANNEL])
        urls = dict(URLS, slides=["https://example.com/post.jpg"])
        posts = robot.send_to_buffer(buffer, targets, "#ad hello\n\n👉 Link in bio", urls, "Hook", True,
                                     plan_now(NOW), True, [], lambda p: None, lambda: NOW,
                                     {"board": BOARDS[0], "title": "T"})
        self.assertEqual({p["service"] for p in posts}, {"facebook", "instagram", "tiktok", "pinterest"})

    def test_boards_are_read_from_the_channel(self):
        class Boards:
            def ask(self, query, variables=None):
                if "organizations" in query:
                    return {"account": {"organizations": [{"id": "o1"}]}}
                return {"channels": [{"id": "ig", "metadata": {}},
                                     {"id": "pin", "metadata": {"boards": BOARDS + [{"name": "no id"}]}}]}
        self.assertEqual(robot.pinterest_boards(Boards(), "pin"), BOARDS)
        self.assertEqual(robot.pinterest_boards(Boards(), "missing"), [])

    def test_the_queue_passes_the_board(self):
        import pet_shelf_queue as queue
        entry = {"id": "x", "date": "2026-11-12", "time": "02:00", "picture": "ready/a.jpg", "caption": "Hi",
                 "board": "Indoor Cat Must-Haves"}
        self.assertEqual(queue.order_env(entry, {}, "1", 1, "draft")["ORDER_BOARD"], "Indoor Cat Must-Haves")


class SecondPinterestAccountTest(unittest.TestCase):
    """Pinterest in its own free Buffer account (PINTEREST_BUFFER_API_KEY), 11 Nov 2026."""

    def pin_account(self, channels):
        class Account(FakeBuffer):
            def channels(self_inner):
                return channels
        return Account()

    def test_pinterest_comes_from_the_second_account(self):
        account = self.pin_account([PIN_CHANNEL])
        targets = robot.pick_channels(CHANNELS)
        got = robot.connect_pinterest({"PINTEREST_BUFFER_API_KEY": "k"}, targets, lambda key: account)
        self.assertIs(got, account)
        self.assertEqual(targets["pinterest"]["id"], "pin")

    def test_no_key_means_no_pinterest_and_no_change(self):
        targets = robot.pick_channels(CHANNELS)
        self.assertIsNone(robot.connect_pinterest({}, targets, lambda key: self.fail("no account wanted")))
        self.assertNotIn("pinterest", targets)

    def test_pinterest_in_the_main_account_wins(self):
        targets = robot.pick_channels(CHANNELS + [PIN_CHANNEL])
        self.assertIsNone(robot.connect_pinterest({"PINTEREST_BUFFER_API_KEY": "k"}, targets,
                                                  lambda key: self.fail("not needed")))

    def test_trouble_only_skips_pinterest(self):
        solvix = {"id": next(iter(robot.SOLVIX_CHANNEL_IDS)), "name": "solvix", "service": "facebook", "paused": False}
        bad_sets = [[], [solvix, PIN_CHANNEL], [dict(PIN_CHANNEL, name="someone else")],
                    [PIN_CHANNEL, dict(PIN_CHANNEL, id="pin2")]]
        for channels in bad_sets:
            targets = robot.pick_channels(CHANNELS)
            with mock.patch.object(robot, "warn") as warned:
                self.assertIsNone(robot.connect_pinterest({"PINTEREST_BUFFER_API_KEY": "k"}, targets,
                                                          lambda key: self.pin_account(channels)))
            self.assertNotIn("pinterest", targets)
            warned.assert_called_once()

        def broken(key):
            raise BufferError("Buffer did not accept the key")
        targets = robot.pick_channels(CHANNELS)
        with mock.patch.object(robot, "warn"):
            self.assertIsNone(robot.connect_pinterest({"PINTEREST_BUFFER_API_KEY": "k"}, targets, broken))

    def test_pin_goes_to_the_second_account_and_the_rest_to_the_main_one(self):
        main, pins = FakeBuffer(), FakeBuffer()
        targets = robot.pick_channels(CHANNELS)
        targets["pinterest"] = PIN_CHANNEL
        posts = robot.send_to_buffer(main, targets, "#ad hello\n\n👉 Link in bio", URLS, "Hook", True,
                                     plan_now(NOW), True, [], lambda p: None, lambda: NOW,
                                     {"board": BOARDS[0], "title": "T"}, pins)
        self.assertEqual({p["service"] for p in posts}, {"facebook", "instagram", "tiktok", "pinterest"})
        self.assertEqual([p["channelId"] for p in pins.created], ["pin"])
        self.assertEqual(sorted(p["channelId"] for p in main.created), ["fb", "ig", "tt"])
        self.assertNotIn("Link in bio", pins.created[0]["text"])


if __name__ == "__main__":
    unittest.main()
