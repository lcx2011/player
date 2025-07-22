import os
import re
import subprocess
import requests
import json
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import asyncio

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent.parent
VIDEOS_DIR = BASE_DIR / "videos"
FRONTEND_DIR = BASE_DIR / "frontend"
COVERS_DIR = BASE_DIR / "covers"  # 封面缓存目录
# Ensure the main directories exist
VIDEOS_DIR.mkdir(exist_ok=True)
COVERS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Video Player Backend")

# 挂载前端静态文件服务
app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")

# --- CORS Middleware ---
# This allows the frontend (running on a different port) to communicate with this backend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# --- Bilibili Downloader Logic (Adapted from 1.py) ---

HEADERS = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36',
    'referer': 'https://www.bilibili.com/'
}

def get_bilibili_response(url, params=None):
    """Sends a request to a Bilibili API endpoint."""
    try:
        # Disable SSL verification warnings
        requests.packages.urllib3.disable_warnings()
        response = requests.get(url, params=params, headers=HEADERS, timeout=15, verify=False)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None

def extract_bvid_from_url(url_or_bvid: str) -> str:
    """Extract BV ID from Bilibili URL or return as-is if already a BV ID."""
    if url_or_bvid.startswith('http'):
        # Extract BV ID from URL like https://www.bilibili.com/video/BV1LnuzzyEQp
        match = re.search(r'/video/(BV[a-zA-Z0-9]+)', url_or_bvid)
        if match:
            return match.group(1)
        else:
            raise ValueError(f"Could not extract BV ID from URL: {url_or_bvid}")
    else:
        # Assume it's already a BV ID
        return url_or_bvid

def get_video_parts_with_covers(bvid: str):
    """Fetches video parts and their cover images from Bilibili page."""
    try:
        # 获取视频页面
        url = f"https://www.bilibili.com/video/{bvid}"
        response = get_bilibili_response(url)
        if not response:
            return None

        html_content = response.text

        # 提取JSON数据
        match = re.search(r'<script>window\.__INITIAL_STATE__=(.*?);\(function\(\)', html_content)
        if not match:
            print(f"未找到视频数据: {bvid}")
            return None

        json_data_string = match.group(1)
        data = json.loads(json_data_string)

        # 获取视频分P列表
        video_parts = data.get('videoData', {}).get('pages', [])
        if not video_parts:
            print(f"未找到分P视频: {bvid}")
            return None

        # 为每个分P添加封面信息
        enhanced_parts = []
        for part in video_parts:
            enhanced_part = {
                'cid': part.get('cid'),
                'page': part.get('page'),
                'part': part.get('part'),
                'duration': part.get('duration'),
                'cover_url': part.get('first_frame', ''),
                'dimension': part.get('dimension', {})
            }
            enhanced_parts.append(enhanced_part)

        return enhanced_parts

    except (json.JSONDecodeError, Exception) as e:
        print(f"获取视频信息失败: {e}")
        return None

def get_video_parts(bvid: str):
    """Fetches the list of video parts (pages) for a given Bilibili BV ID."""
    url = 'https://api.bilibili.com/x/player/pagelist'
    params = {'bvid': bvid, 'jsonp': 'jsonp'}
    response = get_bilibili_response(url, params)
    if response:
        try:
            data = response.json()
            if data['code'] == 0:
                return data['data']
        except (ValueError, KeyError):
            return None
    return None

async def download_and_cache_cover(bvid: str, page: int, cover_url: str) -> str:
    """下载并缓存封面图片，返回本地路径"""
    if not cover_url:
        return ""

    # 确保URL协议完整
    if cover_url.startswith('//'):
        cover_url = 'http:' + cover_url

    # 生成缓存文件名
    cover_filename = f"{bvid}_p{page}.jpg"
    cover_path = COVERS_DIR / cover_filename

    # 如果已经缓存，直接返回
    if cover_path.exists():
        return f"/covers/{cover_filename}"

    try:
        # 下载封面
        response = get_bilibili_response(cover_url)
        if response:
            with open(cover_path, 'wb') as f:
                f.write(response.content)
            return f"/covers/{cover_filename}"
    except Exception as e:
        print(f"下载封面失败: {e}")

    return ""

