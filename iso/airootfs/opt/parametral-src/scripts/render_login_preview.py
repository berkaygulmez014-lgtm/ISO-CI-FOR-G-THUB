#!/usr/bin/env python3
"""Render the login screen in both palettes, using the real background images.

This mirrors branding/sddm/parametral/Main.qml at 1920x1080 (u = 1): same geometry,
same colours, same fonts. It is a render of the design, the live proof is the VM
screenshot.
"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
THEME = os.path.join(ROOT, "branding", "sddm", "parametral")

W, H = 1920, 1080
ACCENT = (224, 169, 59)
ACCENT_DOWN = (201, 148, 47)
ACCENT_BORDER = (208, 154, 44)

F_XL = "/usr/share/fonts/TTF/DejaVuSans-ExtraLight.ttf"
F_L = "/usr/share/fonts/TTF/DejaVuSans-ExtraLight.ttf"
F_R = "/usr/share/fonts/TTF/DejaVuSans.ttf"

PALETTE = {
    "light": dict(ink=(26, 26, 30), soft=(92, 88, 82), muted=(138, 131, 120), muted2=(160, 151, 136),
                  card=(255, 254, 251), card_border=(228, 219, 202), field=(255, 255, 255),
                  field_border=(230, 221, 204), chip=(241, 232, 216), chip_border=(226, 214, 191),
                  on_accent=(35, 28, 16), border=(207, 195, 173)),
    "dark": dict(ink=(242, 237, 228), soft=(185, 177, 164), muted=(142, 135, 123), muted2=(125, 118, 107),
                 card=(23, 26, 31), card_border=(43, 48, 55), field=(16, 19, 23),
                 field_border=(46, 52, 60), chip=(32, 36, 42), chip_border=(51, 58, 67),
                 on_accent=(26, 21, 9), border=(49, 55, 63)),
}


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def draw_centered(d, cx, y, text, fnt, fill):
    box = d.textbbox((0, 0), text, font=fnt)
    d.text((cx - (box[2] - box[0]) / 2 - box[0], y), text, font=fnt, fill=fill)
    return box[3] - box[1]


def draw_spaced(d, cx, y, text, fnt, fill, spacing=1.2):
    widths = [d.textlength(c, font=fnt) for c in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = cx - total / 2
    for c, w in zip(text, widths):
        d.text((x, y), c, font=fnt, fill=fill)
        x += w + spacing
    return d.textbbox((0, 0), text, font=fnt)[3]


def render(mode, out):
    p = PALETTE[mode]
    bg = "background.png" if mode == "light" else "background-dark.png"
    img = Image.open(os.path.join(THEME, bg)).convert("RGBA").resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(img)

    # clock / date, top-left
    d.text((64, 52), "19:41", font=font(F_XL, 56), fill=p["ink"])
    d.text((64, 118), "Perşembe, 19 Kasım", font=font(F_L, 16), fill=p["muted"])

    # footer, bottom-left
    d.text((64, H - 62), "Parametral OS", font=font(F_L, 16), fill=p["muted"])

    # controls, bottom-right — text buttons, exactly as the QML draws them
    labels = ["Yeniden", "Kapat", "Açık tema" if mode == "dark" else "Koyu tema"]
    fb = font(F_L, 15)
    x = W - 56
    for lab in labels:
        w = d.textlength(lab, font=fb)
        d.text((x - w, H - 40 - 19), lab, font=fb, fill=p["soft"])
        x -= w + 22

    # centre column
    mark = Image.open(os.path.join(THEME, "logo-large.png")).convert("RGBA")
    mark.thumbnail((150, 150), Image.LANCZOS)
    glow = Image.open(os.path.join(THEME, "logo-glow.png" if mode == "light" else "logo-glow-dark.png"))
    glow = glow.convert("RGBA").resize((233, 233), Image.LANCZOS)

    card_w, card_h = 620, 400
    title_h = d.textbbox((0, 0), "Hoş geldiniz", font=font(F_L, 24))[3]
    inner = title_h + 11 + 44 + 11 + 52 + 11 + 52 + 11 + 54
    word_h = d.textbbox((0, 0), "Parametral", font=font(F_XL, 52))[3]
    col_h = 150 + 16 + word_h + 16 + card_h
    top = (H - col_h) // 2

    img.alpha_composite(glow, (W // 2 - 116, top + 75 - 116))
    img.paste(mark, (W // 2 - mark.width // 2, top), mark)
    d = ImageDraw.Draw(img)

    word_y = top + 150 + 16
    draw_spaced(d, W // 2, word_y, "Parametral", font(F_XL, 52), p["ink"])

    card_x = W // 2 - card_w // 2
    card_y = word_y + word_h + 16

    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=26,
                                          fill=p["card"] + (255,), outline=p["card_border"] + (255,), width=1)
    img.alpha_composite(card, (card_x, card_y))
    d = ImageDraw.Draw(img)

    iy = card_y + (card_h - inner) // 2
    draw_centered(d, W // 2, iy, "Hoş geldiniz", font(F_L, 24), p["soft"])

    # two user chips
    cy = iy + title_h + 11
    chip_x = W // 2 - (44 * 2 + 8) // 2
    for i, ch in enumerate(("O", "S")):
        cx = chip_x + i * 52
        fill = ACCENT if i == 0 else p["chip"]
        edge = ACCENT_BORDER if i == 0 else p["chip_border"]
        d.ellipse([cx, cy, cx + 44, cy + 44], fill=fill, outline=edge, width=1)
        tc = p["on_accent"] if i == 0 else p["muted"]
        box = d.textbbox((0, 0), ch, font=font(F_R, 17))
        d.text((cx + 22 - (box[2] - box[0]) / 2 - box[0], cy + 22 - (box[3] - box[1]) / 2 - box[1]),
               ch, font=font(F_R, 17), fill=tc)

    fy = cy + 44 + 11
    for label, focused, dots in (("operator", True, False), ("••••••••••", False, True)):
        d.rounded_rectangle([W // 2 - 260, fy, W // 2 + 260, fy + 52], radius=13,
                            fill=p["field"], outline=ACCENT if focused else p["field_border"],
                            width=2 if focused else 1)
        box = d.textbbox((0, 0), label, font=font(F_R, 18))
        d.text((W // 2 - 260 + 22, fy + (52 - (box[3] - box[1])) / 2 - box[1]),
               label, font=font(F_R, 18), fill=p["ink"] if not dots else p["muted2"])
        if dots:
            rb = d.textbbox((0, 0), "göster", font=font(F_R, 13))
            d.text((W // 2 + 260 - 16 - (rb[2] - rb[0]), fy + (52 - (rb[3] - rb[1])) / 2 - rb[1]),
                   "göster", font=font(F_R, 13), fill=p["muted2"])
        fy += 52 + 11

    d.rounded_rectangle([W // 2 - 260, fy, W // 2 + 260, fy + 54], radius=13, fill=ACCENT)
    box = d.textbbox((0, 0), "Giriş yap", font=font(F_R, 18))
    d.text((W // 2 - (box[2] - box[0]) / 2 - box[0], fy + (54 - (box[3] - box[1])) / 2 - box[1]),
           "Giriş yap", font=font(F_R, 18), fill=p["on_accent"])

    img.convert("RGB").save(out, quality=95)
    return out


if __name__ == "__main__":
    print(render("dark", os.path.join(ASSETS, "preview-login.png")))
    print(render("light", os.path.join(ASSETS, "preview-login-light.png")))
