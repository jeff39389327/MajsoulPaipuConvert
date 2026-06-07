import ujson
from pathlib import Path

with open(Path(__file__).parent / "cfg.json", "r", encoding="utf-8") as f:
    cfg = ujson.load(f)

with open(Path(__file__).parent / "ms_cfg.json", "r", encoding="utf-8") as f:
    ms_cfg = ujson.load(f)

__all__ = ("cfg", "ms_cfg")
