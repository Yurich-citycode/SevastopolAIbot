#!/usr/bin/env python3
"""Build a print-ready A4 PDF of the "What to do in RWA" article (RU).

Page 1 is the cover illustration, the rest is an ivory print layout with the
inline photo set, a real table and clickable links.
"""

import os
import re
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image,
                                PageBreak, CondPageBreak, KeepTogether, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

ROOT = "/home/user/SevastopolAIbot/analytics"
MODE = sys.argv[1] if len(sys.argv) > 1 else "ru"
if MODE == "en":
    SRC = os.path.join(ROOT, "2026-11-02-what-to-do-in-rwa-en.md")
    OUT = os.path.join(ROOT, "what-to-do-in-rwa.pdf")
    TITLE = "So What Do You Actually Do in RWA"
    RUNNING = "SO WHAT DO YOU DO IN RWA"
    COVER_SUB = ("three questions instead of hype",
                 "the map / a 20 minute check",
                 "for whales / builders / beginners")
    COVER_TITLE = ("SO WHAT", "DO YOU DO", "IN RWA")
else:
    SRC = os.path.join(ROOT, "2026-11-02-chto-delat-v-rwa.md")
    OUT = os.path.join(ROOT, "chto-delat-v-rwa.pdf")
    TITLE = "Что же делать в RWA"
    RUNNING = "ЧТО ЖЕ ДЕЛАТЬ В RWA"
    COVER_SUB = ("три вопроса вместо хайпа",
                 "карта рынка · проверка за 20 минут",
                 "китам · билдерам · новичкам")
    COVER_TITLE = ("ЧТО ЖЕ", "ДЕЛАТЬ", "В RWA")

FDIR = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("Sans", FDIR + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("Sans-B", FDIR + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Mono", FDIR + "DejaVuSansMono.ttf"))
pdfmetrics.registerFont(TTFont("Mono-B", FDIR + "DejaVuSansMono-Bold.ttf"))

INK = colors.HexColor("#14141a")
MUTED = colors.HexColor("#6b6a66")
RULE = colors.HexColor("#d8d5cc")
PAPER = colors.HexColor("#f7f5ef")
RED = colors.HexColor("#a3231c")

PW, PH = A4
MARGIN = 22 * mm
CONTENT_W = PW - 2 * MARGIN

IMG_MAP = {
    "img/cover-ru.png": "img/print/01-cover.jpg",
    "img/rwa-02-three-questions.png": "img/print/02-tri-dveri.jpg",
    "img/rwa-05-check.png": "img/print/03-proverka.jpg",
    "img/rwa-03-stack.png": "img/print/04-pyat-sloev.jpg",
    "img/rwa-06-whales.png": "img/print/05-kity.jpg",
    "img/rwa-04-monday.png": "img/print/06-ponedelnik.jpg",
}

body = ParagraphStyle("body", fontName="Sans", fontSize=10.4, leading=16.2,
                      textColor=INK, spaceAfter=8, alignment=TA_LEFT)
lead = ParagraphStyle("lead", parent=body, fontSize=11.4, leading=18,
                      textColor=colors.HexColor("#2b2b33"))
h2 = ParagraphStyle("h2", fontName="Sans-B", fontSize=16.5, leading=20,
                    textColor=INK, spaceBefore=16, spaceAfter=10)
caption = ParagraphStyle("cap", parent=body, fontSize=8.2, leading=11,
                         textColor=MUTED, alignment=TA_CENTER)
cell = ParagraphStyle("cell", fontName="Sans", fontSize=7.6, leading=10.2,
                      textColor=INK)
cellh = ParagraphStyle("cellh", fontName="Sans-B", fontSize=7.2, leading=9.6,
                       textColor=colors.HexColor("#3d2a12"))


def inline(text):
    text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<link href="\2" color="#8a5a00">\1</link>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text


# ---------------------------------------------------------------- flowables
story = []
lines = open(SRC, encoding="utf-8").read().split("\n")
i = 0
first_para_done = False

while i < len(lines):
    ln = lines[i].rstrip()
    if not ln:
        i += 1
        continue

    m = re.match(r"^!\[[^\]]*\]\((.+?)\)\s*$", ln)
    if m:
        rel = IMG_MAP.get(m.group(1))
        if rel and rel != "img/print/01-cover.jpg":
            path = os.path.join(ROOT, rel)
            iw, ih = ImageReader(path).getSize()
            w = CONTENT_W
            h = w * ih / iw
            max_h = 96 * mm
            if h > max_h:
                h = max_h
                w = h * iw / ih
            if w > CONTENT_W:
                w = CONTENT_W
                h = w * ih / iw
            story.append(Spacer(1, 6))
            story.append(Image(path, width=w, height=h))
            story.append(Spacer(1, 12))
        i += 1
        continue

    m = re.match(r"^(#{1,3})\s+(.*)$", ln)
    if m:
        lvl = len(m.group(1))
        txt = inline(m.group(2))
        if lvl == 1:
            story.append(Paragraph(txt, ParagraphStyle(
                "t", fontName="Sans-B", fontSize=27, leading=31, textColor=INK,
                spaceAfter=14)))
        else:
            story.append(CondPageBreak(16 * mm))
            if "Карта рынка" in txt or "The map" in txt:
                story.append(PageBreak())
            story.append(Paragraph(txt, h2))
        i += 1
        continue

    if ln.startswith("|"):
        rows = []
        while i < len(lines) and lines[i].startswith("|"):
            rows.append(lines[i])
            i += 1
        cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
        head, rest = cells[0], cells[2:]
        data = [[Paragraph(inline(c), cellh) for c in head]]
        for r in rest:
            data.append([Paragraph(inline(c), cell) for c in r])
        widths = [0.22, 0.11, 0.22, 0.23, 0.22]
        t = Table(data, colWidths=[w * CONTENT_W for w in widths], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#efe9d8")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#3d2a12")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
            ("BOX", (0, 0), (-1, -1), 0.5, RULE),
            ("NOSPLIT", (0, 0), (-1, -1)),
        ]))
        story.append(Spacer(1, 4))
        story.append(KeepTogether([t]))
        story.append(Spacer(1, 12))
        continue

    style = body if first_para_done else lead
    first_para_done = True
    story.append(Paragraph(inline(ln), style))
    i += 1


