import os
import re
import subprocess
import requests
import json
import time
import locale
from functools import reduce
from hashlib import md5
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import asyncio
import aiohttp
from typing import Optional, Dict, List, Any
import random
import threading

# 导入配置
try:
    from config import BILIBILI_COOKIE
except ImportError:
    BILIBILI_COOKIE = ""
    print("警告: 未找到config.py文件，字幕功能将不可用")

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent.parent
VIDEOS_DIR = BASE_DIR / "videos"
FRONTEND_DIR = BASE_DIR / "frontend"
COVERS_DIR = BASE_DIR / "covers"  # 封面缓存目录
SUBTITLES_DIR = BASE_DIR / "subtitles"  # 字幕缓存目录
# Ensure the main directories exist
VIDEOS_DIR.mkdir(exist_ok=True)
COVERS_DIR.mkdir(exist_ok=True)
SUBTITLES_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Video Player Backend")

# 设置locale以支持中文排序
try:
    locale.setlocale(locale.LC_COLLATE, 'zh_CN.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_COLLATE, 'Chinese (Simplified)_China.936')
    except locale.Error:
        try:
            locale.setlocale(locale.LC_COLLATE, 'zh_CN')
        except locale.Error:
            # 如果都失败了，使用默认排序
            pass

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

# 中文友好的排序函数
def chinese_sort_key(text: str) -> str:
    """生成中文友好的排序键"""
    import unicodedata
    # 将中文字符转换为拼音或者使用Unicode序号
    normalized = unicodedata.normalize('NFKD', text)
    # 简单的排序策略：数字优先，然后是字母，最后是中文
    result = []
    for char in normalized:
        if char.isdigit():
            result.append(('0', char))  # 数字排在最前
        elif char.isascii() and char.isalpha():
            result.append(('1', char.lower()))  # 字母排在中间
        else:
            result.append(('2', char))  # 中文等其他字符排在最后
    return result

def sort_folders_chinese(folders: List[dict]) -> List[dict]:
    """按中文友好的方式排序文件夹"""
    try:
        # 尝试使用locale排序
        return sorted(folders, key=lambda x: locale.strxfrm(x['name']))
    except (AttributeError, TypeError):
        # 如果locale排序失败，使用自定义排序
        return sorted(folders, key=lambda x: chinese_sort_key(x['name']))

# --- Bilibili Downloader Logic (Adapted from 1.py) ---

HEADERS = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36',
    'referer': 'https://www.bilibili.com/'
}

# 全局异步HTTP客户端
_http_session: Optional[aiohttp.ClientSession] = None

# 内存缓存
_video_parts_cache: Dict[str, Any] = {}
_wbi_key_cache: Optional[str] = None
_wbi_key_cache_time: float = 0

# --- Outbound request limiting & backoff ---
# 最大并发外呼数（根据实际情况微调）
_MAX_CONCURRENT_OUTBOUND = int(os.getenv("OUTBOUND_MAX_CONCURRENCY", "3"))
# 目标每秒请求数（全局），通过请求间隔实现（带抖动）
_MAX_QPS = float(os.getenv("OUTBOUND_MAX_QPS", "2"))  # e.g. 2 req/s -> 500ms 基准间隔
# 429/403 冷却秒数上限（指数退避中的最大冷却）
_MAX_COOLDOWN_SECONDS = int(os.getenv("OUTBOUND_MAX_COOLDOWN", "300"))

# 异步并发控制与时序控制
_outbound_sem = asyncio.Semaphore(_MAX_CONCURRENT_OUTBOUND)
_outbound_lock = asyncio.Lock()  # 保护时间间隔调度
_next_earliest_ts = 0.0  # 单位：monotonic 秒

# 同步代码路径（requests）用的锁与时序控制
_sync_lock = threading.Lock()
_sync_next_earliest_ts = 0.0

# 针对特定端点的冷却窗口，key 可用为 URL 前缀
_cooldowns: Dict[str, float] = {}

def _endpoint_key(url: str) -> str:
    # 简化：取主机+路径的前两段作为 key，避免过细颗粒度
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        parts = p.path.strip('/').split('/')
        head = '/'.join(parts[:2]) if parts else ''
        return f"{p.scheme}://{p.netloc}/{head}"
    except Exception:
        return url

def _in_cooldown(url: str) -> bool:
    now = time.monotonic()
    key = _endpoint_key(url)
    until = _cooldowns.get(key, 0.0)
    return now < until

def _set_cooldown(url: str, base_seconds: float) -> None:
    # 叠加冷却到不超过最大上限
    now = time.monotonic()
    key = _endpoint_key(url)
    current = _cooldowns.get(key, 0.0)
    target = now + min(base_seconds, _MAX_COOLDOWN_SECONDS)
    if target > current:
        _cooldowns[key] = target

