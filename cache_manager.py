import hashlib
import json
from pathlib import Path

CACHE_FILE = Path(__file__).resolve().parent / "llm_cache.json"


def _hash_file(file_path: str) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _cache_key(file_path: str, category: str) -> str:
    return f"{_hash_file(file_path)}:{category}"


def load_cache() -> dict:
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"entries": {}}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def check_cache(file_path: str, category: str) -> dict | None:
    cache = load_cache()
    key = _cache_key(file_path, category)
    return cache["entries"].get(key)


def put_cache(file_path: str, category: str, recognition: dict, description: str):
    cache = load_cache()
    key = _cache_key(file_path, category)
    cache["entries"][key] = {
        "sha256": _hash_file(file_path),
        "category": category,
        "recognition": recognition,
        "description": description,
    }
    save_cache(cache)
