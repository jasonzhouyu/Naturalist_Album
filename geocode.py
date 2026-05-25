"""高德地理编码: 中文地址 → (lat, lng)。带内存缓存。

用于把用户输入的"新疆吐尔加辽草原"这类地址转成坐标，
喂给 Pl@ntNet (latitude/longitude) 和 iNat (lat/lng) 提升识别准确性。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
import urllib.error
from threading import Lock

from secrets_loader import get_secret

GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"

_cache: dict[str, tuple[float, float] | None] = {}
_lock = Lock()


def lookup(address: str) -> tuple[float, float] | None:
    """中文地址 → (lat, lng) 或 None。失败和命中都缓存。"""
    if not address:
        return None
    key = address.strip()
    if not key:
        return None

    with _lock:
        if key in _cache:
            return _cache[key]

    api_key = get_secret("AMAP_KEY") or get_secret("AMAP_API_KEY")
    if not api_key:
        print("[geocode] AMAP_KEY not set, geocoding disabled")
        with _lock:
            _cache[key] = None
        return None

    params = urllib.parse.urlencode({"address": key, "key": api_key, "output": "JSON"})
    try:
        with urllib.request.urlopen(f"{GEOCODE_URL}?{params}", timeout=10) as r:
            data = json.loads(r.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"[geocode] {key!r} failed: {e}")
        with _lock:
            _cache[key] = None
        return None

    if data.get("status") != "1" or data.get("infocode") != "10000":
        print(f"[geocode] {key!r}: amap returned {data.get('info')}")
        with _lock:
            _cache[key] = None
        return None

    geocodes = data.get("geocodes") or []
    if not geocodes:
        with _lock:
            _cache[key] = None
        return None

    loc = geocodes[0].get("location", "")
    if "," not in loc:
        with _lock:
            _cache[key] = None
        return None
    try:
        lng_str, lat_str = loc.split(",", 1)
        lat, lng = float(lat_str), float(lng_str)
    except ValueError:
        with _lock:
            _cache[key] = None
        return None

    coords = (lat, lng)
    print(f"[geocode] {key!r} → ({lat:.4f}, {lng:.4f})")
    with _lock:
        _cache[key] = coords
    return coords
