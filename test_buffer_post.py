"""
Tests for posting through Buffer. Run them with:   python test_buffer_post.py

NOTHING here touches the internet or the real Buffer. A tiny pretend Buffer ("FakeBuffer") runs on
this computer and answers the same kinds of questions as api.buffer.com. That proves OUR logic
(when to post, which channels, what we send, what happens when things go wrong). It cannot prove
that the real Buffer still accepts our wording: the "rehearsal" command is for that (BUFFER-SETUP.md).

Each test is a short story: "given this situation, this should happen".
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Make sure "talk to this computer" is never sent through a proxy
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"

import buffer_post as bp  # noqa: E402

try:
    import yaml           # only needed for the workflow tests; they are skipped without it
except ImportError:       # pragma: no cover
    yaml = None


def at(text):
    """'2026-10-28 18:17' -> a UTC time."""
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# =============================================================================================
# A pretend Buffer
# =============================================================================================

class FakeBuffer:
    KEY = "test-key-123"

    def __init__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):       # keep the test output quiet
                pass

            def reply(self, status, data, kind, headers=None):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):                    # the "public picture" addresses
                owner.picture_requests.append(self.path)
                if self.path == "/pic.jpg":
                    self.reply(200, b"\xff\xd8\xff\xe0 pretend jpeg", "image/jpeg")
                elif self.path == "/unlabelled.jpg":       # a real JPEG, but the server forgot to say so
                    self.reply(200, b"\xff\xd8\xff\xe0 pretend jpeg", "application/octet-stream")
                elif self.path == "/login-page.jpg":
                    self.reply(200, b"<html>please log in</html>", "text/html")
                else:
                    self.reply(404, b"not found", "text/plain")

            def do_POST(self):                   # Buffer's one address
                size = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(size) or b"{}")
                owner.requests.append({"query": body.get("query", ""), "variables": body.get("variables"),
                                       "auth": self.headers.get("Authorization"),
                                       "agent": self.headers.get("User-Agent")})
                status, payload, headers = owner.answer(body, self.headers.get("Authorization"))
                self.reply(status, json.dumps(payload).encode(), "application/json", headers)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.reset()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def reset(self):
        self.requests = []                 # every question we received
        self.picture_requests = []
        self.organizations = [{"id": "org1", "name": "Solvix"}]
        self.channels = [
            {"id": "ch_fb", "name": "Solvix Page", "service": "facebook", "isQueuePaused": False},
            {"id": "ch_ig", "name": "solvix0", "service": "instagram", "isQueuePaused": False},
            {"id": "ch_tt", "name": "solvix", "service": "tiktok", "isQueuePaused": False},
        ]
        self.created = []                  # the 'input' of every post we were asked to create
        self.refuse = {}                   # channel id -> message: refuse to create a post there
        self.scripted = []                 # one-off answers: (text the question contains, (status, payload, headers))
        self.reject_words = set()          # questions containing these words get a "Cannot query field" answer
        self.status_script = {}            # post id -> list of statuses to give one after the other
        self.now = at("2026-10-28 18:17")  # what Buffer thinks the time is (for "must be in the future")
        self.due_override = None           # pretend Buffer set a different time than we asked for

    # ---- how the pretend Buffer answers -------------------------------------------------
    def answer(self, body, auth):
        query = body.get("query", "")
        for index, (needle, response) in enumerate(self.scripted):
            if needle in query:
                del self.scripted[index]
                return response
        if auth != f"Bearer {self.KEY}":
            return 200, {"data": None, "errors": [{"message": "You must be signed in",
                                                   "extensions": {"code": "UNAUTHORIZED"}}]}, {}
        for word in self.reject_words:
            if word in query:
                return 200, {"errors": [{"message": f'Cannot query field "{word}" on type "X".',
                                         "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}}]}, {}
        if "createPost" in query:
            return self.create_post((body.get("variables") or {}).get("input") or {})
        if "channels(input" in query:
            org = query.split('organizationId: "')[1].split('"')[0]
            if org not in [o["id"] for o in self.organizations]:
                return 200, {"errors": [{"message": "Organization not found", "extensions": {"code": "NOT_FOUND"}}]}, {}
            return 200, {"data": {"channels": self.channels}}, {}
        if "organizations" in query:
            return 200, {"data": {"account": {"organizations": self.organizations}}}, {}
        if "post(input" in query:
            return self.post_status(query.split('id: "')[1].split('"')[0])
        return 200, {"errors": [{"message": "the test server does not know this question"}]}, {}

    def typed_error(self, kind, message):
        return 200, {"data": {"createPost": {"__typename": kind, "message": message}}}, {}

    def create_post(self, given):
        for needed in ("channelId", "text", "schedulingType", "mode", "assets", "metadata"):
            if needed not in given:
                return self.typed_error("InvalidInputError", f"{needed} is required")
        channel = next((c for c in self.channels if c["id"] == given["channelId"]), None)
        if channel is None:
            return self.typed_error("NotFoundError", "Channel not found")
        if channel["service"] not in given["metadata"]:
            return self.typed_error("InvalidInputError",
                                    f"{channel['service'].capitalize()} posts require a type (post, story, or reel)")
        if not given["assets"] or "image" not in given["assets"][0] or not given["assets"][0]["image"].get("url"):
            return self.typed_error("InvalidInputError", "assets must hold an image with a url")
        if given["mode"] == "customScheduled":
            if not given.get("dueAt"):
                return self.typed_error("InvalidInputError", "customScheduled needs dueAt")
            if bp.parse_buffer_time(given["dueAt"]) <= self.now:
                return self.typed_error("InvalidInputError", "dueAt must be in the future")
        if channel["id"] in self.refuse:
            return self.typed_error("InvalidInputError", self.refuse[channel["id"]])
        self.created.append(given)
        post_id = f"post_{len(self.created)}"
        return 200, {"data": {"createPost": {"__typename": "PostActionSuccess",
                                             "post": {"id": post_id,
                                                      "dueAt": self.due_override or given.get("dueAt")}}}}, {}

    def post_status(self, post_id):
        index = int(post_id.split("_")[1]) - 1 if post_id.startswith("post_") else -1
        if not 0 <= index < len(self.created):
            return 200, {"data": {"post": None}, "errors": [{"message": "Post not found",
                                                              "extensions": {"code": "NOT_FOUND"}}]}, {}
        given = self.created[index]
        script = self.status_script.get(post_id)
        if script:
            status = script.pop(0) if len(script) > 1 else script[0]
        else:
            status = "draft" if given.get("saveToDraft") else (
                "scheduled" if given["mode"] == "customScheduled" else "sent")
        post = {"__typename": "Post", "status": status, "dueAt": given.get("dueAt"),
                "sentAt": None, "externalLink": None, "error": None}
        if isinstance(status, tuple):                   # ("error", "the reason")
            post["status"] = status[0]
            post["error"] = {"message": status[1]}
        return 200, {"data": {"post": post}}, {}


# =============================================================================================
# Shared set-up for the tests
# =============================================================================================

CAPTION = "Daily Data Drop: Job Listings\n\nMy scraper collected 100 records today.\n\n#webscraping #python\n"


class InTempFolder(unittest.TestCase):
    """Every test runs inside a fresh empty folder that looks like the project:
    results/2026-10-29_jobs/ holds a caption and a picture."""

    server = None

    @classmethod
    def setUpClass(cls):
        cls.server = FakeBuffer()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        self.server.reset()
        self.sleeps = []
        self.tmp = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(os.chdir, self.old_cwd)
        self.make_folder("results/2026-10-29_jobs")
        self.folder = "results/2026-10-29_jobs"
        self.picture = self.server.url + "/pic.jpg"
        self.env = {"GITHUB_REPOSITORY": "vincent001100/web-scraper"}

    # -- helpers --
    def make_folder(self, path, caption=CAPTION, jpg=True):
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "caption.txt"), "w", encoding="utf-8") as f:
            f.write(caption)
        if jpg:
            with open(os.path.join(path, "post.jpg"), "wb") as f:
                f.write(b"\xff\xd8\xff pretend jpeg")

    def client(self, key=None):
        return bp.Buffer(key or self.server.KEY, api_url=self.server.url, sleep=self.sleeps.append)

    def quietly(self, function, *args, **kwargs):
        """Run something, hide what it prints, and return (result, printed text)."""
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            result = function(*args, **kwargs)
        return result, printed.getvalue()

    def daily(self, now="2026-10-28 18:17", when="next", env=None, buffer=None, **kwargs):
        merged = dict(self.env)
        merged.update(env or {})
        return self.quietly(bp.run_daily, env=merged, now=at(now), when=when, buffer=buffer or self.client(),
                            image_url=self.picture, **kwargs)

    def failure_of(self, function, *args, **kwargs):
        """Run something that must fail with a BufferError; return its message."""
        with self.assertRaises(bp.BufferError) as caught:
            self.quietly(function, *args, **kwargs)
        return str(caught.exception)

    def record(self, folder=None):
        with open(os.path.join(folder or self.folder, bp.RECORD_FILE), encoding="utf-8") as f:
            return json.load(f)


# =============================================================================================
# 1. When to post
# =============================================================================================

class WhenToPost(unittest.TestCase):
    def plan(self, now, when):
        now = at(now)
        return bp.plan_for(bp.decide_post_date(now, when), now)

    def test_evening_run_is_for_tomorrow_at_0600_utc(self):
        plan = self.plan("2026-10-28 18:17", "next")
        self.assertEqual(plan.post_date, date(2026, 10, 29))
        self.assertEqual(plan.mode, "customScheduled")
        self.assertEqual(bp.buffer_time(plan.due_at), "2026-10-29T06:00:00.000Z")

    def test_a_very_late_evening_run_after_midnight_is_still_for_this_morning(self):
        plan = self.plan("2026-10-29 00:30", "next")
        self.assertEqual(plan.post_date, date(2026, 10, 29))
        self.assertEqual(bp.buffer_time(plan.due_at), "2026-10-29T06:00:00.000Z")

    def test_make_com_button_press_at_0600_posts_right_away(self):
        plan = self.plan("2026-10-28 06:00:07", "today")
        self.assertEqual((plan.post_date, plan.mode, plan.due_at), (date(2026, 10, 28), "shareNow", None))

    def test_manual_run_in_the_morning_after_0600_posts_right_away(self):
        self.assertEqual(self.plan("2026-10-28 09:30", "today").mode, "shareNow")

    def test_manual_run_before_0600_is_scheduled_for_0600(self):
        plan = self.plan("2026-10-28 04:00", "today")
        self.assertEqual(plan.mode, "customScheduled")
        self.assertEqual(bp.buffer_time(plan.due_at), "2026-10-28T06:00:00.000Z")

    def test_less_than_three_minutes_before_0600_posts_right_away(self):
        self.assertEqual(self.plan("2026-10-28 05:58", "today").mode, "shareNow")
        self.assertEqual(self.plan("2026-10-28 05:56", "today").mode, "customScheduled")

    def test_an_evening_run_that_starts_at_0558_aims_at_the_following_morning(self):
        plan = self.plan("2026-10-29 05:58", "next")
        self.assertEqual(plan.post_date, date(2026, 10, 30))

    def test_new_year(self):
        plan = self.plan("2026-12-31 18:17", "next")
        self.assertEqual(plan.post_date, date(2027, 1, 1))
        self.assertEqual(bp.buffer_time(plan.due_at), "2027-01-01T06:00:00.000Z")

    def test_now_always_means_right_away(self):
        plan = bp.plan_now(at("2026-10-26 12:00"))
        self.assertEqual((plan.mode, plan.due_at, plan.post_date), ("shareNow", None, date(2026, 10, 26)))

    def test_lagos_time_is_one_hour_ahead(self):
        self.assertIn("07:00 Lagos", bp.human_time(at("2026-10-29 06:00")))

    def test_unknown_when_is_refused(self):
        with self.assertRaises(ValueError):
            bp.decide_post_date(at("2026-10-28 18:17"), "tomorrow-ish")

    def test_the_post_date_command_prints_only_the_date(self):
        code, printed = self.run_main(["post-date", "next", "--now", "2026-10-28T18:17:00Z"])
        self.assertEqual((code, printed), (0, "2026-10-29\n"))

    def test_a_bad_practice_time_is_explained(self):
        code, printed = self.run_main(["post-date", "next", "--now", "garbage"])
        self.assertEqual(code, 1)
        self.assertIn("--now must be written like", printed)

    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = bp.main(argv, env_file=None)
        return code, out.getvalue()

    def test_importing_the_file_needs_no_extra_tools(self):
        """The GitHub 'check' step runs buffer_post.py on a machine that may not have 'requests'."""
        code = ("import sys; sys.path.insert(0, sys.argv[1]); sys.modules['requests'] = None; import buffer_post; "
                "print(buffer_post.decide_post_date(buffer_post.now_utc(), 'today'))")
        result = subprocess.run([sys.executable, "-I", "-c", code, HERE], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


# =============================================================================================
# 2. Dry run: show what would be sent, send nothing
# =============================================================================================

class DryRun(InTempFolder):
    def test_dry_run_prints_the_plan_and_sends_nothing_and_needs_no_key(self):
        env_without_key = {k: v for k, v in os.environ.items() if k != "BUFFER_API_KEY"}
        printed = io.StringIO()
        with mock.patch.dict(os.environ, env_without_key, clear=True), contextlib.redirect_stdout(printed):
            code = bp.main(["daily", "--dry-run", "--when", "next", "--now", "2026-10-28T18:17:00Z",
                            "--folder", self.folder], env_file=None)
        text = printed.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", text)
        self.assertIn("2026-10-29T06:00:00.000Z", text)
        self.assertIn("customScheduled", text)
        self.assertIn("results/2026-10-29_jobs/post.jpg", text)
        self.assertIn('"shouldShareToFeed": true', text)
        self.assertEqual(self.server.requests, [])          # no questions went to Buffer
        self.assertEqual(self.server.picture_requests, [])  # and nobody fetched the picture

    def test_dry_run_of_the_advert_and_the_rehearsal_send_nothing(self):
        os.makedirs("brand/promo")
        shutil.copy(os.path.join(self.folder, "post.jpg"), "brand/promo/automation-post.jpg")
        shutil.copy(os.path.join(self.folder, "caption.txt"), "brand/promo/caption.txt")
        for command in (["promo", "--dry-run"], ["rehearsal", "--dry-run"]):
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                self.assertEqual(bp.main(command, env_file=None), 0)
            self.assertIn("DRY RUN", printed.getvalue())
        self.assertEqual(self.server.requests, [])


# =============================================================================================
# 3. The normal, happy path
# =============================================================================================

class HappyPath(InTempFolder):
    def test_evening_run_schedules_instagram_and_facebook_for_0600_utc(self):
        created, printed = self.daily()
        self.assertEqual([p["service"] for p in created], ["instagram", "facebook"])
        self.assertEqual(len(self.server.created), 2)
        by_channel = {c["channelId"]: c for c in self.server.created}
        self.assertEqual(set(by_channel), {"ch_ig", "ch_fb"})            # not TikTok
        for sent in self.server.created:
            self.assertEqual(sent["mode"], "customScheduled")
            self.assertEqual(sent["dueAt"], "2026-10-29T06:00:00.000Z")
            self.assertEqual(sent["schedulingType"], "automatic")
            self.assertEqual(sent["text"], CAPTION)
            self.assertEqual(sent["assets"], [{"image": {"url": self.picture}}])
        self.assertEqual(by_channel["ch_ig"]["metadata"], {"instagram": {"type": "post", "shouldShareToFeed": True}})
        self.assertEqual(by_channel["ch_fb"]["metadata"], {"facebook": {"type": "post"}})
        self.assertIn("DONE: 2 post(s) handed to Buffer", printed)
        self.assertTrue(all(r["auth"] == f"Bearer {self.server.KEY}" for r in self.server.requests))

    def test_a_record_of_the_posts_is_saved_next_to_the_caption(self):
        self.daily()
        record = self.record()
        self.assertEqual(record["post_date"], "2026-10-29")
        self.assertEqual(record["due_at"], "2026-10-29T06:00:00.000Z")
        self.assertEqual([p["service"] for p in record["posts"]], ["instagram", "facebook"])
        self.assertEqual([p["post_id"] for p in record["posts"]], ["post_1", "post_2"])
        self.assertNotIn(self.server.KEY, json.dumps(record))      # never the key

    def test_a_late_run_posts_right_away_and_waits_for_buffer_to_say_sent(self):
        self.server.status_script = {"post_1": ["sending", "sending", "sent"], "post_2": ["sent"]}
        created, printed = self.daily(now="2026-10-29 09:00", when="today")
        self.assertEqual(len(created), 2)
        for sent in self.server.created:
            self.assertEqual(sent["mode"], "shareNow")
            self.assertNotIn("dueAt", sent)
        self.assertIn("to post right now", printed)
        self.assertGreaterEqual(len(self.sleeps), 2)          # it waited while Buffer was 'sending'
        self.assertIn("Buffer says Instagram: published", printed)

    def test_the_date_chosen_by_the_workflow_wins_over_the_clock(self):
        """The workflow works out the post date once. If the clock drifts past the 'too close' line while the
        robot is scraping, the date must not change: it posts right away instead."""
        created, _ = self.daily(now="2026-10-29 05:59:30", when="next", env={"POST_DATE": "2026-10-29"})
        self.assertEqual(self.server.created[0]["mode"], "shareNow")
        self.assertEqual(self.record()["post_date"], "2026-10-29")

    def test_the_folder_comes_from_the_workflow_when_given(self):
        self.make_folder("results/2026-10-29_hockey")
        self.daily(env={"DAILY_FOLDER": "results/2026-10-29_hockey"})
        self.assertTrue(os.path.exists("results/2026-10-29_hockey/" + bp.RECORD_FILE))
        self.assertFalse(os.path.exists("results/2026-10-29_jobs/" + bp.RECORD_FILE))

    def test_the_folder_is_found_by_date_when_not_given(self):
        self.make_folder("results/2026-10-28_older")
        self.daily()
        self.assertTrue(os.path.exists("results/2026-10-29_jobs/" + bp.RECORD_FILE))

    def test_a_paused_queue_is_a_warning_not_a_failure(self):
        self.server.channels[0]["isQueuePaused"] = True
        _, printed = self.daily()
        self.assertIn("PAUSED", printed)
        self.assertEqual(len(self.server.created), 2)

    def test_a_warning_if_buffer_does_not_keep_our_exact_time(self):
        self.server.due_override = "2026-10-29T08:00:00.000Z"
        created, printed = self.daily()
        self.assertEqual(len(created), 2)
        self.assertIn("we asked Buffer for Thu 29 Oct 2026 06:00 UTC (07:00 Lagos), but it set "
                      "Thu 29 Oct 2026 08:00 UTC (09:00 Lagos)", printed)

    def test_an_unknown_optional_field_is_dropped_once_not_every_time(self):
        self.server.reject_words = {"sentAt"}
        created, _ = self.daily()
        self.assertEqual(len(created), 2)
        self.assertEqual(sum("sentAt" in r["query"] for r in self.server.requests), 1)

    def test_the_extra_field_is_dropped_if_buffer_does_not_know_it(self):
        self.server.reject_words = {"isQueuePaused"}
        created, _ = self.daily()
        self.assertEqual(len(created), 2)

    def test_the_picture_is_checked_before_anything_is_created(self):
        self.daily()
        self.assertEqual(self.server.picture_requests, ["/pic.jpg"])


# =============================================================================================
# 4. Things going wrong must be loud, plain, and must not make a mess
# =============================================================================================

class WhenThingsGoWrong(InTempFolder):
    def test_wrong_key_says_so_and_creates_nothing_and_never_prints_the_key(self):
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                                  buffer=self.client("wrong-key-999"), image_url=self.picture)
        self.assertIn("did not accept the API key", message)
        self.assertNotIn("wrong-key-999", message)
        self.assertEqual(self.server.created, [])

    def test_no_key_at_all(self):
        with self.assertRaises(bp.BufferError) as caught:
            bp.Buffer("   ")
        self.assertIn("BUFFER_API_KEY is not set", str(caught.exception))

    def test_a_key_with_stray_spaces_still_works(self):
        created, _ = self.daily(buffer=self.client(f"  {self.server.KEY}\n"))
        self.assertEqual(len(created), 2)

    def test_no_instagram_channel_stops_before_anything_is_created(self):
        self.server.channels = [c for c in self.server.channels if c["service"] != "instagram"]
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                                  buffer=self.client(), image_url=self.picture)
        self.assertIn("no Instagram channel", message)
        self.assertIn("facebook 'Solvix Page'", message)
        self.assertEqual(self.server.created, [])

    def test_two_facebook_channels_are_not_guessed(self):
        self.server.channels.append({"id": "ch_fb2", "name": "Other Page", "service": "facebook", "isQueuePaused": False})
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                                  buffer=self.client(), image_url=self.picture)
        self.assertIn("2 Facebook channels", message)
        self.assertIn("BUFFER_FACEBOOK_CHANNEL_ID", message)
        self.assertEqual(self.server.created, [])

    def test_naming_the_channel_with_a_secret_settles_it(self):
        self.server.channels.append({"id": "ch_fb2", "name": "Other Page", "service": "facebook", "isQueuePaused": False})
        self.daily(env={"BUFFER_FACEBOOK_CHANNEL_ID": "ch_fb2"})
        self.assertEqual({c["channelId"] for c in self.server.created}, {"ch_ig", "ch_fb2"})

    def test_a_channel_id_that_does_not_exist_is_explained(self):
        message = self.failure_of(bp.run_daily, env={**self.env, "BUFFER_INSTAGRAM_CHANNEL_ID": "nope"},
                                  now=at("2026-10-28 18:17"), when="next", buffer=self.client(), image_url=self.picture)
        self.assertIn("BUFFER_INSTAGRAM_CHANNEL_ID", message)
        self.assertIn("not one of the Instagram channels", message)

    def test_a_picture_that_is_not_public_stops_everything(self):
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                                  buffer=self.client(), image_url=self.server.url + "/missing.jpg")
        self.assertIn("could not fetch the picture", message)
        self.assertIn("HTTP 404", message)
        self.assertEqual(self.server.created, [])
        self.assertEqual(len(self.sleeps), 5)         # it tried 6 times, waiting in between

    def test_a_real_picture_with_a_vague_label_is_accepted(self):
        created, _ = self.quietly(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                                  buffer=self.client(), image_url=self.server.url + "/unlabelled.jpg")
        self.assertEqual(len(created), 2)

    def test_a_login_page_is_not_a_picture(self):
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                                  buffer=self.client(), image_url=self.server.url + "/login-page.jpg")
        self.assertIn("text/html", message)

    def test_instagram_refused_but_facebook_is_still_posted_and_boss_is_told_what_to_do(self):
        self.server.refuse = {"ch_ig": "Instagram rejected the image"}
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                                  buffer=self.client(), image_url=self.picture)
        self.assertIn("Instagram: Buffer would not create the post: Instagram rejected the image", message)
        self.assertIn("Already created in Buffer: Facebook", message)
        self.assertIn("Do not tick 'Post again' for this day, or Facebook would get it twice", message)
        self.assertEqual([c["channelId"] for c in self.server.created], ["ch_fb"])
        self.assertEqual([p["service"] for p in self.record()["posts"]], ["facebook"])   # remembered

    def test_a_post_buffer_says_failed_is_not_called_fine(self):
        self.server.status_script = {"post_1": [("error", "Instagram could not open the picture")], "post_2": ["sent"]}
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-29 09:00"), when="today",
                                  buffer=self.client(), image_url=self.picture)
        self.assertIn("Already created in Buffer: Facebook. Add the missing post", message)
        self.assertNotIn("Instagram and Facebook would get it twice", message)

    def test_buffer_having_a_bad_day_stops_without_retrying_a_post(self):
        self.server.scripted = [("createPost", (500, {"error": "boom"}, {}))]
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                                  buffer=self.client(), image_url=self.picture)
        self.assertIn("problem on its side", message)
        self.assertIn("may still have received the post", message)      # warns about double posting
        self.assertEqual(sum("createPost" in r["query"] for r in self.server.requests), 1)   # no retry

    def test_buffer_asking_us_to_slow_down_is_obeyed_then_it_works(self):
        self.server.scripted = [("channels(input", (429, {"errors": [{"message": "slow down",
                                                                         "extensions": {"code": "RATE_LIMIT_EXCEEDED"}}]},
                                                    {"Retry-After": "7"}))]
        created, printed = self.daily()
        self.assertEqual(len(created), 2)
        self.assertEqual(self.sleeps, [7])
        self.assertIn("slow down", printed)

    def test_a_long_wait_demanded_by_buffer_is_reported_not_slept_through(self):
        self.server.scripted = [("organizations", (429, {}, {"Retry-After": "3600"}))]
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                                  buffer=self.client(), image_url=self.picture)
        self.assertIn("too many times", message)
        self.assertEqual(self.sleeps, [])

    def test_no_internet_is_explained(self):
        client = bp.Buffer(self.server.KEY, api_url="http://127.0.0.1:9", sleep=self.sleeps.append)   # nobody listens there
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                                  buffer=client, image_url=self.picture)
        self.assertIn("Could not reach Buffer", message)

    def test_buffer_changing_its_api_gives_a_clear_message(self):
        self.server.reject_words = {"CreatePostInput"}
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                                  buffer=self.client(), image_url=self.picture)
        self.assertIn("usually means its API changed", message)

    def test_buffer_saying_a_post_failed_to_publish_is_a_failure(self):
        self.server.status_script = {"post_1": [("error", "Instagram could not open the picture")]}
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-29 09:00"), when="today",
                                  buffer=self.client(), image_url=self.picture)
        self.assertIn("Instagram: Buffer could not publish it: Instagram could not open the picture", message)

    def test_not_being_able_to_read_the_status_is_only_a_warning(self):
        self.server.reject_words = {"post(input"}
        created, printed = self.daily()
        self.assertEqual(len(created), 2)                  # the posts exist, so this is not a failure
        self.assertIn("could not read its status", printed)

    def test_caption_problems_are_caught_early(self):
        for caption, expected in (("   \n", "caption is empty"),
                                  ("x" * 2300, "at most 2200"),
                                  (" ".join(f"#tag{i}" for i in range(31)), "31 hashtags")):
            self.make_folder("results/2026-10-30_bad", caption=caption)
            message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-29 18:17"), when="next",
                                      buffer=self.client(), image_url=self.picture)
            self.assertIn(expected, message)
        self.assertEqual(self.server.created, [])

    def test_a_missing_jpeg_is_explained(self):
        self.make_folder("results/2026-10-30_nojpg", jpg=False)
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-29 18:17"), when="next",
                                  buffer=self.client(), image_url=self.picture)
        self.assertIn("post.jpg is missing", message)

    def test_no_folder_for_the_day_is_explained(self):
        message = self.failure_of(bp.run_daily, env=self.env, now=at("2026-11-05 18:17"), when="next",
                                  buffer=self.client(), image_url=self.picture)
        self.assertIn("There is no folder for 2026-11-06", message)

    def test_main_turns_any_problem_into_exit_code_1_and_a_message_on_stderr(self):
        self.server.channels = []                                # Buffer has no channels: a problem
        real_class = bp.Buffer

        def pretend_buffer(key):
            return real_class(key, api_url=self.server.url, sleep=self.sleeps.append)

        with mock.patch.dict(os.environ, {"BUFFER_API_KEY": self.server.KEY}), \
                mock.patch.object(bp, "Buffer", pretend_buffer):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = bp.main(["channels"], env_file=None)
        self.assertEqual(code, 1)
        self.assertIn("BUFFER POST FAILED", err.getvalue())
        self.assertIn("Buffer has no Instagram channel", err.getvalue())

    def test_an_unexpected_crash_is_still_a_red_x_with_a_plain_sentence(self):
        with mock.patch.object(bp, "run_channels", side_effect=KeyError("surprise")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = bp.main(["channels"], env_file=None)
        self.assertEqual(code, 1)
        self.assertIn("Something unexpected went wrong inside the Buffer robot", err.getvalue())
        self.assertIn("Show this to the Builders", err.getvalue())

    def test_we_introduce_ourselves_to_buffer(self):
        self.client().channels()
        self.assertTrue(all("solvix-robot" in (r.get("agent") or "") for r in self.server.requests))

    def test_github_annotations_are_used_on_github(self):
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            _, printed = self.quietly(bp.warn, "line one\nline two")
        self.assertIn("::warning title=Buffer::line one%0Aline two", printed)


# =============================================================================================
# 5. Never post the same day twice ("Re-run failed jobs" safety)
# =============================================================================================

class NoDoublePosting(InTempFolder):
    def test_a_channel_that_already_has_todays_post_is_skipped_on_a_rerun(self):
        # an earlier (half-finished) run made the Facebook post from a different folder
        self.make_folder("results/2026-10-29_hockey")
        with open("results/2026-10-29_hockey/" + bp.RECORD_FILE, "w") as f:
            json.dump({"posts": [{"service": "facebook", "post_id": "old_77"}]}, f)
        created, printed = self.daily()
        self.assertEqual([p["service"] for p in created], ["instagram"])
        self.assertEqual([c["channelId"] for c in self.server.created], ["ch_ig"])
        self.assertIn("Facebook: already handed to Buffer for 2026-10-29 (post id old_77", printed)

    def test_when_both_are_done_nothing_is_posted_and_it_is_not_an_error(self):
        self.daily()
        before = len(self.server.created)
        created, printed = self.daily()
        self.assertEqual((created, len(self.server.created)), ([], before))
        self.assertIn("nothing new to post", printed)

    def test_the_post_again_tickbox_overrides_it(self):
        self.daily()
        self.daily(env={"FORCE_POST": "true"})
        self.assertEqual(len(self.server.created), 4)

    def test_a_retry_in_the_same_folder_keeps_the_first_runs_record(self):
        self.server.refuse = {"ch_fb": "Facebook is having a moment"}
        self.failure_of(bp.run_daily, env=self.env, now=at("2026-10-28 18:17"), when="next",
                        buffer=self.client(), image_url=self.picture)
        self.assertEqual([p["service"] for p in self.record()["posts"]], ["instagram"])
        self.server.refuse = {}                                    # Facebook recovers; someone retries
        created, printed = self.daily()
        self.assertEqual([p["service"] for p in created], ["facebook"])      # only the missing one is made
        self.assertEqual([p["service"] for p in self.record()["posts"]], ["instagram", "facebook"])
        self.assertEqual(len(self.server.created), 2)                        # Instagram was NOT made twice

    def test_another_day_is_not_affected(self):
        self.daily()
        self.make_folder("results/2026-10-30_quotes")
        self.daily(now="2026-10-29 18:17")
        self.assertEqual(len(self.server.created), 4)


# =============================================================================================
# 6. The morning check: did the posts really go out?
# =============================================================================================

class MorningCheck(InTempFolder):
    def setUp(self):
        super().setUp()
        self.daily()                                         # evening run made two posts for 29 Oct
        self.env_with_key = {"BUFFER_API_KEY": self.server.KEY}

    def check(self, now="2026-10-29 06:41"):
        return self.quietly(bp.run_check_today, env=self.env_with_key, now=at(now),
                            buffer=self.client(), tries=3, pause=20)

    def test_everything_sent_is_fine(self):
        self.server.status_script = {"post_1": ["sent"], "post_2": ["sent"]}
        _, printed = self.check()
        self.assertIn("All of today's Buffer posts look fine", printed)

    def test_an_error_status_is_a_red_x_with_buffers_reason(self):
        self.server.status_script = {"post_1": [("error", "Token expired")], "post_2": ["sent"]}
        message = self.failure_of(bp.run_check_today, env=self.env_with_key, now=at("2026-10-29 06:41"),
                                  buffer=self.client(), tries=3, pause=20)
        self.assertIn("Instagram: Buffer could not publish it: Token expired", message)
        self.assertIn("Open Buffer", message)

    def test_a_post_that_is_still_scheduled_after_its_time_is_a_red_x_after_waiting_a_bit(self):
        self.server.status_script = {"post_1": ["scheduled"], "post_2": ["sent"]}
        message = self.failure_of(bp.run_check_today, env=self.env_with_key, now=at("2026-10-29 06:41"),
                                  buffer=self.client(), tries=3, pause=20)
        self.assertIn("still 'scheduled', but it was due at", message)
        self.assertEqual(self.sleeps, [20, 20, 20])

    def test_a_post_that_becomes_sent_while_we_wait_is_fine(self):
        self.server.status_script = {"post_1": ["scheduled", "sending", "sent"], "post_2": ["sent"]}
        _, printed = self.check()
        self.assertIn("All of today's Buffer posts look fine", printed)
        self.assertEqual(len(self.sleeps), 2)

    def test_a_post_still_waiting_for_its_time_is_fine(self):
        self.server.status_script = {"post_1": ["scheduled"], "post_2": ["scheduled"]}
        _, printed = self.check(now="2026-10-29 05:30")
        self.assertIn("goes out at", printed)

    def test_without_a_key_it_stays_quiet_and_succeeds(self):
        _, printed = self.quietly(bp.run_check_today, env={}, now=at("2026-10-29 06:41"))
        self.assertIn("not switched on", printed)

    def test_no_folder_for_today_is_a_red_x(self):
        shutil.rmtree("results/2026-10-29_jobs")
        message = self.failure_of(bp.run_check_today, env=self.env_with_key, now=at("2026-10-29 06:41"),
                                  buffer=self.client())
        self.assertIn("no post for 2026-10-29 in the results folder yet (checked at 06:41 UTC)", message)

    def test_a_folder_made_the_old_way_has_nothing_to_check(self):
        os.remove("results/2026-10-29_jobs/" + bp.RECORD_FILE)
        _, printed = self.check()
        self.assertIn("went out the old way (Make.com)", printed)

    def test_a_check_that_cannot_ask_buffer_is_a_red_x_too(self):
        """A monitor that cannot monitor must say so, or a broken post would go unnoticed."""
        self.server.reject_words = {"post(input"}
        message = self.failure_of(bp.run_check_today, env=self.env_with_key, now=at("2026-10-29 06:41"),
                                  buffer=self.client())
        self.assertIn("did not understand our request", message)
        self.assertIn("Tell the Builders", message)

    def test_a_deleted_post_is_a_red_x(self):
        self.server.created.clear()                     # Buffer no longer knows these posts
        message = self.failure_of(bp.run_check_today, env=self.env_with_key, now=at("2026-10-29 06:41"),
                                  buffer=self.client())
        self.assertIn("could not check", message)


# =============================================================================================
# 7. The helper commands: channels, rehearsal, the advert
# =============================================================================================

class HelperCommands(InTempFolder):
    def test_channels_lists_what_buffer_shows_and_what_would_be_used(self):
        _, printed = self.quietly(bp.run_channels, env={}, buffer=self.client())
        self.assertIn("facebook   'Solvix Page'   id ch_fb", printed)
        self.assertIn("Instagram  -> 'solvix0'", printed)
        self.assertEqual(self.server.created, [])

    def test_rehearsal_makes_drafts_only(self):
        os.makedirs("brand/promo")
        shutil.copy(self.folder + "/post.jpg", "brand/promo/automation-post.jpg")
        _, printed = self.quietly(bp.run_rehearsal, env={}, now=at("2026-10-28 12:00"), buffer=self.client(),
                                  image_url=self.picture)
        self.assertEqual(len(self.server.created), 2)
        for sent in self.server.created:
            self.assertTrue(sent["saveToDraft"])
            self.assertEqual(sent["mode"], "addToQueue")
            self.assertNotIn("dueAt", sent)
        self.assertIn("REHEARSAL OK", printed)

    def test_rehearsal_shouts_if_buffer_did_not_make_a_draft(self):
        self.server.status_script = {"post_1": ["scheduled"], "post_2": ["draft"]}
        message = self.failure_of(bp.run_rehearsal, env={}, now=at("2026-10-28 12:00"), buffer=self.client(),
                                  image_url=self.picture)
        self.assertIn("meant to be a draft", message)
        self.assertIn("delete", message)

    def test_rehearsal_fails_if_it_cannot_read_the_drafts_status(self):
        self.server.reject_words = {"post(input"}
        message = self.failure_of(bp.run_rehearsal, env={}, now=at("2026-10-28 12:00"), buffer=self.client(),
                                  image_url=self.picture)
        self.assertIn("test draft was created, but I could not read its status", message)

    def test_the_advert_goes_out_right_away_without_a_record_file(self):
        os.makedirs("brand/promo")
        shutil.copy(self.folder + "/post.jpg", "brand/promo/automation-post.jpg")
        shutil.copy(self.folder + "/caption.txt", "brand/promo/caption.txt")
        created, _ = self.quietly(bp.run_promo, env={}, now=at("2026-11-02 12:00"), buffer=self.client(),
                                  image_url=self.picture)
        self.assertEqual(len(created), 2)
        self.assertTrue(all(c["mode"] == "shareNow" for c in self.server.created))
        self.assertFalse(os.path.exists("brand/promo/" + bp.RECORD_FILE))


# =============================================================================================
# 8. The old Make.com way must work EXACTLY as before when there is no Buffer key
# =============================================================================================

class MakeComWayIsUntouched(InTempFolder):
    def setUp(self):
        super().setUp()
        import post_social
        import post_promo
        self.post_social, self.post_promo = post_social, post_promo
        os.makedirs("brand/promo")
        for name in ("caption.txt", "automation-post.jpg"):
            with open("brand/promo/" + name, "w") as f:
                f.write("advert")

    def run_social(self, env):
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("BUFFER_", "MAKE_", "META_", "FB_", "IG_"))}
        clean.update(env)
        with mock.patch.dict(os.environ, clean, clear=True), \
                mock.patch.object(self.post_social.requests, "post") as fake_post, \
                mock.patch("buffer_post.main") as buffer_main:
            fake_post.return_value.text = "Accepted"
            fake_post.return_value.raise_for_status = lambda: None
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                self.post_social.main()
        return fake_post, buffer_main, printed.getvalue()

    def test_without_a_buffer_key_the_daily_post_goes_to_make_exactly_as_before(self):
        fake_post, buffer_main, printed = self.run_social({
            "MAKE_WEBHOOK_URL": "https://hook.example/abc", "GITHUB_REPOSITORY": "vincent001100/web-scraper",
            "GITHUB_REF_NAME": "main"})
        buffer_main.assert_not_called()
        fake_post.assert_called_once_with("https://hook.example/abc", timeout=60, json={
            "image_url": "https://raw.githubusercontent.com/vincent001100/web-scraper/main/results/2026-10-29_jobs/post.jpg",
            "caption": CAPTION,
            "title": "2026-10-29_jobs",
        })
        self.assertIn("Sent to Make.com", printed)

    def test_a_blank_buffer_secret_counts_as_no_secret(self):
        fake_post, buffer_main, _ = self.run_social({"MAKE_WEBHOOK_URL": "https://hook.example/abc", "BUFFER_API_KEY": "  "})
        buffer_main.assert_not_called()
        fake_post.assert_called_once()

    def test_with_no_secrets_at_all_it_still_just_skips(self):
        fake_post, buffer_main, printed = self.run_social({})
        fake_post.assert_not_called()
        buffer_main.assert_not_called()
        self.assertIn("skipping social posting", printed)

    def test_with_a_buffer_key_the_daily_post_goes_to_buffer_and_not_to_make(self):
        for code in (0, 1):
            with mock.patch.dict(os.environ, {"BUFFER_API_KEY": "k", "MAKE_WEBHOOK_URL": "https://hook.example/abc"}), \
                    mock.patch("buffer_post.main", return_value=code) as buffer_main, \
                    mock.patch.object(self.post_social.requests, "post") as fake_post:
                with self.assertRaises(SystemExit) as stopped:
                    self.post_social.main()
            buffer_main.assert_called_once_with(["daily"])
            fake_post.assert_not_called()
            self.assertEqual(stopped.exception.code, code)       # 1 = red X on GitHub

    def test_the_advert_follows_the_same_rule(self):
        with mock.patch.dict(os.environ, {"MAKE_WEBHOOK_URL": "https://hook.example/abc"}), \
                mock.patch.object(self.post_promo, "send_to_make") as send, mock.patch("buffer_post.main") as buffer_main:
            os.environ.pop("BUFFER_API_KEY", None)
            self.post_promo.main()
        send.assert_called_once()
        buffer_main.assert_not_called()
        with mock.patch.dict(os.environ, {"BUFFER_API_KEY": "k"}), \
                mock.patch.object(self.post_promo, "send_to_make") as send, \
                mock.patch("buffer_post.main", return_value=0) as buffer_main:
            with self.assertRaises(SystemExit) as stopped:
                self.post_promo.main()
        buffer_main.assert_called_once_with(["promo"])
        send.assert_not_called()
        self.assertEqual(stopped.exception.code, 0)


class DailyPyDates(unittest.TestCase):
    """daily.py names the folder and prints the date on the picture. In the evening run that is TOMORROW's date."""

    def setUp(self):
        try:
            import daily
        except ImportError as problem:        # needs the project's tools (pip install -r requirements.txt)
            self.skipTest(f"daily.py needs the project tools installed: {problem}")
        self.daily = daily

    def test_without_post_date_it_is_today_as_always(self):
        with mock.patch.dict(os.environ, {"POST_DATE": ""}):
            self.assertEqual(self.daily.post_day().date(), datetime.now(timezone.utc).date())

    def test_with_post_date_it_is_that_day(self):
        with mock.patch.dict(os.environ, {"POST_DATE": "2026-10-29"}):
            day = self.daily.post_day()
        self.assertEqual((f"{day:%Y-%m-%d}", day.strftime("%d %b %Y")), ("2026-10-29", "29 Oct 2026"))

    def test_a_badly_written_date_stops_with_a_clear_message(self):
        with mock.patch.dict(os.environ, {"POST_DATE": "29/10/2026"}):
            with self.assertRaises(SystemExit) as stopped:
                self.daily.post_day()
        self.assertIn("2026-10-29", str(stopped.exception))


