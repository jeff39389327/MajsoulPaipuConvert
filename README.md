# <div align="center">**MajsoulPaipuConvert**</div>

## Integration Project
**Convert Mahjong Soul game logs to MJAI format using mjai-reviewer and tensoul**

This tool downloads game logs from MajSoul Stats and converts them to the MJAI format.

## ⚠️ Important Notes
- This tool collects data from third-party websites and games
- Only supports 4-player mahjong (三麻/3-player requires modifications to mjai-reviewer)
- Currently only compatible with CN server
- Uses mjai-reviewer (Apache-2.0 License)

> If you find any missing attributions or licensing issues, please submit an ISSUE. Your feedback helps us maintain proper attribution and licensing compliance.

## Prerequisites
Before installation, ensure you have:
- Python 3.8+
- pip (Python package manager)
- Git

## Installation and Setup

### **Step 1: Install Dependencies**
```bash
pip install -r requirements.txt
```

**Required External Tool:**
- Install [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer)
  - Ensure it's added to your system PATH or properly referenced in your configuration

### **Step 2: Configuration**

#### **2.1 Configure Web Scraping**
Check the web elements at [MajSoul Stats](https://amae-koromo.sapk.ch/)

**File Path:** `paipu_project/paipu_project/spiders/PaipuSpider.py`
```python
# Web element selector
"a.MuiTypography-root.MuiTypography-inherit.MuiLink-root.MuiLink-underlineHover.css-17xi075"

# For specific players
player_urls = [
    # Add player URLs here
]
```

Example of web element:
```html
<a href="https://game.maj-soul.com/1/?paipu=241114-189aa3d7--2e3e83a76230_a7832143000" 
   class="MuiTypography-root MuiTypography-inherit MuiLink-root MuiLink-underlineHover css-17xi075" 
   title="查看牌谱" 
   target="_blank" 
   rel="noopener noreferrer">
   0r0j50 [13000]
</a>
```

#### **2.2 Set Mahjong Soul Credentials**
**File Path:** `toumajsoul.py`
```python
username = "example@example.com"
password = "12345678"
```

### **Step 3: Collect Game IDs**
Navigate to the paipu_project directory and run:
```bash
scrapy crawl paipu_spider
```
> Note: This uses headless mode and multi-threading to download game IDs and save them to `tonpuulist.txt`

Example output in `tonpuulist.txt`:
```
241103-057ea444-a219-4202-930e-2d2472f4d6e600
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

## License
This project incorporates code from mjai-reviewer under the Apache-2.0 license.

## Acknowledgments
- [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer) - Game log analysis tool
- [MajSoul Stats](https://amae-koromo.sapk.ch/) - Data source

## Contributing
Issues and pull requests are welcome. Please ensure proper attribution and licensing compliance when contributing.

---
<div align="center">
Created with ❤️ for the Mahjong community
</div>