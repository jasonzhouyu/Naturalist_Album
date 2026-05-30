"""通过 Playwright 自动登录 iNaturalist，抓取 24h JWT 并持久化。

凭证来源（按优先级）:
    1. 环境变量 INATURALIST_USERNAME / INATURALIST_PASSWORD (Docker 推荐)
    2. .env 文件 (RELIC_ENV 指定路径，默认 Y:\\Openclaw\\workspace\\.env)

输出位置（按优先级）:
    1. JWT_OUTPUT_FILE 环境变量指定的文件 (Docker 推荐) — 写入纯 token
    2. .env 中替换 INATURALIST_JWT 一行 (Windows 本地默认)

状态缓存:
    STATE_PATH 环境变量指定的路径，默认项目根 .inat_state/state.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ENV_PATH = Path(os.environ.get("RELIC_ENV", r"Y:\Openclaw\workspace\.env"))
JWT_OUTPUT_FILE = os.environ.get("JWT_OUTPUT_FILE", "")  # 设置后写文件而非 .env
_default_state = Path(__file__).resolve().parent.parent / ".inat_state" / "state.json"
STATE_PATH = Path(os.environ.get("STATE_PATH", str(_default_state)))

LOGIN_URL = "https://www.inaturalist.org/login"
TOKEN_URL = "https://www.inaturalist.org/users/api_token"

JWT_RE = re.compile(r'"api_token"\s*:\s*"([^"]+)"')


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        sys.exit(f"[err] .env not found: {path}")
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _get_proxy() -> str:
    """INAT_PROXY: 优先 env 变量，其次 .env 文件。"""
    val = os.environ.get("INAT_PROXY", "")
    if val:
        return val
    env = load_env(ENV_PATH)
    return env.get("INAT_PROXY", "")


PROXY = _get_proxy()


def update_env(path: Path, key: str, value: str) -> None:
    """在 .env 中替换一行 KEY=...，保留其他行。原子写。"""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^(\s*){re.escape(key)}\s*=.*$", re.MULTILINE)
    repl = rf"\1{key}={value}"
    new_text, n = pattern.subn(repl, text)
    if n == 0:
        if not new_text.endswith("\n"):
            new_text += "\n"
        new_text += f"{key}={value}\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, path)


def get_credentials() -> tuple[str, str]:
    """优先 env，其次 .env 文件。"""
    username = os.environ.get("INATURALIST_USERNAME", "").strip()
    password = os.environ.get("INATURALIST_PASSWORD", "").strip()
    if username and password:
        return username, password
    if ENV_PATH.exists():
        env = load_env(ENV_PATH)
        username = username or env.get("INATURALIST_USERNAME", "")
        password = password or env.get("INATURALIST_PASSWORD", "")
    if not username or not password:
        sys.exit("[err] INATURALIST_USERNAME / INATURALIST_PASSWORD not set "
                 "(checked env vars and .env)")
    return username, password


def write_jwt(jwt: str) -> str:
    """根据配置写到文件或 .env，返回写入位置描述。"""
    if JWT_OUTPUT_FILE:
        out = Path(JWT_OUTPUT_FILE)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(jwt, encoding="utf-8")
        os.replace(tmp, out)
        return f"file {out}"
    if not ENV_PATH.exists():
        sys.exit(f"[err] no JWT_OUTPUT_FILE set and .env not found: {ENV_PATH}")
    update_env(ENV_PATH, "INATURALIST_JWT", jwt)
    return f".env at {ENV_PATH}"


def fetch_jwt() -> str:
    username, password = get_credentials()

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        proxy_arg = {"server": PROXY} if PROXY else None
        browser = p.chromium.launch(headless=True, proxy=proxy_arg)
        ctx_kwargs = {"locale": "en-US"}
        if STATE_PATH.exists():
            ctx_kwargs["storage_state"] = str(STATE_PATH)
        ctx = browser.new_context(**ctx_kwargs)
        page = ctx.new_page()

        jwt = _try_token_with_session(page)
        if jwt is None:
            print("[info] cookies missing or expired — running full login")
            _login(page, username, password)
            jwt = _try_token_with_session(page)
            if jwt is None:
                _dump_failure(page)
                browser.close()
                sys.exit("[err] login succeeded but token page returned no JWT")

        ctx.storage_state(path=str(STATE_PATH))
        browser.close()
        return jwt


def _try_token_with_session(page) -> str | None:
    try:
        page.goto(TOKEN_URL, wait_until="networkidle", timeout=30000)
    except PlaywrightTimeout:
        return None
    body = page.content()
    m = JWT_RE.search(body)
    if not m:
        return None
    return m.group(1)


def _login(page, username: str, password: str) -> None:
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    # 字段名 iNat 历史上稳定，但留 fallback
    user_sel = 'input[name="user[email]"], input#user_email, input[type="text"][name*="email"]'
    pass_sel = 'input[name="user[password]"], input#user_password, input[type="password"]'
    submit_sel = 'input[type="submit"], button[type="submit"]'

    page.fill(user_sel, username)
    page.fill(pass_sel, password)
    page.click(submit_sel)
    # 等跳出 /login 即可，无需等具体页加载完
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=30000)
    except PlaywrightTimeout:
        # 仍在 login 页 → 大概率密码错或触发验证码
        _dump_failure(page)
        raise SystemExit("[err] login appears to have failed (still on /login)")


def _dump_failure(page) -> None:
    out_dir = STATE_PATH.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(out_dir / "fail.png"), full_page=True)
        (out_dir / "fail.html").write_text(page.content(), encoding="utf-8")
        print(f"[info] failure dump saved to {out_dir}")
    except Exception:
        pass


def main() -> None:
    t0 = time.time()
    jwt = fetch_jwt()
    location = write_jwt(jwt)
    elapsed = time.time() - t0
    print(f"[ok] JWT refreshed (len={len(jwt)}, took {elapsed:.1f}s, written to {location})")


if __name__ == "__main__":
    main()
