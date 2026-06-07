# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— 把 gui/backend (含 scrapy/selenium/tensoul/ms_api) 凍成單一
backend.exe，子命令分派 crawl|download|doctor|__extractor。

凍結前提：build 機器須先 `git clone` 好 <repo>/tensoul-py-ng/ (gitignored)，否則
tensoul 收集不到。執行：在 gui/ 下 `pyinstaller build/backend.spec` (或 npm run freeze)。
"""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# build/ -> gui -> <repo root>
GUI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))
REPO_ROOT = os.path.dirname(GUI_DIR)
TENSOUL_DIR = os.path.join(REPO_ROOT, 'tensoul-py-ng')

# scrapy / selenium / tensoul 大量使用動態 import，需顯式收集 submodules。
hiddenimports = []
for pkg in ('scrapy', 'selenium', 'tensoul', 'ms', 'twisted', 'dotenv', 'tqdm',
            'google.protobuf', 'webdriver_manager', 'ujson', 'nest_asyncio',
            'gui.backend'):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

# scrapy 的 VERSION、mime types、tensoul 的 ms_cfg 範本等資料檔。
datas = []
for pkg in ('scrapy', 'tensoul'):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

# 把既有 repo 模組 (toumajsoul / ms_patch / date_room_extractor / spider) 與 inner
# scrapy 專案、tensoul-py-ng 一併納入搜尋路徑，讓凍結後可 import。
pathex = [
    REPO_ROOT,
    TENSOUL_DIR,
    os.path.join(REPO_ROOT, 'paipu_project', 'paipu_project'),
]

a = Analysis(
    [os.path.join(GUI_DIR, 'backend', '_frozen_entry.py')],
    pathex=pathex,
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports + [
        'toumajsoul', 'ms_patch', 'date_room_extractor',
        'paipu_project.settings', 'paipu_project.spiders.PaipuSpider',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='backend',
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='backend',  # 產出 dist/backend/ (onedir，啟動較快)
)
