# <div align="center">**MajsoulPaipuConvert**</div>

## Integration Project
**Convert Mahjong Soul game logs to MJAI format using mjai-reviewer and tensoul-py-ng**

This tool downloads game logs from MajSoul Stats and converts them to the MJAI format with a configurable crawler system for flexible data collection.

## ⚠️ Important Notes
- This tool collects data from third-party websites and games
- Only supports 4-player mahjong (三麻/3-player requires modifications to mjai-reviewer)
- Currently only compatible with CN server
- Uses mjai-reviewer (Apache-2.0 License)
- Uses tensoul-py-ng for Mahjong Soul log downloading in tenhou.net/6 format

> If you find any missing attributions or licensing issues, please submit an ISSUE. Your feedback helps us maintain proper attribution and licensing compliance.

## ✨ New Features
- 🎯 **Unified Configuration**: Single JSON config file for all modes
- 🔄 **Mode Switching**: Easily switch between auto/manual modes 
- 🚀 **Automated Collection**: Auto-collect from ranking leaderboards
- 📊 **Multi-Rank Support**: Throne/Jade/Gold + East variants
- ⏰ **Multi-Period**: 4w/1w/3d/1d rankings
- 🔧 **Legacy Compatible**: Full support for manual player selection
- 📝 **Validation**: Automatic configuration validation with helpful error messages
- 🔄 **Migration**: Migrated to tensoul-py-ng for direct tenhou.net/6 format output
- ⏱️ **Think Time Collection**: Automatically collect and inject player thinking time (milliseconds) into MJAI format

## 🔄 Migration Notes
This project now uses `tensoul-py-ng` for improved:
- **Direct Format**: Downloads directly in tenhou.net/6 format, eliminating conversion steps
- **Stability**: Better error handling and connection management
- **Compatibility**: Native support for Mahjong Soul CN server
- **Simplified Pipeline**: Reduced dependencies and processing steps

## Prerequisites
Before installation, ensure you have:
- Python 3.8+
- pip (Python package manager)
- Git
- Google Chrome + ChromeDriver

## Installation and Setup

### **Step 1: Install Dependencies**
```bash
pip install -r requirements.txt
pip install scrapy selenium
```

**Required External Tools:**
- Install [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer)
  - Ensure it's added to your system PATH or properly referenced in your configuration
