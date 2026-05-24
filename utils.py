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

BASE_DIR = Path(__file__).resolve().parent
ALBUM_BASE = BASE_DIR / "album"
THUMBS_BASE = BASE_DIR / "thumbs"


def is_raw(filename: str) -> bool:
    return Path(filename).suffix.lower() in RAW_EXTENSIONS


def is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def get_album_dir(category: str) -> Path:
    d = ALBUM_BASE / category
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_thumbs_dir(category: str) -> Path:
    d = THUMBS_BASE / category
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
    thumb_path = thumb_dir / filename
    img = Image.open(src_path)
    img.thumbnail(size)
    img.save(thumb_path, "JPEG", quality=85)
    return str(thumb_path)


def sanitize_filename(name: str) -> str:
    return "".join(c for c in name if c not in r'\/:*?"<>|')
