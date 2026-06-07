# -*- coding: utf-8 -*-
"""
mjlog_common
============

天鳳 mjlog 轉換器共用的底層原語 (tile 編碼、鳴牌 `m` 位元欄位解碼、GO 規則旗標、
座位常數)。被 ``mjlog_to_tenhou6`` 與 ``mjlog_to_mjai`` 共用，避免那段最容易出錯的
位元運算在兩處各維護一份而悄悄分歧。

* tile id (0-135) 編碼：天鳳原始 tile id，赤五固定為 16(0m)/52(0p)/88(0s)。
* 鳴牌 `m` 解碼採用天鳳官方 tehai.js 演算法 (參考 mthrok/tenhou-log-utils)，
  ``decode_meld`` 回傳結構化的 tile id + kui，由各轉換器各自格式化。
"""

from __future__ import annotations

# 摸 / 打 的 tag 首字母 -> 座位
DRAW_SEAT = {"T": 0, "U": 1, "V": 2, "W": 3}
DISCARD_SEAT = {"D": 0, "E": 1, "F": 2, "G": 3}
# 場風 (seed.kyoku_num // 4)
BAKAZE = ["E", "S", "W", "N"]

# 天鳳原始 tile id 中的赤五
_AKA_T6 = {16: 51, 52: 52, 88: 53}        # -> tenhou.net/6 編碼
_AKA_MJAI = {16: "5mr", 52: "5pr", 88: "5sr"}  # -> MJAI 字串
_HONOR = ["E", "S", "W", "N", "P", "F", "C"]


def int_list(s):
    """逗號分隔整數字串 -> list[int] (空字串 -> [])。"""
    return [int(x) for x in s.split(",")] if s else []


def tile136_to_t6(tid: int) -> int:
    """天鳳原始 tile id (0-135) -> tenhou.net/6 編碼 (11-19/21-29/31-39/41-47, 赤 51/52/53)。"""
    if tid in _AKA_T6:
        return _AKA_T6[tid]
    suit = tid // 36           # 0=m, 1=p, 2=s, 3=字
    num = (tid % 36) // 4       # 0-8
    if suit < 3:
        return (suit + 1) * 10 + (num + 1)
    return 41 + num             # 字牌 0-6 -> 41-47


def tile136_to_mjai(tid: int) -> str:
    """天鳳原始 tile id (0-135) -> MJAI 字串 (1m..9s / E,S,W,N,P,F,C / 赤 5mr,5pr,5sr)。"""
    if tid in _AKA_MJAI:
        return _AKA_MJAI[tid]
    suit = tid // 36
    num = (tid % 36) // 4
    if suit < 3:
        return f"{num + 1}{'mps'[suit]}"
    return _HONOR[num]


def decode_meld(meld: int) -> dict:
    """解碼天鳳鳴牌 `m` 位元欄位，回傳結構化 tile id (供各轉換器格式化)。

    回傳 dict::
        chi/pon/daiminkan: {kind, called, consumed:[手中組成牌, 升序], kui}
        kakan:             {kind, called(加上去的第4張), consumed:[原碰3張, 升序], kui}
        ankan:             {kind, consumed:[4張, 升序(赤在前)], kui(=0)}
        nukidora (三麻北): {kind}

    kui = 放槍者相對於鳴牌者 (1=下家, 2=對面, 3=上家; 暗槓=0)。
    采用天鳳官方 tehai.js 的位元配置。
    """
    kui = meld & 0x3
    if meld & 0x4:  # 吃
        t = (meld & 0xFC00) >> 10
        ci = t % 3
        t //= 3
        base = (9 * (t // 7) + (t % 7)) * 4
        offs = [(meld & 0x18) >> 3, (meld & 0x60) >> 5, (meld & 0x180) >> 7]
        ids = [base + 0 + offs[0], base + 4 + offs[1], base + 8 + offs[2]]
        return {"kind": "chi", "called": ids[ci],
                "consumed": [ids[i] for i in range(3) if i != ci], "kui": kui}
    if meld & 0x8:  # 碰
        unused = (meld & 0x60) >> 5
        t = (meld & 0xFE00) >> 9
        ci = t % 3
        t //= 3
        base = t * 4
        copies = [c for c in range(4) if c != unused]
        ids = [base + c for c in copies]
        return {"kind": "pon", "called": ids[ci],
                "consumed": [ids[i] for i in range(3) if i != ci], "kui": kui}
    if meld & 0x10:  # 加槓
        added = (meld & 0x60) >> 5
        t = (meld & 0xFE00) >> 9
        t //= 3
        base = t * 4
        return {"kind": "kakan", "called": base + added,
                "consumed": [base + c for c in range(4) if c != added], "kui": kui}
    if meld & 0x20:  # 北抜 (三麻)
        return {"kind": "nukidora"}
    # 暗槓 / 大明槓
    hai0 = (meld & 0xFF00) >> 8
    base = (hai0 // 4) * 4
    if kui == 0:
        return {"kind": "ankan",
                "consumed": [base, base + 1, base + 2, base + 3], "kui": kui}
    return {"kind": "daiminkan", "called": hai0,
            "consumed": [base + i for i in range(4) if base + i != hai0], "kui": kui}


def decode_go_flags(go_type: int) -> dict:
    """解碼 GO 的 type 位元欄位 (天鳳遊戲規則)。"""
    return {
        "aka": not (go_type & 0x02),       # 赤あり
        "kuitan": not (go_type & 0x04),    # 喰い断あり
        "hanchan": bool(go_type & 0x08),   # 半莊 (否則東風)
        "sanma": bool(go_type & 0x10),     # 三人打ち
    }


def sc_deltas(attrib) -> list:
    """從 AGARI/RYUUKYOKU 的 sc="前,變,前,變,..." 取出 4 家分數變動 (×100, 不足補 0)。"""
    sc = int_list(attrib.get("sc", ""))
    deltas = [sc[i] * 100 for i in range(1, len(sc), 2)]
    return (deltas + [0, 0, 0, 0])[:4]
