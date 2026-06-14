# -*- coding: utf-8 -*-
"""用實際編譯出的 mortal-sanma libriichi3p，把 mjai 牌譜逐事件 replay 過 PlayerState，
完整對齊 libriichi/src/bin/validate_logs.rs 的合法性檢查（三人）。

任一事件不合法（can_* 不符 / update 拋例外）即視為不通過。"""
import glob
import gzip
import json
import sys

import libriichi
from libriichi import state as _state
PlayerState = _state.PlayerState

NP = libriichi.consts.NUM_PLAYERS  # 3


def load_events(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def validate_one(path):
    events = load_events(path)
    states = [PlayerState(i) for i in range(NP)]
    cans = [None] * NP  # 各家上一事件後算出的可行動 (= validate_logs 的 cans[])

    for idx, ev in enumerate(events):
        t = ev["type"]
        actor = ev.get("actor")
        # --- 行動前的合法性閘 (對齊 validate_logs.rs) ---
        if t == "dahai":
            c = cans[actor]
            assert c is not None and c.can_discard, f"line {idx+1}: fails can_discard {ev}"
        elif t == "pon":
            assert cans[actor].can_pon, f"line {idx+1}: fails can_pon {ev}"
        elif t == "daiminkan":
            assert cans[actor].can_daiminkan, f"line {idx+1}: fails can_daiminkan {ev}"
        elif t == "ankan":
            assert cans[actor].can_ankan, f"line {idx+1}: fails can_ankan {ev}"
            cand = states[actor].ankan_candidates()
            base = ev["consumed"][0].replace("r", "")  # de-aka
            assert base in cand or ev["consumed"][0] in cand, \
                f"line {idx+1}: ankan {ev['consumed']} not in {cand}"
        elif t == "kakan":
            assert cans[actor].can_kakan, f"line {idx+1}: fails can_kakan {ev}"
        elif t == "reach":
            assert cans[actor].can_riichi, f"line {idx+1}: fails can_riichi {ev}"
        elif t == "nukidora":
            assert cans[actor].can_nukidora, f"line {idx+1}: fails can_nukidora {ev}"
        elif t == "hora":
            if actor != ev["target"]:
                assert cans[actor].can_ron_agari, f"line {idx+1}: fails can_ron_agari {ev}"
            else:
                assert cans[actor].can_tsumo_agari, f"line {idx+1}: fails can_tsumo_agari {ev}"
        # --- 套用事件到三家 (update 會解析 schema 並套用狀態；非法轉移會拋例外) ---
        # 對齊 validate_logs.rs 的 update_with_keep_cans(ev, true)：announce 事件
        # (reach_accepted/dora/hora) 只套用狀態、保留上一手算出的 cans——否則「立直牌被碰」
        # 這類序列會誤判（Python 綁定的 update 預設 keep_cans=false 會重置 cans）。
        js = json.dumps(ev, ensure_ascii=False)
        keep = t in ("reach_accepted", "dora", "hora")
        for i in range(NP):
            c = states[i].update(js)
            if not keep:
                cans[i] = c
    return len(events)


def main():
    paths = sys.argv[1:]
    if not paths:
        paths = sorted(glob.glob("mahjong_logs/mjai/*.json.gz"))
    print(f"libriichi3p NUM_PLAYERS={NP} ACTION_SPACE={libriichi.consts.ACTION_SPACE}")
    ok = 0
    for p in paths:
        try:
            n = validate_one(p)
            print(f"  ✓ PASS  {p}  ({n} events)")
            ok += 1
        except Exception as e:
            print(f"  ✗ FAIL  {p}")
            print(f"        {type(e).__name__}: {e}")
    print(f"\n結果：{ok}/{len(paths)} 通過 libriichi3p PlayerState replay")
    sys.exit(0 if ok == len(paths) else 1)


if __name__ == "__main__":
    main()
