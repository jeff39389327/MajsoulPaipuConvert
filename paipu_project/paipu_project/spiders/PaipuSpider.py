import scrapy
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
import re
import json
from dataclasses import dataclass
from typing import List, Dict

@dataclass
class CrawlerConfig:
    """爬蟲配置類"""
    # 時間段設定 (可選: "4w", "1w", "3d", "1d")
    time_periods: List[str]
    
    # 段位設定 (可選: "Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East", "All")
    ranks: List[str]
    
    # 每個時間段最多抓取的玩家數量
    max_players_per_period: int = 20
    
    # 牌譜數量限制參數
    paipu_limit: int = 9999
    
    # 輸出檔案名稱
    output_filename: str = "tonpuulist.txt"
    
    # 是否啟用無頭模式 (headless)
    headless_mode: bool = True
    
    # 是否儲存驗證截圖
    save_screenshots: bool = True

    @classmethod
    def from_json(cls, json_path: str):
        """從JSON檔案載入配置"""
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return cls(**data)
        except FileNotFoundError:
            print(f"配置檔案 {json_path} 不存在，使用預設配置")
            return cls.get_default_config()
    
    @classmethod
    def get_default_config(cls):
        """取得預設配置"""
        return cls(
            time_periods=["4w", "1w", "3d"],
            ranks=["Gold"],
            max_players_per_period=20,
            paipu_limit=9999,
            output_filename="tonpuulist.txt",
            headless_mode=True,
            save_screenshots=True
        )
    
    def save_to_json(self, json_path: str):
        """儲存配置到JSON檔案"""
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.__dict__, f, ensure_ascii=False, indent=2)
    
    def validate(self):
        """驗證配置的有效性"""
        valid_periods = ["4w", "1w", "3d", "1d"]
        valid_ranks = ["Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East", "All"]
        
        # 驗證時間段
        for period in self.time_periods:
            if period not in valid_periods:
                raise ValueError(f"無效的時間段: {period}。有效選項: {valid_periods}")
        
        # 驗證段位
        for rank in self.ranks:
            if rank not in valid_ranks:
                raise ValueError(f"無效的段位: {rank}。有效選項: {valid_ranks}")
        
        print("✅ 配置驗證通過")

def get_rank_display_name(rank: str) -> Dict[str, str]:
    """取得段位的顯示名稱對應"""
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
    """取得時間段的顯示名稱"""
    period_mapping = {
        "4w": "四週",
        "1w": "一週", 
        "3d": "三天",
        "1d": "一天"
    }
    return period_mapping.get(period, period)

def setup_rank_selection(driver, target_ranks: List[str]):
    """設定段位選擇"""
    all_available_ranks = ["Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East"]
    
    try:
        print("正在配置段位選擇...")
        
        # 如果選擇"全部"，直接使用網頁預設狀態（所有段位都已選中）
        if "All" in target_ranks:
            print("選擇全部段位 - 使用網頁預設狀態，無需點擊")
            print("網頁預設已選中所有段位，跳過段位選擇操作")
            return
        
        # 先取消選擇所有段位
        for rank in all_available_ranks:
            try:
                # 嘗試英文標籤
                rank_label = driver.find_element(By.XPATH, f"//span[contains(@class, 'MuiFormControlLabel-label') and text()='{rank}']")
                checkbox = rank_label.find_element(By.XPATH, "./preceding-sibling::span//input[@type='checkbox']")
                
                if checkbox.is_selected():
                    print(f"取消選擇段位: {rank}")
                    driver.execute_script("arguments[0].click();", rank_label)
                    time.sleep(0.5)
            except:
                # 嘗試中文標籤
                try:
                    chinese_rank = get_rank_display_name(rank)
                    rank_label = driver.find_element(By.XPATH, f"//span[contains(@class, 'MuiFormControlLabel-label') and text()='{chinese_rank}']")
                    checkbox = rank_label.find_element(By.XPATH, "./preceding-sibling::span//input[@type='checkbox']")
                    
                    if checkbox.is_selected():
                        print(f"取消選擇段位: {chinese_rank}")
                        driver.execute_script("arguments[0].click();", rank_label)
                        time.sleep(0.5)
                except:
                    continue
        
        # 選擇目標段位
        for rank in target_ranks:
            try:
                # 嘗試英文標籤
                rank_label = driver.find_element(By.XPATH, f"//span[contains(@class, 'MuiFormControlLabel-label') and text()='{rank}']")
                checkbox = rank_label.find_element(By.XPATH, "./preceding-sibling::span//input[@type='checkbox']")
                
                if not checkbox.is_selected():
                    print(f"選擇段位: {rank}")
                    driver.execute_script("arguments[0].click();", rank_label)
                    time.sleep(0.5)
                else:
                    print(f"段位 {rank} 已選中")
            except:
                # 嘗試中文標籤
                try:
                    chinese_rank = get_rank_display_name(rank)
                    rank_label = driver.find_element(By.XPATH, f"//span[contains(@class, 'MuiFormControlLabel-label') and text()='{chinese_rank}']")
                    checkbox = rank_label.find_element(By.XPATH, "./preceding-sibling::span//input[@type='checkbox']")
                    
                    if not checkbox.is_selected():
                        print(f"選擇段位: {chinese_rank}")
                        driver.execute_script("arguments[0].click();", rank_label)
                        time.sleep(0.5)
                    else:
                        print(f"段位 {chinese_rank} 已選中")
                except Exception as e:
                    print(f"無法選擇段位 {rank}: {e}")
        
        # 等待頁面更新
        time.sleep(3)
        print("段位選擇配置完成")
        
    except Exception as e:
        print(f"配置段位選擇時出錯: {e}")

