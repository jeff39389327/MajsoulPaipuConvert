# -*- coding: utf-8 -*-
"""
tenhou_collect
==============

收集天鳳 (tenhou.net) **鳳凰卓** 牌譜 id 清單 —— 這是 ``tenhou_review.py`` 的前置步驟
(等同雀魂流程裡 Stage 1 的角色，只是對象換成天鳳)。

資料來源
--------
天鳳把每天/每小時的對局成績放在 ``https://tenhou.net/sc/raw/`` 底下，索引由兩支 cgi 提供：

* ``list.cgi``       —— 最近約 9 天的檔案 (每小時一檔，路徑不含年份)
* ``list.cgi?old``   —— 較舊的檔案 (**每天一檔**，路徑含 ``{YYYY}/`` 子目錄)

其中 **``scc*.html.gz`` 就是鳳凰卓 (houou)** 的清單檔，每行格式：

    00:01 | 36 | 四鳳南喰赤－ | <a href="http://tenhou.net/0/?log=2026062800gm-00a9-0000-108d0ecc">牌譜</a> | players...<br>

* 第 3 欄是卓種字串，含「鳳」= 鳳凰卓；「四鳳」= 四麻、「三鳳」= 三麻 (sanma)。
* log id 就在 ``log=`` 後面。

(``sca``/``scb`` 是純成績、沒有 log 連結；``scf`` 是上級卓，皆非鳳凰卓 → 不用。)

**重要限制**：天鳳的索引只回溯到約 2026/01；更舊的鳳凰卓資料早已封進 ``scraw{year}.zip``
而那些檔案現在全部回 404 —— 也就是 2009~2025 的資料**無法再自己抓**，請改用現成的
轉好資料集 (例如 NikkeTryHard/tenhou-to-mjai 的 release)。本工具只負責**抓得到的近期缺口**。

用法
----
    # 收集 2026-02-01 ~ 今天 的鳳凰卓 id (四麻+三麻) 到 tenhou_ids.txt
    python tenhou_collect.py --start 2026-02-01 --end 2026-06-28

    python tenhou_collect.py --start 2026-02-01 --end 2026-06-28 --players 4   # 只要四麻
    python tenhou_collect.py --start 2026-06-20 --end 2026-06-28 --players 3   # 只要三麻

接著把產出的清單餵給既有下載器即可 (它四麻/三麻混合都吃)：

    python tenhou_review.py --file tenhou_ids.txt

輸出
----
預設寫到 ``tenhou_ids.txt`` (可用 --out 改)。**逐筆 append + flush**，啟動時會讀回既有檔案
去重 —— 所以可隨時中斷/續跑。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://tenhou.net/sc/raw"
DAT = BASE + "/dat/"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Referer": BASE + "/",
}

# list.cgi 內容形如  {file:'2026/scc20260201.html.gz',size:12345},
_FILE_RE = re.compile(r"file:'([^']+)'")
# scc 檔名 → 日期(8碼) 與可選的小時(2碼)；路徑可帶 {YYYY}/ 前綴
_SCC_RE = re.compile(r"(?:(\d{4})/)?scc(\d{8})(\d{2})?\.html\.gz$")
# 每行抽 log id 與卓種欄位
_LOG_RE = re.compile(r"log=([0-9A-Za-z\-]+)")


def _get(url: str, retries: int = 3, timeout: int = 30) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"下載失敗 {url}: {last}")


def build_index() -> dict:
    """讀 list.cgi 與 list.cgi?old，回傳 {date(YYYYMMDD): {'daily': path 或 None,
    'hourly': [path,...]}}，path 為相對 dat/ 的字串。"""
    idx: dict = {}
    for q in ("list.cgi", "list.cgi?old"):
        try:
            body = _get(f"{BASE}/{q}").decode("utf-8", "replace")
        except RuntimeError as e:
            print(f"[warn] 取 {q} 失敗: {e}", file=sys.stderr)
            continue
        for path in _FILE_RE.findall(body):
            m = _SCC_RE.search(path)
            if not m:
                continue
            date, hour = m.group(2), m.group(3)
            slot = idx.setdefault(date, {"daily": None, "hourly": []})
            if hour is None:
                slot["daily"] = path           # 每天一檔 (已合併整天)
            else:
                slot["hourly"].append(path)
    return idx


def _daterange(start: str, end: str):
    d0 = _dt.datetime.strptime(start, "%Y-%m-%d").date()
    d1 = _dt.datetime.strptime(end, "%Y-%m-%d").date()
    d = d0
    while d <= d1:
        yield d.strftime("%Y%m%d")
        d += _dt.timedelta(days=1)


def _parse_ids(html: str, players: str):
    """從一個 scc html 解出 (id, kind) 清單。players: '4' / '3' / 'all'。"""
    out = []
    for line in html.splitlines():
        if "鳳" not in line:            # 只要鳳凰卓
            continue
        parts = line.split(" | ")
        if len(parts) < 4:
            continue
        kind_field = parts[2]          # e.g. 四鳳南喰赤－
        if "鳳" not in kind_field:
            continue
        is_sanma = kind_field.startswith("三")
        is_yonma = kind_field.startswith("四")
        if not (is_sanma or is_yonma):
            continue
        if players == "4" and not is_yonma:
            continue
        if players == "3" and not is_sanma:
            continue
        m = _LOG_RE.search(line)
        if not m:
            continue
        out.append((m.group(1), "3p" if is_sanma else "4p"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="收集天鳳鳳凰卓牌譜 id 清單 (tenhou_review.py 的前置)")
    ap.add_argument("--start", required=True, help="起日 YYYY-MM-DD (含)")
    ap.add_argument("--end", required=True, help="迄日 YYYY-MM-DD (含)")
    ap.add_argument("--players", choices=["4", "3", "all"], default="all",
                    help="只收四麻(4)/三麻(3)/全部(all，預設)")
    ap.add_argument("--out", default="tenhou_ids.txt", help="輸出清單檔 (預設 tenhou_ids.txt)")
    ap.add_argument("--delay", type=float, default=1.0, help="每個清單檔之間的秒數 (預設 1.0)")
    args = ap.parse_args()

    # 載入既有 id 去重 (可續跑)
    seen = set()
    try:
        with open(args.out, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    seen.add(ln)
        if seen:
            print(f"[info] 既有 {len(seen)} 筆，續跑去重", file=sys.stderr)
    except FileNotFoundError:
        pass

    print("[info] 建立天鳳檔案索引 ...", file=sys.stderr)
    idx = build_index()
    if idx:
        avail = sorted(idx)
        print(f"[info] 索引可用日期範圍: {avail[0]} ~ {avail[-1]} (共 {len(avail)} 天)",
              file=sys.stderr)

    n_new = n4 = n3 = 0
    out = open(args.out, "a", encoding="utf-8")
    try:
        for date in _daterange(args.start, args.end):
            slot = idx.get(date)
            if not slot:
                print(f"[skip] {date}: 索引中無此日 (可能太舊已封存或尚未產生)", file=sys.stderr)
                continue
            # 整天合併的 daily 檔優先 (省請求)；否則用該日所有 hourly 檔
            files = [slot["daily"]] if slot["daily"] else sorted(slot["hourly"])
            day_new = 0
            for path in files:
                try:
                    raw = _get(DAT + path)
                    html = gzip.decompress(raw).decode("utf-8", "replace")
                except (RuntimeError, OSError) as e:
                    print(f"[warn] {path}: {e}", file=sys.stderr)
                    continue
                for rid, kind in _parse_ids(html, args.players):
                    if rid in seen:
                        continue
                    seen.add(rid)
                    out.write(rid + "\n")
                    n_new += 1
                    day_new += 1
                    if kind == "4p":
                        n4 += 1
                    else:
                        n3 += 1
                out.flush()
                time.sleep(args.delay)
            print(f"[ok] {date}: +{day_new} (檔 {len(files)})", file=sys.stderr)
    finally:
        out.close()

    print(f"[done] 新增 {n_new} 筆 (四麻 {n4} / 三麻 {n3})；總計 {len(seen)} 筆 → {args.out}",
          file=sys.stderr)
    print(f"[next] python tenhou_review.py --file {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
