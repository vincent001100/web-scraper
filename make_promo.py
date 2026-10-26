"""Draw the Solvix advert for our social media auto-posting service: a feed post (Instagram/Facebook)
and a short vertical video for TikTok."""
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from make_brand import FOREST, PAPER, TERRA, MUTED, INK, SERIF_BOLD, SANS, SANS_BOLD, draw_icon

CARD = "#e8e0d0"
OUT = Path("brand/promo")


def dot_grid(d, w, h, step=54):
    # Faint dot grid in the background, like squared paper (same as the covers)
    for x in range(step // 2, w, step):
        for y in range(step // 2, h, step):
            d.ellipse((x - 2, y - 2, x + 2, y + 2), fill="#e3dccd")


def header(img, d, w):
    icon = draw_icon(74, rounded=True)
    img.paste(icon, (60, 52), icon)
    d.text((152, 89), "Solvix", font=ImageFont.truetype(SERIF_BOLD, 50), fill=INK, anchor="lm")


def footer(d, w, h, line="Send us a message: “AUTOMATE”"):
    d.rectangle((0, h - 150, w, h), fill=FOREST)
    d.rectangle((0, h - 156, w, h - 150), fill=TERRA)
    d.text((w // 2, h - 98), line, font=ImageFont.truetype(SERIF_BOLD, 40), fill=PAPER, anchor="mm")
    d.text((w // 2, h - 48), "Python tools that solve real business problems",
           font=ImageFont.truetype(SANS, 24), fill="#c9d3cb", anchor="mm")


def flow(d, cx, top):
    """The three steps as cards joined by arrows: your content → Solvix → your pages."""
    steps = [("1", "Your content", "pictures, prices, offers"),
             ("2", "Solvix automation", "runs every morning"),
             ("3", "Facebook + Instagram", "posted for you, on time")]
    card_w, card_h, gap = 720, 118, 52
    y = top
    for i, (num, title, sub) in enumerate(steps):
        x0 = cx - card_w // 2
        d.rounded_rectangle((x0, y, x0 + card_w, y + card_h), radius=22,
                            fill=FOREST if i == 1 else CARD)
        text = PAPER if i == 1 else INK
        d.ellipse((x0 + 30, y + 29, x0 + 90, y + 89), fill=TERRA)
        d.text((x0 + 60, y + 59), num, font=ImageFont.truetype(SANS_BOLD, 30), fill=PAPER, anchor="mm")
        d.text((x0 + 120, y + 42), title, font=ImageFont.truetype(SANS_BOLD, 36), fill=text, anchor="lm")
        d.text((x0 + 120, y + 84), sub, font=ImageFont.truetype(SANS, 26),
               fill="#c9d3cb" if i == 1 else MUTED, anchor="lm")
        y += card_h
        if i < len(steps) - 1:
            d.line((cx, y + 8, cx, y + gap - 14), fill=TERRA, width=5)
            d.polygon([(cx - 13, y + gap - 20), (cx + 13, y + gap - 20), (cx, y + gap - 4)], fill=TERRA)
            y += gap
    return y


def feed_post(w=1080, h=1350):
    img = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(img)
    dot_grid(d, w, h)
    header(img, d, w)
    cx = w // 2
    d.text((cx, 230), "Tired of posting", font=ImageFont.truetype(SERIF_BOLD, 74), fill=INK, anchor="mm")
    d.text((cx, 318), "every single day?", font=ImageFont.truetype(SERIF_BOLD, 74), fill=TERRA, anchor="mm")
    d.text((cx, 408), "We build automations that post to your Facebook Page",
           font=ImageFont.truetype(SANS, 30), fill=MUTED, anchor="mm")
    d.text((cx, 450), "and Instagram for you — automatically, every day.",
           font=ImageFont.truetype(SANS, 30), fill=MUTED, anchor="mm")
    bottom = flow(d, cx, 520)
    d.text((cx, bottom + 62), "SAVE TIME   •   NEVER MISS A POST   •   SET UP ONCE",
           font=ImageFont.truetype(SANS_BOLD, 26), fill=TERRA, anchor="mm")
    footer(d, w, h)
    return img


def video_slides(w=1080, h=1920):
    """Four tall slides for the TikTok video."""
    def blank():
        img = Image.new("RGB", (w, h), PAPER)
        d = ImageDraw.Draw(img)
        dot_grid(d, w, h)
        header(img, d, w)
        return img, d

    cx = w // 2
    slides = []

    img, d = blank()
    d.text((cx, 760), "Still posting", font=ImageFont.truetype(SERIF_BOLD, 96), fill=INK, anchor="mm")
    d.text((cx, 880), "by hand", font=ImageFont.truetype(SERIF_BOLD, 96), fill=INK, anchor="mm")
    d.text((cx, 1000), "every day?", font=ImageFont.truetype(SERIF_BOLD, 96), fill=TERRA, anchor="mm")
    slides.append(img)

    img, d = blank()
    d.text((cx, 520), "We automate it.", font=ImageFont.truetype(SERIF_BOLD, 84), fill=INK, anchor="mm")
    flow(d, cx, 700)
    slides.append(img)

    img, d = blank()
    d.text((cx, 560), "What you get", font=ImageFont.truetype(SERIF_BOLD, 84), fill=INK, anchor="mm")
    for i, line in enumerate(["Posts go out on time, every day",
                              "Facebook + Instagram together",
                              "No apps to open, no copy-paste",
                              "Set up once — it keeps running"]):
        y = 760 + i * 150
        d.rounded_rectangle((110, y - 52, w - 110, y + 52), radius=22, fill=CARD)
        d.ellipse((150, y - 18, 186, y + 18), fill=TERRA)
        d.text((220, y), line, font=ImageFont.truetype(SANS_BOLD, 38), fill=INK, anchor="lm")
    slides.append(img)

    img, d = blank()
    d.text((cx, 720), "Want this for", font=ImageFont.truetype(SERIF_BOLD, 92), fill=INK, anchor="mm")
    d.text((cx, 840), "your business?", font=ImageFont.truetype(SERIF_BOLD, 92), fill=TERRA, anchor="mm")
    d.text((cx, 1000), "Send us a message: “AUTOMATE”", font=ImageFont.truetype(SANS_BOLD, 46),
           fill=FOREST, anchor="mm")
    # No footer bar here: TikTok's caption and buttons cover the bottom of the screen
    d.text((cx, 1110), "Solvix can build it for you", font=ImageFont.truetype(SANS, 40), fill=MUTED, anchor="mm")
    slides.append(img)
    return slides


def make_video(slides, path, seconds=3.5, fade=0.6):
    """Join the slides into an MP4 with soft fades between them."""
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    files = []
    for i, slide in enumerate(slides):
        f = OUT / f"slide{i + 1}.png"
        slide.save(f)
        files.append(f)
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    for f in files:
        cmd += ["-loop", "1", "-t", str(seconds), "-i", str(f)]
    # Chain crossfades: each fade starts just before the previous clip ends
    chain, last = [], "[0:v]"
    for i in range(1, len(files)):
        out = f"[v{i}]"
        chain.append(f"{last}[{i}:v]xfade=transition=fade:duration={fade}:offset={i * (seconds - fade):.2f}{out}")
        last = out
    cmd += ["-filter_complex", ";".join(chain), "-map", last,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(path)]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    feed_post().save(OUT / "automation-post.jpg", quality=92)
    make_video(video_slides(), OUT / "automation-tiktok.mp4")
    print(f"Advert saved in {OUT}/")
