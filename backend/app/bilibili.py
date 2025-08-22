import os
import re
import subprocess
import requests
import json
import time
import asyncio
import aiohttp
import random
import threading
from functools import reduce
from hashlib import md5
from pathlib import Path
from typing import Optional, Dict, List, Any

from .config import (
    BILIBILI_COOKIE, HEADERS, COVERS_DIR, SUBTITLES_DIR,
    MAX_CONCURRENT_OUTBOUND, MAX_QPS, MAX_COOLDOWN_SECONDS
)
from .utils import sanitize_filename, format_webvtt_time

# --- Globals for Bilibili Client ---

# Global async HTTP client session
_http_session: Optional[aiohttp.ClientSession] = None

# In-memory caches
_video_parts_cache: Dict[str, Any] = {}
_wbi_key_cache: Dict[str, Any] = {'key': None, 'timestamp': 0}

# --- Request Throttling and Concurrency Control ---

_outbound_sem = asyncio.Semaphore(MAX_CONCURRENT_OUTBOUND)
_outbound_lock = asyncio.Lock()
_next_earliest_ts = 0.0

_sync_lock = threading.Lock()
_sync_next_earliest_ts = 0.0

_cooldowns: Dict[str, float] = {}

def _get_endpoint_key(url: str) -> str:
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        parts = p.path.strip('/').split('/')
        head = '/'.join(parts[:2]) if parts else ''
        return f"{p.scheme}://{p.netloc}/{head}"
    except Exception:
        return url

def _is_in_cooldown(url: str) -> bool:
    now = time.monotonic()
    key = _get_endpoint_key(url)
    return now < _cooldowns.get(key, 0.0)

def _set_cooldown(url: str, base_seconds: float):
    now = time.monotonic()
    key = _get_endpoint_key(url)
    current_cooldown = _cooldowns.get(key, 0.0)
    # Exponential backoff, capped at max cooldown
    target_cooldown = now + min(base_seconds, MAX_COOLDOWN_SECONDS)
    if target_cooldown > current_cooldown:
        _cooldowns[key] = target_cooldown

def _jitter(seconds: float) -> float:
    return max(0.0, seconds + random.uniform(-seconds * 0.2, seconds * 0.2))

async def _wait_for_qps_window():
    global _next_earliest_ts
    async with _outbound_lock:
        now = time.monotonic()
        min_gap = 1.0 / max(MAX_QPS, 0.001)
        wait_time = max(0.0, _next_earliest_ts - now)
        if wait_time > 0:
            await asyncio.sleep(wait_time)
        _next_earliest_ts = time.monotonic() + _jitter(min_gap)

async def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(ssl=False)
        _http_session = aiohttp.ClientSession(headers=HEADERS, timeout=timeout, connector=connector)
    return _http_session

async def close_http_session():
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None

async def limited_get_async(url: str, **kwargs) -> Optional[aiohttp.ClientResponse]:
    if _is_in_cooldown(url): return None
    session = await get_http_session()
    backoff = 1.0
    for attempt in range(3):
        async with _outbound_sem:
            await _wait_for_qps_window()
            try:
                resp = await session.get(url, **kwargs)
                if resp.status == 200: return resp
                if resp.status in (429, 403, 412):
                    _set_cooldown(url, 60.0 * (2 ** attempt))
                    await resp.release()
                    return None
                if resp.status >= 500: # Server error, worth retrying
                    pass
                else: # Client error, not worth retrying
                    await resp.release()
                    return None
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
        await asyncio.sleep(_jitter(backoff))
        backoff = min(backoff * 2, 15.0)
    return None

# --- WBI Signing ---
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

def get_mixin_key(orig: str):
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, '')[:32]

async def get_wbi_keys_async() -> Optional[str]:
    now = time.time()
    if _wbi_key_cache['key'] and (now - _wbi_key_cache['timestamp'] < 300):
        return _wbi_key_cache['key']

    headers = {'Cookie': BILIBILI_COOKIE} if BILIBILI_COOKIE else {}
    async with await limited_get_async('https://api.bilibili.com/x/web-interface/nav', headers=headers) as resp:
        if not resp: return None
        data = await resp.json()
        img_url = data.get('data', {}).get('wbi_img', {}).get('img_url', '')
        sub_url = data.get('data', {}).get('wbi_img', {}).get('sub_url', '')
        img_key = img_url.rsplit('/', 1)[-1].split('.')[0]
        sub_key = sub_url.rsplit('/', 1)[-1].split('.')[0]
        wbi_key = get_mixin_key(img_key + sub_key)
        _wbi_key_cache['key'] = wbi_key
        _wbi_key_cache['timestamp'] = now
        return wbi_key

def sign_wbi_params(params: dict, wbi_key: str) -> dict:
    params['wts'] = str(int(time.time()))
    sorted_params = dict(sorted(params.items()))
    query = '&'.join([f"{k}={v}" for k, v in sorted_params.items()])
    w_rid = md5((query + wbi_key).encode()).hexdigest()
    params['w_rid'] = w_rid
    return params

# --- Bilibili Data Fetching ---

async def get_video_parts_with_covers_async(bvid: str) -> Optional[List[Dict]]:
    cache_key = f"parts_covers_{bvid}"
    if cache_key in _video_parts_cache: return _video_parts_cache[cache_key]

    url = f"https://www.bilibili.com/video/{bvid}"
    async with await limited_get_async(url) as resp:
        if not resp: return None
        html = await resp.text()
        match = re.search(r'window\.__INITIAL_STATE__=(.*?);\(function\(\)', html)
        if not match: return None
        data = json.loads(match.group(1))
        pages = data.get('videoData', {}).get('pages', [])
        _video_parts_cache[cache_key] = pages
        return pages

