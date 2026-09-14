# -*- coding: utf-8 -*-
"""
Пересобирает «Sevastopol AI База.zip» по устоявшейся формуле:

    оригинал из git show 4440faa (10 html-файлов + resources/sheet.css)
    + актуальный «Sevastopol AI База.xlsx» внутри

Запуск из корня репозитория:
    .venv/bin/python tools/rebuild_zip.py
"""

import io
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGINAL_COMMIT = "4440faa"
XLSX_NAME = "Sevastopol AI База.xlsx"
ZIP_NAME = "Sevastopol AI База.zip"


def main():
    original = subprocess.check_output(
        ["git", "show", f"{ORIGINAL_COMMIT}:{ZIP_NAME}"], cwd=ROOT
    )
    xlsx_path = os.path.join(ROOT, XLSX_NAME)
    with open(xlsx_path, "rb") as f:
        xlsx_bytes = f.read()

    out_path = os.path.join(ROOT, ZIP_NAME)
    with zipfile.ZipFile(io.BytesIO(original), "r") as src, zipfile.ZipFile(
        out_path, "w", zipfile.ZIP_DEFLATED
    ) as out:
        for info in src.infolist():
            zi = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            out.writestr(zi, src.read(info.filename))
        # актуальная база внутри архива
        xlsx_info = zipfile.ZipInfo(filename=XLSX_NAME)
        xlsx_info.compress_type = zipfile.ZIP_DEFLATED
        out.writestr(xlsx_info, xlsx_bytes)

    with zipfile.ZipFile(out_path, "r") as z:
        names = z.namelist()
    print(f"✅ {ZIP_NAME} пересобран: {len(names)} файлов, xlsx внутри: {XLSX_NAME in names}")
    for n in names:
        print(f"   {n}")


if __name__ == "__main__":
    sys.exit(main())
