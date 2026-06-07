# -*- coding: utf-8 -*-
"""doctor —— 環境自檢，回傳結構化結果 (機器碼)，由前端 i18n 翻譯成提示。

凍結版 (一般使用者)：Python 與套件已內建、mjai-reviewer 已隨附，主要只需確認
**Chrome 瀏覽器** 是否存在 (Stage 1 Selenium 必需) 與 work_dir 可寫。
dev 模式 (開發者)：額外檢查 pip 套件、PATH 上的 mjai-reviewer、tensoul-py-ng 是否 clone。
"""
from __future__ import annotations

import os
import shutil
import sys

from . import bridge, paths


def _check_import(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def _find_chrome() -> str | None:
    """嘗試找到 Chrome 瀏覽器執行檔 (跨平台)。找不到回 None。"""
    candidates = [
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _find_mjai() -> str | None:
    """凍結版優先用內建的 MJAI_REVIEWER_BIN，否則找 PATH 上的 mjai-reviewer。"""
    env = os.getenv("MJAI_REVIEWER_BIN")
    if env and os.path.exists(env):
        return env
    return shutil.which("mjai-reviewer")


def run(params: dict | None = None) -> dict:
    params = params or {}
    bridge.stage_start("doctor")

    if bridge.has_flag("--mock"):
        result = {
            "frozen": bridge.is_frozen(),
            "python": sys.version.split()[0],
            "chrome": "/usr/bin/google-chrome",
            "mjai_reviewer": "mjai-reviewer",
            "tensoul": True,
            "work_dir_writable": True,
            "packages": {},
            "ok": True,
        }
        bridge.stage_done("doctor", **result)
        bridge.done(ok=True)
        return result

    frozen = bridge.is_frozen()
    wd = paths.work_dir(params)
    chrome = _find_chrome()
    mjai = _find_mjai()

    result: dict = {
        "frozen": frozen,
        "python": sys.version.split()[0],
        "chrome": chrome,
        "mjai_reviewer": mjai,
        "work_dir": str(wd),
        "work_dir_writable": os.access(wd, os.W_OK) if wd.exists() else os.access(wd.parent, os.W_OK),
    }

    if not frozen:
        # dev 模式：檢查 pip 套件與 vendored tensoul
        pkgs = {
            "scrapy": _check_import("scrapy"),
            "selenium": _check_import("selenium"),
            "dotenv": _check_import("dotenv"),
            "tqdm": _check_import("tqdm"),
            "google.protobuf": _check_import("google.protobuf"),
            "ms": _check_import("ms.protocol_pb2"),
        }
        paths.ensure_repo_on_syspath(params)
        tensoul_ok = os.path.isdir(paths.repo_root(params) / "tensoul-py-ng" / "tensoul")
        result["packages"] = pkgs
        result["tensoul"] = tensoul_ok

    # ok 判定：Chrome 一定要有 (Stage 1)；dev 還要套件齊全
    ok = chrome is not None
    if not frozen:
        ok = ok and all(result["packages"].values()) and result.get("tensoul", False)
    result["ok"] = ok

    bridge.stage_done("doctor", **result)
    bridge.done(ok=True)
    return result


if __name__ == "__main__":
    run(bridge.read_params())
