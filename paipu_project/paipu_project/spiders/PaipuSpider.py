import scrapy
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import re
import json
from dataclasses import dataclass
from typing import List, Dict
from datetime import datetime, timedelta
import subprocess
import sys
import os
import tempfile
import signal
import random
import traceback
import logging

# selenium 的 remote_connection logger 在 DEBUG 等級會把「每一個」WebDriver 指令（含整段
# getAttribute 注入 JS，單筆數 KB）印出來。scrapy 預設 LOG_LEVEL=DEBUG，會讓它噴出 MB 級
# 洪流，經由 GUI 逐行轉送到 renderer 並無上限累加進 DOM，拖垮前端主執行緒、導致「取消」鈕
# 點不動、進度/狀態也更新不了。將 selenium / urllib3 logger 提到 WARNING 以止血（不影響
# 我們自己的 print 進度輸出）。
for _noisy_logger in ("selenium", "selenium.webdriver.remote.remote_connection", "urllib3"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

# date_room_api 模式：純 amae-koromo API 取牌譜 UUID（無 Selenium）。scrapy/frozen 都以
# 套件 paipu_project.spiders 載入本檔，故相對匯入為主；直接執行 PaipuSpider.py（CWD=spiders）
# 時退回絕對匯入。
try:
    from .akoromo_api import collect_room_paipus
except ImportError:  # pragma: no cover - 直接執行 / CWD=spiders 後備
    from akoromo_api import collect_room_paipus

@dataclass
class CrawlerConfig:
    """Crawler configuration class"""
    # Crawler mode selection: "auto", "manual", or "date_room"
    crawler_mode: str = "auto"

    # Manual mode: List of player URLs (used when crawler_mode = "manual")
    manual_player_urls: List[str] = None

    # Auto mode: Time period settings (options: "4w", "1w", "3d", "1d")
    time_periods: List[str] = None

    # Auto mode: Rank settings (options: "Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East", "All")
    ranks: List[str] = None

    # Maximum number of players to fetch per time period
    max_players_per_period: int = 20

    # Paipu quantity limit parameter
    paipu_limit: int = 9999

    # date_room mode: Date range and target room
    start_date: str = None  # Format: "2019-08-20"
    end_date: str = None    # Format: "2019-08-23"
    target_room: str = None # Options: "Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East"

    # Output filename
    output_filename: str = "tonpuulist.txt"

    # Enable headless mode
    headless_mode: bool = True

    # Fast mode (for large-scale collection, may miss 5-10% data)
    fast_mode: bool = False

    # Save verification screenshots
    save_screenshots: bool = True

    @classmethod
    def from_json(cls, json_path: str):
        """Load configuration from JSON file"""
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return cls(**data)
        except FileNotFoundError:
            print(f"Config file {json_path} not found, using default configuration")
            return cls.get_default_config()

    @classmethod
    def get_default_config(cls):
        """Get default configuration"""
        return cls(
            crawler_mode="auto",
            manual_player_urls=[],
            time_periods=["4w", "1w", "3d"],
            ranks=["Gold"],
            max_players_per_period=20,
            paipu_limit=9999,
            output_filename="tonpuulist.txt",
            headless_mode=True,
            save_screenshots=True,
            start_date=None,
            end_date=None,
            target_room=None
        )

    def save_to_json(self, json_path: str):
        """Save configuration to JSON file"""
        # Handle None values, convert to empty lists for JSON serialization
        config_dict = self.__dict__.copy()
        if config_dict.get('manual_player_urls') is None:
            config_dict['manual_player_urls'] = []
        if config_dict.get('time_periods') is None:
            config_dict['time_periods'] = []
        if config_dict.get('ranks') is None:
            config_dict['ranks'] = []

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, ensure_ascii=False, indent=2)

    def validate(self):
        """Validate configuration validity"""
        valid_modes = ["auto", "manual", "date_room", "date_room_player", "date_room_api"]
        valid_periods = ["4w", "1w", "3d", "1d"]
        valid_ranks = ["Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East", "All"]
        valid_rooms = ["Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East"]

        # Validate crawler mode
        if self.crawler_mode not in valid_modes:
            raise ValueError(f"Invalid crawler mode: {self.crawler_mode}. Valid options: {valid_modes}")

        # Validate corresponding parameters based on mode
        if self.crawler_mode == "manual":
            if not self.manual_player_urls or len(self.manual_player_urls) == 0:
                raise ValueError("Manual mode requires manual_player_urls")
            print(f"Manual mode configuration validated - {len(self.manual_player_urls)} player URLs configured")

        elif self.crawler_mode == "auto":
            if not self.time_periods or len(self.time_periods) == 0:
                raise ValueError("Auto mode requires time_periods")
            if not self.ranks or len(self.ranks) == 0:
                raise ValueError("Auto mode requires ranks")

            # Validate time periods
            for period in self.time_periods:
                if period not in valid_periods:
                    raise ValueError(f"Invalid time period: {period}. Valid options: {valid_periods}")

            # Validate ranks
            for rank in self.ranks:
                if rank not in valid_ranks:
                    raise ValueError(f"Invalid rank: {rank}. Valid options: {valid_ranks}")

            print(f"Auto mode configuration validated")

        elif self.crawler_mode in ("date_room", "date_room_player", "date_room_api"):
            # Validate date format and required parameters
            if not self.start_date or not self.end_date:
                raise ValueError(f"{self.crawler_mode} mode requires start_date and end_date")
            if not self.target_room:
                raise ValueError(f"{self.crawler_mode} mode requires target_room")

            # Validate date format
            try:
                start = datetime.strptime(self.start_date, "%Y-%m-%d")
                end = datetime.strptime(self.end_date, "%Y-%m-%d")
                if start > end:
                    raise ValueError("start_date cannot be later than end_date")
            except ValueError as e:
                raise ValueError(f"Date format error (should be YYYY-MM-DD): {e}")

            # Validate room
            if self.target_room not in valid_rooms:
                raise ValueError(f"Invalid room: {self.target_room}. Valid options: {valid_rooms}")

            print(f"{self.crawler_mode} mode configuration validated")
            print(f"  Date range: {self.start_date} to {self.end_date}")
            print(f"  Target room: {self.target_room}")

        print("Overall configuration validated")

