"""Draw the Solvix brand images: the "S" icon (phone app + profile pictures) and the social media cover banners."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FOREST = "#2f4a3a"
PAPER = "#f4efe6"
TERRA = "#b5532a"
MUTED = "#6b675c"
INK = "#1f2a24"
SERIF_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Cover sizes each site asks for
BANNERS = {"facebook": (1640, 624), "linkedin": (1584, 396), "x": (1500, 500)}


def draw_icon(size, rounded=False):
    # Drawn 4x larger then shrunk, so the edges come out smooth
    big = size * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle((0, 0, big, big), radius=big // 5, fill=FOREST)
    else:
        d.rectangle((0, 0, big, big), fill=FOREST)
    # Social sites crop the picture to a circle, so the letter stays well inside the middle
    d.text((big // 2, big // 2 - big // 40), "S", font=ImageFont.truetype(SERIF_BOLD, int(big * 0.52)),
           fill=PAPER, anchor="mm")
    dot = big // 22
    cx, cy = int(big * 0.72), int(big * 0.62)
    d.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=TERRA)
    return img.resize((size, size), Image.LANCZOS)


def draw_banner(w, h):
    img = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(img)
    # Faint dot grid in the background, like squared paper
    step = h // 9
    for x in range(step // 2, w, step):
        for y in range(step // 2, h, step):
            d.ellipse((x - 2, y - 2, x + 2, y + 2), fill="#e3dccd")
    # Forest band along the bottom with the accent line above it
    band = h // 9
    d.rectangle((0, h - band, w, h), fill=FOREST)
    d.rectangle((0, h - band - 6, w, h - band), fill=TERRA)

    # Everything sits in the middle, because phones crop the sides and the profile picture covers a corner
    cx, cy = w // 2, (h - band) // 2
    name_font = ImageFont.truetype(SERIF_BOLD, int(h * 0.20))
    icon = draw_icon(int(h * 0.24), rounded=True)
    name_w = d.textlength("Solvix", font=name_font)
    gap = h * 0.05
    left = cx - (icon.width + gap + name_w) / 2
    top = cy - h * 0.20
    img.paste(icon, (int(left), int(top - icon.height / 2)), icon)
    d.text((left + icon.width + gap, top), "Solvix", font=name_font, fill=INK, anchor="lm")

    d.text((cx, cy + h * 0.06), "Python tools that solve real business problems",
           font=ImageFont.truetype(SANS, int(h * 0.062)), fill=MUTED, anchor="mm")
    d.text((cx, cy + h * 0.19), "WEB SCRAPING   •   AUTOMATION   •   DATA   •   WEB APPS",
           font=ImageFont.truetype(SANS_BOLD, int(h * 0.04)), fill=TERRA, anchor="mm")
    return img


if __name__ == "__main__":
    Path("static").mkdir(exist_ok=True)
    Path("brand").mkdir(exist_ok=True)
    draw_icon(1080).convert("RGB").save("brand/solvix-profile.png")  # Instagram, Facebook, TikTok
    draw_icon(180).convert("RGB").save("static/apple-touch-icon.png")  # iPhone home screen
    draw_icon(512, rounded=True).save("static/icon-512.png")
    draw_icon(64, rounded=True).save("static/favicon.png")  # browser tab
    for site, (w, h) in BANNERS.items():
        draw_banner(w, h).save(f"brand/solvix-cover-{site}.png")
    print("Icons and covers saved in brand/ and static/")
