#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
測試 Chrome 驅動器修復
用於驗證臨時用戶數據目錄是否正常工作
"""

import sys
import os

# 添加專案路徑到系統路徑
project_path = os.path.join(os.path.dirname(__file__), 'paipu_project', 'paipu_project')
sys.path.insert(0, project_path)

from date_room_extractor import OptimizedPaipuExtractor

def test_chrome_initialization():
    """測試 Chrome 初始化"""
    print("=" * 60)
    print("測試 Chrome 驅動器初始化")
    print("=" * 60)
    
    try:
        # 測試非無頭模式（如果你想看到瀏覽器）
        print("\n步驟 1: 初始化 Chrome 驅動器 (headless=False)...")
        extractor = OptimizedPaipuExtractor(headless=False)
        
        print("\n步驟 2: 測試訪問網頁...")
        extractor.driver.get("https://www.google.com")
        
        current_url = extractor.driver.current_url
        print(f"當前 URL: {current_url}")
        
        if current_url.startswith("data:"):
            print("❌ 錯誤: 網頁顯示 'data:'，瀏覽器未正常工作")
            return False
        else:
            print("✅ 成功: 網頁正常加載")
        
        print("\n步驟 3: 關閉驅動器...")
        extractor.close()
        
        print("\n✅ 所有測試通過！")
        return True
        
    except Exception as e:
        print(f"\n❌ 測試失敗: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_multiple_instances():
    """測試多個 Chrome 實例（驗證 user-data-dir 衝突是否解決）"""
    print("\n" + "=" * 60)
    print("測試多個 Chrome 實例")
    print("=" * 60)
    
    extractors = []
    
    try:
        print("\n嘗試創建 3 個 Chrome 實例...")
        for i in range(3):
            print(f"\n創建實例 {i+1}...")
            extractor = OptimizedPaipuExtractor(headless=True)
            extractors.append(extractor)
            print(f"✅ 實例 {i+1} 創建成功")
        
        print("\n✅ 所有實例創建成功，無衝突！")
        return True
        
    except Exception as e:
        print(f"\n❌ 測試失敗: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        print("\n清理所有實例...")
        for i, extractor in enumerate(extractors):
            try:
                extractor.close()
                print(f"✅ 實例 {i+1} 已關閉")
            except:
                pass

if __name__ == "__main__":
    print("\n開始測試 Chrome 驅動器修復...\n")
    
    # 測試 1: 基本初始化
    test1_passed = test_chrome_initialization()
    
    # 測試 2: 多實例（驗證 user-data-dir 衝突修復）
    test2_passed = test_multiple_instances()
    
    print("\n" + "=" * 60)
    print("測試總結")
    print("=" * 60)
    print(f"基本初始化測試: {'✅ 通過' if test1_passed else '❌ 失敗'}")
    print(f"多實例測試: {'✅ 通過' if test2_passed else '❌ 失敗'}")
    
    if test1_passed and test2_passed:
        print("\n🎉 所有測試通過！Chrome 驅動器修復成功。")
    else:
        print("\n⚠️ 部分測試失敗，請檢查錯誤訊息。")