def apply_stealth_js(driver):
    """Apply anti-detection JavaScript to WebDriver"""
    try:
        # Enhanced anti-detection: Modify more browser features
        driver.execute_cdp_cmd('Network.setUserAgentOverride', {
            "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

        # Hide webdriver features
        driver.execute_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Modify plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Modify languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-TW', 'zh', 'en-US', 'en']
            });

            // Modify platform
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32'
            });

            // Modify hardwareConcurrency
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 8
            });

            // Modify deviceMemory
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8
            });

            // Modify Chrome object
            window.chrome = {
                runtime: {}
            };

            // Modify permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)
        print("Anti-detection measures applied")
    except Exception as e:
        print(f"Error applying anti-detection measures: {e}")

def create_stealth_driver(headless_mode: bool, extra_args: List[str] = None):
    """Build a Chrome WebDriver with stability flags, log suppression and anti-detection applied.

    Returns (driver, remote_port). extra_args are appended verbatim (e.g. window size).
    """
    chrome_options = Options()

    if headless_mode:
        chrome_options.add_argument("--headless=new")

    # Core fix: Do not use user-data-dir, use random port isolation
    remote_port = random.randint(9222, 65535)
    chrome_options.add_argument(f"--remote-debugging-port={remote_port}")

    # Core stability parameters
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-software-rasterizer")

    # Tolerate TLS-intercepting egress proxies (sandbox / CI environments). Without this,
    # Chrome shows a "Your connection is not private" interstitial and no page content loads.
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.set_capability("acceptInsecureCerts", True)

    # Disable various features that may cause conflicts
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--disable-popup-blocking")

    for arg in (extra_args or []):
        chrome_options.add_argument(arg)

    # Prevent detection as automation tool
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # Log settings - strongly suppress all logs
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--silent")
    chrome_options.add_argument("--disable-logging")

    # Set environment variables to suppress Chrome logs
    os.environ['WDM_LOG_LEVEL'] = '0'
    os.environ['WDM_PRINT_FIRST_LINE'] = 'False'

    driver = webdriver.Chrome(options=chrome_options)
    apply_stealth_js(driver)  # Apply anti-detection
    return driver, remote_port

def get_rank_display_name(rank: str) -> Dict[str, str]:
    """Get rank display name mapping"""
    rank_mapping = {
        "Throne": "王座",
        "Jade": "玉",
        "Gold": "金",
        "Throne East": "王东",
        "Jade East": "玉东",
        "Gold East": "金东",
        "All": "全部"
    }
    return rank_mapping.get(rank, rank)

def get_period_display_name(period: str) -> str:
    """Get time period display name"""
    period_mapping = {
        "4w": "四週",
        "1w": "一週",
        "3d": "三天",
        "1d": "一天"
    }
    return period_mapping.get(period, period)

