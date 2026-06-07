# -*- coding: utf-8 -*-
"""
tenhou_review
=============

下載天鳳 (tenhou.net) 牌譜並轉成 MJAI —— 取代 mjai-reviewer 已失效的內建天鳳下載，
**同時支援四麻與三麻 (sanma)**。

問題背景 (mjai-reviewer #163)
-----------------------------
mjai-reviewer 透過 ``https://tenhou.net/5/mjlog2json.cgi?{id}`` 下載天鳳牌譜，
但天鳳已停用該端點 (回傳空 body)，導致 ``mjai-reviewer <tenhou_url>`` 全面失敗；
而且 mjai-reviewer (convlog) 還**硬性拒絕三麻**。

本工具改用「仍正常」的原始 mjlog 端點 ``https://tenhou.net/0/log/?{id}``，在本地轉換：

* **四麻**：mjlog → tenhou.net/6 (``mjlog_to_tenhou6``) → ``mjai-reviewer --no-review``
  產生 MJAI (與既有 ``toumajsoul.py`` 雀魂流程使用同一支 binary、慣例一致)。
* **三麻**：mjai-reviewer 無法處理，改用自包含直轉器 ``mjlog_to_mjai``
  (含 nukidora 事件，與 hidacow/mjai-reviewer3p 慣例一致)。
* ``--direct``：四麻也改用自包含直轉器 (不需 mjai-reviewer，完全繞過 #163)。

輸出至 ``mahjong_logs/{tenhou,mjai}/``，與既有 pipeline 對齊。

用法
----
    python tenhou_review.py 2019050417gm-0029-0000-4f2a8622      # 四麻
    python tenhou_review.py "https://tenhou.net/0/?log=...&tw=3"  # 自網址抽 id
    python tenhou_review.py --file ids.txt                        # 清單檔 (三/四麻混合皆可)
    python tenhou_review.py --direct <id>                         # 四麻也用自包含直轉器
    python tenhou_review.py --tenhou6-only <id>                   # 只輸出 tenhou6 (四麻)
    python tenhou_review.py --to-mjai <id> -o out.json            # 直接印 mjai (除錯)
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

import mjlog_to_mjai
import mjlog_to_tenhou6
from mjlog_common import decode_go_flags

TENHOU_RAW_LOG = "https://tenhou.net/0/log/?{}"
DEFAULT_BASE_DIR = "mahjong_logs"
DEFAULT_MJAI_REVIEWER = os.getenv("MJAI_REVIEWER", "mjai-reviewer")

_LOG_PARAM = re.compile(r"[?&]log=([^&\s]+)")
_LOG_ID = re.compile(r"\d{10}gm-[0-9a-f]{4}-[0-9a-f]{4,}-[0-9a-f]+", re.I)
_GO_TYPE = re.compile(r"<GO[^>]*\btype=\"(\d+)\"")


def parse_log_id(token: str) -> str:
    """從 ID / URL 字串抽出天鳳 log id。"""
    token = token.strip()
    if not token:
        return ""
    m = _LOG_PARAM.search(token)
    if m:
        return m.group(1)
    m = _LOG_ID.search(token)
    if m:
        return m.group(0)
    return token


def is_sanma(xml_str: str) -> bool:
    """由 GO 的 type 位元欄位偵測三麻 (輕量 regex 預掃，用於選擇轉換路徑)。"""
    m = _GO_TYPE.search(xml_str)
    return bool(m) and decode_go_flags(int(m.group(1)))["sanma"]


def download_mjlog(log_id: str, retries: int = 3, timeout: int = 30) -> str:
    """從 tenhou.net/0/log/ 下載原始 mjlog XML。失敗或非 mjlog 內容會 raise。"""
    url = TENHOU_RAW_LOG.format(log_id)
    headers = {
        "Referer": "https://tenhou.net/",
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0 Safari/537.36"),
    }
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            body = raw.decode("utf-8", errors="replace").lstrip("﻿").strip()
            if not body:
                raise RuntimeError("天鳳回傳空內容 (此牌譜可能已被刪除，或天鳳暫時限流)")
            if "<mjloggm" not in body:
                raise RuntimeError(f"回傳非 mjlog 內容: {body[:120]!r}")
            return body
        except (urllib.error.URLError, RuntimeError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"下載 {log_id} 失敗: {last_err}")


def run_mjai_reviewer(tenhou6_path: str, mjai_out_path: str, exe: str) -> None:
    """呼叫 mjai-reviewer --no-review 把 tenhou6 轉成 mjai。"""
    cmd = [exe, "--no-review", "-i", tenhou6_path, "--mjai-out", mjai_out_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"mjai-reviewer 失敗 (returncode={result.returncode}):\n{result.stderr.strip()}")


def _mjai_line(ev):
    return json.dumps(ev, ensure_ascii=False, separators=(",", ":"))


def _write_mjai_gz(events, path):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for ev in events:
            f.write(_mjai_line(ev) + "\n")


def process_one(token: str, base_dir: str, run_mjai: bool, exe: str,
                overwrite: bool = False, force_direct: bool = False) -> bool:
    """下載 + 轉換單一牌譜。回傳是否成功。"""
    log_id = parse_log_id(token)
    if not log_id:
        print("  跳過空白項目")
        return False

    tenhou_dir = os.path.join(base_dir, "tenhou")
    mjai_dir = os.path.join(base_dir, "mjai")
    tenhou_path = os.path.join(tenhou_dir, f"{log_id}.json")
    mjai_gz = os.path.join(mjai_dir, f"{log_id}.json.gz")

    # 已存在則跳過 (避免重新下載)
    target = mjai_gz if run_mjai else tenhou_path
    if not overwrite and os.path.exists(target):
        print(f"  已存在，跳過: {log_id}")
        return True

    try:
        xml = download_mjlog(log_id)
    except Exception as e:
        print(f"  ✗ {log_id}: {e}")
        return False

    sanma = is_sanma(xml)
    use_direct = sanma or force_direct

    # === 直轉路徑 (三麻必走；四麻 --direct 可選) ===
    if use_direct:
        try:
            events = mjlog_to_mjai.convert(xml)
        except Exception as e:
            print(f"  ✗ {log_id}: 直轉 mjai 失敗: {e}")
            return False
        if not events:
            print(f"  ✗ {log_id}: 轉換後無事件 (空牌譜?)")
            return False
        os.makedirs(mjai_dir, exist_ok=True)
        _write_mjai_gz(events, mjai_gz)
        kind = "三麻" if sanma else "四麻"
        print(f"  ✓ {log_id}: [{kind}/直轉] -> {mjai_gz}")
        return True

    # === 四麻 reviewer 路徑：mjlog -> tenhou6 -> mjai-reviewer ===
    os.makedirs(tenhou_dir, exist_ok=True)
    try:
        data = mjlog_to_tenhou6.convert(xml, ref=log_id)
        if not data.get("log"):
            print(f"  ✗ {log_id}: 轉換後無對局資料 (空牌譜?)")
            return False
        with open(tenhou_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        print(f"  ✗ {log_id}: 轉換 tenhou6 失敗: {e}")
        return False

    if not run_mjai:
        print(f"  ✓ {log_id}: [四麻] tenhou6 -> {tenhou_path}")
        return True

    os.makedirs(mjai_dir, exist_ok=True)
    mjai_tmp = os.path.join(mjai_dir, f"{log_id}.mjai.tmp")
    try:
        run_mjai_reviewer(tenhou_path, mjai_tmp, exe)
        with open(mjai_tmp, "rb") as f_in, gzip.open(mjai_gz, "wb") as f_out:
            f_out.writelines(f_in)
        print(f"  ✓ {log_id}: [四麻/reviewer] -> {mjai_gz}")
        return True
    except Exception as e:
        print(f"  ✗ {log_id}: {e}  (可改用 --direct 以自包含直轉器轉換)")
        return False
    finally:
        if os.path.exists(mjai_tmp):
            os.remove(mjai_tmp)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="下載天鳳牌譜並轉成 MJAI (支援三/四麻，繞過 mjai-reviewer 已失效的天鳳下載)。")
    p.add_argument("tokens", nargs="*", help="天鳳牌譜 ID 或網址 (可多個)")
    p.add_argument("--file", help="從檔案讀取 ID/URL 清單 (每行一個)")
    p.add_argument("--base-dir", default=DEFAULT_BASE_DIR,
                   help=f"輸出根目錄 (預設 {DEFAULT_BASE_DIR})")
    p.add_argument("--tenhou6-only", action="store_true",
                   help="(四麻) 只下載+轉成 tenhou6，不跑 mjai-reviewer")
    p.add_argument("--direct", action="store_true",
                   help="四麻也用自包含直轉器 (mjlog->mjai)，不需 mjai-reviewer")
    p.add_argument("--overwrite", action="store_true", help="覆寫已存在的輸出")
    p.add_argument("--mjai-reviewer", default=DEFAULT_MJAI_REVIEWER,
                   help="mjai-reviewer 執行檔路徑 (預設讀 PATH / 環境變數 MJAI_REVIEWER)")
    p.add_argument("--delay", type=float, default=1.0,
                   help="每筆下載間延遲秒數 (對天鳳禮貌一點，預設 1.0)")
    # 除錯：把單一牌譜直接轉成 mjai 印出 / 存檔
    p.add_argument("--to-mjai", action="store_true",
                   help="只輸出 mjai (直轉，配合單一 token 與 -o)")
    p.add_argument("-o", "--output", help="--to-mjai 時的輸出檔 (預設 stdout)")
    args = p.parse_args(argv)

    tokens = list(args.tokens)
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            tokens.extend(line.strip() for line in f if line.strip())
    if not tokens:
        p.error("請提供至少一個牌譜 ID/URL，或用 --file 指定清單檔")

    # 除錯模式：單純直轉 mjai
    if args.to_mjai:
        xml = download_mjlog(parse_log_id(tokens[0]))
        events = mjlog_to_mjai.convert(xml)
        lines = "\n".join(_mjai_line(e) for e in events)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(lines + "\n")
            print(f"已輸出 mjai -> {args.output}", file=sys.stderr)
        else:
            print(lines)
        return 0

    run_mjai = not args.tenhou6_only
    mode = "四麻直轉" if args.direct else "四麻reviewer"
    print(f"待處理: {len(tokens)} 筆 | 四麻模式: {mode} | 三麻一律直轉")

    ok = 0
    for i, token in enumerate(tokens, 1):
        print(f"[{i}/{len(tokens)}] {token}")
        if process_one(token, args.base_dir, run_mjai, args.mjai_reviewer,
                        args.overwrite, args.direct):
            ok += 1
        if i < len(tokens) and args.delay > 0:
            time.sleep(args.delay)

    print(f"\n完成：{ok}/{len(tokens)} 成功")
    return 0 if ok == len(tokens) else 1


if __name__ == "__main__":
    sys.exit(main())
