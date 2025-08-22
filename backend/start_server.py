#!/usr/bin/env python3
"""
Development server startup script.
This script is designed for development and enables auto-reloading.
"""
import uvicorn
import sys
from pathlib import Path

# --- Path Setup ---
# This ensures the script works whether it's run from the project root
# (e.g., `python backend/start_server.py`) or from the backend directory
# (e.g., `cd backend; python start_server.py`).

# The directory containing this script (`backend/`)
script_dir = Path(__file__).resolve().parent
# The project root is one level up
project_root = script_dir.parent
# Add the project root to the system path to ensure modules are found
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def main():
    # The reload directory path should be an absolute path or relative to the CWD.
    # We construct an absolute path to be safe.
    reload_dir_path = project_root / "backend" / "app"

    print("🚀 Starting development server for Video Player Backend...")
    print(f"🔄 Auto-reload is enabled for the '{reload_dir_path.relative_to(project_root)}' directory.")
    print("🌐 Service will be available at: http://localhost:8000")
    print("📖 API documentation at: http://localhost:8000/docs")
    print("-" * 50)
    
    try:
        uvicorn.run(
            "backend.app.main:app",  # Full import path from the project root
            host="0.0.0.0",
            port=8000,
            reload=True,
            reload_dirs=[str(reload_dir_path)],  # Use the absolute path for reliability
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 Server has been stopped.")
    except ImportError as e:
        print(f"\n❌ Error: Could not import the application: {e}")
        print("   Please ensure all dependencies are installed from `backend/requirements.txt`.")

if __name__ == "__main__":
    main()