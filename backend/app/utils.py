import locale
import re
import unicodedata
from typing import List, Dict

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
            # 如果都失败了，使用自定义排序
            print("警告: 中文locale设置失败，文件夹排序可能不准确。")
            pass

def chinese_sort_key(text: str):
    """为中文文本生成一个适合排序的键。"""
    # 简单的排序策略：数字 -> 字母 -> 中文
    # 这种方法不依赖于locale，但可能不如locale精确
    key = []
    for char in text:
        if char.isdigit():
            key.append((0, char))
        elif 'a' <= char.lower() <= 'z':
            key.append((1, char.lower()))
        else:
            key.append((2, char))
    return key

def sort_folders_chinese(folders: List[Dict]) -> List[Dict]:
    """使用中文友好的方式对文件夹列表进行排序。"""
    try:
        # 优先尝试使用locale进行排序
        return sorted(folders, key=lambda x: locale.strxfrm(x['name']))
    except (AttributeError, TypeError):
        # 如果locale失败，回退到自定义排序
        return sorted(folders, key=lambda x: chinese_sort_key(x['name']))

def sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符。"""
    return re.sub(r'[\\/*?:"<>|]', "", name)

def format_webvtt_time(seconds: float) -> str:
    """将秒数转换为WebVTT时间格式 (HH:MM:SS.sss)。"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"

def extract_bvid_from_url(url_or_bvid: str) -> str:
    """从Bilibili URL中提取BV号，如果已经是BV号则直接返回。"""
    if url_or_bvid.startswith('http'):
        match = re.search(r'/video/(BV[a-zA-Z0-9]+)', url_or_bvid)
        if match:
            return match.group(1)
        else:
            raise ValueError(f"无法从URL中提取BV号: {url_or_bvid}")
    # 假设已经是BV号
    return url_or_bvid
