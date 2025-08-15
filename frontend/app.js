// 应用状态管理
class VideoPlayerApp {
    constructor() {
        this.currentScreen = 'loading';
        this.currentFolder = null;
        this.currentVideo = null;
        this.apiBase = window.location.origin;
        this.subtitleEnabled = false;
        this.currentPath = [];  // 当前路径栈 ['folder1', 'subfolder1']
        this.folderHistory = []; // 导航历史
        this.player = null; // Plyr播放器实例
        // 加载页状态：打字是否完成、数据是否就绪
        this.typingDone = false;
        this.foldersLoaded = false;
        
        this.init();
    }

    async init() {
        // 绑定事件监听器
        this.bindEvents();
        
        // 注册 Service Worker
        this.registerServiceWorker();
        
        // 开始打字动画并并行加载数据
        this.startTypingAnimation();
        this.loadFolders('', true); // 初始加载时标记为true
    }

    bindEvents() {
        // 主页选择按钮
        document.getElementById('go-to-folders').addEventListener('click', () => {
            // 重置路径状态并加载根目录
            this.currentPath = [];
            this.loadFolders('');
            this.showScreen('folders');
        });
        
        // 返回按钮
        document.getElementById('back-to-home').addEventListener('click', () => {
            this.showScreen('home');
        });
        
        document.getElementById('back-to-home-from-folders').addEventListener('click', () => {
            this.showScreen('home');
        });
        
        document.getElementById('back-to-folders').addEventListener('click', () => {
            this.showScreen('folders');
        });
        
        document.getElementById('back-to-videos').addEventListener('click', () => {
            this.showScreen('videos');
        });

        // 返回上级文件夹按钮
        document.getElementById('back-to-parent').addEventListener('click', () => {
            this.navigateToParent();
        });

        // 字幕将由Plyr自动处理
    }

    showScreen(screenName) {
        // 如果正在离开播放器屏幕，彻底停止并清理视频播放
        if (this.currentScreen === 'player' && screenName !== 'player') {
            this.clearVideoPlayer();
        }
        
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

    async loadFolders(path = '', isInitialLoad = false) {
        try {
            // 标准化路径：将反斜杠转换为正斜杠
            const normalizedPath = path ? path.replace(/\\/g, '/') : '';
            
            const url = normalizedPath && normalizedPath.trim() ? `${this.apiBase}/api/folders?path=${encodeURIComponent(normalizedPath)}` : `${this.apiBase}/api/folders`;
            const response = await fetch(url);
            const folders = await response.json();
            
            // 更新当前路径
            this.currentPath = (normalizedPath && normalizedPath.trim()) ? normalizedPath.split('/') : [];
            
            this.renderFolders(folders);
            this.updateBreadcrumb();
            this.updateBackButton();
            
            // 只有在初始加载时才设置标记和检查是否进入主页
            if (isInitialLoad) {
                this.foldersLoaded = true;
                this.maybeEnterApp();
            }
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
            //folderElement.style.animationDelay = `${index * 0.15}s`;
            folderElement.setAttribute('tabindex', '0'); // 键盘可访问性

            const folderName = typeof folder === 'string' ? folder : folder.name;
            const hasVideos = typeof folder === 'object' && folder.has_list_file;
            const folderIcon = '📁'; // 统一使用文件夹图标

            folderElement.innerHTML = `
                <span class="folder-icon">${folderIcon}</span>
                <div class="folder-name">${folderName}</div>
            `;

            // 点击和键盘事件
            const handleActivation = () => {
                if (typeof folder === 'string') {
                    // 兼容旧格式（字符串）
                    this.loadVideos(folder);
                } else if (folder.has_list_file) {
                    // 有list.txt文件，进入视频列表
                    this.loadVideos(folder.path);
                } else {
                    // 纯文件夹，继续浏览子文件夹
                    this.loadFolders(folder.path);
                }
            };

            folderElement.addEventListener('click', handleActivation);
            folderElement.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleActivation();
                }
            });

