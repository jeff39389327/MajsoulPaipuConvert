# -*- coding: utf-8 -*-
"""三麻端到端驗收：解析多張三麻 uuid -> 下載(含重試/重登) -> process_log 寫 mjai
-> 逐張過實際編譯的 libriichi3p PlayerState replay。輸出通過率與 nukidora 邊界統計。"""
import asyncio, glob, gzip, json, os, re, sys, time
sys.path.append("tensoul-py-ng")
import ms_patch; ms_patch.ensure_ms_cfg()
import dotenv, requests
from tensoul import MajsoulPaipuDownloader
import toumajsoul as T
import download_recovery as DR
import libriichi
from libriichi import state as _state
PlayerState = _state.PlayerState
NP = libriichi.consts.NUM_PLAYERS

FULL = re.compile(r"\d{6}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
S = requests.Session(); S.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})


def get_sanma_uuids(n):
    now = int(time.time()); start = now - 3 * 24 * 3600
    base = "https://5-data.amae-koromo.com"
    out = []
    for mode in (26, 24, 22, 23, 25, 21):
        games = S.get(f"{base}/api/v2/pl3/games/{now}/{start}",
                      params={"limit": 40, "mode": mode, "descending": "true"}, timeout=20).json()
        for g in games:
            st = g["startTime"]
            for p in g["players"]:
                recs = S.get(f"{base}/api/v2/pl3/player_records/{p['accountId']}/{now}/{start}",
                             params={"limit": 50, "mode": mode, "descending": "true"}, timeout=20).json()
                hit = next((r.get("uuid") or r.get("_id") for r in recs
                            if FULL.fullmatch(str(r.get("uuid") or r.get("_id"))) and r.get("startTime") == st), None)
                if hit and hit not in out:
                    out.append(hit); break
                time.sleep(0.1)
            if len(out) >= n:
                return out
    return out


def validate_mjai(path):
    """回傳 (passed: bool, reason: str)。mirror validate_logs.rs (三人)。"""
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        events = [json.loads(l) for l in f if l.strip()]
    states = [PlayerState(i) for i in range(NP)]
    cans = [None] * NP
    for idx, ev in enumerate(events):
        t = ev["type"]; a = ev.get("actor")
        try:
            if t == "dahai":
                assert cans[a].can_discard, "can_discard"
            elif t == "pon":
                assert cans[a].can_pon, "can_pon"
            elif t == "daiminkan":
                assert cans[a].can_daiminkan, "can_daiminkan"
            elif t == "ankan":
                assert cans[a].can_ankan, "can_ankan"
            elif t == "kakan":
                assert cans[a].can_kakan, "can_kakan"
            elif t == "reach":
                assert cans[a].can_riichi, "can_riichi"
            elif t == "nukidora":
                assert cans[a].can_nukidora, "can_nukidora"
            elif t == "hora":
                if a != ev["target"]:
                    assert cans[a].can_ron_agari, "can_ron_agari"
                else:
                    assert cans[a].can_tsumo_agari, "can_tsumo_agari"
        except AssertionError as e:
            return False, f"line {idx+1} fails {e} ({t} actor{a})"
        # keep_cans on announce events (reach_accepted/dora/hora) — mirror validate_logs.rs
        js = json.dumps(ev, ensure_ascii=False)
        keep = t in ("reach_accepted", "dora", "hora")
        try:
            for i in range(NP):
                c = states[i].update(js)
                if not keep:
                    cans[i] = c
        except Exception as e:
            return False, f"line {idx+1} update raised: {e}"
    return True, f"{len(events)} events"


async def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    dotenv.load_dotenv("config.env")
    print(f"解析 {n} 張三麻 uuid...")
    uuids = get_sanma_uuids(n)
    print(f"取得 {len(uuids)} 張")
    base_dir = "mahjong_logs"
    os.makedirs(os.path.join(base_dir, "mjai"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "tenhou"), exist_ok=True)
    os.makedirs("temp_logs", exist_ok=True)
    accounts = DR.load_accounts({"username": os.getenv("ms_username"), "password": os.getenv("ms_password")})

    results = []
    async with MajsoulPaipuDownloader() as dl:
        session = DR.AccountSession(dl, accounts, notify=lambda c, m="": None)
        await session.ensure_login()
        print("登入成功")

        async def dlfn(u):
            return await T.download_single_log(u, dl, collect_timing=False)

        for u in uuids:
            try:
                log, timing, full, err = await DR.download_with_retry(session, dlfn, u, max_attempts=3)
            except Exception as e:
                print(f"  {u} 下載失敗 {e}"); continue
            if not log:
                print(f"  {u} 下載失敗 {err}"); continue
            await T.process_log(u, log, base_dir, None, None, False, False)
            mjp = os.path.join(base_dir, "mjai", f"{u}.json.gz")
            passed, reason = validate_mjai(mjp)
            results.append((u, passed, reason))
            print(f"  {'✓PASS' if passed else '✗FAIL'} {u}  {reason}")
            await asyncio.sleep(0.3)

    npass = sum(1 for _, p, _ in results if p)
    print(f"\n=== libriichi3p 驗收：{npass}/{len(results)} 通過 ===")
    for u, p, r in results:
        if not p:
            print(f"  FAIL {u}: {r}")

asyncio.run(main())
