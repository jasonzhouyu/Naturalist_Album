import uuid
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
SHARES_FILE = Path(__file__).resolve().parent / "shares.json"


def _load() -> dict:
    if SHARES_FILE.exists():
        with open(SHARES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"shares": []}


def _save(data: dict):
    with open(SHARES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_share(artifact_id: str, category: str) -> dict:
    share_id = uuid.uuid4().hex[:8]
    data = _load()
    share = {
        "id": share_id,
        "artifact_id": artifact_id,
        "category": category,
        "created_at": datetime.now(TZ).isoformat(),
        "view_count": 0,
    }
    data["shares"].append(share)
    _save(data)
    return share


def get_share(share_id: str) -> dict | None:
    data = _load()
    for s in data["shares"]:
        if s["id"] == share_id:
            s["view_count"] += 1
            _save(data)
            return s
    return None


def delete_share(share_id: str) -> bool:
    data = _load()
    for i, s in enumerate(data["shares"]):
        if s["id"] == share_id:
            data["shares"].pop(i)
            _save(data)
            return True
    return False
