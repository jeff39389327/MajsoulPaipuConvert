# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Communication language

一律使用**繁體中文**回覆使用者（程式碼、識別字與既有英文註解維持原樣）。

## Git workflow

Commit and push changes directly to `main`. Do **not** create feature branches or
pull requests for changes in this repo — work straight on `main`.

## What this is

A two-stage Windows/Python pipeline that scrapes Mahjong Soul (雀魂) game-log IDs from the
MajSoul Stats site (amae-koromo.sapk.ch) and then downloads + converts those games into
**tenhou.net/6** and **MJAI** formats, optionally annotated with per-action thinking time.

Hard constraints baked into the code: **4-player mahjong only**, **CN server only** (the
downloader logs in with username/password, which only CN accounts support).

## Commands

```powershell
# Install (note: scrapy/selenium are NOT in requirements.txt — install separately)
pip install -r requirements.txt
pip install scrapy selenium

# Stage 1 — collect game IDs
# MUST be run from the INNER package dir paipu_project/paipu_project/ — the spider reads
# crawler_config.json from CWD and imports date_room_extractor.py via a CWD-relative path
# (sys.path.insert(0, '.')), and BOTH files live in the inner dir. Scrapy still locates
# scrapy.cfg by searching upward into the outer paipu_project/. Running from the OUTER
# paipu_project/ silently falls back to the default "auto" config (crawler_config.json not
# found) and breaks the date_room / date_room_player modes (extractor import fails in the subprocess).
cd paipu_project/paipu_project
scrapy crawl paipu_spider                       # reads crawler_config.json from CWD (this dir)

# Stage 2 — download + convert (MUST be run from the repo root, see "tensoul-py-ng path" below)
cd ../..
python toumajsoul.py                            # reads config.env + tonpuulist.txt

# Validate produced MJAI logs
.\validate_logs.exe mahjong_logs/mjai
```

There is no test suite, linter, or build step. `validate_logs.exe` is the only verification tool
and it only checks the MJAI output directory.

## External dependencies (must be on PATH / present on disk)

- **`mjai-reviewer`** — the tenhou→MJAI conversion is done by shelling out to
  `mjai-reviewer --no-review` (see `toumajsoul.py:process_log`). Without it, only tenhou output is produced.
- **Google Chrome + matching ChromeDriver** — all scraping is Selenium-driven.
- **`tensoul-py-ng/`** — a vendored third-party package (MIT, from https://github.com/unStatiK/tensoul-py-ng),
  now **committed into this repo** (its upstream is unmaintained). It provides `MajsoulPaipuDownloader`.
  `toumajsoul.py` adds it to `sys.path` with a *relative* path (`sys.path.append('tensoul-py-ng')`), which
  is why Stage 2 must run from the repo root. Its runtime-generated `tensoul/ms_cfg.json` stays gitignored
  (via `tensoul-py-ng/.gitignore`); `ms_patch.ensure_ms_cfg()` creates it from `ms_cfg.example.json`.
- **`ms` protobuf package** — comes from the `ms_api` pip package (in requirements.txt), used to fetch
  raw `GameDetailRecords` for timing extraction. Do not confuse it with the `tensoul-py-ng/tensoul` package.

## Architecture

### Stage 1 — ID collection (`paipu_project/`, a Scrapy project)

The Scrapy framework here is essentially just a launcher. `PaipuSpider` issues **one** dummy request,
then in the callback drives **Selenium synchronously** to do all the real work — it does not use
Scrapy's request/scheduler engine for crawling. All scraping logic lives in:

- **`spiders/PaipuSpider.py`** — config loading (`CrawlerConfig` dataclass ← `crawler_config.json`),
  mode dispatch, and the `auto`/`manual` Selenium logic (leaderboard → player pages → `paipu=` links).
- **`date_room_extractor.py`** — the heavy Selenium engine (`OptimizedPaipuExtractor`) for the
  `date_room`/`date_room_player` modes. It is **not imported**; `PaipuSpider` writes a small temp
  driver script and runs it as a **subprocess per day**, parsing paipu IDs from the subprocess's
  **stdout** (regex-matched UUID lines) while all logs/debug go to **stderr**.

Five `crawler_mode` values:
- `auto` — scrape leaderboard top players for given ranks/periods, then collect each player's games.
- `manual` — use an explicit `manual_player_urls` list.
- `date_room` — for each day in `[start_date, end_date]` and `target_room`, find each game and resolve
  its UUID by opening a participant's player page and **time-matching the row** (this deliberately
  avoids the rate-limited `5-data.amae-koromo.com` API; `extract_paipu_via_redirect` is the old,
  deprecated API path kept only as a fallback).
