# Project Documentation

This document provides an overview of the backend API and the frontend architecture for the Bilibili Video Player application.

## 1. Backend API

The backend is a FastAPI application. The API endpoints are defined in `backend/app/router.py`.

### General Concepts
- **`folder_path`**: A relative path from the main `videos/` directory. Example: `PeppaPig/Season1`.
- **`bvid`**: The Bilibili video ID (e.g., `BV1xx411c7mu`).
- **`page_number`**: The page number (分P) of a video in a Bilibili collection.

---

### Endpoints

#### `GET /api/folders`
- **Description**: Gets the list of subfolders in a given path. If no path is provided, it lists the top-level folders in the `videos/` directory.
- **Query Parameters**:
  - `path` (optional, string): The relative path to scan.
- **Returns**: A JSON array of folder objects.
  ```json
  [
    {
      "name": "PeppaPig",
      "path": "PeppaPig",
      "has_list_file": true
    }
  ]
  ```

#### `GET /api/folders/{folder_path:path}`
- **Description**: Gets the list of videos in a folder based on its `list.txt` file. This is the first stage of loading, returning basic info quickly.
- **Path Parameters**:
  - `folder_path`: The full relative path to the folder containing `list.txt`.
- **Returns**: A JSON array of video part objects.
  ```json
  [
    {
      "title": "P1 The First Episode",
      "page": 1,
      "duration": 300,
      "cid": 123456,
      "bvid": "BV1xx411c7mu"
    }
  ]
  ```

#### `GET /api/folders/{folder_path:path}/details`
- **Description**: Gets detailed information for videos in a folder, such as cover image URLs and subtitle availability. This is the second stage of loading.
- **Path Parameters**:
  - `folder_path`: The full relative path to the folder.
- **Returns**: A JSON array of detailed video part objects.
  ```json
  [
    {
      "page": 1,
      "cover_source": "http://i1.hdslb.com/bfs/archive/xxx.jpg",
      "has_subtitle": true
    }
  ]
  ```

#### `GET /api/batch/covers/{bvid}`
- **Description**: Gets multiple cover image URLs in a single batch request to improve frontend loading performance.
- **Path Parameters**:
  - `bvid`: The Bilibili video ID.
- **Query Parameters**:
  - `pages`: A comma-separated string of page numbers (e.g., "1,2,3").
- **Returns**: A JSON object mapping page numbers to their cached cover URLs.
  ```json
  {
    "covers": {
      "1": "/covers/BV1xx411c7mu_p1.jpg",
      "2": "/covers/BV1xx411c7mu_p2.jpg"
    }
  }
  ```

#### `GET /api/play/{folder_path:path}/{page_number}`
- **Description**: The main endpoint to play a video. If the video is not already downloaded, this endpoint triggers a download and merge process on the backend. It returns the URL to the playable video file and subtitle information.
- **Path Parameters**:
  - `folder_path`: The folder containing the video series.
  - `page_number`: The specific page (episode) to play.
- **Returns**: A JSON object with the status and URLs.
  ```json
  {
    "status": "ready",
    "video_url": "/static/PeppaPig/P1 The First Episode.mp4",
    "subtitle_url": "/subtitles/BV1xx411c7mu_p1.vtt"
  }
  ```

#### `GET /api/subtitle/{folder_path:path}/{page_number}`
- **Description**: Explicitly requests the subtitle for a specific video.
- **Path Parameters**:
  - `folder_path`: The folder containing the video series.
  - `page_number`: The specific page (episode).
- **Returns**: A JSON object with the subtitle URL.
  ```json
  {
    "subtitle_url": "/subtitles/BV1xx411c7mu_p1.vtt"
  }
  ```

### Static File Endpoints
- **`GET /static/{folder_path:path}/{file_name}`**: Serves downloaded video files.
- **`GET /covers/{file_name}`**: Serves cached cover images.
- **`GET /subtitles/{file_name}`**: Serves cached subtitle files (`.vtt`).
- **`GET /`** and **`GET /{file_path:path}`**: Serve the frontend application files (SPA routing).

---

## 2. Frontend Architecture

The frontend code has been refactored into a modular structure located in the `frontend/js/` directory. This separates concerns and makes the code easier to manage.

### File Structure
```
frontend/
├── js/
│   ├── api.js         # Handles all communication with the backend API
│   ├── app.js         # Main application entry point and state management
│   ├── player.js      # Encapsulates the Plyr video player logic
│   └── ui.js          # Handles all DOM manipulation and UI updates
├── index.html       # The main HTML file
├── styles.css       # Main application styles
└── ...              # Other static assets (PWA manifest, icons)
```

### Module Descriptions

#### `js/api.js`
- **Purpose**: To abstract all `fetch` calls to the backend into a clean, reusable interface.
- **Key Functions**:
  - `getFolders(path)`: Fetches the list of folders.
  - `getVideos(folderPath)`: Fetches the list of videos for a folder.
  - `getCover(bvid, page)`: Fetches the cover for a single video.
  - `getPlayInfo(folderPath, page)`: Gets the video and subtitle URLs for playback.

#### `js/ui.js`
- **Purpose**: To control all direct interactions with the DOM. This module is responsible for rendering content and updating the UI based on state changes. It does not contain any application logic.
- **Key Functions**:
  - `showScreen(screenName)`: Switches between the different screens (loading, folders, videos, player).
  - `renderFolders(folders, onFolderClick)`: Renders the folder list.
  - `renderVideos(videos, onVideoClick)`: Renders the video list.
  - `updateVideoCover(page, coverUrl)`: Updates a video's thumbnail.
  - `updatePathUI(currentPath)`: Updates the header and back button based on the current folder path.
  - `showError(message)`: Displays a temporary error toast.

#### `js/player.js`
- **Purpose**: To manage the Plyr video player instance. It wraps all player-related functionality in a `VideoPlayer` class.
- **Key Class**: `VideoPlayer`
  - `constructor(videoElementId, subtitleElementId)`: Initializes with the DOM element IDs.
  - `load(videoUrl, subtitleUrl)`: Loads a new video and optional subtitles into the player.
  - `destroy()`: Cleans up the player instance.

#### `js/app.js`
- **Purpose**: The central coordinator of the application. It holds the application state, handles user events, and calls the other modules to perform tasks.
- **Key Logic**:
  - Initializes the application by fetching the initial folder list.
  - Handles clicks on folders and videos, calling the `api.js` module to fetch data and the `ui.js` module to render it.
  - Manages the `currentPath` and `currentFolder` state.
  - Instantiates and uses the `VideoPlayer` from `player.js` to play videos.
  - Contains the PWA service worker registration logic.
