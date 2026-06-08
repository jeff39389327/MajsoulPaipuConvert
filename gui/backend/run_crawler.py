# -*- coding: utf-8 -*-
"""run_crawler —— 包裝 Stage 1 (爬牌譜 ID)。

職責
----
1. 把 GUI 傳來的 crawler 設定寫進 inner dir 的 crawler_config.json。
2. 啟動 scrapy spider (dev: 外部 scrapy CLI；凍結: CrawlerProcess)。
3. 解析子程序輸出中的牌譜 UUID，emit 不定量 progress (Stage 1 無法預知總數)。
4. 完成時 emit stage_done，附上輸出檔的絕對路徑 (供 Stage 2 直接接手，繞過
   tonpuulist.txt 的硬編碼 gotcha)。

注意：Selenium 本質序列、逐 player/逐日，無法並行加速，這裡只提供「不定量進度 +
可中斷 + resume」體驗。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading

from . import bridge, paths

_UUID_RE = re.compile(
    r"[0-9]{6}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def _count_ids(output_path: str) -> tuple[int, str | None]:
    """數出輸出檔目前的 UUID 筆數與最後一筆 (供即時進度回報)。檔案不存在時回 (0, None)。"""
    count, current = 0, None
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            for ln in f:
                if _UUID_RE.search(ln):
                    count += 1
                    current = ln.strip()
    except FileNotFoundError:
        pass
    return count, current


def _watch_output(output_path: str, stop_evt: threading.Event) -> None:
    """凍結模式下 process.start() 會阻塞主執行緒、無法逐行解析 stdout；改以背景執行緒輪詢
    輸出檔 (spider 逐筆 append+flush 寫入)，收集數變動時 emit progress，讓前端的計數與
    進度條會即時更新 (與 dev 模式的逐行解析等效)。"""
    last = -1
    while not stop_evt.is_set():
        count, current = _count_ids(output_path)
        if count != last:
            last = count
            bridge.progress("crawl", unit="id", count=count, total=None, current=current)
        stop_evt.wait(0.8)


def _write_config(params: dict) -> str:
    """把 params['config'] 寫成 inner dir 的 crawler_config.json，回傳 output 檔絕對路徑。"""
    cfg = dict(params.get("config") or {})
    cfg_path = paths.crawler_config_path(params)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    output_filename = cfg.get("output_filename") or "tonpuulist.txt"
    return str((paths.inner_dir(params) / output_filename).resolve())


def _run_scrapy_cli(params: dict, output_path: str) -> None:
    """dev 模式：以子程序執行 `scrapy crawl paipu_spider`，解析 stdout 統計進度。"""
    cfg = params.get("config") or {}
    bridge.stage_start("crawl", mode=cfg.get("crawler_mode", "auto"))

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    # 以「正在跑後端的同一個 Python」呼叫 scrapy：GUI 用 .venv/Scripts/python.exe 啟動本
    # 程序，但 venv 的 Scripts/ 不在 PATH 上，裸 `scrapy` 會 FileNotFoundError。-m scrapy
    # 必用該直譯器的 scrapy，與其相依一致。(此分支僅 dev 模式走到，sys.executable 即 venv python。)
    proc = subprocess.Popen(
        [sys.executable, "-m", "scrapy", "crawl", "paipu_spider"],
        cwd=str(paths.inner_dir(params)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    seen: set[str] = set()
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            # 原始 spider/extractor 輸出 -> stderr (sys.stdout 已被 bridge 導向 stderr)
            print(line)
        m = _UUID_RE.search(line)
        if m and m.group(0) not in seen:
            seen.add(m.group(0))
            bridge.progress("crawl", unit="id", count=len(seen), total=None, current=m.group(0))

    rc = proc.wait()
    if rc != 0:
        bridge.error("crawl", "SCRAPY_FAILED", f"scrapy exited with {rc}", fatal=True)
        bridge.done(ok=False, exit_code=rc)
        return
    bridge.stage_done("crawl", collected=len(seen), output_file=output_path)
    bridge.done(ok=True)


def _run_scrapy_frozen(params: dict, output_path: str) -> None:
    """凍結模式：以 CrawlerProcess 程式化啟動 (無外部 scrapy CLI)。

    需在含 crawler_config.json 的 inner dir 內執行，spider 與 settings 已 bundle。
    逐日 extractor 的 subprocess 再入由 PaipuSpider (frozen dual-mode) 處理。
    """
    cfg = params.get("config") or {}
    bridge.stage_start("crawl", mode=cfg.get("crawler_mode", "auto"))

    inner = str(paths.inner_dir(params))
    if inner not in sys.path:
        sys.path.insert(0, inner)

    # process.start() 會阻塞主執行緒，故用背景執行緒輪詢輸出檔回報即時收集數 (進度條/計數會動)。
    stop_evt = threading.Event()
    watcher = threading.Thread(target=_watch_output, args=(output_path, stop_evt), daemon=True)
    watcher.start()
    try:
        with bridge.chdir(inner):
            os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "paipu_project.settings")
            from scrapy.crawler import CrawlerProcess  # noqa: WPS433 (frozen import)
            from scrapy.utils.project import get_project_settings  # noqa: WPS433

            # 凍結後不能用名稱啟動 spider：Scrapy 的 SpiderLoader 透過 pkgutil.iter_modules
            # 掃描 SPIDER_MODULES 來探索 spider，但 PyInstaller 把模組封進 exe，frozen importer
            # 的套件路徑列舉不到 bundle 進去的 paipu_project.spiders.PaipuSpider，
            # process.crawl("paipu_spider") 會同步丟 "Spider not found"（這正是 GUI 看到的
            # CRAWL_EXCEPTION）。改為直接 import 類別、以類別啟動，完全繞過名稱解析/探索。
            from paipu_project.spiders.PaipuSpider import PaipuSpider  # noqa: WPS433

            process = CrawlerProcess(get_project_settings())
            process.crawl(PaipuSpider)
            process.start()  # 阻塞直到完成
    finally:
        stop_evt.set()
        watcher.join(timeout=2)

    # 由輸出檔回報最終數量 (watcher 已停，避免與 stage_done 競寫 stdout)。
    collected, _ = _count_ids(output_path)
    bridge.stage_done("crawl", collected=collected, output_file=output_path)
    bridge.done(ok=True)


def run(params: dict) -> None:
    output_path = _write_config(params)
    try:
        if bridge.is_frozen():
            _run_scrapy_frozen(params, output_path)
        else:
            _run_scrapy_cli(params, output_path)
    except Exception as exc:  # noqa: BLE001 - 回報致命錯誤碼給前端
        # 完整堆疊印到 stderr（GUI 把 stderr 當原始 log 顯示於可折疊面板），方便診斷；
        # 同時把例外字串放進 error event 的 msg，前端會一併呈現於錯誤框。
        import traceback

        traceback.print_exc()
        bridge.error("crawl", "CRAWL_EXCEPTION", str(exc), fatal=True)
        bridge.done(ok=False, exit_code=1)


if __name__ == "__main__":
    run(bridge.read_params())