def get_top_players_urls(config: CrawlerConfig):
    """根據配置自動抓取排行榜玩家的URLs"""
    chrome_options = Options()
    if config.headless_mode:
        chrome_options.add_argument("--headless")
    
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=chrome_options)
    
    all_player_urls = []
    
    try:
        # 存取排名頁面
        driver.get("https://amae-koromo.sapk.ch/ranking/delta")
        
        # 等待頁面載入完成
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        time.sleep(5)
        
        # 建立段位顯示字串
        rank_display = ", ".join([get_rank_display_name(rank) for rank in config.ranks])
        period_display = ", ".join([get_period_display_name(period) for period in config.time_periods])
        
        print(f"正在抓取汪汪榜排名")
        print(f"目標時間段: {period_display}")
        print(f"目標段位: {rank_display}")
        
        # 設定段位選擇
        setup_rank_selection(driver, config.ranks)
        
        # 儲存段位選擇驗證截圖
        if config.save_screenshots:
            driver.save_screenshot("screenshot_rank_selection_verification.png")
            print("已儲存段位選擇驗證截圖: screenshot_rank_selection_verification.png")
        
        # 處理每個時間段
        for period in config.time_periods:
            print(f"\n=== 開始處理時間段: {get_period_display_name(period)} ({period}) ===")
            
            try:
                # 查找並點擊對應的時間段radio按鈕
                print(f"查找時間段 {period} 的radio按鈕...")
                
                radio_button = driver.find_element(By.CSS_SELECTOR, f'input[type="radio"][value="{period}"]')
                print(f"找到 {period} 的radio按鈕")
                
                # 點擊radio按鈕
                driver.execute_script("arguments[0].click();", radio_button)
                print(f"已點擊 {period} 時間段")
                
                # 等待頁面更新
                time.sleep(5)
                
                # 儲存驗證截圖
                if config.save_screenshots:
                    rank_suffix = "_".join(config.ranks).lower()
                    screenshot_filename = f"screenshot_{period}_positive_ranking_{rank_suffix}.png"
                    driver.save_screenshot(screenshot_filename)
                    print(f"已儲存截圖: {screenshot_filename}")
                
            except Exception as e:
                print(f"切換到時間段 {period} 時出錯: {e}")
                continue
            
            # 取得該時間段的玩家連結
            period_player_urls = extract_positive_ranking_players(driver, period, config)
            all_player_urls.extend(period_player_urls)
            
            print(f"時間段 {period} 取得到 {len(period_player_urls)} 個玩家URL")
        
        # 去重處理
        unique_player_urls = []
        seen_players = set()
        
        for url in all_player_urls:
            player_id_match = re.search(r'/player/(\d+)', url)
            if player_id_match:
                player_id = player_id_match.group(1)
                if player_id not in seen_players:
                    seen_players.add(player_id)
                    unique_player_urls.append(url)
        
        print(f"共取得到 {len(unique_player_urls)} 個不重複的玩家URLs（/12模式）")
        
        if config.save_screenshots:
            print(f"\n📸 驗證截圖已儲存:")
            print(f"  - screenshot_rank_selection_verification.png (段位選擇驗證)")
            for period in config.time_periods:
                rank_suffix = "_".join(config.ranks).lower()
                print(f"  - screenshot_{period}_positive_ranking_{rank_suffix}.png ({get_period_display_name(period)})")
        
        return unique_player_urls
        
    except Exception as e:
        print(f"抓取排名時出錯: {e}")
        return []
    
    finally:
        driver.quit()

