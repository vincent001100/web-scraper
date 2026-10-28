"""
Post the Solvix picture and caption to Facebook and Instagram through Buffer (buffer.com).

WHY THIS FILE EXISTS
  Make.com's free plan only allows 2 active automations, and on 28 Oct 2026 it answered
  "Accepted" but posted nothing. Buffer's free plan has 3 channels, a free API, and it can
  publish at an exact time. (Meta's own developer route is closed to us: the phone check failed.)

HOW IT SWITCHES ON
  post_social.py (the daily post) and post_promo.py (the Monday advert) call this file ONLY when
  the GitHub secret BUFFER_API_KEY exists. No secret = nothing in here runs, Make.com works as before.

THE "EVENING BEFORE" IDEA
  GitHub's timer is often late (once by about 6 hours), so starting a job at 07:00 and hoping is
  fragile. Instead the robot runs the EVENING BEFORE (about 18:00 UTC), makes tomorrow's picture,
  and tells Buffer: "publish this at 06:00 UTC". Buffer keeps it and publishes on the dot.
    * 07:00 in Lagos is always 06:00 UTC (Nigeria has no summer time).
    * If 06:00 has already passed (a manual run at 09:00, say) we ask Buffer to post right away.
    * "Which day is this post FOR?" decides the results folder name, the date printed on the
      picture, and the "don't post twice in one day" check. A run tonight at 18:20 is for TOMORROW.

HOW IT TALKS TO BUFFER
  Buffer's API is a "GraphQL" API: ONE web address (https://api.buffer.com). Every request is a
  POST with the key in the header  Authorization: Bearer <key>  and a JSON body holding our
  question. The answer always comes back as JSON.

WHAT WE COULD NOT CHECK (written 28 Oct 2026)
  api.buffer.com and developers.buffer.com cannot be opened from the cloud session where this was
  written, so NOTHING here has been run against the real Buffer. The wording of the questions
  below comes from Buffer's public docs (as quoted by web search) and from other people's working
  code. The first real check is the "rehearsal" command (see BUFFER-SETUP.md). Buffer's API is in
  beta, so if Buffer changes something, section 2 (THE QUESTIONS) is the only place to fix.

COMMANDS (run in a terminal, in the project folder)
  python buffer_post.py daily --dry-run      show what would be sent; sends nothing; needs no key
  python buffer_post.py daily                post today's picture (what the GitHub robot runs)
  python buffer_post.py promo                post the Monday advert (right away)
  python buffer_post.py channels             list our Buffer channels (read-only, changes nothing)
  python buffer_post.py rehearsal            save 2 test DRAFTS in Buffer; publishes nothing
  python buffer_post.py check-today          did today's posts really go out? (red X if not)
  python buffer_post.py post-date next       print which date a post made right now is FOR
Practice at any time: add  --now 2026-10-28T18:20:00Z  to pretend it is that moment.
For local runs put BUFFER_API_KEY=... in a file called .env (it is never uploaded to GitHub).
"""
import argparse
import glob
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

# "requests" is imported inside the functions that need it, on purpose: the date helpers in this
# file are also run on GitHub's small "check" step, which has no extra tools installed.

API_URL = "https://api.buffer.com"      # Buffer's one and only address
RESULTS = "results"
RECORD_FILE = "buffer-posts.json"       # saved next to caption.txt: which Buffer posts we made
PROMO_FOLDER = "brand/promo"
PROMO_PICTURE = "automation-post.jpg"

POST_HOUR_UTC = 6                       # 07:00 Lagos = 06:00 UTC, all year round
MIN_LEAD = timedelta(minutes=3)         # a scheduled time must still be in the future when Buffer gets it
SERVICES = ("instagram", "facebook")    # Instagram first: it is the pickier one, so trouble shows up before anything is created
LABEL = {"instagram": "Instagram", "facebook": "Facebook"}
INSTAGRAM_MAX_CHARACTERS = 2200         # Instagram's own limits
INSTAGRAM_MAX_HASHTAGS = 30
WHEN_CHOICES = ("next", "today", "now")


# =============================================================================================
# 1. WHEN TO POST  (plain date maths; needs no internet)
# =============================================================================================

@dataclass(frozen=True)
class Plan:
    """The answer to 'when does this post go out?'"""
    mode: str            # "customScheduled" = at an exact time, "shareNow" = right away
    due_at: object       # the exact time (UTC) when mode is customScheduled, otherwise None
    post_date: object    # the day this post is FOR (also the start of its folder name in results/)


def now_utc():
    return datetime.now(timezone.utc)


def make_clock(pretend_now=None):
    """A clock for one run: the real time, or (for practice and tests) a pretend moment that stays put."""
    return (lambda: pretend_now) if pretend_now else now_utc


def target_time(day):
    """06:00 UTC (= 07:00 Lagos) on the given day."""
    return datetime(day.year, day.month, day.day, POST_HOUR_UTC, tzinfo=timezone.utc)


