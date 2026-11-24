#!/usr/bin/env python3
"""Generate shell/Theme.js from branding/tokens.json.

Why a JS library and not a QML singleton: a real singleton needs a qmldir in the config
directory, and Quickshell synthesises that file itself — shipping our own is fragile across
versions. A `.pragma library` module is imported once per engine and shared by every file that
imports it, which is the property we actually want: one place to change a colour.

    python3 scripts/gen_theme.py        # rewrite shell/Theme.js
    python3 scripts/gen_theme.py --check  # exit 1 if the checked-in file is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "branding" / "tokens.json"
OUTPUT = ROOT / "shell" / "Theme.js"

HEADER = """// GENERATED FILE — do not edit. Source: branding/tokens.json, generator: scripts/gen_theme.py
.pragma library

"""


def js(value: object) -> str:
    """Render a JSON scalar or array as a JavaScript literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(js(item) for item in value) + "]"
    raise TypeError(f"cannot render {type(value).__name__} in Theme.js")


def rgba(hex_colour: str, alpha_token: str) -> str:
    """Build the translucent stroke expression from a token colour, not a copied hex."""
    raw = hex_colour.lstrip("#")
    r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
    return f'"rgba({r}, {g}, {b}, " + {alpha_token} + ")"'


def render(tokens: dict) -> str:
    colour = tokens["colour"]
    light = tokens["light"]
    lines = [HEADER]

    lines.append("// ---- dark (default) -------------------------------------------------------")
    for name, value in colour.items():
        lines.append(f"var {name} = {js(value)}")
    lines.append("")

    lines.append("// ---- light ----------------------------------------------------------------")
    for name, value in light.items():
        suffix = name[0].upper() + name[1:]
        lines.append(f"var light{suffix} = {js(value)}")
    lines.append("")

    lines.append("// ---- metrics --------------------------------------------------------------")
    for name, value in tokens["metric"].items():
        lines.append(f"var {name} = {js(value)}")
    lines.append("")

    lines.append("// ---- type -----------------------------------------------------------------")
    for name, value in tokens["type"].items():
        lines.append(f"var {name} = {js(value)}")
    lines.append("")

    lines.append("// derived: the translucent strokes the shell uses everywhere")
    lines.append(f"var edge = {rgba(colour['amber'], 'edgeAlpha')}")
    lines.append(f"var hairline = {rgba(colour['muted'], 'hairlineAlpha')}")
    lines.append(f"var selection = {rgba(colour['amber'], 'selectionTint')}")
    lines.append(f"var lightEdge = {rgba(light['primary'], 'lightEdgeAlpha')}")
    lines.append(f"var lightHairline = {rgba(light['muted'], 'lightHairlineAlpha')}")
    lines.append(f"var lightSelection = {rgba(light['primary'], 'lightSelectionTint')}")
    lines.append("")

    lines.append("// compatibility aliases — shell.qml migrates to the explicit names in T6.")
    lines.append("// Do not add new uses; the design spec calls the tokens radiusPanel / radiusRow /")
    lines.append("// barSideGap / panelRow.")
    lines.append("var radius = radiusPanel")
    lines.append("var radiusSmall = radiusRow")
    lines.append("var barMargin = barSideGap")
    lines.append("var rowHeight = panelRow")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    tokens = json.loads(TOKENS.read_text())
    rendered = render(tokens)

    if "--check" in sys.argv:
        current = OUTPUT.read_text() if OUTPUT.exists() else ""
        if current != rendered:
            print(f"{OUTPUT.relative_to(ROOT)} is stale — run scripts/gen_theme.py")
            return 1
        print("Theme.js is up to date")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered)
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
