"""向法老的飞书私信发文本消息。

用法:
    python scripts/feishu_notify.py "消息内容"
    echo "消息" | python scripts/feishu_notify.py -

读取 Y:\\Openclaw\\workspace\\.env 中的:
    FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_OPEN_ID
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

# 兼容 reprocess.py 的 PROJECT_DIR 设定
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from secrets_loader import get_secret

_raw_domain = (get_secret("FEISHU_DOMAIN") or "feishu").strip().lower()
# 兼容 "feishu" / "lark" / 完整 URL 三种写法
if _raw_domain.startswith("http"):
    DOMAIN = _raw_domain.rstrip("/")
elif _raw_domain == "lark":
    DOMAIN = "https://open.larksuite.com"
else:
    DOMAIN = "https://open.feishu.cn"
TOKEN_URL = f"{DOMAIN}/open-apis/auth/v3/tenant_access_token/internal"
SEND_URL = f"{DOMAIN}/open-apis/im/v1/messages?receive_id_type=open_id"


def get_token() -> str:
    app_id = get_secret("FEISHU_APP_ID")
    app_secret = get_secret("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET not configured")
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    if data.get("code") != 0:
        raise RuntimeError(f"feishu token error: {data}")
    return data["tenant_access_token"]


def send_text(message: str, receive_id: str | None = None) -> dict:
    receive_id = receive_id or get_secret("FEISHU_USER_OPEN_ID")
    if not receive_id:
        raise RuntimeError("FEISHU_USER_OPEN_ID not configured")
    token = get_token()
    body = json.dumps({
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": message}, ensure_ascii=False),
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        SEND_URL, data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"feishu send HTTP {e.code}: {body_text}")


def main():
    if len(sys.argv) < 2:
        print("usage: feishu_notify.py '<message>' | feishu_notify.py -", file=sys.stderr)
        sys.exit(1)
    arg = sys.argv[1]
    if arg == "-":
        msg = sys.stdin.read().strip()
    else:
        msg = arg
    if not msg:
        print("[err] empty message", file=sys.stderr)
        sys.exit(1)
    result = send_text(msg)
    print(f"[ok] feishu sent: code={result.get('code')} msg_id={result.get('data', {}).get('message_id', '?')}")


if __name__ == "__main__":
    main()
