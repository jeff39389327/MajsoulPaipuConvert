# -*- coding: utf-8 -*-
"""config_store —— 單一 config.ini 的 Python 端讀寫（GUI 與 CLI 共用）。

設計
----
所有 pipeline 設定集中在「與執行檔同層」的單一 config.ini（升級會被 GUI 自動保留，
見 gui/electron）。本模組負責 **Python 端** 的兩件事：

1. ``load_into_env``：把 [account] / [download] 區段的相關鍵載入 ``os.environ``，
   使既有的 ``toumajsoul.py`` / ``ms_patch.py``（皆以 ``os.getenv`` 取值）原封不動可用。
   若 config.ini 不存在，回退讀舊的 ``config.env``（dotenv 格式），維持向後相容。

2. ``set_value``：以 **逐行、保留註解** 的方式就地更新單一鍵（供 error 151 自動更新後把
   ``ms_res_version`` 寫回 config.ini）。刻意不使用 ``configparser.write()``，因其會丟失
   檔內所有註解 / 排版。

config.ini 區段 / 鍵 → 環境變數 名稱的對照（鍵一律小寫，與 Node 端 configIni.js 對齊）。
"""
from __future__ import annotations

import os
from pathlib import Path

# (section, key) -> 環境變數名稱。只列出需要進 os.environ 的鍵。
_ENV_MAP: dict[tuple[str, str], str] = {
    ("account", "ms_username"): "ms_username",
    ("account", "ms_password"): "ms_password",
    ("account", "ms_res_version"): "MS_RES_VERSION",
    # 備用帳號池（JSON 陣列 [{"username","password"},...]），下載失敗時輪替（download_recovery）。
    ("account", "account_pool"): "ACCOUNT_POOL",
    ("download", "collect_timing"): "COLLECT_TIMING",
    ("download", "save_debug"): "SAVE_DEBUG",
    ("download", "save_raw_json"): "SAVE_RAW_JSON",
}

DEFAULT_FILENAME = "config.ini"


def default_path() -> str:
    """預設 config.ini 路徑（CWD 下）。CLI 從 repo root 執行，GUI 後端則由 params 明確指定。"""
    return os.path.join(os.getcwd(), DEFAULT_FILENAME)


def _read_ini(path: str) -> dict[str, dict[str, str]]:
    """以 configparser 解析 config.ini，回傳 {section: {key: value}}（鍵小寫）。檔案缺失回空。"""
    import configparser

    # interpolation=None：值原樣讀取。預設的 BasicInterpolation 會把值內的 '%' 當
    # 插值語法（密碼或 account_pool JSON 含 '%' 即拋 InterpolationSyntaxError）。
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str.lower  # 鍵小寫（與 Node 端一致）
    try:
        with open(path, "r", encoding="utf-8") as f:
            parser.read_file(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return {sec.lower(): dict(parser.items(sec)) for sec in parser.sections()}


def load_into_env(path: str | None = None) -> bool:
    """把 config.ini 的相關鍵載入 os.environ（只覆寫非空值，保留 getenv 預設回退語意）。

    回傳是否有載入到任何來源（config.ini 或回退的 config.env）。
    """
    path = path or default_path()

    if os.path.exists(path):
        data = _read_ini(path)
        for (section, key), env_name in _ENV_MAP.items():
            val = (data.get(section) or {}).get(key, "")
            # 只設定非空值：空值代表「未設定」，交給 os.getenv 的預設回退（如 MS_RES_VERSION
            # 留空 → ms_patch 用內建預設）。
            if val != "":
                os.environ[env_name] = val
        return True

    # 回退：舊的 config.env（dotenv）。同目錄優先，其次 CWD。
    legacy = os.path.join(os.path.dirname(path) or ".", "config.env")
    for candidate in (legacy, "config.env"):
        if os.path.exists(candidate):
            try:
                import dotenv

                dotenv.load_dotenv(candidate)
                return True
            except Exception:
                pass
    return False


def set_value(path: str, section: str, key: str, value: str) -> None:
    """逐行就地更新 config.ini 的 [section] key=value，**保留註解與排版**。

    - 檔案 / 區段 / 鍵不存在時會建立（區段缺則追加於檔尾）。
    - 鍵與 section 一律以小寫比對（與 Node 端、_read_ini 一致）。
    """
    section = section.lower()
    key = key.lower()
    p = Path(path)
    try:
        lines = p.read_text(encoding="utf-8").split("\n")
    except FileNotFoundError:
        lines = []

    out: list[str] = []
    in_target = False
    replaced = False
    section_seen = False
    new_line = f"{key} = {value}"

    for raw in lines:
        stripped = raw.strip()
        header = stripped[1:-1].strip().lower() if (stripped.startswith("[") and stripped.endswith("]")) else None

        if header is not None:
            # 離開目標區段卻還沒寫到 key → 在區段結尾補上。
            if in_target and not replaced:
                out.append(new_line)
                replaced = True
            in_target = header == section
            if in_target:
                section_seen = True
            out.append(raw)
            continue

        if in_target and not replaced and stripped and not stripped.startswith(("#", ";")):
            idx = stripped.find("=")
            if idx >= 0 and stripped[:idx].strip().lower() == key:
                out.append(new_line)
                replaced = True
                continue

        out.append(raw)

    # 檔尾仍在目標區段、key 未寫入 → 補一行。
    if in_target and not replaced:
        out.append(new_line)
        replaced = True

    # 整個檔案都沒有該區段 → 追加新區段。
    if not section_seen:
        if out and out[-1].strip() != "":
            out.append("")
        out.append(f"[{section}]")
        out.append(new_line)

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out), encoding="utf-8")
