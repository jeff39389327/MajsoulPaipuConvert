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

def extract_timing_data(raw_details, debug=False):
    """從原始數據中提取思考時間（基於 RecordDiscardTile 順序匹配）"""
    import base64
    
    timing_map = {}  # key: (actor, action_seq) -> think_ms
    
    actions = raw_details.get('actions', [])
    action_seq = {0: 0, 1: 0, 2: 0, 3: 0}  # 每個玩家的動作序號
    
    # 遍歷所有動作，按順序處理
    for i, action in enumerate(actions):
        action_type = action.get('type')
        
        # type 1: 系統事件 - RecordDiscardTile
        if action_type == 1 and 'result' in action:
            try:
                result_bytes = base64.b64decode(action['result'])
                wrapper = pb.Wrapper()
                wrapper.ParseFromString(result_bytes)
                
                if 'RecordDiscardTile' in wrapper.name:
                    discard = pb.RecordDiscardTile()
                    discard.ParseFromString(wrapper.data)
                    seat = discard.seat
                    
                    # 往前找對應的 user_input 中的 timeuse
                    timeuse = None
                    for j in range(max(0, i-3), i):
                        prev_action = actions[j]
                        if (prev_action.get('type') == 2 and 
                            'user_input' in prev_action):
                            prev_ui = prev_action['user_input']
                            prev_seat = prev_ui.get('seat', 0)
                            prev_type = prev_ui.get('type')
                            
                            # 檢查是否為同一玩家的打牌操作
                            if prev_seat == seat and prev_type == 2 and 'operation' in prev_ui:
                                operation = prev_ui['operation']
                                if 'timeuse' in operation:
                                    timeuse = operation['timeuse']
                                break
                    
                    # 如果沒有找到 timeuse，設為 0（配牌打或無記錄）
                    if timeuse is None:
                        timeuse = 0
                    
                    # 記錄到 timing_map
                    timing_map[(seat, action_seq[seat])] = timeuse
                    action_seq[seat] += 1
                    
            except:
                pass
        
        # type 2: 玩家操作 - 鳴牌（chi/pon/kan）
        elif action_type == 2 and 'user_input' in action:
            user_input = action['user_input']
            user_input_type = user_input.get('type')
            
            # 鳴牌操作
            if user_input_type == 3 and 'cpg' in user_input:
                cpg = user_input['cpg']
                # 跳過取消的鸣牌操作（不生成mjai事件，不計入action_seq）
                if cpg.get('cancel_operation'):
                    continue
                
                seat = user_input.get('seat', 0)
                timeuse = cpg.get('timeuse', 0)
                
                timing_map[(seat, action_seq[seat])] = timeuse
                action_seq[seat] += 1
    
    return timing_map

def inject_timing_to_mjai(mjai_file, timing_map, debug=False):
    """在 mjai 格式中注入思考時間（不进行智能填补）"""
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
                    elif debug:
                        print(f"缺失timing - actor={actor}, seq={action_seq[actor]}, type={event_type}, tsumogiri={event.get('tsumogiri')}")
                    action_seq[actor] += 1
            
            elif event_type in ['chi', 'pon', 'daiminkan', 'kakan', 'ankan']:
                actor = event.get('actor')
                if actor is not None:
                    key = (actor, action_seq[actor])
                    if key in timing_map:
                        event['think_ms'] = timing_map[key]
                    elif debug:
                        print(f"缺失timing - actor={actor}, seq={action_seq[actor]}, type={event_type}")
                    action_seq[actor] += 1
            
            output_lines.append(json.dumps(event, ensure_ascii=False))
    
    # 寫回文件
    with open(mjai_file, 'w', encoding='utf-8') as f:
        for line in output_lines:
            f.write(line + '\n')