# ------------------------------------------------------------------ canvas
def cover_page(canv, doc):
    """Portrait cover: typography on black, illustration bleeding along the bottom."""
    BLACK = colors.HexColor("#0b0b0c")
    IVORY = colors.HexColor("#f2f0ea")
    GREY = colors.HexColor("#9a968e")

    canv.setFillColor(BLACK)
    canv.rect(0, 0, PW, PH, stroke=0, fill=1)

    band_h = 118 * mm
    path = os.path.join(ROOT, "img/print/hero.jpg")
    iw, ih = ImageReader(path).getSize()
    scale = max(PW / iw, band_h / ih)
    w, h = iw * scale, ih * scale
    canv.saveState()
    pth = canv.beginPath()
    pth.rect(0, 0, PW, band_h)
    canv.clipPath(pth, stroke=0, fill=0)
    canv.drawImage(path, (PW - w) / 2, band_h - h, w, h, mask=None)
    canv.restoreState()

    canv.setFillColor(colors.Color(0, 0, 0, alpha=0.35))
    canv.rect(0, 0, PW, 55 * mm, stroke=0, fill=1)

    x = MARGIN
    canv.setFont("Mono", 8.5)
    canv.setFillColor(RED)
    canv.drawString(x, PH - 30 * mm, "R W A   /   N O V E M B E R   2 0 2 6")

    canv.setFillColor(IVORY)
    canv.setFont("Sans-B", 40)
    for k, line in enumerate(COVER_TITLE):
        canv.drawString(x, PH - 55 * mm - k * 17 * mm, line)

    canv.setFillColor(RED)
    canv.rect(x, PH - 108 * mm, 30 * mm, 2, stroke=0, fill=1)

    canv.setFont("Mono", 9.5)
    canv.setFillColor(GREY)
    for k, line in enumerate(COVER_SUB):
        canv.drawString(x, PH - 120 * mm - k * 7 * mm, line)

    canv.setFillColor(GREY)
    canv.setFont("Mono", 8)
    canv.drawString(x, 12 * mm, "@PavelYuRichRWA")
    canv.drawRightString(PW - MARGIN, 12 * mm, RUNNING)


def text_page(canv, doc):
    canv.setFillColor(PAPER)
    canv.rect(0, 0, PW, PH, stroke=0, fill=1)
    canv.setFillColor(RED)
    canv.rect(MARGIN, PH - 15 * mm, 26 * mm, 1.6, stroke=0, fill=1)
    canv.setFont("Mono", 7)
    canv.setFillColor(MUTED)
    canv.drawString(MARGIN, PH - 20 * mm, RUNNING)
    canv.drawRightString(PW - MARGIN, PH - 20 * mm, "@PavelYuRichRWA")
    canv.setFillColor(RULE)
    canv.rect(MARGIN, 16 * mm, CONTENT_W, 0.6, stroke=0, fill=1)
    canv.setFont("Mono", 7)
    canv.setFillColor(MUTED)
    canv.drawCentredString(PW / 2, 11 * mm, str(canv.getPageNumber() - 1))



doc = BaseDocTemplate(OUT, pagesize=A4, title=TITLE, author="@PavelYuRichRWA")
frame_cover = Frame(0, 0, PW, PH)
doc.addPageTemplates([
    PageTemplate(id="Cover", frames=[frame_cover], onPage=cover_page),
    PageTemplate(id="Text", frames=[Frame(MARGIN, 22 * mm, CONTENT_W,
                                          PH - 50 * mm, leftPadding=0,
                                          rightPadding=0, topPadding=0,
                                          bottomPadding=0)],
                 onPage=text_page),
])


def _dispatch(canv, doc):
    if canv.getPageNumber() == 1:
        cover_page(canv, doc)
    else:
        text_page(canv, doc)


story.insert(0, PageBreak())

frame = Frame(MARGIN, 22 * mm, CONTENT_W, PH - 50 * mm,
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
doc = BaseDocTemplate(OUT, pagesize=A4, title=TITLE, author="@PavelYuRichRWA")
doc.addPageTemplates([PageTemplate(id="Page", frames=[frame],
                                   onPage=_dispatch)])
doc.build(story)
print(OUT)
