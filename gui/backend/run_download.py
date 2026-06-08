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

帳密來源：不經 argv，改由單一 config.ini 讀取 (路徑由 params.config_ini_path 帶入，GUI 全面
管理該檔；缺檔回退舊 config.env)；params 僅帶非敏感的並發/旗標設定。
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


def _persist_res_version(ini_paths: list[str], version: str) -> None:
    """把成功登入的資源版本寫回 config.ini 的 [account] ms_res_version，下次直接可用、毋需再抓。

    ini_paths 通常為 [primary(執行檔同層), mirror(userData)]：兩者都寫，確保升級洗掉同層檔後
    仍能由 mirror 還原到最新版本。寫入失敗不影響本次執行（記憶體中已套用新版本）。"""
    import config_store

    for path in ini_paths:
        if not path:
            continue
        try:
            config_store.set_value(path, "account", "ms_res_version", version)
        except Exception:  # noqa: BLE001 持久化失敗不影響本次執行
            pass


async def _login_with_auto_update(downloader, username: str, password: str, ini_paths: list[str]) -> bool:
    """登入雀魂；遇 error 151 (資源版本過期) 時自動抓最新版本、寫回 config.env 並重新登入。

    候選順序：version.json 抓到的最新版本 -> ms_patch 內建預設值 (修正 GUI 寫入空值的情況)。
    任一候選成功即持久化並回 True；全部失敗回 False (已 emit 對應錯誤事件)。"""
    import ms_patch

    try:
        await ms_patch.login(downloader, username, password)
        ms_patch.patch_downloader(downloader)
        return True
    except Exception as exc:  # noqa: BLE001
        if not ms_patch.is_resource_version_error(exc):
            bridge.error("download", "LOGIN_FAILED", str(exc), fatal=True)
            return False

    # error 151：自動更新資源版本並重新登入 (重開)。
    bridge.notice("download", "VERSION_AUTO_UPDATING")

    # 以「第一次登入實際使用的版本」(空值會被 _res_version 解析為預設) 作為已試集合，
    # 避免重複重試同一個剛失敗的版本。
    tried = {ms_patch._res_version()}
    candidates: list[str] = []
    fetched = ms_patch.fetch_latest_res_version()
    if fetched:
        candidates.append(fetched)
    candidates.append(ms_patch._DEFAULT_RES_VERSION)

    for ver in candidates:
        if not ver or ver in tried:
            continue
        tried.add(ver)
        # _res_version() 於登入時才讀環境變數，故直接改 os.environ 即可即時生效。
        os.environ["MS_RES_VERSION"] = ver
        try:
            await ms_patch.login(downloader, username, password)
            ms_patch.patch_downloader(downloader)
        except Exception as exc:  # noqa: BLE001
            if ms_patch.is_resource_version_error(exc):
                continue  # 此版本仍被拒，試下一個候選
            bridge.error("download", "LOGIN_FAILED", str(exc), fatal=True)
            return False
        _persist_res_version(ini_paths, ver)
        bridge.notice("download", "VERSION_UPDATED", ver)
        return True

    bridge.error("download", "VERSION_UPDATE_FAILED",
                 "已嘗試自動更新資源版本但仍登入失敗 (error 151)", fatal=True)
    return False


async def _run_async(params: dict, work_dir: str, repo_root: str) -> None:
    import config_store

    # 單一設定檔 config.ini：primary 為「執行檔同層」(GUI 由 params 帶入)，mirror 為 userData
    # 備援。缺檔時 load_into_env 會回退舊的 config.env。帳密 / 旗標皆由此載入 os.environ。
    ini_primary = params.get("config_ini_path") or os.path.join(work_dir, "config.ini")
    ini_mirror = params.get("config_ini_mirror") or ""
    ini_paths = [p for p in (ini_primary, ini_mirror) if p]
    config_store.load_into_env(ini_primary)

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
        if not await _login_with_auto_update(downloader, username, password, ini_paths):
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
