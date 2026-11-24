"""Turn the delivered PNG logo into usable assets.

The delivered file has a baked-in black background, a glow that turns to mush at
small sizes and a wordmark whose second "a" is drawn as a lambda glyph. Fix here:

  * mark cropped out, black background converted to alpha (usable on any dark UI),
  * a light-theme recolour (neutral + blue palette, glow damped),
  * wordmark is NOT baked in: README renders the name as text (crisp, theme-aware,
    and spelled correctly).

Run: python3 scripts/prepare_logo.py <source.png>
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageChops

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "assets")


def content_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    """bbox of non-black pixels in the upper part (the mark, not the wordmark)."""
    top = image.crop((0, 0, image.width, int(image.height * 0.62)))
    mask = top.convert("L").point(lambda value: 255 if value > 18 else 0)
    return mask.getbbox()


def to_rgba(dark: Image.Image) -> Image.Image:
    alpha = dark.convert("L").point(lambda value: min(255, int(value * 1.15)))
    out = dark.convert("RGBA")
    out.putalpha(alpha)
    return out


def to_light(dark: Image.Image) -> Image.Image:
    """White/blue on black → graphite/blue on transparent, glow damped."""
    rgb = dark.convert("RGB")
    red, _green, blue = rgb.split()
    blueness = ImageChops.subtract(blue, red)
    blue_mask = blueness.point(lambda value: 255 if value > 28 else 0)

    neutral = Image.new("RGB", rgb.size, (31, 41, 55))       # #1F2937
    accent = Image.new("RGB", rgb.size, (11, 99, 206))       # #0B63CE
    recoloured = Image.composite(accent, neutral, blue_mask)

    alpha = dark.convert("L").point(
        lambda value: 0 if value < 42 else min(255, int((value - 42) * 1.6)))
    recoloured.putalpha(alpha)
    return recoloured


def save(image: Image.Image, name: str, sizes=(1024, 512, 256)) -> None:
    os.makedirs(OUT, exist_ok=True)
    for size in sizes:
        resized = image.copy()
        resized.thumbnail((size, size), Image.LANCZOS)
        path = os.path.join(OUT, f"{name}-{size}.png")
        resized.save(path)
        print("wrote", path, resized.size)


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/egedevcat/Downloads/Futuristic ParametralOS Gauge Logo.png"
    image = Image.open(source).convert("RGB")
    box = content_bbox(image)
    if box is None:
        raise SystemExit("no mark found in the upper part of the image")
    pad = 24
    box = (max(0, box[0] - pad), max(0, box[1] - pad),
           min(image.width, box[2] + pad), min(image.height, box[3] + pad))
    mark = image.crop(box)
    print("mark crop:", box, mark.size)

    dark = to_rgba(mark)
    save(dark, "parametral-mark")
    light = to_light(mark)
    save(light, "parametral-mark-light")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
