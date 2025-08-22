import os
from pathlib import Path

# --- Configuration ---
# The project root is three levels up from this file
# (backend/app/config.py -> backend/app -> backend -> root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

VIDEOS_DIR = BASE_DIR / "videos"
FRONTEND_DIR = BASE_DIR / "frontend"
COVERS_DIR = BASE_DIR / "covers"
SUBTITLES_DIR = BASE_DIR / "subtitles"

# --- Bilibili API Settings ---
try:
    # This tries to import the user-defined cookie from a file at `backend/config.py`
    from ..config import BILIBILI_COOKIE
except ImportError:
    BILIBILI_COOKIE = ""
    print("警告: 未找到 backend/config.py, 字幕功能将不可用。")

HEADERS = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36',
    'referer': 'https://www.bilibili.com/'
}

# --- Request Limiting & Backoff ---
MAX_CONCURRENT_OUTBOUND = int(os.getenv("OUTBOUND_MAX_CONCURRENCY", "3"))
MAX_QPS = float(os.getenv("OUTBOUND_MAX_QPS", "2"))
MAX_COOLDOWN_SECONDS = int(os.getenv("OUTBOUND_MAX_COOLDOWN", "300"))

def ensure_dirs_exist():
    """Ensure that the necessary directories for caching and videos exist."""
    VIDEOS_DIR.mkdir(exist_ok=True)
    COVERS_DIR.mkdir(exist_ok=True)
    SUBTITLES_DIR.mkdir(exist_ok=True)
