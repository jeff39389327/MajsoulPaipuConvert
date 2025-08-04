import asyncio
import json
import os
from tensoul import MajsoulPaipuDownloader
import gzip
import time
import subprocess
from tqdm import tqdm

async def process_log(record_uuid, log_data, base_dir):
    # 建立目錄
    mjai_dir = os.path.join(base_dir, "mjai")
    tenhou_dir = os.path.join(base_dir, "tenhou")
    os.makedirs(mjai_dir, exist_ok=True)
    os.makedirs(tenhou_dir, exist_ok=True)
    
    # 直接保存 tenhou 格式為 json
    try:
        tenhou_path = os.path.join(tenhou_dir, f"{record_uuid}.json")
        with open(tenhou_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving tenhou format for {record_uuid}: {str(e)}")
        return

    # 暫存檔案用於 mjai 轉換
    temp_file = f"temp_logs/{record_uuid}.json"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving temp file for {record_uuid}: {str(e)}")
        return

    # 轉換為 mjai 格式
    try:
        mjai_cmd = f'mjai-reviewer --no-review -i {temp_file} --mjai-out temp_logs/{record_uuid}_mjai.json'
        mjai_result = subprocess.run(mjai_cmd, shell=True, capture_output=True, text=True)
        if mjai_result.returncode != 0:
            print(f"Warning: mjai conversion failed for {record_uuid}")
            print(f"Error: {mjai_result.stderr}")
    except Exception as e:
        print(f"Error executing mjai-reviewer: {str(e)}")

    # 保存 mjai 格式 (gzip 壓縮)
    mjai_temp = f"temp_logs/{record_uuid}_mjai.json"
    if os.path.exists(mjai_temp):
        try:
            with open(mjai_temp, "rb") as f_in:
                with gzip.open(f"{mjai_dir}/{record_uuid}.json.gz", "wb") as f_out:
                    f_out.writelines(f_in)
        except Exception as e:
            print(f"Error saving mjai format for {record_uuid}: {str(e)}")

    # 清理臨時檔案
    try:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        if os.path.exists(mjai_temp):
            os.remove(mjai_temp)
    except Exception as e:
        print(f"Error cleaning temp files for {record_uuid}: {str(e)}")

    await asyncio.sleep(0.1)

async def main():
    username = "cohipi3374@nausard.com"
    password = "48764876"
    batch_size = 1
    base_dir = "mahjong_logs"
    temp_dir = "temp_logs"
    temp_file = "temp_ids.txt"
    
    # 建立必要的目錄
    os.makedirs(base_dir, exist_ok=True)
    os.makedirs(os.path.join(base_dir, "mjai"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "tenhou"), exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    # 讀取牌譜 ID
    with open('tonpuulist.txt', 'r', encoding='UTF-8') as f:
        ids = [line.strip() for line in f]
    
    # 檢查已存在的檔案
    tenhou_existing = set()
    tenhou_dir = os.path.join(base_dir, "tenhou")
    if os.path.exists(tenhou_dir):
        tenhou_existing = set(os.path.splitext(filename)[0] 
                            for filename in os.listdir(tenhou_dir) 
                            if filename.endswith(".json"))
    
    unique_ids = [id for id in ids if id not in tenhou_existing]
    total_unique_ids = len(unique_ids)
    
    print(f"需要下載的id數量: {total_unique_ids}")
    
    if total_unique_ids == 0:
        print("沒有新的牌譜需要下載")
        return
        
    with open(temp_file, 'w', encoding='UTF-8') as f:
        f.write('\n'.join(unique_ids))
    
    # 下載和處理牌譜
    async with MajsoulPaipuDownloader() as downloader:
        await downloader.login(username, password)
        
        with open(temp_file, 'r', encoding='UTF-8') as f:
            temp_ids = [line.strip() for line in f]
            
        print("開始下載牌譜...")
        downloaded_ids = []
        with tqdm(total=total_unique_ids, desc="下載進度", unit="log") as download_progress:
            for i in range(0, total_unique_ids, batch_size):
                batch_ids = temp_ids[i:i+batch_size]
                
                # 下載牌譜
                download_tasks = [downloader.download(record_uuid) for record_uuid in batch_ids]
                logs_batch = await asyncio.gather(*download_tasks)
                
                # 處理每個下載的牌譜
                for log, record_uuid in zip(logs_batch, batch_ids):
                    if 'log' in log:
                        await process_log(record_uuid, log, base_dir)
                        downloaded_ids.append(record_uuid)
                        download_progress.update(1)
    
    # 清理臨時檔案
    print("\n清理臨時檔案...")
    os.remove(temp_file)
    if os.path.exists(temp_dir):
        for file in os.listdir(temp_dir):
            os.remove(os.path.join(temp_dir, file))
        os.rmdir(temp_dir)
    
    print("全部處理完成！")

if __name__ == "__main__":
    asyncio.run(main())