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
- 迴圈只做網路那一段（`fetch_record`）：解析（`decode_record`，純 CPU、單筆約 70 ms）
  與寫檔/轉換一律丟背景，讓串行下載的節奏只被雀魂 RTT（實測約 0.46 s/筆）限制，
  而不是「RTT + 本機處理」。`slots` 限制在途後處理筆數以免記憶體堆積。
- 轉換並發：mjai-reviewer 是外部 binary，可安全多開 -> Semaphore(convert_concurrency)
  (預設 = CPU 核心，上限 8)。下載完成即丟背景轉換，不阻塞下一筆下載。

失敗復原 (download_recovery，repo root 共用模組)
------------------------------------------------
- 依錯誤性質決定復原強度：牌譜級錯誤（1203 牌譜不存在）直接放棄；連線／會話級
  （151、1004、斷線）才重連＋重登，再失敗才切換 [account] account_pool 的備用帳號；
  全部帳號不可用才中止。
- 斷點：work_dir/download_checkpoint.json（＋ _failed.jsonl / _pending.txt 兩個附檔）
  記錄失敗項與中止時未處理清單；下次執行自動重試，全部成功即自動刪除。

帳密來源：不經 argv，改由單一 config.ini 讀取 (路徑由 params.config_ini_path 帶入，GUI 全面
管理該檔；缺檔回退舊 config.env)；params 僅帶非敏感的並發/旗標設定。
"""
from __future__ import annotations

import asyncio
import os
import time

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
        from toumajsoul import decode_record, fetch_record, process_log
        MajsoulPaipuDownloader = toumajsoul.MajsoulPaipuDownloader
        ms_patch.ensure_ms_cfg()
    finally:
        os.chdir(cwd_for_import)

    # 設定 (params 覆寫 > config.env > 預設)
    username = params.get("username") or os.getenv("ms_username", "")
    password = params.get("password") or os.getenv("ms_password", "")
    collect_timing = params.get("collect_timing", _bool_env("COLLECT_TIMING", False))
    save_debug = params.get("save_debug", _bool_env("SAVE_DEBUG", False))
    save_raw_json = params.get("save_raw_json", _bool_env("SAVE_RAW_JSON", False))
    if save_raw_json and not collect_timing:
        collect_timing = True

    # 0 / 缺省 = 自動（CPU 核心，上限 8）。不可為 0：Semaphore(0) 會讓轉換永遠等不到名額。
    convert_concurrency = max(1, int(params.get("convert_concurrency") or 0)
                              or min(8, os.cpu_count() or 4))

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
    # 斷點檔：記錄失敗項與中止時的未處理清單。先載入並把 pending/failed 併回工作
    # 清單——清單被重爬覆蓋或換檔時，上次中止的項目才不會默默消失（斷點才算真的有讀）。
    checkpoint = download_recovery.Checkpoint(
        os.path.join(work_dir, "download_checkpoint.json")).load()
    ids = download_recovery.merge_checkpoint_ids(ids, checkpoint)
    if not ids:
        bridge.error("download", "NO_INPUT_LIST", input_path, fatal=True)
        bridge.done(ok=False, exit_code=1)
        return
    unique_ids = _filter_existing(ids, base_dir)
    total = len(unique_ids)
    del ids  # 百萬筆規模時每份副本都是數百 MB，用不到就立刻放掉

    # 只要「有幾筆是續跑的」，不要為此再造一份百萬筆清單。
    resume_set = set(checkpoint.pending)
    resume_set.update(checkpoint.failed)
    retry_count = sum(1 for u in unique_ids if u in resume_set)
    del resume_set
    # pending 已併入工作清單，記憶體中不需再留（磁碟上的 _pending.txt 仍是續跑來源，
    # 只有 set_pending() 會覆寫它）。
    checkpoint.forget_pending()

    bridge.stage_start("download", total=total, collect_timing=collect_timing,
                       convert_concurrency=convert_concurrency,
                       accounts=len(accounts), input_list=input_path)
    if retry_count:
        bridge.notice("download", "RETRY_PREV_FAILED", str(retry_count))

    if total == 0:
        bridge.stage_done("download", downloaded=0, total=0,
                          output_dir=os.path.abspath(base_dir))
        bridge.done(ok=True)
        return

    mj_sem = asyncio.Semaphore(convert_concurrency)
    counters = {"dl": 0, "cv": 0, "fail": 0}
    # 下載是嚴格串行、依序走 unique_ids，所以「還沒處理的」＝目前索引之後的切片。
    # 不用 done_uuids 集合：百萬筆規模下它會長成另一份數百 MB 的副本。
    next_index = 0
    failures: list[dict] = []
    state = {"aborted": False}
    convert_tasks: set = set()
    max_attempts = 3 if len(accounts) > 1 else 2

    async with MajsoulPaipuDownloader() as downloader:
        session = download_recovery.AccountSession(
            downloader, accounts, ini_paths=ini_paths,
            notify=lambda code, msg="": bridge.notice("download", code, msg))
        try:
            await session.ensure_login()
        except download_recovery.AllAccountsFailed as exc:
            checkpoint.set_pending(unique_ids)
            checkpoint.close()
            # 最終仍是 error 151 → 自動探測全滅，改用帶「如何手動查版本」指引的錯誤碼，
            # 而非誤導使用者去檢查帳密。
            if ms_patch.is_resource_version_error(exc):
                code = "VERSION_UPDATE_FAILED"
            else:
                code = "LOGIN_FAILED" if len(accounts) == 1 else "ALL_ACCOUNTS_FAILED"
            bridge.error("download", code, str(exc), fatal=True)
            bridge.done(ok=False, exit_code=1)
            return

        session.start_keepalive()

        # 下載迴圈只做網路那一段；解析（純 CPU，單筆約 70 ms）與轉換一律丟背景，
        # 使串行下載的節奏只受雀魂 RTT 限制。
        async def download_fn(uuid: str):
            res, err = await fetch_record(uuid, downloader)
            return res, None, None, err

        loop = asyncio.get_event_loop()
        # slots 限制在途的後處理筆數，避免下載比轉換快時，未處理的回應在記憶體中無限堆積。
        slots = asyncio.Semaphore(convert_concurrency * 2)

        async def convert(uuid: str, res) -> None:
            try:
                try:
                    log, timing, full = await loop.run_in_executor(
                        None, decode_record, res, downloader, collect_timing)
                except Exception as exc:  # noqa: BLE001 解析失敗＝這筆沒有任何輸出
                    counters["fail"] += 1
                    failures.append({"uuid": uuid, "error": str(exc)})
                    checkpoint.record_failure(uuid, str(exc), session.current_username)
                    bridge.progress("convert", phase="mjai", done=counters["cv"], total=total,
                                    uuid=uuid, ok=False, failed=counters["fail"])
                    return
                try:
                    await process_log(uuid, log, base_dir, timing, full,
                                      save_debug, save_raw_json, mjai_semaphore=mj_sem)
                except Exception as exc:  # noqa: BLE001 寫檔/轉換失敗只回報，不記斷點
                    # （tenhou 輸出可能已寫出，記入斷點反而會因去重而永遠留在失敗清單）
                    bridge.progress("convert", phase="mjai", done=counters["cv"], total=total,
                                    uuid=uuid, ok=False, failed=counters["fail"])
                    bridge.log("download", f"process_log 失敗 {uuid}: {exc}", level="warn")
                    return
                counters["cv"] += 1
                bridge.progress("convert", phase="mjai", done=counters["cv"], total=total,
                                uuid=uuid, ok=True)
            finally:
                slots.release()

        # 下載嚴格串行（單帳號單連線，一次只一個 RPC 在線上）；
        # 轉換丟背景 task 並行跑，不阻塞下一筆下載。
        started = time.perf_counter()
        try:
            for index, uuid in enumerate(unique_ids):
                next_index = index
                t0 = time.perf_counter()
                try:
                    res, _, _, err = await download_recovery.download_with_retry(
                        session, download_fn, uuid, max_attempts=max_attempts)
                except download_recovery.AllAccountsFailed:
                    state["aborted"] = True
                    break
                # net_ms＝這筆花在雀魂來回的時間，rate＝整體平均筆/秒。慢的時候可據此
                # 分辨是網路（net_ms 就很大）還是本機（net_ms 小但 rate 低）。
                net_ms = int((time.perf_counter() - t0) * 1000)
                counters["dl"] += 1
                next_index = index + 1
                rate = round(counters["dl"] / max(1e-6, time.perf_counter() - started), 2)
                if res is None:
                    counters["fail"] += 1
                    failures.append({"uuid": uuid, "error": err or "unknown error"})
                    checkpoint.record_failure(uuid, err or "unknown error",
                                              session.current_username)
                    bridge.progress("download", phase="download", done=counters["dl"],
                                    total=total, uuid=uuid, ok=False, failed=counters["fail"],
                                    net_ms=net_ms, rate=rate)
                    continue
                checkpoint.clear_failure(uuid)
                bridge.progress("download", phase="download", done=counters["dl"], total=total,
                                uuid=uuid, ok=True, failed=counters["fail"],
                                net_ms=net_ms, rate=rate)
                # 連線異常緩慢（節點抽壞或帳號被限流）→ 重連換節點＋換下一個帳號。
                slow = session.note_timing(net_ms / 1000)
                if slow is not None:
                    bridge.notice("download", "SLOW_SESSION", f"{slow:.1f}")
                    try:
                        await session.recover(session.generation, force_switch=True,
                                              reason=f"連線異常緩慢（{slow:.1f}s/筆）")
                    except download_recovery.AllAccountsFailed:
                        state["aborted"] = True
                        break
                await slots.acquire()
                task = asyncio.ensure_future(convert(uuid, res))
                convert_tasks.add(task)
                task.add_done_callback(convert_tasks.discard)  # 完成即移除，長時間執行不累積

            # 中止與否都要等已下載的牌譜轉完，避免漏寫 mjai 輸出。
            if convert_tasks:
                await asyncio.gather(*list(convert_tasks), return_exceptions=True)
        finally:
            await session.stop_keepalive()  # 心跳任務不可留到連線關閉之後

    # 清理暫存
    try:
        for fn in os.listdir("temp_logs"):
            os.remove(os.path.join("temp_logs", fn))
    except Exception:  # noqa: BLE001
        pass

    if state["aborted"]:
        # 號池全滅：記錄斷點（剩餘未處理清單＝索引之後的切片），下次執行自動續跑。
        pending = unique_ids[next_index:]
        checkpoint.set_pending(pending)
        checkpoint.close()
        bridge.error("download", "ALL_ACCOUNTS_FAILED",
                     f"尚餘 {len(pending)} 筆未處理，斷點：{checkpoint.path}", fatal=True)
        bridge.done(ok=False, exit_code=1)
        return

    checkpoint.set_pending([])
    checkpoint.close()
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
