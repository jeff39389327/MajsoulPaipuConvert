# -*- coding: utf-8 -*-
"""差分測試：比對 tensoul 直出 mjai vs mjai-reviewer 參考輸出（四麻）。"""
import asyncio, gzip, json, os, sys
sys.path.append("tensoul-py-ng")
import ms_patch
ms_patch.ensure_ms_cfg()
from tensoul import MajsoulPaipuDownloader
import dotenv

UUID = sys.argv[1] if len(sys.argv) > 1 else "260602-d007ec54-c808-42eb-8d78-3a5829cce84c"
REF = f"mahjong_logs/mjai/{UUID}.json.gz"


def norm(ev):
    """去掉只在某一方出現、不影響語意的欄位，方便比對。"""
    ev = dict(ev)
    ev.pop("kyoku_first", None)
    ev.pop("aka_flag", None)
    ev.pop("think_ms", None)
    return ev


async def main():
    dotenv.load_dotenv("config.env")
    acc = os.getenv("ms_username"); pw = os.getenv("ms_password")
    async with MajsoulPaipuDownloader() as dl:
        await ms_patch.login(dl, acc, pw)
        ms_patch.patch_downloader(dl)
        result = await dl.download(UUID)
    if result.get("is_error"):
        print("download error:", result); return
    mine = result["log"]["mjai"]

    ref = [json.loads(l) for l in gzip.open(REF, "rt", encoding="utf-8").read().splitlines() if l.strip()]

    print(f"mine={len(mine)} events  ref={len(ref)} events")
    mism = 0
    for i in range(max(len(mine), len(ref))):
        a = norm(mine[i]) if i < len(mine) else None
        b = norm(ref[i]) if i < len(ref) else None
        if a != b:
            mism += 1
            print(f"--- mismatch #{mism} at index {i} ---")
            print("  mine:", json.dumps(a, ensure_ascii=False))
            print("  ref :", json.dumps(b, ensure_ascii=False))
            if mism >= 25:
                print("... (stop at 25)"); break
    if mism == 0:
        print("✓ IDENTICAL — 四麻 mjai 與 mjai-reviewer 完全一致")
    else:
        print(f"共 {mism} 處差異（前 25）")

asyncio.run(main())
