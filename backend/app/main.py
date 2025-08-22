from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIR, ensure_dirs_exist
from .router import router as api_router
from .bilibili import close_http_session, get_http_session

# Create necessary directories on startup
ensure_dirs_exist()

app = FastAPI(title="Video Player Backend")

# --- Event Handlers ---
@app.on_event("startup")
async def startup_event():
    # Initialize the global aiohttp session
    await get_http_session()
    print("🚀 Backend service started, aiohttp session created.")

@app.on_event("shutdown")
async def shutdown_event():
    # Cleanly close the aiohttp session
    await close_http_session()
    print("🔄 Backend service stopped, aiohttp session closed.")

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Router ---
app.include_router(api_router)

# --- Frontend Serving ---
# Mount the main frontend directory to serve js, css, etc.
app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend_static")

@app.get("/", response_class=HTMLResponse)
async def serve_frontend_root():
    """Serves the main index.html file for the root path."""
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend 'index.html' not found.")
    return FileResponse(index_path)

@app.get("/{file_path:path}", response_class=FileResponse)
async def serve_frontend_files(file_path: str):
    """Serves other static files for the frontend, required for SPA routing."""
    file = FRONTEND_DIR / file_path
    # Check if the requested file exists and is a file
    if file.is_file():
        return FileResponse(file)

    # If the path does not correspond to a file, assume SPA routing and serve index.html
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend 'index.html' not found.")
    return FileResponse(index_path)