def decide_post_date(now, when):
    """Which day is a post that is made right now FOR?

    when = "next"   the evening run: aim for the NEXT 07:00 Lagos.
                    Tonight at 18:20 UTC that is tomorrow. If GitHub is so late that it only starts
                    after midnight, the next 07:00 is still today.
    when = "today"  a manual run, Make.com's 07:00 button press, or the 06:23 backup: today.
    when = "now"    post straight away: today.
    """
    if when not in WHEN_CHOICES:
        raise ValueError(f"'when' must be one of {WHEN_CHOICES}, not {when!r}")
    if when == "next" and not now + MIN_LEAD < target_time(now.date()):
        return now.date() + timedelta(days=1)    # today's 06:00 is too close or already gone
    return now.date()


def plan_for(post_date, now):
    """Given the day a post is FOR, choose how to send it.
    If that day's 06:00 UTC is still comfortably ahead, ask Buffer for that exact time.
    If not (it has passed, or it is only seconds away), ask Buffer to post right now."""
    target = target_time(post_date)
    if target > now + MIN_LEAD:
        return Plan("customScheduled", target, post_date)
    return Plan("shareNow", None, post_date)


def plan_now(now):
    """Post straight away (used for the Monday advert)."""
    return Plan("shareNow", None, now.date())


def buffer_time(moment):
    """How Buffer wants a time written: 2026-10-29T06:00:00.000Z (UTC)."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_buffer_time(text):
    """Read a time Buffer sent back. Returns None if there is none."""
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def human_time(moment):
    """For people: 'Thu 29 Oct 2026 06:00 UTC (07:00 Lagos)'."""
    if moment is None:
        return "an unknown time"
    moment = moment.astimezone(timezone.utc)
    lagos = moment + timedelta(hours=1)
    return f"{moment:%a %d %b %Y %H:%M} UTC ({lagos:%H:%M} Lagos)"


# =============================================================================================
# 2. THE QUESTIONS WE ASK BUFFER  (if Buffer changes its API, fix them here and nowhere else)
# =============================================================================================

# Who am I? Buffer calls an account an "organization".
ORGANIZATIONS_QUERY = "query { account { organizations { id name } } }"


def channels_query(organization_id, extras=True):
    """The channels (Facebook Page, Instagram account...) in one organization.
    'isQueuePaused' is a nice extra (we warn if a queue is paused); we drop it if Buffer objects."""
    fields = "id name service isQueuePaused" if extras else "id name service"
    return ("query { channels(input: { organizationId: " + json.dumps(organization_id) + " }) { "
            + fields + " } }")


# Create ONE post. $input carries the details (channel, text, time, picture) - see build_input().
# 'post { id dueAt }' and 'message' are exactly what Buffer's own examples ask for.
CREATE_POST = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id dueAt } }
    ... on MutationError { message }
  }
}
"""


def post_status_query(post_id, extras=True):
    """How is one post doing? (This is the least certain question - see the note at the top.)"""
    fields = "status dueAt sentAt externalLink error { message }" if extras else "status dueAt"
    return ("query { post(input: { id: " + json.dumps(post_id) + " }) { __typename ... on Post { "
            + fields + " } } }")


# Buffer insists on a post "type" for Facebook and Instagram (found in other people's working
# code; the docs we could open did not list it). A picture post is type "post".
POST_METADATA = {
    "facebook": {"facebook": {"type": "post"}},
    "instagram": {"instagram": {"type": "post", "shouldShareToFeed": True}},
}


def build_input(service, channel_id, caption, image_url, plan, draft=False):
    """The details for ONE post. Buffer wants the picture as a public web address, not a file."""
    post = {
        "channelId": channel_id,
        "text": caption,
        "schedulingType": "automatic",              # Buffer posts it itself (not just a reminder)
        "mode": plan.mode,
        "assets": [{"image": {"url": image_url}}],  # a list; each item holds exactly one picture
        "metadata": json.loads(json.dumps(POST_METADATA[service])),   # a private copy
    }
    if draft:
        # A draft is saved in Buffer but never published. Used only by the rehearsal.
        post["mode"] = "addToQueue"
        post["saveToDraft"] = True
    elif plan.mode == "customScheduled":
        post["dueAt"] = buffer_time(plan.due_at)
    return post


# =============================================================================================
# 3. TALKING TO BUFFER
# =============================================================================================

class BufferError(Exception):
    """Something went wrong. The message is written in plain English for boss.
    stop_everything: trying the next channel would be pointless (wrong key, no internet, limit hit).
    bad_question:    Buffer did not understand our question, i.e. its API probably changed."""

    def __init__(self, message, stop_everything=False, bad_question=False):
        super().__init__(message)
        self.stop_everything = stop_everything
        self.bad_question = bad_question


KEY_PROBLEM = (
    "Buffer did not accept the API key. Check: (1) the GitHub secret is called exactly "
    "BUFFER_API_KEY; (2) it holds the whole key and nothing else; (3) the key has not run out or "
    "been replaced (in Buffer: your picture, bottom left, then API; making a new key cancels the old "
    "one, so put the new key into the GitHub secret)."
)

# Words Buffer uses when the QUESTION itself is wrong (not our data)
SCHEMA_WORDS = re.compile(
    r"Cannot query field|Unknown argument|Unknown type|Unknown field|is not defined by type|"
    r"Variable \"[^\"]*\" of type|Fragment cannot be spread|Field \"[^\"]*\" of required type|"
    r"must have a selection of subfields|Expected type", re.IGNORECASE)


def parse_day(text):
    """'2026-10-29' -> a date. Stops with a clear message if it is not written like that."""
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise BufferError(f"A date must be written like 2026-10-29, but I got '{text}'.")


