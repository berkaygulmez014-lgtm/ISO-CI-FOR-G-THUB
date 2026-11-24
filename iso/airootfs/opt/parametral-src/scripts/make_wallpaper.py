#!/usr/bin/env python3
"""Generate the Parametral desktop wallpapers.

Art direction: ÖLÇÜM PLAKASI (a drafting table). Warm graphite, hairline measurement line,
no decoration that competes with a window.

The bar plateau is drawn HERE, not by the shell. Noctalia draws a bar surface we cannot
restyle into a plate with a 2 px ruler along its bottom edge, so the plate + ruler live in the
wallpaper at the exact geometry the bar occupies (top, margin_edge, thickness, margin_ends),
and Noctalia runs with `background_opacity = 0.0` and draws only the widgets on top of it.
The workspace marks are the ruler's ticks; they sit in the bar's content row.

Rules this file follows:
  * colours and bar geometry come from branding/tokens.json — no hex literals here
  * no amber in the wallpaper: amber is the screen's signal, not its decoration
  * no wordmark floating in the air (it read as a rendering accident at 1280x800)
  * the dial is drawn at full resolution — no blur, no crop, no glow
  * the centre of the screen stays dark and empty: that is where windows go

    python3 scripts/make_wallpaper.py
"""

from __future__ import annotations

import json
import math
import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "branding", "wallpapers")
TOKENS = os.path.join(ROOT, "branding", "tokens.json")

# Fallbacks only for keys tokens.json does not carry yet (T0 adds them to metric).
LIGHT_FALLBACK = dict(bg="#EFE7D9", surface="#F4EFE6", text="#1C1A18", muted="#5A544A")


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def load_tokens():
    with open(TOKENS) as fh:
        return json.load(fh)


def palette(tokens, mode: str):
    # tokens.json carries "colour" (dark) and "light"; a missing light key falls back to the
    # values below only so an older tokens file still renders.
    light = tokens.get("light", tokens.get("colourLight", {}))
    if mode == "dark":
        source = tokens["colour"]
    else:
        source = {**{k: LIGHT_FALLBACK[k] for k in LIGHT_FALLBACK}, **light}
    return dict(
        bg=hex_rgb(source["bg"]),
        surface=hex_rgb(source["surface"]),
        text=hex_rgb(source["text"]),
        muted=hex_rgb(source["muted"]),
    )


def bar_geometry(width: int, height: int, bars: dict):
    """The plate the Noctalia bar reserves: same numbers as branding/noctalia/config.toml."""
    thickness = int(bars.get("thickness", 40))
    edge = int(bars.get("marginEdge", 6))
    # 8 at every width: the shell has one margin_ends value, and a plate drawn at 12 while the
    # widgets sit at 8 would put the plate edge and the content on different lines.
    ends = int(bars.get("marginEnds", 8))
    radius = int(bars.get("radius", 12))
    return dict(x0=ends, y0=edge, x1=width - ends, y1=edge + thickness, radius=radius,
                thickness=thickness)


