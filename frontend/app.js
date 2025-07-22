// 应用状态管理
class VideoPlayerApp {
    constructor() {
        this.currentScreen = 'loading';
        this.currentFolder = null;
        this.currentVideo = null;
        this.apiBase = window.location.origin;
        this.subtitleEnabled = false;
        
        this.init();
    }

    async init() {
        // 绑定事件监听器
        this.bindEvents();
        
        // 注册 Service Worker
        this.registerServiceWorker();
        
        // 模拟加载时间
        setTimeout(() => {
            this.loadFolders();
        }, 1500);
    }

    bindEvents() {
        // 返回按钮
        document.getElementById('back-to-folders').addEventListener('click', () => {
            this.showScreen('folders');
        });
        
        document.getElementById('back-to-videos').addEventListener('click', () => {
            this.showScreen('videos');
        });

        // 字幕开关按钮
        document.getElementById('subtitle-toggle').addEventListener('click', () => {
            this.toggleSubtitle();
        });
    }

    showScreen(screenName) {
        // 隐藏所有屏幕
        document.querySelectorAll('.screen').forEach(screen => {
            screen.classList.add('hidden');
        });
        
        // 显示目标屏幕
        const targetScreen = document.getElementById(`${screenName}-screen`);
        if (targetScreen) {
            targetScreen.classList.remove('hidden');
            this.currentScreen = screenName;
        }
    }

    async loadFolders() {
        try {
            const response = await fetch(`${this.apiBase}/api/folders`);
            const folders = await response.json();
            
            this.renderFolders(folders);
            this.showScreen('folders');
        } catch (error) {
            this.showError('加载文件夹失败');
            console.error('Error loading folders:', error);
        }
    }

    renderFolders(folders) {
        const container = document.getElementById('folders-list');
        container.innerHTML = '';

        if (folders.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <h3>📁 暂无文件夹</h3>
                    <p>请在 videos 目录下创建文件夹并添加 list.txt</p>
                </div>
            `;
            return;
        }

        folders.forEach((folder, index) => {
            const folderElement = document.createElement('div');
            folderElement.className = 'folder-item';
            folderElement.style.animationDelay = `${index * 0.1}s`;
            
            folderElement.innerHTML = `
                <span class="folder-icon">📁</span>
                <div class="folder-name">${folder}</div>
            `;
            
            folderElement.addEventListener('click', () => {
                this.loadVideos(folder);
            });
            
            container.appendChild(folderElement);
        });
    }

    async loadVideos(folderName) {
        try {
            this.currentFolder = folderName;
            document.getElementById('folder-title').textContent = `📺 ${folderName}`;
            
            const response = await fetch(`${this.apiBase}/api/folders/${encodeURIComponent(folderName)}`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const videos = await response.json();
            this.renderVideos(videos);
            this.showScreen('videos');

            // 异步加载封面
            this.loadCoversAsync(videos);
        } catch (error) {
            this.showError('加载视频列表失败');
            console.error('Error loading videos:', error);
        }
    }

    renderVideos(videos) {
        const container = document.getElementById('videos-list');
        container.innerHTML = '';

        if (videos.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <h3>📺 暂无视频</h3>
                    <p>请在 list.txt 中添加B站视频链接</p>
                </div>
            `;
            return;
        }

        videos.forEach((video, index) => {
            const videoElement = document.createElement('div');
            videoElement.className = 'video-item';
            videoElement.style.animationDelay = `${index * 0.1}s`;
            videoElement.dataset.videoPage = video.page; // 添加数据属性用于后续查找

            // 初始显示占位符，添加加载状态
            const thumbnailHTML = '<div class="placeholder-icon">🎬</div>';

            videoElement.innerHTML = `
                <div class="video-thumbnail loading">
                    ${thumbnailHTML}
                </div>
                <div class="video-info">
                    <div class="video-title">${video.title}</div>
                    <div class="video-page">第 ${video.page} 集</div>
                    ${video.duration ? `<div class="video-duration">${this.formatDuration(video.duration)}</div>` : ''}
                </div>
            `;

            videoElement.addEventListener('click', () => {
                this.playVideo(video);
            });

            container.appendChild(videoElement);
        });
    }

    async loadCoversAsync(videos) {
        // 异步加载每个视频的封面
        for (const video of videos) {
            if (video.bvid) {
                try {
                    // 延迟一点时间，避免同时发起太多请求
                    await new Promise(resolve => setTimeout(resolve, 100));

                    const response = await fetch(`${this.apiBase}/api/cover/${video.bvid}/${video.page}`);
                    if (response.ok) {
                        const result = await response.json();
                        if (result.cover_url) {
                            this.updateVideoCover(video.page, result.cover_url);
                        }
                    }
                } catch (error) {
                    console.error(`加载封面失败 (${video.title}):`, error);
                }
            }
        }
    }

    updateVideoCover(page, coverUrl) {
        // 找到对应的视频元素并更新封面
        const videoElement = document.querySelector(`[data-video-page="${page}"]`);
        if (videoElement) {
            const thumbnail = videoElement.querySelector('.video-thumbnail');
            if (thumbnail) {
                // 移除加载状态
                thumbnail.classList.remove('loading');
                thumbnail.innerHTML = `
                    <img src="${this.apiBase}${coverUrl}" alt="视频封面"
                         onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                    <div class="placeholder-icon" style="display: none;">🎬</div>
                `;
            }
        }
    }