def execute_date_room_extractor_py(target_date: str, target_room: str, headless_mode: bool = True, fast_mode: bool = False, output_file=None, player_mode: bool = False) -> List[str]:
    """
    Execute date_room_extractor.py and get the output paipu ID list

    Args:
        target_date: Target date (format: "2019-08-23")
        target_room: Target room (e.g.: "Throne", "Jade", "Gold", etc.)
        headless_mode: Whether to use headless mode
        fast_mode: Whether to use fast mode (faster but may miss 5-10% data)
        player_mode: True 表示啟用逐玩家頁面模式（date_room_player）

    Returns:
        List of paipu IDs
    """
    # Create temporary modified version of date_room_extractor.py
    temp_script = """
import sys
sys.path.insert(0, '.')
from date_room_extractor import OptimizedPaipuExtractor, convert_ranks_to_english

def main():
    # Parameter settings
    target_date = "{target_date}"
    target_ranks = ["{target_room}"]
    max_paipus = 99999
    headless_mode = {headless_mode}
    fast_mode = {fast_mode}

    target_ranks = convert_ranks_to_english(target_ranks)

    extractor = OptimizedPaipuExtractor(headless=headless_mode, fast_mode=fast_mode, player_mode={player_mode})

    try:
        results = extractor.extract_from_rooms(
            target_date=target_date,
            target_ranks=target_ranks,
            max_paipus=max_paipus
        )

        # Output only paipu IDs, one per line
        for paipu in results:
            print(paipu)

    finally:
        extractor.close()

if __name__ == "__main__":
    main()
""".format(
        target_date=target_date,
        target_room=target_room,
        headless_mode=str(headless_mode),
        fast_mode=str(fast_mode),
        player_mode=str(player_mode)
    )

    # 凍結 (PyInstaller) 模式下，sys.executable 是 backend.exe 而非 python，且沒有
    # 外部 python 可跑臨時 .py。改為自我再入 `backend.exe __extractor <args>`，由
    # gui.backend.cli 執行同一個 OptimizedPaipuExtractor 並把 UUID 印到 stdout。
    frozen = getattr(sys, 'frozen', False)
    temp_file_path = None
    if frozen:
        cmd = [
            sys.executable, '__extractor',
            '--target-date', target_date,
            '--target-room', target_room,
            '--headless', str(headless_mode),
            '--fast', str(fast_mode),
            '--player-mode', str(player_mode),
        ]
    else:
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as temp_file:
            temp_file.write(temp_script)
            temp_file_path = temp_file.name
        cmd = [sys.executable, '-u', temp_file_path]  # -u for unbuffered output

    try:
        # Execute temporary script with real-time output
        # Use Popen to allow real-time output display
        # Set environment to force UTF-8 encoding
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr to stdout for unified output
            text=True,
            encoding='utf-8',
            errors='replace',  # Replace invalid characters with ?
            bufsize=1,  # Line buffered
            universal_newlines=True,
            env=env
        )

        # Collect paipu IDs while displaying real-time output
        paipu_ids = []
        for line in process.stdout:
            line = line.rstrip()
            if line:
                # 顯示 extractor 的原始輸出，方便除錯
                try:
                    print(f"  [extractor] {line}", flush=True)
                except UnicodeEncodeError:
                    print(f"  [extractor] {line.encode('utf-8', errors='replace').decode('utf-8')}", flush=True)

                # Check if this line is a paipu ID
                if re.match(r'^[0-9]{6}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', line.strip()):
                    paipu_id = line.strip()
                    paipu_ids.append(paipu_id)

                    # 即時寫入到檔案
                    if output_file:
                        output_file.write(paipu_id + "\n")
                        output_file.flush()
                        print(f"[Spider] 即時寫入牌譜: {paipu_id}", flush=True)

        # Wait for process to complete
        return_code = process.wait()

        if return_code != 0:
            mode_suffix = " (player mode)" if player_mode else ""
            print(f"Error: date_room_extractor.py{mode_suffix} exited with code {return_code}")
            return []

        return paipu_ids

    finally:
        # Delete temporary file (dev mode only; frozen mode writes no temp script)
        if temp_file_path:
            try:
                os.unlink(temp_file_path)
            except Exception:
                pass


