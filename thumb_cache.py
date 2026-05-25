"""会话期缩略图缓存。

为批量导入页提供 ~256px 的小缩略图，避免浏览器直接加载 RAW/全尺寸 JPEG。
按需生成，磁盘缓存到 uploads/session_thumbs/{session_id}/{index}.jpg。
"""
import io
from pathlib import Path
from threading import Lock

from PIL import Image

from utils import RAW_EXTENSIONS

BASE_DIR = Path(__file__).resolve().parent
THUMB_ROOT = BASE_DIR / "uploads" / "session_thumbs"
THUMB_SIZE = (512, 512)
JPEG_QUALITY = 78

_locks: dict[str, Lock] = {}
_locks_guard = Lock()


def _lock_for(key: str) -> Lock:
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = Lock()
            _locks[key] = lock
        return lock


def thumb_path(session_id: str, index: int) -> Path:
    return THUMB_ROOT / session_id / f"{index}.jpg"


def get_or_create(session_id: str, index: int, source_path: str) -> Path | None:
    """返回缩略图路径，不存在则同步生成。失败返回 None。"""
    dest = thumb_path(session_id, index)
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    lock = _lock_for(f"{session_id}:{index}")
    with lock:
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            _generate(source_path, dest)
        except Exception:
            if dest.exists():
                try:
                    dest.unlink()
                except OSError:
                    pass
            return None
    return dest if dest.exists() else None


def _generate(src: str, dest: Path) -> None:
    ext = Path(src).suffix.lower()
    if ext in RAW_EXTENSIONS:
        img = _open_raw(src)
    else:
        img = Image.open(src)
        img.draft("RGB", THUMB_SIZE)

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
    img.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True)


def _open_raw(src: str) -> Image.Image:
    """RAW 文件先取嵌入 JPEG（快），失败回落 half-size demosaic。"""
    import rawpy
    try:
        with rawpy.imread(src) as raw:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                return Image.open(io.BytesIO(thumb.data))
            if thumb.format == rawpy.ThumbFormat.BITMAP:
                return Image.fromarray(thumb.data)
    except Exception:
        pass

    with rawpy.imread(src) as raw:
        rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True)
    return Image.fromarray(rgb)


def cleanup_session(session_id: str) -> None:
    import shutil
    target = THUMB_ROOT / session_id
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