def download_and_merge(bvid: str, p_info: dict, target_dir: Path):
    """Downloads and merges a single video part."""
    page = p_info['page']
    cid = p_info['cid']
    # Sanitize the title to create a valid filename
    clean_name = re.sub(r'[\\/*?:"<>|]', "", p_info['part'])
    final_video_path = target_dir / f"{clean_name}.mp4"
    
    # If the final merged video already exists, do nothing.
    if final_video_path.exists():
        print(f"Video '{clean_name}.mp4' already exists. Skipping download.")
        return str(final_video_path)

    # 1. Get Session
    session_url = f'https://www.bilibili.com/video/{bvid}?p={page}'
    session_response = get_bilibili_response(session_url)
    if not session_response:
        raise Exception("Failed to get session.")
    
    session_match = re.search(r'"session":"(.*?)"', session_response.text)
    if not session_match:
        raise Exception("Could not find session in page.")
    session = session_match.group(1)

    # 2. Get Video/Audio URLs
    playurl = 'https://api.bilibili.com/x/player/playurl'
    params = {
        'cid': cid, 'bvid': bvid, 'qn': '80', # qn=80 for 1080p
        'fnver': '0', 'fnval': '976', 'session': session
    }
    play_response = get_bilibili_response(playurl, params)
    if not play_response:
        raise Exception("Failed to get play URLs.")
        
    play_data = play_response.json()
    if play_data['code'] != 0:
        raise Exception(f"API error getting play URLs: {play_data.get('message', 'Unknown error')}")

    try:
        audio_url = play_data['data']['dash']['audio'][0]['baseUrl']
        video_url = play_data['data']['dash']['video'][0]['baseUrl']
    except (KeyError, IndexError):
        raise Exception("Could not parse audio/video URLs from API response.")

    # 3. Download Audio and Video
    temp_audio_path = target_dir / f"{clean_name}_audio.mp3"
    temp_video_path = target_dir / f"{clean_name}_video.mp4"

    audio_res = get_bilibili_response(audio_url)
    video_res = get_bilibili_response(video_url)

    if not audio_res or not video_res:
        raise Exception("Failed to download audio or video content.")

    with open(temp_audio_path, 'wb') as f:
        f.write(audio_res.content)
    with open(temp_video_path, 'wb') as f:
        f.write(video_res.content)

    # 4. Merge with ffmpeg
    command = f'ffmpeg -i "{temp_video_path}" -i "{temp_audio_path}" -c copy "{final_video_path}"'
    try:
        subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        # If merge fails, clean up temp files and raise error
        temp_audio_path.unlink(missing_ok=True)
        temp_video_path.unlink(missing_ok=True)
        raise Exception(f"ffmpeg merge failed: {e.stderr}")

    # 5. Clean up temporary files
    temp_audio_path.unlink(missing_ok=True)
    temp_video_path.unlink(missing_ok=True)
    
    return str(final_video_path)


# --- API Endpoints ---

@app.get("/api/folders")
async def list_folders():
    """Lists all top-level folders within the VIDEOS_DIR."""
    if not VIDEOS_DIR.is_dir():
        return []
    return [d.name for d in VIDEOS_DIR.iterdir() if d.is_dir()]

