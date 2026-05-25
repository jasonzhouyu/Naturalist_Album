"""Pl@ntNet API 客户端 + 结果解析。

Pl@ntNet 给得很干脆: family / genus / species 学名 + 通用名 + 分数。
界门纲目 没给 — 由 Qwen-plus 补全（见 vision.py）。
"""
from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
import urllib.error
import uuid
from pathlib import Path

from secrets_loader import get_secret

API_URL = "https://my-api.plantnet.org/v2/identify/all"
USER_AGENT = "relic-album/0.1 (personal photo cataloging)"

HIGH_THRESHOLD = 0.40   # Pl@ntNet score 是 0-1
LOW_THRESHOLD = 0.10


class PlantnetError(Exception):
    pass


class PlantnetLowConfidence(Exception):
    def __init__(self, candidates: list[dict]):
        self.candidates = candidates
        super().__init__(f"low confidence, {len(candidates)} candidates")


def identify(image_path: str, organs: str = "auto") -> dict:
    api_key = get_secret("PLANTNET_API_KEY")
    if not api_key:
        raise PlantnetError("PLANTNET_API_KEY not set (check .env)")

    image_data = Path(image_path).read_bytes()
    filename = Path(image_path).name
    ext = Path(image_path).suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp"}.get(ext, "image/jpeg")
    boundary = f"----relicalbum{uuid.uuid4().hex}"

    body = io.BytesIO()
    # field: organs (允许多值，对应每张图)
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="organs"\r\n\r\n')
    body.write(organs.encode())
    body.write(b"\r\n")
    # field: images
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="images"; filename="{filename}"\r\n'.encode())
    body.write(f"Content-Type: {mime}\r\n\r\n".encode())
    body.write(image_data)
    body.write(f"\r\n--{boundary}--\r\n".encode())

    url = f"{API_URL}?{urllib.parse.urlencode({'api-key': api_key, 'lang': 'zh', 'no-reject': 'false'})}"
    req = urllib.request.Request(url, data=body.getvalue(), method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:300]
        if e.code == 401:
            raise PlantnetError(f"Pl@ntNet auth failed (HTTP 401): {body_text}")
        if e.code == 404:
            # Pl@ntNet 在没识别到时返回 404 "Species Not Found"
            raise PlantnetLowConfidence([])
        raise PlantnetError(f"Pl@ntNet HTTP {e.code}: {body_text}")
    except urllib.error.URLError as e:
        raise PlantnetError(f"Pl@ntNet connection failed: {e}")


def recognize_plant(image_path: str) -> dict:
    response = identify(image_path)
    results = response.get("results") or []
    if not results:
        raise PlantnetLowConfidence([])

    top = results[0]
    score = float(top.get("score") or 0)
    if score < LOW_THRESHOLD:
        raise PlantnetLowConfidence(results[:3])

    confidence = "高" if score >= HIGH_THRESHOLD else "中"
    schema = _build_schema(top, confidence)
    if confidence == "中":
        schema["_candidates"] = [_summarize(r) for r in results[:3]]
    schema["_plantnet_score"] = round(score, 3)
    return schema


def _build_schema(result: dict, confidence: str) -> dict:
    species = result.get("species") or {}
    family = species.get("family") or {}
    genus = species.get("genus") or {}
    common_names = species.get("commonNames") or []
    chinese_name = next((n for n in common_names if any("一" <= c <= "鿿" for c in n)), "")
    if not chinese_name and common_names:
        chinese_name = common_names[0]

    return {
        "chinese_name": chinese_name,
        "scientific_name": species.get("scientificNameWithoutAuthor", ""),
        "kingdom": "Plantae",
        "phylum": "",
        "class": "",
        "order": "",
        "family": family.get("scientificNameWithoutAuthor", ""),
        "genus": genus.get("scientificNameWithoutAuthor", ""),
        "species": species.get("scientificNameWithoutAuthor", "").split(" ", 1)[-1] if " " in species.get("scientificNameWithoutAuthor", "") else "",
        "distribution": "",
        "habitat": "",
        "confidence": confidence,
    }


def _summarize(result: dict) -> dict:
    species = result.get("species") or {}
    return {
        "scientific_name": species.get("scientificNameWithoutAuthor", ""),
        "common_names": species.get("commonNames", [])[:2],
        "score": round(float(result.get("score") or 0), 3),
    }