def collect_paipus_by_date_room(config: CrawlerConfig, output_file=None, player_mode: bool = False) -> List[str]:
    """Collect paipus using date_room mode (player_mode=True 逐玩家收集所有玩家頁面牌譜)"""
    mode_label = "date_room_player" if player_mode else "date_room"
    all_paipus: List[str] = []
    seen = set()
    interrupted = False
    progress_file = "crawler_progress.json"

    # Setup interrupt handler
    def signal_handler(sig, frame):  # noqa: ARG001 - callback signature fixed by signal
        nonlocal interrupted
        print(f"\n\nInterrupt signal received (Ctrl+C)")
        print(f"Currently collected {len(all_paipus)} paipus")
        print(f"Saving data...")
        interrupted = True

    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Parse date range
        start_date = datetime.strptime(config.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(config.end_date, "%Y-%m-%d")

        # Check for existing progress (player mode supports resume)
        if player_mode and os.path.exists(progress_file):
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    progress = json.load(f)

                if progress.get('mode') == 'date_room_player' and \
                   progress.get('target_room') == config.target_room and \
                   progress.get('end_date') == config.end_date:

                    last_date_str = progress.get('last_processed_date')
                    if last_date_str:
                        last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
                        if start_date <= last_date < end_date:
                            print(f"\nFound progress file. Resuming from {last_date_str}...")
                            start_date = last_date + timedelta(days=1)
                            print(f"New start date: {start_date.strftime('%Y-%m-%d')}")
            except Exception as e:
                print(f"Error reading progress file: {e}")

        # Calculate total days
        total_days = (end_date - start_date).days + 1
        print(f"\n{'='*70}")
        print(f"Starting {mode_label} mode collection")
        print(f"{'='*70}")
        print(f"Date range: {start_date.strftime('%Y-%m-%d')} to {config.end_date} (total {total_days} days)")
        print(f"Target room: {config.target_room}")
        print(f"Headless mode: {'Enabled' if config.headless_mode else 'Disabled'}")
        print(f"Fast mode: {' Enabled' if config.fast_mode else 'Disabled (complete)'}")
        print(f"Output file: {config.output_filename}")
        print(f"{'='*70}\n")

        # Process each day
        current_date = start_date
        day_count = 0
        start_time = time.time()

        while current_date <= end_date and not interrupted:
            day_count += 1
            date_str = current_date.strftime("%Y-%m-%d")
            day_start = time.time()

            print(f"\n{'-'*70}")
            print(f"[{day_count}/{total_days}] Processing date: {date_str}")
            print(f"{'-'*70}")

            # Execute date_room_extractor.py to get paipus for this day
            try:
                day_results = execute_date_room_extractor_py(
                    target_date=date_str,
                    target_room=config.target_room,
                    headless_mode=config.headless_mode,
                    fast_mode=config.fast_mode,
                    output_file=output_file,  # 傳遞 output_file 以實現即時寫入
                    player_mode=player_mode,
                )
            except Exception as e:
                print(f"Error processing {date_str}: {e}")
                traceback.print_exc()
                day_results = []

            # 檢查是否被中斷
            if interrupted:
                print(f"\nCollection interrupted by user")
                break

            # Add to total list (date_room_extractor.py already deduplicates, but ensure cross-date deduplication here)
            # 注意：牌譜已在 execute_date_room_extractor_py 中即時寫入，這裡只做去重統計
            new_paipus = 0
            for paipu in day_results:
                if paipu not in seen:
                    seen.add(paipu)
                    all_paipus.append(paipu)
                    new_paipus += 1

            # Save progress (player mode supports resume)
            if player_mode:
                try:
                    progress_data = {
                        'mode': 'date_room_player',
                        'target_room': config.target_room,
                        'start_date': config.start_date,
                        'end_date': config.end_date,
                        'last_processed_date': date_str,
                        'timestamp': time.time()
                    }
                    with open(progress_file, 'w', encoding='utf-8') as f:
                        json.dump(progress_data, f, ensure_ascii=False, indent=2)
                    print(f"Progress saved: {date_str}")
                except Exception as e:
                    print(f"Error saving progress: {e}")

            day_elapsed = time.time() - day_start
            total_elapsed = time.time() - start_time

            print(f"\n{date_str} completed:")
            print(f"  Collected today: {len(day_results)} paipus")
            print(f"  New today: {new_paipus} (after deduplication)")
            print(f"  Cumulative total: {len(all_paipus)} unique paipus")
            print(f"  Time today: {day_elapsed:.1f} seconds")
            print(f"  Total time: {total_elapsed/60:.1f} minutes")

            # Move to next day
            current_date += timedelta(days=1)

            # If not the last day, show ETA
            if current_date <= end_date:
                remaining_days = (end_date - current_date).days + 1
                avg_time_per_day = total_elapsed / day_count
                estimated_remaining = avg_time_per_day * remaining_days / 60
                print(f"  Estimated remaining time: {estimated_remaining:.1f} minutes ({remaining_days} days)")


        total_time = time.time() - start_time
        print(f"\n{'='*70}")
        if interrupted:
            print(f"{mode_label} mode collection interrupted by user!")
        else:
            print(f"{mode_label} mode collection completed!")
            # Clean up progress file on completion (player mode only)
            if player_mode and os.path.exists(progress_file):
                try:
                    os.remove(progress_file)
                    print("Progress file removed (task completed)")
                except Exception:
                    pass
        print(f"{'='*70}")
        print(f"Total collected: {len(all_paipus)} unique paipu IDs")
        print(f"Days processed: {day_count} days")
        print(f"Total time: {total_time/60:.1f} minutes ({total_time/3600:.2f} hours)")
        if len(all_paipus) > 0 and total_time > 0:
            print(f"Average speed: {len(all_paipus)/total_time*60:.1f} paipus/minute")
        print(f"{'='*70}\n")

    except Exception as e:
        print(f"\n{mode_label} mode execution error: {e}")
        traceback.print_exc()
        print(f"Collected {len(all_paipus)} paipus before error")

    return all_paipus


def find_rank_checkbox(driver, rank: str):
    """Locate a rank's (label, checkbox, label_text), trying the English then Chinese label.

    Returns (None, None, None) if neither label is present on the page.
    """
    for label_text in (rank, get_rank_display_name(rank)):
        try:
            rank_label = driver.find_element(
                By.XPATH,
                f"//span[contains(@class, 'MuiFormControlLabel-label') and text()='{label_text}']",
            )
            checkbox = rank_label.find_element(By.XPATH, "./preceding-sibling::span//input[@type='checkbox']")
            return rank_label, checkbox, label_text
        except Exception:
            continue
    return None, None, None

def setup_rank_selection(driver, target_ranks: List[str]):
    """Setup rank selection"""
    all_available_ranks = ["Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East"]

    try:
        print("Configuring rank selection...")

        # If "All" is selected, use the page's default state (all ranks already selected)
        if "All" in target_ranks:
            print("Selecting all ranks - using page default state, no clicking needed")
            print("Page default has all ranks selected, skipping rank selection operation")
            return

        # First deselect all ranks
        for rank in all_available_ranks:
            rank_label, checkbox, label_text = find_rank_checkbox(driver, rank)
            if checkbox is not None and checkbox.is_selected():
                print(f"Deselecting rank: {label_text}")
                driver.execute_script("arguments[0].click();", rank_label)

        # Select target ranks
        for rank in target_ranks:
            rank_label, checkbox, label_text = find_rank_checkbox(driver, rank)
            if checkbox is None:
                print(f"Unable to select rank {rank}")
                continue
            if not checkbox.is_selected():
                print(f"Selecting rank: {label_text}")
                driver.execute_script("arguments[0].click();", rank_label)
            else:
                print(f"Rank {label_text} already selected")

        # Wait for page update
        print("Rank selection configuration completed")

    except Exception as e:
        print(f"Error configuring rank selection: {e}")

def get_top_players_urls(config: CrawlerConfig):
    """Automatically crawl leaderboard player URLs based on configuration"""
    driver, remote_port = create_stealth_driver(
        config.headless_mode,
        ["--disable-infobars", "--window-size=1920,1080"],
    )
    print(f"Chrome instance started (debug port: {remote_port})")

    all_player_urls = []

    try:
        # Access ranking page
        driver.get("https://amae-koromo.sapk.ch/ranking/delta")

        # Wait for page load complete
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # 等待頁面實際內容載入
        print("等待排行榜頁面載入...")
        time.sleep(2)  # 給予額外時間讓動態內容載入

        # Build rank display string
        rank_display = ", ".join([get_rank_display_name(rank) for rank in config.ranks])
        period_display = ", ".join([get_period_display_name(period) for period in config.time_periods])

        print(f"Fetching leaderboard rankings")
        print(f"Target time periods: {period_display}")
        print(f"Target ranks: {rank_display}")

        # Setup rank selection
        setup_rank_selection(driver, config.ranks)

        # Save rank selection verification screenshot
        if config.save_screenshots:
            driver.save_screenshot("screenshot_rank_selection_verification.png")
            print("Saved rank selection verification screenshot: screenshot_rank_selection_verification.png")

        # Process each time period
        for period in config.time_periods:
            print(f"\n=== Starting to process time period: {get_period_display_name(period)} ({period}) ===")

            try:
                # Find and click corresponding time period radio button
                print(f"Finding radio button for time period {period}...")

                radio_button = driver.find_element(By.CSS_SELECTOR, f'input[type="radio"][value="{period}"]')
                print(f"Found radio button for {period}")

                # Click radio button
                driver.execute_script("arguments[0].click();", radio_button)
                print(f"Clicked {period} time period")

                # 切換時間段會觸發 React 重新抓取榜單，舊表會先被卸載 (玩家連結瞬間歸零)。
                # 先沉澱片刻讓舊內容消失，再由 extract_positive_ranking_players 等新榜單
                # 渲染完成；否則會在空表上抓取而收集到 0 筆。
                time.sleep(1.5)

                # Save verification screenshot
                if config.save_screenshots:
                    rank_suffix = "_".join(config.ranks).lower()
                    screenshot_filename = f"screenshot_{period}_positive_ranking_{rank_suffix}.png"
                    driver.save_screenshot(screenshot_filename)
                    print(f"Saved screenshot: {screenshot_filename}")

            except Exception as e:
                print(f"Error switching to time period {period}: {e}")
                continue

            # Get player links for this time period
            period_player_urls = extract_positive_ranking_players(driver, period, config)
            all_player_urls.extend(period_player_urls)

            print(f"Time period {period} obtained {len(period_player_urls)} player URLs")

        # Deduplication processing
        unique_player_urls = []
        seen_players = set()

        for url in all_player_urls:
            player_id_match = re.search(r'/player/(\d+)', url)
            if player_id_match:
                player_id = player_id_match.group(1)
                if player_id not in seen_players:
                    seen_players.add(player_id)
                    unique_player_urls.append(url)

        print(f"Obtained {len(unique_player_urls)} unique player URLs (/12 mode)")

        if config.save_screenshots:
            rank_suffix = "_".join(config.ranks).lower()
            print(f"\nVerification screenshots saved:")
            print(f"  - screenshot_rank_selection_verification.png (rank selection verification)")
            for period in config.time_periods:
                print(f"  - screenshot_{period}_positive_ranking_{rank_suffix}.png ({get_period_display_name(period)})")

        return unique_player_urls

    except Exception as e:
        print(f"Error fetching rankings: {e}")
        return []

    finally:
        driver.quit()
        print("Chrome instance closed")

def extract_positive_ranking_players(driver, period, config: CrawlerConfig):
    """Extract player links from the 'Positive ranking' column.

    delta 排行榜頁渲染三欄 MuiGrid（Negative / Positive / Stamina ranking），每欄是一個
    <h5> 標題後接一張玩家連結表。重點：切換時間段 radio 後 React 會卸載並重抓榜單，玩家
    連結會瞬間歸零（見過往「Method 3 found 0」即此故），故**必須先等連結重新渲染**再抓，
    否則讀到空表收集 0 筆。鎖定 Positive 欄的方式：用 <h5> 標題文字定位，取其父層 grid
    item（恰好只包這一欄）內的 /player/ 連結——避免抓到 Negative 欄（輸最多的人）。
    """
    player_urls = []

    try:
        print(f"Starting to find player links in Positive ranking column for time period {period}...")

        # 等榜單（任一玩家連結）重新渲染完成
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/player/']"))
            )
        except Exception:
            print("Timed out waiting for player links to render after period switch")

        # 以 'Positive ranking' 標題定位該欄，取其父 grid item 內的玩家連結
        player_links_in_positive = []
        try:
            positive_heading = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//h5[normalize-space(.)='Positive ranking']")
                )
            )
            positive_column = positive_heading.find_element(By.XPATH, "./parent::*")
            player_links_in_positive = positive_column.find_elements(
                By.CSS_SELECTOR, "a[href*='/player/']"
            )
            print(f"Found {len(player_links_in_positive)} player links in Positive ranking column")
        except Exception as e:
            # 退路：找不到標題（版面再次改版時）就抓全部連結，至少不空手而回
            print(f"Could not isolate Positive ranking column ({e}); falling back to all player links")
            player_links_in_positive = driver.find_elements(By.CSS_SELECTOR, "a[href*='/player/']")
            print(f"Fallback collected {len(player_links_in_positive)} player links (may include other columns)")

        # Extract specified number of unique player URLs
        seen_players = set()
        for link in player_links_in_positive:
            href = link.get_attribute("href") if hasattr(link, 'get_attribute') else getattr(link, 'href', None)
            if href and "/player/" in href:
                player_id_match = re.search(r'/player/(\d+)', href)
                if player_id_match:
                    player_id = player_id_match.group(1)
                    if player_id not in seen_players:
                        seen_players.add(player_id)
                        base_url = f"https://amae-koromo.sapk.ch/player/{player_id}/12"
                        url = f"{base_url}?limit={config.paipu_limit}"
                        player_urls.append(url)
                        print(f"Added player URL ({period}): {url}")

                        if len(player_urls) >= config.max_players_per_period:
                            break

    except Exception as e:
        print(f"Error extracting player links for time period {period}: {e}")

    return player_urls

