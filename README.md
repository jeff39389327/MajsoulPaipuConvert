# MajsoulPaipuConvert

Tool for converting Mahjong Soul game logs to MJAI format.

## Introduction

Download game logs from MajSoul Stats and convert them to MJAI format. Supports automated crawling and manual player specification.

**Important Notes:**
- Only supports 4-player mahjong (3-player requires mjai-reviewer modifications)
- Currently only compatible with CN server
- Requires CN server account (username/password login supported)

## Features

- Unified configuration file for all modes
- Three modes: auto leaderboard, manual player, date room batch
- Supported ranks: Throne/Jade/Gold and East variants
- Supported periods: 4w/1w/3d/1d
- Automatic thinking time collection (optional)
- Direct tenhou.net/6 format output

## Requirements

- Python 3.8+
- pip
- Git
- Google Chrome + ChromeDriver
- [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer)

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
pip install scrapy selenium
```

### 2. Install External Tools

- Install [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer) and add to system PATH
- Install [Google Chrome](https://www.google.com/chrome/)
- Download matching [ChromeDriver](https://chromedriver.chromium.org/) and add to PATH

## Configuration

### Crawler Configuration

Create or modify `crawler_config.json` in `paipu_project/paipu_project/` directory:

#### Mode A: Auto Mode (Crawl from Leaderboard)

```json
{
  "crawler_mode": "auto",
  "time_periods": ["4w", "1w", "3d"],
  "ranks": ["Gold"],
  "max_players_per_period": 20,
  "paipu_limit": 9999,
  "output_filename": "tonpuulist.txt",
  "headless_mode": true,
  "save_screenshots": true
}
```

#### Mode B: Manual Mode (Specify Players)

```json
{
  "crawler_mode": "manual",
  "manual_player_urls": [
    "https://amae-koromo.sapk.ch/player/123456789/12",
    "https://amae-koromo.sapk.ch/player/987654321/12"
  ],
  "paipu_limit": 9999,
  "output_filename": "manual_paipu.txt",
  "headless_mode": true
}
```

#### Mode C: Date Room Mode (Batch Crawl Date Range)

```json
{
  "crawler_mode": "date_room",
  "start_date": "2019-08-20",
  "end_date": "2019-08-23",
  "target_room": "Jade",
  "output_filename": "date_room_list.txt",
  "headless_mode": true,
  "fast_mode": false
}
```

**Date Room Mode Notes:**
- Applicable for Throne/Jade rank data from 2019-08-23 onwards
- fast_mode: false for complete mode (100% accuracy, ~30-40 records/min)
- fast_mode: true for fast mode (slightly faster, suitable for large-scale collection)

#### Mode D: Date Room Player Mode (Comprehensive Player Page Crawl)

```json
{
  "crawler_mode": "date_room_player",
  "start_date": "2019-08-20",
  "end_date": "2019-08-23",
  "target_room": "Jade",
  "output_filename": "date_room_player_list.txt",
  "headless_mode": true,
  "fast_mode": false
}
```

**Date Room Player Mode Notes:**
- For each game in the date range, visits all player pages to collect all game logs
- More comprehensive than date_room mode, captures all games from all players
- Slower than date_room mode but ensures maximum coverage
- Recommended for complete historical data collection

### Configuration Parameters

| Parameter | Description | Options | Default |
|-----------|-------------|---------|---------|
| `crawler_mode` | Crawler mode | `"auto"`, `"manual"`, `"date_room"`, `"date_room_player"` | `"auto"` |
| `manual_player_urls` | Manual player URL list | URL array | `[]` |
| `time_periods` | Time periods (auto mode) | `"4w"`, `"1w"`, `"3d"`, `"1d"` | `["4w", "1w", "3d"]` |
| `ranks` | Ranks (auto mode) | `"Throne"`, `"Jade"`, `"Gold"`, `"Throne East"`, `"Jade East"`, `"Gold East"`, `"All"` | `["Gold"]` |
| `max_players_per_period` | Players per period | 1-50 | `20` |
| `paipu_limit` | Logs per player | Any positive integer | `9999` |
| `output_filename` | Output filename | Any filename | `"tonpuulist.txt"` |
| `headless_mode` | Headless mode (background) | `true`, `false` | `true` |
| `save_screenshots` | Save verification screenshots | `true`, `false` | `true` |
| `start_date` | Start date (date_room mode) | `"YYYY-MM-DD"` | - |
| `end_date` | End date (date_room mode) | `"YYYY-MM-DD"` | - |
| `target_room` | Target room (date_room mode) | `"Throne"`, `"Jade"`, `"Gold"`, etc. | - |
| `fast_mode` | Fast mode (date_room mode) | `true`, `false` | `false` |

### Mahjong Soul Account Configuration

Edit `config.env` file:

```env
# Mahjong Soul authentication
ms_username=your_email@example.com
ms_password=your_password