    formatDuration(seconds) {
        if (!seconds) return '';
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
    }

    async playVideo(video) {
        try {
            this.currentVideo = video;
            document.getElementById('video-title').textContent = `🎬 ${video.title}`;

            // 先清空播放器
            this.clearVideoPlayer();

            this.showScreen('player');
            this.showDownloadProgress();
            
            // 请求播放视频
            const response = await fetch(
                `${this.apiBase}/api/play/${encodeURIComponent(this.currentFolder)}/${video.page}`
            );
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const result = await response.json();
            
            if (result.status === 'ready') {
                this.loadVideoPlayer(result.video_url);
                // 设置字幕按钮状态，使用API返回的字幕信息
                this.setupSubtitleButton({
                    ...video,
                    has_subtitle: result.has_subtitle,
                    subtitle_url: result.subtitle_url
                });
            } else {
                // 如果视频还在下载，可以实现轮询检查状态
                this.showError('视频正在准备中，请稍后重试');
            }
            
        } catch (error) {
            this.hideDownloadProgress();
            this.showError('播放视频失败');
            console.error('Error playing video:', error);
        }
    }

    loadVideoPlayer(videoUrl) {
        const videoPlayer = document.getElementById('video-player');
        const videoSource = document.getElementById('video-source');
        
        videoSource.src = `${this.apiBase}${videoUrl}`;
        videoPlayer.load();
        
        this.hideDownloadProgress();
        
        // 自动播放（某些浏览器可能需要用户交互）
        videoPlayer.play().catch(e => {
            console.log('自动播放被阻止，需要用户手动播放');
        });
    }

    showDownloadProgress() {
        document.getElementById('download-progress').classList.remove('hidden');
        
        // 模拟下载进度
        let progress = 0;
        const interval = setInterval(() => {
            progress += Math.random() * 10;
            if (progress >= 100) {
                progress = 100;
                clearInterval(interval);
            }
            
            document.getElementById('progress-fill').style.width = `${progress}%`;
            document.getElementById('progress-text').textContent = `${Math.round(progress)}%`;
        }, 200);
    }

    hideDownloadProgress() {
        document.getElementById('download-progress').classList.add('hidden');
    }

    showError(message) {
        const errorToast = document.getElementById('error-toast');
        const errorMessage = document.getElementById('error-message');
        
        errorMessage.textContent = message;
        errorToast.classList.remove('hidden');
        
        setTimeout(() => {
            errorToast.classList.add('hidden');
        }, 3000);
    }

    setupSubtitleButton(video) {
        const subtitleToggle = document.getElementById('subtitle-toggle');

        if (video.has_subtitle && video.subtitle_url) {
            // 有字幕可用
            subtitleToggle.disabled = false;
            subtitleToggle.classList.remove('active');
            this.subtitleEnabled = false;

            // 加载字幕
            this.loadSubtitle(video.subtitle_url);
        } else {
            // 无字幕可用
            subtitleToggle.disabled = true;
            subtitleToggle.classList.remove('active');
            this.subtitleEnabled = false;

            // 清除字幕轨道
            const subtitleTrack = document.getElementById('subtitle-track');
            subtitleTrack.src = '';
            subtitleTrack.style.display = 'none';
        }
    }

    loadSubtitle(subtitleUrl) {
        try {
            const subtitleTrack = document.getElementById('subtitle-track');
            subtitleTrack.src = `${this.apiBase}${subtitleUrl}`;
            subtitleTrack.style.display = 'block';

            // 默认开启字幕
            this.subtitleEnabled = true;
            document.getElementById('subtitle-toggle').classList.add('active');

            // 启用字幕轨道
            const videoPlayer = document.getElementById('video-player');
            videoPlayer.addEventListener('loadedmetadata', () => {
                if (videoPlayer.textTracks.length > 0) {
                    videoPlayer.textTracks[0].mode = 'showing';
                }
            });
        } catch (error) {
            console.error('加载字幕失败:', error);
        }
    }

    toggleSubtitle() {
        const videoPlayer = document.getElementById('video-player');
        const subtitleToggle = document.getElementById('subtitle-toggle');

        if (subtitleToggle.disabled) return;

        this.subtitleEnabled = !this.subtitleEnabled;

        if (this.subtitleEnabled) {
            subtitleToggle.classList.add('active');
            if (videoPlayer.textTracks.length > 0) {
                videoPlayer.textTracks[0].mode = 'showing';
            }
        } else {
            subtitleToggle.classList.remove('active');
            if (videoPlayer.textTracks.length > 0) {
                videoPlayer.textTracks[0].mode = 'hidden';
            }
        }
    }

    async registerServiceWorker() {
        if ('serviceWorker' in navigator) {
            try {
                await navigator.serviceWorker.register('./sw.js');
                console.log('Service Worker 注册成功');
            } catch (error) {
                console.log('Service Worker 注册失败:', error);
            }
        }
    }
}

// 启动应用
document.addEventListener('DOMContentLoaded', () => {
    new VideoPlayerApp();
});

// PWA 安装提示
let deferredPrompt;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    
    // 可以在这里显示自定义的安装提示
    console.log('PWA 可以安装');
});

window.addEventListener('appinstalled', () => {
    console.log('PWA 已安装');
    deferredPrompt = null;
});