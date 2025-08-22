const API_BASE = window.location.origin;

// --- DOM Element Selectors ---
const screens = document.querySelectorAll('.screen');
const foldersList = document.getElementById('folders-list');
const videosList = document.getElementById('videos-list');
const backToParentBtn = document.getElementById('back-to-parent');
const foldersTitle = document.getElementById('folders-title');
const folderTitle = document.getElementById('folder-title');
const videoTitle = document.getElementById('video-title');
const errorToast = document.getElementById('error-toast');
const errorMessage = document.getElementById('error-message');
const downloadProgress = document.getElementById('download-progress');
const progressFill = document.getElementById('progress-fill');
const progressText = document.getElementById('progress-text');

/**
 * Shows a specific screen and hides all others.
 * @param {string} screenName - The name of the screen to show (e.g., 'folders').
 */
export function showScreen(screenName) {
    screens.forEach(screen => {
        screen.classList.add('hidden');
    });
    const targetScreen = document.getElementById(`${screenName}-screen`);
    if (targetScreen) {
        targetScreen.classList.remove('hidden');
    }
}

/**
 * Formats seconds into a MM:SS string.
 * @param {number} seconds - The duration in seconds.
 * @returns {string} The formatted duration string.
 */
function formatDuration(seconds) {
    if (!seconds) return '';
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
}

/**
 * Renders the list of folders.
 * @param {Array} folders - The array of folder objects.
 * @param {function} onFolderClick - The callback function for when a folder is clicked.
 */
export function renderFolders(folders, onFolderClick) {
    foldersList.innerHTML = '';
    if (folders.length === 0) {
        foldersList.innerHTML = `
            <div class="empty-state">
                <h3>📁 暂无文件夹</h3>
                <p>请在 videos 目录下创建文件夹并添加 list.txt</p>
            </div>`;
        return;
    }

    folders.forEach(folder => {
        const folderElement = document.createElement('div');
        folderElement.className = 'folder-item';
        folderElement.setAttribute('tabindex', '0');
        folderElement.innerHTML = `
            <span class="folder-icon">📁</span>
            <div class="folder-name">${folder.name}</div>
        `;
        folderElement.addEventListener('click', () => onFolderClick(folder));
        folderElement.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onFolderClick(folder);
            }
        });
        foldersList.appendChild(folderElement);
    });
}

/**
 * Renders the list of videos.
 * @param {Array} videos - The array of video objects.
 * @param {function} onVideoClick - The callback function for when a video is clicked.
 */
export function renderVideos(videos, onVideoClick) {
    videosList.innerHTML = '';
    if (videos.length === 0) {
        videosList.innerHTML = `
            <div class="empty-state">
                <h3>📺 暂无视频</h3>
                <p>请在 list.txt 中添加B站视频链接</p>
            </div>`;
        return;
    }

    videos.forEach(video => {
        const videoElement = document.createElement('div');
        videoElement.className = 'video-item';
        videoElement.dataset.videoPage = video.page;
        videoElement.setAttribute('tabindex', '0');
        videoElement.innerHTML = `
            <div class="video-thumbnail loading">
                <div class="placeholder-icon">🎬</div>
            </div>
            <div class="video-info">
                <div class="video-title">${video.title}</div>
                <div class="video-page">第 ${video.page} 集</div>
                ${video.duration ? `<div class="video-duration">${formatDuration(video.duration)}</div>` : ''}
            </div>
        `;
        videoElement.addEventListener('click', () => onVideoClick(video));
        videoElement.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onVideoClick(video);
            }
        });
        videosList.appendChild(videoElement);
    });
}

/**
 * Updates a single video's cover image.
 * @param {number} page - The page number of the video to update.
 * @param {string} coverUrl - The URL of the new cover image.
 */
export function updateVideoCover(page, coverUrl) {
    const videoElement = document.querySelector(`[data-video-page="${page}"]`);
    if (videoElement) {
        const thumbnail = videoElement.querySelector('.video-thumbnail');
        if (thumbnail) {
            thumbnail.classList.remove('loading');
            thumbnail.innerHTML = `
                <img src="${API_BASE}${coverUrl}" alt="视频封面"
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                <div class="placeholder-icon" style="display: none;">🎬</div>
            `;
        }
    }
}

/**
 * Updates the "back to parent" button and the folder title.
 * @param {Array} currentPath - An array representing the current folder path.
 */
export function updatePathUI(currentPath) {
    if (currentPath.length > 0) {
        backToParentBtn.classList.remove('hidden');
        foldersTitle.textContent = `📁 ${currentPath[currentPath.length - 1]}`;
    } else {
        backToParentBtn.classList.add('hidden');
        foldersTitle.textContent = '📁 选择文件夹';
    }
}

/**
 * Sets the title for the videos screen.
 * @param {string} name - The name of the folder.
 */
export function setVideosTitle(name) {
    folderTitle.textContent = `📺 ${name}`;
}

/**
 * Sets the title for the player screen.
 * @param {string} title - The title of the video.
 */
export function setPlayerTitle(title) {
    videoTitle.textContent = `🎬 ${title}`;
}

/**
 * Shows or hides the download progress indicator.
 * @param {boolean} visible - Whether to show the progress bar.
 */
export function showDownloadProgress(visible) {
    downloadProgress.classList.toggle('hidden', !visible);
}

/**
 * Displays an error message toast.
 * @param {string} message - The error message to display.
 */
export function showError(message) {
    errorMessage.textContent = message;
    errorToast.classList.remove('hidden');
    setTimeout(() => {
        errorToast.classList.add('hidden');
    }, 3000);
}

/**
 * Starts the typing animation on the loading screen.
 * @returns {Promise<void>} - A promise that resolves when the animation is complete.
 */
export function startTypingAnimation() {
    return new Promise(resolve => {
        const text = 'welcome to player';
        const el = document.getElementById('typing-text');
        if (!el) {
            resolve();
            return;
        }
        el.textContent = '';
        let i = 0;
        const typeNext = () => {
            if (i < text.length) {
                el.textContent += text[i++];
                setTimeout(typeNext, 100);
            } else {
                setTimeout(resolve, 700);
            }
        };
        typeNext();
    });
}