def _jitter(seconds: float) -> float:
    # 抖动：±20%
    delta = seconds * 0.2
    return max(0.0, seconds + random.uniform(-delta, delta))

async def _await_global_qps_window():
    global _next_earliest_ts
    async with _outbound_lock:
        now = time.monotonic()
        min_gap = 1.0 / max(_MAX_QPS, 0.0001)
        wait = max(0.0, _next_earliest_ts - now)
        if wait > 0:
            await asyncio.sleep(wait)
        # 设定下一次最早时间点（带抖动）
        _next_earliest_ts = time.monotonic() + _jitter(min_gap)

async def limited_get(url: str, params: Optional[Dict]=None, headers: Optional[Dict]=None, retries: int=3) -> Optional[aiohttp.ClientResponse]:
    """带并发限制、QPS 间隔、退避与冷却的 GET（aiohttp）。返回已打开的响应对象或 None。"""
    if _in_cooldown(url):
        return None
    session = await get_http_session()
    last_exc: Optional[Exception] = None
    backoff = 0.5  # 初始退避基准（秒）
    for attempt in range(retries):
        async with _outbound_sem:
            await _await_global_qps_window()
            try:
                resp = await session.get(url, params=params, headers=headers)
                if resp.status == 200:
                    return resp
                # 对 429/403：进入冷却并立即结束（避免 hammer）
                if resp.status in (429, 403):
                    # 以 60s * 2^attempt 递增，封顶 _MAX_COOLDOWN_SECONDS
                    _set_cooldown(url, 60.0 * (2 ** attempt))
                    await resp.release()
                    return None
                # 其它 5xx 可退避重试；4xx（非429/403）直接放弃
                if 500 <= resp.status < 600:
                    last_exc = Exception(f"HTTP {resp.status}")
                else:
                    await resp.release()
                    return None
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exc = e
        # 退避等待（带抖动）
        await asyncio.sleep(_jitter(backoff))
        backoff = min(backoff * 2, 8.0)
    return None

def limited_get_sync(url: str, params: Optional[Dict]=None, headers: Optional[Dict]=None, timeout: int=15, retries: int=3):
    """同步路径的受限 GET（requests），带并发间隔与退避。由于 GIL，我们仅实现 QPS 间隔与冷却，不做并发信号量。"""
    if _in_cooldown(url):
        return None
    last_exc: Optional[Exception] = None
    backoff = 0.5
    for attempt in range(retries):
        # 全局 QPS 控制（同步）
        with _sync_lock:
            global _sync_next_earliest_ts
            now = time.monotonic()
            min_gap = 1.0 / max(_MAX_QPS, 0.0001)
            wait = max(0.0, _sync_next_earliest_ts - now)
            if wait > 0:
                time.sleep(wait)
            _sync_next_earliest_ts = time.monotonic() + _jitter(min_gap)
        try:
            resp = requests.get(url, params=params, headers=headers or HEADERS, timeout=timeout)
            status = resp.status_code
            if status == 200:
                return resp
            if status in (429, 403):
                _set_cooldown(url, 60.0 * (2 ** attempt))
                return None
            if 500 <= status < 600:
                last_exc = Exception(f"HTTP {status}")
            else:
                return None
        except requests.exceptions.RequestException as e:
            last_exc = e
        time.sleep(_jitter(backoff))
        backoff = min(backoff * 2, 8.0)
    return None

async def get_http_session() -> aiohttp.ClientSession:
    """获取全局HTTP会话"""
    global _http_session
    if _http_session is None or _http_session.closed:
        timeout = aiohttp.ClientTimeout(total=15)
        connector = aiohttp.TCPConnector(ssl=False)  # 禁用SSL验证
        _http_session = aiohttp.ClientSession(
            headers=HEADERS,
            timeout=timeout,
            connector=connector
        )
    return _http_session

async def close_http_session():
    """关闭HTTP会话"""
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None



# WBI签名相关常量和函数
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

def get_mixin_key(orig: str):
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, '')[:32]

async def get_wbi_keys_async(cookie: Optional[str] = None) -> Optional[str]:
    """异步获取WBI密钥，带缓存"""
    global _wbi_key_cache, _wbi_key_cache_time

    # 检查缓存（5分钟有效期）
    current_time = time.time()
    if _wbi_key_cache and (current_time - _wbi_key_cache_time) < 300:
        return _wbi_key_cache

    try:
        session = await get_http_session()
        headers = {}
        if cookie:
            headers['Cookie'] = cookie

        async with session.get('https://api.bilibili.com/x/web-interface/nav', headers=headers) as response:
            if response.status == 200:
                json_content = await response.json()
                img_url: str = json_content['data']['wbi_img']['img_url']
                sub_url: str = json_content['data']['wbi_img']['sub_url']
                img_key = img_url.rsplit('/', 1)[1].split('.')[0]
                sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]

                wbi_key = get_mixin_key(img_key + sub_key)

                # 更新缓存
                _wbi_key_cache = wbi_key
                _wbi_key_cache_time = current_time

                return wbi_key
    except Exception as e:
        print(f"异步获取WBI密钥失败: {e}")
    return None

