# -*- coding: utf-8 -*-
"""freeze_backend —— 以 PyInstaller 凍結 backend 成 backend.exe。

由 `npm run freeze` 呼叫 (cwd = gui/)。輸出到 gui/backend/dist/backend/，electron-builder
再透過 extraResources 收進安裝包。

凍結前提：repo 必須先 clone 好 tensoul-py-ng/ (gitignored)，否則 tensoul 收集不到。
"""
from __future__ import annotations

import os
import subprocess
import sys

GUI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(GUI_DIR)
SPEC = os.path.join(GUI_DIR, "build", "backend.spec")
DIST = os.path.join(GUI_DIR, "backend", "dist")
WORK = os.path.join(GUI_DIR, "backend", "build")


def main() -> int:
    tensoul = os.path.join(REPO_ROOT, "tensoul-py-ng", "tensoul")
    if not os.path.isdir(tensoul):
        print("[freeze] 錯誤：找不到 tensoul-py-ng/。請先在 repo 根目錄 clone：", file=sys.stderr)
        print("[freeze]   git clone <tensoul-py-ng repo> tensoul-py-ng", file=sys.stderr)
        return 2

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[freeze] 錯誤：未安裝 pyinstaller。請先 `pip install pyinstaller`。", file=sys.stderr)
        return 2

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", DIST,
        "--workpath", WORK,
        SPEC,
    ]
    print("[freeze] 執行:", " ".join(cmd))
    return subprocess.call(cmd, cwd=GUI_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