# =============================================================================================
# 8b. One whole day, with the real pieces chained together (the seams are where bugs hide)
# =============================================================================================

@unittest.skipUnless(yaml, "install PyYAML (pip install pyyaml) to test the workflow files")
class WholeDayStory(InTempFolder):
    def setUp(self):
        super().setUp()
        try:
            import daily
            import post_social
        except ImportError as problem:
            self.skipTest(f"needs the project tools installed: {problem}")
        self.daily, self.post_social = daily, post_social
        shutil.rmtree(self.folder)                                  # start with an empty results/ folder
        self.server.now = at("2000-01-01 00:00")                    # the pretend Buffer's clock: long ago

    def fake_scrape(self, name, folder=".", max_pages=None, progress=None):
        os.makedirs(folder, exist_ok=True)
        csv_path = os.path.join(folder, "quotes_fake.csv")
        with open(csv_path, "w") as f:
            f.write("quote,author,tags\nHello,Someone,x\n")
        return [{"quote": "Hello", "author": "Someone", "tags": "x"}], csv_path

    def fake_screenshot(self, url, path):
        from PIL import Image
        Image.new("RGB", (1280, 800), "white").save(path)

    def test_evening_run_to_the_next_morning_check(self):
        # 1. 18:17 UTC: GitHub's evening timer wakes the workflow, with Buffer switched on
        step = run_check_step({"EVENT_NAME": "schedule", "CRON": EVENING, "BUFFER_API_KEY": "k"})
        self.assertEqual((step["buffer"], step["post_when"], step["done"]), ("true", "next", "false"))
        post_date = step["post_date"]

        # 2. the robot scrapes (pretend) and makes the picture FOR THAT DAY
        github_output = os.path.join(self.tmp, "gh_output.txt")
        with mock.patch.dict(os.environ, {"POST_DATE": post_date, "GITHUB_OUTPUT": github_output}), \
                mock.patch.object(sys, "argv", ["daily.py"]), \
                mock.patch.object(self.daily, "pick_site", return_value="quotes"), \
                mock.patch.object(self.daily, "scrape", self.fake_scrape), \
                mock.patch.object(self.daily, "take_screenshot", self.fake_screenshot):
            self.quietly(self.daily.main)
        folder = f"results/{post_date}_quotes"
        for name in ("caption.txt", "post.jpg", "post.png", "data.csv"):
            self.assertTrue(os.path.exists(os.path.join(folder, name)), name)
        self.assertIn(f"## {datetime.strptime(post_date, '%Y-%m-%d'):%d %b %Y}", open("results/README.md").read())
        with open(github_output) as f:
            self.assertEqual(f.read().strip(), f"folder={folder}")

        # 3. the posting step: post_social.py hands over to buffer_post.py (pointed at the pretend Buffer)
        env = {"BUFFER_API_KEY": self.server.KEY, "POST_WHEN": step["post_when"], "POST_DATE": post_date,
               "DAILY_FOLDER": folder, "GITHUB_REPOSITORY": "vincent001100/web-scraper", "GITHUB_REF_NAME": "main"}
        real_class = bp.Buffer
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(bp, "Buffer", lambda key: real_class(key, api_url=self.server.url, sleep=self.sleeps.append)), \
                mock.patch.object(bp, "check_picture_is_public"):
            with self.assertRaises(SystemExit) as stopped:
                self.quietly(self.post_social.main)
        self.assertEqual(stopped.exception.code, 0)

        # 4. what Buffer was told
        self.assertEqual(len(self.server.created), 2)
        caption = open(os.path.join(folder, "caption.txt"), encoding="utf-8").read()
        for sent in self.server.created:
            self.assertEqual(sent["mode"], "customScheduled")
            self.assertEqual(sent["dueAt"], f"{post_date}T06:00:00.000Z")        # 07:00 Lagos on the post date
            self.assertEqual(sent["text"], caption)
            self.assertEqual(sent["assets"][0]["image"]["url"],
                             f"https://raw.githubusercontent.com/vincent001100/web-scraper/main/{folder}/post.jpg")
        self.assertTrue(os.path.exists(os.path.join(folder, bp.RECORD_FILE)))    # saved for the 'Save the Buffer record' step

        # 5. a second evening trigger (or a late Make.com press for the same day) now stops: no double post
        again = run_check_step({"EVENT_NAME": "schedule", "CRON": EVENING, "BUFFER_API_KEY": "k"},
                               folders=[f"{post_date}_quotes"])
        self.assertEqual(again["done"], "true")

        # 6. 06:41 UTC on the post date: the morning check asks Buffer and is happy
        self.server.status_script = {"post_1": ["sent"], "post_2": ["sent"]}
        _, printed = self.quietly(bp.run_check_today, env={"BUFFER_API_KEY": self.server.KEY},
                                  now=at(f"{post_date} 06:41"), buffer=self.client())
        self.assertIn("All of today's Buffer posts look fine", printed)

    def test_the_old_way_still_works_end_to_end_when_there_is_no_key(self):
        """No BUFFER_API_KEY: the check step says buffer=false, daily.py uses today's date, and the post goes to Make.com."""
        step = run_check_step({"EVENT_NAME": "workflow_dispatch", "FORCE": "false"})
        self.assertEqual(step, {"buffer": "false", "done": "false"})          # no post_date: daily.py uses today
        github_output = os.path.join(self.tmp, "gh_output.txt")
        with mock.patch.dict(os.environ, {"POST_DATE": "", "GITHUB_OUTPUT": github_output}), \
                mock.patch.object(sys, "argv", ["daily.py"]), \
                mock.patch.object(self.daily, "pick_site", return_value="quotes"), \
                mock.patch.object(self.daily, "scrape", self.fake_scrape), \
                mock.patch.object(self.daily, "take_screenshot", self.fake_screenshot):
            self.quietly(self.daily.main)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertTrue(os.path.exists(f"results/{today}_quotes/post.jpg"))
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("BUFFER_", "MAKE_"))}
        clean["MAKE_WEBHOOK_URL"] = "https://hook.example/abc"
        with mock.patch.dict(os.environ, clean, clear=True), \
                mock.patch.object(self.post_social.requests, "post") as fake_post:
            fake_post.return_value.text = "Accepted"
            self.quietly(self.post_social.main)
        self.assertEqual(fake_post.call_args.args[0], "https://hook.example/abc")
        self.assertEqual(fake_post.call_args.kwargs["json"]["title"], f"{today}_quotes")
        self.assertEqual(self.server.requests, [])                              # Buffer was never contacted


