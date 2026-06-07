# -*- coding: utf-8 -*-
"""
mjlog_to_mjai
=============

將天鳳 (tenhou.net) 原始 mjlog XML **直接**轉成 MJAI 事件串流，
**同時支援四麻與三麻 (sanma)**。

為什麼直接轉？
--------------
* mjai-reviewer 已無法下載天鳳牌譜 (issue #163，mjlog2json.cgi 被停用)，
  且其轉換器 (convlog) **硬性拒絕三麻** (`disp.contains('三')` → NotFourPlayer)。
* 從 mjlog 直接轉 mjai 反而比 tenhou6→mjai 單純：mjlog 保留完整時序與明確
  actor，不需要 convlog 那套「從 tenhou6 反推下一位 actor」的回溯演算法。
* 本轉換器自包含、不依賴任何外部執行檔，從根本繞過 #163。

正確性如何保證
--------------
* 四麻：輸出與 mjai-reviewer (convlog) 的 mjai **逐事件語意一致** (對數十場真實牌譜驗證)。
* 三麻：依 hidacow/mjai-reviewer3p 的 mjai 規格實作 (新增 `nukidora` 事件；
  北家(第4席) tehai 以 13 張 "?" 佔位；StartGame/StartKyoku 仍維持 4 席結構)。

MJAI tile 字串: 1m..9m / 1p..9p / 1s..9s / E,S,W,N,P,F,C / 赤 5mr,5pr,5sr / 未知 ?

可當模組 (``convert(xml) -> list[dict]``)，或 CLI 輸出 mjai (一行一事件 JSON)::

    python mjlog_to_mjai.py input.mjlog.xml > out.mjai.json
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from urllib.parse import unquote

from mjlog_common import (BAKAZE, DISCARD_SEAT, DRAW_SEAT, decode_go_flags,
                          decode_meld, int_list, sc_deltas, tile136_to_mjai)

_m = tile136_to_mjai


def convert(xml_str: str) -> list:
    """將 mjlog XML 轉成 MJAI 事件 (list of dict)。支援三麻/四麻。"""
    root = ET.fromstring(xml_str.lstrip("﻿"))

    names = ["", "", "", ""]
    game_length = 0   # 0=半莊(Hanchan), 4=東風(Tonpuu)
    aka_flag = True

    events = []
    started = False
    last_draw = [None, None, None, None]
    last_discard_seat = None
    pending_agari = []        # 累積的 AGARI attrib (處理雙/三響)
    pending_ryuukyoku = None  # RYUUKYOKU attrib

    def flush_kyoku():
        """把上一局的 hora/ryukyoku 結果與 end_kyoku 補上。"""
        nonlocal pending_agari, pending_ryuukyoku
        if pending_agari:
            # 裏ドラ取最長 (雙響時可能僅一方有立直)
            ura = max((int_list(a.get("doraHaiUra", "")) for a in pending_agari),
                      key=len, default=[])
            ura_m = [_m(t) for t in ura]
            for a in pending_agari:
                events.append({
                    "type": "hora",
                    "actor": int(a["who"]),
                    "target": int(a["fromWho"]),
                    "deltas": sc_deltas(a),
                    "ura_markers": ura_m,
                })
            events.append({"type": "end_kyoku"})
            pending_agari = []
        elif pending_ryuukyoku is not None:
            events.append({"type": "ryukyoku", "deltas": sc_deltas(pending_ryuukyoku)})
            events.append({"type": "end_kyoku"})
            pending_ryuukyoku = None

    for node in root:
        tag = node.tag
        a = node.attrib

        if tag == "GO":
            flags = decode_go_flags(int(a.get("type", "0")))
            aka_flag = flags["aka"]
            game_length = 0 if flags["hanchan"] else 4   # 半莊=0, 東風=4
            continue

        if tag == "UN":
            for i in range(4):
                n = a.get(f"n{i}")
                if n is not None and not names[i]:
                    names[i] = unquote(n)
            continue

        if tag == "INIT":
            flush_kyoku()
            if not started:
                events.append({"type": "start_game", "names": names,
                               "kyoku_first": game_length, "aka_flag": aka_flag})
                started = True

            seed = int_list(a["seed"])
            ten = int_list(a["ten"])
            # tehai：四麻 4 家各 13 張(升序)；三麻第 4 家(北)以 13 張 "?" 佔位
            tehais = []
            for i in range(4):
                ids = sorted(int_list(a.get(f"hai{i}", "")))
                tehais.append([_m(t) for t in ids] if ids else ["?"] * 13)
            events.append({
                "type": "start_kyoku",
                "bakaze": BAKAZE[seed[0] // 4],
                "dora_marker": _m(seed[5]),
                "kyoku": seed[0] % 4 + 1,
                "honba": seed[1],
                "kyotaku": seed[2],
                "oya": int(a["oya"]),
                "scores": [(ten[i] if i < len(ten) else 0) * 100 for i in range(4)],
                "tehais": tehais,
            })
            last_draw = [None, None, None, None]
            last_discard_seat = None
            continue

        if not started:
            continue

        if tag == "REACH":
            who = int(a["who"])
            # step 1：宣告 (打牌前)；step 2：立直成立
            kind = "reach" if int(a.get("step", "1")) == 1 else "reach_accepted"
            events.append({"type": kind, "actor": who})
            continue

        if tag == "DORA":
            events.append({"type": "dora", "dora_marker": _m(int(a["hai"]))})
            continue

        if tag == "N":
            who = int(a["who"])
            d = decode_meld(int(a["m"]))
            k = d["kind"]
            last_draw[who] = None
            if k in ("chi", "pon", "daiminkan"):
                events.append({"type": k, "actor": who, "target": last_discard_seat,
                               "pai": _m(d["called"]),
                               "consumed": [_m(x) for x in d["consumed"]]})
            elif k == "kakan":
                events.append({"type": "kakan", "actor": who, "pai": _m(d["called"]),
                               "consumed": [_m(x) for x in d["consumed"]]})
            elif k == "ankan":
                events.append({"type": "ankan", "actor": who,
                               "consumed": [_m(x) for x in d["consumed"]]})
            elif k == "nukidora":
                events.append({"type": "nukidora", "actor": who, "pai": "N"})
            continue

        if tag == "AGARI":
            pending_agari.append(dict(a))
            continue

        if tag == "RYUUKYOKU":
            pending_ryuukyoku = dict(a)
            continue

        # 摸 / 打 (tag 名如 T110 / D75)
        head = tag[0]
        if head in DRAW_SEAT and tag[1:].isdigit():
            seat = DRAW_SEAT[head]
            tid = int(tag[1:])
            events.append({"type": "tsumo", "actor": seat, "pai": _m(tid)})
            last_draw[seat] = tid
        elif head in DISCARD_SEAT and tag[1:].isdigit():
            seat = DISCARD_SEAT[head]
            tid = int(tag[1:])
            events.append({"type": "dahai", "actor": seat, "pai": _m(tid),
                           "tsumogiri": last_draw[seat] == tid})
            last_draw[seat] = None
            last_discard_seat = seat
        # 其餘 (SHUFFLE/TAIKYOKU/BYE...) 略過

    flush_kyoku()
    if started:
        events.append({"type": "end_game"})
    return events


def _main(argv):
    if len(argv) > 1 and argv[1] not in ("-", "--"):
        with open(argv[1], "r", encoding="utf-8") as f:
            xml_str = f.read()
    else:
        xml_str = sys.stdin.read()
    for ev in convert(xml_str):
        sys.stdout.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    _main(sys.argv)
