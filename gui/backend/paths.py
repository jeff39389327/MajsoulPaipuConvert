# -*- coding: utf-8 -*-
"""路徑解析 —— 統一處理 dev 與凍結 (PyInstaller) 兩種模式下的關鍵目錄。

關鍵約束 (見專案 CLAUDE.md)：
- Stage 1 (scrapy) 必須在 inner dir `paipu_project/paipu_project/` 執行。
- Stage 2 (toumajsoul) 必須在「含 toumajsoul.py / tensoul-py-ng / config.env」的
  工作目錄執行。

dev 模式：repo_root = gui 的上一層 (gui/backend/paths.py -> parents[2])。
凍結模式：repo 程式碼已 bundle 進 exe，但 config.env / mahjong_logs / crawler_config.json
          等「資料」需放在使用者指定的 work_dir。故所有路徑優先採用 params 傳入的
          repo_root / work_dir，缺省才回退推導值。
"""
from __future__ import annotations

import os
from pathlib import Path

from . import bridge

# gui/backend/paths.py -> gui/backend -> gui -> <repo root>
_BACKEND_DIR = Path(__file__).resolve().parent
_DERIVED_REPO_ROOT = _BACKEND_DIR.parents[1]


def repo_root(params: dict | None = None) -> Path:
    """含 toumajsoul.py / tensoul-py-ng 的目錄 (Stage 2 import 來源)。"""
    params = params or {}
    if params.get("repo_root"):
        return Path(params["repo_root"]).resolve()
    env = os.getenv("MS_REPO_ROOT")
    if env:
        return Path(env).resolve()
    return _DERIVED_REPO_ROOT


def work_dir(params: dict | None = None) -> Path:
    """放 config.env / crawler_config.json / mahjong_logs 的工作目錄。

    dev 預設等於 repo_root；凍結版由使用者於 GUI 指定 (params.work_dir)。
    """
    params = params or {}
    if params.get("work_dir"):
        return Path(params["work_dir"]).resolve()
    env = os.getenv("MS_WORK_DIR")
    if env:
        return Path(env).resolve()
    return repo_root(params)


def inner_dir(params: dict | None = None) -> Path:
    """Stage 1 scrapy 的執行目錄（放 crawler_config.json 與輸出檔的可寫位置）。

    dev：repo 內的 inner package dir（spider 透過 CWD 相對路徑載入 date_room_extractor，
         crawler_config.json 也在此）。
    凍結：repo_root 位於唯讀的 process.resourcesPath 底下，不可寫；spider/extractor/settings
         皆已 bundle 進 backend.exe（import 不依賴 CWD），故改用使用者選定、可寫的 work_dir。
         crawler_config.json 與爬取輸出都落在 work_dir，Stage 2 的銜接也指向 work_dir 內的檔案。
    """
    if bridge.is_frozen():
        return work_dir(params)
    return repo_root(params) / "paipu_project" / "paipu_project"


def crawler_config_path(params: dict | None = None) -> Path:
    """crawler_config.json 的位置 (Stage 1 由此讀取設定)。"""
    return inner_dir(params) / "crawler_config.json"


def ensure_repo_on_syspath(params: dict | None = None) -> None:
    """把 repo_root 與 tensoul-py-ng 加到 sys.path，使 dev 模式能 import 既有模組。

    凍結模式下這些模組已 bundle，import 仍可用，重複加入無害。
    """
    import sys

    root = repo_root(params)
    for p in (str(root), str(root / "tensoul-py-ng")):
        if p not in sys.path:
            sys.path.insert(0, p)
