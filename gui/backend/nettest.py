# -*- coding: utf-8 -*-
"""nettest —— 雀魂連線測速（回答「到底是誰慢」）。

為什麼需要這支
--------------
下載變慢時，光看下載進度分不出是 (a) 這台機器到雀魂的線路慢、(b) 帳號被限流、
(c) 我們自己的流程（解析/寫檔/重試）在拖。本自檢繞開整條下載流程，只量三件事：

1. **握手 + 登入**：連得上嗎？多久？
2. **純延遲**：連送 10 次 `.lq.Lobby.heatbeat`（極小封包、伺服器幾乎不做事）取中位數。
   這就是純粹的來回時間，與牌譜大小無關。
3. **實際牌譜**：抓最多 5 筆真實牌譜（uuid 取自工作目錄既有的清單／斷點），算每筆
   耗時與等效吞吐量。

判讀：延遲小但牌譜慢 → 頻寬/丟包或伺服器對該帳號降速；兩者都慢 → 這台的線路問題；
兩者都快但實際下載慢 → 問題在下載流程本身（該回頭看 run_download）。
"""
from __future__ import annotations

import asyncio
import os
import statistics
import time

from . import bridge, paths


def _sample_uuids(params: dict, work_dir: str, limit: int = 5) -> list[str]:
    """從工作目錄既有檔案取幾個 uuid 當測試樣本（不下載新清單）。"""
    candidates = [
        params.get("input_list") or "",
        os.path.join(work_dir, "tonpuulist.txt"),
        os.path.join(work_dir, "download_checkpoint_pending.txt"),
        os.path.join(work_dir, "date_room_list.txt"),
    ]
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        out: list[str] = []
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    uuid = line.strip().strip('",')
                    if len(uuid) > 30 and uuid.count("-") >= 4:
                        out.append(uuid)
                    if len(out) >= limit:
                        break
        except OSError:
            continue
        if out:
            return out
    return []


async def _run_async(params: dict, work_dir: str, repo_root: str) -> dict:
    import config_store

    ini_primary = params.get("config_ini_path") or os.path.join(work_dir, "config.ini")
    config_store.load_into_env(ini_primary)

    cwd = os.getcwd()
    os.chdir(repo_root)
    try:
        import ms_patch
        import ms.protocol_pb2 as pb
        ms_patch.ensure_ms_cfg()
        from tensoul import MajsoulPaipuDownloader
    finally:
        os.chdir(cwd)

    username = os.getenv("ms_username", "")
    password = os.getenv("ms_password", "")
    result: dict = {"account": username[:3] + "***" if username else ""}
    if not username or not password:
        result["error"] = "NO_ACCOUNT"
        return result

    uuids = _sample_uuids(params, work_dir)
    t = time.perf_counter()
    async with MajsoulPaipuDownloader() as dl:
        result["connect_ms"] = int((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        try:
            await ms_patch.login(dl, username, password)
        except Exception as exc:  # noqa: BLE001 登入失敗直接回報，不做版本探測
            result["error"] = str(exc)
            return result
        result["login_ms"] = int((time.perf_counter() - t) * 1000)

        pings: list[float] = []
        for _ in range(10):
            t = time.perf_counter()
            try:
                await asyncio.wait_for(dl.lobby.heatbeat(pb.ReqHeatBeat()), timeout=30)
            except Exception:  # noqa: BLE001 單次失敗跳過，剩下的樣本仍有意義
                continue
            pings.append((time.perf_counter() - t) * 1000)
        if pings:
            result["ping_ms"] = int(statistics.median(pings))
            result["ping_min_ms"] = int(min(pings))

        fetches: list[float] = []
        sizes: list[int] = []
        for uuid in uuids:
            t = time.perf_counter()
            try:
                res = await asyncio.wait_for(
                    dl.lobby.fetch_game_record(ms_patch.build_game_record_req(uuid)), timeout=60)
            except Exception:  # noqa: BLE001
                continue
            elapsed = (time.perf_counter() - t) * 1000
            if res.error.code:
                continue  # 1203 等牌譜級錯誤：不計入速度樣本
            fetches.append(elapsed)
            sizes.append(len(res.data))
        if fetches:
            result["fetch_ms"] = int(statistics.median(fetches))
            result["fetch_count"] = len(fetches)
            result["fetch_kb"] = int(statistics.median(sizes) / 1024)
            result["kbps"] = int(sum(sizes) / 1024 / max(0.001, sum(fetches) / 1000))
    return result


def run(params: dict) -> None:
    work_dir = str(paths.work_dir(params))
    repo_root = str(paths.repo_root(params))
    paths.ensure_repo_on_syspath(params)
    bridge.stage_start("nettest")
    try:
        result = asyncio.run(_run_async(params, work_dir, repo_root))
    except Exception as exc:  # noqa: BLE001 自檢本身失敗也要有結果可看
        result = {"error": str(exc)}
    bridge.stage_done("nettest", **result)
    bridge.done(ok="error" not in result)


if __name__ == "__main__":
    run(bridge.read_params())
