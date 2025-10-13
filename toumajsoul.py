import asyncio
import json
import os
import sys
import gzip
import time
import subprocess
from tqdm import tqdm
import dotenv
from google.protobuf import json_format

# 添加 tensoul-py-ng 路徑
sys.path.append('tensoul-py-ng')
from tensoul import MajsoulPaipuDownloader
import ms.protocol_pb2 as pb

def extract_timing_data(raw_details):
    """從原始數據中提取思考時間"""
    import base64
    
    timing_map = {}  # key: (actor, action_seq) -> think_ms
    
    actions = raw_details.get('actions', [])
    last_deal_time = {}  # 記錄每個玩家收到牌的時間（發牌時間）
    action_seq = {0: 0, 1: 0, 2: 0, 3: 0}  # 每個玩家的動作序號
    last_global_event = 0  # 最後一個全局事件時間
    
    for i, action in enumerate(actions):
        current_time = action.get('passed', 0)
        action_type = action.get('type')
        
        # type 1: 系統事件（發牌等）- 需要解析是發給哪個玩家
        if action_type == 1 and 'result' in action:
            last_global_event = current_time
            try:
                # 解析 protobuf 數據
                result_bytes = base64.b64decode(action['result'])
                wrapper = pb.Wrapper()
                wrapper.ParseFromString(result_bytes)
                
                # 判斷是否為發牌事件
                if 'RecordDealTile' in wrapper.name:
                    deal_tile = pb.RecordDealTile()
                    deal_tile.ParseFromString(wrapper.data)
                    seat = deal_tile.seat
                    # 記錄該玩家收到牌的時間
                    last_deal_time[seat] = current_time
            except Exception as e:
                # 解析失敗，跳過
                pass
        
        # type 2: 玩家操作
        elif action_type == 2 and 'user_input' in action:
            user_input = action['user_input']
            seat = user_input.get('seat', 0)
            
            # 打牌操作
            if user_input.get('type') == 2 and 'operation' in user_input:
                # 計算思考時間：從收到牌到打牌
                if seat in last_deal_time:
                    think_ms = current_time - last_deal_time[seat]
                else:
                    # 開局第一個動作：從上一個全局事件（可能是配牌完成）算起
                    # 使用 passed 本身作為基準
                    think_ms = current_time - last_global_event if last_global_event > 0 else current_time
                
                # 記錄：(玩家, 動作序號) -> 思考時間
                timing_map[(seat, action_seq[seat])] = think_ms
                action_seq[seat] += 1
                
                # 清除該玩家的發牌記錄（已經使用過了）
                if seat in last_deal_time:
                    del last_deal_time[seat]
            
            # 鳴牌操作（chi/pon/kan）
            elif user_input.get('type') == 3 and 'cpg' in user_input:
                cpg = user_input['cpg']
                if not cpg.get('cancel_operation'):
                    # 鳴牌的思考時間：從上一個玩家打牌（或發牌）到現在
                    think_ms = 0
                    for j in range(i-1, -1, -1):
                        prev_action = actions[j]
                        # 找到前一個有 passed 時間的事件
                        if 'passed' in prev_action:
                            think_ms = current_time - prev_action['passed']
                            break
                    
                    timing_map[(seat, action_seq[seat])] = think_ms
                    action_seq[seat] += 1
    
    return timing_map

