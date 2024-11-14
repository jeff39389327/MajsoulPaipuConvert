import os

def clean_duplicates(folder_path):
    # 使用字典存儲檔案名和路徑
    file_dict = {}

    # 掃描資料夾內的所有檔案
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        
        # 如果是檔案而不是資料夾
        if os.path.isfile(file_path):
            # 如果檔案名已經存在於字典中，則刪除重複的檔案
            if filename in file_dict:
                os.remove(file_path)
            else:
                file_dict[filename] = file_path

    # 計算刪除的檔案數量
    removed_count = len(os.listdir(folder_path)) - len(file_dict)

    # 輸出結果
    print(f"刪除重複檔案後，共有 {len(file_dict)} 個唯一的檔案")
    print(f"刪除了 {removed_count} 個重複的檔案")

# 指定要掃描的資料夾路徑
folder_path = 'tonpuulog'  # 指定清理 "log" 資料夾

# 呼叫函式清理重複檔案
clean_duplicates(folder_path)