- `date_room_player` — like `date_room` but visits **every** player's page per game for maximum
  coverage; supports **resume** via a `crawler_progress.json` checkpoint (deleted on clean completion).
- `date_room_api` — same inputs as `date_room` (`start_date`/`end_date`/`target_room`) but **no Selenium**:
  `spiders/akoromo_api.py` hits amae-koromo's backend JSON API directly. Because the room `games` endpoint
  returns **masked** short-code uuids (`"_masked": true`), it de-masks each game via the `player_records`
  endpoint (which returns the full `YYMMDD-…` uuid), time-matching on `startTime`. Two steps: enumerate the
  room (time-sliced into 6 h windows to stay under the 500-row cap, auto-bisecting on overflow) → resolve
  each game's full uuid (a per-`startTime` cache folds in whole player windows to cut requests). Runs
  in-process inside `PaipuSpider.start_crawling` (no per-day subprocess); writes UUIDs incrementally like
  the other modes. Faster and far more reliable than the Selenium `date_room`, but the API is rate-limited
  (tune `_REQ_DELAY` in `akoromo_api.py`).

Key Selenium realities to keep in mind when editing the extractor: the target site uses a
`ReactVirtualized` table (rows are recycled on scroll, so element references go stale — the code
re-finds elements via JS by index), heavy anti-detection JS is injected on every driver
(`apply_stealth_js` / `Page.addScriptToEvaluateOnNewDocument`), and headless mode needs explicit
"warm-up" scrolling to force virtual rows to render. `fast_mode` trades ~5-10% completeness for speed.

IDs are written **incrementally** (append + `flush()` as each is found), and on startup the spider
loads already-collected IDs from the output file to dedupe — so runs are resumable/interruptible.

### Stage 2 — download + convert (`toumajsoul.py`)

For each ID: `MajsoulPaipuDownloader.download()` → tenhou.net/6 dict → written to
`mahjong_logs/tenhou/`, then `mjai-reviewer --no-review` converts it to MJAI → gzipped into
`mahjong_logs/mjai/*.json.gz`. Already-downloaded IDs are skipped by checking the tenhou dir.

**Thinking-time injection** (when `COLLECT_TIMING=true`) is the subtle part:
`fetch_raw_timing_data` pulls raw protobuf `GameDetailRecords`; `extract_timing_data` walks the
actions and builds a `(seat, action_sequence_index) → timeuse_ms` map (incrementing a per-seat
counter on each discard/call, **skipping cancelled calls**); `inject_timing_to_mjai` then replays the
*same* per-actor counter over the MJAI event stream to attach `think_ms`. The two counters must stay
in lock-step — any change to which events advance the counter on one side must mirror the other, or
timings will misalign.

Behavior is driven by **`config.ini`** — the single unified settings file (sections `[account]`,
`[download]`, `[crawler]`, `[app]`). `config_store.load_into_env()` loads `[account]`/`[download]`
keys (`ms_username`, `ms_password`, `MS_RES_VERSION`, `ACCOUNT_POOL`, `COLLECT_TIMING`, `SAVE_DEBUG`,
`SAVE_RAW_JSON`) into `os.environ`, so the existing `os.getenv`-based code (`toumajsoul.py`,
`ms_patch.py`) is unchanged. Setting `SAVE_RAW_JSON` force-enables `COLLECT_TIMING`. If `config.ini`
is absent, the loader falls back to the legacy `config.env` (python-dotenv) for backward compat.
The GUI owns `config.ini`; on error 151, the recovered `ms_res_version` is written back into it
(see `config_store.set_value`).

