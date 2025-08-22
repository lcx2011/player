const API_BASE = window.location.origin;

/**
 * A wrapper for fetch that handles errors and JSON parsing.
 * @param {string} url - The URL to fetch.
 * @param {object} options - The options for the fetch request.
 * @returns {Promise<any>} - The JSON response.
 */
async function apiFetch(url, options = {}) {
    try {
        const response = await fetch(url, options);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`API fetch error for ${url}:`, error);
        throw error; // Re-throw the error to be caught by the caller
    }
}

/**
 * Fetches the list of folders from the backend.
 * @param {string} path - The sub-path to fetch folders from.
 * @returns {Promise<Array>} - A promise that resolves to the list of folders.
 */
export function getFolders(path = '') {
    const url = path ? `${API_BASE}/api/folders?path=${encodeURIComponent(path)}` : `${API_BASE}/api/folders`;
    return apiFetch(url);
}

/**
 * Fetches the list of videos for a specific folder.
 * @param {string} folderPath - The path to the folder.
 * @returns {Promise<Array>} - A promise that resolves to the list of videos.
 */
export function getVideos(folderPath) {
    return apiFetch(`${API_BASE}/api/folders/${encodeURIComponent(folderPath)}`);
}

/**
 * Fetches the cover image URL for a specific video part.
 * @param {string} bvid - The Bilibili video ID.
 * @param {number} page - The page number of the video part.
 * @returns {Promise<object>} - A promise that resolves to the cover info.
 */
export function getCover(bvid, page) {
    return apiFetch(`${API_BASE}/api/cover/${bvid}/${page}`);
}

/**
 * Requests the video playback information from the backend.
 * This may trigger a download on the backend if the video is not cached.
 * @param {string} folderPath - The path to the folder.
 *p * @param {number} page - The page number of the video part.
 * @returns {Promise<object>} - A promise that resolves to the play info.
 */
export function getPlayInfo(folderPath, page) {
    return apiFetch(`${API_BASE}/api/play/${encodeURIComponent(folderPath)}/${page}`);
}
