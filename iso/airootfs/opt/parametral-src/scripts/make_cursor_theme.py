#!/usr/bin/env python3
"""Build the Parametral XCursor theme.

One arrow PNG is not a cursor set: a desktop needs ~25 distinct shapes (text I-beam, hand,
busy, eight resize directions, forbidden, grab...). This script draws all of them from the
same palette so the set is consistent, then compiles them with xcursorgen.

Design rules
  - dark graphite body (#12171E) so it reads on our light wallpapers
  - amber rim (#E0A93B) so it reads on our dark wallpapers
  - drawn at 4x and downsampled: PIL has no anti-aliasing, supersampling is the cheap fix
"""
from __future__ import annotations

import shutil
import struct
from pathlib import Path

from PIL import Image, ImageDraw

SS = 4                      # supersampling factor
SIZES = (24, 32, 48, 64)    # sizes written into each cursor
# Light body with a dark edge reads on both our wallpapers; an all-dark body disappears on
# the dark one (it looked hollow in the first draft). Amber is the accent, not the outline.
BODY = (245, 241, 232, 255)
EDGE = (11, 15, 20, 255)
AMBER = (224, 169, 59, 255)
MUTED = (154, 164, 178, 255)

OUT = Path(__file__).resolve().parent.parent / "branding" / "cursors"