# Thinking time collection (optional)
# true: enable thinking time collection, false: disable (default: true)
COLLECT_TIMING=true
```

**Parameter Description:**
- `ms_username`: Mahjong Soul account email
- `ms_password`: Mahjong Soul account password
- `COLLECT_TIMING`: Whether to collect thinking time data
  - `true`: Add `think_ms` field in MJAI format (milliseconds)
  - `false`: Standard MJAI format without thinking time

## Usage

### 1. Collect Game IDs

```bash
cd paipu_project
scrapy crawl paipu_spider
```

Output file (e.g., `tonpuulist.txt`) format:
```
241103-057ea444-a219-4202-930e-2d2472f4d6e600
241104-12345678-abcd-efgh-ijkl-mnopqrstuvwx00
```

### 2. Download and Convert Logs

```bash
cd ..
python toumajsoul.py
```

Logs saved in `mahjong_logs` directory:
```
mahjong_logs/
├── mjai/           # MJAI format (with think_ms)
│   └── *.json.gz
└── tenhou/         # Tenhou.net/6 format
    └── *.json
```

### 3. Validate Logs

```bash
validate_logs.exe mahjong_logs/mjai
```

## Thinking Time Data

When `COLLECT_TIMING=true`, MJAI output includes `think_ms` field:

**Standard output:**
```json
{"type": "dahai", "actor": 0, "pai": "W", "tsumogiri": false}
```

**With thinking time:**
```json
{"type": "dahai", "actor": 0, "pai": "W", "think_ms": 2864, "tsumogiri": false}
```

**Data Description:**
- `think_ms`: Milliseconds from receiving tile to making action
- Includes all player actions: discard, chi, pon, kan, riichi
- Typical values:
  - Quick discard: 1000-3000 ms
  - Thoughtful discard: 2000-15000 ms
  - Calls: 500-5000 ms

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
pip install scrapy selenium

# 2. Configure files
#    - Edit crawler_config.json (choose mode)
#    - Edit config.env (set account and COLLECT_TIMING)

# 3. Collect game IDs
cd paipu_project
scrapy crawl paipu_spider

# 4. Download logs
cd ..
python toumajsoul.py

# 5. Validate logs
validate_logs.exe mahjong_logs/mjai
```

## Troubleshooting

**ChromeDriver error:** Ensure ChromeDriver version matches Chrome browser

**Empty results:** Check network connection and configuration settings

**No think_ms field:** Verify `COLLECT_TIMING=true` in `config.env`

**Configuration errors:** Program will validate and display error messages

## License

This project uses the following open source components:
- [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer) - Apache-2.0 License
- [tensoul-py-ng](https://github.com/unStatiK/tensoul-py-ng) - MIT License

## Acknowledgments

- [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer) - Log analysis tool
- [tensoul-py-ng](https://github.com/unStatiK/tensoul-py-ng) - Mahjong Soul log downloader
- [MajSoul Stats](https://amae-koromo.sapk.ch/) - Data source
- [Scrapy](https://scrapy.org/) - Web scraping framework
- [Selenium](https://selenium.dev/) - Browser automation