            container.appendChild(folderElement);
        });
    }

    updateBreadcrumb() {
        // 需求：移除列表上方的第二处重复信息（面包屑）。
        // 做法：始终将面包屑隐藏，不再渲染路径项。
        const breadcrumb = document.getElementById('breadcrumb');
        if (breadcrumb) {
            breadcrumb.classList.add('hidden');
        }
        return;
    }
    
    updateBackButton() {
        const backToParentButton = document.getElementById('back-to-parent');
        const backToHomeButton = document.getElementById('back-to-home-from-folders');
        const foldersTitle = document.getElementById('folders-title');
        
        if (this.currentPath.length > 0) {
            // 在子文件夹中，显示返回上级文件夹按钮，隐藏返回主页按钮
            backToParentButton.classList.remove('hidden');
            backToHomeButton.classList.add('hidden');
            foldersTitle.textContent = `📁 ${this.currentPath[this.currentPath.length - 1]}`;
        } else {
            // 在根目录，显示返回主页按钮，隐藏返回上级文件夹按钮
            backToParentButton.classList.add('hidden');
            backToHomeButton.classList.remove('hidden');
            foldersTitle.textContent = '📁 选择文件夹';
        }
    }
    
    navigateToParent() {
        if (this.currentPath.length > 0) {
            // 计算父级路径
            const parentPathArray = this.currentPath.slice(0, -1);
            const parentPath = parentPathArray.length > 0 ? parentPathArray.join('/') : '';
            
            // 加载父级文件夹
            this.loadFolders(parentPath);
        }
    }

    async showRecommendations() {
        try {
            this.showScreen('recommendations');
            // 加载推荐内容
            await this.loadRecommendations();
        } catch (error) {
            this.showError('加载推荐内容失败');
            console.error('Error loading recommendations:', error);
        }
    }

    async loadRecommendations() {
        const container = document.getElementById('recommendations-content');
        
        // 显示加载状态
        container.innerHTML = `
            <div class="loading-state">
                <div class="loading-spinner">🔄</div>
                <p>正在加载推荐内容...</p>
            </div>
        `;
        
        try {
            const response = await fetch(`${this.apiBase}/api/recommendations`);
            if (response.ok) {
                const recommendations = await response.json();
                this.renderRecommendations(recommendations);
            } else {
                throw new Error('Failed to load recommendations');
            }
        } catch (error) {
            // 显示占位符内容
            container.innerHTML = `
                <div class="recommendations-placeholder">
                    <div class="placeholder-icon">🎯</div>
                    <h3>推荐功能即将上线</h3>
                    <p>我们正在为您准备精彩的推荐内容</p>
                    <div class="placeholder-items">
                        <div class="placeholder-item">
                            <div class="placeholder-thumbnail">🎬</div>
                            <div class="placeholder-info">
                                <div class="placeholder-title">热门视频推荐</div>
                                <div class="placeholder-desc">即将为您推荐最受欢迎的内容</div>
                            </div>
                        </div>
                        <div class="placeholder-item">
                            <div class="placeholder-thumbnail">📚</div>
                            <div class="placeholder-info">
                                <div class="placeholder-title">学习内容推荐</div>
                                <div class="placeholder-desc">根据年龄推荐适合的学习视频</div>
                            </div>
                        </div>
                        <div class="placeholder-item">
                            <div class="placeholder-thumbnail">🎵</div>
                            <div class="placeholder-info">
                                <div class="placeholder-title">音乐动画推荐</div>
                                <div class="placeholder-desc">精选儿童音乐和动画内容</div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }
    }

    renderRecommendations(recommendations) {
        const container = document.getElementById('recommendations-content');
        // TODO: 实现推荐内容的渲染逻辑
        console.log('Recommendations:', recommendations);
    }

    async loadVideos(folderPath) {
        try {
            this.currentFolder = folderPath;
            const folderName = folderPath.split('/').pop() || folderPath;
            document.getElementById('folder-title').textContent = `📺 ${folderName}`;
            
            const response = await fetch(`${this.apiBase}/api/folders/${encodeURIComponent(folderPath)}`);
            
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
            // 移除动画延迟，让所有视频项一次性显示
            // videoElement.style.animationDelay = `${index * 0.12}s`;
            videoElement.dataset.videoPage = video.page;
            videoElement.setAttribute('tabindex', '0'); // 键盘可访问性

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

            // 点击和键盘事件
            const handleActivation = () => {
                this.playVideo(video);
            };

            videoElement.addEventListener('click', handleActivation);
            videoElement.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleActivation();
                }
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

    // 打字动画：逐字显示“welcome to player”，结束后标记完成
    startTypingAnimation() {
        const text = 'welcome to player';
        const el = document.getElementById('typing-text');
        const cursor = document.querySelector('.typing-cursor');
        if (!el) {
            // 若元素不存在，直接标记完成，避免阻塞
            this.typingDone = true;
            this.maybeEnterApp();
            return;
        }
        el.textContent = '';
        let i = 0;
        const charSpeed = 100; // 每个字符的基础间隔(ms)——更慢
        const wordPause = 400; // 单词间的额外停顿(ms)
        const typeNext = () => {
            if (i < text.length) {
                const ch = text[i];
                el.textContent += ch;
                i += 1;
                // 如果是空格，额外停顿一下（单词间）
                const delay = ch === ' ' ? wordPause : charSpeed;
                setTimeout(typeNext, delay);
            } else {
                // 打字完成，光标继续闪烁；整体额外停顿700ms再进入
                setTimeout(() => {
                    this.typingDone = true;
                    this.maybeEnterApp();
                }, 700);
            }
        };
        typeNext();
    }

    // 若数据准备完成且打字完成，则进入主页选择界面
    maybeEnterApp() {
        if (this.typingDone && this.foldersLoaded) {
            this.showScreen('home');
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

    clearVideoPlayer() {
        // 销毁现有的Plyr实例
        if (this.player) {
            this.player.destroy();
            this.player = null;
        }

        const videoPlayer = document.getElementById('video-player');
        const videoSource = document.getElementById('video-source');
        const subtitleTrack = document.getElementById('subtitle-track');

        // 暂停并清空当前视频
        if (videoPlayer) {
            videoPlayer.pause();
            videoSource.src = '';
            subtitleTrack.src = '';
            subtitleTrack.style.display = 'none';
            videoPlayer.load();
        }

        // 重置字幕状态
        this.subtitleEnabled = false;
    }

    stopVideo() {
        // 优先通过Plyr停止
        if (this.player) {
            try { this.player.pause(); } catch(_) {}
            try { this.player.currentTime = 0; } catch(_) {}
        }
        // 同时直接操作原生video，确保彻底停止
        const videoPlayer = document.getElementById('video-player');
        const videoSource = document.getElementById('video-source');
        const subtitleTrack = document.getElementById('subtitle-track');
        if (videoPlayer) {
            try { videoPlayer.pause(); } catch(_) {}
            if (videoSource) videoSource.src = '';
            if (subtitleTrack) {
                subtitleTrack.src = '';
                subtitleTrack.style.display = 'none';
            }
            try { videoPlayer.removeAttribute('src'); } catch(_) {}
            try { videoPlayer.load(); } catch(_) {}
        }
    }

    loadVideoPlayer(videoUrl) {
        const videoPlayer = document.getElementById('video-player');
        const videoSource = document.getElementById('video-source');

        // 设置新的视频源
        videoSource.src = `${this.apiBase}${videoUrl}`;
        // 确保允许自动播放
        videoPlayer.autoplay = true;
        videoPlayer.load();

        // 如果浏览器允许，尽早开始播放（与用户点击更贴近）
        try {
            const playPromise = videoPlayer.play();
            if (playPromise && typeof playPromise.then === 'function') {
                playPromise.catch(() => {
                    // 忽略，稍后由Plyr接管再尝试播放
                });
            }
        } catch (_) {}

        // 初始化Plyr播放器
        this.initPlyrPlayer();

        this.hideDownloadProgress();
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
        const subtitleTrack = document.getElementById('subtitle-track');

        // 先重置字幕状态
        this.subtitleEnabled = false;
        subtitleTrack.src = '';
        subtitleTrack.style.display = 'none';

        if (video.has_subtitle && video.subtitle_url) {
            // 有字幕可用。加载字幕
            this.loadSubtitle(video.subtitle_url);
        } else {
            console.log('无字幕可用');
        }
    }

    loadSubtitle(subtitleUrl) {
        try {
            const subtitleTrack = document.getElementById('subtitle-track');
            const videoPlayer = document.getElementById('video-player');

            // 设置字幕源
            subtitleTrack.src = `${this.apiBase}${subtitleUrl}`;
            subtitleTrack.style.display = 'block';

            // 默认开启字幕
            this.subtitleEnabled = true;
            console.log('字幕已加载，将在Plyr初始化时自动启用');

            // 等待视频和字幕都加载完成后启用字幕
            const enableSubtitle = () => {
                if (videoPlayer.textTracks.length > 0) {
                    videoPlayer.textTracks[0].mode = 'showing';
                }
            };

            // 如果视频已经加载，立即启用字幕
            if (videoPlayer.readyState >= 1) {
                enableSubtitle();
            } else {
                // 否则等待视频加载
                videoPlayer.addEventListener('loadedmetadata', enableSubtitle, { once: true });
            }
        } catch (error) {
            console.error('加载字幕失败:', error);
        }
    }

    initPlyrPlayer() {
        const videoPlayer = document.getElementById('video-player');
        
        // Plyr配置选项
        const plyrOptions = {
            // 控制按钮配置：只显示播放、进度条、字幕和全屏
            controls: [
                'play', // 播放/暂停
                'progress', // 进度条
                'current-time', // 当前时间
                'duration', // 总时长
                'captions', // 字幕
                'fullscreen' // 全屏
            ],
            // 不显示设置菜单
            settings: [],
            // 字幕配置
            captions: {
                active: true, // 默认开启字幕（如果有的话）
                language: 'auto',
                update: true
            },
            // 其他配置
            autoplay: true, // 优先尝试自动播放
            clickToPlay: true,
            hideControls: true,
            resetOnEnd: false,
            keyboard: { focused: true, global: false },
            tooltips: { controls: false, seek: true },
            displayDuration: true,
            invertTime: true,
            toggleInvert: true
        };

        // 创建Plyr实例
        this.player = new Plyr(videoPlayer, plyrOptions);

        // 监听Plyr事件
        this.player.on('ready', () => {
            console.log('Plyr播放器已就绪');
            // 如果有字幕且默认开启，则启用字幕
            if (this.subtitleEnabled && this.player.captions && this.player.captions.tracks.length > 0) {
                this.player.captions.active = true;
            }
            // 尝试自动播放
            this.player.play().catch(e => {
                console.log('自动播放被阻止，需要用户手动播放');
            });
        });

        this.player.on('play', () => {
            console.log('开始播放');
        });

        this.player.on('pause', () => {
            console.log('暂停播放');
        });

        // 播放错误处理
        this.player.on('error', (event) => {
            console.error('播放器错误:', event);
            this.showError('视频播放失败，请检查网络连接或重试');
        });

        // 视频加载错误处理
        this.player.media.addEventListener('error', (e) => {
            console.error('视频加载错误:', e);
            this.showError('视频文件加载失败');
        });

        // 检测视频是否可以播放
        this.player.on('canplay', () => {
            console.log('视频可以播放');
            // 再次确保处于播放中
            if (this.player && this.player.paused) {
                this.player.play().catch(() => {});
            }
        });

        // 字幕事件监听
        this.player.on('captionsenabled', () => {
            this.subtitleEnabled = true;
            console.log('字幕已启用');
        });

        this.player.on('captionsdisabled', () => {
            this.subtitleEnabled = false;
            console.log('字幕已禁用');
        });
    }

    toggleSubtitle() {
        // 使用Plyr API控制字幕
        if (this.player && this.player.captions) {
            this.player.captions.toggle();
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