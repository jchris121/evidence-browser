"""Evidence Browser — FastAPI backend.
Uses SQLite + FTS5 for instant search, file watcher for live data."""
import time
import os
import logging
import uvicorn
from logging_config import setup_logging
setup_logging()
from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from db import db
from search_api import rag_search, chat_with_evidence
from network_builder import get_cached_network, get_person_details
from legal_scanner import get_case_index, read_legal_file, LEGAL_BASE
from auth import auth_manager, VALID_ROLES

app = FastAPI(title="Evidence Browser")

# Load friendly device names
import json as _json
_dn_path = os.path.join(os.path.dirname(__file__), "device_names.json")
DEVICE_NAMES = _json.load(open(_dn_path)) if os.path.exists(_dn_path) else {}


# ─── Auth Middleware ───
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Public routes: static files, index, login/logout only
    # Media files exempt from bearer auth (img/audio/video tags can't send headers)
    # Still protected by Tailscale network + login required to see media URLs
    if (path.startswith("/static/") or
        path == "/" or
        path == "/login" or
        path == "/api/auth/login" or
        path == "/api/auth/logout" or
        (path.startswith("/api/media/") and not path.startswith("/api/media/list/"))):
        return await call_next(request)

    # All /api/* routes require auth
    if path.startswith("/api/"):
        token = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token:
            return Response(
                content='{"detail":"Not authenticated"}',
                status_code=401,
                media_type="application/json"
            )

        user = auth_manager.validate_session(token)
        if not user:
            return Response(
                content='{"detail":"Invalid or expired session"}',
                status_code=401,
                media_type="application/json"
            )

        request.state.user = user
        request.state.token = token

    return await call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start

    # Only log errors or slow requests (>2s)
    if response.status_code >= 400 or elapsed > 2.0:
        logger = logging.getLogger('access')
        user = getattr(request.state, 'user', None)
        msg = f"{request.method} {request.url.path} → {response.status_code} ({elapsed:.2f}s)"
        if user:
            msg += f" user={user.get('username', '?')}"
        if response.status_code >= 500:
            logger.error(msg)
        else:
            logger.warning(msg)
    return response


def get_current_user(request: Request) -> dict:
    return getattr(request.state, 'user', None)

def require_admin(request: Request) -> dict:
    user = getattr(request.state, 'user', None)
    if not user or user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ─── Auth Endpoints ───

class LoginRequest(BaseModel):
    username: str
    password: str

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"
    display_name: Optional[str] = None
    email: Optional[str] = None

class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class ResetPasswordRequest(BaseModel):
    password: str


@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")
    result = auth_manager.login(req.username, req.password, ip=ip, user_agent=ua)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid credentials or account locked")
    return result

@app.post("/api/auth/logout")
async def logout(request: Request):
    token = getattr(request.state, 'token', None)
    if token:
        auth_manager.logout(token)
    return {"ok": True}

@app.get("/api/auth/me")
async def auth_me(request: Request):
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

@app.get("/api/auth/check")
async def auth_check(request: Request):
    user = getattr(request.state, 'user', None)
    return {"authenticated": user is not None, "user": user}


# ─── Admin Endpoints ───

@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    require_admin(request)
    return auth_manager.list_users()

@app.post("/api/admin/users")
async def admin_create_user(req: CreateUserRequest, request: Request):
    require_admin(request)
    try:
        return auth_manager.create_user(
            username=req.username, password=req.password, role=req.role,
            display_name=req.display_name, email=req.email
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: str, req: UpdateUserRequest, request: Request):
    require_admin(request)
    try:
        result = auth_manager.update_user(
            user_id, display_name=req.display_name, email=req.email,
            role=req.role, is_active=req.is_active if req.is_active is not None else None
        )
        if not result:
            raise HTTPException(status_code=404, detail="User not found")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str, request: Request):
    admin = require_admin(request)
    if user_id == admin['id']:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    auth_manager.deactivate_user(user_id)
    return {"ok": True}

