#!/usr/bin/env python3
"""Tiny markdown to HTML for long-form essays: headings, lists, blockquotes, links, emphasis.
Usage: python3 tools/md2html.py input.md output.html
"""
import re, html, sys


def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r'\[([^\]]+)\]\((https?://[^)\s]+)\)',
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'(?<![\w*])\*([^*\n]+)\*(?![\w*])', r'<em>\1</em>', t)
    return t


CSS = """
:root{color-scheme:light dark}
body{margin:0;padding:48px 20px 140px;background:#faf9f7;color:#1c1b19;
 font:17px/1.72 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}
main{max-width:44rem;margin:0 auto}
h1{font-size:2.1rem;line-height:1.2;margin:0 0 .4rem;letter-spacing:-.01em}
h2{font-size:1.42rem;margin:2.6rem 0 .8rem;padding-bottom:.35rem;border-bottom:1px solid #ded9d0}
h3{font-size:1.1rem;margin:1.8rem 0 .5rem;color:#4a4741}
p{margin:0 0 1rem}
blockquote{margin:1.4rem 0;padding:.2rem 0 .2rem 1.1rem;border-left:3px solid #b9b1a3;
 color:#4a4741;font-style:italic}
ul,ol{margin:0 0 1rem;padding-left:1.4rem}
li{margin:.35rem 0}
a{color:#1d5b8f;text-decoration:underline;text-decoration-thickness:.06em;text-underline-offset:.12em}
strong{font-weight:700}
@media (prefers-color-scheme:dark){body{background:#191817;color:#e8e4dc}
 h3{color:#bdb7ab}h2{border-color:#3a3733}blockquote{color:#bdb7ab;border-color:#6a645a}
 a{color:#8fc0ea}}
"""


def convert(src):
    out, buf, mode = [], [], None
    def flush():
        nonlocal buf, mode
        if not buf:
            return
        if mode == 'ul':
            out.append('<ul>' + ''.join(f'<li>{inline(x)}</li>' for x in buf) + '</ul>')
        elif mode == 'ol':
            out.append('<ol>' + ''.join(f'<li>{inline(x)}</li>' for x in buf) + '</ol>')
        elif mode == 'quote':
            out.append('<blockquote>' + ' '.join(inline(x) for x in buf) + '</blockquote>')
        else:
            out.append('<p>' + ' '.join(inline(x) for x in buf) + '</p>')
        buf, mode = [], None

    for raw in src.split('\n'):
        line = raw.rstrip()
        if not line:
            flush(); continue
        if line.startswith('### '):
            flush(); out.append(f'<h3>{inline(line[4:])}</h3>')
        elif line.startswith('## '):
            flush(); out.append(f'<h2>{inline(line[3:])}</h2>')
        elif line.startswith('# '):
            flush(); out.append(f'<h1>{inline(line[2:])}</h1>')
        elif line.startswith('> '):
            if mode != 'quote':
                flush(); mode = 'quote'
            buf.append(line[2:])
        elif line.startswith('- '):
            if mode != 'ul':
                flush(); mode = 'ul'
            buf.append(line[2:])
        elif re.match(r'^\d+\.\s', line):
            if mode != 'ol':
                flush(); mode = 'ol'
            buf.append(re.sub(r'^\d+\.\s', '', line))
        else:
            if mode and mode != 'quote':
                flush()
            mode = mode or 'para'
            buf.append(line)
    flush()
    return '\n'.join(out)


if __name__ == '__main__':
    src = open(sys.argv[1], encoding='utf-8').read()
    title = re.search(r'^# (.+)$', src, re.M).group(1)
    body = convert(src)
    doc = (f'<!doctype html><html lang="{sys.argv[3] if len(sys.argv)>3 else "ru"}"><head>'
           f'<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>'
           f'{body}</main></body></html>')
    open(sys.argv[2], 'w', encoding='utf-8').write(doc)
    print(f'{sys.argv[2]}: {len(doc)} bytes, {len(src.split())} words')
