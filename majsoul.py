import asyncio
import json
import os
from tensoul import MajsoulPaipuDownloader
import gzip
import time
from rich.progress import Progress
import subprocess

async def process_log(record_uuid):
    cmd = f'mjai-reviewer --no-review -i new_log/{record_uuid}.json --mjai-out new_log/{record_uuid}.json'
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if os.path.exists(f"new_log/{record_uuid}.json"):
        with open(f"new_log/{record_uuid}.json", "rb") as f_in:
            with gzip.open(f"log/{record_uuid}.json.gz", "wb") as f_out:
                f_out.writelines(f_in)
        os.remove(f"new_log/{record_uuid}.json")
        await asyncio.sleep(0.1)

async def main():
    username = "bivide8594@bsomek.com"
    password = "12345678"
    batch_size = 1
    log_dir = r"log"
    new_log_dir = r"new_log"
    temp_file = "temp_ids.txt"

    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    if not os.path.exists(new_log_dir):
        os.makedirs(new_log_dir)

    with open('list.txt', 'r', encoding='UTF-8') as f:
        ids = [line.strip() for line in f]

    total_ids = len(ids)

    existing_ids = set(os.path.splitext(os.path.splitext(filename)[0])[0] for filename in os.listdir(log_dir) if filename.endswith(".json.gz"))
    unique_ids = [id for id in ids if id not in existing_ids]
    total_unique_ids = len(unique_ids)

    with open(temp_file, 'w', encoding='UTF-8') as f:
        f.write('\n'.join(unique_ids))

    print(f"需要下載的id數量: {total_unique_ids}")

    start_time_download = time.time()
    start_time_process = time.time()
    downloaded_bytes = 0

    async with MajsoulPaipuDownloader() as downloader:
        await downloader.login(username, password)
        
        with Progress() as progress:
            download_task = progress.add_task("[cyan]下載進度", total=total_unique_ids)
            process_task = progress.add_task("[magenta]轉換進度", total=total_unique_ids)

            with open(temp_file, 'r', encoding='UTF-8') as f:
                temp_ids = [line.strip() for line in f]

            for i in range(0, total_unique_ids, batch_size):
                batch_ids = temp_ids[i:i+batch_size]
                
                download_tasks = [downloader.download(record_uuid) for record_uuid in batch_ids]
                logs_batch = await asyncio.gather(*download_tasks)
                
                valid_logs = [log for log in logs_batch if 'log' in log]
                valid_ids = [record_uuid for log, record_uuid in zip(logs_batch, batch_ids) if 'log' in log]
                
                for log, record_uuid in zip(valid_logs, valid_ids):
                    with open(f"new_log/{record_uuid}.json", "w", encoding="utf-8") as f:
                        json.dump(log, f, ensure_ascii=False)
                    downloaded_bytes += os.path.getsize(f"new_log/{record_uuid}.json")
                
                progress.update(download_task, advance=len(valid_ids))
                
                process_tasks = [process_log(record_uuid) for record_uuid in valid_ids if record_uuid+'.json' in os.listdir(new_log_dir)]
                await asyncio.gather(*process_tasks)
                
                progress.update(process_task, advance=len(process_tasks))

    os.remove(temp_file)

asyncio.run(main())