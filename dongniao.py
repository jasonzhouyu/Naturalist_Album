"""懂鸟 /niaodian2 图片识别客户端。

webkey 从 secrets_loader 读取 DONGNIAO_WEBKEY（写入 .env），有效期 7 天。
过期时接口返回 Challenge，调用方收到 DongniaoAuthRequired 后应提示用户
运行 scripts/dongniao_auth.py 刷新 webkey。
"""
from __future__ import annotations

import io
import json
import urllib.request
import urllib.error
from pathlib import Path

from secrets_loader import get_secret

API_URL = "https://dongniao.net/niaodian2"
MAX_DIM  = 1600   # 超过此边长自动缩放
JPEG_Q   = 85


class DongniaoError(Exception):
    pass


class DongniaoAuthRequired(DongniaoError):
    """webkey 失效，需要重新运行 scripts/dongniao_auth.py 刷新。"""
    def __init__(self, code: str):
        self.code = code
        super().__init__(f"webkey 已失效，请运行 scripts/dongniao_auth.py 完成验证（验证码 {code}）")


def _get_webkey() -> str:
    key = get_secret("DONGNIAO_WEBKEY")
    if not key:
        raise DongniaoError("DONGNIAO_WEBKEY 未配置，请运行 scripts/dongniao_auth.py")
    return key


def _resize_jpeg(image_bytes: bytes) -> bytes:
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_DIM:
            s = MAX_DIM / max(w, h)
            img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=JPEG_Q)
        return buf.getvalue()
    except ImportError:
        return image_bytes


def _post(image_bytes: bytes, webkey: str) -> list:
    boundary = "----DongniaoClient"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="img.jpg"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + image_bytes + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="async"\r\n\r\n0\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="sc"\r\n\r\nweb\r\n'
        f"--{boundary}--\r\n"
    ).encode()

    req = urllib.request.Request(API_URL, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Cookie", f"webkey={webkey}")
    req.add_header("Referer", "https://dongniao.net/photoid.html")
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; relic-album)")

    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        raise DongniaoError(f"网络请求失败: {e}")


def identify(image_bytes: bytes) -> list[dict]:
    """识别图片，返回 Top5 结果列表。

    每条格式:
        {
          "score": 85.3,          # 置信度 %
          "bird_id": 1192,        # 懂鸟物种 ID
          "chinese_name": "棕尾鵟",
          "english_name": "Long-legged Buzzard",
          "scientific_name": "Buteo rufinus",
          "order": "ACCIPITRIFORMES",
          "family": "Accipitridae",
        }

    Raises:
        DongniaoAuthRequired: webkey 失效，需要重新验证。
        DongniaoError: 其他错误。
    """
    webkey = _get_webkey()
    img = _resize_jpeg(image_bytes)
    data = _post(img, webkey)

    if not data:
        raise DongniaoError("接口返回空结果")

    # Challenge 响应: [[code, "Challenge", webkey_to_activate], ...]
    if len(data[0]) >= 2 and data[0][1] == "Challenge":
        raise DongniaoAuthRequired(str(data[0][0]))

    results = []
    for item in data[:5]:
        # item 格式: [score, bird_id, cn_name, en_name, sci_name, cn_name2, order, family]
        results.append({
            "score":          round(float(item[0]), 1),
            "bird_id":        item[1],
            "chinese_name":   item[2] if len(item) > 2 else "",
            "english_name":   item[3] if len(item) > 3 else "",
            "scientific_name": item[4] if len(item) > 4 else "",
            "order":          item[6] if len(item) > 6 else "",
            "family":         item[7] if len(item) > 7 else "",
        })
    return results


def identify_file(path: str | Path) -> list[dict]:
    return identify(Path(path).read_bytes())
