# 三麻（3-player / sanma）支援

本管線現在同時支援**四麻**與**三麻**。四麻流程完全不變；三麻在**下載 + 轉換**階段自動處理，
並在**抓 ID（爬蟲）階段**新增三麻房間選項。

## 運作方式

### 下載 + 轉換（Stage 2，自動偵測）

雀魂牌譜下載後，`tensoul` 會依牌譜玩家數自動產出對應 mjai：

- **四麻**：`tenhou.net/6 JSON → mjai-reviewer (convlog) → mjai`（與原本一致）。
- **三麻**：`mjai-reviewer`/convlog **硬性拒絕三麻**（`disp` 含「三」→ NotFourPlayer），
  因此改用 **tensoul 直出的 mjai 事件串流**，對齊
  [mortal-sanma](https://github.com/Mateces/mortal-sanma) 的 `libriichi3p` 規格
  （真三席：`names[3]`、`tehais[3][13]`、`actor` 限 0–2、`deltas[3]`、`nukidora` 拔北事件、無吃）。

關鍵實作：mjai 事件**與既有的 tenhou6 解析在同一條「按序走訪 protobuf record」的迴圈中產生**
（`tensoul/parser.py`），因此完整重用 tensoul 已驗證的計分/delta 邏輯（包牌、自摸損、雙響 delta 拆分），
事件順序天然正確（不需要 convlog 那套從 tenhou6 反推 actor 的回溯演算法）。

涉及檔案：
- `tensoul-py-ng/tensoul/model.py` — `Tile.encode_mjai()`
- `tensoul-py-ng/tensoul/parser.py` — `MajsoulPaipuParser` 內聯產生 mjai（`set_mjai_header` / `finalize_mjai`）
- `tensoul-py-ng/tensoul/downloader.py` — `download()` 回傳的 dict 多一個 `res["mjai"]`
- `toumajsoul.py` `process_log` — 三麻寫直出 mjai、四麻維持 mjai-reviewer

### 抓 ID（Stage 1，GUI 選項）

GUI 的「純 API（`date_room_api`）」模式新增 **遊戲類型：四麻 / 三麻** 下拉選單。
三麻會改打 amae-koromo 的 **pl3** 端點與三麻房間 mode_id：

| 房間 | 四麻(pl4) | 三麻(pl3) 南 | 三麻(pl3) 東 |
|------|-----------|--------------|--------------|
| 王座 Throne | 16 | 26 | 25 |
| 玉 Jade | 12 | 24 | 23 |
| 金 Gold | 9 | 22 | 21 |

涉及檔案：`paipu_project/.../akoromo_api.py`、`PaipuSpider.py`（`game_mode` 欄位）、
`gui/renderer/views/step-mode.js`、`gui/renderer/i18n/*.json`。
（三麻收集僅 `date_room_api` 純 API 模式支援；Selenium 模式仍只有四麻。）

## 驗證

- **四麻正確性**：tensoul 直出的 mjai 與 `mjai-reviewer` 的輸出在多張真實牌譜上**逐事件位元組一致**
  （`batch_diff.py`）——證明事件產生引擎正確。
- **三麻正確性**：用實際從原始碼編譯的 mortal-sanma `libriichi3p`，把產出的三麻 mjai 逐事件
  replay 過 `PlayerState`（對齊 `libriichi/src/bin/validate_logs.rs`），**20+ 張真實 majsoul 三麻譜全數通過**
  （`validate_mjai_libriichi.py`、`run_sanma_accept.py`）。

### 在本機編譯 libriichi3p（Windows）

mortal-sanma 只提供 Linux 預編譯 `.so`。本機（Windows / Python 3.11 venv）自行編譯方式：

```bash
# 1) Rust（gnu host，含 rust-mingw 連結器）
curl -sSfL -o rustup-init.exe https://win.rustup.rs/x86_64
./rustup-init.exe -y --default-host x86_64-pc-windows-gnu --profile minimal
# 2) 完整 mingw-w64（minimal toolchain 缺 as.exe/dlltool 需要的組譯器）— WinLibs 可攜版
#    解壓後把 mingw64/bin 置於 PATH 最前
# 3) maturin 編譯（跳過 mimalloc 的 C 編譯；指向 .venv 的 python）
pip install maturin
cd mortal-sanma/libriichi
maturin build --no-default-features --features pymod -i <venv python>
pip install <產出的 .whl>
```

## ⚠️ 在 mortal-sanma libriichi3p 中發現的兩個 nukidora bug（已修正）

未修正前，約 1/3 真實 majsoul 三麻譜無法通過 `libriichi3p`，**根因全在 mortal-sanma 自身**（與本轉換器無關）。
修正後**全數通過**。修正內容見 `mortal-sanma-nukidora-fix.patch`（`libriichi/src/state/update.rs`）：

1. **立直中無法拔北**：`tsumo` handler 在 `if riichi_accepted { …; return }` 早退，永遠執行不到
   `can_nukidora` 的設定——但其**自身註解明說拔北在立直中允許**。修正：在立直分支補上 `can_nukidora`。
2. **拔北誤計入 4-槓上限**：拔北會 `kans_on_board += 1`（與槓共用計數），導致單局拔北+槓超過 4 次後
   後續拔北/加槓全被擋。但拔北不是槓，且一局最多可拔 4 張北＋做槓（>4 次嶺上補抽，majsoul 允許）。
   「牌山耗盡」其實已由各 gate 的 `tiles_left > 0` 保護。修正：拔北不再增加 `kans_on_board`。

> 這兩個 bug 對「用 mortal-sanma 跑 majsoul 三麻牌譜訓練/推論」影響重大，建議回報上游或套用此 patch。
