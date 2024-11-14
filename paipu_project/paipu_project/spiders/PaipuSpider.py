import scrapy
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
#scrapy crawl  paipu_spider
def process_player(url, processed_paipu_ids, player_counts):
    # 创建一个隐藏的Chrome WebDriver实例
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # 设置为无头模式
    driver = webdriver.Chrome(options=chrome_options)
    driver.get(url)

    # 等待页面加载完成
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a.MuiTypography-root.MuiTypography-inherit.MuiLink-root.MuiLink-underlineHover.css-17xi075"))
    )

    while True:
        # 提取当前页面上的牌谱链接
        paipu_links = driver.find_elements(By.CSS_SELECTOR, "a.MuiTypography-root.MuiTypography-inherit.MuiLink-root.MuiLink-underlineHover.css-17xi075")

        # 处理找到的牌谱链接
        for link in paipu_links:
            href = link.get_attribute("href")
            if "paipu=" in href:
                paipu_id = href.split("paipu=")[1].split("_")[0]
                
                # 检查是否已处理过该paipu参数值
                if paipu_id not in processed_paipu_ids:
                    processed_paipu_ids.append(paipu_id)
                    player_counts[url] += 1
                    print(f"已寫入新的牌譜 ({url}):", paipu_id)
                else:
                    continue
        
        # 滚动页面一定距离(例如400像素)
        driver.execute_script("window.scrollBy(0, 500);")
        # 等待页面加载新的牌谱数据
        time.sleep(0.3)

        # 检查是否滚动到页面底部(添加容差值)
        if driver.execute_script("return window.innerHeight + window.scrollY + 10 >= document.body.offsetHeight"):
            break

    print(f"玩家 {url} 收集到 {player_counts[url]} 個牌譜ID")
    driver.quit()

class PaipuSpider(scrapy.Spider):
    name = "paipu_spider"
    player_urls = [
        "https://amae-koromo.sapk.ch/player/118984954/12",


    ]

    def __init__(self):
        self.manager = multiprocessing.Manager()
        self.processed_paipu_ids = self.manager.list()
        self.player_counts = self.manager.dict({url: 0 for url in self.player_urls})

        # 读取已有的牌谱ID
        try:
            with open("tonpuulist.txt", "r") as file:
                for line in file:
                    paipu_id = line.strip()
                    self.processed_paipu_ids.append(paipu_id)
        except FileNotFoundError:
            pass

    def start_requests(self):
        # 返回一个虚拟的请求对象,以满足Scrapy的要求
        yield scrapy.Request(url="https://amae-koromo.sapk.ch", callback=self.start_crawling)

    def start_crawling(self, response):
        processes = []
        for url in self.player_urls:
            process = multiprocessing.Process(target=process_player, args=(url, self.processed_paipu_ids, self.player_counts))
            processes.append(process)
            process.start()

        for process in processes:
            process.join()

        # 爬取完成后调用`spider_closed`方法
        self.spider_closed(None)

    def spider_closed(self, reason):
        print(f"共收集到 {len(self.processed_paipu_ids)} 個不重複的牌譜ID")
        print("各玩家收集到的牌譜ID數量:")
        for url in self.player_urls:
            print(f"{url}: {self.player_counts[url]}")

        # 使用多线程加速文件写入
        with ThreadPoolExecutor() as executor:
            executor.submit(self.write_to_file)

    def write_to_file(self):
        with open("tonpuulist.txt", "w") as file:
            for paipu_id in self.processed_paipu_ids:
                file.write(paipu_id + "\n")
