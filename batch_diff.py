# -*- coding: utf-8 -*-
"""批次四麻差分：抓 N 局四麻，逐局比對 tensoul 直出 mjai vs mjai-reviewer。
涵蓋 kan/ankan/kakan/daiminkan/dora/雙響等所有事件分支。"""
import asyncio, gzip, json, os, re, sys, subprocess, time, tempfile
sys.path.append("tensoul-py-ng")
import ms_patch
ms_patch.ensure_ms_cfg()
from tensoul import MajsoulPaipuDownloader
import dotenv
import requests

N = int(sys.argv[1]) if len(sys.argv) > 1 else 15
MJAI_BIN = os.environ.get("MJAI_REVIEWER_BIN", "mjai-reviewer")
FULL = re.compile(r"\d{6}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
S = requests.Session(); S.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})


def get_yonma_uuids(n):
    now = int(time.time()); start = now - 2 * 24 * 3600
    base = "https://5-data.amae-koromo.com"
    out = []
    for mode in (16, 12):  # throne / jade yonma
        games = S.get(f"{base}/api/v2/pl4/games/{now}/{start}",
                      params={"limit": 40, "mode": mode, "descending": "true"}, timeout=20).json()
        for g in games:
            st = g["startTime"]
            for p in g["players"]:
                recs = S.get(f"{base}/api/v2/pl4/player_records/{p['accountId']}/{now}/{start}",
                             params={"limit": 50, "mode": mode, "descending": "true"}, timeout=20).json()
                hit = next((r.get("uuid") or r.get("_id") for r in recs
                            if FULL.fullmatch(str(r.get("uuid") or r.get("_id"))) and r.get("startTime") == st), None)
                if hit:
                    out.append(hit); break
                time.sleep(0.1)
            if len(out) >= n: return out
    return out


def norm(ev):
    ev = dict(ev); ev.pop("kyoku_first", None); ev.pop("aka_flag", None); ev.pop("think_ms", None)
    return ev


def run_reviewer(tenhou6):
    with tempfile.TemporaryDirectory() as d:
        ip = os.path.join(d, "in.json"); op = os.path.join(d, "out.json")
        json.dump(tenhou6, open(ip, "w", encoding="utf-8"), ensure_ascii=False)
        r = subprocess.run([MJAI_BIN, "--no-review", "-i", ip, "--mjai-out", op],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr.strip()
        return [json.loads(l) for l in open(op, encoding="utf-8").read().splitlines() if l.strip()], None


async def main():
    dotenv.load_dotenv("config.env")
    acc = os.getenv("ms_username"); pw = os.getenv("ms_password")
    print(f"抓 {N} 局四麻 uuid...")
    uuids = get_yonma_uuids(N)
    print(f"取得 {len(uuids)} 局")
    seen_types = set()
    n_ident = 0; n_fail = 0; details = []
    async with MajsoulPaipuDownloader() as dl:
        await ms_patch.login(dl, acc, pw); ms_patch.patch_downloader(dl)
        for idx, u in enumerate(uuids, 1):
            try:
                result = await dl.download(u)
            except Exception as e:
                print(f"[{idx}] {u} 下載例外 {e}"); n_fail += 1; continue
            if result.get("is_error"):
                print(f"[{idx}] {u} 下載失敗 {result}"); n_fail += 1; continue
            mine = result["log"]["mjai"]
            for e in mine: seen_types.add(e["type"])
            ref, err = run_reviewer(result["log"])
            if ref is None:
                print(f"[{idx}] {u} reviewer 失敗: {err[:120]}"); n_fail += 1; continue
            mism = [i for i in range(max(len(mine), len(ref)))
                    if (norm(mine[i]) if i < len(mine) else None) != (norm(ref[i]) if i < len(ref) else None)]
            if not mism:
                n_ident += 1; print(f"[{idx}] {u} ✓ identical ({len(mine)} ev)")
            else:
                details.append((u, mine, ref, mism))
                print(f"[{idx}] {u} ✗ {len(mism)} mismatches (mine={len(mine)} ref={len(ref)})")
    print(f"\n=== 結果 ===  identical={n_ident}  mismatch={len(details)}  fail={n_fail}")
    print("出現的事件型別：", sorted(seen_types))
    for u, mine, ref, mism in details[:3]:
        print(f"\n--- {u} 前 8 處差異 ---")
        for i in mism[:8]:
            print("  idx", i, "mine:", json.dumps(norm(mine[i]) if i < len(mine) else None, ensure_ascii=False)[:140])
            print("        ref :", json.dumps(norm(ref[i]) if i < len(ref) else None, ensure_ascii=False)[:140])

asyncio.run(main())