async def get_video_parts_async(bvid: str) -> Optional[List[Dict]]:
    cache_key = f"parts_{bvid}"
    if cache_key in _video_parts_cache: return _video_parts_cache[cache_key]

    params = {'bvid': bvid, 'jsonp': 'jsonp'}
    async with await limited_get_async('https://api.bilibili.com/x/player/pagelist', params=params) as resp:
        if not resp: return None
        data = await resp.json()
        if data.get('code') == 0:
            parts = data['data']
            _video_parts_cache[cache_key] = parts
            return parts
    return None

async def download_and_cache_cover_async(bvid: str, page: int, cover_url: str) -> str:
    if not cover_url: return ""
    if cover_url.startswith('//'): cover_url = 'http:' + cover_url

    filename = f"{bvid}_p{page}.jpg"
    filepath = COVERS_DIR / filename
    if filepath.exists(): return f"/covers/{filename}"

    async with await limited_get_async(cover_url) as resp:
        if not resp: return ""
        content = await resp.read()
        with open(filepath, 'wb') as f:
            f.write(content)
        return f"/covers/{filename}"

async def check_subtitle_availability_async(bvid: str, cid: int) -> bool:
    if not BILIBILI_COOKIE: return False
    wbi_key = await get_wbi_keys_async()
    if not wbi_key: return False

    params = sign_wbi_params({'bvid': bvid, 'cid': cid}, wbi_key)
    api_url = "https://api.bilibili.com/x/player/wbi/v2"
    headers = {'Cookie': BILIBILI_COOKIE}

    async with await limited_get_async(api_url, params=params, headers=headers) as resp:
        if not resp: return False
        data = await resp.json()
        if data.get('code') != 0: return False
        subtitles = data.get('data', {}).get('subtitle', {}).get('subtitles', [])
        return any(s.get('ai_type') == 0 and s.get('subtitle_url') for s in subtitles)

async def download_and_cache_subtitle_async(bvid: str, page: int, cid: int) -> str:
    filename = f"{bvid}_p{page}.vtt"
    filepath = SUBTITLES_DIR / filename
    if filepath.exists(): return f"/subtitles/{filename}"
    if not BILIBILI_COOKIE: return ""

    wbi_key = await get_wbi_keys_async()
    if not wbi_key: return ""

    params = sign_wbi_params({'bvid': bvid, 'cid': cid}, wbi_key)
    api_url = "https://api.bilibili.com/x/player/wbi/v2"
    headers = {'Cookie': BILIBILI_COOKIE}

    async with await limited_get_async(api_url, params=params, headers=headers) as resp:
        if not resp: return ""
        data = await resp.json()
        user_sub = next((s for s in data.get('data', {}).get('subtitle', {}).get('subtitles', []) if s.get('ai_type') == 0), None)
        if not user_sub: return ""

        sub_url = user_sub.get('subtitle_url', '')
        if sub_url.startswith('//'): sub_url = 'https:' + sub_url

        async with await limited_get_async(sub_url) as sub_resp:
            if not sub_resp: return ""
            content = await sub_resp.json()
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("WEBVTT\n\n")
                for line in content.get('body', []):
                    start = format_webvtt_time(line.get('from', 0))
                    end = format_webvtt_time(line.get('to', 0))
                    f.write(f"{start} --> {end}\n{line.get('content', '')}\n\n")
            return f"/subtitles/{filename}"
    return ""

def download_and_merge_video(bvid: str, p_info: dict, target_dir: Path):
    # This function remains synchronous as it involves subprocess calls
    # which are blocking. It will be run in a thread pool.
    clean_name = sanitize_filename(p_info['part'])
    final_video_path = target_dir / f"{clean_name}.mp4"
    if final_video_path.exists(): return str(final_video_path)

    # Simplified sync request logic for this specific path
    def get_sync(url, **kwargs):
        try:
            return requests.get(url, headers=HEADERS, timeout=30, **kwargs)
        except requests.RequestException:
            return None

    # 1. Get Session
    session_url = f'https://www.bilibili.com/video/{bvid}?p={p_info["page"]}'
    session_resp = get_sync(session_url)
    if not session_resp or not (match := re.search(r'"session":"(.*?)"', session_resp.text)):
        raise Exception("Failed to get session")
    session = match.group(1)

    # 2. Get Play URLs
    play_params = {'cid': p_info['cid'], 'bvid': bvid, 'qn': '80', 'fnver': '0', 'fnval': '976', 'session': session}
    play_resp = get_sync('https://api.bilibili.com/x/player/playurl', params=play_params)
    if not play_resp or play_resp.json().get('code') != 0:
        raise Exception("Failed to get play URLs")

    play_data = play_resp.json()['data']['dash']
    audio_url = play_data['audio'][0]['baseUrl']
    video_url = play_data['video'][0]['baseUrl']

    # 3. Download
    temp_audio_path = target_dir / f"{clean_name}_audio.mp3"
    temp_video_path = target_dir / f"{clean_name}_video.mp4"
    with open(temp_audio_path, 'wb') as f: f.write(get_sync(audio_url).content)
    with open(temp_video_path, 'wb') as f: f.write(get_sync(video_url).content)

    # 4. Merge
    cmd = ['ffmpeg', '-i', str(temp_video_path), '-i', str(temp_audio_path), '-c', 'copy', str(final_video_path)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        # Cleanup and re-raise
        temp_audio_path.unlink(missing_ok=True)
        temp_video_path.unlink(missing_ok=True)
        raise Exception(f"ffmpeg failed: {e.stderr}") from e

    # 5. Cleanup
    temp_audio_path.unlink(missing_ok=True)
    temp_video_path.unlink(missing_ok=True)
    return str(final_video_path)
