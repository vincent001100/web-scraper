"""Film the animated Solvix TikTok advert (brand/promo/video/promo.html) into an MP4 with sound.

Opens the page in a hidden browser, draws it frame by frame, and joins the frames with a
soundtrack made right here (a light beat plus pops, dings and whooshes timed to the animation).
Run:  .venv/bin/python make_promo_video.py   →  brand/promo/solvix-tiktok.mp4
"""
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from playwright.sync_api import sync_playwright

PAGE = Path("brand/promo/video/promo.html")
OUT = Path("brand/promo/solvix-tiktok.mp4")
SOUND = Path("brand/promo/video/soundtrack.wav")
FPS = 30
RATE = 44100   # sound samples per second


# ---------- soundtrack ----------
def tone(freq, length, decay, start_freq=None):
    """A sine note that fades out; with start_freq it slides down to freq (a 'pop')."""
    t = np.arange(int(RATE * length)) / RATE
    f = freq if start_freq is None else freq + (start_freq - freq) * np.exp(-t * 40)
    return np.sin(2 * np.pi * np.cumsum(f) / RATE) * np.exp(-t * decay)


def noise(length, smooth, rng):
    """A burst of hiss; a bigger 'smooth' makes it softer and deeper."""
    n = rng.standard_normal(int(RATE * length))
    return np.convolve(n, np.ones(smooth) / smooth, mode="same")


def effect(kind, rng):
    if kind == "pop":
        return tone(420, .12, 30, start_freq=950) * .5
    if kind == "ding":
        return (tone(1318, .6, 7) + tone(1760, .6, 9) * .6) * .28
    if kind == "blip":
        return tone(660, .1, 35) * .35
    if kind == "tick":
        return (tone(1500, .06, 60) + tone(2200, .06, 70)) * .3
    if kind == "key":
        return noise(.03, 3, rng) * np.exp(-np.arange(int(RATE * .03)) / RATE * 150) * .35
    if kind in ("whoosh", "swish"):
        length = .55 if kind == "whoosh" else .25
        n = noise(length, 6 if kind == "whoosh" else 3, rng)
        env = np.sin(np.linspace(0, np.pi, len(n))) ** 2
        return n * env * (.9 if kind == "whoosh" else .6)
    if kind == "confetti":
        out = np.zeros(int(RATE * .8))
        for _ in range(14):
            p = tone(rng.uniform(700, 1500), .06, 60) * .12
            at = int(rng.uniform(0, .7) * RATE)
            out[at:at + len(p)] += p
        return out
    raise ValueError(kind)


def music(seconds, rng):
    """A soft, upbeat loop at 120 beats a minute: kick, hi-hat, bass and warm chords."""
    total = np.zeros(int(RATE * (seconds + 3)))   # extra room so the last chord fits
    beat = .5
    chords = [(220.0, 261.6, 329.6), (174.6, 220.0, 261.6), (261.6, 329.6, 392.0), (196.0, 246.9, 293.7)]
    for i in range(int(seconds / beat) + 1):
        at = int(i * beat * RATE)
        kick = tone(50, .25, 14, start_freq=140) * .55
        total[at:at + len(kick)] += kick
        hat = noise(.04, 1, rng) * np.exp(-np.arange(int(RATE * .04)) / RATE * 120) * .07
        off = at + int(beat / 2 * RATE)
        total[off:off + len(hat)] += hat
        if i % 4 == 0:   # a new chord every bar (4 beats)
            notes = chords[(i // 4) % 4]
            t = np.arange(int(RATE * beat * 4)) / RATE
            env = np.minimum(1, t * 8) * np.exp(-t * .6)
            pad = sum(np.sin(2 * np.pi * f * t) + .3 * np.sin(4 * np.pi * f * t) for f in notes) * env * .05
            bass = np.sin(2 * np.pi * notes[0] / 2 * t) * env * .16
            total[at:at + len(t)] += pad + bass
    return total


def soundtrack(duration, events):
    rng = np.random.default_rng(3)
    mix = music(duration, rng) * .8
    for e in events:
        fx = effect(e["kind"], rng)
        at = int(e["t"] * RATE)
        mix[at:at + len(fx)] += fx[:len(mix) - at]
    mix = mix[:int(duration * RATE)]
    fade = int(RATE * .8)   # fade the music out over the last moment
    mix[-fade:] *= np.linspace(1, 0, fade)
    mix = np.tanh(mix * 1.2) * .85   # keep loud moments from crackling
    with wave.open(str(SOUND), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())


# ---------- picture ----------
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto(PAGE.resolve().as_uri())
        duration = page.evaluate("DURATION")
        soundtrack(duration, page.evaluate("SFX"))
        frames = int(duration * FPS)
        ffmpeg = subprocess.Popen(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
             "-f", "image2pipe", "-framerate", str(FPS), "-i", "-", "-i", str(SOUND),
             "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(OUT)],
            stdin=subprocess.PIPE)
        for i in range(frames):
            page.evaluate(f"render({i / FPS})")
            ffmpeg.stdin.write(page.screenshot(type="jpeg", quality=95))
            if i % 60 == 0:
                print(f"frame {i}/{frames}")
        ffmpeg.stdin.close()
        ffmpeg.wait()
        browser.close()
    print(f"Saved {OUT} ({OUT.stat().st_size // 1024} KB, {duration:.1f} s)")


if __name__ == "__main__":
    main()
