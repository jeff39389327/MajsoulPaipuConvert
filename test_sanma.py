# -*- coding: utf-8 -*-
"""下載一張三麻譜，檢視直出 mjai 並對照 mortal-sanma libriichi3p 的 schema 嚴格驗證。"""
import asyncio, json, os, sys
sys.path.append("tensoul-py-ng")
import ms_patch
ms_patch.ensure_ms_cfg()
from tensoul import MajsoulPaipuDownloader
import dotenv

UUID = sys.argv[1] if len(sys.argv) > 1 else "260614-1dde421e-b393-4a73-bcb1-d1c3cb394874"

HONORS = {"E", "S", "W", "N", "P", "F", "C"}
def valid_tile(t):
    if t in HONORS: return True
    if len(t) == 2 and t[0] in "123456789" and t[1] in "mps": return True
    if t in ("5mr", "5pr", "5sr"): return True
    return False

def check(events, nplayers=3):
    errs = []
    def err(i, msg): errs.append(f"[{i}] {msg}: {json.dumps(events[i], ensure_ascii=False)[:160]}")
    counts = {}
    for i, e in enumerate(events):
        t = e["type"]; counts[t] = counts.get(t, 0) + 1
        if t == "start_game":
            if len(e["names"]) != nplayers: err(i, f"names!={nplayers}")
        elif t == "start_kyoku":
            if not (1 <= e["kyoku"] <= 3): err(i, "kyoku not in 1..3")
            if e["bakaze"] not in ("E", "S", "W"): err(i, "bad bakaze")
            if not (0 <= e["oya"] <= nplayers-1): err(i, "oya oob")
            if len(e["scores"]) != nplayers: err(i, "scores len")
            if len(e["tehais"]) != nplayers: err(i, "tehais seats")
            for h in e["tehais"]:
                if len(h) != 13: err(i, "tehai!=13")
                for tt in h:
                    if not valid_tile(tt): err(i, f"bad tile {tt}")
            if not valid_tile(e["dora_marker"]): err(i, "bad dora_marker")
        elif t in ("tsumo", "dahai", "reach", "reach_accepted", "nukidora", "pon",
                   "daiminkan", "kakan", "ankan", "hora"):
            a = e["actor"]
            if not (0 <= a <= nplayers-1): err(i, f"actor {a} oob")
            if t == "nukidora" and e.get("pai") != "N": err(i, "nukidora pai!=N")
            if t in ("pon", "daiminkan"):
                if not (0 <= e["target"] <= nplayers-1): err(i, "target oob")
                if t == "pon" and len(e["consumed"]) != 2: err(i, "pon consumed!=2")
                if t == "daiminkan" and len(e["consumed"]) != 3: err(i, "dmk consumed!=3")
            if t == "kakan" and len(e["consumed"]) != 3: err(i, "kakan consumed!=3")
            if t == "ankan" and len(e["consumed"]) != 4: err(i, "ankan consumed!=4")
            if t == "hora":
                if not (0 <= e["target"] <= nplayers-1): err(i, "hora target oob")
                if "deltas" not in e or len(e["deltas"]) != nplayers: err(i, "hora deltas")
                if "ura_markers" not in e: err(i, "hora missing ura_markers")
        elif t == "chi":
            err(i, "CHI present in sanma (should never happen)")
        elif t == "ryukyoku":
            if len(e.get("deltas", [])) != nplayers: err(i, "ryukyoku deltas len")
        elif t in ("dora", "end_kyoku", "end_game"):
            pass
        else:
            err(i, f"unknown event type {t}")
    return errs, counts


async def main():
    dotenv.load_dotenv("config.env")
    acc = os.getenv("ms_username"); pw = os.getenv("ms_password")
    async with MajsoulPaipuDownloader() as dl:
        await ms_patch.login(dl, acc, pw)
        ms_patch.patch_downloader(dl)
        result = await dl.download(UUID)
    if result.get("is_error"):
        print("download error:", result); return
    log = result["log"]
    nplayers = len(log["name"])
    print(f"uuid={UUID} ratingc={log['ratingc']} nplayers={nplayers} names={log['name']}")
    print(f"rule={log['rule']}")
    ev = log["mjai"]
    print(f"mjai events: {len(ev)}")
    errs, counts = check(ev, nplayers)
    print("event counts:", counts)
    # dump a representative slice: first start_kyoku block + first nukidora + first hora
    for i, e in enumerate(ev[:8]):
        print("  ", json.dumps(e, ensure_ascii=False)[:200])
    for key in ("nukidora", "hora", "ryukyoku", "ankan", "kakan", "daiminkan", "pon", "dora"):
        for i, e in enumerate(ev):
            if e["type"] == key:
                print(f"  first {key}:", json.dumps(e, ensure_ascii=False)[:200]); break
    if errs:
        print(f"\n✗ schema 違規 {len(errs)} 處：")
        for s in errs[:30]: print("  ", s)
    else:
        print("\n✓ schema 全數通過 mortal-sanma libriichi3p 規格（三席/actor 0-2/nukidora/hora 欄位齊備）")
    # 寫出 mjai 檔供日後 libriichi3p 驗證
    os.makedirs("mahjong_logs/mjai", exist_ok=True)
    import gzip
    with gzip.open(f"mahjong_logs/mjai/{UUID}.json.gz", "wt", encoding="utf-8") as f:
        for e in ev:
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"已寫出 mahjong_logs/mjai/{UUID}.json.gz")

asyncio.run(main())
