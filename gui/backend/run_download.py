# -*- coding: utf-8 -*-
"""run_download —— 包裝 Stage 2 (下載 + 轉換)，並加入並行化。

與既有 toumajsoul.py 的關係
---------------------------
重用其核心函式 `download_single_log` / `process_log` (不重寫下載與 timing 注入邏輯)，
只重寫 main 外殼：讀清單、跳過已下載、登入一次、**並行調度**、emit 進度。

並行策略 (見計畫)
-----------------
- 下載並發：雀魂單一 websocket lobby 有狀態、同帳號多登入會互踢 -> 單一 downloader、
  登入一次，用 Semaphore(download_concurrency) 控制同時請求數 (預設 3，可調，亦可序列)。
- 轉換並發：mjai-reviewer 是外部 binary，可安全多開 -> Semaphore(convert_concurrency)
  (預設 = CPU 核心，上限 8)。吞吐主要來自這裡。

帳密來源：不經 argv，改由 work_dir/config.env 讀取 (GUI 全面管理該檔)；params 僅帶
非敏感的並發/旗標設定。
"""
from __future__ import annotations

import asyncio
import os

from . import bridge, paths


def _read_id_list(params: dict, work_dir: str) -> list[str]:
    """取得待下載 ID 清單：優先用 params['input_list'] (Stage 1 自動銜接)，
    否則回退 work_dir/tonpuulist.txt。"""
    path = params.get("input_list") or os.path.join(work_dir, "tonpuulist.txt")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


def _filter_existing(ids: list[str], base_dir: str) -> list[str]:
    """沿用 toumajsoul 的去重：掃 mahjong_logs/tenhou/ 跳過已下載。"""
    tenhou_dir = os.path.join(base_dir, "tenhou")
    existing: set[str] = set()
    if os.path.isdir(tenhou_dir):
        existing = {
            os.path.splitext(fn)[0]
            for fn in os.listdir(tenhou_dir)
            if fn.endswith(".json")
        }
    return [i for i in ids if i not in existing]


def _bool_env(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() == "true"


async def _run_async(params: dict, work_dir: str, repo_root: str) -> None:
    import dotenv

    dotenv.load_dotenv(os.path.join(work_dir, "config.env"))

    # 既有模組需在 repo_root 下完成 import (tensoul-py-ng 相對路徑、ms_cfg)。
    cwd_for_import = os.getcwd()
    os.chdir(repo_root)
    try:
        import ms_patch
        import toumajsoul
        from toumajsoul import download_single_log, process_log
        MajsoulPaipuDownloader = toumajsoul.MajsoulPaipuDownloader
        ms_patch.ensure_ms_cfg()
    finally:
        os.chdir(cwd_for_import)

    # 設定 (params 覆寫 > config.env > 預設)
    username = params.get("username") or os.getenv("ms_username", "")
    password = params.get("password") or os.getenv("ms_password", "")
    collect_timing = params.get("collect_timing", _bool_env("COLLECT_TIMING", True))
    save_debug = params.get("save_debug", _bool_env("SAVE_DEBUG", False))
    save_raw_json = params.get("save_raw_json", _bool_env("SAVE_RAW_JSON", False))
    if save_raw_json and not collect_timing:
        collect_timing = True

    download_concurrency = int(params.get("download_concurrency", 3))
    convert_concurrency = int(params.get("convert_concurrency", min(8, os.cpu_count() or 4)))
    if params.get("sequential_download"):
        download_concurrency = 1

    # 輸出落在 work_dir
    os.chdir(work_dir)
    base_dir = "mahjong_logs"
    os.makedirs(os.path.join(base_dir, "mjai"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "tenhou"), exist_ok=True)
    os.makedirs("temp_logs", exist_ok=True)

    ids = _read_id_list(params, work_dir)
    unique_ids = _filter_existing(ids, base_dir)
    total = len(unique_ids)

    bridge.stage_start("download", total=total, collect_timing=collect_timing,
                       download_concurrency=download_concurrency,
                       convert_concurrency=convert_concurrency)

    if total == 0:
        bridge.stage_done("download", downloaded=0, total=0)
        bridge.done(ok=True)
        return

    dl_sem = asyncio.Semaphore(download_concurrency)
    mj_sem = asyncio.Semaphore(convert_concurrency)
    counters = {"dl": 0, "cv": 0}

    async with MajsoulPaipuDownloader() as downloader:
        try:
            await ms_patch.login(downloader, username, password)
            ms_patch.patch_downloader(downloader)
        except Exception as exc:  # noqa: BLE001
            bridge.error("download", "LOGIN_FAILED", str(exc), fatal=True)
            bridge.done(ok=False, exit_code=1)
            return

        async def worker(uuid: str) -> None:
            async with dl_sem:
                log, timing, full = await download_single_log(uuid, downloader, collect_timing)
            counters["dl"] += 1
            bridge.progress("download", phase="download", done=counters["dl"], total=total,
                            uuid=uuid, ok=bool(log))
            if log:
                await process_log(uuid, log, base_dir, timing, full,
                                  save_debug, save_raw_json, mjai_semaphore=mj_sem)
                counters["cv"] += 1
                bridge.progress("convert", phase="mjai", done=counters["cv"], total=total,
                                uuid=uuid, ok=True)

        await asyncio.gather(*(worker(u) for u in unique_ids))

    # 清理暫存
    try:
        for fn in os.listdir("temp_logs"):
            os.remove(os.path.join("temp_logs", fn))
    except Exception:  # noqa: BLE001
        pass

    bridge.stage_done("download", downloaded=counters["cv"], total=total,
                      output_dir=os.path.abspath(base_dir))
    bridge.done(ok=True)


def run(params: dict) -> None:
    work_dir = str(paths.work_dir(params))
    repo_root = str(paths.repo_root(params))
    paths.ensure_repo_on_syspath(params)

    try:
        asyncio.run(_run_async(params, work_dir, repo_root))
    except Exception as exc:  # noqa: BLE001
        bridge.error("download", "DOWNLOAD_EXCEPTION", str(exc), fatal=True)
        bridge.done(ok=False, exit_code=1)


if __name__ == "__main__":
    run(bridge.read_params())
