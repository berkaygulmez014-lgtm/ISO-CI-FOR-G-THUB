"""Generate assets/parametral-mark-{dark,light}.svg from one geometry spec.

Design (the user's blue-arc language, cleaned up):
  - 20 tick slots, 18 deg apart, one contiguous run of 3 slots replaced by a solid
    blue arc segment -> "the authorised window" in the parameter ring.
  - one dot inside, on the bisector of that arc -> "the thing behind the gate".
  - everything aligned to the same slot grid: no floating cuts, no second ring,
    no dashed circle, single stroke family.
"""
import math
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

CX = CY = 50.0
TICK_INNER = 36.5
TICK_OUTER = 47.0
TICK_HALF_WIDTH = 1.6          # degrees-ish, drawn as a rotated rect
SLOTS = 20
SLOT_DEG = 360.0 / SLOTS
GATE_START_SLOT = 2            # top-right
GATE_SLOTS = 3

ARC_INNER = 35.5
ARC_OUTER = 48.5
DOT_RADIUS = 5.6
DOT_RADIUS_POS = 23.0


def polar(r, deg):
    rad = math.radians(deg - 90.0)   # 0 deg = 12 o'clock, clockwise
    return CX + r * math.cos(rad), CY + r * math.sin(rad)


def tick_rect(slot: int, width: float = 3.4, inner: float = TICK_INNER,
              outer: float = TICK_OUTER, slot_deg: float = SLOT_DEG) -> str:
    angle = slot * slot_deg
    x, y = polar(inner, angle)
    return (f'<rect x="{x - width / 2:.3f}" y="{y:.3f}" width="{width:.2f}" '
            f'height="{outer - inner:.3f}" '
            f'transform="rotate({angle:.3f} {x:.3f} {y:.3f})"/>')


def arc_path(start_deg: float, end_deg: float) -> str:
    ox1, oy1 = polar(ARC_OUTER, start_deg)
    ox2, oy2 = polar(ARC_OUTER, end_deg)
    ix2, iy2 = polar(ARC_INNER, end_deg)
    ix1, iy1 = polar(ARC_INNER, start_deg)
    large = 1 if (end_deg - start_deg) > 180 else 0
    return (f'M {ox1:.3f} {oy1:.3f} A {ARC_OUTER} {ARC_OUTER} 0 {large} 1 {ox2:.3f} {oy2:.3f} '
            f'L {ix2:.3f} {iy2:.3f} A {ARC_INNER} {ARC_INNER} 0 {large} 0 {ix1:.3f} {iy1:.3f} Z')


def make(path: str, tick_color: str, dot_color: str, arc_color: str, bg: str | None,
         slots_total: int = SLOTS, gate_slots: int = GATE_SLOTS,
         tick_width: float = 3.4, tick_inner: float = TICK_INNER,
         tick_outer: float = TICK_OUTER) -> None:
    slot_deg = 360.0 / slots_total
    gate_start = GATE_START_SLOT * slot_deg
    gate_end = (GATE_START_SLOT + gate_slots) * slot_deg
    slots = [slot for slot in range(slots_total)
             if not (GATE_START_SLOT <= slot < GATE_START_SLOT + gate_slots)]
    ticks = "".join(tick_rect(slot, tick_width, tick_inner, tick_outer, slot_deg) for slot in slots)
    mid = (gate_start + gate_end) / 2.0
    dot_x, dot_y = polar(DOT_RADIUS_POS, mid)
    background = (f'<rect width="100" height="100" fill="{bg}"/>' if bg else "")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
        'width="100" height="100" role="img" aria-label="Parametral OS">\n'
        f'  {background}\n'
        f'  <g fill="{tick_color}">{ticks}</g>\n'
        f'  <path d="{arc_path(gate_start, gate_end)}" fill="{arc_color}"/>\n'
        f'  <circle cx="{dot_x:.3f}" cy="{dot_y:.3f}" r="{DOT_RADIUS}" fill="{dot_color}"/>\n'
        '</svg>\n'
    )
    os.makedirs(OUT, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(svg)
    print("wrote", path, len(svg), "bytes")


make(os.path.join(OUT, "parametral-mark-dark.svg"),
     tick_color="#D6DAE1", dot_color="#F2F4F8", arc_color="#3B8BFF", bg=None)
make(os.path.join(OUT, "parametral-mark-light.svg"),
     tick_color="#9AA3AF", dot_color="#4B5563", arc_color="#0B63CE", bg=None)

# Favicon variant: fewer, thicker ticks so the silhouette survives 16 px.
make(os.path.join(OUT, "parametral-favicon.svg"),
     tick_color="#D6DAE1", dot_color="#F2F4F8", arc_color="#3B8BFF", bg=None,
     slots_total=12, gate_slots=3, tick_width=6.0, tick_inner=33.0, tick_outer=47.0)
