"""
每日自動抓取統一期貨「每日數據大整理」的多份盤後報告，
PDF 會把每一頁轉成圖片，PNG/JPG 則直接下載，輸出到 docs/data/ 讓網頁顯示。

要新增或移除報告，只要修改下面的 REPORTS 清單。
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

# 網頁上的顯示順序 = 這裡的順序
#   id      ：資料夾名稱（英文，不要重複）
#   name    ：網頁上顯示的標題
#   short   ：跳轉列上的簡稱
#   keyword ：官網標題裡一定會出現的文字，用來找出這份報告
REPORTS = [
    {"id": "options",    "name": "每日期權盤後資料",     "short": "期權",   "keyword": "每日期權盤後資料"},
    {"id": "top30",      "name": "股票期貨前30大成交量", "short": "成交量", "keyword": "股票期貨前30大成交量"},
    {"id": "volatility", "name": "股票期貨波動度排序",   "short": "波動度", "keyword": "股票期貨波動度排序"},
]

OUT_DIR = Path("docs/data")
META_FILE = OUT_DIR / "latest.json"
DPI = 150
TPE = timezone(timedelta(hours=8))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
}
FILE_EXT = (".pdf", ".png", ".jpg", ".jpeg")


def scan_list_page():
    """讀取列表頁，回傳 {報告id: 最新一筆資訊}。"""
    r = requests.get(LIST_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    found = {}
    for a in soup.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        if not a["href"].lower().endswith(FILE_EXT):
            continue
        m = re.search(r"(\d{3})(\d{2})(\d{2})\s*$", title)  # 標題結尾的民國日期
        if not m:
            continue
        for rep in REPORTS:
            if rep["keyword"] in title and rep["id"] not in found:
                y, mo, d = int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))
                found[rep["id"]] = {
                    "title": title,
                    "src_url": urljoin(LIST_URL, a["href"]),
                    "date": f"{y:04d}-{mo:02d}-{d:02d}",
                    "roc_date": m.group(1) + m.group(2) + m.group(3),
                }
    return found


def save_pages(rep_id, content):
    """把下載內容存成圖片，回傳網頁要用的圖片路徑清單。"""
    tmp = OUT_DIR / f"_tmp_{rep_id}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)

    names = []
    if content.startswith(b"%PDF"):
        with fitz.open(stream=content, filetype="pdf") as doc:
            for i, page in enumerate(doc, start=1):
                name = f"p{i:02d}.jpg"
                page.get_pixmap(dpi=DPI).save(tmp / name, jpg_quality=85)
                names.append(name)
    elif content.startswith(b"\x89PNG"):
        (tmp / "p01.png").write_bytes(content)
        names.append("p01.png")
    elif content.startswith(b"\xff\xd8"):
        (tmp / "p01.jpg").write_bytes(content)
        names.append("p01.jpg")
    else:
        shutil.rmtree(tmp)
        raise ValueError("下載到的不是 PDF 或圖片")

    final = OUT_DIR / rep_id
    shutil.rmtree(final, ignore_errors=True)
    tmp.rename(final)
    return [f"data/{rep_id}/{n}" for n in names]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    old = json.loads(META_FILE.read_text("utf-8")) if META_FILE.exists() else {}
    old_map = {r["id"]: r for r in old.get("reports", [])}

    found = scan_list_page()
    if not found:
        sys.exit("列表頁一份報告都找不到，官網版面可能改了。")

    changed = "reports" not in old  # 舊版格式也要重寫一次
    result = []
    for rep in REPORTS:
        rid, info, prev = rep["id"], found.get(rep["id"]), old_map.get(rep["id"])

        if info is None:
            print(f"::warning::找不到「{rep['keyword']}」，保留上一次的資料。")
            if prev:
                result.append(prev)
            continue

        if prev and prev.get("src_url") == info["src_url"]:
            print(f"{rep['name']}：已是最新（{info['date']}）")
            result.append(prev)
            continue

        try:
            print(f"{rep['name']}：下載 {info['src_url']}")
            resp = requests.get(info["src_url"], headers=HEADERS, timeout=60)
            resp.raise_for_status()
            pages = save_pages(rid, resp.content)
        except Exception as e:
            print(f"::warning::{rep['name']} 更新失敗：{e}，保留上一次的資料。")
            if prev:
                result.append(prev)
            continue

        result.append({**info, "id": rid, "name": rep["name"], "short": rep["short"], "pages": pages})
        changed = True
        print(f"{rep['name']}：完成 {info['date']}，{len(pages)} 張圖")

    # 清掉舊版留下的資料夾，以及已從清單移除的報告
    keep = {r["id"] for r in REPORTS}
    for p in OUT_DIR.iterdir():
        if p.is_dir() and (p.name == "pages" or (p.name not in keep and not p.name.startswith("_"))):
            shutil.rmtree(p)
            changed = True

    if not changed:
        print("全部都是最新，不需更新。")
        return

    META_FILE.write_text(json.dumps({
        "updated_at": datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
        "reports": result,
    }, ensure_ascii=False, indent=2), "utf-8")
    print("latest.json 已更新")


if __name__ == "__main__":
    main()
