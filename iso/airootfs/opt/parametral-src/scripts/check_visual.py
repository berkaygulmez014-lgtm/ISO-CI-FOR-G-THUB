#!/usr/bin/env python3
"""Measure a Parametral screenshot against the design thresholds.

No third-party libraries: the PNG is decoded with zlib, the way the rest of this repo avoids
depending on Pillow. Run it on every preview before a visual task can leave review.

    python3 scripts/check_visual.py docs/previews/T6-after-1280x800-dark.png
    python3 scripts/check_visual.py <png> --surface bar --json

Thresholds (docs/DESIGN.md §10):
    amber   <= 1.2 % of the bar, <= 2.0 % of the full desktop
    palette <= 5 % of the measured UI region (wallpaper excluded)
    black   <= 35 % of the screen (near-pure black, not the token bg)
    edge    >= 8 px of empty margin around the UI content

Exit code 1 when a threshold is exceeded, so CI and the review gate can use it directly.
"""

from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "branding" / "tokens.json"

AMBER = {"#E0A93B", "#B8862B", "#8A5F14"}
NEAR = 24
AMBER_NEAR = 40
BLACK_MAX = 8
EDGE_MIN = 8
BAR_HEIGHT = 40
BAR_TOP_GAP = 6

SURFACES = {"desktop", "bar", "panel", "launcher"}


