"""Pet Shelf pictures without the PC (boss, 13 Nov 2026).
Asks Google's Gemini service (the same GEMINI_API_KEY the posting robot uses, no login to anyone's account)
to draw one product picture per id, from the team's written prompts in pet_shelf_picture_prompts.md.
Pictures are saved on the pet-shelf-media branch in pictures/<date>-<run>/ for the team to check
before anything goes on the shop. It never posts, never changes the shop, never reads Amazon.
From the phone: Actions, Pet Shelf pictures, Run workflow."""
import base64
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

import pet_shelf_order as robot
from buffer_post import say, write_summary

BASE = "https://generativelanguage.googleapis.com/v1beta"
PROMPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet_shelf_picture_prompts.md")


def load_prompts(path=PROMPTS):
    """id -> full prompt (description + the shared suffix line)."""
    text = open(path, encoding="utf-8").read()
    suffix = (re.search(r'Suffix on every prompt:\s*"([^"]+)"', text) or [None, ""])[1]
    prompts = {}
    for line in text.splitlines():
        if "|" in line and not line.startswith("#"):
            pid, desc = line.split("|", 1)
            prompts[pid.strip()] = f"Create an image: {desc.strip()}. {suffix}".strip()
    return prompts


def image_models(key, get=requests.get):
    """The picture-making models this key can use, best guess first. Asks Google, so new names are found."""
    names, page = [], ""
    for _ in range(5):
        r = get(f"{BASE}/models", params={"pageSize": 200, "pageToken": page}, headers={"x-goog-api-key": key}, timeout=30)
        if r.status_code != 200:
            raise SystemExit(f"Google did not list the models (HTTP {r.status_code}). Check the GEMINI_API_KEY secret.")
        data = r.json()
        for m in data.get("models", []):
            name = m["name"].split("/")[-1]; ways = m.get("supportedGenerationMethods", [])
            if "imagen" in name and "predict" in ways:
                names.append(("predict", name))
            elif "image" in name and "generateContent" in ways and "embed" not in name:
                names.append(("generate", name))
        page = data.get("nextPageToken") or ""
        if not page:
            break
    rank = lambda m: (0 if m[0] == "generate" else 1, "preview" in m[1], m[1])
    return sorted(set(names), key=rank)


def draw(prompt, key, models, post=requests.post):
    """PNG/JPEG bytes and the model's name, or (None, reason)."""
    last = "no picture model available for this key"
    for way, name in models:
        try:
            if way == "generate":
                body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}
                r = post(f"{BASE}/models/{name}:generateContent", json=body, headers={"x-goog-api-key": key}, timeout=180)
                if r.status_code == 200:
                    for part in r.json()["candidates"][0]["content"]["parts"]:
                        data = part.get("inlineData") or part.get("inline_data")
                        if data and data.get("data"):
                            return base64.b64decode(data["data"]), name
                    last = f"{name}: answered without a picture"
                    continue
            else:
                body = {"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1, "aspectRatio": "1:1"}}
                r = post(f"{BASE}/models/{name}:predict", json=body, headers={"x-goog-api-key": key}, timeout=180)
                if r.status_code == 200:
                    pred = (r.json().get("predictions") or [{}])[0]
                    if pred.get("bytesBase64Encoded"):
                        return base64.b64decode(pred["bytesBase64Encoded"]), name
                    last = f"{name}: answered without a picture"
                    continue
            msg = ""
            try:
                msg = r.json().get("error", {}).get("message", "")[:160]
            except ValueError:
                pass
            last = f"{name}: HTTP {r.status_code} {msg}"
        except (requests.RequestException, KeyError, IndexError, ValueError) as problem:
            last = f"{name}: {type(problem).__name__}"
    return None, last


def main():
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    prompts = load_prompts()
    wanted = [w for w in re.split(r"[,\s]+", os.environ.get("PICTURE_IDS", "")) if w]
    unknown = [w for w in wanted if w not in prompts]
    if not wanted or unknown:
        robot.fail_message(f"Give product ids from pet_shelf_picture_prompts.md. Unknown: {unknown or 'none given'}"); return 1
    models = image_models(key) if key else []
    say("Picture models this key can use: " + (", ".join(n for _, n in models) or "none"))
    robot.open_media_branch()
    folder = f"pictures/{datetime.now(timezone.utc):%Y-%m-%d}-{os.environ.get('GITHUB_RUN_ID', 'local')}"
    os.makedirs(os.path.join(robot.MEDIA_DIR, folder), exist_ok=True)
    done, failed = [], []
    for pid in wanted[:12]:
        data, who = draw(prompts[pid], key, models)
        if not data:
            # Free fallback: Cloudflare's picture service (same keys the order robot uses). Lower quality, check it.
            picture, why = robot.draw_cloudflare_picture(prompts[pid].replace("Create an image: ", ""),
                                                         os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN"))
            if picture is not None:
                import io
                buf = io.BytesIO(); picture.save(buf, "JPEG", quality=92); data = buf.getvalue()
                who = f"{robot.CLOUDFLARE_MODEL} (free fallback; Gemini said: {who[:90]})"
            else:
                who = f"Gemini: {who[:120]} | Cloudflare: {why}"
        if data:
            ext = "jpg" if data[:3] == b"\xff\xd8\xff" else "png"
            open(os.path.join(robot.MEDIA_DIR, folder, f"{pid}.{ext}"), "wb").write(data)
            done.append((pid, who)); say(f"{pid}: drawn by {who}")
        else:
            failed.append((pid, who)); say(f"{pid}: no picture ({who})")
    json.dump({"made": done, "failed": failed, "prompts": {p: prompts[p] for p in wanted}},
              open(os.path.join(robot.MEDIA_DIR, folder, "pictures.json"), "w"), indent=1)
    robot.save_media(f"Pet Shelf pictures {folder}")
    lines = [f"### Pet Shelf pictures: {len(done)} made, {len(failed)} failed", f"Saved on branch {robot.MEDIA_BRANCH} in {folder}"]
    lines += [f"- {p}: {w}" for p, w in done] + [f"- FAILED {p}: {w}" for p, w in failed]
    write_summary("\n".join(lines))
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
