from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class VideoInfo(BaseModel):
    """视频信息模型"""
    bv_id: str
    title: str
    duration: str
    thumbnail: str
    is_downloaded: bool = False
    local_path: Optional[str] = None
    file_size: Optional[int] = None
    upload_date: Optional[str] = None

class FolderInfo(BaseModel):
    """文件夹信息模型"""
    name: str
    path: str
    parent_path: Optional[str] = None
    # 使用前向引用并避免可变默认值陷阱
    children: List['FolderInfo'] = Field(default_factory=list)
    has_list_file: bool
    video_count: int = 0
    downloaded_count: int = 0
    depth: int = 0
    is_folder: bool = True

# 解析前向引用
FolderInfo.model_rebuild()

class DownloadStatus(BaseModel):
    """下载状态模型"""
    task_id: str
    bv_id: str
    status: str  # pending, downloading, completed, failed
    progress: int = 0  # 0-100
    message: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

class DownloadRequest(BaseModel):
    """下载请求模型"""
    bv_id: str
    folder_path: str
