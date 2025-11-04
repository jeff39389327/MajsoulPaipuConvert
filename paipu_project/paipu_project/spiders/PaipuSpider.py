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
import shutil
import signal
import atexit
import random

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
        valid_modes = ["auto", "manual", "date_room"]
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
            
        elif self.crawler_mode == "date_room":
            # Validate date format and required parameters
            if not self.start_date or not self.end_date:
                raise ValueError("date_room mode requires start_date and end_date")
            if not self.target_room:
                raise ValueError("date_room mode requires target_room")
                
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
            
            print(f"date_room mode configuration validated")
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

def execute_date_room_extractor_py(target_date: str, target_room: str, headless_mode: bool = True, fast_mode: bool = False) -> List[str]:
    """
    Execute date_room_extractor.py and get the output paipu ID list
    
    Args:
        target_date: Target date (format: "2019-08-23")
        target_room: Target room (e.g.: "Throne", "Jade", "Gold", etc.)
        headless_mode: Whether to use headless mode
        fast_mode: Whether to use fast mode (faster but may miss 5-10% data)
        
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
    
    extractor = OptimizedPaipuExtractor(headless=headless_mode, fast_mode=fast_mode)
    
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
        fast_mode=str(fast_mode)
    )
    
    # Create temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as temp_file:
        temp_file.write(temp_script)
        temp_file_path = temp_file.name
    
    try:
        # Execute temporary script
        # Use errors='ignore' to ignore encoding errors (Chrome logs may contain non-UTF-8 characters)
        result = subprocess.run(
            [sys.executable, temp_file_path],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'  # Ignore characters that cannot be decoded
        )
        
        if result.returncode != 0:
            # Safely handle error output
            stderr_output = result.stderr if result.stderr else "Unknown error"
            print(f"Error executing date_room_extractor.py: {stderr_output}")
            return []
        
        # Parse output, one paipu ID per line
        paipu_ids = []
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                # Filter out non-paipu ID output (such as print debug messages)
                if line and re.match(r'^[0-9]{6}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', line):
                    paipu_ids.append(line)
        
        return paipu_ids
        
    finally:
        # Delete temporary file
        try:
            os.unlink(temp_file_path)
        except:
            pass

def collect_paipus_by_date_room(config: CrawlerConfig) -> List[str]:
    """Collect paipus using date_room mode"""
    all_paipus = []
    interrupted = False
    
    # Setup interrupt handler
    def signal_handler(sig, frame):
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
        
        # Calculate total days
        total_days = (end_date - start_date).days + 1
        print(f"\n{'='*70}")
        print(f"Starting date_room mode collection")
        print(f"{'='*70}")
        print(f"Date range: {config.start_date} to {config.end_date} (total {total_days} days)")
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
                    fast_mode=config.fast_mode
                )
            except Exception as e:
                print(f"Error processing {date_str}: {e}")
                import traceback
                traceback.print_exc()
                day_results = []
            
            # 檢查是否被中斷
            if interrupted:
                print(f"\nCollection interrupted by user")
                break
            
            # Add to total list (date_room_extractor.py already deduplicates, but ensure cross-date deduplication here)
            new_paipus = 0
            for paipu in day_results:
                if paipu not in all_paipus:
                    all_paipus.append(paipu)
                    new_paipus += 1
            
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
            
            # If not the last day, wait a bit
            if current_date <= end_date:
                remaining_days = (end_date - current_date).days + 1
                avg_time_per_day = total_elapsed / day_count
                estimated_remaining = avg_time_per_day * remaining_days / 60
                print(f"  Estimated remaining time: {estimated_remaining:.1f} minutes ({remaining_days} days)")
            
        
        total_time = time.time() - start_time
        print(f"\n{'='*70}")
        if interrupted:
            print(f"date_room mode collection interrupted by user!")
        else:
            print(f"date_room mode collection completed!")
        print(f"{'='*70}")
        print(f"Total collected: {len(all_paipus)} unique paipu IDs")
        print(f"Days processed: {day_count} days")
        print(f"Total time: {total_time/60:.1f} minutes ({total_time/3600:.2f} hours)")
        if len(all_paipus) > 0 and total_time > 0:
            print(f"Average speed: {len(all_paipus)/total_time*60:.1f} paipus/minute")
        print(f"{'='*70}\n")
        
    except Exception as e:
        print(f"\ndate_room mode execution error: {e}")
        import traceback
        traceback.print_exc()
        print(f"Collected {len(all_paipus)} paipus before error")
    
    return all_paipus

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
            try:
                # Try English label
                rank_label = driver.find_element(By.XPATH, f"//span[contains(@class, 'MuiFormControlLabel-label') and text()='{rank}']")
                checkbox = rank_label.find_element(By.XPATH, "./preceding-sibling::span//input[@type='checkbox']")
                
                if checkbox.is_selected():
                    print(f"Deselecting rank: {rank}")
                    driver.execute_script("arguments[0].click();", rank_label)
            except:
                # Try Chinese label
                try:
                    chinese_rank = get_rank_display_name(rank)
                    rank_label = driver.find_element(By.XPATH, f"//span[contains(@class, 'MuiFormControlLabel-label') and text()='{chinese_rank}']")
                    checkbox = rank_label.find_element(By.XPATH, "./preceding-sibling::span//input[@type='checkbox']")
                    
                    if checkbox.is_selected():
                        print(f"Deselecting rank: {chinese_rank}")
                        driver.execute_script("arguments[0].click();", rank_label)
                except:
                    continue
        
        # Select target ranks
        for rank in target_ranks:
            try:
                # Try English label
                rank_label = driver.find_element(By.XPATH, f"//span[contains(@class, 'MuiFormControlLabel-label') and text()='{rank}']")
                checkbox = rank_label.find_element(By.XPATH, "./preceding-sibling::span//input[@type='checkbox']")
                
                if not checkbox.is_selected():
                    print(f"Selecting rank: {rank}")
                    driver.execute_script("arguments[0].click();", rank_label)
                else:
                    print(f"Rank {rank} already selected")
            except:
                # Try Chinese label
                try:
                    chinese_rank = get_rank_display_name(rank)
                    rank_label = driver.find_element(By.XPATH, f"//span[contains(@class, 'MuiFormControlLabel-label') and text()='{chinese_rank}']")
                    checkbox = rank_label.find_element(By.XPATH, "./preceding-sibling::span//input[@type='checkbox']")
                    
                    if not checkbox.is_selected():
                        print(f"Selecting rank: {chinese_rank}")
                        driver.execute_script("arguments[0].click();", rank_label)
                    else:
                        print(f"Rank {chinese_rank} already selected")
                except Exception as e:
                    print(f"Unable to select rank {rank}: {e}")
        
        # Wait for page update
        print("Rank selection configuration completed")
        
    except Exception as e:
        print(f"Error configuring rank selection: {e}")

def get_top_players_urls(config: CrawlerConfig):
    """Automatically crawl leaderboard player URLs based on configuration"""
    chrome_options = Options()
    
    if config.headless_mode:
        chrome_options.add_argument("--headless=new")
    
    # Core fix: Do not use user-data-dir, use random port isolation
    import random
    remote_port = random.randint(9222, 65535)
    chrome_options.add_argument(f"--remote-debugging-port={remote_port}")
    
    # Core stability parameters
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-software-rasterizer")
    
    # Disable various features that may cause conflicts
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--window-size=1920,1080")
    
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
            print(f"\nVerification screenshots saved:")
            print(f"  - screenshot_rank_selection_verification.png (rank selection verification)")
            for period in config.time_periods:
                rank_suffix = "_".join(config.ranks).lower()
                print(f"  - screenshot_{period}_positive_ranking_{rank_suffix}.png ({get_period_display_name(period)})")
        
        return unique_player_urls
        
    except Exception as e:
        print(f"Error fetching rankings: {e}")
        return []
    
    finally:
        driver.quit()
        print("Chrome instance closed")

def extract_positive_ranking_players(driver, period, config: CrawlerConfig):
    """Extract player links from Positive ranking column"""
    player_urls = []
    
    try:
        print(f"Starting to find player links in Positive ranking column for time period {period}...")
        
        # Method 1: Try to find player links in Positive ranking column
        player_links_in_positive = []
        
        try:
            positive_heading = driver.find_element(By.XPATH, "//*[contains(text(), 'Positive ranking')]")
            print("Found Positive ranking heading")
            
            positive_container = positive_heading.find_element(By.XPATH, "./following-sibling::*[1] | ./parent::*/following-sibling::*[1]")
            
            container_links = positive_container.find_elements(By.CSS_SELECTOR, "a[href*='/player/']")
            player_links_in_positive.extend(container_links)
            print(f"Found {len(container_links)} player links in Positive ranking container")
            
        except Exception as e:
            print(f"Method 1 failed: {e}")
        
        # Method 2: If method 1 fails, try to locate through page layout
        if not player_links_in_positive:
            try:
                print("Trying method 2: Locating Positive ranking through page layout...")
                
                all_player_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/player/']")
                
                for link in all_player_links:
                    try:
                        location = link.location
                        size = driver.get_window_size()
                        
                        if size['width'] * 0.33 < location['x'] < size['width'] * 0.66:
                            player_links_in_positive.append(link)
                    except:
                        continue
                
                print(f"Method 2 found {len(player_links_in_positive)} possible Positive ranking links")
                
            except Exception as e:
                print(f"Method 2 also failed: {e}")
        
        # Method 3: If both methods fail, get all player links and filter
        if not player_links_in_positive:
            print("Trying method 3: Getting all player links...")
            all_links = driver.find_elements(By.TAG_NAME, "a")
            for link in all_links:
                href = link.get_attribute("href")
                if href and "/player/" in href:
                    player_links_in_positive.append(link)
            
            print(f"Method 3 found {len(player_links_in_positive)} player links")
            if len(player_links_in_positive) >= 60:
                start_idx = len(player_links_in_positive) // 3
                end_idx = start_idx + config.max_players_per_period
                player_links_in_positive = player_links_in_positive[start_idx:end_idx]
                print(f"After filtering, kept {len(player_links_in_positive)} Positive ranking links")
        
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

def process_player(url, processed_paipu_ids, player_counts, config: CrawlerConfig):
    """Process paipu fetching for a single player"""
    chrome_options = Options()
    
    if config.headless_mode:
        chrome_options.add_argument("--headless=new")
    
    # Core fix: Do not use user-data-dir, use random port isolation
    import random
    remote_port = random.randint(9222, 65535)
    chrome_options.add_argument(f"--remote-debugging-port={remote_port}")
    
    # Core stability parameters
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-software-rasterizer")
    
    # Disable various features that may cause conflicts
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--disable-popup-blocking")
    
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
                        processed_paipu_ids.append(paipu_id)
                        player_counts[url] += 1
                        print(f"Wrote new paipu ({url}):", paipu_id)
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
        
        self.processed_paipu_ids = []
        
        # Decide usage method based on configuration mode
        if self.config.crawler_mode == "manual":
            print("Using Manual mode (Legacy compatible)...")
            print(f"Reading {len(self.config.manual_player_urls)} manually configured player URLs from config file")
            
            # Use manual URLs from configuration file
            self.player_urls = []
            for url in self.config.manual_player_urls:
                # Ensure URL format is correct, add limit parameter
                if "/player/" in url and "?limit=" not in url:
                    url = f"{url}?limit={self.config.paipu_limit}"
                elif "/player/" in url and "?limit=" in url:
                    # URL already has limit parameter, use original URL
                    pass
                else:
                    print(f"Skipping invalid URL format: {url}")
                    continue
                self.player_urls.append(url)
            
            print(f"Loaded {len(self.player_urls)} valid player URLs")
            self.player_counts = {url: 0 for url in self.player_urls}
            
        elif self.config.crawler_mode == "date_room":
            print("Using date_room mode...")
            # date_room mode doesn't need player_urls
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
                        self.processed_paipu_ids.append(paipu_id)
            print(f"Loaded {len(self.processed_paipu_ids)} processed paipu IDs")
        except FileNotFoundError:
            print(f"{self.config.output_filename} file not found, will create new file")

    def start_requests(self):
        yield scrapy.Request(url="https://amae-koromo.sapk.ch", callback=self.start_crawling)

    def start_crawling(self, response):
        if self.config.crawler_mode == "date_room":
            # date_room mode: Directly call collection function
            date_room_paipus = collect_paipus_by_date_room(self.config)
            
            # Add to processed_paipu_ids (avoid duplicates)
            for paipu_id in date_room_paipus:
                if paipu_id not in self.processed_paipu_ids:
                    self.processed_paipu_ids.append(paipu_id)
            
            # End directly
            self.spider_closed(None)
            
        else:
            # Original auto and manual mode processing
            print(f"Starting to process {len(self.player_urls)} players...")
            
            for url in self.player_urls:
                process_player(url, self.processed_paipu_ids, self.player_counts, self.config)

            self.spider_closed(None)

    def spider_closed(self, reason):
        print(f"Total collected {len(self.processed_paipu_ids)} unique paipu IDs")
        
        if self.config.crawler_mode == "date_room":
            print("\ndate_room mode configuration summary:")
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
            print(f"\nVerification screenshots saved:")
            print(f"  - screenshot_rank_selection_verification.png (rank selection verification)")
            for period in self.config.time_periods:
                rank_suffix = "_".join(self.config.ranks).lower()
                print(f"  - screenshot_{period}_positive_ranking_{rank_suffix}.png ({get_period_display_name(period)})")

        print("Saving data...")
        self.write_to_file()

    def write_to_file(self):
        with open(self.config.output_filename, "w", encoding='utf-8') as file:
            for paipu_id in self.processed_paipu_ids:
                file.write(paipu_id + "\n")
        print(f"Paipu IDs saved to {self.config.output_filename}")

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
    import os
    if not os.path.exists("crawler_config.json"):
        create_default_config()
        print("Created default configuration file: crawler_config.json")
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