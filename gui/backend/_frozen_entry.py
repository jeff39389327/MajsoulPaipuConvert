# -*- coding: utf-8 -*-
"""PyInstaller 凍結的進入點腳本。

以「絕對 import」呼叫 cli.main（PyInstaller 直接分析此檔，非套件內相對 import 情境，
故不用 `from .cli`）。pathex 含 repo root，使 `gui.backend.cli` 可解析。
"""
from gui.backend.cli import main

if __name__ == "__main__":
    main()
