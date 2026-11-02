#!/usr/bin/env python3
"""Table card in the article's cover style (dark, ivory type, oxblood accents).

Renders the "market map" table as a PNG so it survives X / Telegram, where real
tables do not exist. Wraps long cells by hand.
"""

from PIL import Image, ImageDraw, ImageFont

FDIR = "/usr/share/fonts/truetype/dejavu/"
SANS = FDIR + "DejaVuSans.ttf"
SANS_B = FDIR + "DejaVuSans-Bold.ttf"
MONO = FDIR + "DejaVuSansMono.ttf"

BG = (11, 11, 12)
GRID = (24, 24, 27)
RULE = (44, 44, 48)
IVORY = (242, 240, 234)
GREY = (154, 150, 142)
DIM = (110, 107, 100)
RED = (170, 36, 30)
GOLD = (201, 163, 92)

W, H = 2000, 1310
M = 90
COLS = [0.24, 0.135, 0.215, 0.225, 0.185]  # category, yield, min, exit, risk

RU = dict(
    kicker="КАРТА РЫНКА  /  НОЯБРЬ 2026",
    head=["КАТЕГОРИЯ", "ДОХОД", "МИНИМУМ", "ВЫХОД", "ГЛАВНЫЙ РИСК"],
    rows=[
        ("Трежерис и MMF", "3–5%",
         "от $5 000 у OUSG, у BUIDL институциональный",
         "ежедневное погашение по NAV", "эмитент и кастодиан"),
        ("Золото PAXG / XAUt", "ноль + DeFi-надстройки",
         "от нескольких долларов", "мгновенный, лучший вторичный рынок",
         "кастодиан и аудит слитков"),
        ("Токенизированные акции", "цена + дивиденды", "от $1 у Ondo",
         "зависит от площадки, у многих 24/7 минт",
         "брокер-держатель, юрисдикция"),
        ("Частный кредит", "8–15%", "часто от $100 000",
         "лок в месяцы, вторички почти нет", "заёмщик и андеррайтер"),
        ("Недвижимость", "7–12% ренты", "от $50", "месяцами",
         "застройщик и управляющий"),
        ("Фонды и структуры", "6–12%", "по правилам фонда",
         "по правилам фонда", "управляющий и платформа"),
    ],
    note="ДОХОДНОСТЬ ПРОПОРЦИОНАЛЬНА ТОМУ, НАСКОЛЬКО СЛОЖНО ВЫЙТИ",
    foot="@PavelYuRichRWA  ·  ЧТО ДЕЛАТЬ В RWA",
    out="/home/user/SevastopolAIbot/analytics/img/table-ru.png",
)

EN = dict(
    kicker="THE MAP  /  NOVEMBER 2026",
    head=["CATEGORY", "YIELD", "MINIMUM", "EXIT", "MAIN RISK"],
    rows=[
        ("Treasuries and MMF", "3 to 5%",
         "$5,000 at OUSG, institutional at BUIDL",
         "daily redemption at NAV", "issuer and custodian"),
        ("Gold PAXG / XAUt", "none + DeFi add-ons",
         "pennies, from a few dollars", "instant, the best secondary market",
         "custodian and bar audit"),
        ("Tokenized equities", "price + dividends", "$1 at Ondo",
         "venue dependent, 24/7 minting at many",
         "broker holding the shares, jurisdiction"),
        ("Private credit", "8 to 15%", "often $100,000",
         "lockups for months, almost no secondary", "borrower and underwriter"),
        ("Real estate", "7 to 12% rent", "$50", "months",
         "developer and manager"),
        ("Funds and structures", "6 to 12%", "per fund rules",
         "per fund rules", "manager and platform"),
    ],
    note="YIELD IS PROPORTIONAL TO HOW HARD IT IS TO LEAVE",
    foot="@PavelYuRichRWA  ·  WHAT TO DO IN RWA",
    out="/home/user/SevastopolAIbot/analytics/img/table-en.png",
)


def wrap(draw, text, font, max_w):
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        probe = (cur + " " + w).strip()
        if draw.textlength(probe, font=font) <= max_w or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def track(d, xy, text, font, fill, spacing):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + spacing
    return x - xy[0]


def render(cfg):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    for x in range(0, W, 50):
        d.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, 50):
        d.line([(0, y), (W, y)], fill=GRID, width=1)

    f_kick = ImageFont.truetype(MONO, 26)
    f_head = ImageFont.truetype(MONO, 24)
    f_cat = ImageFont.truetype(SANS_B, 37)
    f_yld = ImageFont.truetype(SANS_B, 35)
    f_cell = ImageFont.truetype(SANS, 28)
    f_note = ImageFont.truetype(MONO, 27)
    f_foot = ImageFont.truetype(MONO, 24)

    track(d, (M, 96), cfg["kicker"], f_kick, RED, spacing=6)

    content = W - 2 * M
    widths = [int(content * c) for c in COLS]
    xs, cur = [], M
    for w in widths:
        xs.append(cur)
        cur += w

    top = 190
    for i, h in enumerate(cfg["head"]):
        track(d, (xs[i], top), h, f_head,
              GOLD if i == 0 else GREY, spacing=2)
    d.line([(M, top + 52), (W - M, top + 52)], fill=RED, width=3)

    y = top + 96
    for n, row in enumerate(cfg["rows"]):
        cell_lines, heights = [], []
        for i, text in enumerate(row):
            font = (f_cat if i == 0 else f_yld if i == 1 else f_cell)
            lines = wrap(d, text, font, widths[i] - 28)
            cell_lines.append((lines, font))
            heights.append(len(lines) * (font.size + 12))

        row_h = max(heights) + 40
        if n % 2 == 0:
            d.rectangle([M - 12, y - 16, W - M + 12, y + row_h - 24],
                        fill=(15, 15, 17))

        for i, (lines, font) in enumerate(cell_lines):
            if i == 0:
                color = IVORY
            elif i == 1:
                color = GOLD
            elif i == 4:
                color = DIM
            else:
                color = GREY
            yy = y
            for ln in lines:
                d.text((xs[i], yy), ln, font=font, fill=color)
                yy += font.size + 12

        y += row_h
        d.line([(M, y - 24), (W - M, y - 24)], fill=RULE, width=1)

    y += 30
    track(d, (M, y), cfg["note"], f_note, IVORY, spacing=1)
    d.rectangle([M, y + 46, M + 120, y + 49], fill=RED)

    track(d, (M, y + 92), cfg["foot"], f_foot, DIM, spacing=1)
    img.save(cfg["out"])
    print(cfg["out"], img.size)


render(RU)
render(EN)