def parse_now(text):
    """For practice runs: '2026-10-28T18:20:00Z' (or '2026-10-28 18:20') -> a UTC time."""
    try:
        moment = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise BufferError(f"--now must be written like 2026-10-28T18:20:00Z, but I got '{text}'.")
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def seconds_to_wait(response):
    """How long Buffer wants us to wait (its Retry-After header); 10 seconds if it does not say."""
    try:
        return max(1, int(response.headers.get("Retry-After", 10)))
    except (TypeError, ValueError):
        return 10


class Buffer:
    """A small helper that sends questions to Buffer and understands the answers."""

    def __init__(self, api_key, api_url=API_URL, sleep=time.sleep):
        import requests   # imported here on purpose (see the note at the top)
        api_key = (api_key or "").strip()
        if not api_key:
            raise BufferError("BUFFER_API_KEY is not set. Add it as a GitHub secret "
                              "(Settings, Secrets and variables, Actions) - see BUFFER-SETUP.md.",
                              stop_everything=True)
        self.requests = requests
        self.api_key = api_key
        self.api_url = api_url
        self.sleep = sleep
        self.channel_extras = True     # we ask for nice-to-have fields until Buffer says it doesn't know them
        self.status_extras = True

    # ---- the one place where a request is really sent -------------------------------------
    def ask(self, query, variables=None, changes_something=False):
        """Send one question to Buffer and return the 'data' part of its answer.
        Any problem becomes a BufferError with a plain-English message.
        changes_something=True means 'this creates a post': then we never retry after an unclear
        failure, because that could post twice."""
        body = {"query": query}
        if variables:
            body["variables"] = variables
        unsure = (" Buffer may still have received the post, so look in Buffer (Content, then "
                  "Calendar) before running this again." if changes_something else "")

        for attempt in range(1, 4):
            try:
                response = self.requests.post(
                    self.api_url, json=body, timeout=30,
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "User-Agent": "solvix-robot (github.com/vincent001100/web-scraper)"})
            except self.requests.RequestException as problem:
                raise BufferError(f"Could not reach Buffer ({type(problem).__name__}). Either the "
                                  f"internet or Buffer is down.{unsure}", stop_everything=True)

            try:
                answer = response.json()
            except ValueError:
                answer = None
            errors = answer.get("errors") if isinstance(answer, dict) else None
            errors = [e for e in (errors or []) if isinstance(e, dict)]
            codes = {(e.get("extensions") or {}).get("code") for e in errors}
            messages = "; ".join(str(e.get("message")) for e in errors)

            # Too many requests: wait a little and try again (safe: Buffer did nothing)
            if response.status_code == 429 or "RATE_LIMIT_EXCEEDED" in codes:
                wait = seconds_to_wait(response)
                if attempt < 3 and wait <= 60:
                    say(f"Buffer asked us to slow down; waiting {wait} seconds.")
                    self.sleep(wait)
                    continue
                raise BufferError("Buffer says we have asked it too many times in a short while "
                                  f"(its limit). Try again in about {max(1, wait // 60)} minute(s).",
                                  stop_everything=True)
            if response.status_code in (401, 403) or codes & {"UNAUTHORIZED", "UNAUTHENTICATED", "FORBIDDEN"}:
                detail = ", ".join(sorted(c for c in codes if c))
                raise BufferError(f"{KEY_PROBLEM} (Buffer answered: HTTP {response.status_code}"
                                  f"{', ' + detail if detail else ''})", stop_everything=True)
            if response.status_code >= 500:
                raise BufferError(f"Buffer had a problem on its side (HTTP {response.status_code}).{unsure} "
                                  "Try again in a few minutes.", stop_everything=True)
            if answer is None:
                raise BufferError("Buffer sent back something we could not read "
                                  f"(HTTP {response.status_code}).{unsure}", stop_everything=True)
            if errors:
                if "GRAPHQL_VALIDATION_FAILED" in codes or SCHEMA_WORDS.search(messages):
                    raise BufferError("Buffer did not understand our request, which usually means its API "
                                      f"changed (it is still in beta). Buffer said: {messages}",
                                      bad_question=True)
                raise BufferError(f"Buffer refused the request: {messages}")
            if response.status_code >= 400:
                raise BufferError(f"Buffer answered with an error (HTTP {response.status_code}).")
            return answer.get("data") or {}
        raise BufferError("Buffer kept asking us to slow down.", stop_everything=True)

    # ---- the questions, one method each ---------------------------------------------------
    def channels(self):
        """Every channel this key can post to, as a list of dicts: id, name, service, paused."""
        data = self.ask(ORGANIZATIONS_QUERY)
        organizations = ((data.get("account") or {}).get("organizations")) or []
        if not organizations:
            raise BufferError("Buffer did not list any organization for this key. Make sure the key "
                              "was created in the Buffer account that has the channels.")
        found = []
        for organization in organizations:
            try:
                data = self.ask(channels_query(organization["id"], extras=self.channel_extras))
            except BufferError as problem:
                if not (problem.bad_question and self.channel_extras):
                    raise
                self.channel_extras = False
                data = self.ask(channels_query(organization["id"], extras=False))
            for channel in data.get("channels") or []:
                found.append({
                    "id": channel.get("id"),
                    "name": channel.get("name") or "(no name)",
                    "service": str(channel.get("service") or "").lower(),
                    "paused": bool(channel.get("isQueuePaused")),
                })
        return found

    def create_post(self, post_input):
        """Create one post in Buffer. Returns {'id':..., 'dueAt':...}."""
        data = self.ask(CREATE_POST, {"input": post_input}, changes_something=True)
        result = data.get("createPost") or {}
        post = result.get("post")
        if post and post.get("id"):
            return post
        reason = result.get("message") or f"it answered with '{result.get('__typename') or 'something unexpected'}'"
        raise BufferError(f"Buffer would not create the post: {reason}")

    def post_status(self, post_id):
        """How is a post doing? Returns a dict: status (lowercase), due_at, sent_at, link, problem."""
        try:
            data = self.ask(post_status_query(post_id, extras=self.status_extras))
        except BufferError as problem:
            if not (problem.bad_question and self.status_extras):
                raise
            self.status_extras = False
            data = self.ask(post_status_query(post_id, extras=False))
        post = data.get("post") or {}
        if "status" not in post:
            raise BufferError(f"Buffer did not tell us the status of post {post_id} "
                              f"(it answered with '{post.get('__typename') or 'nothing'}'). "
                              "If that means the channel must be reconnected, reconnect it in Buffer.")
        error = post.get("error")
        return {
            "status": str(post.get("status") or "").lower(),
            "due_at": parse_buffer_time(post.get("dueAt")),
            "sent_at": parse_buffer_time(post.get("sentAt")),
            "link": post.get("externalLink"),
            "problem": error.get("message") if isinstance(error, dict) else None,
        }