def compose(size, mode, tokens, plate: bool = True):
    w, h = size
    pal = palette(tokens, mode)
    bars = tokens.get("metric", {})
    img = Image.new("RGB", (w, h), pal["bg"])

    # ---- 1 px grid: scale for the eye, not a pattern to read ---------------
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    # light paper shows the major grid as blocky tiles, so it gets a lighter hand
    fine, major = (12, 22) if mode == "dark" else (8, 13)
    step = max(32, w // 48)
    for x in range(0, w, step):
        gd.line([(x, 0), (x, h)], fill=pal["muted"] + (fine,))
    for y in range(0, h, step):
        gd.line([(0, y), (w, y)], fill=pal["muted"] + (fine,))
    every = step * 5
    for x in range(0, w, every):
        gd.line([(x, 0), (x, h)], fill=pal["muted"] + (major,))
    for y in range(0, h, every):
        gd.line([(0, y), (w, y)], fill=pal["muted"] + (major,))
    img = Image.alpha_composite(img.convert("RGBA"), grid).convert("RGB")

    # ---- the dial: instrument, low contrast, no glow, no amber -------------
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = int(w * 0.70), int(h * 0.46)
    r = int(min(w, h) * 0.26)
    width = max(1, int(min(w, h) * 0.0020))

    for scale, alpha in ((1.0, 46), (0.70, 24)):
        rr = int(r * scale)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=pal["muted"] + (alpha,), width=width)

    for i in range(60):
        angle = math.tau * i / 60 - math.pi / 2
        major = i % 5 == 0
        inner = r * (0.87 if major else 0.91)
        outer = r * 0.98
        d.line(
            [(cx + math.cos(angle) * inner, cy + math.sin(angle) * inner),
             (cx + math.cos(angle) * outer, cy + math.sin(angle) * outer)],
            fill=pal["muted"] + ((72 if major else 38),),
            width=width * (2 if major else 1),
        )

    needle_angle = math.radians(-50)
    nr = r * 0.62
    d.line([(cx, cy), (cx + math.cos(needle_angle) * nr, cy + math.sin(needle_angle) * nr)],
           fill=pal["text"] + (120,), width=max(2, width * 2))
    hub = max(3, int(r * 0.022))
    d.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=pal["text"] + (120,))

    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    # ---- vignette: keeps the middle quiet where windows live ---------------
    # Applied BEFORE the plate: the plate is a UI surface and must be the token colour exactly,
    # edge to edge. A vignette over it gave the bar a gradient face, and a measurement tool that
    # looks for #12171E stopped finding the plate at all.
    # Dark only: on a flat light page the blurred mask quantises into visible patches instead of
    # a gradient, and paper does not vignette anyway.
    if mode == "dark":
        vign = Image.new("L", (w, h), 0)
        vd = ImageDraw.Draw(vign)
        vd.ellipse([-w // 3, -h // 3, w + w // 3, h + h // 3], fill=255)
        vign = vign.filter(ImageFilter.GaussianBlur(int(min(w, h) * 0.15)))
        img = Image.composite(img, Image.new("RGB", (w, h), pal["bg"]), vign)

    # ---- the plate and its ruler ------------------------------------------
    if plate:
        g = bar_geometry(w, h, bars)
        plate_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        pd = ImageDraw.Draw(plate_layer)
        pd.rounded_rectangle([g["x0"], g["y0"], g["x1"], g["y1"]], radius=g["radius"],
                             fill=pal["surface"] + (255,))
        # one hairline edge, no glow, no second border
        pd.rounded_rectangle([g["x0"], g["y0"], g["x1"], g["y1"]], radius=g["radius"],
                             outline=pal["muted"] + (26,), width=1)
        # the ruler: 2 px, inset from the plate ends, sitting on its bottom edge
        rr_y = g["y1"] - 3
        inset = g["radius"]
        pd.rectangle([g["x0"] + inset, rr_y, g["x1"] - inset, rr_y + 1],
                     fill=pal["muted"] + (46,))
        img = Image.alpha_composite(img.convert("RGBA"), plate_layer).convert("RGB")
    return img


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    tokens = load_tokens()
    targets = [
        ((2560, 1440), "2560x1440", "dark", True),
        ((2560, 1440), "2560x1440-light", "light", True),
        ((1920, 1080), "1920x1080", "dark", True),
        ((1920, 1080), "1920x1080-light", "light", True),
        ((1280, 800), "1280x800", "dark", True),
        ((1280, 800), "1280x800-light", "light", True),
    ]
    for size, name, mode, plate in targets:
        img = compose(size, mode, tokens, plate)
        path = os.path.join(OUT, f"{name}.png")
        img.save(path, optimize=True)
        print(f"wrote {path} ({size[0]}x{size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