def extract_positive_ranking_players(driver, period, config: CrawlerConfig):
    """從Positive ranking列中提取玩家連結"""
    player_urls = []
    
    try:
        print(f"開始查找時間段 {period} 的Positive ranking列中的玩家連結...")
        
        # 方法1：嘗試查找Positive ranking列中的玩家連結
        player_links_in_positive = []
        
        try:
            positive_heading = driver.find_element(By.XPATH, "//*[contains(text(), 'Positive ranking')]")
            print("找到Positive ranking標題")
            
            positive_container = positive_heading.find_element(By.XPATH, "./following-sibling::*[1] | ./parent::*/following-sibling::*[1]")
            
            container_links = positive_container.find_elements(By.CSS_SELECTOR, "a[href*='/player/']")
            player_links_in_positive.extend(container_links)
            print(f"在Positive ranking容器中找到 {len(container_links)} 個玩家連結")
            
        except Exception as e:
            print(f"方法1失敗: {e}")
        
        # 方法2：如果方法1失敗，嘗試通過頁面佈局定位
        if not player_links_in_positive:
            try:
                print("嘗試方法2：通過頁面佈局定位Positive ranking...")
                
                all_player_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/player/']")
                
                for link in all_player_links:
                    try:
                        location = link.location
                        size = driver.get_window_size()
                        
                        if size['width'] * 0.33 < location['x'] < size['width'] * 0.66:
                            player_links_in_positive.append(link)
                    except:
                        continue
                
                print(f"方法2找到 {len(player_links_in_positive)} 個可能的Positive ranking連結")
                
            except Exception as e:
                print(f"方法2也失敗: {e}")
        
        # 方法3：如果前兩種方法都失敗，取得所有玩家連結並過濾
        if not player_links_in_positive:
            print("嘗試方法3：取得所有玩家連結...")
            all_links = driver.find_elements(By.TAG_NAME, "a")
            for link in all_links:
                href = link.get_attribute("href")
                if href and "/player/" in href:
                    player_links_in_positive.append(link)
            
            print(f"方法3找到 {len(player_links_in_positive)} 個玩家連結")
            if len(player_links_in_positive) >= 60:
                start_idx = len(player_links_in_positive) // 3
                end_idx = start_idx + config.max_players_per_period
                player_links_in_positive = player_links_in_positive[start_idx:end_idx]
                print(f"過濾後保留 {len(player_links_in_positive)} 個Positive ranking連結")
        
        # 提取指定數量的不重複玩家URL
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
                        print(f"添加玩家URL ({period}): {url}")
                        
                        if len(player_urls) >= config.max_players_per_period:
                            break
        
    except Exception as e:
        print(f"提取時間段 {period} 的玩家連結時出錯: {e}")
    
    return player_urls

def process_player(url, processed_paipu_ids, player_counts, config: CrawlerConfig):
    """處理單個玩家的牌譜抓取"""
    chrome_options = Options()
    if config.headless_mode:
        chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        time.sleep(2)

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
                        print(f"已寫入新的牌譜 ({url}):", paipu_id)
                        new_paipu_found = True
            
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(0.3)

            if driver.execute_script("return window.innerHeight + window.scrollY + 10 >= document.body.offsetHeight"):
                break
                
            if not new_paipu_found:
                time.sleep(1)

        print(f"玩家 {url} 收集到 {player_counts[url]} 個牌譜ID")
        
    except Exception as e:
        print(f"處理玩家 {url} 時出錯: {e}")
    finally:
        driver.quit()

