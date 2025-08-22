#!/usr/bin/env python3
"""
启动服务器脚本
"""
import uvicorn
from pathlib import Path

def main():
    print("🚀 Starting development server for Video Player Backend...")
    print("🔄 Auto-reload is enabled for the 'backend/app' directory.")
    print("🌐 Service will be available at: http://localhost:8000")
    print("📖 API documentation at: http://localhost:8000/docs")
    print("-" * 50)
    
    try:
        # Run from the project root directory
        uvicorn.run(
            "backend.app.main:app",  # Full import path to the app object
            host="0.0.0.0",
            port=8000,
            reload=True,
            reload_dirs=["backend/app"],  # Watch the new app directory for changes
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 Server has been stopped.")
    except ImportError as e:
        print(f"\n❌ Error: Could not import the application: {e}")
        print("   Please ensure you are running this script from the project's root directory.")

if __name__ == "__main__":
    main()