async def process_log(record_uuid, log_data, base_dir, raw_timing_data=None, full_record=None, save_debug=False, save_raw_json=False):
    # 建立目錄
    mjai_dir = os.path.join(base_dir, "mjai")
    tenhou_dir = os.path.join(base_dir, "tenhou")
    raw_json_dir = os.path.join(base_dir, "raw_json")
    debug_dir = os.path.join(base_dir, "debug_timing")
    os.makedirs(mjai_dir, exist_ok=True)
    os.makedirs(tenhou_dir, exist_ok=True)
    if save_raw_json:
        os.makedirs(raw_json_dir, exist_ok=True)
    if save_debug:
        os.makedirs(debug_dir, exist_ok=True)
    
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
            # 保存原始JSON（如果启用）
            if save_raw_json and full_record:
                raw_json_file = os.path.join(raw_json_dir, f"{record_uuid}_full.json")
                with open(raw_json_file, 'w', encoding='utf-8') as f:
                    json.dump(full_record, f, ensure_ascii=False, indent=2)
            
            timing_map = extract_timing_data(raw_timing_data)
            
            # 如果启用debug，保存原始timing数据
            if save_debug:
                timing_dict = {f"{k[0]},{k[1]}": v for k, v in timing_map.items()}
                debug_file = os.path.join(debug_dir, f"{record_uuid}_timing_map.json")
                with open(debug_file, 'w', encoding='utf-8') as f:
                    json.dump(timing_dict, f, ensure_ascii=False, indent=2)
                
                # 保存原始actions
                raw_file = os.path.join(debug_dir, f"{record_uuid}_raw_actions.json")
                with open(raw_file, 'w', encoding='utf-8') as f:
                    json.dump(raw_timing_data, f, ensure_ascii=False, indent=2)
            
            inject_timing_to_mjai(mjai_temp, timing_map, debug=save_debug)
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
    """獲取原始思考時間數據和完整牌譜記錄"""
    try:
        req = pb.ReqGameRecord()
        req.game_uuid = record_uuid
        req.client_version_string = f'web-{downloader.version_to_force}'
        
        res = await downloader.lobby.fetch_game_record(req)
        
        if res.error.code:
            return None, None
        
        # 保存完整的原始響應（包含head和details_data）
        full_record = {
            'head': json_format.MessageToDict(res.head, preserving_proto_field_name=True) if res.head else None,
            'data_url': res.data_url if res.data_url else None,
        }
        
        # 解析詳細記錄
        wrapper = pb.Wrapper()
        wrapper.ParseFromString(res.data)
        
        details = pb.GameDetailRecords()
        details.ParseFromString(wrapper.data)
        
        # 轉換為 JSON
        details_json = json_format.MessageToDict(details, preserving_proto_field_name=True)
        
        # 合併到完整記錄中
        full_record['details'] = details_json
        
        return details_json, full_record
        
    except Exception as e:
        print(f"Warning: Failed to fetch timing data for {record_uuid}: {str(e)}")
        return None, None

async def download_single_log(record_uuid, downloader, collect_timing=False):
    """使用 tensoul-py-ng 下載單個牌譜"""
    try:
        # tensoul 直接使用 record_uuid 下載並返回 tenhou.net/6 格式
        # lobby_id 設為 0（默認值）
        result = await downloader.download(record_uuid, lobby_id=0)
        
        if result.get("is_error", False):
            print(f"下載牌譜 {record_uuid} 失敗: {result.get('error_msg', 'Unknown error')}")
            return None, None, None
        
        log_data = result.get("log")
        
        # 如果需要收集思考時間，獲取原始數據
        timing_data = None
        full_record = None
        if collect_timing:
            timing_data, full_record = await fetch_raw_timing_data(record_uuid, downloader)
        
        return log_data, timing_data, full_record
        
    except Exception as e:
        print(f"下載牌譜 {record_uuid} 失敗: {str(e)}")
        return None, None, None

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
    
    # 是否保存debug信息（從環境變數讀取，默認為 false）
    save_debug = os.getenv("SAVE_DEBUG", "false").lower() == "true"
    
    # 是否保存原始JSON（從環境變數讀取，默認為 false）
    save_raw_json = os.getenv("SAVE_RAW_JSON", "false").lower() == "true"
    
    # 如果要保存原始JSON，必須啟用timing收集
    if save_raw_json and not collect_timing:
        collect_timing = True
        print("注意: 保存原始JSON需要啟用timing收集，已自動啟用")
    
    # 建立必要的目錄
    os.makedirs(base_dir, exist_ok=True)
    os.makedirs(os.path.join(base_dir, "mjai"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "tenhou"), exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)
    
    print(f"思考時間收集: {'啟用' if collect_timing else '停用'}")
    print(f"Debug模式: {'啟用' if save_debug else '停用'}")
    print(f"保存原始JSON: {'啟用' if save_raw_json else '停用'}")

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
                for (log, timing_data, full_record), record_uuid in zip(logs_batch, batch_ids):
                    if log:
                        await process_log(record_uuid, log, base_dir, timing_data, full_record, save_debug, save_raw_json)
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