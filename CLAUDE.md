# Naturalist Album — 自然观察相册

FastAPI web app for AI-powered photo cataloging. Three categories: 文物 (relics), 动物 (animals), 植物 (plants).

## How to run

```bash
# Local dev (hot reload)
cd C:\Users\jason\Projects\relic-album
python main.py
# → http://localhost:8000

# Docker deploy to NAS
python deploy_nas.py
# → http://192.168.31.233:8000
```

Requires Python 3.12+. No venv — runs on system Python. Dependencies: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `Pillow`, `rawpy`, `paramiko` (NAS deploy only), `dashscope` (Alibaba Cloud AI).

## Environment

API keys managed in `Y:\Openclaw\workspace\.env`. The app reads `DASHSCOPE_API_KEY` from that file via `vision.py` → `dotenv`. If AI recognition fails, check that the key is set.

## Architecture

```
main.py              — FastAPI app, all routes (MUST follow route ordering rules)
processor.py         — Photo pipeline: RAW extract → cache check → AI recognize → thumbnail → archive
vision.py            — DashScope API calls: qwen-vl-max (vision), qwen-plus (text generation)
utils.py             — Metadata CRUD, filename generation, thumbnail creation
cache_manager.py     — LLM result cache (SHA256 file hash × category → recognition result)
session_manager.py   — Batch import session state (batch_sessions.json)
share_manager.py     — Share link management (shares.json)
settings_manager.py  — Storage path config (settings.json)
deploy_nas.py        — Docker build + SCP to NAS + docker run via paramiko SSH
```

## Frontend

- Pure custom CSS, NO framework (Pico.css removed in UI redesign)
- Single stylesheet at `static/style.css` with full design system
  - CSS variables for colors/radius/shadows (`--bg`, `--surface`, `--primary`, `--radius`, etc.)
  - Apple-inspired neutrals + dark fixed top navbar
  - Card-based gallery (Google Photos style): `auto-fill` grid, 4:3 aspect ratio, hover scale
  - Detail page is two-column on desktop (`detail-grid`), stacks on mobile
  - System font stack, no external font loads
- Templates extend `base.html`. Active nav highlight via `request.url.path` checks.
- All JS is inline in templates (no separate JS files yet)

## Route ordering (CRITICAL)

FastAPI matches routes in registration order. Specific routes MUST register before wildcard `/{category}` and `/{category}/{artifact_id}`. Current order in main.py:

1. Static mounts (`/static`, `/album`, `/thumbs`)
2. `/` — homepage
3. `/settings` — GET/POST
4. `/album` — unified search
5. `/upload/{category}` — GET/POST
6. `/batch` — GET
7. `/batch/scan` — POST
8. `/api/browse-dir` — POST (server-side directory browser)
9. `/batch/upload-files` — POST (legacy browser folder picker, kept but UI-removed)
10. `/batch/{session_id}` — GET
11. `/batch-preview/{session_id}/{index}` — GET
12. `/batch/{session_id}/tag` — POST
13. `/batch/{session_id}/location` — POST
14. `/batch/{session_id}/process` — POST
15. `/share/{share_id}` — GET
16. `/api/share/{category}/{artifact_id}` — POST
17. `/api/share/{share_id}` — DELETE
18. `/photo/{category}/{artifact_id}` — GET (indexed files)
19. `/{category}` — category album (WILDCARD)
20. `/api/{category}` — JSON API
21. `/{category}/{artifact_id}` — detail page (WILDCARD)
22. DELETE `/{category}/{artifact_id}`
23. POST `/{category}/{artifact_id}/edit`

**Never** add a new route after the wildcards without placing it before, or it will 404.

## Key flows

### Batch import (primary workflow — index-in-place)
1. User opens `/batch` and uses the **server-side directory browser** to navigate drives + NAS UNC paths
2. Click a folder → drills in via `POST /api/browse-dir`. Folder contents listed; image count shown if photos exist
3. Click "扫描目录" → `POST /batch/scan` creates session by listing image files in-place (no upload, no copy)
4. User tags each photo with category (relic/animal/plant/null) and optional location
5. "处理全部" → `POST /batch/{id}/process` → calls `process_photo()` per tagged file
6. Index-only mode is **enabled by default** — original files stay where they are; only thumbnails + metadata are stored

### Directory browser API
- `POST /api/browse-dir` with `{"path": "..."}` (empty = list drives + NAS roots)
- Returns `{items: [{name, path, type}], current, image_count}`
- `type` is `drive` | `network` | `dir`
- NAS roots hardcoded: `\\DX4600-HOMENAS`, `\\192.168.31.233`
- Hidden files (`.foo`) skipped; permission errors return 403

### Index-only mode
- Default ON in batch flow
- Skips `shutil.copy2` — original file stays in place
- Stores `source_path` (absolute path) in artifact metadata
- Still generates thumbnails in `thumbs/{category}/`
- Detail page serves from `/photo/{category}/{id}` instead of `/album/{filename}`
- Fallback: if source file is gone, tries album dir

