"""批量导入会话存储。

每个会话独立 JSON 文件 batch_sessions/{session_id}.json，加内存缓存避免每次请求都重读磁盘。
保留旧 batch_sessions.json 的兼容读取（首次访问时拆分迁移）。
"""
import os
import uuid
import json
from pathlib import Path
from threading import RLock
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
BASE_DIR = Path(__file__).resolve().parent
SESSION_DIR = BASE_DIR / "batch_sessions"
LEGACY_FILE = BASE_DIR / "batch_sessions.json"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif",
                    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2"}

_cache: dict[str, dict] = {}
_lock = RLock()
_legacy_migrated = False


def _ensure_dir() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def _migrate_legacy() -> None:
    """旧 batch_sessions.json 拆分为 per-session 文件后重命名备份。一次性。"""
    global _legacy_migrated
    if _legacy_migrated:
        return
    _legacy_migrated = True
    if not LEGACY_FILE.exists():
        return
    try:
        with open(LEGACY_FILE, "r", encoding="utf-8") as f:
            sessions = json.load(f)
    except Exception:
        return
    _ensure_dir()
    for sid, sess in sessions.items():
        target = SESSION_DIR / f"{sid}.json"
        if target.exists():
            continue
        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(sess, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    try:
        LEGACY_FILE.rename(LEGACY_FILE.with_suffix(".json.bak"))
    except OSError:
        pass


def _session_path(session_id: str) -> Path:
    return SESSION_DIR / f"{session_id}.json"


def _read_from_disk(session_id: str) -> dict | None:
    p = _session_path(session_id)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_to_disk(session: dict) -> None:
    _ensure_dir()
    p = _session_path(session["id"])
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _load(session_id: str) -> dict | None:
    with _lock:
        _migrate_legacy()
        cached = _cache.get(session_id)
        if cached is not None:
            return cached
        s = _read_from_disk(session_id)
        if s is not None:
            _cache[session_id] = s
        return s


def _store(session: dict) -> None:
    with _lock:
        _cache[session["id"]] = session
        _write_to_disk(session)


def create_session(directory: str) -> dict:
    dir_path = Path(directory).resolve()
    if not dir_path.is_dir():
        raise ValueError(f"不是有效目录: {directory}")

    files = []
    for entry in sorted(dir_path.iterdir()):
        if entry.is_file() and entry.suffix.lower() in IMAGE_EXTENSIONS:
            files.append({
                "index": len(files),
                "path": str(entry),
                "name": entry.name,
                "category": None,
                "location": None,
            })

    if not files:
        raise ValueError("目录中没有支持的照片文件")

    session_id = uuid.uuid4().hex
    session = {
        "id": session_id,
        "directory": str(dir_path),
        "files": files,
        "default_location": "",
        "created_at": datetime.now(TZ).isoformat(),
    }
    _store(session)
    return session


def get_session(session_id: str) -> dict | None:
    return _load(session_id)


def save_session(session: dict) -> None:
    _store(session)


def tag_files(session_id: str, indices: list[int], category: str | None) -> dict:
    session = _load(session_id)
    if not session:
        raise KeyError("Session not found")
    for idx in indices:
        if 0 <= idx < len(session["files"]):
            session["files"][idx]["category"] = category
    _store(session)
    return session


def set_location(session_id: str, location: str, indices: list[int] | None = None) -> dict:
    session = _load(session_id)
    if not session:
        raise KeyError("Session not found")
    if indices is None:
        session["default_location"] = location
        for f in session["files"]:
            f["location"] = location
    else:
        for idx in indices:
            if 0 <= idx < len(session["files"]):
                session["files"][idx]["location"] = location
    _store(session)
    return session