def process_player(url, processed_paipu_ids, player_counts, config: CrawlerConfig, output_file=None):
    """Process paipu fetching for a single player"""
    driver, _ = create_stealth_driver(config.headless_mode)

    try:
        driver.get(url)

        # 等待頁面 body 載入
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # 等待至少一個 paipu 連結出現(最多等待 20 秒)
        print(f"等待頁面動態內容載入...")
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='paipu=']"))
            )
            print(f"頁面載入完成,開始收集 paipu 連結...")
        except Exception as e:
            print(f"等待 paipu 連結超時: {e}")
            print(f"嘗試繼續...")

        # 額外等待一秒,確保更多內容載入
        time.sleep(1)

        while True:
            paipu_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='paipu=']")

            if not paipu_links:
                paipu_links = driver.find_elements(By.XPATH, "//a[contains(@href, 'paipu=')]")

            new_paipu_found = False
            for link in paipu_links:
                href = link.get_attribute("href")
                if href and "paipu=" in href:
                    paipu_id = href.split("paipu=")[1].split("_")[0]

                    if paipu_id not in processed_paipu_ids:
                        processed_paipu_ids.add(paipu_id)
                        player_counts[url] += 1
                        print(f"Wrote new paipu ({url}):", paipu_id)

                        # 即時寫入到文件
                        if output_file:
                            output_file.write(paipu_id + "\n")
                            output_file.flush()  # 強制刷新緩衝區，確保立即寫入磁碟

                        new_paipu_found = True

                        # 添加小延迟，避免处理过快 (0.05-0.15秒)
                        time.sleep(random.uniform(0.05, 0.15))

            # 檢查是否已經滾動到底部
            if driver.execute_script("return window.innerHeight + window.scrollY + 10 >= document.body.offsetHeight"):
                break

            driver.execute_script("window.scrollBy(0, 500);")

            # 添加滚动延迟，避免滚动过快 (0.3-0.8秒)
            time.sleep(random.uniform(0.3, 0.8))



        print(f"Player {url} collected {player_counts[url]} paipu IDs")

    except Exception as e:
        print(f"Error processing player {url}: {e}")
    finally:
        driver.quit()

