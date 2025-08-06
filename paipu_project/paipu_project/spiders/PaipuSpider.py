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
from datetime import datetime, timedelta
import subprocess
import sys
import os
import tempfile

@dataclass
class CrawlerConfig:
    """爬蟲配置類"""
    # 爬蟲模式選擇: "auto", "manual", 或 "date_room"
    crawler_mode: str = "auto"
    
    # 手動模式：玩家URLs列表 (當 crawler_mode = "manual" 時使用)
    manual_player_urls: List[str] = None
    
    # 自動模式：時間段設定 (可選: "4w", "1w", "3d", "1d")
    time_periods: List[str] = None
    
    # 自動模式：段位設定 (可選: "Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East", "All")
    ranks: List[str] = None
    
    # 每個時間段最多抓取的玩家數量
    max_players_per_period: int = 20
    
    # 牌譜數量限制參數
    paipu_limit: int = 9999
    
    # date_room模式：日期區間和目標房間
    start_date: str = None  # 格式: "2019-08-20"
    end_date: str = None    # 格式: "2019-08-23"
    target_room: str = None # 可選: "Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East"
    
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
        """儲存配置到JSON檔案"""
        # 處理 None 值，轉換為空列表以便於JSON序列化
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
        """驗證配置的有效性"""
        valid_modes = ["auto", "manual", "date_room"]
        valid_periods = ["4w", "1w", "3d", "1d"]
        valid_ranks = ["Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East", "All"]
        valid_rooms = ["Throne", "Jade", "Gold", "Throne East", "Jade East", "Gold East"]
        
        # 驗證爬蟲模式
        if self.crawler_mode not in valid_modes:
            raise ValueError(f"無效的爬蟲模式: {self.crawler_mode}。有效選項: {valid_modes}")
        
        # 根據模式驗證對應參數
        if self.crawler_mode == "manual":
            if not self.manual_player_urls or len(self.manual_player_urls) == 0:
                raise ValueError("手動模式需要提供 manual_player_urls")
            print(f"✅ 手動模式配置驗證通過 - 已設定 {len(self.manual_player_urls)} 個玩家URLs")
            
        elif self.crawler_mode == "auto":
            if not self.time_periods or len(self.time_periods) == 0:
                raise ValueError("自動模式需要提供 time_periods")
            if not self.ranks or len(self.ranks) == 0:
                raise ValueError("自動模式需要提供 ranks")
                
            # 驗證時間段
            for period in self.time_periods:
                if period not in valid_periods:
                    raise ValueError(f"無效的時間段: {period}。有效選項: {valid_periods}")
            
            # 驗證段位
            for rank in self.ranks:
                if rank not in valid_ranks:
                    raise ValueError(f"無效的段位: {rank}。有效選項: {valid_ranks}")
            
            print(f"✅ 自動模式配置驗證通過")
            
        elif self.crawler_mode == "date_room":
            # 驗證日期格式和必要參數
            if not self.start_date or not self.end_date:
                raise ValueError("date_room模式需要提供 start_date 和 end_date")
            if not self.target_room:
                raise ValueError("date_room模式需要提供 target_room")
                
            # 驗證日期格式
            try:
                start = datetime.strptime(self.start_date, "%Y-%m-%d")
                end = datetime.strptime(self.end_date, "%Y-%m-%d")
                if start > end:
                    raise ValueError("start_date 不能晚於 end_date")
            except ValueError as e:
                raise ValueError(f"日期格式錯誤（應為YYYY-MM-DD）: {e}")
            
            # 驗證房間
            if self.target_room not in valid_rooms:
                raise ValueError(f"無效的房間: {self.target_room}。有效選項: {valid_rooms}")
            
            print(f"✅ date_room模式配置驗證通過")
            print(f"  日期範圍: {self.start_date} 到 {self.end_date}")
            print(f"  目標房間: {self.target_room}")
        
        print("✅ 總體配置驗證通過")

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

