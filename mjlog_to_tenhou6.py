# -*- coding: utf-8 -*-
"""
mjlog_to_tenhou6
================

將天鳳 (tenhou.net) 的「原始 mjlog XML」轉成 mjai-reviewer 可直接讀取的
**tenhou.net/6** 格式 (與 tensoul-py-ng 輸出相同的 schema)。**四麻專用**
(三麻請改用 ``mjlog_to_mjai``，因為 mjai-reviewer/convlog 不支援三麻)。

背景 / 為什麼需要這支程式
------------------------
mjai-reviewer 內建的天鳳下載器 (`src/download.rs`) 只會打 ::

    https://tenhou.net/5/mjlog2json.cgi?{log_id}

天鳳已將這個「mjlog→JSON」轉換端點停用 (對新舊牌譜都回傳 HTTP 200 但
content-length: 0 的空 body)，導致 mjai-reviewer 無法分析天鳳牌譜
(見 https://github.com/Equim-chan/mjai-reviewer/issues/163)。

但原始 mjlog 下載端點 ``https://tenhou.net/0/log/?{log_id}`` 仍然正常運作
(回傳 <mjloggm> XML)。本模組就是把那份 XML 在本地轉成 tenhou.net/6 JSON，
之後即可餵給 ``mjai-reviewer --no-review -i file.json``。

格式來源 (權威參考)
------------------
* tile / 鳴牌 / tsumogiri(=60) / riichi("r") 的編碼，與 tensoul 的
  ``tensoul/model.py`` 一致 (mjai-reviewer 的 convlog 解析器逐位元組對應)。
* 底層 tile 編碼與鳴牌 `m` 解碼共用 ``mjlog_common`` (見該模組)。
* INIT 的 `ten`、AGARI/RYUUKYOKU 的 `sc` 皆為「百點」單位，需 ×100 還原成
  實際點數 (tenhou.net/6 的 scoreboard / deltas 用實際點數)。

可當模組使用 (``convert(xml_str) -> dict``)，也可當 CLI ::

    python mjlog_to_tenhou6.py input.mjlog.xml > output.json
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from urllib.parse import unquote

from mjlog_common import (DISCARD_SEAT, DRAW_SEAT, decode_go_flags, decode_meld,
                          int_list, sc_deltas, tile136_to_t6)


class SanmaNotSupported(ValueError):
    """三人麻將牌譜：本模組僅支援四麻 (三麻請用 mjlog_to_mjai)。"""


# 天鳳 yaku id -> 名稱 (僅供 viewer 顯示; convlog 不解析這些字串)
_YAKU = {
    0: "門前清自摸和", 1: "立直", 2: "一発", 3: "槍槓", 4: "嶺上開花",
    5: "海底摸月", 6: "河底撈魚", 7: "平和", 8: "断幺九", 9: "一盃口",
    10: "自風 東", 11: "自風 南", 12: "自風 西", 13: "自風 北",
    14: "場風 東", 15: "場風 南", 16: "場風 西", 17: "場風 北",
    18: "役牌 白", 19: "役牌 發", 20: "役牌 中",
    21: "両立直", 22: "七対子", 23: "混全帯幺九", 24: "一気通貫",
    25: "三色同順", 26: "三色同刻", 27: "三槓子", 28: "対々和",
    29: "三暗刻", 30: "小三元", 31: "混老頭", 32: "二盃口",
    33: "純全帯幺九", 34: "混一色", 35: "清一色", 36: "人和",
    37: "天和", 38: "地和", 39: "大三元", 40: "四暗刻", 41: "四暗刻単騎",
    42: "字一色", 43: "緑一色", 44: "清老頭", 45: "九蓮宝燈",
    46: "純正九蓮宝燈", 47: "国士無双", 48: "国士無双１３面",
    49: "大四喜", 50: "小四喜", 51: "四槓子",
    52: "ドラ", 53: "裏ドラ", 54: "赤ドラ",
}

_LIMIT = {1: "満貫", 2: "跳満", 3: "倍満", 4: "三倍満", 5: "役満"}

# RYUUKYOKU type -> 顯示字串 (convlog 只認 "和了"，其餘一律視為流局並讀 results[1] 當 deltas)
_RYUU_NAME = {
    "yao9": "九種九牌", "reach4": "四家立直", "ron3": "三家和了",
    "kan4": "四開槓", "kaze4": "四風連打", "nm": "流し満貫",
}


def _meld_string(meld: int):
    """解碼鳴牌 `m` 並格式化成 tenhou.net/6 字串。

    回傳 (kind, string)：chi/pon/daiminkan 放進 takes(摸)；ankan/kakan 放進 discards(打)；
    daiminkan 另需在 discards 補 0 (由呼叫端處理)。三麻北抜回傳 (None, None)。
    字串格式與 tensoul/model.py 一致，convlog 才能正確解析。
    feeder_relative = 3 - kui (kui = 放槍者相對位置)。
    """
    d = decode_meld(meld)
    k = d["kind"]
    if k == "nukidora":
        return None, None   # 四麻不會出現
    if k == "chi":
        c = [tile136_to_t6(x) for x in d["consumed"]]
        return "chi", f"c{tile136_to_t6(d['called'])}{c[0]}{c[1]}"
    if k == "ankan":
        c = [tile136_to_t6(x) for x in d["consumed"]]
        return "ankan", f"{c[0]}{c[1]}{c[2]}a{c[3]}"
    # pon / kakan / daiminkan：在 consumed 之間插入「被鳴牌」標記
    fr = 3 - d["kui"]
    parts = [str(tile136_to_t6(x)) for x in d["consumed"]]
    called = tile136_to_t6(d["called"])
    if k == "pon":
        parts.insert(fr, f"p{called}")
        return "pon", "".join(parts)
    if k == "kakan":
        parts.insert(fr, f"k{called}")
        return "kakan", "".join(parts)
    # daiminkan (插入位置 fr==2 時為 3)
    parts.insert(3 if fr == 2 else fr, f"m{called}")
    return "daiminkan", "".join(parts)


class _KyokuBuilder:
    """累積單一局的狀態，最後 dump() 成 tenhou.net/6 的 16 元素陣列。"""

    __slots__ = ("meta", "scoreboard", "doras", "ura", "haipai",
                 "takes", "discards", "result", "_last_draw", "_reach_pending")

    def __init__(self, seed, ten, haipai):
        # seed = kyoku, honba, kyotaku, dice, dice, dora_indicator(tile id)
        self.meta = [seed[0], seed[1], seed[2]]
        self.scoreboard = [s * 100 for s in ten]
        self.doras = [tile136_to_t6(seed[5])]
        self.ura = []
        # tenhou.net/6 的配牌依 tile id 排序 (赤五排在對應正常五的位置)
        self.haipai = [[tile136_to_t6(t) for t in sorted(h)] for h in haipai]
        self.takes = [[] for _ in range(4)]
        self.discards = [[] for _ in range(4)]
        self.result = None            # 設定後即視為本局結束
        self._last_draw = [None, None, None, None]
        self._reach_pending = [False, False, False, False]

    # -- 事件 --
    def draw(self, seat, tid):
        self.takes[seat].append(tile136_to_t6(tid))
        self._last_draw[seat] = tid

    def discard(self, seat, tid):
        tsumogiri = self._last_draw[seat] == tid
        code = 60 if tsumogiri else tile136_to_t6(tid)
        if self._reach_pending[seat]:
            self._reach_pending[seat] = False
            self.discards[seat].append(f"r{code}")
        else:
            self.discards[seat].append(code)
        self._last_draw[seat] = None

    def call(self, seat, meld):
        kind, s = _meld_string(meld)
        if kind is None:
            return
        self._last_draw[seat] = None
        if kind in ("chi", "pon", "daiminkan"):
            self.takes[seat].append(s)
            if kind == "daiminkan":
                self.discards[seat].append(0)   # 天鳳會在 discards 放一個 0 佔位
        else:  # ankan / kakan -> 放進 discards
            self.discards[seat].append(s)

    def reach_declare(self, seat):
        self._reach_pending[seat] = True

    def add_dora(self, tid):
        self.doras.append(tile136_to_t6(tid))

    # -- 結果 --
    def set_agari(self, attrib):
        """累積 AGARI (可能多次 = 雙/三響)。"""
        if self.result is None or self.result[0] != "和了":
            self.result = ["和了"]
        deltas = sc_deltas(attrib)

        who = int(attrib["who"])
        from_who = int(attrib["fromWho"])
        pao = int(attrib.get("paoWho", who))

        oya = self.meta[0] % 4
        honba = self.meta[1]
        detail = [who, from_who, pao, _point_string(attrib, oya, honba, deltas)]
        detail.extend(_yaku_strings(attrib))

        self.result.append(deltas)
        self.result.append(detail)

        # 裏ドラ：取最長的一份 (雙響+立直/默聽)
        ura = int_list(attrib.get("doraHaiUra", ""))
        if len(ura) > len(self.ura):
            self.ura = [tile136_to_t6(t) for t in ura]

    def set_ryuukyoku(self, attrib):
        name = _RYUU_NAME.get(attrib.get("type", ""), "流局")
        self.result = [name, sc_deltas(attrib)]

    # -- 輸出 --
    def dump(self):
        entry = [self.meta, self.scoreboard, self.doras, self.ura]
        for i in range(4):
            entry.append(self.haipai[i])
            entry.append(self.takes[i])
            entry.append(self.discards[i])
        entry.append(self.result if self.result is not None else ["流局", [0, 0, 0, 0]])
        return entry


def _point_string(attrib, oya, honba, deltas):
    """產生顯示用的點數字串 (cosmetic; convlog 不使用，但 tenhou viewer 需以 点/飜/役満 結尾)。

    天鳳慣例：榮和/上限手顯示基本點 (不含本場)；莊家自摸用「{點}点∀」；
    子家自摸用「{子}-{親}点」。子/親支付額由各家 deltas 扣掉本場求得最穩健。
    """
    ten = int_list(attrib.get("ten", ""))
    fu = ten[0] if len(ten) > 0 else 0
    pts = ten[1] if len(ten) > 1 else 0
    limit = ten[2] if len(ten) > 2 else 0
    who = int(attrib["who"])
    from_who = int(attrib["fromWho"])
    head = "役満" if attrib.get("yakuman") else _LIMIT.get(limit)

    if who != from_who:
        # 榮和：ten[1] 即為基本點
        body = f"{pts}点"
    else:
        # 自摸：由 deltas 扣掉本場 (100×honba/家) 求各家支付
        hb = 100 * honba
        if who == oya:
            losers = [(-deltas[s] - hb) for s in range(4) if s != who]
            per = losers[0] if losers else (pts // 3)
            body = f"{per}点∀"
        else:
            oya_pay = -deltas[oya] - hb
            ko_pays = [(-deltas[s] - hb) for s in range(4) if s != who and s != oya]
            ko_pay = ko_pays[0] if ko_pays else (pts // 4)
            body = f"{ko_pay}-{oya_pay}点"

    if head:
        return f"{head}{body}"
    return f"{fu}符{_total_han(attrib)}飜{body}"


def _total_han(attrib):
    yk = int_list(attrib.get("yaku", ""))
    return sum(yk[i] for i in range(1, len(yk), 2))


def _yaku_strings(attrib):
    yakuman = int_list(attrib.get("yakuman", ""))
    if yakuman:
        return [f"{_YAKU.get(yid, str(yid))}(役満)" for yid in yakuman]
    yk = int_list(attrib.get("yaku", ""))
    return [f"{_YAKU.get(yk[i], str(yk[i]))}({yk[i + 1]}飜)" for i in range(0, len(yk), 2)]


def _build_rule(go_type):
    """由 GO 的 type 位元欄位產生 rule (convlog 以 disp 含 '東' 判東風、含 '三' 拒絕三麻)。"""
    f = decode_go_flags(go_type)
    disp = ("三" if f["sanma"] else "") + ("南" if f["hanchan"] else "東")
    disp += ("喰" if f["kuitan"] else "") + ("赤" if f["aka"] else "")
    rule = {"disp": disp}
    if f["aka"]:
        rule["aka51"] = 1
        rule["aka52"] = 1
        rule["aka53"] = 1
    else:
        rule["aka"] = 0
    return rule


def convert(xml_str: str, ref: str = "") -> dict:
    """將 mjlog XML 字串轉成 tenhou.net/6 dict (四麻)。三麻會 raise SanmaNotSupported。"""
    root = ET.fromstring(xml_str.lstrip("﻿"))

    names = ["", "", "", ""]
    dans = ["", "", "", ""]
    rates = [0.0, 0.0, 0.0, 0.0]
    sx = ["", "", "", ""]
    rule = {"disp": "南", "aka51": 1, "aka52": 1, "aka53": 1}
    lobby = 0

    logs = []
    cur = None

    def flush():
        nonlocal cur
        if cur is not None:
            logs.append(cur.dump())
            cur = None

    for node in root:
        tag = node.tag
        a = node.attrib

        if tag == "GO":
            go_type = int(a.get("type", "0"))
            if decode_go_flags(go_type)["sanma"]:
                raise SanmaNotSupported("此為三人麻將牌譜，本模組僅支援四麻 (請用 mjlog_to_mjai)")
            rule = _build_rule(go_type)
            lobby = int(a.get("lobby", "0"))
            continue

        if tag == "UN":
            # 第一個 UN 含 n0..n3 (開局)；之後的 UN 為斷線重連，只更新部分欄位
            for i in range(4):
                n = a.get(f"n{i}")
                if n is not None and not names[i]:
                    names[i] = unquote(n)
            if "dan" in a and not any(dans):
                dl = a["dan"].split(",")
                for i in range(min(4, len(dl))):
                    dans[i] = dl[i]
            if "rate" in a and not any(rates):
                rl = a["rate"].split(",")
                for i in range(min(4, len(rl))):
                    try:
                        rates[i] = float(rl[i])
                    except ValueError:
                        pass
            if "sx" in a and not any(sx):
                sl = a["sx"].split(",")
                for i in range(min(4, len(sl))):
                    sx[i] = sl[i]
            continue

        if tag == "INIT":
            flush()
            seed = int_list(a["seed"])
            ten = int_list(a["ten"])
            haipai = [int_list(a.get(f"hai{i}", "")) for i in range(4)]
            if any(len(h) != 13 for h in haipai):
                # 四麻每家開局必為 13 張；否則多半是三麻或殘缺牌譜
                raise SanmaNotSupported("配牌張數非 13 (可能為三麻或殘缺牌譜)，本模組僅支援四麻")
            cur = _KyokuBuilder(seed, ten, haipai)
            continue

        if cur is None:
            # INIT 之前的雜項 (SHUFFLE/TAIKYOKU/BYE...) 直接略過
            continue

        if tag == "REACH":
            if int(a.get("step", "1")) == 1:
                cur.reach_declare(int(a["who"]))
            continue

        if tag == "DORA":
            cur.add_dora(int(a["hai"]))
            continue

        if tag == "N":
            cur.call(int(a["who"]), int(a["m"]))
            continue

        if tag == "AGARI":
            cur.set_agari(a)
            continue

        if tag == "RYUUKYOKU":
            cur.set_ryuukyoku(a)
            continue

        # 摸 / 打 (tag 名如 T110 / D75)
        head = tag[0]
        if head in DRAW_SEAT and tag[1:].isdigit():
            cur.draw(DRAW_SEAT[head], int(tag[1:]))
        elif head in DISCARD_SEAT and tag[1:].isdigit():
            cur.discard(DISCARD_SEAT[head], int(tag[1:]))
        # 其餘 (BYE 等) 略過

    flush()

    out = {
        "title": ["", ""],
        "name": names,
        "rule": rule,
        "log": logs,
    }
    if ref:
        out["ref"] = ref
    if any(dans):
        out["dan"] = dans
    if any(rates):
        out["rate"] = rates
    if any(sx):
        out["sx"] = sx
    out["lobby"] = lobby
    return out


def _main(argv):
    if len(argv) > 1 and argv[1] not in ("-", "--"):
        with open(argv[1], "r", encoding="utf-8") as f:
            xml_str = f.read()
    else:
        xml_str = sys.stdin.read()
    result = convert(xml_str)
    json.dump(result, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    _main(sys.argv)
