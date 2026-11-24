#!/usr/bin/env python3
"""Generate the artwork the boot splash and the login theme load at runtime.

Everything stays inside branding/ so the ISO build never depends on scripts/.

Both palettes are generated from the same geometry:
  * light — warm cream, ink watermark, soft white halo (default)
  * dark  — graphite, warm amber glow, light watermark, warm halo

The login theme ships BOTH backgrounds so it can flip live; the splash ships one
directory per palette because plymouth only reads one theme at a time.
"""
import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
BRAND = os.path.join(ROOT, "branding")

W, H = 1920, 1080
MARK = os.path.join(ASSETS, "parametral-mark-1024.png")

PALETTES = {
    "light": {
        "top": (251, 247, 240),
        "bottom": (231, 219, 200),
        "glow1": ((255, 252, 242), 115),
        "glow2": ((233, 208, 168), 52),
        "mark": ((74, 63, 48), 0.062),
        "echo": ((74, 63, 48), 0.035),
        "halo": ((255, 253, 247), 200),
        "dot": (26, 26, 30, 235),
        "vig": ((62, 52, 40), 34),
    },
    "dark": {
        "top": (22, 24, 29),
        "bottom": (9, 10, 13),
        "glow1": ((255, 176, 102), 52),
        "glow2": ((90, 140, 220), 22),
        "mark": ((255, 246, 232), 0.14),
        "echo": ((255, 246, 232), 0.07),
        "halo": ((255, 236, 205), 92),
        "dot": (240, 235, 225, 230),
        "vig": ((0, 0, 0), 60),
    },
}


def gradient(p):
    strip = Image.new("RGB", (1, H))
    px = strip.load()
    for y in range(H):
        t = y / (H - 1)
        px[0, y] = tuple(round(a + (b - a) * t) for a, b in zip(p["top"], p["bottom"]))
    return strip.resize((W, H), Image.BILINEAR).convert("RGBA")


def glow(img, center, radius, color, strength):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = center
    for i in range(24, 0, -1):
        r = radius * i / 24
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  fill=color + (int(strength * (1 - i / 24) ** 1.5),))
    return Image.alpha_composite(img, layer.filter(ImageFilter.GaussianBlur(radius // 7)))


def vignette(img, color, amount):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse([-W * 0.30, -H * 0.40, W * 1.30, H * 1.40], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(240))
    dark = Image.new("RGBA", img.size, color + (255,))
    dark.putalpha(mask.point(lambda v: int((255 - v) * amount / 255)))
    return Image.alpha_composite(img, dark)


def watermark(color, alpha, size_px=1050, blur=10):
    """The mark recoloured to one flat colour, used as a background ghost."""
    mark = Image.open(MARK).convert("RGBA")
    mark.thumbnail((size_px, size_px), Image.LANCZOS)
    a = mark.split()[3].point(lambda v: int(v * alpha))
    flat = Image.new("RGBA", mark.size, color + (255,))
    flat.putalpha(a)
    return flat.filter(ImageFilter.GaussianBlur(blur))


def logo_glow(color, strength, size_px=620):
    g = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    c = size_px // 2
    for i in range(40, 0, -1):
        r = c * i / 40
        a = int(strength * (1 - i / 40) ** 2.2)
        d.ellipse([c - r, c - r, c + r, c + r], fill=color + (a,))
    return g.filter(ImageFilter.GaussianBlur(size_px // 14))


def background(p, with_watermark=True):
    img = gradient(p)
    img = glow(img, (W // 2, 380), 660, *p["glow1"])
    img = glow(img, (W // 2, 840), 920, *p["glow2"])
    if with_watermark:
        wm = watermark(*p["mark"])
        img.alpha_composite(wm, (int(W * 0.80) - wm.width // 2,
                                 int(H * 0.17) - wm.height // 2))
        echo = watermark(*p["echo"], size_px=760, blur=14)
        img.alpha_composite(echo, (int(W * 0.14) - echo.width // 2,
                                   int(H * 0.88) - echo.height // 2))
    img = vignette(img, *p["vig"])
    return img.convert("RGB")


def dot(color):
    d = Image.new("RGBA", (14, 14), (0, 0, 0, 0))
    ImageDraw.Draw(d).ellipse([2, 2, 11, 11], fill=color)
    return d.filter(ImageFilter.GaussianBlur(0.6))


def write_logos(d):
    mark = Image.open(MARK).convert("RGBA")
    mark.thumbnail((256, 256), Image.LANCZOS)
    mark.save(os.path.join(d, "logo.png"))

    big = Image.open(MARK).convert("RGBA")
    big.thumbnail((420, 420), Image.LANCZOS)
    big.save(os.path.join(d, "logo-large.png"))


def main():
    light, dark = PALETTES["light"], PALETTES["dark"]

    # ---- boot splash: one directory per palette ------------------------------
    for name, p in (("parametral", light), ("parametral-dark", dark)):
        d = os.path.join(BRAND, "plymouth", name)
        os.makedirs(d, exist_ok=True)
        background(p, with_watermark=False).save(os.path.join(d, "background.png"), optimize=True)
        write_logos(d)
        dot(p["dot"]).save(os.path.join(d, "dot.png"))
        print("wrote", d)

    # ---- login theme: one directory, both backgrounds ------------------------
    d = os.path.join(BRAND, "sddm", "parametral")
    os.makedirs(d, exist_ok=True)
    background(light, True).save(os.path.join(d, "background.png"), optimize=True)
    background(dark, True).save(os.path.join(d, "background-dark.png"), optimize=True)
    write_logos(d)
    logo_glow(*light["halo"]).save(os.path.join(d, "logo-glow.png"))
    logo_glow(*dark["halo"]).save(os.path.join(d, "logo-glow-dark.png"))
    print("wrote", d)


if __name__ == "__main__":
    main()
