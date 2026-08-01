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
# 可攜式補丁 (繞過 error 151 + 自動建立 ms_cfg.json)；必須在 import tensoul 前 ensure_ms_cfg
import ms_patch
ms_patch.ensure_ms_cfg()
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

async def process_log(record_uuid, log_data, base_dir, raw_timing_data=None, full_record=None, save_debug=False, save_raw_json=False, mjai_semaphore=None):
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
    
    # tensoul 直出的 mjai 事件串流（三麻 3 席 / 四麻 4 席）。先從 tenhou6 dict 取出，
    # 避免寫進 tenhou6 檔。三麻必用它（mjai-reviewer/convlog 硬性拒絕三麻）。
    mjai_events = log_data.pop("mjai", None) if isinstance(log_data, dict) else None
    # ratingc 是 downloader 寫的權威玩家數欄位（f"PF{nplayers}"，PF3=三麻/PF4=四麻）；
    # 不要用 name 長度判斷（name 以 "AI" 佔位，語意是「名字槽位數」而非玩家數）。
    is_sanma = isinstance(log_data, dict) and log_data.get("ratingc") == "PF3"

    # log_data 已經是 tenhou.net/6 格式的字典，直接保存
    try:
        tenhou_path = os.path.join(tenhou_dir, f"{record_uuid}.json")
        with open(tenhou_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving tenhou format for {record_uuid}: {str(e)}")
        return

    # 暫存檔案（四麻 mjai-reviewer 用；三麻不會寫，留作清理時的安全檢查）
    temp_file = f"temp_logs/{record_uuid}.json"
    mjai_temp = f"temp_logs/{record_uuid}_mjai.json"

    # 轉換為 mjai 格式
    if is_sanma and mjai_events is not None:
        # 三麻：mjai-reviewer (convlog) 硬性拒絕三麻 (disp 含「三」-> NotFourPlayer)，
        # 改用 tensoul 直出、對齊 mortal-sanma libriichi3p 規格的 mjai 事件串流。
        try:
            with open(mjai_temp, "w", encoding="utf-8") as f:
                for ev in mjai_events:
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Error writing sanma mjai for {record_uuid}: {str(e)}")
    else:
        # 四麻：沿用 mjai-reviewer 把 tenhou6 -> mjai（與既有流程一致）。
        # mjai-reviewer 可由環境變數覆寫路徑 (凍結版指向內建的 mjai-reviewer.exe 絕對路徑)。
        # mjai_semaphore (若提供) 限制同時並發的轉換數，讓 GUI 能並行轉換多個牌譜。
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving temp file for {record_uuid}: {str(e)}")
            return
        try:
            mjai_bin = os.environ.get("MJAI_REVIEWER_BIN", "mjai-reviewer")
            mjai_cmd = f'"{mjai_bin}" --no-review -i {temp_file} --mjai-out {mjai_temp}'
            # 用一個不限量的 Semaphore 當作「無限制」的 fallback，避免 nullcontext 在
            # Python 3.8/3.9 不支援 async with 的問題。
            sem = mjai_semaphore if mjai_semaphore is not None else asyncio.Semaphore(2 ** 31)
            async with sem:
                proc = await asyncio.create_subprocess_shell(
                    mjai_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr_data = await proc.communicate()
            if proc.returncode != 0:
                print(f"Warning: mjai conversion failed for {record_uuid}")
                print(f"Error: {stderr_data.decode('utf-8', errors='replace')}")
        except Exception as e:
            print(f"Error executing mjai-reviewer: {str(e)}")

    # 如果有思考時間數據，注入到 mjai
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

async def fetch_record(record_uuid, downloader):
    """**只做網路那一段**：向雀魂取回單筆牌譜的原始回應。

    回傳 (res, error_msg)；失敗時 res 為 None。刻意不解析——解析是純 CPU（單筆約
    70 ms，含 timing 更多），留給呼叫端丟到背景/執行緒，讓下載迴圈只被網路 RTT 限制。
    """
    try:
        # PATCH: 舊 'web-{version}' 會回 error 151，改用可攜式補丁的共用 builder
        res = await downloader.lobby.fetch_game_record(ms_patch.build_game_record_req(record_uuid))
        if res.error.code:
            err = "error_code: %s" % res.error.code
            print(f"下載牌譜 {record_uuid} 失敗: {err}")
            return None, err
        return res, None
    except Exception as e:
        print(f"下載牌譜 {record_uuid} 失敗: {str(e)}")
        return None, str(e)

def parse_full_record(res):
    """從**已下載的回應**解出 (details_json, full_record)——不再發第二次請求。

    以前這裡是 fetch_raw_timing_data()：為了拿思考時間，對同一個 uuid 再打一次
    fetch_game_record，等於每筆牌譜向雀魂下載兩次完整內容（實測讓每筆多花 0.3~0.5 秒）。
    下載回應裡本來就含 details，直接重用即可。"""
    full_record = {
        'head': json_format.MessageToDict(res.head, preserving_proto_field_name=True) if res.head else None,
        'data_url': res.data_url if res.data_url else None,
    }

    wrapper = pb.Wrapper()
    wrapper.ParseFromString(res.data)

    details = pb.GameDetailRecords()
    details.ParseFromString(wrapper.data)

    details_json = json_format.MessageToDict(details, preserving_proto_field_name=True)
    full_record['details'] = details_json
    return details_json, full_record

def decode_record(res, downloader, collect_timing=False):
    """**只做 CPU 那一段**：把原始回應轉成 (log_data, timing_data, full_record)。

    純同步、無 I/O，可安全地丟進執行緒（run_in_executor）跑，不佔用 event loop。"""
    log_data = downloader._handle_game_record(res, 0)
    timing_data = full_record = None
    if collect_timing:
        try:
            timing_data, full_record = parse_full_record(res)
        except Exception as e:  # noqa: BLE001 timing 解析失敗不該讓整筆牌譜作廢
            print(f"Warning: Failed to parse timing data: {str(e)}")
    return log_data, timing_data, full_record

async def download_single_log(record_uuid, downloader, collect_timing=False):
    """下載並解析單個牌譜（fetch_record + decode_record 的便利組合）。

    回傳 (log_data, timing_data, full_record, error_msg)；成功時 error_msg 為 None，
    失敗時 log_data 為 None 且 error_msg 帶原因（供重試/斷點記錄判斷）。"""
    res, err = await fetch_record(record_uuid, downloader)
    if res is None:
        return None, None, None, err
    try:
        log_data, timing_data, full_record = decode_record(res, downloader, collect_timing)
    except Exception as e:  # noqa: BLE001 解析失敗視同該筆失敗
        print(f"解析牌譜 {record_uuid} 失敗: {str(e)}")
        return None, None, None, str(e)
    return log_data, timing_data, full_record, None

async def main():
    # 載入設定：優先 config.ini（單一設定檔），缺檔時回退舊的 config.env。
    import config_store
    import download_recovery
    config_store.load_into_env()

    username = os.getenv("ms_username", "cohipi3374@nausard.com")
    password = os.getenv("ms_password", "48764876")
    base_dir = "mahjong_logs"
    temp_dir = "temp_logs"
    temp_file = "temp_ids.txt"
    
    # 是否收集思考時間（從環境變數讀取，默認為 false）
    collect_timing = os.getenv("COLLECT_TIMING", "false").lower() == "true"
    
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

    # 讀取牌譜 ID（保序去除清單內重複；缺檔視為空清單——斷點可能仍有待續跑項）
    try:
        with open('tonpuulist.txt', 'r', encoding='UTF-8') as f:
            ids = list(dict.fromkeys(line.strip() for line in f if line.strip()))
    except FileNotFoundError:
        ids = []

    # 斷點檔先載入並把 pending/failed 併回工作清單——清單被覆蓋/換檔時上次中止的
    # 項目才不會默默消失（斷點才算真的有讀）。
    checkpoint = download_recovery.Checkpoint("download_checkpoint.json").load()
    ids = download_recovery.merge_checkpoint_ids(ids, checkpoint)

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

    # 逐行寫（不要 '\n'.join）：百萬筆規模時那個中間字串本身就是上百 MB。
    with open(temp_file, 'w', encoding='UTF-8') as f:
        f.writelines(f"{uuid}\n" for uuid in unique_ids)

    # 帳號池（主帳號＋config.ini [account] account_pool）
    accounts = download_recovery.load_accounts({"username": username, "password": password})
    if not accounts:
        print("錯誤：尚未設定雀魂帳號（config.ini [account]）")
        return
    # 只要「有幾筆是續跑的」，不要為此再造一份百萬筆清單。
    resume_set = set(checkpoint.pending)
    resume_set.update(checkpoint.failed)
    retry_count = sum(1 for u in unique_ids if u in resume_set)
    del resume_set
    checkpoint.forget_pending()  # 已併入工作清單，記憶體中不需再留（磁碟檔仍在）
    if retry_count:
        print(f"偵測到上次失敗/中止的 {retry_count} 筆，將自動續跑")
    ini_paths = [p for p in (config_store.default_path(),) if os.path.exists(p)]
    max_attempts = 3 if len(accounts) > 1 else 2

    print("開始下載牌譜...")
    failed_count = 0
    aborted = False
    # 串行依序處理，故「未處理的」＝目前索引之後的切片（不必留 done_uuids 集合，
    # 百萬筆規模下那是另一份數百 MB 的副本）。
    next_index = 0

    # 初始化 tensoul downloader 並登入（失敗時自動更新版本/換帳號，見 download_recovery）
    async with MajsoulPaipuDownloader() as downloader:
        session = download_recovery.AccountSession(
            downloader, accounts, ini_paths=ini_paths,
            notify=lambda code, msg="": print(f"[帳號] {code} {msg}".rstrip()))
        print(f"登入雀魂...（號池共 {len(accounts)} 個帳號）")
        try:
            await session.ensure_login()
        except download_recovery.AllAccountsFailed as e:
            checkpoint.set_pending(unique_ids)
            checkpoint.close()
            print(f"所有帳號皆無法登入（{e}），已記錄斷點於 {checkpoint.path}")
            return
        print("登入成功！")
        session.start_keepalive()

        # 下載迴圈只做「發請求 / 收回應」，解析與轉換丟到背景（見 handle_record）：
        # 一次仍只有一個請求在線上（嚴格串行），但單筆的本機成本（解析約 70 ms、
        # 寫檔、mjai-reviewer 子程序）不再串在網路等待之後，整體逼近純網路速度。
        async def fetch_only(uuid):
            res, err = await fetch_record(uuid, downloader)
            return res, None, None, err

        workers = min(8, os.cpu_count() or 4)
        mjai_sem = asyncio.Semaphore(workers)
        slots = asyncio.Semaphore(workers * 2)  # 限制在途的後處理，避免記憶體堆積
        tasks = set()
        loop = asyncio.get_event_loop()

        async def handle_record(uuid, res, progress):
            """背景後處理：解析（丟執行緒，不卡 event loop）＋寫檔＋轉 mjai。"""
            try:
                log, timing_data, full_record = await loop.run_in_executor(
                    None, decode_record, res, downloader, collect_timing)
                await process_log(uuid, log, base_dir, timing_data, full_record,
                                  save_debug, save_raw_json, mjai_semaphore=mjai_sem)
                progress.update(1)
            except Exception as e:  # noqa: BLE001 單筆後處理失敗不影響其餘下載
                print(f"處理牌譜 {uuid} 失敗: {str(e)}")
            finally:
                slots.release()

        try:
            with tqdm(total=total_unique_ids, desc="下載進度", unit="log") as download_progress:
                for index, record_uuid in enumerate(unique_ids):
                    next_index = index
                    t0 = time.perf_counter()
                    try:
                        res, _, _, err = await download_recovery.download_with_retry(
                            session, fetch_only, record_uuid, max_attempts=max_attempts)
                    except download_recovery.AllAccountsFailed as e:
                        aborted = True
                        pending = unique_ids[next_index:]
                        checkpoint.set_pending(pending)
                        print(f"\n所有帳號皆無法登入（{e}），中止。"
                              f"尚餘 {len(pending)} 筆未處理，已記錄斷點於 {checkpoint.path}")
                        break
                    next_index = index + 1
                    if res is not None:
                        # 連線異常緩慢（節點抽壞或帳號被限流）→ 重連換節點＋換下一個帳號。
                        slow = session.note_timing(time.perf_counter() - t0)
                        if slow is not None:
                            print(f"[連線] 異常緩慢（{slow:.1f}s/筆），改換節點/帳號")
                            await session.recover(session.generation, force_switch=True,
                                                  reason=f"連線異常緩慢（{slow:.1f}s/筆）")
                        checkpoint.clear_failure(record_uuid)
                        await slots.acquire()
                        task = asyncio.ensure_future(
                            handle_record(record_uuid, res, download_progress))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
                    else:
                        failed_count += 1
                        checkpoint.record_failure(record_uuid, err or "unknown error",
                                                  session.current_username)

                if tasks:  # 中止與否都要等背景後處理完成，避免漏寫輸出
                    await asyncio.gather(*list(tasks), return_exceptions=True)
        finally:
            await session.stop_keepalive()  # 心跳任務不可留到連線關閉之後

    # 清理臨時檔案
    print("\n清理臨時檔案...")
    os.remove(temp_file)
    if os.path.exists(temp_dir):
        for file in os.listdir(temp_dir):
            os.remove(os.path.join(temp_dir, file))
        os.rmdir(temp_dir)

    if aborted:
        checkpoint.close()
        return
    checkpoint.set_pending([])
    if failed_count:
        checkpoint.close()
        print(f"完成，但有 {failed_count} 筆失敗（已記錄於 {checkpoint.path}，重新執行會自動重試）")
    else:
        checkpoint.delete_if_clean()
        print("全部處理完成！")

if __name__ == "__main__":
    asyncio.run(main())