"""统一的 secret 加载，处理双重部署。

加载顺序（每个 key 独立）:
    1. os.environ
    2. .env 文件 (按 SECRETS_ENV_PATHS 顺序首个存在的)

iNat JWT 特殊路径:
    - INAT_JWT_FILE 环境变量指向的文件 (Docker sidecar 写在 /keys/inat_jwt.txt)
    - 否则同上的 INATURALIST_JWT 走通用流程
"""
from __future__ import annotations

import os
from pathlib import Path

# 按优先级，第一个存在的 .env 被加载
SECRETS_ENV_PATHS = [
    os.environ.get("RELIC_ENV", ""),
    r"Y:\Openclaw\workspace\.env",
    "/keys/.env",
    str(Path(__file__).resolve().parent / ".env"),
]

_dotenv_cache: dict[str, str] | None = None


def _load_dotenv() -> dict[str, str]:
    global _dotenv_cache
    if _dotenv_cache is not None:
        return _dotenv_cache
    out: dict[str, str] = {}
    for path in SECRETS_ENV_PATHS:
        if not path:
            continue
        p = Path(path)
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
            break
        except Exception:
            continue
    _dotenv_cache = out
    return out


def get_secret(name: str, default: str = "") -> str:
    """env 优先，.env 兜底。"""
    val = os.environ.get(name, "").strip()
    if val:
        return val
    return _load_dotenv().get(name, default)


def get_inat_jwt() -> str:
    """JWT 加载: INAT_JWT_FILE 文件 > INATURALIST_JWT (env / .env)."""
    jwt_file = os.environ.get("INAT_JWT_FILE", "").strip()
    if jwt_file:
        try:
            content = Path(jwt_file).read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError:
            pass
    return get_secret("INATURALIST_JWT")
