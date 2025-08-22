import asyncio
from pathlib import Path
from typing import List, Dict
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from . import bilibili
from . import utils
from .config import VIDEOS_DIR, COVERS_DIR, SUBTITLES_DIR

router = APIRouter()

# --- API Endpoints ---

@router.get("/api/folders", response_class=JSONResponse)
async def list_folders(path: str = ""):
    """Gets the list of subfolders in a given path."""
    base_path = VIDEOS_DIR
    if path:
        target_path = base_path / path
        if not target_path.is_dir():
            raise HTTPException(status_code=404, detail="Folder not found")
    else:
        target_path = base_path

    folders = []
    for item in target_path.iterdir():
        if item.is_dir():
            relative_path = str(item.relative_to(base_path)).replace('\\', '/')
            folders.append({
                "name": item.name,
                "path": relative_path,
                "has_list_file": (item / "list.txt").exists()
            })

    return utils.sort_folders_chinese(folders)

@router.get("/api/folders/{folder_path:path}", response_class=JSONResponse)
async def list_videos_in_folder(folder_path: str):
    """Gets the list of videos in a folder based on its list.txt."""
    list_file = VIDEOS_DIR / folder_path / "list.txt"
    if not list_file.exists():
        raise HTTPException(status_code=404, detail="'list.txt' not found")

    with open(list_file, 'r', encoding='utf-8') as f:
        bvid_line = next((line.strip() for line in f if line.strip() and not line.startswith('#')), None)

    if not bvid_line:
        raise HTTPException(status_code=404, detail="'list.txt' is empty")

    bvid = utils.extract_bvid_from_url(bvid_line)
    video_parts = await bilibili.get_video_parts_async(bvid)
    if not video_parts:
        raise HTTPException(status_code=500, detail="Could not fetch video parts")

    # Return basic info first for quick loading
    return [{
        "title": part['part'],
        "page": part['page'],
        "duration": part.get('duration', 0),
        "cid": part['cid'],
        "bvid": bvid,
    } for part in video_parts]

@router.get("/api/folders/{folder_path:path}/details", response_class=JSONResponse)
async def get_videos_details(folder_path: str):
    """Gets detailed info for videos (covers, subtitles)."""
    list_file = VIDEOS_DIR / folder_path / "list.txt"
    if not list_file.exists(): raise HTTPException(404, "'list.txt' not found")

    with open(list_file, 'r', encoding='utf-8') as f:
        bvid_line = next((l.strip() for l in f if l.strip() and not l.startswith('#')), None)
    if not bvid_line: raise HTTPException(404, "'list.txt' is empty")

    bvid = utils.extract_bvid_from_url(bvid_line)
    video_parts = await bilibili.get_video_parts_with_covers_async(bvid)
    if not video_parts: raise HTTPException(500, "Could not fetch detailed video parts")

    tasks = [
        bilibili.check_subtitle_availability_async(bvid, p['cid']) for p in video_parts
    ]
    sub_avail = await asyncio.gather(*tasks)

    return [{
        "page": part['page'],
        "cover_source": part.get('first_frame', ''),
        "has_subtitle": sub_avail[i]
    } for i, part in enumerate(video_parts)]