### AI recognition
- `vision.py` → DashScope API
- Relic: returns name, dynasty, material, museum, discovery_place, etc.
- Animal/Plant: returns taxonomy (kingdom→species), distribution, habitat
- Description generated separately via qwen-plus

### LLM cache
- Key: `SHA256(file_bytes):category`
- Stored in `llm_cache.json` (gitignored)
- Cache hit → skips both recognize() and generate_description()

### Storage paths
- Default: `{project_dir}/album/` and `{project_dir}/thumbs/`
- Configurable via Settings page → `settings.json` → `storage_path`
- `utils.py` resolves storage path lazily via `get_storage_path()` to avoid circular imports

### Share links
- `POST /api/share/{category}/{id}` → creates share token
- `GET /share/{id}` → read-only detail view, no edit/delete buttons
- Shares tracked in `shares.json` with view counter

## File naming

| Category | Format | Example |
|----------|--------|---------|
| relic | `{name}_{dynasty}_{counter}.ext` | `青花瓷_明_001.jpg` |
| animal | `{order}-{genus}-{species}_{location}_{counter}.ext` | `食肉目-猫属-豹猫_北京_001.jpg` |
| plant | `{order}-{genus}-{species}_{location}_{counter}.ext` | `蔷薇目-蔷薇属-月季_公园_001.jpg` |

## Gitignored runtime files

`llm_cache.json`, `batch_sessions.json`, `shares.json`, `settings.json`, `.env`, `uploads/`, `uploads/sessions/`, `album/**/*`, `thumbs/**/*`

## NAS (UGREEN DX4600)

- IP: `192.168.31.233`
- SSH: port 22, user `pcwork`
- Docker container: `nature-album`, port 8000
- Deploy: `python deploy_nas.py` (packages → SCP → docker build+run)
- NAS firewall sometimes blocks SSH — if deploy fails with connection error, check SSH service on NAS web admin
- NAS is behind transparent proxy (mihomo on router), but Docker build uses `--network host` to bypass

### 已知部署坑（2026-05-26 首次成功部署）

**坑1：pip 超时（`files.pythonhosted.org` 被墙）**
- 症状：`docker compose build --no-cache` 跑到 pydantic 下载时 ReadTimeoutError
- 原因：`Dockerfile` 没配 pip 镜像，国内 NAS 直连 PyPI 被墙
- 修复：`Dockerfile` 加阿里云镜像源：
  ```dockerfile
  RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
      pip config set global.trusted-host mirrors.aliyun.com && \
      pip install --no-cache-dir -r requirements.txt
  ```

**坑2：`inat-jwt-refresher` sidecar 构建失败**
- 症状：Playwright 从 npmmirror 下载 `chromium-headless-shell v1223` 返回 404；Docker Hub 拉基础镜像超时
- 原因：npmmirror 没有该 Playwright 版本；NAS Docker 无法直连 Docker Hub
- 修复：`docker-compose.yml` 给 `inat-jwt-refresher` 加 `profiles: ["inat"]`，默认部署跳过它
- 需要 iNat 功能时手动启：`docker compose --profile inat up -d`

## Template notes

- Templates in `templates/`, plain Jinja2, no framework
- `base.html` provides fixed top dark navbar with active-state highlighting
- All templates use `request` as first arg to `TemplateResponse` (Starlette 1.0.0 requirement)
- Category labels in templates: `CATEGORY_LABELS = {"relic": "文物", "animal": "动物", "plant": "植物"}`
- Breadcrumb pattern: `<ul class="breadcrumb">` with auto separators via CSS

## Recent changes (2026-05-26 session)

- **首次 NAS 部署成功**：`python deploy_nas.py` → `http://192.168.31.233:8000`
- **Dockerfile**：加阿里云 pip 镜像，解决 PyPI 被墙超时问题
- **docker-compose.yml**：`inat-jwt-refresher` 加 `profiles: ["inat"]`，默认不构建/启动

## Recent changes (2026-05-25 session)

- **UI redesign**: Removed Pico.css, wrote custom CSS design system (`static/style.css`). Card-based gallery, dark fixed navbar, hover animations, fadeInUp entrance animation.
- **Batch import flow rewrite**: Removed browser-based folder upload (caused "upload N files?" prompts). Replaced with server-side directory browser at `POST /api/browse-dir` — clickable tree starting from drives + NAS roots. UNC paths supported.
- **Index-only by default**: The "仅索引" checkbox in batch_tag is now checked by default — files stay in place.

## Known issues / TODO

- UNC path validation in `session_manager.create_session` uses `Path(directory).resolve()` which may transform `\\server\share` paths unexpectedly. If user reports "不是有效目录" for a NAS path that exists, check whether `resolve()` is the culprit.
- No batch deletion / re-tagging from album view — once processed, photos can only be edited/deleted one-by-one via detail page.
- No way to re-scan a directory and pick up new photos (would need session merge logic).