def canvas(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def finish(img: Image.Image, size: int) -> Image.Image:
    return img.resize((size, size), Image.Resampling.LANCZOS)


def outline(draw: ImageDraw.ImageDraw, pts: list[tuple[float, float]], colour, width: float) -> None:
    """Closed, rounded outline — PIL's default joins are square and look cheap."""
    scaled = [(x * SS, y * SS) for x, y in pts]
    draw.line(scaled + [scaled[0]], fill=colour, width=int(width * SS), joint="curve")


ARROW = [(4, 2), (4, 23.5), (9.5, 18.4), (13.2, 27.6), (17.4, 25.9), (13.7, 16.9), (21.5, 16.6)]


def draw_arrow(size: int, colour_body=BODY, colour_rim=EDGE) -> tuple[Image.Image, tuple[int, int]]:
    img, d = canvas(size)
    body = [(x * size / 32, y * size / 32) for x, y in ARROW]
    d.polygon([(x * SS, y * SS) for x, y in body], fill=colour_body)
    outline(d, body, colour_rim, max(1.4, size / 21))
    # amber accent down the arrow's leading edge — brand without touching legibility
    tip, notch = body[0], body[2]
    d.line([(tip[0] * SS, tip[1] * SS), (notch[0] * SS, notch[1] * SS)],
           fill=AMBER, width=int(max(0.9, size / 34) * SS))
    hotspot = (round(4.6 * size / 32), round(2.6 * size / 32))
    return finish(img, size), hotspot


def draw_xterm(size: int) -> tuple[Image.Image, tuple[int, int]]:
    img, d = canvas(size)
    w = max(1.6, size / 15)
    top, bottom = 3 * size / 32, 29 * size / 32
    mid = size / 2
    d.line([(mid * SS, top * SS), (mid * SS, bottom * SS)], fill=EDGE, width=int(w * SS))
    d.line([(mid * SS, top * SS), (mid * SS, bottom * SS)], fill=BODY,
           width=int(max(0.8, w / 2.2) * SS))
    serif = 3.4 * size / 32
    for y in (top, bottom):
        d.line([((mid - serif) * SS, y * SS), ((mid + serif) * SS, y * SS)],
               fill=AMBER, width=int(w * SS))
    return finish(img, size), (round(mid), round(mid))


def draw_crosshair(size: int) -> tuple[Image.Image, tuple[int, int]]:
    img, d = canvas(size)
    mid = size / 2
    arm, gap, w = 7 * size / 32, 3 * size / 32, max(1.2, size / 26)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        d.line([((mid + dx * gap) * SS, (mid + dy * gap) * SS),
                ((mid + dx * arm) * SS, (mid + dy * arm) * SS)],
               fill=EDGE, width=int(w * 1.9 * SS))
        d.line([((mid + dx * gap) * SS, (mid + dy * gap) * SS),
                ((mid + dx * arm) * SS, (mid + dy * arm) * SS)],
               fill=BODY, width=int(w * SS))
    d.ellipse([(mid - gap * 0.55) * SS, (mid - gap * 0.55) * SS,
               (mid + gap * 0.55) * SS, (mid + gap * 0.55) * SS], fill=AMBER)
    return finish(img, size), (round(mid), round(mid))


def draw_hand(size: int, closed: bool = False) -> tuple[Image.Image, tuple[int, int]]:
    """Pointer hand: palm + raised index finger + thumb.

    Three separate finger capsules read as a comb at 24 px, so the folded fingers are
    bumps on the palm instead of full-length capsules.
    """
    img, d = canvas(size)
    s = size / 32
    w = int(max(1.1, s * 1.5) * SS)

    def capsule(box, radius):
        d.rounded_rectangle([box[0] * s * SS, box[1] * s * SS, box[2] * s * SS, box[3] * s * SS],
                            radius=radius * s * SS, fill=BODY, outline=EDGE, width=w)

    # palm first, then the parts that stick out, so the outlines merge into one shape
    capsule((9.5, 13.5, 25.5, 27.5), 5.0)
    if closed:
        # fist: knuckle bumps only
        capsule((11.5, 9.5, 16.0, 15.0), 2.2)
        capsule((16.0, 9.0, 20.5, 15.0), 2.2)
        capsule((20.3, 10.0, 24.6, 15.0), 2.2)
        capsule((7.0, 14.0, 11.5, 20.5), 2.2)
        hotspot = (round(16 * s), round(11 * s))
    else:
        capsule((11.8, 3.4, 16.8, 16.5), 2.5)   # index finger
        capsule((5.6, 11.0, 11.0, 19.5), 2.5)   # thumb
        capsule((17.0, 10.4, 21.2, 15.2), 2.2)  # folded knuckles
        capsule((21.0, 11.2, 25.0, 15.2), 2.2)
        hotspot = (round(14 * s), round(4 * s))
    return finish(img, size), hotspot


def draw_forbidden(size: int) -> tuple[Image.Image, tuple[int, int]]:
    img, d = canvas(size)
    m, r = 3 * size / 32, 13 * size / 32
    box = [m * SS, m * SS, (m + 2 * r) * SS, (m + 2 * r) * SS]
    d.ellipse(box, fill=(245, 241, 232, 255), outline=(206, 86, 86, 255),
              width=int(max(1.6, size / 13) * SS))
    c = m + r
    off = r * 0.7
    d.line([((c - off) * SS, (c - off) * SS), ((c + off) * SS, (c + off) * SS)],
           fill=(206, 86, 86, 255), width=int(max(1.6, size / 13) * SS))
    return finish(img, size), (round(c), round(c))


def draw_resize(size: int, angle: float, double: bool = True) -> tuple[Image.Image, tuple[int, int]]:
    img, d = canvas(size)
    w = max(1.4, size / 18)
    c = size / 2
    arm = 9 * size / 32
    d.line([((c - arm) * SS, c * SS), ((c + arm) * SS, c * SS)], fill=EDGE, width=int(w * 1.9 * SS))
    d.line([((c - arm) * SS, c * SS), ((c + arm) * SS, c * SS)], fill=BODY, width=int(w * SS))
    head = 4.2 * size / 32
    for sign in ((1, -1) if double else (1,)):
        tip = c + sign * arm
        base = tip - sign * head
        d.polygon([(tip * SS, c * SS), (base * SS, (c - head * 0.75) * SS), (base * SS, (c + head * 0.75) * SS)],
                  fill=AMBER)
    img = img.rotate(angle, resample=Image.Resampling.BICUBIC, center=(c * SS, c * SS))
    return finish(img, size), (round(c), round(c))


def draw_fleur(size: int) -> tuple[Image.Image, tuple[int, int]]:
    img, d = canvas(size)
    c = size / 2
    w = max(1.4, size / 18)
    arm, head = 9 * size / 32, 4.2 * size / 32
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        d.line([((c - dx * arm) * SS, (c - dy * arm) * SS), ((c + dx * arm) * SS, (c + dy * arm) * SS)],
               fill=EDGE, width=int(w * 1.9 * SS))
        d.line([((c - dx * arm) * SS, (c - dy * arm) * SS), ((c + dx * arm) * SS, (c + dy * arm) * SS)],
               fill=BODY, width=int(w * SS))
        tip = (c + dx * arm)
        if dx:
            d.polygon([(tip * SS, c * SS), ((tip - dx * head) * SS, (c - head * 0.75) * SS),
                       ((tip - dx * head) * SS, (c + head * 0.75) * SS)], fill=AMBER)
        else:
            d.polygon([(c * SS, tip * SS), ((c - head * 0.75) * SS, (tip - dy * head) * SS),
                       ((c + head * 0.75) * SS, (tip - dy * head) * SS)], fill=AMBER)
    d.ellipse([(c - 2) * SS, (c - 2) * SS, (c + 2) * SS, (c + 2) * SS], fill=AMBER)
    return finish(img, size), (round(c), round(c))


def draw_busy(size: int, step: int) -> tuple[Image.Image, tuple[int, int]]:
    """The gauge arc from our mark, spinning — eight frames."""
    img, d = canvas(size)
    m = 4 * size / 32
    r = 12 * size / 32
    box = [m * SS, m * SS, (m + 2 * r) * SS, (m + 2 * r) * SS]
    ring = int(max(1.8, size / 13) * SS)
    d.ellipse(box, outline=(11, 15, 20, 150), width=ring)
    start = -90 + step * 45
    d.arc(box, start=start, end=start + 160, fill=AMBER, width=int(max(2.6, size / 7.5) * SS))
    return finish(img, size), (round(m + r), round(m + r))


def draw_question(size: int) -> tuple[Image.Image, tuple[int, int]]:
    """Help cursor: a bold question mark, drawn edge-first so it reads on light and dark.

    A disc with a tiny "?" inside (first draft) turned to mush below 32 px, so the mark
    uses the whole canvas instead.
    """
    img, d = canvas(size)
    sc = size / 32
    arc_box = [10.5 * sc * SS, 3.6 * sc * SS, 21.5 * sc * SS, 15.4 * sc * SS]
    stroke = int(max(2.6, sc * 3.4) * SS)
    edge = stroke + int(max(1.2, sc * 1.2) * SS)

    for colour, width in ((EDGE, edge), (AMBER, stroke)):
        d.arc(arc_box, start=205, end=352, fill=colour, width=width)
        d.line([(16 * sc * SS, 15.2 * sc * SS), (16 * sc * SS, 19.6 * sc * SS)],
               fill=colour, width=width)
    dot = [(16 - 1.85) * sc * SS, 23.2 * sc * SS, (16 + 1.85) * sc * SS, (23.2 + 3.7) * sc * SS]
    d.ellipse(dot, fill=EDGE)
    d.ellipse([dot[0] + sc * 1.1, dot[1] + sc * 1.1, dot[2] - sc * 1.1, dot[3] - sc * 1.1], fill=AMBER)
    return finish(img, size), (round(16 * sc), round(16 * sc))


# name -> (frames, hotspot per frame)
def build_variants() -> dict[str, list[tuple[Image.Image, tuple[int, int]]]]:
    variants: dict[str, list[tuple[Image.Image, tuple[int, int]]]] = {}

    def add(name, fn):
        variants[name] = [fn(size) for size in SIZES]

    add("left_ptr", draw_arrow)
    add("left_ptr_watch", draw_arrow)   # replaced below with arrow + busy badge
    add("xterm", draw_xterm)
    add("crosshair", draw_crosshair)
    add("hand2", lambda s: draw_hand(s, closed=False))
    add("hand1", lambda s: draw_hand(s, closed=True))
    add("grabbing", lambda s: draw_hand(s, closed=True))
    add("forbidden", draw_forbidden)
    add("question_arrow", draw_question)
    add("fleur", draw_fleur)
    add("sb_h_double_arrow", lambda s: draw_resize(s, 0))
    add("sb_v_double_arrow", lambda s: draw_resize(s, 90))
    add("top_left_corner", lambda s: draw_resize(s, 135))
    add("top_right_corner", lambda s: draw_resize(s, 45))
    add("bottom_left_corner", lambda s: draw_resize(s, 225))
    add("bottom_right_corner", lambda s: draw_resize(s, 315))
    add("sb_left_arrow", lambda s: draw_resize(s, 180, double=False))
    add("sb_right_arrow", lambda s: draw_resize(s, 0, double=False))
    add("sb_up_arrow", lambda s: draw_resize(s, 270, double=False))
    add("sb_down_arrow", lambda s: draw_resize(s, 90, double=False))

    # animated busy cursor: 8 frames per size
    for name, base in (("watch", None), ("progress", None)):
        frames = []
        for size in SIZES:
            for step in range(8):
                frames.append(draw_busy(size, step))
        variants[name] = frames

    # arrow + spinning badge for "background busy": arrow at 80% top-left, ring bottom-right
    busy_frames = []
    for size in SIZES:
        for step in range(8):
            arrow, _hot = draw_arrow(size)
            inner = max(12, int(size * 0.78))
            small = arrow.resize((inner, inner), Image.Resampling.LANCZOS)
            canvas_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            canvas_img.alpha_composite(small, (0, 0))
            badge_size = max(10, int(size * 0.46))
            badge_src, _ = draw_busy(64, step)
            badge = badge_src.resize((badge_size, badge_size), Image.Resampling.LANCZOS)
            canvas_img.alpha_composite(badge, (size - badge_size, size - badge_size))
            hotspot = (round(4.6 * size / 32), round(2.6 * size / 32))
            busy_frames.append((canvas_img, hotspot))
    variants["left_ptr_watch"] = busy_frames
    return variants



# --------------------------------------------------------------------------- XCursor writer
# xcursorgen is not installed everywhere (and is one more build dependency), so the binary
# format is written here directly: magic header, one TOC entry per image, then the image
# chunks. Layout from /usr/include/X11/Xcursor/Xcursor.h.
XCURSOR_MAGIC = 0x72756358
XCURSOR_VERSION = 0x00010000
IMAGE_TYPE = 0xFFFD0002
CHUNK_HEADER_SIZE = 36
TOC_ENTRY_SIZE = 12
HEADER_SIZE = 16
FRAME_DELAY_MS = 50


def write_xcursor(path: Path, frames: list[tuple[int, Image.Image, tuple[int, int]]]) -> None:
    offsets, chunks, offset = [], [], HEADER_SIZE + TOC_ENTRY_SIZE * len(frames)
    for nominal, img, (hx, hy) in frames:
        width, height = img.size
        # little-endian 0xAARRGGBB is byte order B,G,R,A — PIL writes exactly that
        pixels = img.convert("RGBA").tobytes("raw", "BGRA")
        chunk = struct.pack(
            "<9I", CHUNK_HEADER_SIZE, IMAGE_TYPE, nominal, 1, width, height, hx, hy,
            FRAME_DELAY_MS) + pixels
        offsets.append((nominal, offset))
        chunks.append(chunk)
        offset += len(chunk)
    with open(path, "wb") as handle:
        handle.write(struct.pack("<4I", XCURSOR_MAGIC, HEADER_SIZE, XCURSOR_VERSION, len(frames)))
        for nominal, position in offsets:
            handle.write(struct.pack("<3I", IMAGE_TYPE, nominal, position))
        for chunk in chunks:
            handle.write(chunk)


ALIASES = {
    "default": "left_ptr", "arrow": "left_ptr", "top_left_arrow": "left_ptr",
    "pointer": "hand2", "text": "xterm", "vertical-text": "xterm",
    "cross": "crosshair", "cross_reverse": "crosshair", "tcross": "crosshair",
    "move": "fleur", "all-scroll": "fleur", "size_all": "fleur",
    "col-resize": "sb_h_double_arrow", "row-resize": "sb_v_double_arrow",
    "ew-resize": "sb_h_double_arrow", "ns-resize": "sb_v_double_arrow",
    "nwse-resize": "top_left_corner", "nesw-resize": "top_right_corner",
    "not-allowed": "forbidden", "no-drop": "forbidden", "crossed_circle": "forbidden",
    "help": "question_arrow", "left_side": "sb_left_arrow", "right_side": "sb_right_arrow",
    "top_side": "sb_up_arrow", "bottom_side": "sb_down_arrow",
    "openhand": "hand1", "closedhand": "hand1", "dnd-none": "hand1", "dnd-move": "hand2",
    "dnd-copy": "hand2", "dnd-link": "hand2", "dnd-ask": "hand2",
    "wait": "watch", "half-busy": "progress", "00000000000000020006000b00000001": "left_ptr_watch",
}


def main() -> int:
    theme = OUT / "Parametral"
    if theme.exists():
        shutil.rmtree(theme)
    (theme / "cursors").mkdir(parents=True)

    variants = build_variants()
    for name, frames in variants.items():
        packed = [(len(frames) and img.size[0], img, hotspot) for img, hotspot in frames]
        write_xcursor(theme / "cursors" / name, packed)

    for alias, target in ALIASES.items():
        link = theme / "cursors" / alias
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target)

    (theme / "index.theme").write_text(
        "[Icon Theme]\nName=Parametral\nComment=Parametral OS cursors — graphite body, amber rim\n"
        "Inherits=Adwaita\nDirectories=\n")

    count = len(list((theme / "cursors").iterdir()))
    print(f"built {count} cursor files in {theme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
