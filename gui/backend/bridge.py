# -*- coding: utf-8 -*-
"""bridge —— runner 與 Electron 之間的 NDJSON 事件協定與共用工具。

設計重點
--------
stdout 必須是「乾淨的事件流」：每行恰好一個 JSON 物件 (見 emit)。但既有的
toumajsoul.py / PaipuSpider.py / scrapy / selenium 會大量呼叫 print()，預設會污染
stdout。因此本模組在 **import 時** 先保存真正的 stdout 給事件使用，再把 sys.stdout
導向 sys.stderr —— 之後所有 print()（含被 import 進來的既有模組）都落到 stderr，
Electron 將 stderr 當作「原始 log」顯示於可折疊區，stdout 則只剩事件。

事件型別 (type)
---------------
- stage_start : 一個階段開始              {stage, mode?}
- progress    : 進度更新                  {stage, phase?, done, total, ...}
- log         : 一般訊息 (debug 用)       {stage, level, msg}
- error       : 錯誤；fatal=True 會中止    {stage, code, msg, fatal}
- notice      : 非致命通知 (前端提示用)    {stage, code, msg}
- stage_done  : 階段完成                  {stage, stats:{...}}
- done        : 整個 job 結束             {ok, exit}

事件內**不放在地化字串**：error 用 code、progress 用 phase/stage enum，由前端 i18n
翻譯；msg 僅作 debug 原文。
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from datetime import datetime, timezone

# NDJSON 事件含非 ASCII（中文 msg 等）。Windows 上被 Electron spawn 時，stdout/stderr 是
# 管道、預設用 cp1252 編碼，寫中文會 UnicodeEncodeError。強制 UTF-8（與 Electron 端 readline
# 的 utf-8 解碼一致）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 在任何 print 重導之前，保存真正的 stdout 給事件流使用。
_EVENT_OUT = sys.stdout
# 之後所有 print()（含 import 進來的既有模組）一律導向 stderr，保持 stdout 乾淨。
sys.stdout = sys.stderr

# 不可出現在事件 log 中的敏感欄位 (避免帳密外洩到前端/log)。
_SENSITIVE_KEYS = {"ms_password", "password", "ms_token", "token", "access_token"}


def real_stdout():
    """取得未被重導的真正 stdout (供 __extractor 再入時輸出原始 UUID 給父程序解析)。"""
    return _EVENT_OUT


def emit(event: dict) -> None:
    """輸出一個 NDJSON 事件到真正的 stdout 並立即 flush。"""
    event.setdefault("ts", datetime.now(timezone.utc).isoformat())
    _EVENT_OUT.write(json.dumps(event, ensure_ascii=False) + "\n")
    _EVENT_OUT.flush()


def stage_start(stage: str, **extra) -> None:
    emit({"stage": stage, "type": "stage_start", **extra})


def progress(stage: str, **extra) -> None:
    emit({"stage": stage, "type": "progress", **extra})


def log(stage: str, msg: str, level: str = "info") -> None:
    emit({"stage": stage, "type": "log", "level": level, "msg": msg})


def error(stage: str, code: str, msg: str = "", fatal: bool = True) -> None:
    emit({"stage": stage, "type": "error", "code": code, "msg": msg, "fatal": fatal})


def notice(stage: str, code: str, msg: str = "") -> None:
    """非致命的狀態通知 (前端顯示提示但不中止流程)，例如「自動更新資源版本中」。"""
    emit({"stage": stage, "type": "notice", "code": code, "msg": msg})


def stage_done(stage: str, **stats) -> None:
    emit({"stage": stage, "type": "stage_done", "stats": stats})


def done(ok: bool = True, exit_code: int = 0) -> None:
    emit({"type": "done", "ok": ok, "exit": exit_code})


def has_flag(name: str) -> bool:
    return name in sys.argv[1:]


def redact(params: dict) -> dict:
    """回傳遮蔽敏感欄位後的副本 (供 log/debug 顯示)。"""
    out = {}
    for k, v in params.items():
        out[k] = "***" if k in _SENSITIVE_KEYS else v
    return out


def read_params() -> dict:
    """讀取 job 參數。

    優先順序：
      --params-stdin           從 stdin 讀整包 JSON (敏感資料走這條，不進 argv)
      --params-file <path>     從檔案讀 JSON
      argv 中第一個以 '{' 開頭的參數  直接當 JSON (僅供非敏感的手動測試)
      皆無 -> {}
    """
    args = sys.argv[1:]
    if "--params-stdin" in args:
        data = sys.stdin.read()
        return json.loads(data) if data.strip() else {}
    if "--params-file" in args:
        path = args[args.index("--params-file") + 1]
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    for a in args:
        if a.startswith("{"):
            return json.loads(a)
    return {}


@contextlib.contextmanager
def chdir(path: str):
    """暫時切換 CWD (Stage 1 需 inner dir、Stage 2 需 work dir)。"""
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def is_frozen() -> bool:
    """是否為 PyInstaller 凍結後的執行檔。"""
    return bool(getattr(sys, "frozen", False))
