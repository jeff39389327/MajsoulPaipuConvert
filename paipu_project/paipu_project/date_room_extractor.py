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

SLEEP_TIME = 0.2

class OptimizedPaipuExtractor:
    
    def __init__(self, headless=True):
        self.headless = headless
        self.driver = None
        self.setup_driver()
    
    def setup_driver(self):
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless")
        
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--enable-gpu")
        chrome_options.add_argument("--use-gl=desktop")
        chrome_options.add_argument("--enable-gpu-rasterization")
        chrome_options.add_argument("--enable-zero-copy")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
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
    
    def wait_for_table_load(self, max_wait=5):
        try:
            WebDriverWait(self.driver, max_wait).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".ReactVirtualized__Table__rowColumn"))
            )
            time.sleep(SLEEP_TIME)
            game_links = self.driver.find_elements(By.XPATH, "//a[contains(@title, 'View game')]")
            return len(game_links) > 0
        except:
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
            current_url = self.driver.current_url
            if '5-data.amae-koromo.com' in current_url:
                return current_url
            
            all_links = self.driver.find_elements(By.TAG_NAME, "a")
            for link in all_links:
                href = link.get_attribute('href')
                if href and '5-data.amae-koromo.com' in href and 'view_game' in href:
                    return href
            return None
        except:
            return None
    
    def extract_paipu_via_redirect(self, encrypted_api_url):
        try:
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response = session.get(encrypted_api_url, allow_redirects=True, timeout=10)
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
            table_rows = self.driver.find_elements(By.CSS_SELECTOR, ".ReactVirtualized__Table__row")
            
            for row in table_rows:
                try:
                    if not self.is_element_in_viewport(row):
                        continue
                    
                    columns = row.find_elements(By.CSS_SELECTOR, ".ReactVirtualized__Table__rowColumn")
                    
                    if len(columns) >= 4:
                        player_column = columns[1]
                        start_time_column = columns[2]
                        end_time_column = columns[3]
                        
                        player_links = player_column.find_elements(By.TAG_NAME, "a")
                        
                        if player_links:
                            start_time = start_time_column.get_attribute('title') or start_time_column.text.strip()
                            end_time = end_time_column.get_attribute('title') or end_time_column.text.strip()
                            
                            players = []
                            for link in player_links:
                                player_text = link.text.strip()
                                if player_text:
                                    players.append(player_text)
                            
                            if players and start_time and end_time:
                                temp_session_id = self.create_game_session_id(
                                    players, start_time, end_time, room_number
                                )
                                
                                if temp_session_id not in processed_session_ids:
                                    return {
                                        'row': row,
                                        'players': players,
                                        'start_time': start_time,
                                        'end_time': end_time,
                                        'first_link': player_links[0],
                                        'all_links': player_links,
                                        'session_id': temp_session_id
                                    }
                except:
                    continue
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
            
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", game_record['first_link'])
                time.sleep(0.2)
                self.driver.execute_script("arguments[0].click();", game_record['first_link'])
                time.sleep(SLEEP_TIME * 2)
            except:
                player_text = players[0]
                new_links = self.driver.find_elements(By.XPATH, f"//a[contains(text(), '{player_text}')]")
                if new_links:
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", new_links[0])
                    time.sleep(0.2)
                    self.driver.execute_script("arguments[0].click();", new_links[0])
                    time.sleep(SLEEP_TIME * 2)
                else:
                    return None, session_id
            
            api_url = self.find_5data_url_in_page()
            
            if api_url:
                raw_paipu_id = self.extract_paipu_via_redirect(api_url)
                if raw_paipu_id:
                    clean_paipu_id = self.clean_paipu_id(raw_paipu_id)
                    if clean_paipu_id and self.is_valid_paipu_id(clean_paipu_id):
                        try:
                            self.driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                            time.sleep(SLEEP_TIME * 2)
                        except:
                            self.driver.back()
                            time.sleep(SLEEP_TIME * 2)
                        
                        current_url = self.driver.current_url
                        if not ('amae-koromo.sapk.ch' in current_url and f'/{room_info["room_number"]}' in current_url):
                            self.driver.back()
                            time.sleep(SLEEP_TIME * 2)
                        
                        return clean_paipu_id, session_id
            
            try:
                self.driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
            except:
                self.driver.back()
            time.sleep(SLEEP_TIME * 2)
            
            return None, session_id
        except:
            try:
                self.driver.back()
                time.sleep(SLEEP_TIME * 2)
            except:
                pass
            return None, None
    
    def process_room_with_continuous_scroll(self, room_info, max_paipus=5):
        extracted_paipus = []
        processed_session_ids = set()
        
        try:
            self.driver.get(room_info['url'])
            
            if not self.wait_for_table_load():
                return []
            
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.3)
            
            scroll_position = 0
            scroll_step = 300
            max_scroll_attempts = 50
            consecutive_no_new = 0
            
            for scroll_count in range(max_scroll_attempts):
                if len(extracted_paipus) >= max_paipus:
                    break
                
                current_position = self.driver.execute_script("return window.pageYOffset;")
                viewport_height = self.driver.execute_script("return window.innerHeight;")
                page_height = self.driver.execute_script("return document.body.scrollHeight;")
                
                processed_any = False
                max_attempts_per_scroll = 10
                
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
                        elif session_id:
                            processed_session_ids.add(session_id)
                            processed_any = True
                    else:
                        break
                
                if not processed_any:
                    consecutive_no_new += 1
                    if consecutive_no_new >= 3:
                        break
                else:
                    consecutive_no_new = 0
                
                if current_position + viewport_height >= page_height - 50:
                    break
                
                scroll_position += scroll_step
                self.driver.execute_script(f"window.scrollTo(0, {scroll_position});")
                time.sleep(0.5)
            
            return extracted_paipus
            
        except:
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
            self.driver.quit()

def convert_ranks_to_english(chinese_ranks):
    rank_mapping = {
        "王座": "Throne", "玉": "Jade", "金": "Gold",
        "王东": "Throne East", "玉东": "Jade East", "金东": "Gold East",
        "Throne": "Throne", "Jade": "Jade", "Gold": "Gold",
        "Throne East": "Throne East", "Jade East": "Jade East", "Gold East": "Gold East"
    }
    return [rank_mapping.get(rank, rank) for rank in chinese_ranks]

def main():
    # 參數設定
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
        
        # 只輸出牌譜ID，每行一個
        for paipu in results:
            print(paipu)
        
    finally:
        extractor.close()

if __name__ == "__main__":
    main()