# =============================================================================================
# 9. The GitHub workflow itself (needs PyYAML: pip install pyyaml)
# =============================================================================================

EVENING = "17 18 * * *"          # the evening timer's text, as written in scrape.yml
CAN_RUN_GITHUB_SHELL = os.name != "nt" and shutil.which("bash") is not None


def load_workflow(name):
    with open(os.path.join(HERE, ".github", "workflows", name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_step_code():
    steps = load_workflow("scrape.yml")["jobs"]["check"]["steps"]
    return next(s for s in steps if s.get("id") == "today")


def run_check_step(env, folders=()):
    """Run the workflow's 'check' step (its shell code) exactly as GitHub would, in a scratch folder.
    Returns what the step reported, e.g. {'done': 'false', 'buffer': 'true', ...}."""
    if not CAN_RUN_GITHUB_SHELL:
        raise unittest.SkipTest("this runs GitHub's Linux shell code; it is checked on Linux and Mac only")
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(os.path.join(HERE, "buffer_post.py"), tmp)
        for folder in folders:
            os.makedirs(os.path.join(tmp, "results", folder))
        output = os.path.join(tmp, "github_output.txt")
        open(output, "w").close()
        run_env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": output}
        run_env.update(env)
        result = subprocess.run(["bash", "-e", "-c", check_step_code()["run"]], cwd=tmp, env=run_env,
                                capture_output=True, text=True)
        with open(output) as f:
            outputs = dict(line.split("=", 1) for line in f.read().splitlines() if "=" in line)
    if result.returncode != 0:
        raise AssertionError(f"the check step failed: {result.stderr}")
    return outputs


@unittest.skipUnless(yaml, "install PyYAML (pip install pyyaml) to test the workflow files")
class Workflows(unittest.TestCase):
    EVENING = EVENING

    @classmethod
    def load(cls, name):
        return load_workflow(name)

    def check_step(self):
        return check_step_code()

    def run_check(self, env, folders=()):
        return run_check_step(env, folders)

    @staticmethod
    def today():
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ---- Buffer OFF: must behave exactly like the old workflow ----
    def test_off_button_press_with_no_post_yet_goes_ahead_the_old_way(self):
        out = self.run_check({"EVENT_NAME": "workflow_dispatch", "FORCE": "false"})
        self.assertEqual(out, {"buffer": "false", "done": "false"})

    def test_off_button_press_after_todays_post_stops(self):
        out = self.run_check({"EVENT_NAME": "workflow_dispatch", "FORCE": "false"}, [f"{self.today()}_jobs"])
        self.assertEqual(out["done"], "true")

    def test_off_force_goes_ahead_even_if_todays_post_exists(self):
        out = self.run_check({"EVENT_NAME": "workflow_dispatch", "FORCE": "true"}, [f"{self.today()}_jobs"])
        self.assertEqual(out["done"], "false")

    def test_off_the_0623_backup_behaves_like_the_button(self):
        env = {"EVENT_NAME": "schedule", "CRON": "23 6 * * *"}
        self.assertEqual(self.run_check(env)["done"], "false")
        self.assertEqual(self.run_check(env, [f"{self.today()}_jobs"])["done"], "true")

    def test_off_the_evening_timer_does_nothing(self):
        out = self.run_check({"EVENT_NAME": "schedule", "CRON": self.EVENING})
        self.assertEqual(out, {"done": "true"})

    def test_off_a_blank_secret_counts_as_off(self):
        out = self.run_check({"EVENT_NAME": "schedule", "CRON": self.EVENING, "BUFFER_API_KEY": "  \n"})
        self.assertEqual(out, {"done": "true"})

    # ---- Buffer ON ----
    def test_on_evening_run_is_for_the_next_0700_lagos(self):
        expected = str(bp.decide_post_date(bp.now_utc(), "next"))
        out = self.run_check({"EVENT_NAME": "schedule", "CRON": self.EVENING, "BUFFER_API_KEY": "k"})
        self.assertEqual(out, {"buffer": "true", "post_when": "next", "post_date": expected, "done": "false"})

    def test_on_evening_run_stops_if_that_days_post_exists_already(self):
        expected = str(bp.decide_post_date(bp.now_utc(), "next"))
        out = self.run_check({"EVENT_NAME": "schedule", "CRON": self.EVENING, "BUFFER_API_KEY": "k"},
                             [f"{expected}_jobs"])
        self.assertEqual(out["done"], "true")

    def test_on_the_make_button_press_after_the_evening_run_does_not_post_twice(self):
        out = self.run_check({"EVENT_NAME": "workflow_dispatch", "FORCE": "false", "BUFFER_API_KEY": "k"},
                             [f"{self.today()}_jobs"])         # the evening run made today's folder
        self.assertEqual((out["post_when"], out["post_date"], out["done"]), ("today", self.today(), "true"))

    def test_on_a_button_press_with_no_post_yet_posts_today(self):
        out = self.run_check({"EVENT_NAME": "workflow_dispatch", "FORCE": "false", "BUFFER_API_KEY": "k"})
        self.assertEqual((out["post_when"], out["post_date"], out["done"]), ("today", self.today(), "false"))

    # ---- the file itself ----
    def test_the_evening_timer_text_matches_in_both_places(self):
        doc = self.load("scrape.yml")
        crons = [item["cron"] for item in (doc.get("on") or doc.get(True))["schedule"]]
        self.assertIn(self.EVENING, crons)
        self.assertIn("23 6 * * *", crons)                                  # the old backup is still there
        self.assertIn(f'"{self.EVENING}"', self.check_step()["run"])

    def test_the_posting_step_still_passes_the_old_secrets(self):
        steps = self.load("scrape.yml")["jobs"]["scrape"]["steps"]
        step = next(s for s in steps if s.get("name") == "Post to Facebook and Instagram")
        self.assertEqual(step["run"], "python post_social.py")
        for name in ("MAKE_WEBHOOK_URL", "META_PAGE_TOKEN", "FB_PAGE_ID", "IG_USER_ID", "BUFFER_API_KEY"):
            self.assertIn(name, step["env"])

    def test_the_manual_button_and_its_tickbox_still_exist(self):
        doc = self.load("scrape.yml")
        trigger = doc.get("on") or doc.get(True)
        self.assertIn("workflow_dispatch", trigger)
        self.assertEqual(trigger["workflow_dispatch"]["inputs"]["force"]["type"], "boolean")

    def test_no_secret_or_input_is_pasted_straight_into_shell_code(self):
        """Safer habit: values reach shell code through env:, never as ${{ ... }} inside run:."""
        for name in ("scrape.yml", "weekly-promo.yml", "buffer-tools.yml"):
            doc = self.load(name)
            for job in doc["jobs"].values():
                for step in job["steps"]:
                    self.assertNotIn("${{", step.get("run", ""), f"{name}: {step.get('name')}")

    def test_the_advert_workflow_passes_the_buffer_secret(self):
        step = next(s for s in self.load("weekly-promo.yml")["jobs"]["advert"]["steps"] if "env" in s)
        self.assertEqual(step["run"], "python post_promo.py")
        self.assertIn("BUFFER_API_KEY", step["env"])
        self.assertIn("MAKE_WEBHOOK_URL", step["env"])

    def record_step(self):
        steps = self.load("scrape.yml")["jobs"]["scrape"]["steps"]
        return next(s for s in steps if s.get("name") == "Save the Buffer record")

    def run_record_step(self, folder, env):
        return subprocess.run(["bash", "-e", "-c", self.record_step()["run"]], cwd=folder, env=env,
                              capture_output=True, text=True)

    def test_the_record_step_saves_only_record_files_never_half_made_results(self):
        if not (CAN_RUN_GITHUB_SHELL and shutil.which("git")):
            self.skipTest("needs bash and git (this step runs on GitHub's Linux machines)")
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": os.environ["PATH"], "HOME": tmp, "GIT_CONFIG_NOSYSTEM": "1", "POST_DATE": "2026-10-29"}
            me = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]

            def git(*args, cwd):
                return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                                      text=True).stdout

            def write(path, content="x"):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(content)

            origin, work, other = (os.path.join(tmp, name) for name in ("origin.git", "work", "other"))
            git("init", "--bare", origin, cwd=tmp)
            git("symbolic-ref", "HEAD", "refs/heads/main", cwd=origin)
            git("clone", origin, work, cwd=tmp)
            git("symbolic-ref", "HEAD", "refs/heads/main", cwd=work)
            write(os.path.join(work, "results", "2026-10-29_jobs", "caption.txt"))       # saved by the robot earlier
            git("add", ".", cwd=work)
            git(*me, "commit", "-m", "Daily data drop 2026-10-29", cwd=work)
            git("push", "-u", "origin", "main", cwd=work)
            git("clone", origin, other, cwd=tmp)                                          # meanwhile, another change
            write(os.path.join(other, "README.md"))
            git("add", ".", cwd=other)
            git(*me, "commit", "-m", "another change", cwd=other)
            git("push", cwd=other)

            write(os.path.join(work, "results", "2026-10-29_jobs", "buffer-posts.json"), "{}")   # after posting
            write(os.path.join(work, "results", "2026-10-30_half", "data.csv"))                 # a broken scrape

            result = self.run_record_step(work, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = git("ls-tree", "-r", "--name-only", "main", cwd=origin).split()
            self.assertIn("results/2026-10-29_jobs/buffer-posts.json", saved)
            self.assertIn("README.md", saved)                                   # the other change is kept
            self.assertNotIn("results/2026-10-30_half/data.csv", saved)         # the half-made folder is not

            again = self.run_record_step(work, env)                             # nothing new: says so, no error
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn("already saved", again.stdout)

    def test_the_record_step_does_nothing_when_there_is_no_record(self):
        if not CAN_RUN_GITHUB_SHELL:
            self.skipTest("needs bash (this step runs on GitHub's Linux machines)")
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "results", "2026-10-30_half"))
            result = self.run_record_step(tmp, {"PATH": os.environ["PATH"], "POST_DATE": "2026-10-30"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No Buffer record to save", result.stdout)

    def test_the_record_step_only_runs_when_buffer_is_on_and_posting_was_tried(self):
        condition = self.record_step()["if"]
        self.assertIn("always()", condition)
        self.assertIn("needs.check.outputs.buffer == 'true'", condition)
        self.assertIn("steps.post.outcome != 'skipped'", condition)

    def test_the_morning_check_workflow_exists_and_runs_the_check(self):
        doc = self.load("buffer-tools.yml")
        step = next(s for s in doc["jobs"]["buffer"]["steps"] if s.get("name") == "Run the chosen task")
        self.assertIn("python buffer_post.py check-today", step["run"])
        self.assertIn("python buffer_post.py channels", step["run"])
        self.assertIn("python buffer_post.py rehearsal", step["run"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
