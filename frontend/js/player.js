import { showError } from './ui.js';

const API_BASE = window.location.origin;

/**
 * A class to manage the Plyr video player instance and its related logic.
 */
export class VideoPlayer {
    constructor(videoElementId, subtitleElementId) {
        this.player = null;
        this.videoElement = document.getElementById(videoElementId);
        this.videoSource = this.videoElement.querySelector('source');
        this.subtitleTrack = document.getElementById(subtitleElementId);
    }

    /**
     * Initializes the Plyr player with a new video URL and subtitle info.
     * @param {string} videoUrl - The URL of the video to play.
     * @param {string|null} subtitleUrl - The URL of the subtitle file, if available.
     */
    load(videoUrl, subtitleUrl) {
        // Ensure any previous instance is destroyed
        this.destroy();

        // Set up subtitle track if available
        if (subtitleUrl) {
            this.subtitleTrack.src = `${API_BASE}${subtitleUrl}`;
            this.subtitleTrack.style.display = 'block';
        }

        // Set up video source
        this.videoSource.src = `${API_BASE}${videoUrl}`;
        this.videoElement.load();

        // Initialize Plyr
        this._initPlyr(!!subtitleUrl);
    }

    /**
     * Destroys the Plyr instance and cleans up video and subtitle elements.
     */
    destroy() {
        if (this.player) {
            this.player.destroy();
            this.player = null;
        }
        if (this.videoElement) {
            this.videoElement.pause();
            this.videoSource.src = '';
            this.subtitleTrack.src = '';
            this.subtitleTrack.style.display = 'none';
            this.videoElement.load();
        }
    }

    /**
     * Private method to initialize the Plyr instance with specific options.
     * @param {boolean} hasSubtitles - Whether subtitles are available for this video.
     */
    _initPlyr(hasSubtitles) {
        const plyrOptions = {
            controls: ['play', 'progress', 'current-time', 'duration', 'captions', 'fullscreen'],
            settings: [],
            captions: {
                active: hasSubtitles, // Automatically enable captions if they exist
                language: 'auto',
                update: true
            },
            autoplay: true,
            clickToPlay: true
        };

        this.player = new Plyr(this.videoElement, plyrOptions);

        this.player.on('ready', () => {
            this.player.play().catch(() => {
                console.warn('Autoplay was prevented.');
            });
        });

        this.player.on('error', (event) => {
            console.error('Player error:', event);
            showError('视频播放失败，请检查文件或网络。');
        });
    }
}