# =============================================================================================
# 4. CHECKS BEFORE WE SEND ANYTHING
# =============================================================================================

def pick_channels(channels, wanted_ids=None):
    """Choose the Instagram and Facebook channel. Returns {'instagram': channel, 'facebook': channel}.
    If the account has two Facebook channels (or two Instagram), boss must name the right one with the
    GitHub secret BUFFER_FACEBOOK_CHANNEL_ID / BUFFER_INSTAGRAM_CHANNEL_ID."""
    wanted_ids = wanted_ids or {}
    chosen = {}
    for service in SERVICES:
        label = LABEL[service]
        secret = f"BUFFER_{service.upper()}_CHANNEL_ID"
        matches = [c for c in channels if c["service"] == service]
        wanted = (wanted_ids.get(service) or "").strip()
        if wanted:
            matches = [c for c in matches if c["id"] == wanted]
            if not matches:
                raise BufferError(f"The secret {secret} is '{wanted}', but that is not one of the "
                                  f"{label} channels Buffer shows for this key. Run the 'Buffer tools' "
                                  "workflow with list-channels to see the right ids, or delete the secret.")
        if not matches:
            seen = ", ".join(f"{c['service']} '{c['name']}'" for c in channels) or "none"
            raise BufferError(f"Buffer has no {label} channel for this key. In Buffer, connect your "
                              f"{label} account, then run this again. Channels Buffer can see: {seen}.")
        if len(matches) > 1:
            names = ", ".join(f"'{c['name']}' (id {c['id']})" for c in matches)
            raise BufferError(f"Buffer has {len(matches)} {label} channels: {names}. I will not guess. "
                              f"Add a GitHub secret called {secret} holding the id of the right one.")
        chosen[service] = matches[0]
    return chosen


def check_caption(caption):
    """Catch caption problems here, in plain English, instead of a confusing Instagram refusal later."""
    if not caption.strip():
        raise BufferError("The caption is empty, so I will not post.")
    if len(caption) > INSTAGRAM_MAX_CHARACTERS:
        raise BufferError(f"The caption is {len(caption)} characters long, but Instagram allows at most "
                          f"{INSTAGRAM_MAX_CHARACTERS}. Shorten the caption.")
    hashtags = len(re.findall(r"#\w+", caption))
    if hashtags > INSTAGRAM_MAX_HASHTAGS:
        raise BufferError(f"The caption has {hashtags} hashtags, but Instagram allows at most "
                          f"{INSTAGRAM_MAX_HASHTAGS}.")


def check_picture_is_public(image_url, sleep=time.sleep, tries=6):
    """Buffer fetches the picture from this web address by itself, so it must open with no login.
    Right after we upload to GitHub it can take a moment to appear, so we try a few times."""
    import requests
    last = "no answer"
    for attempt in range(tries):
        try:
            response = requests.get(image_url, stream=True, timeout=20)
            kind = response.headers.get("Content-Type", "")
            start = next(response.iter_content(8), b"") if response.status_code == 200 else b""
            response.close()
            # A picture says so in its type, or starts with the secret first bytes of a JPEG / PNG file.
            # (A login page or an error page is neither.)
            if response.status_code == 200 and (kind.startswith("image/") or start[:3] == b"\xff\xd8\xff"
                                                or start[:4] == b"\x89PNG"):
                say(f"Checked: the picture opens for anyone ({kind or 'a picture'}).")
                return
            last = f"HTTP {response.status_code}, content type '{kind or 'unknown'}'"
        except requests.RequestException as problem:
            last = type(problem).__name__
        if attempt < tries - 1:
            sleep(5)
    raise BufferError(f"Buffer could not fetch the picture, so I have not posted. {image_url} does not "
                      f"open as a picture for the public ({last}). Is the picture saved on GitHub, and "
                      "is the project public?")


