#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
安全启动爬虫脚本
自动清理残留进程和临时目录后再运行爬虫
"""

import subprocess
import sys
import os

def run_cleanup():
    """运行清理脚本"""
    print("步骤 1: 清理残留的 Chrome 进程和临时目录...")
    print("=" * 60)
    
    try:
        result = subprocess.run(
            [sys.executable, 'cleanup_chrome.py'],
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        print(result.stdout)
        if result.stderr:
            print("警告:", result.stderr)
    except Exception as e:
        print(f"清理时出错: {e}")
        print("继续运行爬虫...")
    
    print()

def run_spider():
    """运行爬虫"""
    print("步骤 2: 启动爬虫...")
    print("=" * 60)
    print()
    
    # 切换到 paipu_project 目录
    paipu_dir = os.path.join(os.path.dirname(__file__), 'paipu_project')
    os.chdir(paipu_dir)
    
    # 运行 scrapy
    try:
        subprocess.run(
            ['scrapy', 'crawl', 'paipu_spider'],
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"\n爬虫运行出错: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n用户中断爬虫运行")
        sys.exit(0)

def main():
    print()
    print("=" * 60)
    print("安全启动 Mahjsoul Paipu 爬虫")
    print("=" * 60)
    print()
    
    # 步骤 1: 清理
    run_cleanup()
    
    # 步骤 2: 运行爬虫
    run_spider()
    
    print()
    print("=" * 60)
    print("✅ 爬虫运行完成")
    print("=" * 60)

if __name__ == "__main__":
    main()

