import json
import platform
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"

def _default_photos_root() -> str:
    if platform.system() == "Windows":
        return r"\\DX4600-HOMENAS\personal_folder\Photos"
    return "/photos"

DEFAULTS = {
    "storage_path": str(Path(__file__).resolve().parent),
    "photos_root": _default_photos_root(),
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            data = {}
        return {**DEFAULTS, **data}
    return dict(DEFAULTS)


def save_settings(settings: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def get_storage_path() -> Path:
    s = load_settings()
    p = Path(s["storage_path"]).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_photos_root() -> str:
    return load_settings().get("photos_root", _default_photos_root())