def build_image_url(env, folder, filename):
    """The public address of a picture saved on GitHub (same style the Make.com path uses)."""
    repo = env.get("GITHUB_REPOSITORY") or "vincent001100/web-scraper"
    branch = env.get("GITHUB_REF_NAME") or "main"
    path = quote(f"{folder}/{filename}".replace(os.sep, "/"))
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def find_folder(post_date, newest_is_ok=False):
    """The results folder for a given day, e.g. results/2026-10-29_jobs."""
    matches = sorted(glob.glob(os.path.join(RESULTS, f"{post_date:%Y-%m-%d}_*")))
    matches = [m for m in matches if os.path.isdir(m)]
    if matches:
        return matches[-1]
    if newest_is_ok:   # only for practice runs: show the newest folder instead
        every = sorted(f for f in glob.glob(os.path.join(RESULTS, "*_*")) if os.path.isdir(f))
        if every:
            say(f"(Practice: there is no folder for {post_date} yet, so I am showing the newest one.)")
            return every[-1]
    raise BufferError(f"There is no folder for {post_date} in {RESULTS}/. The picture and caption must be "
                      "made first (python daily.py).")


# =============================================================================================
# 5. CREATING THE POSTS AND CHECKING WHAT BUFFER SAYS
# =============================================================================================

def say(text):
    print(text, flush=True)


def escape_annotation(text):
    """GitHub shows lines starting with ::error:: / ::warning:: prominently; newlines must be escaped."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def warn(text):
    say(f"WARNING: {text}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        say(f"::warning title=Buffer::{escape_annotation(text)}")


def report_failure(text):
    print(f"\nBUFFER POST FAILED\n{text}\n", file=sys.stderr, flush=True)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        say(f"::error title=Buffer post failed::{escape_annotation(text)}")


def write_summary(text):
    """On GitHub, also put a short note on the run page (handy on a phone)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def judge(info, now):
    """Turn Buffer's status into (verdict, sentence).
    verdict: 'ok' (published), 'waiting' (on its way), 'late' (should be out already), 'bad' (a problem)."""
    status = info["status"]
    if status == "sent":
        return "ok", "published" + (f" ({info['link']})" if info.get("link") else "")
    if status == "error":
        reason = f": {info['problem']}" if info.get("problem") else ""
        return "bad", f"Buffer could not publish it{reason}"
    if status in ("scheduled", "sending"):
        due = info.get("due_at")
        if due is None or due > now:
            if status == "sending":
                return "waiting", "Buffer is sending it"
            return "waiting", "scheduled" + (f", goes out at {human_time(due)}" if due else "")
        return "late", f"still '{status}', but it was due at {human_time(due)}"
    return "bad", f"Buffer shows the status '{status}', which is not what we expect"


def wait_for_publication(buffer, post_id, tries=18, pause=5):
    """After 'post right now', watch for up to ~90 seconds until Buffer says sent or error."""
    info = buffer.post_status(post_id)
    for _ in range(tries):
        if info["status"] not in ("scheduled", "sending"):
            break
        buffer.sleep(pause)
        info = buffer.post_status(post_id)
    return info


def read_record_posts(folder):
    """The posts an earlier run already wrote down in this folder (an empty list if none)."""
    path = os.path.join(folder or "", RECORD_FILE)
    if folder and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return list(json.load(f).get("posts", []))
        except (OSError, ValueError, AttributeError):
            warn(f"I could not read {path}; it will be written again.")
    return []