**Failure recovery (`download_recovery.py`, shared by CLI and GUI backend).** Accounts come from
`load_accounts()`: primary `[account]` credentials plus `account_pool` (a JSON array of
`{"username","password"}`; reaches Python as env `ACCOUNT_POOL`). `AccountSession` wraps the single
shared `MajsoulPaipuDownloader`: on a download failure, `download_with_retry` first reconnects and
re-logs-in with the *same* account (which covers error 151 via the auto resource-version update),
then on the next failure rotates to the next pool account; a `generation` counter + asyncio lock
ensures concurrent workers trigger only one recovery, and a ready-event fence (`wait_ready`, awaited
at the top of each `download_with_retry` attempt) keeps concurrent workers from sending requests
during the reconnect window — doing so hits a half-built channel (`'NoneType' object has no
attribute 'send'`) or a connected-but-not-yet-logged-in session (server error 1004). Majsoul error
codes seen here: 151 = resource version expired, 1004 = session not logged in (transient, retry),
1203 = record does not exist (permanent). Only when *every* account fails to log in does
it raise `AllAccountsFailed` — the run aborts and `Checkpoint` (`download_checkpoint.json` in the
work dir) records the failed map (`uuid → {error, account, ts}`) and the still-pending list. Failed
uuids are retried automatically on the next run (they're not in the tenhou dir, so the normal dedupe
re-queues them); the checkpoint file is deleted when a run ends fully clean. `download_single_log`
returns a 4-tuple `(log, timing, full_record, error_msg)` — keep its error contract intact, the
retry logic keys off `log is None`.

## Gotchas

- **Filename AND directory mismatch between the two stages.** Stage 1 writes to `crawler_config.json`'s
  `output_filename` (currently `date_room_list.txt`) **in its CWD — the inner `paipu_project/paipu_project/`
  dir**, but `toumajsoul.py` runs from the repo root and **hardcodes reading `tonpuulist.txt`**
  (`toumajsoul.py:322`). After scraping you must copy the output to `tonpuulist.txt` in the repo root
  (or change the hardcoded name) before running Stage 2.
- `toumajsoul.py` and `download.py` contain **hardcoded fallback credentials**; `config.ini` (or the
  legacy `config.env` fallback) overrides them.
- `config.ini` is gitignored (holds credentials) — copy `config.ini.example` to `config.ini` and fill
  it in (CLI: at the repo root; GUI: next to the executable, auto-created/migrated). The GUI mirrors it
  to `userData` and restores it on launch, so it survives electron-updater (NSIS) reinstalls that wipe
  the install dir. The legacy `config.env` / `config.env.example` still work as a fallback for CLI use.
- **Never put output data in the install dir.** electron-updater's NSIS update wipes the install
  directory, so the packaged GUI's default `work_dir` is `Documents\MajsoulPaipuGUI` (persistent +
  findable), **not** the exe folder — otherwise `mahjong_logs/`, `tonpuulist.txt`,
  `download_checkpoint.json` etc. get deleted on every update. `main.js` `defaultWorkDir()` picks
  Documents (falls back to `userData/work`); `migrateLegacyWorkDirData()` moves any leftover data from
  the old exe-folder default on first launch. Only `config.ini` lives next to the exe (it has the
  mirror/restore safety net above).

## Legacy / non-pipeline files (don't assume these are part of the main flow)

- `download.py` — an alternate downloader importing `standard-mjlog-converter-main` (not present in
  the repo); superseded by `toumajsoul.py`.
- `clean.py`, `cleanlog.py` — tiny standalone dedupe utilities referencing legacy paths
  (`list.txt`, `tonpuulog/`), not wired into either stage.
- `paipu_project/.../items.py`, `pipelines.py`, `middlewares.py` — unused Scrapy boilerplate.
