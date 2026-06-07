# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— 把 gui/backend (含 scrapy/selenium/tensoul/ms_api) 凍成單一
backend.exe，子命令分派 crawl|download|doctor|__extractor。

tensoul-py-ng 已納入本 repo，checkout 即帶著。執行：在 gui/ 下 `pyinstaller build/backend.spec`
(或 npm run freeze)。

PyInstaller 對 scrapy/twisted/selenium 這類大量動態 import + 讀套件 metadata 的套件，
單靠自動分析常會漏東西。此處用 collect_all（datas+binaries+hiddenimports 一網打盡）與
copy_metadata（scrapy/twisted 會以 metadata 取版本）盡量補齊，再加上已知會被動態載入的
模組（twisted reactor、scrapy 各子系統）。
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# build/ -> gui -> <repo root>
GUI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))
REPO_ROOT = os.path.dirname(GUI_DIR)
TENSOUL_DIR = os.path.join(REPO_ROOT, 'tensoul-py-ng')

datas, binaries, hiddenimports = [], [], []

# collect_all：把每個套件的 data/binary/submodule 全部收進來（最保險）。
for pkg in ('scrapy', 'twisted', 'selenium', 'tensoul', 'webdriver_manager',
            'google', 'ms', 'nest_asyncio'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# 純 submodule 收集（這些不需 data，但動態 import 居多）。
for pkg in ('dotenv', 'tqdm', 'ujson', 'gui.backend'):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

# scrapy / twisted 以套件 metadata 取版本 (importlib.metadata)，缺 metadata 會在
# runtime 拋 PackageNotFoundError。
for pkg in ('scrapy', 'twisted', 'protobuf', 'ms_api'):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# 已知會被動態載入、collect_all 偶爾仍漏的關鍵模組。
hiddenimports += [
    # twisted reactor（settings.py 指定 asyncioreactor）
    'twisted.internet.asyncioreactor',
    'twisted.internet.asyncio',
    # scrapy 各子系統常被字串路徑動態載入
    'scrapy.spiderloader',
    'scrapy.statscollectors',
    'scrapy.logformatter',
    'scrapy.extensions.corestats',
    'scrapy.extensions.telnet',
    'scrapy.extensions.memusage',
    'scrapy.extensions.logstats',
    'scrapy.core.scheduler',
    'scrapy.core.downloader.handlers.http',
    'scrapy.core.downloader.handlers.https',
    'scrapy.utils.spider',
    'scrapy.squeues',
    'scrapy.pqueues',
    # 本 repo 既有模組（凍結後仍需 import）
    'toumajsoul', 'ms_patch', 'date_room_extractor',
    'paipu_project.settings', 'paipu_project.spiders.PaipuSpider',
    # protobuf runtime
    'google.protobuf', 'google.protobuf.json_format',
]

# tensoul 的 cfg.json / ms_cfg.example.json 等資料檔（collect_all('tensoul') 通常已含，
# 仍顯式補一份保險）。
for fname in ('cfg.json', 'ms_cfg.example.json', 'constants.py'):
    src = os.path.join(TENSOUL_DIR, 'tensoul', fname)
    if os.path.exists(src):
        datas.append((src, 'tensoul'))

# 把既有 repo 模組與 inner scrapy 專案、tensoul-py-ng 納入搜尋路徑。
pathex = [
    REPO_ROOT,
    TENSOUL_DIR,
    os.path.join(REPO_ROOT, 'paipu_project', 'paipu_project'),
]

a = Analysis(
    [os.path.join(GUI_DIR, 'backend', '_frozen_entry.py')],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
