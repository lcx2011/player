#!/usr/bin/env python3
"""
一键启动脚本 - 启动完整的视频播放器应用
包含前端和后端服务
"""
import os
import sys
import subprocess
import webbrowser
import time
from pathlib import Path

def check_dependencies():
    """检查依赖是否安装"""
    try:
        import fastapi
        import uvicorn
        import requests
        import aiohttp
        import aiofiles
        print("✅ 所有依赖已安装")
        return True
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("请运行: pip install -r backend/requirements.txt")
        return False

def check_ffmpeg():
    """检查FFmpeg是否可用"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ FFmpeg 已安装")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  FFmpeg 未找到，视频合并功能可能不可用")
        print("请从 https://ffmpeg.org/download.html 下载安装")
        return False

def create_sample_folders():
    """创建示例文件夹和配置"""
    videos_dir = Path("videos")
    
    # 确保示例文件夹存在
    for folder_name in ["动画片", "教育视频"]:
        folder_path = videos_dir / folder_name
        folder_path.mkdir(exist_ok=True)
        
        list_file = folder_path / "list.txt"
        if not list_file.exists():
            with open(list_file, 'w', encoding='utf-8') as f:
                f.write(f"# {folder_name}视频列表\n")
                f.write("# 每行一个B站视频链接，例如：\n")
                f.write("# https://www.bilibili.com/video/BV1xx411c7mu\n")
    
    print("✅ 示例文件夹已创建")

def main():
    print("🎬 儿童视频播放器")
    print("=" * 50)
    
    # 检查Python版本
    if sys.version_info < (3, 8):
        print("❌ 需要Python 3.8或更高版本")
        return
    
    # 检查是否在正确目录
    if not Path("backend").exists() or not Path("frontend").exists():
        print("❌ 请在项目根目录运行此脚本")
        return
    
    # 检查依赖
    if not check_dependencies():
        return
    
    # 检查FFmpeg
    check_ffmpeg()
    
    # 创建示例文件夹
    create_sample_folders()
    
    print("\n🚀 启动服务器...")
    print("🌐 应用地址: http://localhost:8000")
    print("📖 API文档: http://localhost:8000/docs")
    print("🔄 按 Ctrl+C 停止服务")
    print("-" * 50)
    
    # 启动后端服务器
    try:
        # 延迟打开浏览器
        def open_browser():
            time.sleep(2)
            webbrowser.open('http://localhost:8000')
        
        import threading
        browser_thread = threading.Thread(target=open_browser)
        browser_thread.daemon = True
        browser_thread.start()
        
        # 启动服务器
        os.chdir("backend")
        subprocess.run([sys.executable, "main.py"])
        
    except KeyboardInterrupt:
        print("\n👋 服务已停止")
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")

if __name__ == "__main__":
    main()