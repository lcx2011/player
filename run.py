#!/usr/bin/env python3
"""
一键启动脚本 - 启动后端服务器
"""
import os
import sys
import subprocess
from pathlib import Path

def main():
    print("🎬 儿童视频播放器")
    print("=" * 50)
    
    # 检查Python版本
    if sys.version_info < (3, 8):
        print("❌ 需要Python 3.8或更高版本")
        return
    
    # 检查是否在正确目录
    if not Path("backend").exists():
        print("❌ 请在项目根目录运行此脚本")
        return
    
    # 检查依赖
    try:
        import fastapi
        import uvicorn
        import aiohttp
        import aiofiles
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("请运行: pip install -r backend/requirements.txt")
        return
    
    # 确保videos目录存在
    videos_dir = Path("videos")
    if not videos_dir.exists():
        videos_dir.mkdir()
        print(f"✅ 创建videos目录: {videos_dir.absolute()}")
    
    # 切换到backend目录并启动服务器
    os.chdir("backend")
    
    print("🚀 启动后端服务...")
    print("🌐 前端地址: http://localhost:8000/")
    print("📖 API文档: http://localhost:8000/docs")
    print("🔄 按 Ctrl+C 停止服务")
    print("-" * 50)
    
    try:
        subprocess.run([sys.executable, "start_server.py"])
    except KeyboardInterrupt:
        print("\n👋 服务已停止")

if __name__ == "__main__":
    main()