class PaipuSpider(scrapy.Spider):
    name = "paipu_spider"

    def __init__(self, config_path: str = "crawler_config.json"):
        # Load configuration
        self.config = CrawlerConfig.from_json(config_path)
        self.config.validate()

        # Set for O(1) membership dedup; IDs are persisted incrementally to the output file
        self.processed_paipu_ids = set()

        # Decide usage method based on configuration mode
        if self.config.crawler_mode == "manual":
            print("Using Manual mode (Legacy compatible)...")
            print(f"Reading {len(self.config.manual_player_urls)} manually configured player URLs from config file")

            # Use manual URLs from configuration file
            self.player_urls = []
            for url in self.config.manual_player_urls:
                # Ensure URL format is correct, add limit parameter
                if "/player/" not in url:
                    print(f"Skipping invalid URL format: {url}")
                    continue
                if "?limit=" not in url:
                    url = f"{url}?limit={self.config.paipu_limit}"
                self.player_urls.append(url)

            print(f"Loaded {len(self.player_urls)} valid player URLs")
            self.player_counts = {url: 0 for url in self.player_urls}

        elif self.config.crawler_mode in ("date_room", "date_room_player", "date_room_api"):
            print(f"Using {self.config.crawler_mode} mode...")
            # date_room / date_room_player / date_room_api 模式都不需要預先的 player_urls
            self.player_urls = []
            self.player_counts = {}

        else:  # auto mode
            print("Using automated configuration mode...")
            print(f"Configuration summary:")
            print(f"  Time periods: {[get_period_display_name(p) for p in self.config.time_periods]}")
            print(f"  Ranks: {[get_rank_display_name(r) for r in self.config.ranks]}")
            print(f"  Max players per period: {self.config.max_players_per_period}")
            print(f"  Paipu limit: {self.config.paipu_limit}")

            self.player_urls = get_top_players_urls(self.config)
            self.player_counts = {url: 0 for url in self.player_urls}

        # Read existing paipu IDs (all modes need this)
        try:
            with open(self.config.output_filename, "r") as file:
                for line in file:
                    paipu_id = line.strip()
                    if paipu_id:
                        self.processed_paipu_ids.add(paipu_id)
            print(f"Loaded {len(self.processed_paipu_ids)} processed paipu IDs")
        except FileNotFoundError:
            print(f"{self.config.output_filename} file not found, will create new file")

    def start_requests(self):
        yield scrapy.Request(url="https://amae-koromo.sapk.ch", callback=self.start_crawling)

    def start_crawling(self, response):  # noqa: ARG002 - Scrapy callback signature
        # 以追加模式打開文件，用於即時寫入
        with open(self.config.output_filename, "a", encoding='utf-8') as output_file:
            if self.config.crawler_mode == "date_room_api":
                # 純 amae-koromo API 直取（無 Selenium）：依房間+日期收集完整 UUID。
                # collect_room_paipus 會即時 write+flush 並把新 UUID 加進 processed set。
                collect_room_paipus(
                    self.config.target_room,
                    self.config.start_date,
                    self.config.end_date,
                    output_file=output_file,
                    existing_ids=self.processed_paipu_ids,
                )
                self.spider_closed(None)

            elif self.config.crawler_mode in ("date_room", "date_room_player"):
                # date_room / date_room_player share one collector; player_mode visits every player's page
                player_mode = self.config.crawler_mode == "date_room_player"
                date_room_paipus = collect_paipus_by_date_room(self.config, output_file, player_mode=player_mode)
                self.processed_paipu_ids.update(date_room_paipus)
                self.spider_closed(None)

            else:
                # Original auto and manual mode processing
                print(f"Starting to process {len(self.player_urls)} players...")

                for url in self.player_urls:
                    process_player(url, self.processed_paipu_ids, self.player_counts, self.config, output_file)

                self.spider_closed(None)

    def spider_closed(self, reason):  # noqa: ARG002 - Scrapy hook signature
        print(f"Total collected {len(self.processed_paipu_ids)} unique paipu IDs")

        if self.config.crawler_mode in ("date_room", "date_room_player", "date_room_api"):
            print(f"\n{self.config.crawler_mode} mode configuration summary:")
            print(f"  Date range: {self.config.start_date} to {self.config.end_date}")
            print(f"  Target room: {self.config.target_room}")
        else:
            print("Number of paipu IDs collected per player:")

            total_paipu = 0
            # 限制顯示的玩家數量，避免輸出過多
            max_display = 10
            for i, url in enumerate(self.player_urls):
                count = self.player_counts[url]
                total_paipu += count
                if i < max_display:
                    print(f"{url}: {count}")
                elif i == max_display:
                    print(f"... and {len(self.player_urls) - max_display} more players")

            print(f"\nTotal collected paipu count: {total_paipu}")

            # Display configuration summary
            if self.config.crawler_mode == "auto":
                print(f"\nConfiguration used:")
                print(f"  Time periods: {', '.join([get_period_display_name(p) for p in self.config.time_periods])}")
                print(f"  Ranks: {', '.join([get_rank_display_name(r) for r in self.config.ranks])}")

        if self.config.save_screenshots and self.config.crawler_mode == "auto":
            rank_suffix = "_".join(self.config.ranks).lower()
            print(f"\nVerification screenshots saved:")
            print(f"  - screenshot_rank_selection_verification.png (rank selection verification)")
            for period in self.config.time_periods:
                print(f"  - screenshot_{period}_positive_ranking_{rank_suffix}.png ({get_period_display_name(period)})")

        print(f"\n所有數據已即時寫入到文件: {self.config.output_filename}")
        print(f"爬蟲執行完成！")

