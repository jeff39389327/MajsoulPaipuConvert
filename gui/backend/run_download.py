# -*- coding: utf-8 -*-
"""run_download —— 包裝 Stage 2 (下載 + 轉換)。

與既有 toumajsoul.py 的關係
---------------------------
重用其核心函式 `download_single_log` / `process_log` (不重寫下載與 timing 注入邏輯)，
只重寫 main 外殼：讀清單、跳過已下載、登入一次、調度、emit 進度。

調度策略
--------
- 下載**嚴格串行**：雀魂單一 websocket 只掛一個帳號、會話有狀態，同時多個 RPC
  在線上不被允許（使用者明確要求「同時只能一個號、不可並行」）；並行也會與
  AccountSession 的連線復原互撞。故一次只有一個下載請求在線上。
- 轉換並發：mjai-reviewer 是外部 binary，可安全多開 -> Semaphore(convert_concurrency)
  (預設 = CPU 核心，上限 8)。下載完成即丟背景轉換，不阻塞下一筆下載。

失敗復原 (download_recovery，repo root 共用模組)
------------------------------------------------
- 下載失敗先以同帳號重連＋重登（涵蓋 error 151 資源版本換代），仍失敗依序切換
  [account] account_pool 中的備用帳號；全部帳號不可用才中止。
- 斷點：work_dir/download_checkpoint.json 記錄失敗項與中止時未處理清單；
  下次執行自動重試，全部成功即自動刪除。

帳密來源：不經 argv，改由單一 config.ini 讀取 (路徑由 params.config_ini_path 帶入，GUI 全面
管理該檔；缺檔回退舊 config.env)；params 僅帶非敏感的並發/旗標設定。
"""
from __future__ import annotations

import asyncio
import os

from . import bridge, paths