@router.get("/api/batch/covers/{bvid}", response_class=JSONResponse)
async def get_batch_covers(bvid: str, pages: str):
    """Gets multiple covers in one batch request."""
    try:
        page_numbers = [int(p) for p in pages.split(',') if p.isdigit()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid page numbers")

    video_parts = await bilibili.get_video_parts_with_covers_async(bvid)
    if not video_parts:
        return {"covers": {}}

    page_to_cover = {p['page']: p.get('first_frame', '') for p in video_parts}

    tasks = {
        p_num: bilibili.download_and_cache_cover_async(bvid, p_num, page_to_cover.get(p_num, ''))
        for p_num in page_numbers if page_to_cover.get(p_num)
    }

    results = await asyncio.gather(*tasks.values())

    return {"covers": {list(tasks.keys())[i]: url for i, url in enumerate(results) if url}}


@router.get("/api/play/{folder_path:path}/{page_number}", response_class=JSONResponse)
async def play_video(folder_path: str, page_number: int):
    list_file = VIDEOS_DIR / folder_path / "list.txt"
    if not list_file.exists(): raise HTTPException(404, "'list.txt' not found")

    with open(list_file, 'r', encoding='utf-8') as f:
        bvid_line = next((l.strip() for l in f if l.strip() and not l.startswith('#')), None)
    if not bvid_line: raise HTTPException(404, "'list.txt' is empty")

    bvid = utils.extract_bvid_from_url(bvid_line)
    video_parts = await bilibili.get_video_parts_async(bvid)
    if not video_parts: raise HTTPException(500, "Could not fetch video parts")

    target_part = next((p for p in video_parts if p['page'] == page_number), None)
    if not target_part: raise HTTPException(404, "Page not found")

    clean_name = utils.sanitize_filename(target_part['part'])
    final_video_path = VIDEOS_DIR / folder_path / f"{clean_name}.mp4"

    if not final_video_path.exists():
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, bilibili.download_and_merge_video, bvid, target_part, VIDEOS_DIR / folder_path
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to download video: {e}")

    subtitle_url = await bilibili.download_and_cache_subtitle_async(bvid, page_number, target_part['cid'])

    return {
        "status": "ready",
        "video_url": f"/static/{folder_path}/{final_video_path.name}",
        "subtitle_url": subtitle_url
    }

@router.get("/api/subtitle/{folder_path:path}/{page_number}", response_class=JSONResponse)
async def get_subtitle(folder_path: str, page_number: int):
    list_file = VIDEOS_DIR / folder_path / "list.txt"
    if not list_file.exists(): raise HTTPException(404, "'list.txt' not found")

    with open(list_file, 'r', encoding='utf-8') as f:
        bvid_line = next((l.strip() for l in f if l.strip() and not l.startswith('#')), None)
    if not bvid_line: raise HTTPException(404, "'list.txt' is empty")

    bvid = utils.extract_bvid_from_url(bvid_line)
    video_parts = await bilibili.get_video_parts_async(bvid)
    if not video_parts: raise HTTPException(500, "Could not fetch video parts")

    target_part = next((p for p in video_parts if p['page'] == page_number), None)
    if not target_part: raise HTTPException(404, "Page not found")

    subtitle_path = await bilibili.download_and_cache_subtitle_async(bvid, page_number, target_part['cid'])
    if not subtitle_path:
        raise HTTPException(404, "No subtitle available")

    return {"subtitle_url": subtitle_path}

# --- Static File Serving ---

@router.get("/static/{folder_path:path}/{file_name}", response_class=FileResponse)
async def serve_static_video(folder_path: str, file_name: str):
    file_path = VIDEOS_DIR / folder_path / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)

@router.get("/covers/{file_name}", response_class=FileResponse)
async def serve_cover_image(file_name: str):
    file_path = COVERS_DIR / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Cover image not found")
    return FileResponse(file_path)

@router.get("/subtitles/{file_name}", response_class=FileResponse)
async def serve_subtitle_file(file_name: str):
    file_path = SUBTITLES_DIR / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle file not found")
    return FileResponse(file_path, media_type="text/vtt")

@router.get("/api/cover/{bvid}/{page_number}", response_class=JSONResponse)
async def get_single_cover(bvid: str, page_number: int):
    """
    Asynchronously gets a single video cover. This endpoint is called by the frontend
    to lazy-load cover images.
    """
    try:
        # Check if the cover is already cached
        cover_filename = f"{bvid}_p{page_number}.jpg"
        cover_path = COVERS_DIR / cover_filename
        if cover_path.exists():
            return {"cover_url": f"/covers/{cover_filename}", "cached": True}

        # If not cached, fetch video part details to find the cover URL
        video_parts = await bilibili.get_video_parts_with_covers_async(bvid)
        if not video_parts:
            return {"cover_url": "", "cached": False}

        target_part = next((p for p in video_parts if p['page'] == page_number), None)
        if not target_part or not target_part.get('first_frame'):
            return {"cover_url": "", "cached": False}

        # Download and cache the cover
        cover_url = await bilibili.download_and_cache_cover_async(
            bvid, page_number, target_part['first_frame']
        )
        return {"cover_url": cover_url, "cached": False}

    except Exception as e:
        print(f"Error getting single cover: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve cover")
