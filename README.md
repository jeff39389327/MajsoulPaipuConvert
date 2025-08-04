# <div align="center">**MajsoulPaipuConvert**</div>

## Integration Project
**Convert Mahjong Soul game logs to MJAI format using mjai-reviewer and tensoul**

This tool downloads game logs from MajSoul Stats and converts them to the MJAI format with a configurable crawler system for flexible data collection.

## ⚠️ Important Notes
- This tool collects data from third-party websites and games
- Only supports 4-player mahjong (三麻/3-player requires modifications to mjai-reviewer)
- Currently only compatible with CN server
- Uses mjai-reviewer (Apache-2.0 License)

> If you find any missing attributions or licensing issues, please submit an ISSUE. Your feedback helps us maintain proper attribution and licensing compliance.

## ✨ New Features
- 🎯 **Configurable Crawler**: Flexible targeting by time periods and ranks
- 🚀 **Automated Collection**: Auto-collect from ranking leaderboards
- 📊 **Multi-Rank Support**: Throne/Jade/Gold + East variants
- ⏰ **Multi-Period**: 4w/1w/3d/1d rankings
- 🔧 **JSON Configuration**: Easy setup through config files

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

#### **2.1 Configure Crawler Settings (New!)**
Create or modify `crawler_config.json` in the `paipu_project/paipu_project/` directory:

```json
{
  "time_periods": ["4w", "1w", "3d"],
  "ranks": ["Gold"],
  "max_players_per_period": 20,
  "paipu_limit": 9999,
  "output_filename": "tonpuulist.txt",
  "headless_mode": true,
  "save_screenshots": true
}
```

**Configuration Parameters:**

| Parameter | Description | Options | Default |
|-----------|-------------|---------|---------|
| `time_periods` | Time periods to crawl | `"4w"`, `"1w"`, `"3d"`, `"1d"` | `["4w", "1w", "3d"]` |
| `ranks` | Rank tiers to target | `"Throne"`, `"Jade"`, `"Gold"`, `"Throne East"`, `"Jade East"`, `"Gold East"`, `"All"` | `["Gold"]` |
| `max_players_per_period` | Players per time period | 1-50 | `20` |
| `paipu_limit` | Game logs per player | Any positive integer | `9999` |
| `output_filename` | Output file name | Any filename | `"tonpuulist.txt"` |
| `headless_mode` | Run browser in background | `true`, `false` | `true` |
| `save_screenshots` | Save verification screenshots | `true`, `false` | `true` |

**Common Configuration Examples:**

<details>
<summary>📋 Click to expand configuration examples</summary>

**Quick Test Configuration:**
```json
{
  "time_periods": ["3d"],
  "ranks": ["Gold"],
  "max_players_per_period": 5,
  "paipu_limit": 100,
  "output_filename": "test_paipu.txt",
  "headless_mode": false,
  "save_screenshots": true
}
```

**Throne-Only Configuration:**
```json
{
  "time_periods": ["1w", "3d"],
  "ranks": ["Throne"],
  "max_players_per_period": 15,
  "paipu_limit": 9999,
  "output_filename": "throne_paipu.txt",
  "headless_mode": true,
  "save_screenshots": false
}
```

**Complete Dataset Collection:**
```json
{
  "time_periods": ["4w", "1w", "3d", "1d"],
  "ranks": ["All"],
  "max_players_per_period": 30,
  "paipu_limit": 9999,
  "output_filename": "complete_dataset.txt",
  "headless_mode": true,
  "save_screenshots": true
}
```

**East Room Focused:**
```json
{
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

#### **2.2 Legacy Manual Configuration (Optional)**
For manual player targeting, you can still modify:
**File Path:** `paipu_project/paipu_project/spiders/PaipuSpider.py`

```python
# Manual player URLs (if not using auto-crawler)
player_urls = [
    # Add specific player URLs here
]
```

#### **2.3 Set Mahjong Soul Credentials**
**File Path:** `toumajsoul.py`
```python
username = "example@example.com"
password = "12345678"
```

### **Step 3: Collect Game IDs**

#### **Option A: Automated Crawler (Recommended)**
Navigate to the paipu_project directory and run:
```bash
cd paipu_project
scrapy crawl paipu_spider
```

The crawler will:
- ✅ Automatically visit [MajSoul Stats Rankings](https://amae-koromo.sapk.ch/ranking/delta)
- ⚙️ Apply your configuration settings (time periods, ranks)
- 📊 Collect from Positive ranking leaderboards
- 💾 Save game IDs to your configured output file
- 📸 Optionally save verification screenshots

**Output:** Game IDs saved to `tonpuulist.txt` (or your configured filename)

#### **Option B: Manual Configuration (Legacy)**
Manually configure specific players in the spider code and run the same command.

Example output in `tonpuulist.txt`:
```
241103-057ea444-a219-4202-930e-2d2472f4d6e600
241104-12345678-abcd-efgh-ijkl-mnopqrstuvwx00
```

### **Step 4: Process Game Logs**
1. Move `tonpuulist.txt` to the root directory
2. Run **`toumajsoul.py`**

Game logs will be saved in the `tonpuulog` directory.
Example output: `241103-057ea444-a219-4202-930e-2d2472f4d6e600.json.gz`

### **Step 5: Validate Logs**
```bash
validate_logs.exe tonpuulog
```

## 📁 Project Structure
```
MajsoulPaipuConvert/
├── README.md
├── requirements.txt
├── toumajsoul.py                    # Game log downloader
├── crawler_config.json              # Crawler configuration
├── tonpuulist.txt                   # Generated game IDs
├── paipu_project/                   # Scrapy crawler project
│   ├── scrapy.cfg
│   └── paipu_project/
│       ├── crawler_config.json      # Alternative config location
│       └── spiders/
│           └── PaipuSpider.py       # Main crawler
└── tonpuulog/                       # Downloaded game logs
    └── *.json.gz                    # Compressed game files
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

# 2. Configure crawler (edit crawler_config.json)
# 3. Collect game IDs
cd paipu_project
scrapy crawl paipu_spider

# 4. Download game logs
cd ..
python toumajsoul.py

# 5. Validate logs
validate_logs.exe tonpuulog
```

## ⚠️ Troubleshooting

**Common Issues:**
- **ChromeDriver error**: Ensure ChromeDriver version matches Chrome browser
- **Empty results**: Check network connection and configuration settings
- **Process hanging**: Verify credentials in `toumajsoul.py`
- **Rate limiting**: Adjust `max_players_per_period` if experiencing timeouts

## License
This project incorporates code from mjai-reviewer under the Apache-2.0 license.

## Acknowledgments
- [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer) - Game log analysis tool
- [MajSoul Stats](https://amae-koromo.sapk.ch/) - Data source
- [Scrapy](https://scrapy.org/) - Web scraping framework
- [Selenium](https://selenium.dev/) - Browser automation

## Contributing
Issues and pull requests are welcome. Please ensure proper attribution and licensing compliance when contributing.

---
<div align="center">
Created with ❤️ for the Mahjong community
</div>