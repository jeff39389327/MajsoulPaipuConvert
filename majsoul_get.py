# -*- coding: utf-8 -*-
"""
majsoul_get —— 純 API 登入雀魂 CN 並下載 + 轉換牌譜，**免瀏覽器、免手動 token**。

使用者只需在 config.env 填 ms_username / ms_password (雀魂 CN 帳號)，即可:
    .venv\\Scripts\\python.exe majsoul_get.py 260602-d007ec54-c808-42eb-8d78-3a5829cce84c
    .venv\\Scripts\\python.exe majsoul_get.py --file tonpuulist.txt        # 批次
輸出至 mahjong_logs/{tenhou,mjai}/。繞過 error 151 的修正集中在 ms_patch.py。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import dotenv

sys.path.append("tensoul-py-ng")
import ms_patch                      # 可攜式補丁 (繞過 151 + 自動建 ms_cfg)
ms_patch.ensure_ms_cfg()            # 必須在 import tensoul 之前
from tensoul import MajsoulPaipuDownloader
import toumajsoul as T               # 重用既有 download_single_log / process_log


async def run(uuids, base_dir):
    dotenv.load_dotenv("config.env")
    account = os.getenv("ms_username", "")
    password = os.getenv("ms_password", "")
    collect_timing = os.getenv("COLLECT_TIMING", "true").lower() == "true"
    save_raw = os.getenv("SAVE_RAW_JSON", "false").lower() == "true"
    save_debug = os.getenv("SAVE_DEBUG", "false").lower() == "true"
    if save_raw:
        collect_timing = True
    for d in (base_dir, os.path.join(base_dir, "tenhou"),
              os.path.join(base_dir, "mjai"), "temp_logs"):
        os.makedirs(d, exist_ok=True)

    async with MajsoulPaipuDownloader() as dl:
        try:
            token = await ms_patch.login(dl, account, password)
        except Exception as e:
            print(f"✗ {e}")
            return 1
        ms_patch.patch_downloader(dl)
        print(f"✓ 純 API 登入成功 (帳號 {account})；access_token={token[:12]}...")

        ok = 0
        for u in uuids:
            u = u.strip()
            if not u:
                continue
            print(f"\n下載: {u}")
            log, timing, full = await T.download_single_log(u, dl, collect_timing)
            if not log:
                print("  ✗ 下載失敗 (牌譜不存在或無權限)")
                continue
            print(f"  ✓ 下載成功，局數={len(log.get('log', []))} 玩家={log.get('name')}")
            await T.process_log(u, log, base_dir, timing, full, save_debug, save_raw)
            print(f"  ✓ 已轉換寫出 {base_dir}/{{tenhou,mjai}}/")
            ok += 1
        print(f"\n完成 {ok}/{len(uuids)}")
        return 0 if ok == len(uuids) else 1


def main():
    p = argparse.ArgumentParser(
        description="純 API 登入雀魂 CN 並下載牌譜轉 mjai (免瀏覽器，繞過 151)")
    p.add_argument("uuids", nargs="*", help="雀魂牌譜 id (可多個)")
    p.add_argument("--file", help="從檔案讀 id 清單 (每行一個)")
    p.add_argument("--base-dir", default="mahjong_logs", help="輸出根目錄")
    args = p.parse_args()
    uuids = list(args.uuids)
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            uuids.extend(line.strip() for line in f if line.strip())
    if not uuids:
        p.error("請提供至少一個牌譜 id 或 --file")
    sys.exit(asyncio.run(run(uuids, args.base_dir)))


if __name__ == "__main__":
    main()