@app.post("/api/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, req: ResetPasswordRequest, request: Request):
    require_admin(request)
    try:
        auth_manager.reset_password(user_id, req.password)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/admin/login-history")
async def admin_login_history(request: Request, limit: int = 100):
    require_admin(request)
    return auth_manager.get_login_history(limit=limit)


# ─── Existing Endpoints ───

@app.get("/api/device-names")
async def device_names():
    return DEVICE_NAMES

@app.get("/api/device-info/{device_id}")
async def device_info(device_id: str):
    info = DEVICE_NAMES.get(device_id, {})
    return {
        "id": device_id,
        "display_name": info.get("name", device_id),
        "owner": info.get("owner", "Unknown"),
        "type": info.get("type", "unknown"),
        "email": info.get("email", ""),
        "phone": info.get("phone", ""),
    }


class ChatRequest(BaseModel):
    question: str
    model: str = "deepseek-r1:70b"
    top_k: int = 10
    device_scope: Optional[str] = None


@app.on_event("startup")
async def startup():
    db.full_index()
    db.start_watcher(interval=30)
    # Ensure default admin
    password = auth_manager.ensure_admin_exists()
    if password:
        print(f"\n⚠️  Default admin created. Username: admin, Password: {password}")
        print(f"⚠️  Change this immediately!\n")


# ─── Stats / Devices ───
@app.get("/api/stats")
async def get_stats():
    return db.get_stats()

@app.get("/api/devices")
async def get_devices():
    return db.get_devices()

@app.get("/api/device/{device_id}")
async def get_device(device_id: str, category: str = None, page: int = 1, per_page: int = 50, q: str = None, date_from: str = None, date_to: str = None):
    return db.get_device_data(device_id, category=category, page=page, per_page=per_page, query=q, date_from=date_from, date_to=date_to)

@app.get("/api/device/{device_id}/chat-threads")
async def get_chat_threads(device_id: str, page: int = 1, per_page: int = 50, search: str = None, date_from: str = None, date_to: str = None):
    return db.get_chat_threads(device_id, page=page, per_page=per_page, search=search, date_from=date_from, date_to=date_to)

@app.get("/api/device/{device_id}/chat-thread/{thread_id}")
async def get_thread_messages(device_id: str, thread_id: int):
    return db.get_thread_messages(device_id, thread_id)

# ─── Search ───
@app.get("/api/search")
async def search(q: str, device: str = None, category: str = None, page: int = 1, per_page: int = 50):
    return db.search_all(q, device_filter=device, category_filter=category, page=page, per_page=per_page)

@app.get("/api/rag-search")
async def semantic_search(q: str, top: int = 20):
    return rag_search(q, top_k=top)

# ─── Discoveries ───
@app.get("/api/discoveries")
async def discoveries(category: str = "all", person: str = "all", sort: str = "importance", page: int = 1, per_page: int = 50):
    return db.get_discoveries(category=category, person=person, sort=sort, page=page, per_page=per_page)

# ─── Refresh / Status ───
@app.post("/api/refresh")
async def refresh():
    return db.refresh()

@app.get("/api/index-status")
async def index_status():
    stats = db.get_stats()
    return {
        "last_indexed": stats.get("last_indexed", 0),
        "rag_chunks": stats.get("rag_chunks", 0),
        "total_devices": stats.get("total_devices", 0),
    }

# ─── Models / Chat ───
@app.get("/api/models")
async def get_models():
    import urllib.request, json as _json
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
            data = _json.loads(r.read())
        return [m["name"] for m in data.get("models", []) if m["name"] != "nomic-embed-text:latest"]
    except Exception:
        return ["deepseek-r1:70b"]

@app.post("/api/chat")
async def chat(req: ChatRequest):
    return chat_with_evidence(question=req.question, model=req.model, top_k=req.top_k, device_scope=req.device_scope)

# ─── Network Graph ───
@app.get("/api/network")
async def get_network():
    return get_cached_network()

@app.get("/api/network/person/{person_id}")
async def get_person(person_id: str):
    network = get_cached_network()
    details = get_person_details(person_id, network)
    if not details:
        return {"error": "Person not found"}
    return details

# ─── Legal Files ───
@app.get("/api/legal/cases")
async def get_legal_cases():
    return get_case_index()

@app.get("/api/legal/file")
async def get_legal_file(path: str):
    """Read a legal text file by path."""
    content = read_legal_file(path)
    if content is None:
        return {"error": "File not found or access denied"}
    return {"content": content, "path": path}

@app.get("/api/legal/pdf")
async def serve_legal_pdf(path: str):
    """Serve a legal PDF file."""
    from fastapi.responses import Response
    from pathlib import Path
    p = Path(path)
    if not p.exists() or not str(p.resolve()).startswith(str(LEGAL_BASE)):
        return Response(content="Not found", status_code=404)
    return FileResponse(str(p), media_type="application/pdf", filename=p.name)

# ─── Admin Logs ───
@app.get("/api/admin/logs")
async def admin_logs(request: Request, type: str = "app", lines: int = 50):
    require_admin(request)
    if type not in ("app", "auth", "access"):
        raise HTTPException(status_code=400, detail="Invalid log type")
    lines = min(max(1, lines), 500)
    log_path = os.path.join(os.path.dirname(__file__), 'logs', f'{type}.log')
    if not os.path.exists(log_path):
        return {"lines": [], "type": type}
    try:
        with open(log_path, 'r') as f:
            all_lines = f.readlines()
        return {"lines": [l.rstrip() for l in all_lines[-lines:]], "type": type}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Media Endpoints ───

import mimetypes
from pathlib import Path

MEDIA_EXTENSIONS = {
    'image': {'.jpg', '.jpeg', '.png', '.heic', '.gif', '.bmp', '.tiff', '.webp'},
    'audio': {'.m4a', '.mp3', '.wav', '.aac', '.ogg', '.3gp'},
    'video': {'.mp4', '.mov', '.avi', '.mkv', '.3gp', '.wmv'},
}
ALL_MEDIA_EXT = MEDIA_EXTENSIONS['image'] | MEDIA_EXTENSIONS['audio'] | MEDIA_EXTENSIONS['video']

MEDIA_PATHS = {
    "belinda-knisley": os.path.expanduser("~/clawd/tina-legal/cellebrite-extracted/belinda-knisley"),
    "joy-quinn": os.path.expanduser("~/clawd/tina-legal/cellebrite-extracted/joy-quinn"),
    "wendi-woods": os.path.expanduser("~/clawd/tina-legal/cellebrite-extracted/wendi-woods"),
    "zachary-quinn": os.path.expanduser("~/clawd/tina-legal/cellebrite-extracted/zachary-quinn"),
    "iphone11-graykey": os.path.expanduser("~/clawd/tina-legal/cellebrite-extracted/iphone11-graykey"),
}

# Allowed base directories for serving media (security)
ALLOWED_MEDIA_BASES = [
    os.path.expanduser("~/clawd/tina-legal/cellebrite-extracted"),
    os.path.expanduser("~/clawd/tina-legal/discovery"),
    os.path.expanduser("~/clawd/tina-legal/mega-discovery"),
]

# Cache: device_id -> (timestamp, file_list)
_media_cache: dict = {}
_MEDIA_CACHE_TTL = 3600  # 1 hour

def _classify_media(ext: str) -> str:
    ext = ext.lower()
    for mtype, exts in MEDIA_EXTENSIONS.items():
        if ext in exts:
            return mtype
    return 'unknown'

def _human_size(size: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != 'B' else f"{size} B"
        size /= 1024
    return f"{size:.1f} TB"

def _scan_media_files(device_id: str) -> list:
    """Scan and cache media files for a device."""
    now = time.time()
    if device_id in _media_cache:
        ts, cached = _media_cache[device_id]
        if now - ts < _MEDIA_CACHE_TTL:
            return cached

    base_path = MEDIA_PATHS.get(device_id)
    if not base_path or not os.path.isdir(base_path):
        _media_cache[device_id] = (now, [])
        return []

    files = []
    for root, dirs, filenames in os.walk(base_path):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in ALL_MEDIA_EXT:
                full = os.path.join(root, fname)
                try:
                    st = os.stat(full)
                    files.append({
                        "name": fname,
                        "path": full,
                        "type": _classify_media(ext),
                        "size": st.st_size,
                        "size_human": _human_size(st.st_size),
                    })
                except OSError:
                    pass

    _media_cache[device_id] = (now, files)
    return files


@app.get("/api/media/list/{device_id}")
async def media_list(device_id: str, media_type: str = "all", page: int = 1, per_page: int = 50):
    # Check if AXIOM device
    if device_id.startswith("RMR"):
        return {
            "files": [], "total": 0, "page": page, "per_page": per_page,
            "note": "AXIOM device media is embedded in portable case databases. Direct file listing not available."
        }

    # Resolve device_id - check if it's a merged base device
    # Try direct match first, then check device_names for sub-devices
    target_ids = [device_id]
    if device_id not in MEDIA_PATHS:
        # Check if any MEDIA_PATHS key starts with this device_id
        subs = [k for k in MEDIA_PATHS if k.startswith(device_id)]
        if subs:
            target_ids = subs
        else:
            return {"files": [], "total": 0, "page": page, "per_page": per_page,
                    "note": f"No media path configured for device '{device_id}'"}

    all_files = []
    for tid in target_ids:
        all_files.extend(_scan_media_files(tid))

    # Filter by type
    if media_type != "all" and media_type in MEDIA_EXTENSIONS:
        all_files = [f for f in all_files if f["type"] == media_type]

    total = len(all_files)
    start = (page - 1) * per_page
    end = start + per_page
    return {"files": all_files[start:end], "total": total, "page": page, "per_page": per_page}


@app.get("/api/media/{path:path}")
async def serve_media(path: str, request: Request):
    # Resolve to absolute path
    if not path.startswith("/"):
        path = "/" + path
    real = os.path.realpath(path)

    # Security: must be within allowed directories
    allowed = any(real.startswith(base) for base in ALLOWED_MEDIA_BASES)
    if not allowed or not os.path.isfile(real):
        raise HTTPException(status_code=404, detail="File not found")

    content_type, _ = mimetypes.guess_type(real)
    if not content_type:
        content_type = "application/octet-stream"

    file_size = os.path.getsize(real)

    # Handle range requests for streaming
    range_header = request.headers.get("range")
    if range_header:
        try:
            range_spec = range_header.replace("bytes=", "")
            start_str, end_str = range_spec.split("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1

            with open(real, "rb") as f:
                f.seek(start)
                data = f.read(length)

            return Response(
                content=data,
                status_code=206,
                media_type=content_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(length),
                },
            )
        except (ValueError, IndexError):
            raise HTTPException(status_code=416, detail="Invalid range")

    return FileResponse(real, media_type=content_type, headers={"Accept-Ranges": "bytes"})


# ─── Static ───
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/mockup", StaticFiles(directory="mockup"), name="mockup")

@app.get("/")
async def index():
    return FileResponse("static/index.html")

# Serve index.html for /login route too (SPA handles it)
@app.get("/login")
async def login_page():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8888)
