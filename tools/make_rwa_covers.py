#!/usr/bin/env python3
"""Cover cards for the "What to do in RWA" article (RU + EN) on top of the
generated vault illustration. Layout only, no data."""

from PIL import Image, ImageDraw, ImageFont

FDIR = "/usr/share/fonts/truetype/dejavu/"
SANS_B = FDIR + "DejaVuSans-Bold.ttf"
MONO = FDIR + "DejaVuSansMono.ttf"
MONO_B = FDIR + "DejaVuSansMono-Bold.ttf"

SRC = "/home/user/SevastopolAIbot/analytics/img/rwa-01-hero.png"
IVORY = (240, 236, 226)
DIM = (150, 146, 138)
RED = (170, 32, 28)


def track(d, xy, text, font, fill, spacing=0):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + spacing
    return x - xy[0]


def cover(title_lines, sub, kicker, footer, out):
    img = Image.open(SRC).convert("RGB")
    W, H = img.size
    d = ImageDraw.Draw(img)

    # darken the left half so type sits cleanly on the illustration
    for x in range(0, int(W * 0.62)):
        a = int(232 * max(0.0, 1 - x / (W * 0.62)) ** 0.65)
        d.rectangle([x, 0, x + 1, H], fill=(0, 0, 0))
    veil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(veil)
    for x in range(0, int(W * 0.66)):
        alpha = int(245 * max(0.0, 1 - x / (W * 0.66)) ** 0.8)
        vd.rectangle([x, 0, x + 1, H], fill=(8, 8, 7, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), veil).convert("RGB")
    d = ImageDraw.Draw(img)

    M = int(W * 0.075)
    f_kick = ImageFont.truetype(MONO, int(H * 0.021))
    f_title = ImageFont.truetype(SANS_B, int(H * 0.082))
    f_sub = ImageFont.truetype(MONO, int(H * 0.024))
    f_foot = ImageFont.truetype(MONO, int(H * 0.018))

    track(d, (M, int(H * 0.115)), kicker, f_kick, RED, spacing=int(H * 0.006))

    y = int(H * 0.19)
    for line in title_lines:
        track(d, (M, y), line, f_title, IVORY, spacing=int(H * 0.004))
        y += int(H * 0.098)

    y += int(H * 0.02)
    d.rectangle([M, y, M + int(W * 0.085), y + 3], fill=RED)
    y += int(H * 0.045)
    for line in sub:
        track(d, (M, y), line, f_sub, DIM, spacing=1)
        y += int(H * 0.036)

    track(d, (M, H - int(H * 0.075)), footer, f_foot, DIM, spacing=1)

    img.save(out)
    print(out, img.size)


cover(
    ["ЧТО ЖЕ", "ДЕЛАТЬ", "В RWA"],
    ["три вопроса вместо хайпа", "карта рынка · проверка за 20 минут", "китам · билдерам · новичкам"],
    "RWA / NOVEMBER 2026",
    "@PavelYuRichRWA  ·  ЧТО ДЕЛАТЬ В RWA",
    "/home/user/SevastopolAIbot/analytics/img/cover-ru.png",
)

cover(
    ["SO WHAT", "DO YOU DO", "IN RWA"],
    ["three questions instead of hype", "the map · a 20 minute check", "for whales · builders · beginners"],
    "RWA / NOVEMBER 2026",
    "@PavelYuRichRWA  ·  SO WHAT DO YOU DO IN RWA",
    "/home/user/SevastopolAIbot/analytics/img/cover-en.png",
)