def _read_id_list(params: dict, work_dir: str) -> tuple[list[str], str]:
    """取得待下載 ID 清單：優先用 params['input_list'] (Stage 1 自動銜接或 GUI 指定)，
    否則回退 work_dir/tonpuulist.txt。保序去除清單內重複；回傳 (ids, 實際路徑)。"""
    path = params.get("input_list") or os.path.join(work_dir, "tonpuulist.txt")
    if not os.path.exists(path):
        return [], path
    with open(path, "r", encoding="utf-8") as f:
        return list(dict.fromkeys(ln.strip() for ln in f if ln.strip())), path


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
        import download_recovery
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

    convert_concurrency = int(params.get("convert_concurrency", min(8, os.cpu_count() or 4)))

    # 輸出落在 work_dir
    os.chdir(work_dir)
    base_dir = "mahjong_logs"
    os.makedirs(os.path.join(base_dir, "mjai"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "tenhou"), exist_ok=True)
    os.makedirs("temp_logs", exist_ok=True)

    # 帳號池：主帳號＋[account] account_pool 備用帳號（失敗時輪替）。
    accounts = download_recovery.load_accounts(
        {"username": username, "password": password})
    if not accounts:
        bridge.error("download", "NO_ACCOUNT", "config.ini [account] 未設定帳密", fatal=True)
        bridge.done(ok=False, exit_code=1)
        return

    ids, input_path = _read_id_list(params, work_dir)
    if not ids:
        bridge.error("download", "NO_INPUT_LIST", input_path, fatal=True)
        bridge.done(ok=False, exit_code=1)
        return
    unique_ids = _filter_existing(ids, base_dir)
    total = len(unique_ids)

    # 斷點檔：記錄失敗項與中止時的未處理清單；上次失敗項此次自動重試。
    checkpoint = download_recovery.Checkpoint(
        os.path.join(work_dir, "download_checkpoint.json")).load()
    retrying = [u for u in unique_ids if u in checkpoint.failed]

    bridge.stage_start("download", total=total, collect_timing=collect_timing,
                       convert_concurrency=convert_concurrency,
                       accounts=len(accounts), input_list=input_path)
    if retrying:
        bridge.notice("download", "RETRY_PREV_FAILED", str(len(retrying)))

    if total == 0:
        bridge.stage_done("download", downloaded=0, total=0,
                          output_dir=os.path.abspath(base_dir))
        bridge.done(ok=True)
        return

    mj_sem = asyncio.Semaphore(convert_concurrency)
    counters = {"dl": 0, "cv": 0, "fail": 0}
    done_uuids: set = set()
    failures: list[dict] = []
    state = {"aborted": False}
    convert_tasks: list = []
    max_attempts = 3 if len(accounts) > 1 else 2

    async with MajsoulPaipuDownloader() as downloader:
        session = download_recovery.AccountSession(
            downloader, accounts, ini_paths=ini_paths,
            notify=lambda code, msg="": bridge.notice("download", code, msg))
        try:
            await session.ensure_login()
        except download_recovery.AllAccountsFailed as exc:
            checkpoint.set_pending(unique_ids)
            bridge.error("download",
                         "LOGIN_FAILED" if len(accounts) == 1 else "ALL_ACCOUNTS_FAILED",
                         str(exc), fatal=True)
            bridge.done(ok=False, exit_code=1)
            return

        async def download_fn(uuid: str):
            return await download_single_log(uuid, downloader, collect_timing)

        async def convert(uuid: str, log, timing, full) -> None:
            await process_log(uuid, log, base_dir, timing, full,
                              save_debug, save_raw_json, mjai_semaphore=mj_sem)
            counters["cv"] += 1
            bridge.progress("convert", phase="mjai", done=counters["cv"], total=total,
                            uuid=uuid, ok=True)

        # 下載嚴格串行（單帳號單連線，一次只一個 RPC 在線上）；
        # 轉換丟背景 task 並行跑，不阻塞下一筆下載。
        for uuid in unique_ids:
            try:
                log, timing, full, err = await download_recovery.download_with_retry(
                    session, download_fn, uuid, max_attempts=max_attempts)
            except download_recovery.AllAccountsFailed:
                state["aborted"] = True
                break
            done_uuids.add(uuid)
            counters["dl"] += 1
            if not log:
                counters["fail"] += 1
                failures.append({"uuid": uuid, "error": err or "unknown error"})
                checkpoint.record_failure(uuid, err or "unknown error",
                                          session.current_username)
                bridge.progress("download", phase="download", done=counters["dl"],
                                total=total, uuid=uuid, ok=False, failed=counters["fail"])
                continue
            checkpoint.clear_failure(uuid)
            bridge.progress("download", phase="download", done=counters["dl"], total=total,
                            uuid=uuid, ok=True, failed=counters["fail"])
            convert_tasks.append(asyncio.create_task(convert(uuid, log, timing, full)))

        # 中止與否都要等已下載的牌譜轉完，避免漏寫 mjai 輸出。
        if convert_tasks:
            await asyncio.gather(*convert_tasks)

    # 清理暫存
    try:
        for fn in os.listdir("temp_logs"):
            os.remove(os.path.join("temp_logs", fn))
    except Exception:  # noqa: BLE001
        pass

    if state["aborted"]:
        # 號池全滅：記錄斷點（剩餘未處理清單），下次執行自動續跑。
        pending = [u for u in unique_ids if u not in done_uuids]
        checkpoint.set_pending(pending)
        bridge.error("download", "ALL_ACCOUNTS_FAILED",
                     f"尚餘 {len(pending)} 筆未處理，斷點：{checkpoint.path}", fatal=True)
        bridge.done(ok=False, exit_code=1)
        return

    checkpoint.set_pending([])
    checkpoint.delete_if_clean()
    bridge.stage_done("download", downloaded=counters["cv"], total=total,
                      failed=counters["fail"],
                      failed_uuids=[f["uuid"] for f in failures[:20]],
                      checkpoint_path=os.path.abspath(checkpoint.path) if counters["fail"] else "",
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
