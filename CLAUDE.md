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

## Route ordering (CRITICAL)

FastAPI matches routes in registration order. Specific routes MUST register before wildcard `/{category}` and `/{category}/{artifact_id}`. Current order in main.py:

1. Static mounts (`/static`, `/album`, `/thumbs`)
2. `/` — homepage
3. `/settings` — GET/POST
4. `/album` — unified search
5. `/upload/{category}` — GET/POST
6. `/batch` — GET
7. `/batch/scan` — POST
8. `/batch/upload-files` — POST (browser folder picker)
9. `/batch/{session_id}` — GET
10. `/batch-preview/{session_id}/{index}` — GET
11. `/batch/{session_id}/tag` — POST
12. `/batch/{session_id}/location` — POST
13. `/batch/{session_id}/process` — POST
14. `/share/{share_id}` — GET
15. `/api/share/{category}/{artifact_id}` — POST
16. `/api/share/{share_id}` — DELETE
17. `/photo/{category}/{artifact_id}` — GET (indexed files)
18. `/{category}` — category album (WILDCARD)
19. `/api/{category}` — JSON API
20. `/{category}/{artifact_id}` — detail page (WILDCARD)
21. DELETE `/{category}/{artifact_id}`
22. POST `/{category}/{artifact_id}/edit`

**Never** add a new route after line 18 without placing it before the wildcards, or it will 404.

## Key flows

### Batch import (primary workflow)
1. User enters directory path OR uses browser folder picker
2. Server scans directory / receives uploads → creates session
3. User tags each photo with category (relic/animal/plant/null) and optional location
4. "处理全部" → `POST /batch/{id}/process` → calls `process_photo()` per tagged file
5. `process_photo()`: RAW extract → cache lookup → AI recognize → AI description → copy to album (or index only) → thumbnail → metadata

### Index-only mode
When `index_only=True` checkbox is checked in batch page:
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
- Docker container: `relic-album`, port 8000
- Deploy: `python deploy_nas.py` (packages → SCP → docker build+run)
- NAS firewall sometimes blocks SSH — if deploy fails with connection error, check SSH service on NAS web admin
- NAS is behind transparent proxy (mihomo on router), but Docker build uses `--network host` to bypass

## Template notes

- Jinja2 templates in `templates/`, Pico.css v2 for styling
- `base.html` provides nav bar with links to all sections
- All templates use `request` as first arg to `TemplateResponse` (Starlette 1.0.0 requirement)
- Category labels in templates: `CATEGORY_LABELS = {"relic": "文物", "animal": "动物", "plant": "植物"}`
