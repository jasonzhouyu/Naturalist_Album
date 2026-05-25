"""iNaturalist Computer Vision API 客户端 + 结果解析。

主流程:
    score_image(path) → top results
    recognize_animal(path) → 我们的 schema dict 或 None (low-confidence, 让上层兜底)

阈值:
    HIGH_THRESHOLD: combined_score 之上直接采纳 iNat 结果
    LOW_THRESHOLD: 之下放弃 iNat，让 Qwen-VL 接管
    中间: 用 iNat top-1 但置信度标"中"
"""
from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
import urllib.error
import uuid
from pathlib import Path

from secrets_loader import get_inat_jwt

CV_URL = "https://api.inaturalist.org/v1/computervision/score_image"
USER_AGENT = "relic-album/0.1 (+https://github.com/anthropics/claude-code; personal photo cataloging)"

HIGH_THRESHOLD = 70   # combined_score 0-100
LOW_THRESHOLD = 35

CLASS_TO_KINGDOM = {
    "Animalia": "Animalia",
}

# iconic_taxon_name → 我们 schema 的近似纲映射（粗粒度后备）
ICONIC_TO_CLASS_CN = {
    "Aves": "鸟纲",
    "Mammalia": "哺乳纲",
    "Reptilia": "爬行纲",
    "Amphibia": "两栖纲",
    "Actinopterygii": "辐鳍鱼纲",
    "Insecta": "昆虫纲",
    "Arachnida": "蛛形纲",
    "Mollusca": "软体动物门",  # 这是门级，但占位用
}


class InatError(Exception):
    pass


class InatLowConfidence(Exception):
    """iNat 给了候选但置信度太低，调用方应兜底到 Qwen-VL。"""

    def __init__(self, candidates: list[dict]):
        self.candidates = candidates
        super().__init__(f"low confidence, {len(candidates)} candidates")


def score_image(image_path: str, locale: str = "zh-CN",
                lat: float | None = None, lng: float | None = None) -> dict:
    jwt = get_inat_jwt()
    if not jwt:
        raise InatError("INATURALIST_JWT not set (check .env or INAT_JWT_FILE)")

    image_data = Path(image_path).read_bytes()
    boundary = f"----relicalbum{uuid.uuid4().hex}"
    filename = Path(image_path).name
    ext = Path(image_path).suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp"}.get(ext, "image/jpeg")

    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'.encode())
    body.write(f"Content-Type: {mime}\r\n\r\n".encode())
    body.write(image_data)
    body.write(f"\r\n--{boundary}--\r\n".encode())

    params: dict = {"locale": locale}
    if lat is not None and lng is not None:
        params["lat"] = lat
        params["lng"] = lng
    url = f"{CV_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, data=body.getvalue(), method="POST", headers={
        "Authorization": f"Bearer {jwt}",
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
            raise InatError(f"iNat auth failed (HTTP 401) — JWT expired? {body_text}")
        raise InatError(f"iNat HTTP {e.code}: {body_text}")
    except urllib.error.URLError as e:
        raise InatError(f"iNat connection failed: {e}")


def recognize_animal(image_path: str, lat: float | None = None,
                     lng: float | None = None) -> dict | None:
    """高级识别。

    返回:
        - 高置信度: 完整 schema dict（chinese_name 等填好；分类学需后续 Qwen 补全）
        - 中置信度: schema dict 但 confidence='中'，并附 _candidates 字段供上层增强
        - 低置信度: raise InatLowConfidence (上层应兜底 Qwen-VL)
        - 完全失败: raise InatError
    """
    response = score_image(image_path, lat=lat, lng=lng)
    results = response.get("results") or []
    if not results:
        raise InatLowConfidence([])

    top = results[0]
    score = float(top.get("combined_score") or 0)
    if score < LOW_THRESHOLD:
        raise InatLowConfidence(results[:3])

    confidence = "高" if score >= HIGH_THRESHOLD else "中"
    schema = _build_schema(top, confidence)
    if confidence == "中":
        schema["_candidates"] = [_summarize(r) for r in results[:3]]
    schema["_inat_score"] = round(score, 1)
    return schema


def _build_schema(result: dict, confidence: str) -> dict:
    taxon = result.get("taxon") or {}
    name = taxon.get("name", "")  # 学名
    common = taxon.get("preferred_common_name", "")
    rank = taxon.get("rank", "")  # species/genus/family/...
    iconic = taxon.get("iconic_taxon_name", "")

    # iNat 在 species rank 时 name 形如 "Genus species"
    genus = ""
    species = ""
    if rank == "species" and " " in name:
        parts = name.split(" ", 1)
        genus, species = parts[0], parts[1]
    elif rank == "genus":
        genus = name

    return {
        "chinese_name": common or "",         # iNat 给的 zh locale 优先；缺失留空，让 Qwen-plus 补
        "scientific_name": name,
        "kingdom": "Animalia",
        "phylum": "",                         # iNat 不直接给，留空
        "class": ICONIC_TO_CLASS_CN.get(iconic, iconic),
        "order": "",
        "family": "",
        "genus": genus,
        "species": species,
        "distribution": "",
        "habitat": "",
        "confidence": confidence,
    }


def _summarize(result: dict) -> dict:
    taxon = result.get("taxon") or {}
    return {
        "scientific_name": taxon.get("name", ""),
        "common_name": taxon.get("preferred_common_name", ""),
        "rank": taxon.get("rank", ""),
        "score": round(float(result.get("combined_score") or 0), 1),
    }
