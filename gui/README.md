# 雀魂牌譜 Pipeline — Electron 一體式 GUI

把原本兩階段的 Python CLI（爬牌譜 ID → 下載＋轉換）包成一個引導式桌面 App：
**選擇下載方式 → 下載 ID → 下載牌譜＋轉換 MJAI → 設定**，全程實時進度、可取消，
並支援 Stage 2 並行下載與並行轉換。介面支援 i18n（繁中／English／日本語）。

## 架構

```
Electron (main/preload/renderer)
        │  spawn，stdin 傳 JSON 參數（含帳密，不進 argv）
        ▼
gui/backend (Python)  ──►  NDJSON 事件（stdout）；原始 log → stderr
   cli.py 子命令分派：crawl | download | doctor | __extractor
   run_crawler.py  → 啟動既有 scrapy spider（Stage 1）
   run_download.py → 重用 toumajsoul 的 download_single_log / process_log，
                      並行調度（Semaphore 控制下載與 mjai 轉換並發）
```

- **事件協定**：stdout 每行一個 JSON（`stage_start｜progress｜log｜error｜stage_done｜done`）。
  錯誤只回機器碼（`error.code`）、進度只回 `phase`/`stage`，由前端 i18n 翻譯。
- **自動銜接**：Stage 1 完成的輸出檔路徑會直接當成 Stage 2 的輸入清單，免去手動把
  `date_room_list.txt` 複製成 `tonpuulist.txt` 的舊痛點。

## 開發模式（需本機 Python 環境）

前置：repo 根目錄已可跑原本的 pipeline（`pip install -r requirements.txt`、
`pip install scrapy selenium`、clone 好 `tensoul-py-ng/`、`mjai-reviewer` 在 PATH、安裝 Chrome）。

```bash
cd gui
npm install
npm start          # 啟動 GUI
npm test           # 後端 NDJSON 協定煙霧測試（不需 Chrome / 雀魂）
```

設定頁可填雀魂帳密（寫入 repo 根的 `config.env`）、思考時間等選項、下載/轉換並發數、
工作目錄與介面語言；爬蟲設定寫入 `paipu_project/paipu_project/crawler_config.json`。

## 打包（全凍結，Windows）

使用者免裝 Python 與 mjai-reviewer；**仍需自備 Chrome 瀏覽器**（Stage 1 Selenium 必需）。

前置：
1. repo 根目錄 clone 好 `tensoul-py-ng/`。
2. `pip install pyinstaller`。
3. 把 `mjai-reviewer.exe` 放到 `gui/vendor/mjai-reviewer.exe`。
4.（選用）放 `gui/assets/icon.ico` 自訂圖示；未提供則用 Electron 預設圖示。

```bash
cd gui
npm install
npm run freeze     # PyInstaller → gui/backend/dist/backend/backend.exe
npm run dist       # freeze + electron-builder → ../dist_gui/ 的 NSIS 安裝檔
```

打包版首次啟動請於設定選一個「工作／輸出資料夾」（存放 config.env、crawler_config.json、
`mahjong_logs/` 輸出）。

## CI／CD（自動打包並發佈到 Releases）

`.github/workflows/release.yml` 會在 **push 到 `main`**（或手動 `workflow_dispatch`）時，於
Windows runner 上完成全凍結打包，並把 `.exe` 上傳到 GitHub Releases 的 rolling **`latest`**
預發佈版。

打包前 CI 會自動取得兩個 gitignored / 外部相依：

- **tensoul-py-ng**：由 repo 變數／密鑰 `TENSOUL_REPO_URL` clone。請到
  **Settings → Secrets and variables → Actions** 新增：公開 repo 用 *Variables* 的
  `TENSOUL_REPO_URL`；私有 repo 用 *Secrets*（URL 內含 token）。
  （若改成把 `tensoul-py-ng` 直接納入本 repo，移除 workflow 的 clone 步驟即可。）
- **mjai-reviewer.exe**：自動從 `Equim-chan/mjai-reviewer` 的 Releases 下載 Windows 版。

> 首次跑可能因 PyInstaller 對 scrapy/selenium 的 hidden-import 收集不全而需要在
> `gui/build/backend.spec` 補項；冒煙測試 `node gui/test/smoke.js` 已先在 CI 跑過以驗證後端協定。

## 與既有程式碼的關係

唯一改動的既有檔是 `toumajsoul.py`（`process_log` 新增可選 `mjai_semaphore`、mjai 轉換改
async subprocess 並可由 `MJAI_REVIEWER_BIN` 覆寫路徑）與 `PaipuSpider.py`（凍結時逐日
extractor 改用 `backend.exe __extractor` 自我再入）。兩者皆向下相容，原本的 CLI 流程不受影響。
