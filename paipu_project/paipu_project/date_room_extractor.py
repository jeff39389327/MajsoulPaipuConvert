from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import re
import time
import requests
import hashlib
import tempfile
import os
import shutil

ROOM_RANK_MAPPING = {
    16: "Throne",
    12: "Jade",
    9: "Gold",
    15: "Throne East",
    11: "Jade East",
    8: "Gold East"
}

RANK_ROOM_MAPPING = {
    "Throne": 16,
    "Jade": 12,
    "Gold": 9,
    "Throne East": 15,
    "Jade East": 11,
    "Gold East": 8
}

SLEEP_TIME = 0  # Speed up

class OptimizedPaipuExtractor:
    
    def __init__(self, headless=True):
        self.headless = headless
        self.driver = None
        self.temp_user_data_dir = None
        self.setup_driver()

    
    def setup_driver(self):
        chrome_options = Options()
        
        # Basic headless mode setup
        if self.headless:
            chrome_options.add_argument("--headless=new")
        
        # Core fix: Do not use user-data-dir, use other isolation methods
        
        # Use random port to avoid debug port conflicts
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
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        chrome_options.add_argument("--disable-breakpad")
        chrome_options.add_argument("--disable-component-extensions-with-background-pages")
        chrome_options.add_argument("--disable-features=TranslateUI,BlinkGenPropertyTrees")
        chrome_options.add_argument("--disable-ipc-flooding-protection")
        chrome_options.add_argument("--disable-renderer-backgrounding")
        
        # Browser behavior settings
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        chrome_options.add_argument("--disable-popup-blocking")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--ignore-certificate-errors")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Prevent detection as automation tool
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Performance optimization
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--disable-features=IsolateOrigins,site-per-process")
        
        # Log settings - strongly suppress all logs
        chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--silent")
        chrome_options.add_argument("--disable-logging")
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        # Set environment variables to suppress Chrome logs
        import os as os_module
        os_module.environ['WDM_LOG_LEVEL'] = '0'
        os_module.environ['WDM_PRINT_FIRST_LINE'] = 'False'
        
        # Set User-Agent
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            
            # Enhanced anti-detection: Modify more browser features
            self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            
            # Hide webdriver features
            self.driver.execute_script("""
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
            
            import sys
            print(f"Chrome driver started successfully (debug port: {remote_port})", file=sys.stderr)
            print(f"Anti-detection measures applied", file=sys.stderr)
        except Exception as e:
            import sys
            print(f"Error starting Chrome driver: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            raise
    
    def is_valid_paipu_id(self, value):
        if not isinstance(value, str) or len(value) < 20:
            return False
        paipu_pattern = r'^[0-9]{6}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        return bool(re.match(paipu_pattern, value))
    
    def clean_paipu_id(self, raw_paipu_id):
        if not raw_paipu_id:
            return None
        if '_a' in raw_paipu_id:
            return raw_paipu_id.split('_a')[0]
        return raw_paipu_id
    
    def get_room_urls_by_ranks(self, target_date, target_ranks):
        room_urls = []
        for rank in target_ranks:
            if rank in RANK_ROOM_MAPPING:
                room_number = RANK_ROOM_MAPPING[rank]
                room_url = f"https://amae-koromo.sapk.ch/{target_date}/{room_number}"
                room_urls.append({
                    'url': room_url,
                    'rank': rank,
                    'room_number': room_number,
                    'date': target_date
                })
        return room_urls
    
    def wait_for_table_load(self, max_wait=10):
        import sys
        try:
            print(f"  Waiting for table elements to appear (max wait {max_wait} seconds)...", file=sys.stderr)
            WebDriverWait(self.driver, max_wait).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".ReactVirtualized__Table__rowColumn"))
            )
            print(f"  Table elements appeared", file=sys.stderr)

            
            # Check if there are game links
            game_links = self.driver.find_elements(By.XPATH, "//a[contains(@title, 'View game')]")
            print(f"  Found {len(game_links)} game links", file=sys.stderr)
            
            if len(game_links) == 0:
                print(f"  Warning: Table loaded but no game links found!", file=sys.stderr)
                # Try other ways to check
                all_links = self.driver.find_elements(By.TAG_NAME, "a")
                print(f"  Page has a total of {len(all_links)} links", file=sys.stderr)
                return False
            
            return True
        except Exception as e:
            print(f"  Error waiting for table to load: {e}", file=sys.stderr)
            return False
    
    def create_game_session_id(self, players, start_time, end_time, room_number):
        player_names = [p.split(']')[1].strip() if ']' in p else p for p in players]
        session_data = f"{room_number}_{start_time}_{end_time}_{'-'.join(sorted(player_names))}"
        session_id = hashlib.md5(session_data.encode()).hexdigest()[:12]
        return session_id
    
    def is_element_in_viewport(self, element):
        try:
            rect = self.driver.execute_script("""
                var rect = arguments[0].getBoundingClientRect();
                return {
                    top: rect.top,
                    bottom: rect.bottom,
                    left: rect.left,
                    right: rect.right
                };
            """, element)
            viewport_height = self.driver.execute_script("return window.innerHeight;")
            return rect['bottom'] > 0 and rect['top'] < viewport_height
        except:
            return False
    
    def find_5data_url_in_page(self):
        try:
            # 優先檢查當前 URL
            current_url = self.driver.current_url
            if '5-data.amae-koromo.com' in current_url:
                return current_url
            
            # 使用 JavaScript 快速查找（比 Selenium 快得多）
            api_url = self.driver.execute_script("""
                var links = document.querySelectorAll('a[href*="5-data.amae-koromo.com"]');
                for (var i = 0; i < links.length; i++) {
                    var href = links[i].href;
                    if (href && href.indexOf('view_game') > -1) {
                        return href;
                    }
                }
                return null;
            """)
            return api_url
        except:
            return None
    
    def extract_paipu_via_redirect(self, encrypted_api_url):
        try:
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response = session.get(encrypted_api_url, allow_redirects=True, timeout=2)  # 加快：10秒 → 2秒
            if response.status_code == 200:
                final_url = response.url
                paipu_match = re.search(r'paipu=([^&]+)', final_url)
                if paipu_match:
                    return paipu_match.group(1)
            return None
        except:
            return None
    
    def get_first_unprocessed_game(self, processed_session_ids, room_number):
        try:
            # 使用 JavaScript 快速查找可見的行（比 Selenium 快得多）
            rows_data = self.driver.execute_script("""
                var rows = document.querySelectorAll('.ReactVirtualized__Table__row');
                var viewportHeight = window.innerHeight;
                var result = [];
                
                for (var i = 0; i < rows.length; i++) {
                    var row = rows[i];
                    var rect = row.getBoundingClientRect();
                    
                    // 只處理可見的行
                    if (rect.bottom > 0 && rect.top < viewportHeight) {
                        var columns = row.querySelectorAll('.ReactVirtualized__Table__rowColumn');
                        if (columns.length >= 4) {
                            var playerLinks = columns[1].querySelectorAll('a');
                            if (playerLinks.length > 0) {
                                var players = [];
                                for (var j = 0; j < playerLinks.length; j++) {
                                    var text = playerLinks[j].textContent.trim();
                                    if (text) players.push(text);
                                }
                                
                                var startTime = columns[2].getAttribute('title') || columns[2].textContent.trim();
                                var endTime = columns[3].getAttribute('title') || columns[3].textContent.trim();
                                
                                if (players.length > 0 && startTime && endTime) {
                                    result.push({
                                        players: players,
                                        startTime: startTime,
                                        endTime: endTime,
                                        firstLinkIndex: i
                                    });
                                }
                            }
                        }
                    }
                }
                return result;
            """)
            
            # 在 Python 端檢查哪個未處理
            for row_data in rows_data:
                temp_session_id = self.create_game_session_id(
                    row_data['players'], 
                    row_data['startTime'], 
                    row_data['endTime'], 
                    room_number
                )
                
                if temp_session_id not in processed_session_ids:
                    # 獲取實際的鏈接元素
                    link = self.driver.execute_script(f"""
                        var rows = document.querySelectorAll('.ReactVirtualized__Table__row');
                        var columns = rows[{row_data['firstLinkIndex']}].querySelectorAll('.ReactVirtualized__Table__rowColumn');
                        return columns[1].querySelector('a');
                    """)
                    
                    if link:
                        return {
                            'players': row_data['players'],
                            'start_time': row_data['startTime'],
                            'end_time': row_data['endTime'],
                            'first_link': link,
                            'session_id': temp_session_id
                        }
            
            return None
        except:
            return None

    def click_game_and_extract_paipu_safe(self, game_record, room_info):
        try:
            players = game_record['players']
            start_time = game_record['start_time']
            end_time = game_record['end_time']
            session_id = game_record.get('session_id') or self.create_game_session_id(
                players, start_time, end_time, room_info['room_number']
            )
            
            # 直接點擊，不滾動（已經在可見範圍內）
            try:
                self.driver.execute_script("arguments[0].click();", game_record['first_link'])
            except:
                return None, session_id
            
            # 快速查找 API URL
            api_url = self.find_5data_url_in_page()
            
            if api_url:
                raw_paipu_id = self.extract_paipu_via_redirect(api_url)
                if raw_paipu_id:
                    clean_paipu_id = self.clean_paipu_id(raw_paipu_id)
                    if clean_paipu_id and self.is_valid_paipu_id(clean_paipu_id):
                        # 快速返回（優先使用 ESC）
                        try:
                            self.driver.execute_script("document.querySelector('body').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', keyCode: 27}));")
                        except:
                            self.driver.back()
                        
                        return clean_paipu_id, session_id
            
            # 快速返回
            try:
                self.driver.execute_script("document.querySelector('body').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', keyCode: 27}));")
            except:
                self.driver.back()
            
            return None, session_id
        except:
            try:
                self.driver.back()
            except:
                pass
            return None, None
    
    def process_room_with_continuous_scroll(self, room_info, max_paipus=5):
        extracted_paipus = []
        processed_session_ids = set()
        
        import sys
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Starting to process room: {room_info['rank']} ({room_info['room_number']})", file=sys.stderr)
        print(f"Date: {room_info['date']}", file=sys.stderr)
        print(f"Target paipu count: {max_paipus}", file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)
        
        try:
            print(f"Loading page: {room_info['url']}", file=sys.stderr)
            self.driver.get(room_info['url'])
            
            print(f"Waiting for table to load...", file=sys.stderr)
            if not self.wait_for_table_load():
                print(f"Table load failed!", file=sys.stderr)
                return []
            print(f"Table loaded successfully", file=sys.stderr)
            
            # Get initial page information
            initial_page_height = self.driver.execute_script("return document.body.scrollHeight;")
            print(f"  Initial page height: {initial_page_height}px", file=sys.stderr)
            
            self.driver.execute_script("window.scrollTo(0, 0);")

            print(f"Reset scroll position to top", file=sys.stderr)
            
            scroll_position = 0
            scroll_step = 1200  # Super fast scroll: 1200 pixels
            max_scroll_attempts = 99999999 
            consecutive_no_new = 0
            
            print(f"\nStarting scroll processing loop...", file=sys.stderr)
            
            for scroll_count in range(max_scroll_attempts):
                if len(extracted_paipus) >= max_paipus:
                    print(f"\nReached target paipu count ({max_paipus}), stopping scroll", file=sys.stderr)
                    break
                
                current_position = self.driver.execute_script("return window.pageYOffset;")
                viewport_height = self.driver.execute_script("return window.innerHeight;")
                page_height = self.driver.execute_script("return document.body.scrollHeight;")
                
                # Output progress every 50 scrolls (reduce I/O)
                if scroll_count % 50 == 0:
                    progress_pct = (current_position / page_height * 100) if page_height > 0 else 0
                    print(f"\nScroll progress #{scroll_count}: position={current_position}/{page_height} ({progress_pct:.1f}%) | collected={len(extracted_paipus)}/{max_paipus} | consecutive_no_new={consecutive_no_new}", file=sys.stderr)
                    
                    # Health check every 200 scrolls
                    if scroll_count % 200 == 0:
                        try:
                            # Check if browser is still alive
                            is_alive = self.driver.execute_script("return document.readyState;")
                            visible_rows = self.driver.execute_script("""
                                var rows = document.querySelectorAll('.ReactVirtualized__Table__row');
                                return rows.length;
                            """)
                            print(f"  Health check (#{scroll_count}): page_state={is_alive}, visible_rows={visible_rows}", file=sys.stderr)
                        except Exception as e:
                            print(f"  Health check failed: {e}", file=sys.stderr)
                
                processed_any = False
                max_attempts_per_scroll = 5  # Reduced to 5, speed up scrolling
                
                for attempt in range(max_attempts_per_scroll):
                    if len(extracted_paipus) >= max_paipus:
                        break
                    
                    unprocessed_game = self.get_first_unprocessed_game(processed_session_ids, room_info['room_number'])
                    
                    if unprocessed_game:
                        paipu_id, session_id = self.click_game_and_extract_paipu_safe(
                            unprocessed_game, room_info
                        )
                        
                        if paipu_id and paipu_id not in extracted_paipus:
                            extracted_paipus.append(paipu_id)
                            processed_session_ids.add(session_id)
                            processed_any = True
                            print(f"  Successfully extracted paipu #{len(extracted_paipus)}: {paipu_id}", file=sys.stderr)
                        elif session_id:
                            processed_session_ids.add(session_id)
                            processed_any = True
                            # print(f"  Game already processed but no paipu (session: {session_id[:8]}...)", file=sys.stderr)
                    else:
                        # No more unprocessed games at current position
                        break
                
                if not processed_any:
                    consecutive_no_new += 1
                    if consecutive_no_new >= 50:  # Fast scrolling needs larger buffer
                        print(f"\n{consecutive_no_new} consecutive scrolls with no new paipus, stopping processing", file=sys.stderr)
                        break
                else:
                    consecutive_no_new = 0
                
                # Check if reached page bottom
                if current_position + viewport_height >= page_height - 50:
                    print(f"\nReached page bottom (position: {current_position}+{viewport_height} >= {page_height})", file=sys.stderr)
                    break
                
                # Execute scroll
                scroll_position += scroll_step
                self.driver.execute_script(f"window.scrollTo(0, {scroll_position});")
                
                # Force trigger page re-render (important for virtual scrolling)
                self.driver.execute_script("window.dispatchEvent(new Event('scroll'));")
                
                # Wait for content to load (speed up: 0.8 -> 0.3)

                
                # Check if scroll actually moved
                new_position = self.driver.execute_script("return window.pageYOffset;")
                if new_position == current_position:
                    if scroll_count % 50 == 0:
                        print(f"  Warning: Scroll not effective! Position stays at {current_position}", file=sys.stderr)
                    # Try different way to scroll
                    self.driver.execute_script(f"window.scrollBy(0, {scroll_step});")

            
            print(f"\n{'='*60}", file=sys.stderr)
            print(f"Room processing completed: {room_info['rank']}", file=sys.stderr)
            print(f"Collected {len(extracted_paipus)} paipus", file=sys.stderr)
            print(f"Processed {len(processed_session_ids)} games", file=sys.stderr)
            print(f"Total scrolls: {scroll_count}", file=sys.stderr)
            print(f"{'='*60}\n", file=sys.stderr)
            
            return extracted_paipus
            
        except Exception as e:
            print(f"\nError processing room: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            print(f"Collected {len(extracted_paipus)} paipus before error", file=sys.stderr)
            return extracted_paipus
    
    def extract_from_rooms(self, target_date, target_ranks=None, max_paipus=5):
        if target_ranks is None:
            target_ranks = ["Jade"]
        
        all_paipus = []
        
        try:
            room_urls = self.get_room_urls_by_ranks(target_date, target_ranks)
            
            if not room_urls:
                return []
            
            for room_info in room_urls:
                if len(all_paipus) >= max_paipus:
                    break
                
                remaining_slots = max_paipus - len(all_paipus)
                room_paipus = self.process_room_with_continuous_scroll(room_info, remaining_slots)
                
                for paipu in room_paipus:
                    if paipu not in all_paipus:
                        all_paipus.append(paipu)
            
            return all_paipus
            
        except:
            return all_paipus
    
    def close(self):
        if self.driver:
            try:
                self.driver.quit()
                import sys
                print("Chrome driver closed", file=sys.stderr)
            except Exception as e:
                import sys
                print(f"Error closing Chrome driver: {e}", file=sys.stderr)

def convert_ranks_to_english(chinese_ranks):
    rank_mapping = {
        "王座": "Throne", "玉": "Jade", "金": "Gold",
        "王东": "Throne East", "玉东": "Jade East", "金东": "Gold East",
        "Throne": "Throne", "Jade": "Jade", "Gold": "Gold",
        "Throne East": "Throne East", "Jade East": "Jade East", "Gold East": "Gold East"
    }
    return [rank_mapping.get(rank, rank) for rank in chinese_ranks]

def main():
    # Parameter settings
    target_date = "2019-08-23"
    target_ranks = ["Throne"]
    max_paipus = 99999
    headless_mode = True
    
    target_ranks = convert_ranks_to_english(target_ranks)
    
    extractor = OptimizedPaipuExtractor(headless=headless_mode)
    
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