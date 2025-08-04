import asyncio
import json
import os
from tensoul import MajsoulPaipuDownloader
import time
from tqdm import tqdm

async def main():
    username = "kahalos674@kindomd.com"
    password = "48764876"
    batch_size = 1
    log_dir = r"mahjong_logs"  # 改為一般日誌目錄
    temp_file = "temp_ids.txt"

    # 建立儲存目錄
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 讀取需要下載的牌譜ID
    with open('a.txt', 'r', encoding='UTF-8') as f:
        ids = [line.strip() for line in f]
    
    # 檢查已存在的檔案
    existing_ids = set(os.path.splitext(filename)[0] for filename in os.listdir(log_dir) if filename.endswith(".json"))
    unique_ids = [id for id in ids if id not in existing_ids]
    total_unique_ids = len(unique_ids)

    # 儲存待下載的ID
    with open(temp_file, 'w', encoding='UTF-8') as f:
        f.write('\n'.join(unique_ids))

    print(f"需要下載的id數量: {total_unique_ids}")
    start_time_download = time.time()
    downloaded_bytes = 0

    # 下載牌譜
    async with MajsoulPaipuDownloader() as downloader:
        await downloader.login(username, password)
        
        with open(temp_file, 'r', encoding='UTF-8') as f:
            temp_ids = [line.strip() for line in f]

        with tqdm(total=total_unique_ids, desc="下載進度", unit="log") as download_progress:
            for i in range(0, total_unique_ids, batch_size):
                batch_ids = temp_ids[i:i+batch_size]
                
                # 下載批次牌譜
                download_tasks = [downloader.download(record_uuid) for record_uuid in batch_ids]
                logs_batch = await asyncio.gather(*download_tasks)
                
                # 過濾有效的牌譜
                valid_logs = [log for log in logs_batch if 'log' in log]
                valid_ids = [record_uuid for log, record_uuid in zip(logs_batch, batch_ids) if 'log' in log]
                
                # 儲存JSON檔案
                for log, record_uuid in zip(valid_logs, valid_ids):
                    output_path = f"{log_dir}/{record_uuid}.json"
                    with open(output_path, "w", encoding="utf-8") as f:
                        json.dump(log, f, ensure_ascii=False)
                    downloaded_bytes += os.path.getsize(output_path)
                
                download_progress.update(len(valid_ids))

    # 清理臨時檔案
    os.remove(temp_file)
    
    # 顯示完成訊息
    print(f"\n下載完成！")
    print(f"總共下載: {downloaded_bytes / 1024 / 1024:.2f} MB")
    print(f"耗時: {(time.time() - start_time_download):.2f} 秒")

asyncio.run(main())