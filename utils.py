import os
import json
import uuid
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

from PIL import Image

TZ = timezone(timedelta(hours=8))

RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}
ALLOWED_EXTENSIONS = RAW_EXTENSIONS | IMAGE_EXTENSIONS

CATEGORIES = ["relic", "animal", "plant"]

from settings_manager import get_storage_path, get_photos_root

BASE_DIR = Path(__file__).resolve().parent


def _album_base() -> Path:
    return get_storage_path() / "album"


def _thumbs_base() -> Path:
    return get_storage_path() / "thumbs"


def is_raw(filename: str) -> bool:
    return Path(filename).suffix.lower() in RAW_EXTENSIONS


def is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def get_album_dir(category: str) -> Path:
    d = _album_base() / category
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_thumbs_dir(category: str) -> Path:
    d = _thumbs_base() / category
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_metadata_file(category: str) -> Path:
    return BASE_DIR / f"metadata_{category}.json"


def load_metadata(category: str) -> dict:
    f = get_metadata_file(category)
    if f.exists() and f.stat().st_size > 0:
        with open(f, "r", encoding="utf-8") as fp:
            return json.load(fp)
    data = {"artifacts": [], "category": category}
    save_metadata(category, data)
    return data


def save_metadata(category: str, data: dict):
    with open(get_metadata_file(category), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_artifact(category: str, info: dict) -> dict:
    data = load_metadata(category)
    artifact = {
        "id": uuid.uuid4().hex[:8],
        "category": category,
        **info,
        "created_at": datetime.now(TZ).isoformat(),
    }
    data["artifacts"].append(artifact)
    save_metadata(category, data)
    return artifact


def delete_artifact(category: str, artifact_id: str) -> bool:
    data = load_metadata(category)
    for i, a in enumerate(data["artifacts"]):
        if a["id"] == artifact_id:
            album_path = get_album_dir(category) / a["filename"]
            thumb_path = get_thumbs_dir(category) / a["filename"]
            if album_path.exists():
                album_path.unlink()
            if thumb_path.exists():
                thumb_path.unlink()
            data["artifacts"].pop(i)
            save_metadata(category, data)
            return True
    return False


def update_artifact(category: str, artifact_id: str, updates: dict) -> dict | None:
    data = load_metadata(category)
    for a in data["artifacts"]:
        if a["id"] == artifact_id:
            a.update(updates)
            save_metadata(category, data)
            return a
    return None


def generate_filename(category: str, info: dict, ext: str, location: str = "") -> str:
    if category == "relic":
        name = info.get("name", "未知文物")
        dynasty = info.get("dynasty", "")
        base = f"{name}_{dynasty}" if dynasty and dynasty != "未知" else name
    else:
        order = info.get("order", "")
        genus = info.get("genus", "")
        species = info.get("species", "")
        parts = [p for p in [order, genus, species] if p and p != "未知"]
        base = "-".join(parts) if parts else info.get("chinese_name", f"未知{category}")
        if location:
            base = f"{base}_{location}"

    base = sanitize_filename(base)
    album_dir = get_album_dir(category)
    existing = [f for f in os.listdir(album_dir) if f.startswith(base)]
    counter = len(existing) + 1
    return f"{base}_{counter:03d}{ext}"


def create_thumbnail(src_path: str, category: str, filename: str, size=(400, 400)):
    thumb_dir = get_thumbs_dir(category)
    jpg_filename = Path(filename).stem + ".jpg"
    thumb_path = thumb_dir / jpg_filename
    img = Image.open(src_path)
    img.thumbnail(size)
    img.save(thumb_path, "JPEG", quality=85)
    return str(thumb_path)


def sanitize_filename(name: str) -> str:
    return "".join(c for c in name if c not in r'\/:*?"<>|')


# ── 照片根目录 / 相对路径 ──────────────────────────────────────────────────────

import re as _re

# 已知 UNC 前缀模式（主机名\\共享名\\Photos\\）
_UNC_PHOTOS_RE = _re.compile(
    r"^\\\\[^\\]+\\[^\\]+\\Photos\\(.*)", _re.IGNORECASE
)

def make_relative_source(abs_path: str) -> str:
    """把绝对 source_path 转成相对于 photos_root 的路径（正斜杠）。
    如果无法识别前缀，原样返回。
    """
    if not abs_path:
        return abs_path

    root = get_photos_root().rstrip("/\\")

    # 先尝试直接用 pathlib 求相对路径（跨平台）
    try:
        rel = Path(abs_path).relative_to(root)
        return str(rel).replace("\\", "/")
    except ValueError:
        pass

    # 回退：剥离 UNC \\HOST\SHARE\Photos\ 前缀
    m = _UNC_PHOTOS_RE.match(abs_path)
    if m:
        return m.group(1).replace("\\", "/")

    return abs_path


def resolve_source_path(source_path: str) -> str:
    """把 source_path（可能是相对或旧式绝对路径）解析为本机可访问的绝对路径。"""
    if not source_path:
        return ""

    # 已经是绝对路径且存在 → 直接用
    p = Path(source_path)
    if p.is_absolute() and p.exists():
        return source_path

    # 是相对路径 → 拼接 photos_root
    if not p.is_absolute():
        root = get_photos_root()
        candidate = Path(root) / source_path.replace("\\", "/")
        return str(candidate)

    # 旧式 UNC 绝对路径 → 转换为相对后再拼接 photos_root
    rel = make_relative_source(source_path)
    if rel != source_path:
        root = get_photos_root()
        return str(Path(root) / rel.replace("\\", "/"))

    return source_path