class PaipuSpider(scrapy.Spider):
    name = "paipu_spider"

    def __init__(self, config_path: str = "crawler_config.json", use_manual_urls: bool = False):
        # 載入配置
        self.config = CrawlerConfig.from_json(config_path)
        self.config.validate()
        
        self.manager = multiprocessing.Manager()
        self.processed_paipu_ids = self.manager.list()
        
        # 決定使用自動化還是手動配置
        if use_manual_urls or hasattr(self, 'manual_player_urls'):
            print("🔧 使用 Legacy Manual 模式...")
            print("從程式碼中讀取手動設定的玩家URLs")
            
            # Legacy Manual URLs (在這裡手動添加玩家URLs)
            manual_urls = getattr(self, 'manual_player_urls', [
                # 在這裡添加手動玩家URLs，例如：
                # "https://amae-koromo.sapk.ch/player/123456/12?limit=9999",
                # "https://amae-koromo.sapk.ch/player/789012/12?limit=9999",
            ])
            
            if manual_urls:
                self.player_urls = manual_urls
                print(f"已載入 {len(self.player_urls)} 個手動設定的玩家URLs")
            else:
                print("⚠️  未找到手動設定的玩家URLs，切換到自動化模式")
                use_manual_urls = False
        
        if not use_manual_urls:
            print("🚀 使用自動化配置模式...")
            print(f"配置摘要:")
            print(f"  時間段: {[get_period_display_name(p) for p in self.config.time_periods]}")
            print(f"  段位: {[get_rank_display_name(r) for r in self.config.ranks]}")
            print(f"  每個時間段最多玩家數: {self.config.max_players_per_period}")
            print(f"  牌譜限制: {self.config.paipu_limit}")
            
            self.player_urls = get_top_players_urls(self.config)
        
        self.player_counts = self.manager.dict({url: 0 for url in self.player_urls})

        # 讀取已有的牌譜ID
        try:
            with open(self.config.output_filename, "r") as file:
                for line in file:
                    paipu_id = line.strip()
                    if paipu_id:
                        self.processed_paipu_ids.append(paipu_id)
            print(f"已載入 {len(self.processed_paipu_ids)} 個已處理的牌譜ID")
        except FileNotFoundError:
            print(f"未找到{self.config.output_filename}檔案，將建立新檔案")

    def start_requests(self):
        yield scrapy.Request(url="https://amae-koromo.sapk.ch", callback=self.start_crawling)

    def start_crawling(self, response):
        print(f"開始處理 {len(self.player_urls)} 個玩家...")
        
        processes = []
        for url in self.player_urls:
            process = multiprocessing.Process(target=process_player, args=(url, self.processed_paipu_ids, self.player_counts, self.config))
            processes.append(process)
            process.start()

        for process in processes:
            process.join()

        self.spider_closed(None)

    def spider_closed(self, reason):
        print(f"共收集到 {len(self.processed_paipu_ids)} 個不重複的牌譜ID")
        print("各玩家收集到的牌譜ID數量:")
        
        total_paipu = 0
        for url in self.player_urls:
            count = self.player_counts[url]
            total_paipu += count
            print(f"{url}: {count}")
        
        print(f"\n總計收集牌譜數量: {total_paipu}")
        
        # 顯示配置摘要
        print(f"\n📋 使用的配置:")
        print(f"  時間段: {', '.join([get_period_display_name(p) for p in self.config.time_periods])}")
        print(f"  段位: {', '.join([get_rank_display_name(r) for r in self.config.ranks])}")
        
        if self.config.save_screenshots:
            print(f"\n📸 驗證截圖已儲存:")
            print(f"  - screenshot_rank_selection_verification.png (段位選擇驗證)")
            for period in self.config.time_periods:
                rank_suffix = "_".join(self.config.ranks).lower()
                print(f"  - screenshot_{period}_positive_ranking_{rank_suffix}.png ({get_period_display_name(period)})")

        with ThreadPoolExecutor() as executor:
            executor.submit(self.write_to_file)

    def write_to_file(self):
        with open(self.config.output_filename, "w") as file:
            for paipu_id in self.processed_paipu_ids:
                file.write(paipu_id + "\n")
        print(f"牌譜ID已儲存到 {self.config.output_filename}")

# 建立預設配置檔案的函數
def create_default_config():
    """建立預設配置檔案"""
    config = CrawlerConfig.get_default_config()
    config.save_to_json("crawler_config.json")
    print("已建立預設配置檔案: crawler_config.json")
    return config

# ==========================================
# Legacy Manual 使用範例
# ==========================================

class ManualPaipuSpider(PaipuSpider):
    """手動配置玩家URLs的Spider類別"""
    
    def __init__(self):
        # 手動設定玩家URLs（Legacy方式）
        self.manual_player_urls = [
            "https://amae-koromo.sapk.ch/player/123456789/12?limit=9999",
            "https://amae-koromo.sapk.ch/player/987654321/12?limit=9999",
            "https://amae-koromo.sapk.ch/player/555666777/12?limit=9999",
            # 在這裡添加更多玩家URLs...
        ]
        
        # 呼叫父類初始化，啟用手動模式
        super().__init__(use_manual_urls=True)

# ==========================================
# 使用說明和執行方式
# ==========================================

if __name__ == "__main__":
    # 方式1：自動化配置模式（推薦）
    # 使用 crawler_config.json 配置檔案
    # 執行命令：scrapy crawl paipu_spider
    
    # 方式2：Legacy Manual 模式
    # 1. 修改上面的 manual_player_urls 列表
    # 2. 註冊新的spider：在 settings.py 或直接執行
    # 3. 執行命令：scrapy crawl manual_paipu_spider
    
    # 方式3：混合模式 - 在現有程式中直接設定
    # spider = PaipuSpider(use_manual_urls=True)
    # spider.manual_player_urls = ["URL1", "URL2", ...]
    
    # 如果配置檔案不存在，建立預設配置
    import os
    if not os.path.exists("crawler_config.json"):
        create_default_config()
        print("請編輯 crawler_config.json 來自訂您的抓取設定")
    else:
        print("發現現有配置檔案: crawler_config.json")