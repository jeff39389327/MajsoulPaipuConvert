# -*- coding: utf-8 -*-
"""
管線離線測試 —— 不需任何雀魂帳密 / 網路登入，驗證「整個流程」中可離線確認的環節：

  1. 相依與模組可正常 import（Stage 2 的 tensoul / ms / ms_patch、Stage 1 的爬蟲設定）
  2. tenhou.net/6 -> mjai 轉換（呼叫外部 mjai-reviewer，使用內附去識別化牌譜 fixture）
  3. 思考時間注入邏輯 inject_timing_to_mjai 的 per-actor 計數器鎖步行為
  4. 爬蟲 CrawlerConfig 各模式的設定驗證

需要真實帳密的「下載」環節（Stage 2 的 MajsoulPaipuDownloader.download）不在此測試，
改由 workflow 中、僅在 GitHub Secrets 存在時才執行的線上 e2e job 涵蓋，避免曝露 .env。
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(REPO_ROOT, "tests", "fixtures", "sample_tenhou.json")

# 讓 `import toumajsoul`（其頂層會 sys.path.append('tensoul-py-ng') 並 import tensoul）
# 能在 repo root 的相對路徑下運作。
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)


def test_stage2_imports():
    """Stage 2 的下載/轉換模組鏈可完整 import（tensoul / ms / ms_patch）。"""
    import toumajsoul  # noqa: F401  匯入即觸發 tensoul/ms 載入

    assert hasattr(toumajsoul, "inject_timing_to_mjai")
    assert hasattr(toumajsoul, "extract_timing_data")
    assert hasattr(toumajsoul, "process_log")


def test_stage1_spider_import():
    """Stage 1 的爬蟲設定類別可 import 並具備驗證方法。"""
    sys.path.insert(0, os.path.join(REPO_ROOT, "paipu_project", "paipu_project"))
    from spiders.PaipuSpider import CrawlerConfig

    assert hasattr(CrawlerConfig, "validate")


def test_mjai_conversion():
    """以內附 fixture 跑 mjai-reviewer 轉換，驗證輸出為合理的 mjai 事件串。"""
    assert shutil.which("mjai-reviewer"), "需要 mjai-reviewer 於 PATH（CI 由 setup_env.sh 建置）"
    assert os.path.exists(FIXTURE), "缺少 fixture sample_tenhou.json"

    out = os.path.join(REPO_ROOT, "tests", "_out_mjai.json")
    try:
        res = subprocess.run(
            ["mjai-reviewer", "--no-review", "-i", FIXTURE, "--mjai-out", out],
            capture_output=True, text=True,
        )
        assert res.returncode == 0, f"mjai-reviewer 失敗: {res.stderr}"

        events = [json.loads(line) for line in open(out, encoding="utf-8") if line.strip()]
        types = {e["type"] for e in events}

        # 起手 / 開局 / 打牌 / 結算 等核心事件都應出現
        assert {"start_game", "start_kyoku", "tsumo", "dahai", "end_game"} <= types
        # fixture 為 9 局南場，start_kyoku 應有 9 個
        assert sum(1 for e in events if e["type"] == "start_kyoku") == 9
        # 去識別化的名稱應原樣帶過
        start = next(e for e in events if e["type"] == "start_game")
        assert start["names"] == ["A", "B", "C", "D"]
    finally:
        if os.path.exists(out):
            os.remove(out)


def test_inject_timing_lockstep(tmp_path):
    """inject_timing_to_mjai 應以 per-actor 計數器，把 timing_map 對應到 dahai/reach/鳴牌事件。"""
    import toumajsoul

    mjai_lines = [
        {"type": "start_game"},
        {"type": "start_kyoku"},
        {"type": "tsumo", "actor": 0, "pai": "1m"},
        {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": True},   # (0,0)
        {"type": "tsumo", "actor": 1, "pai": "2p"},
        {"type": "dahai", "actor": 1, "pai": "2p", "tsumogiri": True},   # (1,0)
        {"type": "tsumo", "actor": 0, "pai": "3s"},
        {"type": "dahai", "actor": 0, "pai": "9m", "tsumogiri": False},  # (0,1)
        {"type": "reach", "actor": 0},                                    # (0,2)
        {"type": "pon", "actor": 2, "pai": "5p"},                        # (2,0)
    ]
    mjai_file = tmp_path / "in.json"
    with open(mjai_file, "w", encoding="utf-8") as f:
        for e in mjai_lines:
            f.write(json.dumps(e) + "\n")

    timing_map = {(0, 0): 100, (1, 0): 300, (0, 1): 200, (0, 2): 400, (2, 0): 500}
    toumajsoul.inject_timing_to_mjai(str(mjai_file), timing_map)

    out = [json.loads(line) for line in open(mjai_file, encoding="utf-8")]
    by = lambda t, a: [e for e in out if e["type"] == t and e.get("actor") == a]

    assert by("dahai", 0)[0]["think_ms"] == 100   # (0,0)
    assert by("dahai", 0)[1]["think_ms"] == 200   # (0,1)
    assert by("reach", 0)[0]["think_ms"] == 400   # (0,2) reach 計入同一計數器
    assert by("dahai", 1)[0]["think_ms"] == 300   # (1,0)
    assert by("pon", 2)[0]["think_ms"] == 500     # (2,0)
    # 非動作事件不應被加上 think_ms
    assert "think_ms" not in by("tsumo", 0)[0]


@pytest.mark.parametrize("cfg,ok", [
    ({"crawler_mode": "manual",
      "manual_player_urls": ["https://amae-koromo.sapk.ch/player/69951433/12"]}, True),
    ({"crawler_mode": "auto", "time_periods": ["4w"], "ranks": ["Jade"]}, True),
    ({"crawler_mode": "date_room_player", "start_date": "2024-01-01",
      "end_date": "2024-01-02", "target_room": "Jade"}, True),
    ({"crawler_mode": "manual", "manual_player_urls": []}, False),     # 缺 URL
    ({"crawler_mode": "auto", "time_periods": [], "ranks": []}, False),  # 缺設定
])
def test_crawler_config_validation(cfg, ok):
    """各爬蟲模式的設定驗證：合法者通過、缺漏者拋 ValueError。"""
    sys.path.insert(0, os.path.join(REPO_ROOT, "paipu_project", "paipu_project"))
    from spiders.PaipuSpider import CrawlerConfig

    c = CrawlerConfig(**cfg)
    if ok:
        c.validate()
    else:
        with pytest.raises(ValueError):
            c.validate()