@app.get("/api/folders/{folder_name}")
async def list_videos_in_folder(folder_name: str):
    """
    Lists all video parts from a 'list.txt' file in a specific folder.
    It fetches the part information and covers from Bilibili.
    """
    folder_path = VIDEOS_DIR / folder_name
    list_file = folder_path / "list.txt"

    if not list_file.exists():
        raise HTTPException(status_code=404, detail=f"'list.txt' not found in folder '{folder_name}'")

    with open(list_file, 'r', encoding='utf-8') as f:
        bvid_lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    if not bvid_lines:
        raise HTTPException(status_code=404, detail=f"'list.txt' is empty or contains no valid BV IDs.")

    # For simplicity, we'll use the first BV ID found in the file.
    try:
        bvid = extract_bvid_from_url(bvid_lines[0])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 优先使用带封面的获取方法
    video_parts = get_video_parts_with_covers(bvid)
    if not video_parts:
        # 如果失败，回退到原来的方法
        video_parts = get_video_parts(bvid)
        if not video_parts:
            raise HTTPException(status_code=500, detail=f"Could not fetch video parts for BV ID: {bvid}")
        # 转换为统一格式
        video_parts = [{"title": part['part'], "page": part['page'], "cover_url": ""} for part in video_parts]
    else:
        # 下载并缓存封面
        enhanced_parts = []
        for part in video_parts:
            cover_path = await download_and_cache_cover(bvid, part['page'], part['cover_url'])
            enhanced_parts.append({
                "title": part['part'],
                "page": part['page'],
                "cover_url": cover_path,
                "duration": part.get('duration', 0)
            })
        video_parts = enhanced_parts

    return video_parts


@app.get("/api/play/{folder_name}/{page_number}")
async def play_video(folder_name: str, page_number: int, background_tasks: BackgroundTasks):
    """
    Ensures a video is downloaded and returns its static file path.
    If the video doesn't exist, it's downloaded in the background.
    """
    folder_path = VIDEOS_DIR / folder_name
    list_file = folder_path / "list.txt"

    if not list_file.exists():
        raise HTTPException(status_code=404, detail=f"'list.txt' not found in folder '{folder_name}'")

    with open(list_file, 'r', encoding='utf-8') as f:
        bvid_lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    if not bvid_lines:
        raise HTTPException(status_code=404, detail="'list.txt' is empty.")

    try:
        bvid = extract_bvid_from_url(bvid_lines[0])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    video_parts = get_video_parts(bvid)
    if not video_parts:
        raise HTTPException(status_code=500, detail="Could not fetch video parts.")

    target_part = None
    for part in video_parts:
        if part['page'] == page_number:
            target_part = part
            break
    
    if not target_part:
        raise HTTPException(status_code=404, detail=f"Page number {page_number} not found for this BV ID.")

    clean_name = re.sub(r'[\\/*?:"<>|]', "", target_part['part'])
    final_video_path = folder_path / f"{clean_name}.mp4"

    # If file exists, return its path immediately.
    if final_video_path.exists():
        return {"status": "ready", "video_url": f"/static/{folder_name}/{final_video_path.name}"}

    # If file does not exist, start download and return a "pending" status.
    # The frontend will need to poll or wait.
    try:
        # Using a synchronous function in a thread pool
        await asyncio.to_thread(download_and_merge, bvid, target_part, folder_path)
        return {"status": "ready", "video_url": f"/static/{folder_name}/{final_video_path.name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download video: {str(e)}")


@app.get("/static/{folder_name}/{file_name}")
async def serve_static_video(folder_name: str, file_name: str):
    """Serves the video files statically."""
    file_path = VIDEOS_DIR / folder_name / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(file_path)

@app.get("/covers/{file_name}")
async def serve_cover_image(file_name: str):
    """Serves the cover images statically."""
    file_path = COVERS_DIR / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Cover image not found.")
    return FileResponse(file_path)

# --- Frontend Routes ---
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """服务前端主页"""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding='utf-8'))
    return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)

@app.get("/{file_path:path}")
async def serve_frontend_files(file_path: str):
    """服务前端静态文件"""
    file = FRONTEND_DIR / file_path
    if file.exists() and file.is_file():
        # 为前端文件添加缓存控制头
        if file_path.endswith(('.js', '.css')):
            headers = {
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
            return FileResponse(file, headers=headers)
        return FileResponse(file)
    # 如果文件不存在，返回主页（用于SPA路由）
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding='utf-8'))
    return HTMLResponse("<h1>File not found</h1>", status_code=404)

# --- Main Execution ---
if __name__ == "__main__":
    import uvicorn
    print("🎬 儿童视频播放器服务器启动中...")
    print(f"📁 视频目录: {VIDEOS_DIR.resolve()}")
    print(f"🌐 前端目录: {FRONTEND_DIR.resolve()}")
    print("🚀 服务地址: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)