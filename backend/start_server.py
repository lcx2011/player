#!/usr/bin/env python3
"""
启动服务器脚本
"""
import uvicorn
from pathlib import Path

def main():
    # 确保videos目录存在
    videos_dir = Path("videos")
    if not videos_dir.exists():
        videos_dir.mkdir()
        print(f"创建videos目录: {videos_dir.absolute()}")
    
    # 启动服务器
    print("🚀 启动儿童视频播放器后端服务...")
    print(f"📁 视频目录: {videos_dir.absolute()}")
    print("🌐 服务地址: http://localhost:8000")
    print("📖 API文档: http://localhost:8000/docs")
    print("🔄 按 Ctrl+C 停止服务")
    print("-" * 50)
    
    try:
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            reload_dirs=["backend"],
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 服务已停止")

if __name__ == "__main__":
    main()