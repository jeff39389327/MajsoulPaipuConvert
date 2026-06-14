# -*- coding: utf-8 -*-
"""amae-koromo 後端 API client：依「房間 + 日期區間」直接取得完整牌譜 UUID，
完全不需要 Selenium / 瀏覽器（date_room_api 模式專用）。

為什麼是兩步
------------
amae-koromo 的 room `games` 端點對匿名請求會把 uuid **遮蔽成短碼**（回傳含
``"_masked": true``，uuid 像 ``972bOfSK3ME``，無法用來下載）。但 `player_records`
端點回的是**完整未遮蔽** UUID（``260608-b91ab9ee-...``）。故流程為：

  1. games 端點列舉某房間某時段的所有對局（拿到：短碼、4 位玩家 accountId、起訖時間）。
  2. 對每局取一位 accountId 打 player_records（mode 必填、限縮時間窗），用 startTime
     比對還原成完整 UUID。player_records 一次會回該玩家整個時間窗的對局，全部折進快取，
     使同房間後續對局多半免再請求。

這就是現行 Selenium `date_room` 時間比對法的純 API 版（快一兩個數量級且穩定）。
"""
from __future__ import annotations

import random
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

# 房間名 → 雀魂 mode_id（四麻；與 date_room_extractor.RANK_ROOM_MAPPING 一致）
ROOM_MODE: Dict[str, int] = {
    "Throne": 16,
    "Jade": 12,
    "Gold": 9,
    "Throne East": 15,
    "Jade East": 11,
    "Gold East": 8,
}

# 三麻 (sanma) 房間名 → 雀魂 mode_id（amae-koromo pl3；East=三人東, 預設=三人南）
SANMA_ROOM_MODE: Dict[str, int] = {
    "Throne": 26,
    "Jade": 24,
    "Gold": 22,
    "Throne East": 25,
    "Jade East": 23,
    "Gold East": 21,
}

# game_mode -> (房間對應表, amae-koromo API 路徑段)。四麻走 pl4、三麻走 pl3，
# 兩者的 games/player_records 端點與去遮蔽流程完全相同，只差路徑段與 mode_id。
_GAME_MODES = {
    "yonma": (ROOM_MODE, "pl4"),
    "sanma": (SANMA_ROOM_MODE, "pl3"),
}