def get_wbi_keys(cookie=None):
    try:
        headers = HEADERS.copy()
        if cookie:
            headers['Cookie'] = cookie
        resp = requests.get('https://api.bilibili.com/x/web-interface/nav', headers=headers)
        resp.raise_for_status()
        json_content = resp.json()
        img_url: str = json_content['data']['wbi_img']['img_url']
        sub_url: str = json_content['data']['wbi_img']['sub_url']
        img_key = img_url.rsplit('/', 1)[1].split('.')[0]
        sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
        return get_mixin_key(img_key + sub_key)
    except Exception as e:
        print(f"获取WBI密钥失败: {e}")
        return None

def sign_wbi_params(params: dict, wbi_key: str):
    params['wts'] = str(int(time.time()))
    sorted_params = dict(sorted(params.items()))
    query_parts = []
    for k, v in sorted_params.items():
        v_str = str(v).replace("'", "").replace("!", "").replace("(", "").replace(")", "").replace("*", "")
        query_parts.append(f'{k}={v_str}')
    query_string = '&'.join(query_parts)
    w_rid = md5((query_string + wbi_key).encode()).hexdigest()
    params['w_rid'] = w_rid
    return params

def convert_seconds_to_lrc_time(seconds):
    millisec = int((seconds - int(seconds)) * 100)
    minutes = int(seconds // 60)
    sec = int(seconds % 60)
    return f"[{minutes:02d}:{sec:02d}.{millisec:02d}]"

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

async def get_bilibili_response_async(url: str, params: Optional[Dict] = None, retries: int = 3) -> Optional[aiohttp.ClientResponse]:
    """异步发送请求到B站API端点，支持重试、并发限制与退避。"""
    resp = await limited_get(url, params=params, headers=None, retries=retries)
    if not resp:
        print(f"异步请求失败或被限流: {url}")
    return resp

def get_bilibili_response(url, params=None, retries: int = 3):
    """发送请求到B站API端点（同步路径），带退避/QPS 间隔/冷却。"""
    resp = limited_get_sync(url, params=params, headers=HEADERS, timeout=15, retries=retries)
    if not resp:
        print(f"请求失败或被限流: {url}")
    return resp

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

async def get_video_parts_with_covers_async(bvid: str) -> Optional[List[Dict]]:
    """异步获取视频分P信息和封面，带缓存与外呼限流"""
    # 检查缓存
    cache_key = f"parts_covers_{bvid}"
    if cache_key in _video_parts_cache:
        return _video_parts_cache[cache_key]

    try:
        url = f"https://www.bilibili.com/video/{bvid}"
        response = await limited_get(url)
        if not response:
            return None
        html_content = await response.text()

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

        # 缓存结果
        _video_parts_cache[cache_key] = enhanced_parts
        return enhanced_parts

    except (json.JSONDecodeError, Exception) as e:
        print(f"异步获取视频信息失败: {e}")
        return None

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

async def get_video_parts_async(bvid: str) -> Optional[List[Dict]]:
    """异步获取视频分P基本信息，带缓存与外呼限流"""
    # 检查缓存
    cache_key = f"parts_{bvid}"
    if cache_key in _video_parts_cache:
        return _video_parts_cache[cache_key]

    try:
        url = 'https://api.bilibili.com/x/player/pagelist'
        params = {'bvid': bvid, 'jsonp': 'jsonp'}

        response = await limited_get(url, params=params)
        if response and response.status == 200:
            data = await response.json()
            if data['code'] == 0:
                result = data['data']
                # 缓存结果
                _video_parts_cache[cache_key] = result
                return result
    except Exception as e:
        print(f"异步获取视频分P失败: {e}")
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

async def download_and_cache_cover_async(bvid: str, page: int, cover_url: str) -> str:
    """异步下载并缓存封面图片，返回本地路径（受限流管控）"""
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
        response = await limited_get(cover_url)
        if response and response.status == 200:
            content = await response.read()
            with open(cover_path, 'wb') as f:
                f.write(content)
            return f"/covers/{cover_filename}"
    except Exception as e:
        print(f"异步下载封面失败: {e}")

    return ""


async def check_subtitle_availability_async(bvid: str, page: int, cid: int) -> bool:
    """异步检查视频是否有字幕可用"""
    try:
        # 如果没有配置Cookie，直接返回False
        if not BILIBILI_COOKIE:
            return False

        # 获取WBI签名密钥
        wbi_key = await get_wbi_keys_async(BILIBILI_COOKIE)
        if not wbi_key:
            return False

        # 构建请求参数
        params = {'bvid': bvid, 'cid': cid}
        signed_params = sign_wbi_params(params, wbi_key)

        # 异步请求字幕API
        session = await get_http_session()
        player_api_url = "https://api.bilibili.com/x/player/wbi/v2"
        headers = {'Cookie': BILIBILI_COOKIE}

        async with session.get(player_api_url, params=signed_params, headers=headers) as response:
            if response.status != 200:
                return False

            subtitle_data = await response.json()
            if subtitle_data.get('code') != 0:
                return False

            subtitles_list = subtitle_data.get('data', {}).get('subtitle', {}).get('subtitles', [])
            # 检查是否有用户上传的字幕
            user_subtitle = next((s for s in subtitles_list if s.get('ai_type') == 0 and s.get('subtitle_url')), None)
            return user_subtitle is not None

    except Exception as e:
        print(f"异步检查字幕可用性失败: {e}")
        return False

async def check_subtitle_availability(bvid: str, page: int, cid: int) -> bool:
    """检查视频是否有字幕可用"""
    try:
        print(f"检查字幕可用性: bvid={bvid}, page={page}, cid={cid}")

        # 如果没有配置Cookie，直接返回False
        if not BILIBILI_COOKIE:
            print("未配置B站Cookie，字幕功能不可用")
            return False

        # 获取WBI签名密钥
        wbi_key = get_wbi_keys(BILIBILI_COOKIE)
        if not wbi_key:
            print("获取WBI密钥失败")
            return False

        # 构建请求参数
        params = {'bvid': bvid, 'cid': cid}
        signed_params = sign_wbi_params(params, wbi_key)

        print(f"请求参数: {signed_params}")

        # 请求字幕API，带上Cookie
        player_api_url = "https://api.bilibili.com/x/player/wbi/v2"
        headers = HEADERS.copy()
        headers['Cookie'] = BILIBILI_COOKIE

        response = limited_get_sync(player_api_url, params=signed_params, headers=headers)

        if not response:
            print("字幕API请求失败")
            return False

        subtitle_data = response.json()
        print(f"字幕API响应: code={subtitle_data.get('code')}, message={subtitle_data.get('message')}")

        if subtitle_data.get('code') != 0:
            print(f"字幕API返回错误: {subtitle_data.get('message')}")
            return False

        subtitles_list = subtitle_data.get('data', {}).get('subtitle', {}).get('subtitles', [])
        print(f"找到字幕列表: {len(subtitles_list)} 个")

        # 检查是否有用户上传的字幕
        user_subtitle = next((s for s in subtitles_list if s.get('ai_type') == 0 and s.get('subtitle_url')), None)

        has_subtitle = user_subtitle is not None
        print(f"用户字幕可用: {has_subtitle}")

        return has_subtitle

    except Exception as e:
        print(f"检查字幕可用性失败: {e}")
        return False



async def download_and_cache_subtitle(bvid: str, page: int, cid: int) -> str:
    """下载并缓存字幕文件，返回本地路径"""
    try:
        print(f"开始下载字幕: bvid={bvid}, page={page}, cid={cid}")

        # 生成字幕文件名
        subtitle_filename = f"{bvid}_p{page}.vtt"
        subtitle_path = SUBTITLES_DIR / subtitle_filename

        # 如果已经缓存，直接返回
        if subtitle_path.exists():
            print(f"字幕已缓存: {subtitle_filename}")
            return f"/subtitles/{subtitle_filename}"

        # 如果没有配置Cookie，直接返回空
        if not BILIBILI_COOKIE:
            print("未配置B站Cookie，无法下载字幕")
            return ""

        # 获取WBI签名密钥
        wbi_key = get_wbi_keys(BILIBILI_COOKIE)
        if not wbi_key:
            return ""

        # 构建请求参数
        params = {'bvid': bvid, 'cid': cid}
        signed_params = sign_wbi_params(params, wbi_key)

        # 请求字幕API，带上Cookie
        player_api_url = "https://api.bilibili.com/x/player/wbi/v2"
        headers = HEADERS.copy()
        headers['Cookie'] = BILIBILI_COOKIE

        response = requests.get(player_api_url, params=signed_params, headers=headers)

        if not response or response.status_code != 200:
            print("字幕API请求失败")
            return ""

        subtitle_data = response.json()
        if subtitle_data.get('code') != 0:
            print(f"字幕API返回错误: {subtitle_data.get('code')} - {subtitle_data.get('message')}")
            return ""

        subtitles_list = subtitle_data.get('data', {}).get('subtitle', {}).get('subtitles', [])
        # 查找用户上传的字幕
        user_subtitle = next((s for s in subtitles_list if s.get('ai_type') == 0 and s.get('subtitle_url')), None)

        if not user_subtitle:
            return ""

        # 下载字幕内容
        subtitle_url = user_subtitle.get('subtitle_url')
        if subtitle_url.startswith('//'):
            subtitle_url = 'https:' + subtitle_url

        subtitle_response = limited_get_sync(subtitle_url, headers=HEADERS)
        if not subtitle_response:
            return ""

        subtitle_content = subtitle_response.json()

        # 转换为WebVTT格式并保存
        with open(subtitle_path, 'w', encoding='utf-8') as f:
            f.write("WEBVTT\n\n")
            for line in subtitle_content.get('body', []):
                start_time = format_webvtt_time(line.get('from', 0))
                end_time = format_webvtt_time(line.get('to', 0))
                content = line.get('content', '')
                f.write(f"{start_time} --> {end_time}\n{content}\n\n")

        return f"/subtitles/{subtitle_filename}"

    except Exception as e:
        print(f"下载字幕失败: {e}")
        return ""

def format_webvtt_time(seconds):
    """将秒数转换为WebVTT时间格式"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"

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
    command = [
        'ffmpeg',
        '-i', str(temp_video_path),
        '-i', str(temp_audio_path),
        '-c', 'copy',
        str(final_video_path)
    ]
    try:
        subprocess.run(command, shell=False, check=True, capture_output=True, text=True)
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

def scan_folders_recursive(base_path: Path, current_path: Path = None, depth: int = 0, max_depth: int = 10) -> List[dict]:
    """递归扫描文件夹结构"""
    if current_path is None:
        current_path = base_path
    
    if depth > max_depth:
        return []
    
    folders = []
    
    try:
        for item in current_path.iterdir():
            if item.is_dir():
                # 计算相对路径
                relative_path = str(item.relative_to(base_path))
                parent_path = str(current_path.relative_to(base_path)) if current_path != base_path else ""
                
                # 检查是否有list.txt文件
                list_file = item / "list.txt"
                has_list_file = list_file.exists()
                
                # 递归扫描子文件夹
                children = scan_folders_recursive(base_path, item, depth + 1, max_depth)
                
                folder_info = {
                    "name": item.name,
                    "path": relative_path,
                    "parent_path": parent_path if parent_path else None,
                    "children": children,
                    "has_list_file": has_list_file,
                    "video_count": 0,
                    "downloaded_count": 0,
                    "depth": depth,
                    "is_folder": True
                }
                
                folders.append(folder_info)
    except PermissionError:
        pass
    
    # 对文件夹进行中文友好排序
    return sort_folders_chinese(folders)

@app.get("/api/folders")
async def list_folders(path: str = ""):
    """获取文件夹列表，支持嵌套路径"""
    if not VIDEOS_DIR.is_dir():
        return JSONResponse(content=[], headers={"Content-Type": "application/json; charset=utf-8"})
    
    # 确定要扫描的目录
    if path and path.strip():
        target_path = VIDEOS_DIR / path
        if not target_path.exists() or not target_path.is_dir():
            raise HTTPException(status_code=404, detail=f"Folder not found: {path}")
    else:
        target_path = VIDEOS_DIR
    
    # 直接扫描指定目录下的直接子文件夹
    folders = []
    try:
        for item in target_path.iterdir():
            if item.is_dir():
                relative_path = str(item.relative_to(VIDEOS_DIR)).replace('\\', '/')  # 确保使用正斜杠
                list_file = item / "list.txt"
                has_list_file = list_file.exists()
                
                folder_info = {
                    "name": item.name,
                    "path": relative_path,
                    "parent_path": path if path and path.strip() else None,
                    "children": [],
                    "has_list_file": has_list_file,
                    "video_count": 0,
                    "downloaded_count": 0,
                    "depth": len(path.split('/')) if path and path.strip() else 0,
                    "is_folder": True
                }
                folders.append(folder_info)
    except PermissionError:
        pass
    
    # 对文件夹进行中文友好排序
    sorted_folders = sort_folders_chinese(folders)
    return JSONResponse(content=sorted_folders, headers={"Content-Type": "application/json; charset=utf-8"})

@app.get("/api/folders/{folder_path:path}")
async def list_videos_in_folder(folder_path: str):
    """
    快速返回视频列表基本信息，实现分阶段加载
    第一阶段：立即返回基本信息（标题、分P数量）
    """
    target_folder = VIDEOS_DIR / folder_path
    list_file = target_folder / "list.txt"

    if not list_file.exists():
        raise HTTPException(status_code=404, detail=f"'list.txt' not found in folder '{folder_path}'")

    with open(list_file, 'r', encoding='utf-8') as f:
        bvid_lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    if not bvid_lines:
        raise HTTPException(status_code=404, detail=f"'list.txt' is empty or contains no valid BV IDs.")

    try:
        bvid = extract_bvid_from_url(bvid_lines[0])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 使用异步函数获取基本信息，优先尝试详细信息
    video_parts = await get_video_parts_async(bvid)
    if not video_parts:
        raise HTTPException(status_code=500, detail=f"Could not fetch video parts for BV ID: {bvid}")

    # 快速返回基本信息，不包含封面和详细信息
    enhanced_parts = []
    for part in video_parts:
        enhanced_parts.append({
            "title": part['part'],
            "page": part['page'],
            "cover_url": "",  # 稍后异步加载
            "duration": part.get('duration', 0),
            "cid": part['cid'],
            "bvid": bvid,
            "has_subtitle": None  # 稍后异步检查
        })

    return JSONResponse(content=enhanced_parts, headers={"Content-Type": "application/json; charset=utf-8"})

@app.get("/api/folders/{folder_path:path}/details")
async def get_videos_details(folder_path: str):
    """
    第二阶段：获取视频详细信息（封面、字幕状态等）
    """
    target_folder = VIDEOS_DIR / folder_path
    list_file = target_folder / "list.txt"

    if not list_file.exists():
        raise HTTPException(status_code=404, detail=f"'list.txt' not found in folder '{folder_path}'")

    with open(list_file, 'r', encoding='utf-8') as f:
        bvid_lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    if not bvid_lines:
        raise HTTPException(status_code=404, detail=f"'list.txt' is empty or contains no valid BV IDs.")

    try:
        bvid = extract_bvid_from_url(bvid_lines[0])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 获取详细信息（包含封面URL）
    video_parts = await get_video_parts_with_covers_async(bvid)
    if not video_parts:
        raise HTTPException(status_code=500, detail=f"Could not fetch detailed video parts for BV ID: {bvid}")

    # 返回详细信息
    detailed_parts = []
    for part in video_parts:
        # 异步检查字幕可用性
        has_subtitle = await check_subtitle_availability_async(bvid, part['page'], part['cid'])

        detailed_parts.append({
            "page": part['page'],
            "cover_source": part.get('cover_url', ''),
            "duration": part.get('duration', 0),
            "has_subtitle": has_subtitle
        })

    return JSONResponse(content=detailed_parts, headers={"Content-Type": "application/json; charset=utf-8"})

@app.get("/api/batch/covers/{bvid}")
async def get_batch_covers(bvid: str, pages: str):
    """
    批量获取多个分P的封面
    pages: 逗号分隔的页码，如 "1,2,3"
    """
    try:
        page_numbers = [int(p.strip()) for p in pages.split(',') if p.strip().isdigit()]
        if not page_numbers:
            return {"covers": {}}

        # 获取视频详细信息
        video_parts = await get_video_parts_with_covers_async(bvid)
        if not video_parts:
            return {"covers": {}}

        # 创建页码到封面URL的映射
        page_to_cover = {}
        for part in video_parts:
            if part['page'] in page_numbers:
                page_to_cover[part['page']] = part.get('cover_url', '')

        # 批量下载封面
        covers = {}
        for page_num in page_numbers:
            cover_url = page_to_cover.get(page_num, '')
            if cover_url:
                # 检查是否已缓存
                cover_filename = f"{bvid}_p{page_num}.jpg"
                cover_path = COVERS_DIR / cover_filename

                if cover_path.exists():
                    covers[str(page_num)] = f"/covers/{cover_filename}"
                else:
                    # 异步下载
                    downloaded_url = await download_and_cache_cover_async(bvid, page_num, cover_url)
                    if downloaded_url:
                        covers[str(page_num)] = downloaded_url

        return JSONResponse(content={"covers": covers}, headers={"Content-Type": "application/json; charset=utf-8"})

    except Exception as e:
        print(f"批量获取封面失败: {e}")
        return JSONResponse(content={"covers": {}}, headers={"Content-Type": "application/json; charset=utf-8"})



@app.get("/api/cover/{bvid}/{page_number}")
async def get_video_cover(bvid: str, page_number: int):
    """异步获取单个视频的封面，优化性能"""
    try:
        # 检查是否已经缓存
        cover_filename = f"{bvid}_p{page_number}.jpg"
        cover_path = COVERS_DIR / cover_filename

        if cover_path.exists():
            return JSONResponse(content={"cover_url": f"/covers/{cover_filename}", "cached": True}, headers={"Content-Type": "application/json; charset=utf-8"})

        # 使用异步函数获取视频信息
        video_parts = await get_video_parts_with_covers_async(bvid)
        if not video_parts:
            return JSONResponse(content={"cover_url": "", "cached": False}, headers={"Content-Type": "application/json; charset=utf-8"})

        # 找到对应的分P
        target_part = None
        for part in video_parts:
            if part['page'] == page_number:
                target_part = part
                break

        if not target_part or not target_part.get('cover_url'):
            return JSONResponse(content={"cover_url": "", "cached": False}, headers={"Content-Type": "application/json; charset=utf-8"})

        # 下载并缓存封面
        cover_url = await download_and_cache_cover_async(bvid, page_number, target_part['cover_url'])
        return JSONResponse(content={"cover_url": cover_url, "cached": False}, headers={"Content-Type": "application/json; charset=utf-8"})

    except Exception as e:
        print(f"获取封面失败: {e}")
        return JSONResponse(content={"cover_url": "", "cached": False}, headers={"Content-Type": "application/json; charset=utf-8"})

@app.post("/api/covers/preload")
async def preload_covers(request_data: dict):
    """
    预加载封面，用于提升用户体验
    request_data: {"bvid": "BV1xx", "pages": [1, 2, 3]}
    """
    try:
        bvid = request_data.get('bvid')
        pages = request_data.get('pages', [])

        if not bvid or not pages:
            return {"status": "error", "message": "Missing bvid or pages"}

        # 获取视频详细信息
        video_parts = await get_video_parts_with_covers_async(bvid)
        if not video_parts:
            return {"status": "error", "message": "Could not fetch video parts"}

        # 创建页码到封面URL的映射
        page_to_cover = {}
        for part in video_parts:
            if part['page'] in pages:
                page_to_cover[part['page']] = part.get('cover_url', '')

        # 异步预加载封面（不等待完成）
        preload_tasks = []
        for page_num in pages:
            cover_url = page_to_cover.get(page_num, '')
            if cover_url:
                # 检查是否已缓存
                cover_filename = f"{bvid}_p{page_num}.jpg"
                cover_path = COVERS_DIR / cover_filename

                if not cover_path.exists():
                    # 创建预加载任务
                    task = asyncio.create_task(
                        download_and_cache_cover_async(bvid, page_num, cover_url)
                    )
                    preload_tasks.append(task)

        # 启动预加载任务（不等待完成）
        if preload_tasks:
            asyncio.create_task(asyncio.gather(*preload_tasks, return_exceptions=True))

        return {"status": "success", "preloading": len(preload_tasks)}

    except Exception as e:
        print(f"预加载封面失败: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/play/{folder_path:path}/{page_number}")
async def play_video(folder_path: str, page_number: int):
    """
    播放视频，包含字幕检查（恢复原有功能）
    """
    target_folder = VIDEOS_DIR / folder_path
    list_file = target_folder / "list.txt"

    if not list_file.exists():
        raise HTTPException(status_code=404, detail=f"'list.txt' not found in folder '{folder_path}'")

    with open(list_file, 'r', encoding='utf-8') as f:
        bvid_lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    if not bvid_lines:
        raise HTTPException(status_code=404, detail="'list.txt' is empty.")

    try:
        bvid = extract_bvid_from_url(bvid_lines[0])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 使用异步函数获取视频分P信息
    video_parts = await get_video_parts_async(bvid)
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
    final_video_path = target_folder / f"{clean_name}.mp4"

    # 检查字幕可用性和获取字幕（恢复原有功能）
    has_subtitle = await check_subtitle_availability(bvid, page_number, target_part['cid'])
    subtitle_url = ""
    if has_subtitle:
        subtitle_url = await download_and_cache_subtitle(bvid, page_number, target_part['cid'])

    # If file exists, return its path immediately.
    if final_video_path.exists():
        return {
            "status": "ready",
            "video_url": f"/static/{folder_path}/{final_video_path.name}",
            "has_subtitle": has_subtitle,
            "subtitle_url": subtitle_url
        }

    # If file does not exist, start download and return a "pending" status.
    try:
        # 使用异步线程池下载
        await asyncio.to_thread(download_and_merge, bvid, target_part, target_folder)
        return {
            "status": "ready",
            "video_url": f"/static/{folder_path}/{final_video_path.name}",
            "has_subtitle": has_subtitle,
            "subtitle_url": subtitle_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download video: {str(e)}")




@app.get("/static/{folder_path:path}/{file_name}")
async def serve_static_video(folder_path: str, file_name: str):
    """Serves the video files statically."""
    file_path = VIDEOS_DIR / folder_path / file_name
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

@app.get("/subtitles/{file_name}")
async def serve_subtitle_file(file_name: str):
    """Serves the subtitle files statically."""
    file_path = SUBTITLES_DIR / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle file not found.")
    return FileResponse(file_path, media_type="text/vtt")

@app.get("/api/subtitle/{folder_path:path}/{page_number}")
async def get_subtitle(folder_path: str, page_number: int):
    """获取指定视频的字幕文件"""
    target_folder = VIDEOS_DIR / folder_path
    list_file = target_folder / "list.txt"

    if not list_file.exists():
        raise HTTPException(status_code=404, detail=f"'list.txt' not found in folder '{folder_path}'")

    with open(list_file, 'r', encoding='utf-8') as f:
        bvid_lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    if not bvid_lines:
        raise HTTPException(status_code=404, detail="'list.txt' is empty.")

    try:
        bvid = extract_bvid_from_url(bvid_lines[0])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 获取视频分P信息
    video_parts = get_video_parts_with_covers(bvid)
    if not video_parts:
        video_parts = get_video_parts(bvid)
        if not video_parts:
            raise HTTPException(status_code=500, detail="Could not fetch video parts.")

    # 找到对应的分P
    target_part = None
    for part in video_parts:
        if part['page'] == page_number:
            target_part = part
            break

    if not target_part:
        raise HTTPException(status_code=404, detail=f"Page number {page_number} not found.")

    # 下载并缓存字幕
    subtitle_path = await download_and_cache_subtitle(bvid, page_number, target_part['cid'])

    if not subtitle_path:
        raise HTTPException(status_code=404, detail="No subtitle available for this video.")

    return {"subtitle_url": subtitle_path}

@app.get("/api/recommendations")
async def get_recommendations():
    """
    获取推荐内容
    目前返回占位符数据，将来可以实现智能推荐算法
    """
    try:
        # 这里可以实现推荐算法，目前返回占位符数据
        recommendations = {
            "status": "success",
            "data": {
                "featured": {
                    "title": "今日推荐",
                    "items": [
                        {
                            "id": "rec_001",
                            "title": "精选儿童动画",
                            "description": "适合3-8岁儿童观看的优质动画内容",
                            "thumbnail": "/static/placeholders/animation.jpg",
                            "category": "动画",
                            "age_group": "3-8岁"
                        },
                        {
                            "id": "rec_002",
                            "title": "科学启蒙视频",
                            "description": "有趣的科学知识启蒙内容",
                            "thumbnail": "/static/placeholders/science.jpg",
                            "category": "教育",
                            "age_group": "6-12岁"
                        },
                        {
                            "id": "rec_003",
                            "title": "经典儿歌合集",
                            "description": "传统与现代儿歌的完美结合",
                            "thumbnail": "/static/placeholders/music.jpg",
                            "category": "音乐",
                            "age_group": "2-10岁"
                        }
                    ]
                },
                "categories": [
                    {
                        "id": "animation",
                        "name": "动画片",
                        "icon": "🎬",
                        "count": 25
                    },
                    {
                        "id": "education",
                        "name": "教育内容",
                        "icon": "📚",
                        "count": 18
                    },
                    {
                        "id": "music",
                        "name": "音乐歌曲",
                        "icon": "🎵",
                        "count": 32
                    },
                    {
                        "id": "stories",
                        "name": "故事朗读",
                        "icon": "📖",
                        "count": 15
                    }
                ],
                "recent_popular": {
                    "title": "最近热门",
                    "items": [
                        {
                            "title": "小猪佩奇系列",
                            "views": "1.2万次观看",
                            "rating": 4.8
                        },
                        {
                            "title": "超级飞侠",
                            "views": "8500次观看",
                            "rating": 4.6
                        },
                        {
                            "title": "汪汪队立大功",
                            "views": "9200次观看",
                            "rating": 4.7
                        }
                    ]
                }
            },
            "message": "推荐内容加载成功"
        }
        
        return JSONResponse(
            content=recommendations,
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
    
    except Exception as e:
        print(f"加载推荐内容失败: {e}")
        raise HTTPException(
            status_code=500,
            detail="推荐内容暂时无法加载，请稍后再试"
        )

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

# --- 应用生命周期管理 ---
@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时清理资源"""
    await close_http_session()
    print("🔄 HTTP会话已关闭")

# --- Main Execution ---
if __name__ == "__main__":
    import uvicorn
    print("🎬 儿童视频播放器服务器启动中...")
    print(f"📁 视频目录: {VIDEOS_DIR.resolve()}")
    print(f"🌐 前端目录: {FRONTEND_DIR.resolve()}")
    print("🚀 服务地址: http://localhost:8000")
    print("⚡ 性能优化：异步网络请求 + 分阶段加载")
    uvicorn.run(app, host="0.0.0.0", port=8000)