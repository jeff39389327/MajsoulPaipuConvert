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
import random
import sys
import io

from datetime import datetime

# 強制設定 stdout 和 stderr 為 UTF-8 編碼
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

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

# API请求延迟配置（秒）- 用于避免请求过快被拦截
API_REQUEST_DELAY_MIN = 0.5  # 最小延迟
API_REQUEST_DELAY_MAX = 1.5  # 最大延迟
CLICK_DELAY_MIN = 0.1        # 点击最小延迟
CLICK_DELAY_MAX = 0.3        # 点击最大延迟

class OptimizedPaipuExtractor:

    def __init__(self, headless=True, fast_mode=False, player_mode=False):
        """
        Args:
            headless: 是否使用无头模式
            fast_mode: 快速模式（速度优先，可能漏掉少量数据）
                      False: 完全模式，确保获取所有数据（慢但准确）
                      True: 快速模式，跳过部分扫描（快但可能漏 5-10%）
            player_mode: True 表示啟用逐玩家頁面模式（date_room_player），
                         每局會依序進入所有玩家頁面收集所有牌譜 ID
        """
        self.headless = headless
        self.fast_mode = fast_mode
        self.player_mode = player_mode
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
        # Set window size based on mode
        if self.headless:
            chrome_options.add_argument("--window-size=1920,3000")
        else:
            # Smaller, more manageable size for visible mode
            chrome_options.add_argument("--window-size=1280,800")
        
        # Force device scale factor
        chrome_options.add_argument("--force-device-scale-factor=1")

        # Prevent detection as automation tool
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        # 額外反檢測參數（針對 Cloudflare/Vercel）
        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.default_content_setting_values.notifications": 2,
            "webrtc.ip_handling_policy": "disable_non_proxied_udp",
            "webrtc.multiple_routes_enabled": False,
            "webrtc.nonproxied_udp_enabled": False
        }
        chrome_options.add_experimental_option("prefs", prefs)

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

        # Set User-Agent（更新至最新版本）
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

        try:
            self.driver = webdriver.Chrome(options=chrome_options)

            # Set viewport size for headless mode (critical for virtual scrolling)
            if self.headless:
                self.driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
                    'width': 1920,
                    'height': 3000,
                    'deviceScaleFactor': 1,
                    'mobile': False
                })

            # Enhanced anti-detection: Modify more browser features
            self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                "platform": "Win32"
            })

            # 繞過 Cloudflare/Vercel 檢測：注入更完整的 navigator 與 window 屬性
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    delete Object.getPrototypeOf(navigator).webdriver;

                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 0});
                    Object.defineProperty(navigator, 'vendor', {get: () => 'Google Inc.'});
                    Object.defineProperty(navigator, 'appVersion', {get: () => '5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['zh-TW', 'zh', 'en-US', 'en']});
                    Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
                    Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
                    Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});

                    window.chrome = {runtime: {}, loadTimes: function() {}, csi: function() {}};

                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );

                    if (navigator.connection) {
                        Object.defineProperty(navigator.connection, 'rtt', {get: () => 50});
                    }

                    const getParameter = WebGLRenderingContext.prototype.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(parameter) {
                        if (parameter === 37445) return 'Intel Inc.';
                        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                        return getParameter.apply(this, [parameter]);
                    };

                    ['height', 'width'].forEach(property => {
                        const imageDescriptor = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, property);
                        Object.defineProperty(HTMLImageElement.prototype, property, {
                            ...imageDescriptor,
                            get: function() {
                                if (this.complete && this.naturalHeight == 0) {
                                    return 20;
                                }
                                return imageDescriptor.get.apply(this);
                            },
                        });
                    });
                '''
            })



            import sys
            print(f"Chrome driver started successfully (debug port: {remote_port})", file=sys.stderr)
            print(f"Anti-detection measures applied", file=sys.stderr)
        except Exception as e:
            import sys
            print(f"Error starting Chrome driver: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            raise

    def restart_driver(self):
        import sys
        print("Restarting Chrome driver...", file=sys.stderr)
        try:
            if self.driver:
                self.driver.quit()
        except:
            pass
        time.sleep(2)
        self.setup_driver()

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


    def get_time_candidates(self, start_time):
        s = str(start_time).strip()
        candidates = set()
        # HH:MM
        m = re.search(r'(\d{1,2}:\d{1,2})', s)
        if m:
            hhmm = m.group(1)
            candidates.add(hhmm)
        # YYYY/M/D 或 YYYY-M-D
        dm = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', s)
        if dm and m:
            y, mo, d = dm.groups()
            hhmm = m.group(1)
            candidates.add(f"{y}/{int(mo)}/{int(d)} {hhmm}")
            candidates.add(f"{y}-{int(mo):02d}-{int(d):02d} {hhmm}")
        # 原字串也當作候選
        candidates.add(s)
        return [c for c in candidates if c]


    def _parse_date_loose(self, s):
        m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', str(s))
        if not m:
            return None
        y, mo, d = map(int, m.groups())
        return (y, mo, d)

    def _parse_time_loose(self, s):
        m = re.search(r'(\d{1,2}):(\d{1,2})', str(s))  # 支援 23:5 與 23:05
        if not m:
            return None
        hh, mm = map(int, m.groups())
        return (hh, mm)

    def _extract_dt_loose(self, text, fallback_date_str):
        date_tuple = self._parse_date_loose(text)
        if not date_tuple:
            date_tuple = self._parse_date_loose(fallback_date_str)
        time_tuple = self._parse_time_loose(text)
        if not (date_tuple and time_tuple):
            return None
        y, mo, d = date_tuple
        hh, mm = time_tuple
        try:
            return datetime(y, mo, d, hh, mm)
        except Exception:
            return None

    def is_time_close(self, target_time_str, row_text, room_date_str, tolerance_minutes=15):
        target_dt = self._extract_dt_loose(target_time_str, room_date_str)
        row_dt = self._extract_dt_loose(row_text, room_date_str)
        if not (target_dt and row_dt):
            return False
        diff = abs((row_dt - target_dt).total_seconds()) / 60.0
        return diff <= tolerance_minutes


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

    def wait_for_table_load(self, max_wait=20):
        import sys
        try:
            print(f"  Waiting for table elements to appear (max wait {max_wait} seconds)...", file=sys.stderr)
            WebDriverWait(self.driver, max_wait).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".ReactVirtualized__Table__rowColumn"))
            )
            print(f"  Table elements appeared", file=sys.stderr)

            # Critical for headless mode: Wait for JavaScript to fully initialize
            wait_time = 1.5 if self.fast_mode else 2
            time.sleep(wait_time)

            # Force trigger initial render in headless mode
            if self.headless:
                print(f"  Headless mode: Triggering initial content render...", file=sys.stderr)
                # Scroll down and back up to force virtual list to render
                self.driver.execute_script("window.scrollTo(0, 500);")
                time.sleep(1)
                self.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(1)
                # Force scroll events
                self.driver.execute_script("window.dispatchEvent(new Event('scroll'));")
                self.driver.execute_script("window.dispatchEvent(new Event('resize'));")
                time.sleep(2)

            # Check if there are game links
            game_links = self.driver.find_elements(By.XPATH, "//a[contains(@title, 'View game')]")
            print(f"  Found {len(game_links)} game links", file=sys.stderr)

            if len(game_links) == 0:
                print(f"  Warning: Table loaded but no game links found!", file=sys.stderr)
                # Try other ways to check
                all_links = self.driver.find_elements(By.TAG_NAME, "a")
                print(f"  Page has a total of {len(all_links)} links", file=sys.stderr)

                # In headless mode, try more aggressive rendering
                if self.headless:
                    print(f"  Headless mode: Attempting aggressive render trigger...", file=sys.stderr)
                    for i in range(3):
                        self.driver.execute_script(f"window.scrollTo(0, {(i+1)*300});")
                        time.sleep(1)
                    self.driver.execute_script("window.scrollTo(0, 0);")
                    time.sleep(2)

                    game_links = self.driver.find_elements(By.XPATH, "//a[contains(@title, 'View game')]")
                    print(f"  After aggressive render: Found {len(game_links)} game links", file=sys.stderr)
                    if len(game_links) > 0:
                        return True

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

    def close_dialog(self):
        """Close the game details dialog"""
        try:
            # Try multiple methods to close dialog
            # Method 1: Press ESC key
            self.driver.execute_script("""
                document.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'Escape',
                    keyCode: 27,
                    code: 'Escape',
                    bubbles: true
                }));
            """)
            time.sleep(0.1)

            # Method 2: Click backdrop (outside dialog)
            self.driver.execute_script("""
                var backdrop = document.querySelector('div[class*="backdrop"]') ||
                              document.querySelector('[role="presentation"]');
                if (backdrop) {
                    backdrop.click();
                }
            """)
            time.sleep(0.1)

            # Method 3: Click close button if exists
            self.driver.execute_script("""
                var dialog = document.querySelector('div[role="dialog"]');
                if (dialog) {
                    var closeBtn = dialog.querySelector('button[aria-label*="close"]') ||
                                   dialog.querySelector('button[aria-label*="關閉"]') ||
                                   dialog.querySelector('button[type="button"]');
                    if (closeBtn) {
                        closeBtn.click();
                    }
                }
            """)
        except:
            # Fallback: go back
            try:
                self.driver.back()
            except:
                pass

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
        """
        舊方法：通過 API 請求獲取牌譜 ID（已棄用，會觸發 API 限制）
        保留此函數作為備用方案
        """
        try:
            # 添加随机延迟，避免请求过快被拦截
            time.sleep(random.uniform(API_REQUEST_DELAY_MIN, API_REQUEST_DELAY_MAX))

            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })

            response = session.get(encrypted_api_url, allow_redirects=True, timeout=5)

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
                                var playerHrefs = [];
                                for (var j = 0; j < playerLinks.length; j++) {
                                    var text = playerLinks[j].textContent.trim();
                                    var href = playerLinks[j].href;
                                    if (text) players.push(text);
                                    // 只收集指向玩家頁面的連結
                                    if (href && href.indexOf('/player/') > -1) {
                                        playerHrefs.push(href);
                                    }
                                }

                                var startTime = columns[2].getAttribute('title') || columns[2].textContent.trim();
                                var endTime = columns[3].getAttribute('title') || columns[3].textContent.trim();

                                if (players.length > 0 && startTime && endTime && playerHrefs.length > 0) {
                                    result.push({
                                        players: players,
                                        playerHrefs: playerHrefs,
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
                    # 不保存元素引用，只保存索引和資料
                    return {
                        'players': row_data['players'],
                        'player_hrefs': row_data['playerHrefs'],
                        'start_time': row_data['startTime'],
                        'end_time': row_data['endTime'],
                        'first_link_index': row_data['firstLinkIndex'],
                        'session_id': temp_session_id
                    }

            return None
        except:
            return None

    def click_game_and_extract_paipu_safe(self, game_record, room_info):
        """
        新方法：通過訪問玩家頁面來獲取牌譜 ID，避免觸發 API 限制

        流程：
        1. 點擊玩家名稱 → 觸發彈窗
        2. 在彈窗中點擊 "Player details" → 前往玩家頁面
        3. 在玩家頁面用開始時間比對找到對應的牌譜 ID
        4. 返回原頁面繼續處理
        """
        try:
            players = game_record['players']
            start_time = game_record['start_time']
            end_time = game_record['end_time']
            player_hrefs = game_record.get('player_hrefs', [])
            session_id = game_record.get('session_id') or self.create_game_session_id(
                players, start_time, end_time, room_info['room_number']
            )

            if not player_hrefs:
                return None, session_id

            # 添加小延迟，避免点击过快
            time.sleep(random.uniform(CLICK_DELAY_MIN, CLICK_DELAY_MAX))

            # 保存當前頁面 URL 和滾動位置（日期房間頁面）
            original_url = self.driver.current_url
            original_scroll_position = self.driver.execute_script("return window.pageYOffset;")

            try:
                import sys
                print(f"\n{'='*60}", file=sys.stderr)
                print(f"處理遊戲: {players[0] if players else 'Unknown'}", file=sys.stderr)
                print(f"開始時間: {start_time}", file=sys.stderr)
                print(f"{'='*60}", file=sys.stderr)

                # 重新查找元素（避免 stale element reference）
                print(f"[1] 重新查找並點擊玩家名稱...", file=sys.stderr)
                first_link_index = game_record.get('first_link_index', 0)

                # 除錯資訊：顯示當前狀態
                debug_info = self.driver.execute_script(f"""
                    var rows = document.querySelectorAll('.ReactVirtualized__Table__row');
                    return {{
                        totalRows: rows.length,
                        targetIndex: {first_link_index},
                        scrollPosition: window.pageYOffset
                    }};
                """)
                print(f"    除錯: 總行數={debug_info['totalRows']}, 目標索引={debug_info['targetIndex']}, 滾動位置={debug_info['scrollPosition']}", file=sys.stderr)

                first_link = self.driver.execute_script(f"""
                    var rows = document.querySelectorAll('.ReactVirtualized__Table__row');
                    if (rows.length > {first_link_index}) {{
                        var columns = rows[{first_link_index}].querySelectorAll('.ReactVirtualized__Table__rowColumn');
                        if (columns.length > 1) {{
                            return columns[1].querySelector('a');
                        }}
                    }}
                    return null;
                """)

                if not first_link:
                    print(f"[X] 無法找到玩家連結（元素可能已被虛擬滾動回收）", file=sys.stderr)
                    print(f"    提示: 索引 {first_link_index} 超出範圍或元素未渲染", file=sys.stderr)
                    return None, session_id

                # 點擊玩家名稱，觸發彈窗
                print(f"[2] 點擊玩家名稱...", file=sys.stderr)
                try:
                    self.driver.execute_script("arguments[0].click();", first_link)
                except Exception as e:
                    print(f"[X] 點擊失敗: {str(e)}", file=sys.stderr)
                    return None, session_id

                # 等待彈窗出現
                time.sleep(0.3)
                print(f"[3] 等待彈窗出現...", file=sys.stderr)

                # 在彈窗中找到 "Player details" 連結並點擊
                player_details_link = None
                wait_start = time.time()
                max_wait = 1.0
                attempt_count = 0

                while time.time() - wait_start < max_wait:
                    attempt_count += 1
                    dialog_info = self.driver.execute_script("""
                        var dialog = document.querySelector('div[role="dialog"]');
                        if (dialog) {
                            var links = dialog.querySelectorAll('a[href*="/player/"]');
                            var linkTexts = [];
                            for (var i = 0; i < links.length; i++) {
                                linkTexts.push(links[i].textContent);
                                if (links[i].textContent.indexOf('Player details') > -1) {
                                    return {found: true, link: links[i], allLinks: linkTexts};
                                }
                            }
                            return {found: false, link: null, allLinks: linkTexts};
                        }
                        return {found: false, link: null, allLinks: []};
                    """)

                    if dialog_info and dialog_info.get('found'):
                        player_details_link = dialog_info['link']
                        print(f"    彈窗中找到連結: {dialog_info['allLinks']}", file=sys.stderr)
                        break
                    elif attempt_count == 1:
                        print(f"    彈窗狀態: 找到 {len(dialog_info.get('allLinks', []))} 個連結", file=sys.stderr)

                    time.sleep(0.05)

                if not player_details_link:
                    # 如果沒找到 Player details 連結，關閉彈窗並返回
                    print(f"[X] 未找到 Player details 連結（嘗試 {attempt_count} 次）", file=sys.stderr)
                    self.close_dialog()
                    return None, session_id

                # 獲取玩家 URL 並添加房間篩選
                try:
                    player_href = player_details_link.get_attribute('href')
                    print(f"    玩家連結: {player_href}", file=sys.stderr)
                except Exception as e:
                    print(f"[X] 獲取玩家 URL 失敗: {str(e)}", file=sys.stderr)
                    self.close_dialog()
                    return None, session_id

                room_number = room_info['room_number']
                room_rank = room_info.get('rank', ROOM_RANK_MAPPING.get(room_number, 'Unknown'))

                # 直接構建帶房間篩選的 URL
                if player_href:
                    # URL 格式: /player/{id}/{mode}
                    filtered_url = f"{player_href}/{room_number}"
                    print(f"[4] 前往玩家頁面（已篩選房間）: {filtered_url}", file=sys.stderr)
                    print(f"    房間: {room_rank} (mode={room_number})", file=sys.stderr)

                    # 直接導航到篩選後的 URL
                    try:
                        self.driver.get(filtered_url)
                        print(f"[5] 頁面導航成功", file=sys.stderr)
                    except Exception as e:
                        print(f"[X] 頁面導航失敗: {str(e)}", file=sys.stderr)
                        return None, session_id

                    # 等待頁面載入
                    print(f"[6] 等待頁面載入...", file=sys.stderr)
                    time.sleep(1.0)
                else:
                    print(f"[X] 無法獲取玩家 URL", file=sys.stderr)
                    self.close_dialog()
                    return None, session_id

                # 等待牌譜連結出現
                print(f"[7] 等待牌譜連結出現...", file=sys.stderr)
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='paipu=']"))
                    )
                    print(f"[8] 牌譜連結已出現", file=sys.stderr)
                except Exception as e:
                    # 如果沒有牌譜連結，返回原頁面並恢復滾動位置
                    print(f"[X] 未找到牌譜連結: {str(e)}", file=sys.stderr)
                    self.driver.get(original_url)
                    time.sleep(1)
                    self.driver.execute_script(f"window.scrollTo(0, {original_scroll_position});")
                    time.sleep(0.3)
                    return None, session_id

                # 下滑頁面以載入更多牌譜
                print(f"[9] 下滑頁面載入更多牌譜...", file=sys.stderr)
                for _ in range(3):
                    self.driver.execute_script("window.scrollBy(0, 500);")
                    time.sleep(0.3)

                # 使用 JavaScript 計算牌譜連結數量（避免 stale element）
                paipu_count = self.driver.execute_script("""
                    return document.querySelectorAll('a[href*="paipu="]').length;
                """)
                print(f"[10] 找到 {paipu_count} 個牌譜連結", file=sys.stderr)

                # 快速：先用候選時間直接匹配可見區域
                time_candidates = self.get_time_candidates(start_time)
                print(f"[10] 時間候選: {time_candidates}", file=sys.stderr)
                print(f"    原始開始時間: {start_time}", file=sys.stderr)
                print(f"    玩家列表: {players[:2]}...", file=sys.stderr)  # 只顯示前2個

                # 先取得前5個牌譜的資料來除錯（包含完整的表格行）
                sample_data = self.driver.execute_script("""
                    var samples = [];

                    // 嘗試找到表格行
                    var rows = document.querySelectorAll('.ReactVirtualized__Table__row');

                    for (var i = 0; i < Math.min(5, rows.length); i++) {
                        var row = rows[i];
                        var columns = row.querySelectorAll('.ReactVirtualized__Table__rowColumn');

                        var columnTexts = [];
                        for (var j = 0; j < columns.length; j++) {
                            var text = columns[j].innerText || columns[j].textContent || '';
                            columnTexts.push(text.trim());
                        }

                        samples.push({
                            index: i,
                            fullText: row.innerText || row.textContent || '',
                            columns: columnTexts
                        });
                    }

                    return samples;
                """)

                print(f"    前5個牌譜樣本（表格行）:", file=sys.stderr)
                for sample in sample_data:
                    print(f"      [{sample['index']}] 欄位數={len(sample['columns'])}", file=sys.stderr)
                    for col_idx, col_text in enumerate(sample['columns']):
                        if col_text:
                            print(f"          欄位{col_idx}: {col_text[:80]}", file=sys.stderr)

                # 直接在 JavaScript 中提取 href，檢查所有欄位
                matched_href = self.driver.execute_script("""
                    var candidates = arguments[0];
                    var rows = document.querySelectorAll('.ReactVirtualized__Table__row');

                    for (var i = 0; i < rows.length; i++) {
                        var row = rows[i];
                        var columns = row.querySelectorAll('.ReactVirtualized__Table__rowColumn');

                        // 收集所有欄位的文字
                        var allText = '';
                        for (var k = 0; k < columns.length; k++) {
                            allText += ' ' + (columns[k].innerText || columns[k].textContent || '');
                        }

                        // 檢查時間候選
                        for (var j = 0; j < candidates.length; j++) {
                            if (candidates[j] && allText.indexOf(candidates[j]) !== -1) {
                                // 找到匹配，返回這一行的牌譜連結
                                var link = row.querySelector('a[href*="paipu="]');
                                if (link) {
                                    return link.href;
                                }
                            }
                        }
                    }
                    return null;
                """, time_candidates)

                if matched_href and "paipu=" in matched_href:
                    paipu_id = matched_href.split("paipu=")[1].split("_")[0]
                    clean_paipu_id = self.clean_paipu_id(paipu_id)
                    if clean_paipu_id and self.is_valid_paipu_id(clean_paipu_id):
                        print(f"[✓] 找到匹配的牌譜: {clean_paipu_id}", file=sys.stderr)
                        print(f"[12] 返回原頁面並恢復滾動位置...", file=sys.stderr)
                        self.driver.get(original_url)
                        time.sleep(1)
                        self.driver.execute_script(f"window.scrollTo(0, {original_scroll_position});")
                        time.sleep(0.3)
                        return clean_paipu_id, session_id

                # 快速下滑以找出牌譜
                print(f"[8-quick] 以快速下滑方式搜尋牌譜...", file=sys.stderr)
                max_scrolls = 25 if self.fast_mode else 40
                step = 1000 if self.fast_mode else 700
                wait = 0.15 if self.fast_mode else 0.25

                for _ in range(max_scrolls):
                    self.driver.execute_script("window.scrollBy(0, arguments[0]);", step)
                    self.driver.execute_script("window.dispatchEvent(new Event('scroll'));")
                    time.sleep(wait)
                    # 檢查所有欄位
                    matched_href = self.driver.execute_script("""
                        var candidates = arguments[0];
                        var rows = document.querySelectorAll('.ReactVirtualized__Table__row');

                        for (var i = 0; i < rows.length; i++) {
                            var row = rows[i];
                            var columns = row.querySelectorAll('.ReactVirtualized__Table__rowColumn');

                            var allText = '';
                            for (var k = 0; k < columns.length; k++) {
                                allText += ' ' + (columns[k].innerText || columns[k].textContent || '');
                            }

                            for (var j = 0; j < candidates.length; j++) {
                                if (candidates[j] && allText.indexOf(candidates[j]) !== -1) {
                                    var link = row.querySelector('a[href*="paipu="]');
                                    if (link) {
                                        return link.href;
                                    }
                                }
                            }
                        }
                        return null;
                    """, time_candidates)
                    if matched_href and "paipu=" in matched_href:
                        paipu_id = matched_href.split("paipu=")[1].split("_")[0]
                        clean_paipu_id = self.clean_paipu_id(paipu_id)
                        if clean_paipu_id and self.is_valid_paipu_id(clean_paipu_id):
                            print(f"[✓] 找到匹配的牌譜: {clean_paipu_id}", file=sys.stderr)
                            print(f"[12] 返回原頁面並恢復滾動位置...", file=sys.stderr)
                            self.driver.get(original_url)
                            time.sleep(1)
                            self.driver.execute_script(f"window.scrollTo(0, {original_scroll_position});")
                            time.sleep(0.3)
                            return clean_paipu_id, session_id


                # 備用方案：使用 JavaScript 遍歷所有牌譜連結（避免 stale element）
                print(f"[11] 使用備用方案搜尋牌譜...", file=sys.stderr)

                # 準備玩家名稱列表
                clean_names = []
                for ptxt in players:
                    t = ptxt.split(']', 1)[1].strip() if ']' in ptxt else ptxt
                    t = re.sub(r"\s*\[\s*-?\d+\s*\]\s*$", "", t)
                    if t:
                        clean_names.append(t)

                print(f"    清理後的玩家名稱: {clean_names}", file=sys.stderr)
                print(f"    搜尋時間: {start_time}", file=sys.stderr)

                # 使用 JavaScript 搜尋匹配的牌譜（檢查所有欄位）
                result = self.driver.execute_script("""
                    var players = arguments[0];
                    var startTime = arguments[1];
                    var rows = document.querySelectorAll('.ReactVirtualized__Table__row');

                    var debugInfo = [];

                    for (var i = 0; i < Math.min(rows.length, 100); i++) {
                        var row = rows[i];
                        var columns = row.querySelectorAll('.ReactVirtualized__Table__rowColumn');

                        // 收集所有欄位的文字
                        var allText = '';
                        var columnTexts = [];
                        for (var k = 0; k < columns.length; k++) {
                            var colText = columns[k].innerText || columns[k].textContent || '';
                            allText += ' ' + colText;
                            columnTexts.push(colText.trim());
                        }

                        var nameMatches = 0;

                        // 計算玩家名稱匹配數
                        for (var j = 0; j < players.length; j++) {
                            if (allText.indexOf(players[j]) !== -1) {
                                nameMatches++;
                            }
                        }

                        // 檢查時間匹配
                        var timeMatch = allText.indexOf(startTime) !== -1;

                        // 收集前3個的除錯資訊
                        if (i < 3) {
                            debugInfo.push({
                                index: i,
                                nameMatches: nameMatches,
                                timeMatch: timeMatch,
                                text: allText.substring(0, 150),
                                columns: columnTexts
                            });
                        }

                        // 如果至少3個玩家名稱匹配或時間匹配
                        if (nameMatches >= 3 || timeMatch) {
                            var link = row.querySelector('a[href*="paipu="]');
                            if (link) {
                                return {
                                    found: true,
                                    href: link.href,
                                    index: i,
                                    nameMatches: nameMatches,
                                    timeMatch: timeMatch,
                                    rowText: allText.substring(0, 150),
                                    debugInfo: debugInfo
                                };
                            }
                        }
                    }

                    return {found: false, debugInfo: debugInfo};
                """, clean_names, start_time)

                # 顯示除錯資訊
                if result and 'debugInfo' in result:
                    print(f"    前3個牌譜的匹配情況:", file=sys.stderr)
                    for info in result['debugInfo']:
                        print(f"      [{info['index']}] 玩家匹配={info['nameMatches']}, 時間匹配={info['timeMatch']}", file=sys.stderr)
                        if 'columns' in info and info['columns']:
                            print(f"          欄位數: {len(info['columns'])}", file=sys.stderr)
                            for col_idx, col_text in enumerate(info['columns']):
                                if col_text:
                                    print(f"            欄位{col_idx}: {col_text[:60]}", file=sys.stderr)
                        else:
                            print(f"          內容: {info['text']}", file=sys.stderr)

                if result and result.get('found'):
                    href = result['href']
                    if href and "paipu=" in href:
                        paipu_id = href.split("paipu=")[1].split("_")[0]
                        clean_paipu_id = self.clean_paipu_id(paipu_id)

                        if clean_paipu_id and self.is_valid_paipu_id(clean_paipu_id):
                            print(f"[✓] 找到匹配的牌譜: {clean_paipu_id}", file=sys.stderr)
                            print(f"    匹配資訊: 玩家={result['nameMatches']}, 時間={result['timeMatch']}", file=sys.stderr)
                            print(f"[12] 返回原頁面並恢復滾動位置...", file=sys.stderr)
                            self.driver.get(original_url)
                            time.sleep(1)
                            self.driver.execute_script(f"window.scrollTo(0, {original_scroll_position});")
                            time.sleep(0.3)
                            return clean_paipu_id, session_id

                print(f"[X] 未找到匹配的牌譜", file=sys.stderr)

                # 如果沒找到匹配的，返回原頁面並恢復滾動位置
                print(f"[12] 返回原頁面並恢復滾動位置...", file=sys.stderr)
                self.driver.get(original_url)
                time.sleep(1)
                self.driver.execute_script(f"window.scrollTo(0, {original_scroll_position});")
                time.sleep(0.3)
                return None, session_id

            except Exception as e:
                # 發生錯誤時返回原頁面並恢復滾動位置
                print(f"[ERROR] 處理過程出錯: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc(file=sys.stderr)
                try:
                    self.driver.get(original_url)
                    time.sleep(1)
                    self.driver.execute_script(f"window.scrollTo(0, {original_scroll_position});")
                    time.sleep(0.3)
                except:
                    pass
                return None, session_id

        except Exception as e:
            print(f"[ERROR] 外層錯誤: {e}", file=sys.stderr)
            return None, None


    def collect_all_paipus_on_player_page(self, existing_ids=None):
        """在當前玩家頁面向下捲動並收集所有 paipu= 連結的牌譜 ID。

        Args:
            existing_ids: 用來避免重複加入的 ID set，允許為 None。

        Returns:
            List[str]: 本次在該玩家頁面新收集到的所有牌譜 ID。
        """
        import sys

        if existing_ids is None:
            existing_ids = set()

        collected = []

        try:
            print(f"[PlayerMode] 等待玩家頁面 paipu 連結載入...", file=sys.stderr)
            try:
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='paipu=']"))
                )
            except Exception as e:
                print(f"[PlayerMode] 等待 paipu 連結超時: {e}", file=sys.stderr)

            time.sleep(1)

            while True:
                paipu_links = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='paipu=']")
                if not paipu_links:
                    paipu_links = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'paipu=')]")

                for link in paipu_links:
                    href = link.get_attribute("href")
                    if not href or "paipu=" not in href:
                        continue

                    paipu_id = href.split("paipu=")[1].split("_")[0]
                    clean_paipu_id = self.clean_paipu_id(paipu_id)
                    if not clean_paipu_id or not self.is_valid_paipu_id(clean_paipu_id):
                        continue

                    if clean_paipu_id in existing_ids:
                        continue

                    existing_ids.add(clean_paipu_id)
                    collected.append(clean_paipu_id)

                    # 立即輸出到 stdout 供 Spider 即時讀取
                    print(f"[PlayerMode] 收集到牌譜 #{len(collected)}: {clean_paipu_id}", file=sys.stderr)
                    print(clean_paipu_id, flush=True)

                # 檢查是否已經滾動到底部
                at_bottom = self.driver.execute_script(
                    "return window.innerHeight + window.scrollY + 10 >= document.body.offsetHeight"
                )
                if at_bottom:
                    break

                self.driver.execute_script("window.scrollBy(0, 500);")
                time.sleep(random.uniform(0.3, 0.8))

            print(f"[PlayerMode] 玩家頁面共新增 {len(collected)} 個牌譜", file=sys.stderr)

        except Exception as e:
            print(f"[PlayerMode] 收集玩家頁面牌譜時發生錯誤: {e}", file=sys.stderr)

        return collected

    def collect_all_paipus_for_game_player_mode(self, game_record, room_info):
        """player_mode 下：對單局的所有玩家逐一進入玩家頁面並收集所有牌譜 ID。

        Returns:
            Tuple[List[str], Optional[str]]: (該局所有新收集到的牌譜 ID, session_id)
        """
        import sys

        try:
            players = game_record["players"]
            start_time = game_record["start_time"]
            end_time = game_record["end_time"]
            player_hrefs = game_record.get("player_hrefs", [])
            session_id = game_record.get("session_id") or self.create_game_session_id(
                players, start_time, end_time, room_info["room_number"]
            )

            if not player_hrefs:
                print("[PlayerMode] game_record 中沒有 player_hrefs，跳過", file=sys.stderr)
                return [], session_id

            # 保存原日期房間頁面的 URL 與滾動位置
            original_url = self.driver.current_url
            original_scroll_position = self.driver.execute_script("return window.pageYOffset;")

            room_number = room_info["room_number"]
            room_rank = room_info.get("rank", ROOM_RANK_MAPPING.get(room_number, "Unknown"))

            print(f"\n{'='*60}", file=sys.stderr)
            print(f"[PlayerMode] 處理遊戲（逐玩家模式）", file=sys.stderr)
            print(f"  房間: {room_rank} (mode={room_number})", file=sys.stderr)
            print(f"  玩家: {players}", file=sys.stderr)
            print(f"  開始時間: {start_time}", file=sys.stderr)
            print(f"  player_hrefs: {player_hrefs}", file=sys.stderr)
            print(f"{'='*60}", file=sys.stderr)

            all_new_paipus = []
            seen_ids = set()

            for idx, player_href in enumerate(player_hrefs):
                if not player_href:
                    print(f"[PlayerMode] 跳過空的 player_href (idx={idx})", file=sys.stderr)
                    continue

                player_name = players[idx] if idx < len(players) else f"Player#{idx + 1}"

                print(f"[PlayerMode] 處理玩家 #{idx}: {player_name}", file=sys.stderr)
                print(f"[PlayerMode]   原始 player_href: {player_href}", file=sys.stderr)

                # 確保 player_href 是玩家頁面的 URL
                if '/player/' not in player_href:
                    print(f"[PlayerMode] 警告: player_href 不包含 '/player/'，跳過", file=sys.stderr)
                    continue

                # Retry loop for player page navigation
                max_retries = 2
                success = False
                
                for retry in range(max_retries + 1):
                    try:
                        filtered_url = f"{player_href}/{room_number}"
                        print(f"[PlayerMode]   構建的 filtered_url: {filtered_url}", file=sys.stderr)
                        
                        self.driver.get(filtered_url)
                        time.sleep(1.5)
                        
                        # Check for common error text
                        error_check = self.driver.execute_script("""
                            var bodyText = document.body.innerText;
                            return bodyText.includes('Error loading data') || 
                                   bodyText.includes('500 Internal Server Error') ||
                                   bodyText.includes('An error occurred');
                        """)
                        
                        if error_check:
                            raise Exception("Page displayed error message")
                            
                        success = True
                        break
                        
                    except Exception as e:
                        print(f"[PlayerMode] 無法開啟玩家頁面 {player_name} (嘗試 {retry+1}/{max_retries+1}): {e}", file=sys.stderr)
                        
                        if retry < max_retries:
                            print(f"[PlayerMode] 嘗試重啟 Driver...", file=sys.stderr)
                            self.restart_driver()
                            time.sleep(1)
                        else:
                            print(f"[PlayerMode] 放棄此玩家", file=sys.stderr)

                if not success:
                    continue

                player_paipus = self.collect_all_paipus_on_player_page(existing_ids=seen_ids)
                print(f"[PlayerMode] 玩家 {player_name} 新增 {len(player_paipus)} 個牌譜", file=sys.stderr)
                all_new_paipus.extend(player_paipus)

            # 返回原日期房間頁面並恢復滾動位置
            try:
                print(f"[PlayerMode] 返回日期房間頁面並恢復滾動位置...", file=sys.stderr)
                self.driver.get(original_url)
                time.sleep(1)
                self.driver.execute_script(f"window.scrollTo(0, {original_scroll_position});")
                time.sleep(0.3)
            except Exception as e:
                print(f"[PlayerMode] 返回日期房間頁面失敗: {e}", file=sys.stderr)

            return all_new_paipus, session_id

        except Exception as e:
            print(f"[PlayerMode] 處理遊戲時發生錯誤: {e}", file=sys.stderr)
            return [], None


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

            # Additional wait for headless mode to ensure full initialization
            if self.headless:
                wait_time = 1.5 if self.fast_mode else 3
                print(f"  Headless mode: Extra initialization wait ({wait_time}s)...", file=sys.stderr)
                time.sleep(wait_time)

                # # Debug: Save screenshot in headless mode to verify page loaded
                # try:
                #     screenshot_path = f"debug_headless_{room_info['date']}_{room_info['room_number']}.png"
                #     self.driver.save_screenshot(screenshot_path)
                #     print(f"  Debug screenshot saved: {screenshot_path}", file=sys.stderr)
                # except:
                #     pass

            # Get initial page information
            initial_page_height = self.driver.execute_script("return document.body.scrollHeight;")
            print(f"  Initial page height: {initial_page_height}px", file=sys.stderr)

            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)

            print(f"Reset scroll position to top", file=sys.stderr)

            # Warm-up scrolling for headless mode to initialize virtual scrolling
            if self.headless:
                if self.fast_mode:
                    # Fast mode: minimal warmup
                    print(f"  Fast mode: Quick warmup...", file=sys.stderr)
                    self.driver.execute_script("window.scrollTo(0, 600);")
                    self.driver.execute_script("window.dispatchEvent(new Event('scroll'));")
                    time.sleep(0.5)
                    self.driver.execute_script("window.scrollTo(0, 0);")
                    time.sleep(0.5)
                else:
                    print(f"  Headless mode: Warming up virtual scroll...", file=sys.stderr)
                    for warmup in range(3):
                        self.driver.execute_script(f"window.scrollTo(0, {(warmup+1)*400});")
                        self.driver.execute_script("window.dispatchEvent(new Event('scroll'));")
                        time.sleep(0.8)
                    self.driver.execute_script("window.scrollTo(0, 0);")
                    time.sleep(1)
                    print(f"  Warm-up complete", file=sys.stderr)

            scroll_position = 0
            # Adjust scroll speed based on mode
            if self.fast_mode:
                scroll_step = 800  # Fast mode: balanced (same processing, larger steps)
            elif self.headless:
                scroll_step = 600  # Headless careful: 600 pixels
            else:
                scroll_step = 800  # Normal mode: 800 pixels
            max_scroll_attempts = 99999999
            consecutive_no_new = 0

            if self.fast_mode:
                print(f"  ⚡ Fast mode: scroll={scroll_step}px, threshold=80, full_processing=enabled", file=sys.stderr)

            print(f"\nStarting scroll processing loop...", file=sys.stderr)

            for scroll_count in range(max_scroll_attempts):
                if len(extracted_paipus) >= max_paipus:
                    print(f"\nReached target paipu count ({max_paipus}), stopping scroll", file=sys.stderr)
                    break

                # Re-fetch page dimensions each iteration (important for dynamic virtual scrolling)
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
                # Adjust attempts based on mode
                if self.fast_mode:
                    max_attempts_per_scroll = 10  # Fast: must process all visible games
                elif self.headless:
                    max_attempts_per_scroll = 15  # Headless: more thorough
                else:
                    max_attempts_per_scroll = 10  # Normal mode

                for attempt in range(max_attempts_per_scroll):
                    if len(extracted_paipus) >= max_paipus:
                        break

                    unprocessed_game = self.get_first_unprocessed_game(processed_session_ids, room_info['room_number'])

                    if not unprocessed_game:
                        # No more unprocessed games at current position
                        break

                    # 根據模式選擇不同的處理方式
                    if self.player_mode:
                        paipu_ids, session_id = self.collect_all_paipus_for_game_player_mode(
                            unprocessed_game, room_info
                        )

                        if session_id:
                            processed_session_ids.add(session_id)
                            processed_any = True

                        # 注意：paipu_ids 中的每個 ID 已經在 collect_all_paipus_on_player_page 中即時輸出到 stdout
                        # 這裡只需要加入到 extracted_paipus 列表中，不需要再次輸出
                        for paipu_id in paipu_ids:
                            if len(extracted_paipus) >= max_paipus:
                                break
                            if paipu_id not in extracted_paipus:
                                extracted_paipus.append(paipu_id)
                                processed_any = True
                    else:
                        paipu_id, session_id = self.click_game_and_extract_paipu_safe(
                            unprocessed_game, room_info
                        )

                        if paipu_id and paipu_id not in extracted_paipus:
                            extracted_paipus.append(paipu_id)
                            processed_session_ids.add(session_id)
                            processed_any = True
                            print(f"  Successfully extracted paipu #{len(extracted_paipus)}: {paipu_id}", file=sys.stderr)
                            # 立即輸出到 stdout 供 PaipuSpider 即時讀取
                            print(paipu_id, flush=True)
                        elif session_id:
                            processed_session_ids.add(session_id)
                            processed_any = True
                            # print(f"  Game already processed but no paipu (session: {session_id[:8]}...)", file=sys.stderr)

                if not processed_any:
                    consecutive_no_new += 1
                    # Adjust patience based on mode
                    if self.fast_mode:
                        threshold = 100  # Fast: balanced (rely on reverse/final scan for safety)
                    elif self.headless:
                        threshold = 150  # Headless: more patience
                    else:
                        threshold = 100  # Normal
                    if consecutive_no_new >= threshold:
                        print(f"\n{consecutive_no_new} consecutive scrolls with no new paipus, stopping processing", file=sys.stderr)
                        break
                else:
                    consecutive_no_new = 0

                # Check if reached page bottom
                # Important: Don't break immediately, check multiple times to handle dynamic height changes
                if current_position + viewport_height >= page_height - 50:
                    # Verify we're really at bottom by checking if new scroll attempts don't move
                    old_height = page_height
                    time.sleep(0.5)
                    new_height = self.driver.execute_script("return document.body.scrollHeight;")
                    new_position = self.driver.execute_script("return window.pageYOffset;")

                    print(f"\nPossible bottom detected: pos={new_position}, height={new_height} (was {old_height})", file=sys.stderr)

                    # Only break if height is stable and we're really at bottom
                    if new_position + viewport_height >= new_height - 50 and abs(new_height - old_height) < 100:
                        print(f"Confirmed page bottom reached", file=sys.stderr)
                        break
                    else:
                        print(f"False alarm - page height changed, continuing scroll...", file=sys.stderr)
                        # Update page_height for next iteration
                        page_height = new_height

                # Execute scroll
                scroll_position += scroll_step

                # Handle case where page height shrinks during scroll (common with virtual scrolling)
                current_page_height = self.driver.execute_script("return document.body.scrollHeight;")
                if scroll_position > current_page_height - viewport_height:
                    # Adjust to not exceed page bounds
                    old_scroll_pos = scroll_position
                    scroll_position = max(0, current_page_height - viewport_height)
                    if scroll_count % 50 == 0 and old_scroll_pos != scroll_position:
                        print(f"  Adjusted scroll position: {old_scroll_pos} -> {scroll_position} (page height: {current_page_height})", file=sys.stderr)

                self.driver.execute_script(f"window.scrollTo(0, {scroll_position});")

                # Force trigger page re-render (important for virtual scrolling)
                self.driver.execute_script("window.dispatchEvent(new Event('scroll'));")

                # Wait for content to load - critical for virtual scrolling!
                if self.fast_mode:
                    time.sleep(0.5)  # Fast: must wait enough for processing (NOT just rendering)
                elif self.headless:
                    time.sleep(0.8)  # Headless: more wait
                else:
                    time.sleep(0.5)  # Normal

                # Check if scroll actually moved
                new_position = self.driver.execute_script("return window.pageYOffset;")
                if new_position == current_position:
                    if scroll_count % 50 == 0:
                        print(f"  Warning: Scroll not effective! Position stays at {current_position}", file=sys.stderr)
                    # Try different way to scroll
                    self.driver.execute_script(f"window.scrollBy(0, {scroll_step});")

            # Headless mode: Reverse scroll from bottom to top
            # Fast mode uses a quicker version
            if self.headless:
                print(f"\n{'-'*60}", file=sys.stderr)
                print(f"Headless mode: Performing reverse scan (bottom to top)...", file=sys.stderr)

                # Scroll to bottom first
                page_height = self.driver.execute_script("return document.body.scrollHeight;")
                self.driver.execute_script(f"window.scrollTo(0, {page_height});")
                time.sleep(2)

                reverse_found = 0
                # Adjust reverse scan based on mode
                if self.fast_mode:
                    reverse_step = -800   # Fast: balanced steps
                    max_reverse_iterations = 100  # More iterations for coverage
                    reverse_attempts = 10         # More attempts for reliability
                    reverse_wait = 0.4            # Adequate wait
                else:
                    reverse_step = -600  # Normal: smaller steps
                    max_reverse_iterations = 200
                    reverse_attempts = 15
                    reverse_wait = 0.5

                reverse_position = page_height

                for rev_count in range(max_reverse_iterations):
                    if len(extracted_paipus) >= max_paipus:
                        break

                    for attempt in range(reverse_attempts):
                        if len(extracted_paipus) >= max_paipus:
                            break

                        unprocessed_game = self.get_first_unprocessed_game(processed_session_ids, room_info['room_number'])
                        if not unprocessed_game:
                            break

                        if self.player_mode:
                            paipu_ids, session_id = self.collect_all_paipus_for_game_player_mode(
                                unprocessed_game, room_info
                            )

                            if session_id:
                                processed_session_ids.add(session_id)

                            # 注意：paipu_ids 中的每個 ID 已經在 collect_all_paipus_on_player_page 中即時輸出到 stdout
                            # 這裡只需要加入到 extracted_paipus 列表中，不需要再次輸出
                            for paipu_id in paipu_ids:
                                if len(extracted_paipus) >= max_paipus:
                                    break
                                if paipu_id not in extracted_paipus:
                                    extracted_paipus.append(paipu_id)
                                    reverse_found += 1
                        else:
                            paipu_id, session_id = self.click_game_and_extract_paipu_safe(
                                unprocessed_game, room_info
                            )
                            if paipu_id and paipu_id not in extracted_paipus:
                                extracted_paipus.append(paipu_id)
                                processed_session_ids.add(session_id)
                                reverse_found += 1
                                print(f"  Reverse scan found paipu #{len(extracted_paipus)}: {paipu_id}", file=sys.stderr)
                                # 立即輸出到 stdout
                                print(paipu_id, flush=True)
                            elif session_id:
                                processed_session_ids.add(session_id)

                    # Check if at top
                    current_pos = self.driver.execute_script("return window.pageYOffset;")
                    if current_pos <= 100:
                        print(f"  Reverse scan reached top", file=sys.stderr)
                        break

                    reverse_position += reverse_step
                    if reverse_position < 0:
                        reverse_position = 0
                    self.driver.execute_script(f"window.scrollTo(0, {reverse_position});")
                    self.driver.execute_script("window.dispatchEvent(new Event('scroll'));")
                    time.sleep(reverse_wait)

                print(f"Reverse scan completed: found {reverse_found} additional paipus", file=sys.stderr)
                print(f"{'-'*60}\n", file=sys.stderr)

            # Final sweep: Multiple passes to catch any missed paipus
            print(f"\n{'-'*60}", file=sys.stderr)
            if self.fast_mode:
                print(f"⚡ Fast mode: Performing quick final sweep...", file=sys.stderr)
                num_sweeps = 1  # Fast mode: one quick sweep
            else:
                print(f"Performing final sweep to catch any missed paipus...", file=sys.stderr)
                # Headless mode: Do 2 complete sweeps for better coverage
                num_sweeps = 2 if self.headless else 1

            total_final_found = 0

            for sweep_pass in range(num_sweeps):
                if sweep_pass > 0:
                    print(f"  Starting sweep pass {sweep_pass + 1}/{num_sweeps}...", file=sys.stderr)

                self.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(1.5 if self.headless else 1)

                final_sweep_scroll = 0
                # Adjust sweep step based on mode
                if self.fast_mode:
                    final_sweep_step = 600  # Fast: smaller steps for coverage
                elif self.headless:
                    final_sweep_step = 400  # Headless: very small steps
                else:
                    final_sweep_step = 500  # Normal steps
                final_sweep_found = 0

                # Adjust iterations based on mode
                max_iterations = 120 if self.fast_mode else 300  # More for coverage
                for sweep_count in range(max_iterations):
                    if len(extracted_paipus) >= max_paipus:
                        break

                    # Adjust attempts per position based on mode
                    if self.fast_mode:
                        sweep_attempts = 8   # Fast: more for reliability
                    elif self.headless:
                        sweep_attempts = 15
                    else:
                        sweep_attempts = 10
                    for attempt in range(sweep_attempts):
                        if len(extracted_paipus) >= max_paipus:
                            break

                        unprocessed_game = self.get_first_unprocessed_game(processed_session_ids, room_info['room_number'])
                        if not unprocessed_game:
                            break

                        if self.player_mode:
                            paipu_ids, session_id = self.collect_all_paipus_for_game_player_mode(
                                unprocessed_game, room_info
                            )

                            if session_id:
                                processed_session_ids.add(session_id)

                            # 注意：paipu_ids 中的每個 ID 已經在 collect_all_paipus_on_player_page 中即時輸出到 stdout
                            # 這裡只需要加入到 extracted_paipus 列表中，不需要再次輸出
                            for paipu_id in paipu_ids:
                                if len(extracted_paipus) >= max_paipus:
                                    break
                                if paipu_id not in extracted_paipus:
                                    extracted_paipus.append(paipu_id)
                                    final_sweep_found += 1
                        else:
                            paipu_id, session_id = self.click_game_and_extract_paipu_safe(
                                unprocessed_game, room_info
                            )
                            if paipu_id and paipu_id not in extracted_paipus:
                                extracted_paipus.append(paipu_id)
                                processed_session_ids.add(session_id)
                                final_sweep_found += 1
                                print(f"  Final sweep pass {sweep_pass + 1} found paipu #{len(extracted_paipus)}: {paipu_id}", file=sys.stderr)
                                # 立即輸出到 stdout
                                print(paipu_id, flush=True)
                            elif session_id:
                                processed_session_ids.add(session_id)

                    # Check if at bottom (with dynamic height verification)
                    current_pos = self.driver.execute_script("return window.pageYOffset;")
                    viewport_h = self.driver.execute_script("return window.innerHeight;")
                    page_h = self.driver.execute_script("return document.body.scrollHeight;")
                    if current_pos + viewport_h >= page_h - 50:
                        # Verify we're really at bottom
                        time.sleep(0.3)
                        new_page_h = self.driver.execute_script("return document.body.scrollHeight;")
                        if abs(new_page_h - page_h) < 100:
                            print(f"  Final sweep reached bottom", file=sys.stderr)
                            break
                        # If page height changed significantly, continue scanning

                    final_sweep_scroll += final_sweep_step
                    self.driver.execute_script(f"window.scrollTo(0, {final_sweep_scroll});")
                    # Trigger scroll event explicitly
                    self.driver.execute_script("window.dispatchEvent(new Event('scroll'));")
                    # Adjust wait time based on mode
                    if self.fast_mode:
                        time.sleep(0.3)  # Fast: adequate wait for processing
                    elif self.headless:
                        time.sleep(0.5)
                    else:
                        time.sleep(0.3)

                total_final_found += final_sweep_found
                print(f"  Sweep pass {sweep_pass + 1} completed: found {final_sweep_found} additional paipus", file=sys.stderr)

            print(f"All final sweeps completed: found {total_final_found} additional paipus total", file=sys.stderr)
            print(f"{'-'*60}\n", file=sys.stderr)

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
    fast_mode = False  # 快速模式：True=快速但可能漏5-10%, False=完整但较慢

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