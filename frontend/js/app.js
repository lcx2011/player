import * as api from './api.js';
import * as ui from './ui.js';
import { VideoPlayer } from './player.js';

class VideoPlayerApp {
    constructor() {
        this.currentPath = [];
        this.currentFolder = null;
        this.player = new VideoPlayer('video-player', 'subtitle-track');

        this._init();
    }

    async _init() {
        this._bindEvents();
        this._registerServiceWorker();

        ui.showScreen('loading');
        const typingPromise = ui.startTypingAnimation();
        const foldersPromise = this.loadFolders();

        await Promise.all([typingPromise, foldersPromise]);

        ui.showScreen('folders');
    }

    _bindEvents() {
        document.getElementById('back-to-folders').addEventListener('click', () => {
            this.player.destroy();
            ui.showScreen('folders');
        });

        document.getElementById('back-to-videos').addEventListener('click', () => {
            this.player.destroy();
            ui.showScreen('videos');
        });

        document.getElementById('back-to-parent').addEventListener('click', () => {
            this._navigateToParent();
        });
    }

    async loadFolders(path = '') {
        try {
            const folders = await api.getFolders(path);
            this.currentPath = path ? path.split('/') : [];
            ui.renderFolders(folders, (folder) => this._onFolderClick(folder));
            ui.updatePathUI(this.currentPath);
        } catch (error) {
            ui.showError('加载文件夹列表失败');
        }
    }

    _onFolderClick(folder) {
        if (folder.has_list_file) {
            this.loadVideos(folder.path);
        } else {
            this.loadFolders(folder.path);
        }
    }

    _navigateToParent() {
        if (this.currentPath.length > 0) {
            const parentPath = this.currentPath.slice(0, -1).join('/');
            this.loadFolders(parentPath);
        }
    }

    async loadVideos(folderPath) {
        try {
            this.currentFolder = folderPath;
            ui.setVideosTitle(folderPath.split('/').pop());
            ui.showScreen('videos');

            const videos = await api.getVideos(folderPath);
            ui.renderVideos(videos, (video) => this.playVideo(video));

            // Asynchronously load covers without blocking
            this._loadCovers(videos);

        } catch (error) {
            ui.showError('加载视频列表失败');
            ui.showScreen('folders'); // Go back to folders on error
        }
    }

    async _loadCovers(videos) {
        for (const video of videos) {
            try {
                // No need to await each one, let them load in parallel
                api.getCover(video.bvid, video.page).then(result => {
                    if (result.cover_url) {
                        ui.updateVideoCover(video.page, result.cover_url);
                    }
                });
            } catch (error) {
                console.warn(`Failed to load cover for ${video.title}`, error);
            }
        }
    }

    async playVideo(video) {
        try {
            ui.setPlayerTitle(video.title);
            ui.showScreen('player');
            ui.showDownloadProgress(true);

            const playInfo = await api.getPlayInfo(this.currentFolder, video.page);

            ui.showDownloadProgress(false);

            if (playInfo.status === 'ready') {
                this.player.load(playInfo.video_url, playInfo.subtitle_url);
            } else {
                ui.showError('视频准备中，请稍后...');
            }
        } catch (error) {
            ui.showDownloadProgress(false);
            ui.showError('播放视频失败');
            // Optionally go back to the video list on error
            // ui.showScreen('videos');
        }
    }

    async _registerServiceWorker() {
        if ('serviceWorker' in navigator) {
            try {
                await navigator.serviceWorker.register('./sw.js');
                console.log('Service Worker registered successfully.');
            } catch (error) {
                console.error('Service Worker registration failed:', error);
            }
        }
    }
}

// --- PWA Installation ---
let deferredPrompt;
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    console.log('`beforeinstallprompt` event was fired.');
    // Here you could show a custom install button
});

window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    console.log('PWA was installed');
});


// --- App Entry Point ---
document.addEventListener('DOMContentLoaded', () => {
    new VideoPlayerApp();
});
