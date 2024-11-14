# 讀取list.txt內容
with open('list.txt', 'r') as file:
    ids = file.read().splitlines()

# 使用集合去除重複的id
unique_ids = set(ids)

# 計算刪除的id數量
removed_count = len(ids) - len(unique_ids)

# 將唯一的id寫回list.txt
with open('list.txt', 'w') as file:
    file.write('\n'.join(unique_ids))

# 輸出結果
print(f"刪除重複id後，共有 {len(unique_ids)} 個id")
print(f"刪除了 {removed_count} 個重複的id")