def execute_date_room_extractor_py(target_date: str, target_room: str, headless_mode: bool = True) -> List[str]:
    """
    執行date_room_extractor.py並獲取其輸出的牌譜ID列表
    
    Args:
        target_date: 目標日期 (格式: "2019-08-23")
        target_room: 目標房間 (如: "Throne", "Jade", "Gold" 等)
        headless_mode: 是否使用無頭模式
        
    Returns:
        牌譜ID列表
    """
    # 創建臨時的date_room_extractor.py修改版本
    temp_script = """
import sys
sys.path.insert(0, '.')
from date_room_extractor import OptimizedPaipuExtractor, convert_ranks_to_english

def main():
    # 參數設定
    target_date = "{target_date}"
    target_ranks = ["{target_room}"]
    max_paipus = 99999
    headless_mode = {headless_mode}
    
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
""".format(
        target_date=target_date,
        target_room=target_room,
        headless_mode=str(headless_mode)
    )
    
    # 創建臨時檔案
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as temp_file:
        temp_file.write(temp_script)
        temp_file_path = temp_file.name
    
    try:
        # 執行臨時腳本
        result = subprocess.run(
            [sys.executable, temp_file_path],
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        
        if result.returncode != 0:
            print(f"執行date_room_extractor.py時出錯: {result.stderr}")
            return []
        
        # 解析輸出，每行一個牌譜ID
        paipu_ids = []
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            # 過濾掉非牌譜ID的輸出（如print的調試信息）
            if line and re.match(r'^[0-9]{6}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', line):
                paipu_ids.append(line)
        
        return paipu_ids
        
    finally:
        # 刪除臨時檔案
        try:
            os.unlink(temp_file_path)
        except:
            pass

def collect_paipus_by_date_room(config: CrawlerConfig) -> List[str]:
    """使用date_room模式收集牌譜"""
    all_paipus = []
    
    try:
        # 解析日期範圍
        start_date = datetime.strptime(config.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(config.end_date, "%Y-%m-%d")
        
        # 計算總天數
        total_days = (end_date - start_date).days + 1
        print(f"\n=== 開始 date_room 模式收集 ===")
        print(f"日期範圍: {config.start_date} 到 {config.end_date} (共 {total_days} 天)")
        print(f"目標房間: {config.target_room}")
        print(f"無頭模式: {config.headless_mode}")
        print("="*50)
        
        # 處理每一天
        current_date = start_date
        day_count = 0
        
        while current_date <= end_date:
            day_count += 1
            date_str = current_date.strftime("%Y-%m-%d")
            print(f"\n[{day_count}/{total_days}] 正在處理日期: {date_str}")
            
            # 執行date_room_extractor.py獲取當天的牌譜
            day_results = execute_date_room_extractor_py(
                target_date=date_str,
                target_room=config.target_room,
                headless_mode=config.headless_mode
            )
            
            # 添加到總列表（date_room_extractor.py已經去重，但這裡再次確保跨日期的去重）
            for paipu in day_results:
                if paipu not in all_paipus:
                    all_paipus.append(paipu)
            
            print(f"  ✓ {date_str} 收集到 {len(day_results)} 個牌譜")
            print(f"  累計收集: {len(all_paipus)} 個不重複牌譜")
            
            # 移到下一天
            current_date += timedelta(days=1)
            
            # 如果不是最後一天，稍微等待一下
            if current_date <= end_date:
                time.sleep(1)
        
        print(f"\n=== date_room 模式收集完成 ===")
        print(f"總計收集到 {len(all_paipus)} 個不重複的牌譜ID")
        
    except Exception as e:
        print(f"date_room模式執行出錯: {e}")
        import traceback
        traceback.print_exc()
    
    return all_paipus

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

    def __init__(self, config_path: str = "crawler_config.json"):
        # 載入配置
        self.config = CrawlerConfig.from_json(config_path)
        self.config.validate()
        
        self.manager = multiprocessing.Manager()
        self.processed_paipu_ids = self.manager.list()
        
        # 根據配置模式決定使用方式
        if self.config.crawler_mode == "manual":
            print("🔧 使用 Manual 模式（Legacy相容）...")
            print(f"從配置檔案中讀取 {len(self.config.manual_player_urls)} 個手動設定的玩家URLs")
            
            # 使用配置檔案中的手動URLs
            self.player_urls = []
            for url in self.config.manual_player_urls:
                # 確保URL格式正確，添加limit參數
                if "/player/" in url and "?limit=" not in url:
                    url = f"{url}?limit={self.config.paipu_limit}"
                elif "/player/" in url and "?limit=" in url:
                    # URL已經有limit參數，使用原始URL
                    pass
                else:
                    print(f"⚠️  跳過無效的URL格式: {url}")
                    continue
                self.player_urls.append(url)
            
            print(f"已載入 {len(self.player_urls)} 個有效的玩家URLs")
            self.player_counts = self.manager.dict({url: 0 for url in self.player_urls})
            
        elif self.config.crawler_mode == "date_room":
            print("📅 使用 date_room 模式...")
            # date_room模式不需要player_urls
            self.player_urls = []
            self.player_counts = self.manager.dict()
            
        else:  # auto mode
            print("🚀 使用自動化配置模式...")
            print(f"配置摘要:")
            print(f"  時間段: {[get_period_display_name(p) for p in self.config.time_periods]}")
            print(f"  段位: {[get_rank_display_name(r) for r in self.config.ranks]}")
            print(f"  每個時間段最多玩家數: {self.config.max_players_per_period}")
            print(f"  牌譜限制: {self.config.paipu_limit}")
            
            self.player_urls = get_top_players_urls(self.config)
            self.player_counts = self.manager.dict({url: 0 for url in self.player_urls})

        # 讀取已有的牌譜ID（所有模式都需要）
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
        if self.config.crawler_mode == "date_room":
            # date_room模式：直接調用收集函數
            date_room_paipus = collect_paipus_by_date_room(self.config)
            
            # 添加到processed_paipu_ids中（避免重複）
            for paipu_id in date_room_paipus:
                if paipu_id not in self.processed_paipu_ids:
                    self.processed_paipu_ids.append(paipu_id)
            
            # 直接結束
            self.spider_closed(None)
            
        else:
            # 原有的auto和manual模式處理
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
        
        if self.config.crawler_mode == "date_room":
            print("\n📋 date_room模式配置摘要:")
            print(f"  日期範圍: {self.config.start_date} 到 {self.config.end_date}")
            print(f"  目標房間: {self.config.target_room}")
        else:
            print("各玩家收集到的牌譜ID數量:")
            
            total_paipu = 0
            for url in self.player_urls:
                count = self.player_counts[url]
                total_paipu += count
                print(f"{url}: {count}")
            
            print(f"\n總計收集牌譜數量: {total_paipu}")
            
            # 顯示配置摘要
            if self.config.crawler_mode == "auto":
                print(f"\n📋 使用的配置:")
                print(f"  時間段: {', '.join([get_period_display_name(p) for p in self.config.time_periods])}")
                print(f"  段位: {', '.join([get_rank_display_name(r) for r in self.config.ranks])}")
        
        if self.config.save_screenshots and self.config.crawler_mode == "auto":
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

# 建立date_room模式的範例配置
def create_date_room_config_example():
    """建立date_room模式的範例配置檔案"""
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
    print("已建立date_room模式範例配置檔案: date_room_config_example.json")
    return config

# ==========================================
# 使用說明和執行方式
# ==========================================

if __name__ == "__main__":
    # 方式1：自動化配置模式（推薦）
    # 在 crawler_config.json 中設定：
    # {
    #   "crawler_mode": "auto",
    #   "time_periods": ["4w", "1w", "3d"],
    #   "ranks": ["Gold"],
    #   ...
    # }
    # 執行命令：scrapy crawl paipu_spider
    
    # 方式2：手動模式（Legacy Manual 相容）
    # 在 crawler_config.json 中設定：
    # {
    #   "crawler_mode": "manual",
    #   "manual_player_urls": [
    #     "https://amae-koromo.sapk.ch/player/123456/12",
    #     "https://amae-koromo.sapk.ch/player/789012/12"
    #   ],
    #   ...
    # }
    # 執行命令：scrapy crawl paipu_spider
    
    # 方式3：date_room模式（新增）
    # 在 crawler_config.json 中設定：
    # {
    #   "crawler_mode": "date_room",
    #   "start_date": "2019-08-20",
    #   "end_date": "2019-08-23",
    #   "target_room": "Jade",
    #   "output_filename": "list.txt",
    #   "headless_mode": true,
    #   "save_screenshots": true
    # }
    # 執行命令：scrapy crawl paipu_spider
    
    # 如果配置檔案不存在，建立預設配置
    import os
    if not os.path.exists("crawler_config.json"):
        create_default_config()
        print("已建立預設配置檔案: crawler_config.json")
        print("請編輯配置檔案來自訂您的抓取設定")
        print("\n📋 可用的配置模式:")
        print("  - crawler_mode: 'auto' (自動化)")
        print("  - crawler_mode: 'manual' (手動)")
        print("  - crawler_mode: 'date_room' (日期房間模式)")
        print("  - 詳細設定請參考配置檔案中的範例")
        
        # 同時建立date_room模式的範例
        if not os.path.exists("date_room_config_example.json"):
            create_date_room_config_example()
    else:
        print("發現現有配置檔案: crawler_config.json")