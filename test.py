import asyncio
import json
import os
import sys
import gzip
import time
from rich.progress import Progress
import dotenv

# 添加 standard-mjlog-converter 路徑
sys.path.append('standard-mjlog-converter-main/standard-mjlog-converter-main')
from py_mjlog_converter.fetch.majsoul import MahjongSoulAPI, fetch_majsoul

def convert_protobuf_to_dict(obj):
    """將 protobuf 對象轉換為可序列化的字典"""
    if hasattr(obj, 'DESCRIPTOR'):
        # 使用 MessageToDict 轉換 protobuf 對象
        from google.protobuf.json_format import MessageToDict
        return MessageToDict(obj, preserving_proto_field_name=True)
    elif isinstance(obj, (list, tuple)):
        return [convert_protobuf_to_dict(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: convert_protobuf_to_dict(value) for key, value in obj.items()}
    else:
        return obj

async def download_single_log(record_uuid, username, password):
    """使用 standard-mjlog-converter 下載單個牌譜"""
    try:
        # 構建牌譜連結
        link = f"https://maj-soul.com/?paipu={record_uuid}"
        
        # 使用 MahjongSoulAPI 下載
        async with MahjongSoulAPI(mjs_username=username, mjs_password=password) as api:
            actions, metadata, player, identifier = await fetch_majsoul(link)
            # 轉換 protobuf 對象為可序列化格式
            serializable_actions = convert_protobuf_to_dict(actions)
            serializable_metadata = convert_protobuf_to_dict(metadata)
            return {"log": serializable_actions, "metadata": serializable_metadata, "player": player, "identifier": identifier}
    except Exception as e:
        print(f"下載牌譜 {record_uuid} 失敗: {str(e)}")
        return None

async def main():
    # 載入環境變數
    dotenv.load_dotenv("config.env")
    
    username = os.getenv("ms_username", "bivide8594@bsomek.com")
    password = os.getenv("ms_password", "12345678")
    batch_size = 1
    log_dir = r"3m"
    temp_file = "temp_ids.txt"

    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    with open('3m.txt', 'r', encoding='UTF-8') as f:
        ids = [line.strip() for line in f]

    total_ids = len(ids)

    existing_ids = set(os.path.splitext(os.path.splitext(filename)[0])[0] for filename in os.listdir(log_dir) if filename.endswith(".json.gz"))
    unique_ids = [id for id in ids if id not in existing_ids]
    total_unique_ids = len(unique_ids)

    with open(temp_file, 'w', encoding='UTF-8') as f:
        f.write('\n'.join(unique_ids))

    print(f"需要下載的id數量: {total_unique_ids}")

    start_time_download = time.time()
    downloaded_bytes = 0

    with Progress() as progress:
        download_task = progress.add_task("[cyan]下載進度", total=total_unique_ids)

        with open(temp_file, 'r', encoding='UTF-8') as f:
            temp_ids = [line.strip() for line in f]

        for i in range(0, total_unique_ids, batch_size):
            batch_ids = temp_ids[i:i+batch_size]
            
            download_tasks = [download_single_log(record_uuid, username, password) for record_uuid in batch_ids]
            logs_batch = await asyncio.gather(*download_tasks)
            
            valid_logs = [log for log in logs_batch if log and 'log' in log]
            valid_ids = [record_uuid for log, record_uuid in zip(logs_batch, batch_ids) if log and 'log' in log]
            
            for log, record_uuid in zip(valid_logs, valid_ids):
                with gzip.open(f"3m/{record_uuid}.json.gz", "wt", encoding="utf-8") as f:
                    json.dump(log, f, ensure_ascii=False)
                downloaded_bytes += os.path.getsize(f"3m/{record_uuid}.json.gz")
            
            progress.update(download_task, advance=len(valid_ids))

    os.remove(temp_file)

asyncio.run(main())