# Function to create default configuration file
def create_default_config():
    """Create default configuration file"""
    config = CrawlerConfig.get_default_config()
    config.save_to_json("crawler_config.json")
    print("Created default configuration file: crawler_config.json")
    return config

# Create example configuration for date_room mode
def create_date_room_config_example():
    """Create example configuration file for date_room mode"""
    config = CrawlerConfig(
        crawler_mode="date_room",
        start_date="2019-08-20",
        end_date="2019-08-23",
        target_room="Jade",
        output_filename="date_room_list.txt",
        headless_mode=True,
        save_screenshots=False
    )
    config.save_to_json("date_room_config_example.json")
    print("Created date_room mode example configuration file: date_room_config_example.json")
    return config

# ==========================================
# Usage Instructions and Execution Method
# ==========================================

if __name__ == "__main__":
    # Method 1: Automated configuration mode (Recommended)
    # Configure in crawler_config.json:
    # {
    #   "crawler_mode": "auto",
    #   "time_periods": ["4w", "1w", "3d"],
    #   "ranks": ["Gold"],
    #   ...
    # }
    # Execute command: scrapy crawl paipu_spider

    # Method 2: Manual mode (Legacy Manual compatible)
    # Configure in crawler_config.json:
    # {
    #   "crawler_mode": "manual",
    #   "manual_player_urls": [
    #     "https://amae-koromo.sapk.ch/player/123456/12",
    #     "https://amae-koromo.sapk.ch/player/789012/12"
    #   ],
    #   ...
    # }
    # Execute command: scrapy crawl paipu_spider

    # Method 3: date_room mode (New)
    # Configure in crawler_config.json:
    # {
    #   "crawler_mode": "date_room",
    #   "start_date": "2019-08-20",
    #   "end_date": "2019-08-23",
    #   "target_room": "Jade",
    #   "output_filename": "list.txt",
    #   "headless_mode": true,
    #   "save_screenshots": true
    # }
    # Execute command: scrapy crawl paipu_spider

    # If configuration file doesn't exist, create default configuration
    if not os.path.exists("crawler_config.json"):
        create_default_config()
        print("Please edit the configuration file to customize your crawl settings")
        print("\nAvailable configuration modes:")
        print("  - crawler_mode: 'auto' (automated)")
        print("  - crawler_mode: 'manual' (manual)")
        print("  - crawler_mode: 'date_room' (date room mode)")
        print("  - For detailed settings, refer to examples in the configuration file")

        # Also create example for date_room mode
        if not os.path.exists("date_room_config_example.json"):
            create_date_room_config_example()
    else:
        print("Found existing configuration file: crawler_config.json")