def inject_timing_to_mjai(mjai_file, timing_map):
    """在 mjai 格式中注入思考時間"""
    if not os.path.exists(mjai_file):
        return
    
    action_seq = {0: 0, 1: 0, 2: 0, 3: 0}
    output_lines = []
    
    with open(mjai_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            event = json.loads(line)
            event_type = event.get('type')
            
            # 需要添加思考時間的動作類型
            if event_type in ['dahai', 'reach']:
                actor = event.get('actor')
                if actor is not None:
                    key = (actor, action_seq[actor])
                    if key in timing_map:
                        event['think_ms'] = timing_map[key]
                    action_seq[actor] += 1
            
            elif event_type in ['chi', 'pon', 'daiminkan', 'kakan', 'ankan']:
                actor = event.get('actor')
                if actor is not None:
                    key = (actor, action_seq[actor])
                    if key in timing_map:
                        event['think_ms'] = timing_map[key]
                    action_seq[actor] += 1
            
            output_lines.append(json.dumps(event, ensure_ascii=False))
    
    # 寫回文件
    with open(mjai_file, 'w', encoding='utf-8') as f:
        for line in output_lines:
            f.write(line + '\n')

async def process_log(record_uuid, log_data, base_dir, raw_timing_data=None):
    # 建立目錄
    mjai_dir = os.path.join(base_dir, "mjai")
    tenhou_dir = os.path.join(base_dir, "tenhou")
    os.makedirs(mjai_dir, exist_ok=True)
    os.makedirs(tenhou_dir, exist_ok=True)
    
    # log_data 已經是 tenhou.net/6 格式的字典，直接保存
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

    # 如果有思考時間數據，注入到 mjai
    mjai_temp = f"temp_logs/{record_uuid}_mjai.json"
    if os.path.exists(mjai_temp) and raw_timing_data:
        try:
            timing_map = extract_timing_data(raw_timing_data)
            inject_timing_to_mjai(mjai_temp, timing_map)
        except Exception as e:
            print(f"Warning: Failed to inject timing data: {str(e)}")
    
    # 保存 mjai 格式 (gzip 壓縮)
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

async def fetch_raw_timing_data(record_uuid, downloader):
    """獲取原始思考時間數據"""
    try:
        req = pb.ReqGameRecord()
        req.game_uuid = record_uuid
        req.client_version_string = f'web-{downloader.version_to_force}'
        
        res = await downloader.lobby.fetch_game_record(req)
        
        if res.error.code:
            return None
        
        # 解析詳細記錄
        wrapper = pb.Wrapper()
        wrapper.ParseFromString(res.data)
        
        details = pb.GameDetailRecords()
        details.ParseFromString(wrapper.data)
        
        # 轉換為 JSON
        details_json = json_format.MessageToDict(details, preserving_proto_field_name=True)
        return details_json
        
    except Exception as e:
        print(f"Warning: Failed to fetch timing data for {record_uuid}: {str(e)}")
        return None

async def download_single_log(record_uuid, downloader, collect_timing=False):
    """使用 tensoul-py-ng 下載單個牌譜"""
    try:
        # tensoul 直接使用 record_uuid 下載並返回 tenhou.net/6 格式
        # lobby_id 設為 0（默認值）
        result = await downloader.download(record_uuid, lobby_id=0)
        
        if result.get("is_error", False):
            print(f"下載牌譜 {record_uuid} 失敗: {result.get('error_msg', 'Unknown error')}")
            return None, None
        
        log_data = result.get("log")
        
        # 如果需要收集思考時間，獲取原始數據
        timing_data = None
        if collect_timing:
            timing_data = await fetch_raw_timing_data(record_uuid, downloader)
        
        return log_data, timing_data
        
    except Exception as e:
        print(f"下載牌譜 {record_uuid} 失敗: {str(e)}")
        return None, None

async def main():
    # 載入環境變數
    dotenv.load_dotenv("config.env")
    
    username = os.getenv("ms_username", "cohipi3374@nausard.com")
    password = os.getenv("ms_password", "48764876")
    batch_size = 1
    base_dir = "mahjong_logs"
    temp_dir = "temp_logs"
    temp_file = "temp_ids.txt"
    
    # 是否收集思考時間（從環境變數讀取，默認為 true）
    collect_timing = os.getenv("COLLECT_TIMING", "true").lower() == "true"
    
    # 建立必要的目錄
    os.makedirs(base_dir, exist_ok=True)
    os.makedirs(os.path.join(base_dir, "mjai"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "tenhou"), exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)
    
    print(f"思考時間收集: {'啟用' if collect_timing else '停用'}")

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
    with open(temp_file, 'r', encoding='UTF-8') as f:
        temp_ids = [line.strip() for line in f]
        
    print("開始下載牌譜...")
    downloaded_ids = []
    
    # 初始化 tensoul downloader 並登入
    async with MajsoulPaipuDownloader() as downloader:
        print("登入雀魂...")
        await downloader.login(username, password)
        print("登入成功！")
        
        with tqdm(total=total_unique_ids, desc="下載進度", unit="log") as download_progress:
            for i in range(0, total_unique_ids, batch_size):
                batch_ids = temp_ids[i:i+batch_size]
                
                # 下載牌譜
                download_tasks = [download_single_log(record_uuid, downloader, collect_timing) for record_uuid in batch_ids]
                logs_batch = await asyncio.gather(*download_tasks)
                
                # 處理每個下載的牌譜
                for (log, timing_data), record_uuid in zip(logs_batch, batch_ids):
                    if log:
                        await process_log(record_uuid, log, base_dir, timing_data)
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