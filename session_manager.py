import uuid
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
SESSION_FILE = Path(__file__).resolve().parent / "batch_sessions.json"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif",
                    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2"}


def _load() -> dict:
    if SESSION_FILE.exists():
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(sessions: dict):
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


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

    sessions = _load()
    sessions[session_id] = session
    _save(sessions)
    return session


def get_session(session_id: str) -> dict | None:
    return _load().get(session_id)


def tag_files(session_id: str, indices: list[int], category: str | None):
    sessions = _load()
    session = sessions.get(session_id)
    if not session:
        raise KeyError("Session not found")

    for idx in indices:
        if 0 <= idx < len(session["files"]):
            session["files"][idx]["category"] = category

    _save(sessions)
    return session


def set_location(session_id: str, location: str, indices: list[int] | None = None):
    sessions = _load()
    session = sessions.get(session_id)
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

    _save(sessions)
    return session
