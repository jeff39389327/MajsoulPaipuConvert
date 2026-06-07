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

from . import bridge, paths

_UUID_RE = re.compile(
    r"[0-9]{6}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def _write_config(params: dict) -> str:
    """把 params['config'] 寫成 inner dir 的 crawler_config.json，回傳 output 檔絕對路徑。"""
    cfg = dict(params.get("config") or {})
    cfg_path = paths.crawler_config_path(params)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    output_filename = cfg.get("output_filename") or "tonpuulist.txt"
    return str((paths.inner_dir(params) / output_filename).resolve())


def _dry_run(params: dict, output_path: str) -> None:
    """不啟動 scrapy/selenium，產生假 ID 驗證事件序列與檔案寫入。"""
    cfg = params.get("config") or {}
    bridge.stage_start("crawl", mode=cfg.get("crawler_mode", "auto"))
    seen = set()
    with open(output_path, "a", encoding="utf-8") as out:
        for i in range(5):
            fake = f"24010{i}-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            if fake not in seen:
                seen.add(fake)
                out.write(fake + "\n")
                out.flush()
                bridge.progress("crawl", unit="id", count=len(seen), total=None, current=fake)
    bridge.stage_done("crawl", collected=len(seen), output_file=output_path)
    bridge.done(ok=True)


def _run_scrapy_cli(params: dict, output_path: str) -> None:
    """dev 模式：以子程序執行 `scrapy crawl paipu_spider`，解析 stdout 統計進度。"""
    cfg = params.get("config") or {}
    bridge.stage_start("crawl", mode=cfg.get("crawler_mode", "auto"))

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        ["scrapy", "crawl", "paipu_spider"],
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
    with bridge.chdir(inner):
        os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "paipu_project.settings")
        from scrapy.crawler import CrawlerProcess  # noqa: WPS433 (frozen import)
        from scrapy.utils.project import get_project_settings  # noqa: WPS433

        process = CrawlerProcess(get_project_settings())
        process.crawl("paipu_spider")
        process.start()  # 阻塞直到完成

    # 凍結模式下無法即時逐行解析，改由輸出檔行數回報最終數量。
    collected = 0
    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            collected = sum(1 for ln in f if _UUID_RE.search(ln))
    bridge.stage_done("crawl", collected=collected, output_file=output_path)
    bridge.done(ok=True)


def run(params: dict) -> None:
    output_path = _write_config(params)
    try:
        if bridge.has_flag("--dry-run"):
            _dry_run(params, output_path)
        elif bridge.is_frozen():
            _run_scrapy_frozen(params, output_path)
        else:
            _run_scrapy_cli(params, output_path)
    except Exception as exc:  # noqa: BLE001 - 回報致命錯誤碼給前端
        bridge.error("crawl", "CRAWL_EXCEPTION", str(exc), fatal=True)
        bridge.done(ok=False, exit_code=1)


if __name__ == "__main__":
    run(bridge.read_params())