API_MIRRORS = [
    "https://5-data.amae-koromo.com",
    "https://1-data.amae-koromo.com",
    "https://2-data.amae-koromo.com",
    "https://4-data.amae-koromo.com",
]
_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
# 共享連線池（keep-alive）：避免每發請求都重做 DNS 查詢＋TLS 握手——
# 長時間收集時上千次 getaddrinfo 會把本機/路由器 DNS 打到暫時失靈（NameResolutionError）
_SESSION = requests.Session()
_SESSION.headers.update(_UA)
# 整輪鏡像全失敗後的退避秒數（多半是本地 DNS / 網路抖動，等幾秒就會恢復）
_RETRY_BACKOFF = [3, 8, 20, 45, 90]
_SLICE_SECONDS = 6 * 3600     # games 端點單批上限 500；玉/王座約 6h 內安全，超量自動二分
_ENUM_CAP = 500               # 單批達此值視為被截，需把時間窗再切半
_PAGE_LIMIT = 1000
_PLAYER_LIMIT = 100
_REQ_DELAY = (0.15, 0.4)      # 每次請求後的禮貌延遲（秒），避開速率限制；嫌慢可再調小
_FULL_UUID = re.compile(
    r"\d{6}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def _log(msg: str) -> None:
    # 與 spider 慣例一致：除錯/進度走 stderr，UUID 本身走 stdout（供 dev run_crawler 解析）
    print(msg, file=sys.stderr, flush=True)


def _is_full(u) -> bool:
    return bool(u and _FULL_UUID.fullmatch(str(u)))


def _get(path: str, params: dict) -> object:
    """GET 一個 amae-koromo API，回傳解析後 JSON。

    鏡像失效自動換下一個；整輪鏡像全失敗則按 _RETRY_BACKOFF 退避後重來
    （本地 DNS 抽風／網路抖動幾秒內會自癒），全部用盡才 raise。
    """
    last_err = None
    for attempt, wait in enumerate([0] + _RETRY_BACKOFF):
        if wait:
            _log(f"[api] 整輪鏡像失敗（{last_err}），{wait}s 後重試"
                 f"（第 {attempt}/{len(_RETRY_BACKOFF)} 次）")
            time.sleep(wait)
        for base in API_MIRRORS:
            try:
                r = _SESSION.get(base + path, params=params, timeout=20)
                if r.status_code == 200:
                    time.sleep(random.uniform(*_REQ_DELAY))
                    return r.json()
                last_err = f"HTTP {r.status_code}: {r.text[:120]}"
            except requests.RequestException as exc:
                last_err = repr(exc)
            time.sleep(random.uniform(*_REQ_DELAY))
    raise RuntimeError(f"amae-koromo API 請求失敗 {path} params={params} -> {last_err}")


def _get_games(pl: str, mode: int, start_ts: int, end_ts: int) -> List[dict]:
    data = _get(
        f"/api/v2/{pl}/games/{end_ts}/{start_ts}",
        {"limit": _PAGE_LIMIT, "mode": mode, "descending": "true"},
    )
    return data if isinstance(data, list) else []


def _enumerate(pl: str, mode: int, start_ts: int, end_ts: int) -> List[dict]:
    """列舉 [start_ts, end_ts) 該房間對局；單批達上限（被截）則二分時間窗遞迴補齊。"""
    games = _get_games(pl, mode, start_ts, end_ts)
    if len(games) >= _ENUM_CAP and (end_ts - start_ts) > 600:
        mid = (start_ts + end_ts) // 2
        _log(f"[api] {len(games)} 筆達上限，時間窗二分 {start_ts}..{mid}..{end_ts}")
        return _enumerate(pl, mode, start_ts, mid) + _enumerate(pl, mode, mid, end_ts)
    return games


def _get_player_records(pl: str, account_id: int, mode: int, start_ts: int, end_ts: int) -> List[dict]:
    try:
        data = _get(
            f"/api/v2/{pl}/player_records/{account_id}/{end_ts}/{start_ts}",
            {"limit": _PLAYER_LIMIT, "mode": mode, "descending": "true"},
        )
    except RuntimeError as exc:
        _log(f"[api] player_records 失敗 acc={account_id}: {exc}")
        return []
    return data if isinstance(data, list) else []


def _resolve_full_uuid(
    pl: str, game: dict, mode: int, win_start: int, win_end: int, cache: Dict[int, str]
) -> Optional[str]:
    """把一局（含遮蔽短碼）還原成完整 UUID：用 startTime 對快取/ player_records 比對。"""
    st = game.get("startTime")
    if st is not None and st in cache:
        return cache[st]
    for p in game.get("players", []):
        acc = p.get("accountId")
        if not acc:
            continue
        # 拉該玩家整個時間窗的對局，全部折進快取（同房間後續對局多半免再請求）
        for rec in _get_player_records(pl, acc, mode, win_start, win_end):
            u = rec.get("uuid") or rec.get("_id")
            rst = rec.get("startTime")
            if _is_full(u) and rst is not None:
                cache.setdefault(rst, u)
        if st is not None and st in cache:
            return cache[st]
    return None


def _iter_slices(start_date: str, end_date: str):
    """把 [start_date 00:00, end_date 24:00)（本機時區）切成 _SLICE_SECONDS 的時間窗。"""
    d0 = datetime.strptime(start_date, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
    d1 = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=0, minute=0, second=0) + timedelta(days=1)
    start_ts = int(time.mktime(d0.timetuple()))
    end_ts = int(time.mktime(d1.timetuple()))
    cur = start_ts
    while cur < end_ts:
        nxt = min(cur + _SLICE_SECONDS, end_ts)
        yield cur, nxt
        cur = nxt


def collect_room_paipus(
    target_room: str,
    start_date: str,
    end_date: str,
    output_file=None,
    existing_ids=None,
    game_mode: str = "yonma",
) -> List[str]:
    """依房間 + 日期區間，透過 amae-koromo API 收集完整 UUID。

    game_mode: "yonma"（四麻 pl4，預設）或 "sanma"（三麻 pl3）。三麻走 amae-koromo
    的 pl3 端點與三麻 mode_id；去遮蔽流程（games -> player_records）完全相同。

    每收到一筆新 UUID 就 write+flush 到 output_file（凍結模式靠輪詢檔案回報進度），並
    print 到 stdout（dev 模式 run_crawler 解析 stdout 統計進度）。回傳本次新增的 UUID 清單。
    """
    gm = (game_mode or "yonma").lower()
    if gm not in _GAME_MODES:
        raise ValueError(f"未知 game_mode {game_mode}，可用：{list(_GAME_MODES)}")
    room_map, pl = _GAME_MODES[gm]
    if target_room not in room_map:
        raise ValueError(f"未知房間 {target_room}（{gm}），可用：{list(room_map)}")
    mode = room_map[target_room]
    existing = existing_ids if existing_ids is not None else set()
    cache: Dict[int, str] = {}      # startTime -> 完整 UUID（跨 slice 重用）
    collected: List[str] = []
    total_games = 0
    unresolved = 0

    _log(f"[api] 開始：{gm} 房間={target_room}({pl} mode={mode}) 日期 {start_date}~{end_date}")
    for win_start, win_end in _iter_slices(start_date, end_date):
        games = _enumerate(pl, mode, win_start, win_end)
        _log(f"[api] {datetime.fromtimestamp(win_start):%Y-%m-%d %H:%M} 起 6h：列舉 {len(games)} 局")
        for g in games:
            total_games += 1
            full = _resolve_full_uuid(pl, g, mode, win_start, win_end, cache)
            if not full:
                unresolved += 1
                _log(f"[api] 無法還原 start={g.get('startTime')} "
                     f"players={[p.get('accountId') for p in g.get('players', [])]}")
                continue
            if full in existing:
                continue
            existing.add(full)
            collected.append(full)
            if output_file is not None:
                output_file.write(full + "\n")
                output_file.flush()
            print(full, flush=True)   # 供 dev run_crawler 即時統計

    _log(f"[api] 完成：新增 {len(collected)} 筆（列舉 {total_games} 局，無法還原 {unresolved} 局）")
    return collected
