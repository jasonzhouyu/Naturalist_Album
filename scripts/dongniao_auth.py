"""懂鸟 webkey 获取工具。

运行后在浏览器打开 http://localhost:19876
扫码验证完成后自动把 webkey 写入项目 .env。
"""
import base64, json, re, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import request as urlreq
from urllib.parse import parse_qs, urlparse

PORT = 19876
PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / ".env"

QR_URL = "https://dongniao.net/images/dongniao_430.jpg"
API_URL = "https://dongniao.net/niaodian2"

# 缓存当前 challenge
_state = {"code": None, "webkey": None, "verified": False}


def _fetch_challenge(image_path: Path) -> tuple[str, str] | None:
    """用随机图片调 /niaodian2，拿 challenge code 和待激活 webkey。"""
    import io
    with open(image_path, "rb") as f:
        img_bytes = f.read()

    boundary = "----DongniaoAuthBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="img.jpg"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + img_bytes + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="async"\r\n\r\n0\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="sc"\r\n\r\nweb\r\n'
        f"--{boundary}--\r\n"
    ).encode()

    req = urlreq.Request(API_URL, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Referer", "https://dongniao.net/photoid.html")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        with urlreq.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        if data and data[0][1] == "Challenge":
            return str(data[0][0]), str(data[0][2])
    except Exception as e:
        print(f"[err] fetch_challenge: {e}")
    return None


def _test_webkey(webkey: str, image_path: Path) -> bool:
    """用 webkey cookie 测试识别是否通过。"""
    import io
    with open(image_path, "rb") as f:
        img_bytes = f.read()

    boundary = "----DongniaoTestBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="img.jpg"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + img_bytes + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="async"\r\n\r\n0\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="sc"\r\n\r\nweb\r\n'
        f"--{boundary}--\r\n"
    ).encode()

    req = urlreq.Request(API_URL, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Cookie", f"webkey={webkey}")
    req.add_header("Referer", "https://dongniao.net/photoid.html")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        with urlreq.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        if data and data[0][1] != "Challenge":
            return True
    except Exception as e:
        print(f"[err] test_webkey: {e}")
    return False


def _save_webkey(webkey: str):
    """把 webkey 写入 .env 文件。"""
    content = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    pattern = re.compile(r"^DONGNIAO_WEBKEY\s*=.*$", re.MULTILINE)
    new_line = f"DONGNIAO_WEBKEY={webkey}"
    if pattern.search(content):
        content = pattern.sub(new_line, content)
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        content += new_line + "\n"
    ENV_FILE.write_text(content, encoding="utf-8")
    print(f"[ok] webkey 已写入 {ENV_FILE}")


def _get_qr_b64() -> str:
    try:
        with urlreq.urlopen(QR_URL, timeout=10) as r:
            return base64.b64encode(r.read()).decode()
    except Exception:
        return ""


# 找一张测试图（thumbs/animal里第一张）
def _find_test_image() -> Path:
    for p in (PROJECT_DIR / "thumbs" / "animal").glob("*.jpg"):
        return p
    # fallback
    return PROJECT_DIR / "thumbs" / "animal" / "鹤形目-Grus-grus_新疆_001.jpg"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>懂鸟 webkey 验证</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 520px; margin: 60px auto; padding: 20px; color: #222; }}
  h2 {{ font-size: 1.4em; margin-bottom: 4px; }}
  .card {{ background: #f7f7f7; border-radius: 12px; padding: 24px; margin: 20px 0; }}
  .code {{ font-size: 3em; font-weight: 700; color: #d32f2f; letter-spacing: 6px; margin: 12px 0; }}
  .qr img {{ width: 200px; height: 200px; border-radius: 8px; }}
  .steps {{ font-size: 0.9em; line-height: 1.9; color: #555; }}
  .steps b {{ color: #222; }}
  button {{ background: #1976d2; color: #fff; border: none; border-radius: 8px;
             padding: 12px 32px; font-size: 1em; cursor: pointer; margin-top: 16px; }}
  button:hover {{ background: #1565c0; }}
  .status {{ margin-top: 16px; padding: 12px; border-radius: 8px; font-weight: 600; }}
  .ok {{ background: #e8f5e9; color: #2e7d32; }}
  .fail {{ background: #ffebee; color: #c62828; }}
  .pending {{ background: #fff3e0; color: #e65100; }}
</style>
</head>
<body>
<h2>🐦 懂鸟 webkey 验证</h2>
<p style="color:#888;font-size:.9em">完成一次微信验证，Cookie 有效期 7 天</p>

<div class="card">
  <div class="steps">
    <b>第 1 步</b>：用微信扫描下方小程序码<br>
    <b>第 2 步</b>：进入懂鸟 → 左上角菜单 → 我的设置<br>
    <b>第 3 步</b>：滑到最底部 → 点击 <b>核验身份</b><br>
    <b>第 4 步</b>：输入下方验证码并提交<br>
    <b>第 5 步</b>：回到这里点「验证完成」
  </div>
</div>

<div style="display:flex;gap:32px;align-items:center;margin:8px 0">
  <div class="qr"><img src="data:image/jpeg;base64,{qr_b64}" alt="懂鸟小程序码"></div>
  <div>
    <div style="color:#888;font-size:.85em">验证码</div>
    <div class="code">{code}</div>
    <div style="color:#aaa;font-size:.8em">webkey（验证后生效）</div>
    <div style="font-size:.75em;word-break:break-all;color:#666">{webkey}</div>
  </div>
</div>

<button onclick="verify()">✅ 我已在微信完成验证</button>
<div id="status"></div>

<script>
function verify() {{
  document.getElementById('status').innerHTML = '<div class="status pending">⏳ 正在测试 webkey…</div>';
  fetch('/verify').then(r=>r.json()).then(d=>{{
    if (d.ok) {{
      document.getElementById('status').innerHTML = '<div class="status ok">✅ 验证成功！webkey 已写入 .env，可以关闭此页面。</div>';
    }} else {{
      document.getElementById('status').innerHTML = '<div class="status fail">❌ 验证未通过，请确认已在微信小程序完成核验，再试一次。</div>';
    }}
  }}).catch(()=>{{
    document.getElementById('status').innerHTML = '<div class="status fail">❌ 请求失败，请刷新页面重试。</div>';
  }});
}}
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            html = HTML_TEMPLATE.format(
                qr_b64=_state.get("qr_b64", ""),
                code=_state.get("code", "获取中..."),
                webkey=_state.get("webkey", "..."),
            )
            self._respond(200, "text/html; charset=utf-8", html.encode())

        elif path == "/verify":
            webkey = _state.get("webkey", "")
            img = _find_test_image()
            ok = _test_webkey(webkey, img) if webkey else False
            if ok:
                _state["verified"] = True
                _save_webkey(webkey)
            self._respond(200, "application/json", json.dumps({"ok": ok}).encode())

        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, code, ct, body):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


def main():
    img = _find_test_image()
    if not img.exists():
        sys.exit(f"[err] 找不到测试图片: {img}")

    print("[*] 获取 challenge 中...")
    result = _fetch_challenge(img)
    if not result:
        sys.exit("[err] 无法获取 challenge，检查网络")

    code, webkey = result
    _state["code"] = code
    _state["webkey"] = webkey
    _state["qr_b64"] = _get_qr_b64()

    print(f"[*] 验证码: {code}")
    print(f"[*] webkey: {webkey}")
    print(f"[*] 启动本地服务: http://localhost:{PORT}")

    def open_browser():
        time.sleep(0.8)
        webbrowser.open(f"http://localhost:{PORT}")

    threading.Thread(target=open_browser, daemon=True).start()

    server = HTTPServer(("localhost", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] 已停止")


if __name__ == "__main__":
    main()
