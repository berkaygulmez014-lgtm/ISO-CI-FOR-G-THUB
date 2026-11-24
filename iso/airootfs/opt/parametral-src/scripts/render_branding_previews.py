#!/usr/bin/env python3
"""Render previews of the Parametral boot splash and login screen.

These are NOT mock-ups: each preview composites the exact background.png the real
theme loads, and draws the card with the same geometry the QML uses at 1920x1080
(u = 1). If the preview looks right, SDDM looks right.
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
BRAND = os.path.join(ROOT, "branding")

W, H = 1920, 1080
INK = (26, 26, 30)
INK_SOFT = (92, 88, 82)
AMBER = (224, 169, 59)
FIELD_BORDER = (230, 221, 204)

F_LIGHT = "/usr/share/fonts/TTF/DejaVuSans-ExtraLight.ttf"
F_REG = "/usr/share/fonts/TTF/DejaVuSans.ttf"


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def canvas(which):
    path = os.path.join(BRAND, which, "parametral", "background.png")
    return Image.open(path).convert("RGBA").resize((W, H), Image.LANCZOS)


def logo(size):
    img = Image.open(os.path.join(ASSETS, "parametral-mark-1024.png")).convert("RGBA")
    img.thumbnail((size, size), Image.LANCZOS)
    return img


def draw_spaced(draw, cx, y, text, fnt, fill, spacing=1.2):
    """Match the QML's font.letterSpacing for the wordmark."""
    widths = [draw.textlength(ch, font=fnt) for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += w + spacing


def draw_centered(draw, cx, y, text, fnt, fill):
    box = draw.textbbox((0, 0), text, font=fnt)
    draw.text((cx - (box[2] - box[0]) / 2 - box[0], y), text, font=fnt, fill=fill)
    return box[3] - box[1]


def render_boot(out):
    img = canvas("plymouth")
    mark = logo(256)
    mx, my = W // 2 - mark.width // 2, H // 2 - mark.height // 2 - 48

    halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
    halo.paste(mark, (mx, my), mark)
    img = Image.alpha_composite(img, halo.filter(ImageFilter.GaussianBlur(22)))
    img.paste(mark, (mx, my), mark)

    d = ImageDraw.Draw(img)
    for i, dx in enumerate((-46, 0, 46)):
        cy = H // 2 + 150
        r = 6 if i != 1 else 7
        a = 235 if i == 1 else 130
        d.ellipse([W // 2 + dx - r, cy - r, W // 2 + dx + r, cy + r], fill=INK + (a,))

    img.convert("RGB").save(out, quality=95)
    return out


def render_login(out):
    img = canvas("sddm")
    d = ImageDraw.Draw(img)

    f_word = font(F_LIGHT, 54)
    f_title = font(F_LIGHT, 25)
    f_field = font(F_REG, 19)
    f_btn = font(F_REG, 19)
    f_foot = font(F_LIGHT, 18)

    # --- measure the column exactly as the QML lays it out (spacing 18) ---
    word_h = d.textbbox((0, 0), "Parametral", font=f_word)[3]
    mark_s, card_w, card_h = 150, 620, 348
    col_h = mark_s + 18 + word_h + 18 + card_h
    top = (H - col_h) // 2

    mark = logo(mark_s)
    # the same halo the QML draws behind the mark, so the preview matches
    gs = int(mark_s * 1.7)
    halo = Image.open(os.path.join(BRAND, "sddm", "parametral", "logo-glow.png")).convert("RGBA")
    halo = halo.resize((gs, gs), Image.LANCZOS)
    img.alpha_composite(halo, (W // 2 - gs // 2, top + mark_s // 2 - gs // 2))
    img.paste(mark, (W // 2 - mark.width // 2, top), mark)
    d = ImageDraw.Draw(img)

    word_y = top + mark_s + 18
    draw_spaced(d, W // 2, word_y, "Parametral", f_word, INK, 1.2)

    card_x = W // 2 - card_w // 2
    card_y = word_y + word_h + 18

    # soft shadow under the card
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [card_x, card_y + 22, card_x + card_w, card_y + card_h + 26],
        radius=26, fill=(60, 50, 36, 30))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(48)))

    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle(
        [0, 0, card_w - 1, card_h - 1], radius=26,
        fill=(255, 254, 251, 252), outline=(228, 219, 202, 160), width=2)
    img.alpha_composite(card, (card_x, card_y))
    d = ImageDraw.Draw(img)

    # inner column: title, two fields, button (spacing 14), centred
    title_h = d.textbbox((0, 0), "Hoş geldiniz", font=f_title)[3]
    inner_h = title_h + 14 + 54 + 14 + 54 + 14 + 56
    iy = card_y + (card_h - inner_h) // 2
    draw_centered(d, W // 2, iy, "Hoş geldiniz", f_title, (92, 88, 82))

    field_w, field_h = 520, 54
    fx = W // 2 - field_w // 2
    fy = iy + title_h + 14

    for label, focused in (("kullanıcı", True), ("••••••••••", False)):
        d.rounded_rectangle([fx, fy, fx + field_w, fy + field_h], radius=13,
                            fill=(255, 255, 255, 255),
                            outline=AMBER if focused else FIELD_BORDER,
                            width=2 if focused else 1)
        # vertical centring for the placeholder text
        tb = d.textbbox((0, 0), label, font=f_field)
        d.text((fx + 22, fy + (field_h - (tb[3] - tb[1])) / 2 - tb[1]),
               label, font=f_field, fill=(26, 26, 30) if focused else (120, 114, 105))
        fy += field_h + 14

    d.rounded_rectangle([fx, fy, fx + field_w, fy + 56], radius=13, fill=AMBER)
    tb = d.textbbox((0, 0), "Giriş yap", font=f_btn)
    draw_centered(d, W // 2, fy + (56 - (tb[3] - tb[1])) / 2 - tb[1], "Giriş yap", f_btn, (35, 28, 16))

    draw_centered(d, W // 2, H - 28 - 22, "Parametral OS", f_foot, (138, 131, 120))

    img.convert("RGB").save(out, quality=95)
    return out


if __name__ == "__main__":
    print(render_boot(os.path.join(ASSETS, "preview-boot.png")))
    print(render_login(os.path.join(ASSETS, "preview-login.png")))