- Install [Google Chrome](https://www.google.com/chrome/)
- Download matching [ChromeDriver](https://chromedriver.chromium.org/) and add to PATH

### **Step 2: Configuration**

#### **2.1 Configure Crawler Settings**
Create or modify `crawler_config.json` in the `paipu_project/paipu_project/` directory:

**🎯 Choose Your Mode:**

**Option A: Automated Mode (For Positive Ranking crawling)**
```json
{
  "crawler_mode": "auto",
  "manual_player_urls": [],
  "time_periods": ["4w", "1w", "3d"],
  "ranks": ["Gold"],
  "max_players_per_period": 20,
  "paipu_limit": 9999,
  "output_filename": "tonpuulist.txt",
  "headless_mode": true,
  "save_screenshots": true
}
```

**Option B: Manual Mode ( For Specific Player crawling)**
```json
{
  "crawler_mode": "manual",
  "manual_player_urls": [
    "https://amae-koromo.sapk.ch/player/123456789/12",
    "https://amae-koromo.sapk.ch/player/987654321/12",
    "https://amae-koromo.sapk.ch/player/555666777/12"
  ],
  "time_periods": [],
  "ranks": [],
  "max_players_per_period": 20,
  "paipu_limit": 9999,
  "output_filename": "manual_paipu.txt",
  "headless_mode": true,
  "save_screenshots": false
}
```
**Option C: Date Room Mode ( For Date Range Bulk crawling)**
```json
{
  "crawler_mode": "date_room",
  "start_date": "2019-08-20",
  "end_date": "2019-08-23", 
  "target_room": "Jade",
  "output_filename": "date_room_list.txt",
  "headless_mode": true
}
```

**Configuration Parameters:**

| Parameter | Description | Options | Default |
|-----------|-------------|---------|---------|
| `crawler_mode` | **Crawler mode** | `"auto"`, `"manual"` | `"auto"` |
| `manual_player_urls` | **Manual player URLs** (for manual mode) | Array of player URLs | `[]` |
| `time_periods` | Time periods to crawl (for auto mode) | `"4w"`, `"1w"`, `"3d"`, `"1d"` | `["4w", "1w", "3d"]` |
| `ranks` | Rank tiers to target (for auto mode) | `"Throne"`, `"Jade"`, `"Gold"`, `"Throne East"`, `"Jade East"`, `"Gold East"`, `"All"` | `["Gold"]` |
| `max_players_per_period` | Players per time period | 1-50 | `20` |
| `paipu_limit` | Game logs per player | Any positive integer | `9999` |
| `output_filename` | Output file name | Any filename | `"tonpuulist.txt"` |
| `headless_mode` | Run browser in background | `true`, `false` | `true` |
| `save_screenshots` | Save verification screenshots | `true`, `false` | `true` |

**Common Configuration Examples:**

<details>
<summary>📋 Click to expand configuration examples</summary>

**Quick Test Configuration (Auto Mode):**
```json
{
  "crawler_mode": "auto",
  "time_periods": ["3d"],
  "ranks": ["Gold"],
  "max_players_per_period": 5,
  "paipu_limit": 100,
  "output_filename": "test_paipu.txt",
  "headless_mode": false,
  "save_screenshots": true
}
```

**Throne-Only Configuration (Auto Mode):**
```json
{
  "crawler_mode": "auto",
  "time_periods": ["1w", "3d"],
  "ranks": ["Throne"],
  "max_players_per_period": 15,
  "paipu_limit": 9999,
  "output_filename": "throne_paipu.txt",
  "headless_mode": true,
  "save_screenshots": false
}
```

**Complete Dataset Collection (Auto Mode):**
```json
{
  "crawler_mode": "auto",
  "time_periods": ["4w", "1w", "3d", "1d"],
  "ranks": ["All"],
  "max_players_per_period": 30,
  "paipu_limit": 9999,
  "output_filename": "complete_dataset.txt",
  "headless_mode": true,
  "save_screenshots": true
}
```

**Manual Player Selection (Manual Mode - Legacy Compatible):**
```json
{
  "crawler_mode": "manual",
  "manual_player_urls": [
    "https://amae-koromo.sapk.ch/player/123456789/12",
    "https://amae-koromo.sapk.ch/player/987654321/12",
    "https://amae-koromo.sapk.ch/player/555666777/12"
  ],
  "paipu_limit": 9999,
  "output_filename": "manual_selection.txt",
  "headless_mode": true,
  "save_screenshots": false
}
```

**East Room Focused (Auto Mode):**
```json
{
  "crawler_mode": "auto",
  "time_periods": ["1w"],
  "ranks": ["Throne East", "Jade East", "Gold East"],
  "max_players_per_period": 20,
  "paipu_limit": 9999,
  "output_filename": "east_paipu.txt",
  "headless_mode": true,
  "save_screenshots": false
}
```

</details>

#### **2.2 Set Mahjong Soul Credentials**
**File Path:** `config.env`
```env
# 雀魂認證設定
ms_username=your_email@example.com
ms_password=your_password

# 思考時間收集設定（可選）
# 設為 true 啟用，false 停用（默認：true）
# 啟用後會在 mjai 格式中添加 think_ms 字段，記錄玩家每個動作的思考時間（毫秒）
COLLECT_TIMING=true
```

**Configuration Parameters:**
- `ms_username`: Your Mahjong Soul account email
- `ms_password`: Your Mahjong Soul account password
- `COLLECT_TIMING`: Enable/disable thinking time collection (default: `true`)
  - `true`: Inject `think_ms` field into MJAI format with millisecond-precision thinking time
  - `false`: Standard MJAI format without thinking time data

Note: You need a CN server account with username/password login support.

### **Step 3: Collect Game IDs**

Navigate to the paipu_project directory and run:
```bash
cd paipu_project
scrapy crawl paipu_spider
```

The crawler will automatically detect your configuration mode:

**🚀 Auto Mode Output:**
```
🚀 使用自動化配置模式...
配置摘要:
  時間段: 四週, 一週, 三天
  段位: 金
  每個時間段最多玩家數: 20
```
- ✅ Automatically visit [MajSoul Stats Rankings](https://amae-koromo.sapk.ch/ranking/delta)
- ⚙️ Apply your configuration settings (time periods, ranks)
- 📊 Collect from Positive ranking leaderboards
- 💾 Save game IDs to your configured output file
- 📸 Optionally save verification screenshots

**🔧 Manual Mode Output:**
```
🔧 使用 Manual 模式（Legacy相容）...
從配置檔案中讀取 3 個手動設定的玩家URLs
已載入 3 個有效的玩家URLs
```
- ✅ Use your manually specified player URLs
- 🎯 Collect game logs from specific players
- 💾 Save game IDs to your configured output file

**Output:** Game IDs saved to `tonpuulist.txt` (or your configured filename)

Example output in `tonpuulist.txt`:
```
241103-057ea444-a219-4202-930e-2d2472f4d6e600
241104-12345678-abcd-efgh-ijkl-mnopqrstuvwx00
```

### **Step 4: Process Game Logs**
1. Move `tonpuulist.txt` to the root directory
2. Run **`toumajsoul.py`**

Game logs will be saved in the `mahjong_logs` directory with the following structure:
```
mahjong_logs/
├── mjai/           # MJAI format (with think_ms if enabled)
│   └── *.json.gz
└── tenhou/         # Tenhou.net/6 format
    └── *.json
```

#### **⏱️ Thinking Time Feature**

When `COLLECT_TIMING=true` (default), the MJAI format will include `think_ms` field:

**Standard MJAI output:**
```json
{"type": "dahai", "actor": 0, "pai": "W", "tsumogiri": false}
```

**With thinking time enabled:**
```json
{"type": "dahai", "actor": 0, "pai": "W", "think_ms": 2864, "tsumogiri": false}
```

**Thinking Time Data:**
- `think_ms`: Milliseconds from receiving tile to making action
- Calculated from Mahjong Soul's `passed` timestamp (real game time)
- Includes all player actions: discard, chi, pon, kan, riichi
- Typical values:
  - Quick discard (tsumogiri): 1000-3000 ms
  - Thoughtful discard: 2000-15000 ms  
  - Calling tiles (chi/pon): 500-5000 ms

**Analysis Example:**
```python
import json, gzip

with gzip.open('mahjong_logs/mjai/xxx.json.gz', 'rt') as f:
    for line in f:
        event = json.loads(line)
        if 'think_ms' in event:
            print(f"Player {event['actor']}: {event['think_ms']}ms")
```

### **Step 5: Validate Logs**
```bash
validate_logs.exe tonpuulog
```

## 📁 Project Structure
```
MajsoulPaipuConvert/
├── README.md
├── requirements.txt
├── config.env                       # Authentication & feature settings
├── toumajsoul.py                    # Game log downloader with timing support
├── crawler_config.json              # Crawler configuration
├── tonpuulist.txt                   # Generated game IDs
├── paipu_project/                   # Scrapy crawler project
│   ├── scrapy.cfg
│   └── paipu_project/
│       ├── crawler_config.json      # Alternative config location
│       └── spiders/
│           └── PaipuSpider.py       # Main crawler
├── mahjong_logs/                    # Downloaded game logs (new structure)
│   ├── mjai/                        # MJAI format with think_ms
│   │   └── *.json.gz
│   └── tenhou/                      # Tenhou.net/6 format
│       └── *.json
└── tensoul-py-ng/                   # Mahjong Soul log downloader
    └── tensoul/
```

## 🔍 Verification and Debugging

The crawler provides several verification methods:

1. **Screenshots** (if enabled): Verify rank selection and time period targeting
2. **Console Output**: Detailed logging of collection progress
3. **File Output**: Check collected game IDs in your output file

If you encounter issues:
- Set `headless_mode: false` to see browser actions
- Enable `save_screenshots: true` for visual verification
- Check ChromeDriver compatibility with your Chrome version

## 🚀 Quick Start Commands

```bash
# 1. Install dependencies
pip install -r requirements.txt
pip install scrapy selenium

# 2. Configure settings
#    - Edit crawler_config.json (choose "auto" or "manual" mode)
#    - Edit config.env (set credentials and COLLECT_TIMING option)

# 3. Collect game IDs (unified command for both modes)
cd paipu_project
scrapy crawl paipu_spider

# 4. Download game logs (with thinking time collection)
cd ..
python toumajsoul.py

# 5. Validate logs
validate_logs.exe mahjong_logs/mjai
```

**Thinking Time Collection Control:**
```bash
# Enable thinking time collection (default)
COLLECT_TIMING=true

# Disable thinking time collection
COLLECT_TIMING=false
```

## 🔄 Switching Between Modes

**To switch from Auto to Manual mode:**
```json
{
  "crawler_mode": "manual",  // Changed from "auto"
  "manual_player_urls": [    // Add your specific player URLs
    "https://amae-koromo.sapk.ch/player/123456789/12",
    "https://amae-koromo.sapk.ch/player/987654321/12"
  ],
  "time_periods": [],        // Leave empty for manual mode
  "ranks": []                // Leave empty for manual mode
}
```

**To switch from Manual to Auto mode:**
```json
{
  "crawler_mode": "auto",    // Changed from "manual"
  "manual_player_urls": [],  // Leave empty for auto mode
  "time_periods": ["1w"],    // Set your desired time periods
  "ranks": ["Gold"]          // Set your desired ranks
}
```

No code changes required - just edit the configuration file and run the same command!

## ⚠️ Troubleshooting

**Common Issues:**
- **ChromeDriver error**: Ensure ChromeDriver version matches Chrome browser
- **Empty results**: Check network connection and verify configuration mode/settings
- **Process hanging**: For auto mode, verify network access to rankings site; for manual mode, check player URLs format
- **Rate limiting**: Adjust `max_players_per_period` if experiencing timeouts
- **Configuration errors**: The program will validate and show specific error messages for invalid configurations

**Thinking Time Issues:**
- **No think_ms in output**: Verify `COLLECT_TIMING=true` in `config.env`
- **think_ms values seem wrong**: 
  - Values are calculated from Mahjong Soul's server timestamps (`passed` field)
  - Include small network latency (usually < 100ms)
  - Opening moves may show time from deal completion to first action
- **Missing think_ms for some actions**: Only player actions (dahai, chi, pon, kan, riichi) include thinking time
- **Abnormally long think_ms**: May indicate AFK or disconnection (values > 120000ms = 2 minutes)

## License
This project incorporates code from:
- [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer) under the Apache-2.0 license
- [tensoul-py-ng](https://github.com/unStatiK/tensoul-py-ng) for Mahjong Soul log downloading

**Important**: This project uses third-party libraries and tools. Please ensure compliance with their respective licenses:
- mjai-reviewer: Apache-2.0 License (see [LICENSE](https://github.com/Equim-chan/mjai-reviewer/blob/main/LICENSE))
- tensoul-py-ng: MIT License (see [LICENSE](https://github.com/unStatiK/tensoul-py-ng/blob/master/LICENSE))

## Acknowledgments
- [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer) - Game log analysis tool
- [tensoul-py-ng](https://github.com/unStatiK/tensoul-py-ng) - Mahjong Soul log downloading in tenhou.net/6 format
- [MajSoul Stats](https://amae-koromo.sapk.ch/) - Data source
- [Scrapy](https://scrapy.org/) - Web scraping framework
- [Selenium](https://selenium.dev/) - Browser automation
- [Mortal](https://github.com/Equim-chan/Mortal) - AI Engine

## Contributing
Issues and pull requests are welcome. Please ensure proper attribution and licensing compliance when contributing.

---
<div align="center">
Created with ❤️ for the Mahjong community

</div>

