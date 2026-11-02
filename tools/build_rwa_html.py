#!/usr/bin/env python3
"""Build one self-contained HTML (images embedded as base64) from the RU article
markdown, so it can be opened in a browser, copied with Ctrl+A / Ctrl+C and
pasted into Telegram or a doc with formatting and links intact."""

import base64
import html
import os
import re

ROOT = "/home/user/SevastopolAIbot/analytics"
SRC = os.path.join(ROOT, "2026-11-02-chto-delat-v-rwa.md")
OUT = os.path.join(ROOT, "rwa-cto-delat.html")

IMG_MAP = {
    "img/cover-ru.png": "img/tg/01-cover.jpg",
    "img/rwa-02-three-questions.png": "img/tg/02-tri-dveri.jpg",
    "img/rwa-05-check.png": "img/tg/03-proverka.jpg",
    "img/rwa-03-stack.png": "img/tg/04-pyat-sloev.jpg",
    "img/rwa-06-whales.png": "img/tg/05-kity.jpg",
    "img/rwa-04-monday.png": "img/tg/06-ponedelnik.jpg",
}


def b64(rel):
    with open(os.path.join(ROOT, rel), "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def inline(text):
    text = html.escape(text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
                  r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


lines = open(SRC, encoding="utf-8").read().split("\n")
body, i = [], 0

while i < len(lines):
    ln = lines[i].rstrip()
    if not ln:
        i += 1
        continue

    m = re.match(r"^!\[\]\((.+?)\)$", ln)
    if m:
        rel = m.group(1)
        body.append('<figure><img src="%s" alt=""></figure>' % b64(IMG_MAP[rel]))
        i += 1
        continue

    m = re.match(r"^(#{1,3})\s+(.*)$", ln)
    if m:
        lvl = len(m.group(1))
        body.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2)), lvl))
        i += 1
        continue

    if ln.startswith("|"):
        rows = []
        while i < len(lines) and lines[i].startswith("|"):
            rows.append(lines[i])
            i += 1
        cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
        head = cells[0]
        rest = [r for r in cells[2:]]
        t = ["<table><thead><tr>"]
        t += ["<th>%s</th>" % inline(c) for c in head]
        t.append("</tr></thead><tbody>")
        for r in rest:
            t.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in r) + "</tr>")
        t.append("</tbody></table>")
        body.append("".join(t))
        continue

    body.append("<p>%s</p>" % inline(ln))
    i += 1

HEAD = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Что же делать в RWA</title>
<style>
  body { margin:0; background:#0b0b0c; color:#f2f0ea;
         font: 19px/1.62 -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
  .wrap { max-width: 780px; margin: 0 auto; padding: 56px 28px 96px; }
  h1 { font-size: 44px; line-height:1.1; letter-spacing:-.5px; margin: 40px 0 28px; }
  h2 { font-size: 27px; line-height:1.25; margin: 52px 0 18px; padding-top: 22px;
       border-top: 1px solid #26262a; }
  p { margin: 0 0 20px; }
  a { color: #e2b45a; text-decoration: none; border-bottom: 1px solid rgba(226,180,90,.35); }
  figure { margin: 34px 0 38px; }
  img { width: 100%; display:block; border-radius: 6px; }
  table { width:100%; border-collapse: collapse; margin: 26px 0 30px; font-size: 15px; }
  th, td { text-align:left; padding: 10px 12px; border-bottom: 1px solid #26262a; vertical-align: top; }
  th { color:#c9a35c; font-weight:600; font-size:13px; text-transform: uppercase; letter-spacing:.06em; }
  strong { color:#fff; }
  @media print { body { background:#fff; color:#111; } h2 { border-color:#ddd; } a { color:#8a5a00; } }
</style></head><body><div class="wrap">
"""

doc = HEAD + "\n".join(body) + "\n</div></body></html>\n"

open(OUT, "w", encoding="utf-8").write(doc)
print(OUT, round(os.path.getsize(OUT) / 1024 / 1024, 2), "MB")
