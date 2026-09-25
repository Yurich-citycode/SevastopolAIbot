# -*- coding: utf-8 -*-
"""
Пересобирает «Sevastopol AI База.zip»: html-экспорты листов + resources/sheet.css
(основа — архив из коммита ORIGINAL_COMMIT, а если он недоступен — текущий zip
в рабочей копии) и актуальный «Sevastopol AI База.xlsx» внутри.

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


def read_base_archive() -> bytes:
    try:
        return subprocess.check_output(
            ["git", "show", f"{ORIGINAL_COMMIT}:{ZIP_NAME}"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError):
        pass
    current = os.path.join(ROOT, ZIP_NAME)
    if not os.path.exists(current):
        sys.exit(
            f"❌ Нет ни коммита {ORIGINAL_COMMIT}, ни файла {ZIP_NAME} — пересобирать не из чего."
        )
    print(f"⚠️ Коммит {ORIGINAL_COMMIT} недоступен — основа: текущий {ZIP_NAME}")
    with open(current, "rb") as f:
        return f.read()


def main():
    original = read_base_archive()
    xlsx_path = os.path.join(ROOT, XLSX_NAME)
    with open(xlsx_path, "rb") as f:
        xlsx_bytes = f.read()

    out_path = os.path.join(ROOT, ZIP_NAME)
    with zipfile.ZipFile(io.BytesIO(original), "r") as src, zipfile.ZipFile(
        out_path, "w", zipfile.ZIP_DEFLATED
    ) as out:
        for info in src.infolist():
            if info.filename == XLSX_NAME:
                continue
            zi = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            out.writestr(zi, src.read(info.filename))
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
