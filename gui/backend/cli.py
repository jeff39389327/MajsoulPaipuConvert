# -*- coding: utf-8 -*-
"""cli —— backend 的統一進入點與子命令分派。

dev 模式可用 `python -m gui.backend.cli <cmd>`；凍結後即 `backend.exe <cmd>`。

子命令
------
  crawl        執行 Stage 1 (run_crawler)
  download     執行 Stage 2 (run_download，並行)
  doctor       環境自檢
  __extractor  (內部) 凍結模式下逐日 extractor 的自我再入；輸出原始 UUID 到真 stdout，
               供 PaipuSpider 的子程序解析迴圈讀取 (取代寫臨時 py 腳本 + python)。

參數一律走 stdin JSON (--params-stdin) / --params-file，避免帳密進 argv。
"""
from __future__ import annotations

import sys

from . import bridge


def _run_extractor(args: list[str]) -> None:
    """凍結再入：跑單日 OptimizedPaipuExtractor，把 UUID 印到真正的 stdout。"""
    import argparse

    # bridge 在 import 時把 sys.stdout 導向 stderr；此處還原，讓 print(pid) 回到真 stdout
    # (extractor 自身的 debug 仍走 sys.stderr，與原 temp_script 行為一致)。
    sys.stdout = bridge.real_stdout()

    parser = argparse.ArgumentParser(prog="backend __extractor")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--target-room", required=True)
    parser.add_argument("--headless", default="True")
    parser.add_argument("--fast", default="False")
    parser.add_argument("--player-mode", default="False")
    ns = parser.parse_args(args)

    from date_room_extractor import OptimizedPaipuExtractor, convert_ranks_to_english

    ranks = convert_ranks_to_english([ns.target_room])
    extractor = OptimizedPaipuExtractor(
        headless=ns.headless == "True",
        fast_mode=ns.fast == "True",
        player_mode=ns.player_mode == "True",
    )
    try:
        results = extractor.extract_from_rooms(
            target_date=ns.target_date, target_ranks=ranks, max_paipus=99999
        )
        for pid in results:
            print(pid)
    finally:
        extractor.close()


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else ""

    if cmd == "crawl":
        from . import run_crawler

        run_crawler.run(bridge.read_params())
    elif cmd == "download":
        from . import run_download

        run_download.run(bridge.read_params())
    elif cmd == "doctor":
        from . import doctor

        doctor.run(bridge.read_params())
    elif cmd == "__extractor":
        _run_extractor(argv[1:])
    else:
        bridge.error("cli", "UNKNOWN_COMMAND", f"unknown subcommand: {cmd!r}", fatal=True)
        bridge.done(ok=False, exit_code=2)


if __name__ == "__main__":
    main()
