# -*- coding: utf-8 -*-
"""
tenhou_normalize
================

把「從 tenhou-to-mjai release 解壓出來的牌譜資料夾」正規化成乾淨的 `.json.gz`。

為什麼需要這支？該 release 的檔案有兩個雷（實測 2024+2025 各約 18 萬檔）：

1. **副檔名是 `.mjson`** —— 內容其實是 MJAI，但副檔名跟本專案慣例 (`*.json.gz`) 不一致。
2. **壓縮方式不一致** —— 有些年份是真 gzip、有些年份其實是**純文字 JSON**（沒壓縮）。
   若只是把 `.mjson` 一律改名成 `.json.gz`，純文字那批就變成「副檔名 gzip、內容純文字」→ 任何
   gzip 工具報損壞。
3. **gzip 內嵌 FNAME 帶 `.tmp`** —— release 作者「壓到 .tmp 再改名」，header 內嵌的原始檔名是
   `xxx.mjson.gz.tmp`；7-zip / `gzip -N` 解壓時會用這個內嵌名 → 解出一堆 `.tmp`。

本工具逐檔以 **magic byte** 判斷並修正，**冪等可重跑**：

* `*.mjson` → 改名為 `*.json.gz`
* 純文字 JSON（開頭 `{` / `[`）→ 壓成真 gzip（**不寫入 FNAME**）
* 已是 gzip 但內嵌了 FNAME → 砍掉 FNAME（payload 不重壓）
* 已是 gzip 且無 FNAME → 不動

清掉 FNAME 後，解壓工具改用外層檔名去掉 `.gz` → 正確得到 `<id>.json`。

用法
----
    python tenhou_normalize.py TENHOU              # 正規化整個資料夾
    python tenhou_normalize.py path/to/2009        # 下載別年解壓後同樣跑一次
"""

from __future__ import annotations

import gzip
import os
import sys
import time


def _strip_fname(b: bytes):
    """回傳清掉 gzip FNAME 後的 bytes；若無 FNAME 回傳 None（表示不需改）。
    非單純 header（FEXTRA/FCOMMENT/FHCRC）回傳 'recompress' 字串要求改走重壓。"""
    flg = b[3]
    if not (flg & 0x08):
        return None
    if flg & (0x04 | 0x10 | 0x02):
        return "recompress"
    end = b.index(0, 10)                       # FNAME 從 offset 10 起、null 結尾
    return b[:3] + bytes([flg & ~0x08]) + b[4:10] + b[end + 1:]


def normalize_dir(d: str) -> dict:
    stats = dict(renamed=0, compressed=0, stripped=0, recompressed=0,
                 clean=0, anomaly=0, total=0)
    anomalies = []
    t0 = time.time()
    entries = [e for e in os.scandir(d)
               if e.is_file() and (e.name.endswith(".mjson") or e.name.endswith(".json.gz"))]
    stats["total"] = len(entries)
    print(f"掃描 {len(entries)} 檔 @ {d}", flush=True)

    for i, e in enumerate(entries, 1):
        name = e.name
        final = name[:-len(".mjson")] + ".json.gz" if name.endswith(".mjson") else name
        renamed = final != name
        if renamed:
            stats["renamed"] += 1
        src = e.path
        dst = os.path.join(d, final)

        with open(src, "rb") as f:
            b = f.read()

        nb = None                              # 要寫出的新 bytes；None=內容不變
        if b[:2] == b"\x1f\x8b":               # 已是 gzip
            r = _strip_fname(b)
            if r == "recompress":
                nb = gzip.compress(gzip.decompress(b), mtime=0)
                stats["recompressed"] += 1
            elif r is not None:
                nb = r
                stats["stripped"] += 1
            else:
                stats["clean"] += 1
        elif b[:1] in (b"{", b"["):            # 純文字 JSON → 壓成 gzip（gzip.compress 不寫 FNAME）
            nb = gzip.compress(b, mtime=0)
            stats["compressed"] += 1
        else:
            stats["anomaly"] += 1
            if len(anomalies) < 10:
                anomalies.append((name, b[:2]))
            continue

        if nb is None and not renamed:
            continue                           # 完全不用動
        if nb is None:                         # 只改名
            os.replace(src, dst)
        else:                                  # 寫新內容（純二進位，不會塞 FNAME）到目標名
            tmp = dst + ".nrmtmp"
            with open(tmp, "wb") as f:
                f.write(nb)
            os.replace(tmp, dst)
            if src != dst and os.path.exists(src):
                os.remove(src)

        if i % 40000 == 0:
            print(f"  ..{i}/{len(entries)} {time.time()-t0:.0f}s", flush=True)

    stats["secs"] = round(time.time() - t0)
    print("完成：" + " | ".join(f"{k}={v}" for k, v in stats.items()), flush=True)
    for n, h in anomalies:
        print("  異常:", n, h)
    return stats


def main(argv=None):
    # Windows cp950(Big5) 主控台印中文/特殊字元會 crash，強制 UTF-8。
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("用法: python tenhou_normalize.py <資料夾>", file=sys.stderr)
        return 2
    d = argv[0]
    if not os.path.isdir(d):
        print(f"找不到資料夾: {d}", file=sys.stderr)
        return 2
    normalize_dir(d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