def save_record(folder, plan, posts, now):
    """Write down which Buffer posts we made, next to caption.txt. The morning check reads it,
    and so does the 'never post the same day twice' guard. `posts` is everything for this folder."""
    if not folder:
        return
    record = {
        "post_date": f"{plan.post_date:%Y-%m-%d}",
        "mode": plan.mode,
        "due_at": buffer_time(plan.due_at) if plan.due_at else None,
        "created_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "posts": posts,
    }
    with open(os.path.join(folder, RECORD_FILE), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
        f.write("\n")


def load_records(day):
    """All the Buffer records saved for one day: a list of (folder, record)."""
    found = []
    for folder in sorted(glob.glob(os.path.join(RESULTS, f"{day:%Y-%m-%d}_*"))):
        path = os.path.join(folder, RECORD_FILE)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    found.append((folder, json.load(f)))
            except (OSError, ValueError):
                warn(f"I could not read {path}.")
    return found


def already_handed_over(day):
    """Channels that already have a Buffer post for this day (from earlier runs): {service: (folder, post id)}.
    This is what stops 'Re-run failed jobs' from posting the same day twice."""
    done = {}
    for folder, record in load_records(day):
        for item in record.get("posts", []):
            done.setdefault(item.get("service"), (folder, item.get("post_id")))
    return done


def schedule_posts(buffer, targets, caption, image_url, plan, folder=None, clock=now_utc, draft=False, skip=None):
    """Create the Instagram and Facebook posts in Buffer, then ask Buffer how each one is doing.
    Raises BufferError (so GitHub shows a red X) if anything is wrong - but only after trying every
    channel, so one broken channel does not stop the other from posting.
    skip: {service: (folder, post id)} for channels that already have this day's post."""
    created, failed = [], []
    skip = skip or {}
    earlier = read_record_posts(folder)      # posts a previous run already made for this folder

    for service in SERVICES:
        channel = targets[service]
        label = LABEL[service]
        if service in skip:
            say(f"{label}: already handed to Buffer for {plan.post_date} "
                f"(post id {skip[service][1]}, from {skip[service][0]}), so I am not posting it again.")
            continue
        try:
            post = buffer.create_post(build_input(service, channel["id"], caption, image_url, plan, draft))
        except BufferError as problem:
            failed.append((label, str(problem)))
            if problem.stop_everything:
                break
            continue
        created.append({"service": service, "channel_id": channel["id"],
                        "channel_name": channel["name"], "post_id": post["id"]})
        save_record(folder, plan, earlier + created, clock())    # saved after every success, so nothing is lost
        when = "saved as a draft" if draft else (f"to go out at {human_time(plan.due_at)}" if plan.due_at else "to post right now")
        say(f"OK: {label} post created in Buffer, {when} (post id {post['id']}).")
        given = parse_buffer_time(post.get("dueAt"))
        if plan.due_at and not draft and given and abs((given - plan.due_at).total_seconds()) > 60:
            warn(f"{label}: we asked Buffer for {human_time(plan.due_at)}, but it set {human_time(given)}.")

    # Ask Buffer how each new post is doing. If we cannot read the answer that is only a warning:
    # the post itself is already safe in Buffer, and the morning check will look again.
    for item in created:
        label = LABEL[item["service"]]
        try:
            if plan.mode == "shareNow" and not draft:
                info = wait_for_publication(buffer, item["post_id"])
            else:
                info = buffer.post_status(item["post_id"])
        except BufferError as problem:
            if draft:
                failed.append((label, f"The test draft was created, but I could not read its status ({problem}) "
                                      "Check in Buffer that it is a draft, then delete it."))
            else:
                warn(f"{label}: the post was created, but I could not read its status ({problem}).")
            continue
        if draft:
            if info["status"] == "draft":
                say(f"Buffer says the {label} post is a draft (not published). Good.")
            else:
                failed.append((label, f"This was meant to be a draft but Buffer says '{info['status']}'. "
                                      f"Open Buffer and delete the {label} test post (post id {item['post_id']}) now."))
            continue
        verdict, sentence = judge(info, clock())
        if verdict == "bad":
            failed.append((label, sentence))
        elif verdict == "late":
            warn(f"{label}: {sentence}. Watch Buffer.")
        else:
            say(f"Buffer says {label}: {sentence}.")

    if failed:
        lines = [f"{label}: {why}" for label, why in failed]
        failed_labels = {label for label, _ in failed}
        fine = " and ".join(LABEL[i["service"]] for i in created if LABEL[i["service"]] not in failed_labels)
        if draft and created:
            done = " and ".join(LABEL[i["service"]] for i in created)
            lines.append(f"Test drafts already created in Buffer: {done}. Delete them in Buffer.")
        elif fine:
            where = f"picture {image_url}" + (f", caption in {folder}/caption.txt" if folder else "")
            lines.append(f"Already created in Buffer: {fine}. Add the missing post by hand in Buffer ({where}). "
                         f"Do not tick 'Post again' for this day, or {fine} would get it twice.")
        raise BufferError("\n".join(lines))
    return created


# =============================================================================================
# 6. THE COMMANDS
# =============================================================================================

def read_text(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        raise BufferError(f"I cannot find the {what} ({path}).")


def channel_ids_from(env):
    """Optional GitHub secrets that say exactly which channel to use."""
    return {"facebook": env.get("BUFFER_FACEBOOK_CHANNEL_ID", ""),
            "instagram": env.get("BUFFER_INSTAGRAM_CHANNEL_ID", "")}


def show_dry_run(plan, folder, image_url, caption, wanted, draft=False):
    """Print exactly what would be sent. No internet, no key needed."""
    say("DRY RUN: nothing is sent to Buffer.")
    say(f"  Post is for : {plan.post_date}")
    if draft:
        say("  When        : saved as a draft (never published)")
    elif plan.mode == "customScheduled":
        say(f"  When        : {human_time(plan.due_at)} (Buffer holds it until then)")
    else:
        say("  When        : right now (the 07:00 slot is over or too close)")
    say(f"  Folder      : {folder}")
    say(f"  Picture     : {image_url}")
    first_line = caption.strip().splitlines()[0][:70].encode("ascii", "replace").decode()
    say(f"  Caption     : {len(caption)} characters; first line: {first_line}")
    say("  Channels    : the Instagram and Facebook channels Buffer lists (looked up when it runs for real)")
    for service in SERVICES:
        channel_id = wanted[service].strip() or f"<{LABEL[service]} channel id, looked up in Buffer>"
        say(f"\n  What would be sent to Buffer for {LABEL[service]}:")
        say(json.dumps(build_input(service, channel_id, caption, image_url, plan, draft), indent=4))


def run_daily(env=None, now=None, buffer=None, dry_run=False, when=None, folder=None, image_url=None):
    """Post today's picture and caption (folder: results/<date>_<site>/). See the top of the file."""
    env = os.environ if env is None else env
    clock = make_clock(now)
    now = clock()
    when = when or env.get("POST_WHEN") or "today"
    if when not in WHEN_CHOICES:
        raise BufferError(f"POST_WHEN must be one of {WHEN_CHOICES}, not '{when}'.")
    forced_date = (env.get("POST_DATE") or "").strip()
    post_date = parse_day(forced_date) if forced_date else decide_post_date(now, when)
    plan = Plan("shareNow", None, post_date) if when == "now" else plan_for(post_date, now)

    folder = folder or (env.get("DAILY_FOLDER") or "").strip() or find_folder(post_date, newest_is_ok=dry_run)
    caption = read_text(os.path.join(folder, "caption.txt"), "caption")
    check_caption(caption)
    if not os.path.exists(os.path.join(folder, "post.jpg")):
        raise BufferError(f"{folder}/post.jpg is missing. Instagram needs the JPEG picture.")
    image_url = image_url or build_image_url(env, folder, "post.jpg")
    wanted = channel_ids_from(env)

    if dry_run:
        show_dry_run(plan, folder, image_url, caption, wanted)
        return []

    say(f"Post for {plan.post_date}: " + (f"scheduled for {human_time(plan.due_at)}" if plan.due_at else "right now"))
    say(f"Folder: {folder}")
    say(f"Picture: {image_url}")
    forced = (env.get("FORCE_POST") or "").strip().lower() == "true"    # the 'Post again' tick-box
    skip = {} if forced else already_handed_over(plan.post_date)

    buffer = buffer or Buffer(env.get("BUFFER_API_KEY"))
    check_picture_is_public(image_url, sleep=buffer.sleep)
    targets = pick_channels(buffer.channels(), wanted)
    for service in SERVICES:
        say(f"Using {LABEL[service]} channel '{targets[service]['name']}' (id {targets[service]['id']}).")
        if targets[service]["paused"]:
            warn(f"The {LABEL[service]} queue in Buffer is PAUSED. Posts may not go out until you resume it in Buffer.")
    created = schedule_posts(buffer, targets, caption, image_url, plan, folder=folder, clock=clock, skip=skip)

    when_text = f"at {human_time(plan.due_at)}" if plan.due_at else "right now"
    if created:
        say(f"DONE: {len(created)} post(s) handed to Buffer, to go out {when_text}.")
        write_summary(f"### Buffer: {len(created)} post(s) created for {plan.post_date}\n"
                      f"Going out {when_text}. Folder `{folder}`.")
    else:
        say(f"DONE: nothing new to post - both channels already have a post for {plan.post_date}.")
    return created


def run_promo(env=None, now=None, buffer=None, dry_run=False, image_url=None):
    """Post the Monday advert (brand/promo) right away."""
    env = os.environ if env is None else env
    clock = make_clock(now)
    plan = plan_now(clock())
    caption = read_text(os.path.join(PROMO_FOLDER, "caption.txt"), "advert caption")
    check_caption(caption)
    if not os.path.exists(os.path.join(PROMO_FOLDER, PROMO_PICTURE)):
        raise BufferError(f"{PROMO_FOLDER}/{PROMO_PICTURE} is missing.")
    image_url = image_url or build_image_url(env, PROMO_FOLDER, PROMO_PICTURE)
    wanted = channel_ids_from(env)

    if dry_run:
        show_dry_run(plan, PROMO_FOLDER, image_url, caption, wanted)
        return []

    say(f"Advert: posting right now. Picture: {image_url}")
    buffer = buffer or Buffer(env.get("BUFFER_API_KEY"))
    check_picture_is_public(image_url, sleep=buffer.sleep)
    targets = pick_channels(buffer.channels(), wanted)
    created = schedule_posts(buffer, targets, caption, image_url, plan, folder=None, clock=clock)
    say(f"DONE: the advert was handed to Buffer on {len(created)} channels.")
    return created


def run_channels(env=None, buffer=None):
    """List the channels Buffer shows for our key, and say which ones the daily post would use."""
    env = os.environ if env is None else env
    buffer = buffer or Buffer(env.get("BUFFER_API_KEY"))
    channels = buffer.channels()
    say("Channels Buffer shows for this key:")
    for c in channels:
        say(f"  - {c['service']:<10} '{c['name']}'   id {c['id']}" + ("   (queue PAUSED)" if c["paused"] else ""))
    if not channels:
        say("  (none - connect your Facebook Page and Instagram in Buffer first)")
    targets = pick_channels(channels, channel_ids_from(env))    # raises a clear message if it cannot choose
    say("The daily post would go to:")
    for service in SERVICES:
        say(f"  {LABEL[service]:<10} -> '{targets[service]['name']}'")
    return channels


def run_rehearsal(env=None, now=None, buffer=None, dry_run=False, image_url=None):
    """A safe practice: save a test DRAFT on each channel. Drafts are never published."""
    env = os.environ if env is None else env
    clock = make_clock(now)
    plan = plan_now(clock())
    caption = "Solvix test draft. Please ignore and delete."
    image_url = image_url or build_image_url(env, PROMO_FOLDER, PROMO_PICTURE)
    wanted = channel_ids_from(env)
    if dry_run:
        show_dry_run(plan, "(rehearsal)", image_url, caption, wanted, draft=True)
        return []
    buffer = buffer or Buffer(env.get("BUFFER_API_KEY"))
    check_picture_is_public(image_url, sleep=buffer.sleep)
    targets = pick_channels(buffer.channels(), wanted)
    created = schedule_posts(buffer, targets, caption, image_url, plan, folder=None, clock=clock, draft=True)
    say(f"REHEARSAL OK: {len(created)} test draft(s) are now in Buffer. Nothing was published. "
        "Open Buffer and delete the drafts.")
    return created


def run_check_today(env=None, now=None, buffer=None, tries=6, pause=20):
    """Did today's posts really go out? Raises BufferError (red X) if Buffer says they did not."""
    env = os.environ if env is None else env
    clock = make_clock(now)
    today = clock().date()
    if not (env.get("BUFFER_API_KEY") or "").strip():
        say("Buffer is not switched on (there is no BUFFER_API_KEY secret), so there is nothing to check.")
        return
    folders = [f for f in glob.glob(os.path.join(RESULTS, f"{today:%Y-%m-%d}_*")) if os.path.isdir(f)]
    if not folders:
        raise BufferError(f"There is no post for {today} in the results folder yet (checked at "
                          f"{clock():%H:%M} UTC), so nothing went out at 07:00 Lagos. If a later 'Daily data drop' "
                          "run posts it, all is well; otherwise look at those runs in the Actions tab.")
    records = load_records(today)
    if not records:
        say(f"Today's post ({today}) has no Buffer record, so it went out the old way (Make.com). "
            "Nothing to check here.")
        return

    buffer = buffer or Buffer(env.get("BUFFER_API_KEY"))
    problems = []
    for folder, record in records:
        for item in record.get("posts", []):
            label = LABEL.get(item.get("service"), item.get("service"))
            try:
                info = buffer.post_status(item["post_id"])
                verdict, sentence = judge(info, clock())
                for _ in range(tries):             # a post that is a little late gets a few minutes
                    if verdict != "late":
                        break
                    buffer.sleep(pause)
                    info = buffer.post_status(item["post_id"])
                    verdict, sentence = judge(info, clock())
            except BufferError as problem:
                problems.append(f"{label}: could not check - {problem}"
                                + (" Tell the Builders." if problem.bad_question else ""))
                continue
            say(f"{label} ({folder}): {sentence}.")
            if verdict in ("bad", "late"):
                problems.append(f"{label}: {sentence}.")
    if problems:
        raise BufferError("Today's Buffer post needs a look:\n" + "\n".join(problems)
                          + "\nOpen Buffer (Content, then Calendar) to see whether it went out; fix it or post by hand.")
    say("All of today's Buffer posts look fine.")


# =============================================================================================
# 7. THE COMMAND LINE
# =============================================================================================

def load_env_file(path):
    """Local use only: read KEY=VALUE lines from a .env file (it is in .gitignore, never uploaded)."""
    if not path or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="buffer_post.py", description="Post to Facebook and Instagram through Buffer.")
    commands = parser.add_subparsers(dest="command", required=True)

    def add_common(sub, dry=True):
        if dry:
            sub.add_argument("--dry-run", action="store_true", help="show what would be sent; send nothing")
        sub.add_argument("--now", help="pretend it is this UTC time, e.g. 2026-10-28T18:20:00Z (practice)")

    daily = commands.add_parser("daily", help="post today's picture and caption")
    daily.add_argument("--when", choices=WHEN_CHOICES,
                       help="next = the evening run (aim for the next 07:00 Lagos); "
                            "today = a manual or morning run; now = post straight away")
    daily.add_argument("--folder", help="use this results folder instead of looking for one")
    add_common(daily)
    add_common(commands.add_parser("promo", help="post the Monday advert right away"))
    commands.add_parser("channels", help="list the channels Buffer shows for our key (changes nothing)")
    add_common(commands.add_parser("rehearsal", help="save test DRAFTS in Buffer (nothing is published)"))
    add_common(commands.add_parser("check-today", help="did today's posts go out?"), dry=False)
    date_cmd = commands.add_parser("post-date", help="print which date a post made now is FOR")
    date_cmd.add_argument("when", choices=WHEN_CHOICES)
    add_common(date_cmd, dry=False)
    return parser


def main(argv=None, env_file=".env"):
    """Run one command. Returns 0 when all is well and 1 on any problem (GitHub then shows a red X)."""
    args = build_parser().parse_args(argv)
    load_env_file(env_file)
    try:
        now = parse_now(args.now) if getattr(args, "now", None) else None
        if args.command == "post-date":
            print(decide_post_date(now or now_utc(), args.when))
        elif args.command == "daily":
            run_daily(now=now, dry_run=args.dry_run, when=args.when, folder=args.folder)
        elif args.command == "promo":
            run_promo(now=now, dry_run=args.dry_run)
        elif args.command == "channels":
            run_channels()
        elif args.command == "rehearsal":
            run_rehearsal(now=now, dry_run=args.dry_run)
        elif args.command == "check-today":
            run_check_today(now=now)
        return 0
    except BufferError as problem:
        report_failure(str(problem))
        return 1
    except Exception as problem:     # a bug or something nobody expected: still a red X, still in plain words
        traceback.print_exc()
        report_failure("Something unexpected went wrong inside the Buffer robot "
                       f"({type(problem).__name__}: {problem}). Show this to the Builders.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
