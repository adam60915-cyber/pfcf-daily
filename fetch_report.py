"""
每日自動抓取「統一期貨 ‧ 盤後數據_每日期權盤後資料」PDF，
把每一頁轉成圖片，輸出到 docs/data/ 讓網頁直接顯示。
"""
import json
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import pymupdf as fitz  # PyMuPDF
import requests
from bs4 import BeautifulSoup

LIST_URL = "https://www.pfcf.com.tw/report/l/24"
KEYWORD = "每日期權盤後資料"          # 標題關鍵字，若官網改名只要改這裡
OUT_DIR = Path("docs/data")
PAGES_DIR = OUT_DIR / "pages"
META_FILE = OUT_DIR / "latest.json"
DPI = 150                              # 圖片清晰度，手機看 150 已足夠
TPE = timezone(timedelta(hours=8))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
}


def find_report():
    """在列表頁找出標題含關鍵字的 PDF 連結與日期。"""
    r = requests.get(LIST_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    for a in soup.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        if KEYWORD in title and a["href"].lower().endswith(".pdf"):
            m = re.search(r"(\d{3})(\d{2})(\d{2})", title)  # 民國日期 1151002
            if not m:
                continue
            y, mo, d = int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))
            return {
                "title": title,
                "pdf_url": urljoin(LIST_URL, a["href"]),
                "date": f"{y:04d}-{mo:02d}-{d:02d}",
                "roc_date": m.group(0),
            }
    sys.exit(f"列表頁找不到含「{KEYWORD}」的 PDF，官網版面可能改了。")


def main():
    report = find_report()

    old = json.loads(META_FILE.read_text("utf-8")) if META_FILE.exists() else {}
    if old.get("pdf_url") == report["pdf_url"]:
        print(f"已是最新（{report['date']}），不需更新。")
        return

    print(f"下載 {report['title']}：{report['pdf_url']}")
    pdf = requests.get(report["pdf_url"], headers=HEADERS, timeout=60)
    pdf.raise_for_status()
    if not pdf.content.startswith(b"%PDF"):
        sys.exit("下載到的不是 PDF，停止更新，保留舊資料。")

    # 先輸出到暫存資料夾，全部成功才覆蓋，避免網頁顯示到一半的資料
    tmp = OUT_DIR / "_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)

    pages = []
    with fitz.open(stream=pdf.content, filetype="pdf") as doc:
        for i, page in enumerate(doc, start=1):
            name = f"p{i:02d}.jpg"
            page.get_pixmap(dpi=DPI).save(tmp / name, jpg_quality=85)
            pages.append(f"data/pages/{name}")

    shutil.rmtree(PAGES_DIR, ignore_errors=True)
    tmp.rename(PAGES_DIR)

    report["pages"] = pages
    report["updated_at"] = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
    META_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(f"完成：{report['date']} 共 {len(pages)} 張圖")


if __name__ == "__main__":
    main()