def decode_png(path: Path) -> tuple[int, int, bytes]:
    """Decode an 8-bit, non-interlaced PNG into RGB bytes."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    pos, idat = 8, b""
    width = height = depth = colour_type = None
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, colour_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or interlace != 0:
                raise ValueError(f"{path}: only 8-bit non-interlaced PNG is supported")
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if width is None or height is None:
        raise ValueError(f"{path}: missing IHDR")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour_type)
    if channels is None:
        raise ValueError(f"{path}: unsupported colour type {colour_type}")
    raw = zlib.decompress(idat)
    stride = width * channels
    out = bytearray()
    previous = bytearray(stride)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset : offset + stride])
        offset += stride
        for x in range(stride):
            left = line[x - channels] if x >= channels else 0
            up = previous[x]
            up_left = previous[x - channels] if x >= channels else 0
            if filter_type == 1:
                line[x] = (line[x] + left) & 255
            elif filter_type == 2:
                line[x] = (line[x] + up) & 255
            elif filter_type == 3:
                line[x] = (line[x] + (left + up) // 2) & 255
            elif filter_type == 4:
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                predictor = left if (pa <= pb and pa <= pc) else (up if pb <= pc else up_left)
                line[x] = (line[x] + predictor) & 255
        out += line
        previous = line
    rgb = bytearray(width * height * 3)
    for i in range(width * height):
        if channels == 3:
            rgb[i * 3 : i * 3 + 3] = out[i * 3 : i * 3 + 3]
        elif channels == 4:
            alpha = out[i * 4 + 3] / 255
            for c in range(3):
                rgb[i * 3 + c] = round(out[i * 4 + c] * alpha + 11 * (1 - alpha))
        elif channels == 1:
            rgb[i * 3 : i * 3 + 3] = bytes([out[i]] * 3)
        else:
            rgb[i * 3 : i * 3 + 3] = bytes([out[i * 2]] * 3)
    return width, height, bytes(rgb)


def hex_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))


def distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def token_colours() -> list[tuple[int, int, int]]:
    tokens = json.loads(TOKENS.read_text())
    values = set()
    for section in ("colour", "light"):
        for value in tokens[section].values():
            if isinstance(value, str) and value.startswith("#"):
                values.add(value.upper())
    return [hex_rgb(v) for v in values]


def amber_colours() -> list[tuple[int, int, int]]:
    return [hex_rgb(v) for v in AMBER]


def pixel(px: bytes, width: int, x: int, y: int) -> tuple[int, int, int]:
    offset = (y * width + x) * 3
    return px[offset], px[offset + 1], px[offset + 2]


def nearest(rgb: tuple[int, int, int], palette: list[tuple[int, int, int]]) -> float:
    return min(distance(rgb, colour) for colour in palette)


def bar_region(width: int, height: int, px: bytes, surface: tuple[int, int, int],
               background: tuple[int, int, int]) -> dict:
    """Top and bottom of the plate, measured against the page colour.

    A horizontal grid line can match the plate colour for one row, so the plate is the band
    that starts at the first surface row and ends at the first row that is page-coloured.
    """
    def surface_row(y: int) -> bool:
        count = sum(1 for x in range(width) if distance(pixel(px, width, x, y), surface) <= 8)
        return count > width * 0.5

    top = None
    for y in range(min(height, height // 4) - 2):
        if surface_row(y) and surface_row(y + 1) and surface_row(y + 2):
            top = y
            break
    if top is None:
        return {"found": False}
    bottom = top
    for y in range(top, min(height, height // 2)):
        background_count = sum(
            1 for x in range(width) if distance(pixel(px, width, x, y), background) <= 8
        )
        if background_count > width * 0.5 and y > top:
            break
        bottom = y
    mid = top + 2
    columns = [x for x in range(width) if distance(pixel(px, width, x, mid), surface) <= 8]
    if len(columns) < width * 0.5:
        mid = (top + bottom) // 2
        columns = [x for x in range(width) if distance(pixel(px, width, x, mid), surface) <= 8]
    left, right = (min(columns), max(columns)) if columns else (0, width - 1)
    return {
        "found": True,
        "top": top,
        "bottom": bottom,
        "left": left,
        "right": right,
        "height": bottom - top + 1,
        "width": right - left + 1,
    }


def amber_runs(width: int, height: int, px: bytes, ambers: list[tuple[int, int, int]]) -> list[dict]:
    """Longest horizontal amber run per row — the ruler tick widths, measured."""
    best = []
    for y in range(min(height, height // 4)):
        runs, start = [], None
        for x in range(width):
            hit = min(distance(pixel(px, width, x, y), colour) for colour in ambers) <= AMBER_NEAR
            if hit and start is None:
                start = x
            elif not hit and start is not None:
                runs.append(x - start)
                start = None
        if start is not None:
            runs.append(width - start)
        if runs:
            best.append({"y": y, "widths": sorted(runs, reverse=True)})
    return best


def measure(path: Path, surface: str) -> dict:
    width, height, px = decode_png(path)
    tokens = token_colours()
    ambers = amber_colours()
    tokens_json = json.loads(TOKENS.read_text())
    surface_rgb = hex_rgb(tokens_json["colour"]["surface"])
    background_rgb = hex_rgb(tokens_json["colour"]["bg"])
    bar = bar_region(width, height, px, surface_rgb, background_rgb)

    if surface == "bar" and bar["found"]:
        x0, x1 = bar["left"], bar["right"] + 1
        y0, y1 = bar["top"], bar["bottom"] + 1
    elif surface == "desktop" and bar["found"]:
        x0, x1 = bar["left"], bar["right"] + 1
        y0, y1 = bar["top"], bar["bottom"] + 1
    else:
        x0, x1, y0, y1 = 0, width, 0, height

    region_pixels = (x1 - x0) * (y1 - y0)
    amber = 0
    palette_out = 0
    black = 0
    palette_cache: dict[tuple[int, int, int], float] = {}
    amber_cache: dict[tuple[int, int, int], float] = {}
    for y in range(y0, y1):
        for x in range(x0, x1):
            rgb = pixel(px, width, x, y)
            if rgb not in amber_cache:
                amber_cache[rgb] = min(distance(rgb, colour) for colour in ambers)
            if amber_cache[rgb] <= AMBER_NEAR:
                amber += 1
            if rgb not in palette_cache:
                palette_cache[rgb] = nearest(rgb, tokens)
            if palette_cache[rgb] > NEAR + 8 and max(rgb) > 24:
                palette_out += 1
    for y in range(height):
        for x in range(width):
            if max(pixel(px, width, x, y)) <= BLACK_MAX:
                black += 1

    if surface == "desktop" and bar["found"]:
        content_x0, content_x1 = bar["left"], bar["right"]
        content_y0, content_y1 = bar["top"], bar["bottom"]
    else:
        content_x0, content_y0, content_x1, content_y1 = x0, y0, x1 - 1, y1 - 1
    edges = {
        "left": content_x0,
        "top": content_y0,
        "right": width - 1 - content_x1,
        "bottom": height - 1 - content_y1,
    }

    amber_limit = 1.2 if surface in {"bar"} else 2.0
    result = {
        "file": str(path),
        "surface": surface,
        "size": [width, height],
        "bar": bar,
        "amber_piksel_orani": round(100 * amber / max(1, region_pixels), 3),
        "amber_esik": amber_limit,
        "palet_disi_orani": round(100 * palette_out / max(1, region_pixels), 3),
        "palet_esik": 5.0,
        "siyah_orani": round(100 * black / (width * height), 3),
        "siyah_esik": 35.0,
        "kenar_boslugu": edges,
        "kenar_esik": EDGE_MIN,
        "bar_yuksekligi": bar.get("height"),
        "bar_ust_boslugu": bar.get("top"),
        "amber_runs": amber_runs(width, height, px, ambers)[:4],
    }
    failures = []
    if result["amber_piksel_orani"] > amber_limit:
        failures.append("amber")
    if result["palet_disi_orani"] > 5.0:
        failures.append("palette")
    if result["siyah_orani"] > 35.0:
        failures.append("black")
    edge_values = [edges["left"], edges["right"]]
    if surface not in {"bar", "desktop"}:
        edge_values += [edges["top"], edges["bottom"]]
    if min(edge_values) < EDGE_MIN:
        failures.append("edge")
    if surface in {"bar", "desktop"} and bar["found"]:
        if bar["height"] != BAR_HEIGHT:
            failures.append("bar-height")
        if abs(bar["top"] - BAR_TOP_GAP) > 1:
            failures.append("bar-top-gap")
        widths = [w for row in result["amber_runs"] for w in row["widths"]]
        if widths and max(widths) < 12:
            failures.append("amber-tick")
    result["failures"] = failures
    return result


def render_text(result: dict) -> str:
    lines = [
        f"file              {result['file']}",
        f"surface           {result['surface']}  {result['size'][0]}x{result['size'][1]}",
        f"bar               {result['bar']}",
        f"amber_piksel_orani {result['amber_piksel_orani']:.3f}%  (<= {result['amber_esik']}%)",
        f"palet_disi_orani   {result['palet_disi_orani']:.3f}%  (<= {result['palet_esik']}%)",
        f"siyah_orani        {result['siyah_orani']:.3f}%  (<= {result['siyah_esik']}%)",
        f"kenar_boslugu      {result['kenar_boslugu']}  (>= {result['kenar_esik']} px)",
        f"bar_yuksekligi     {result['bar_yuksekligi']}  (hedef {BAR_HEIGHT})",
        f"bar_ust_boslugu    {result['bar_ust_boslugu']}  (hedef {BAR_TOP_GAP})",
        f"failures           {', '.join(result['failures']) or 'yok'}",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    surface = "desktop"
    if "--surface" in argv:
        surface = argv[argv.index("--surface") + 1]
    if surface not in SURFACES:
        print(f"unknown surface {surface}; use {', '.join(sorted(SURFACES))}")
        return 2
    result = measure(path, surface)
    if "--json" in argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
