import os
import sys
import uuid
import shutil
import json
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
os.chdir(str(BASE_DIR))

CATEGORIES = ["relic", "animal", "plant"]

from utils import (
    load_metadata, add_artifact, delete_artifact, update_artifact,
    ALLOWED_EXTENSIONS, CATEGORIES,
)
from processor import process_photo
from session_manager import create_session, get_session, tag_files, set_location, save_session
from share_manager import create_share, get_share, delete_share
from settings_manager import load_settings, save_settings, get_storage_path

app = FastAPI(title="自然观察相册")

# 静态文件
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/album", StaticFiles(directory=str(BASE_DIR / "album")), name="album")
app.mount("/thumbs", StaticFiles(directory=str(BASE_DIR / "thumbs")), name="thumbs")

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# 品类中文名
CATEGORY_LABELS = {
    "relic": "文物",
    "animal": "动物",
    "plant": "植物",
}


def validate_category(category: str):
    if category not in CATEGORIES:
        return None
    return category


# === 首页 — 品类选择 ===

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    counts = {}
    for c in CATEGORIES:
        data = load_metadata(c)
        counts[c] = len(data["artifacts"])
    return templates.TemplateResponse(request, "index.html", {
        "categories": CATEGORIES,
        "labels": CATEGORY_LABELS,
        "counts": counts,
    })


# === 设置页 ===

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    s = load_settings()
    return templates.TemplateResponse(request, "settings.html", {"settings": s})


@app.post("/settings")
async def settings_save(request: Request):
    body = await request.json()
    storage_path = body.get("storage_path", "").strip()
    if not storage_path:
        return JSONResponse({"error": "请输入存储路径"}, status_code=400)
    p = Path(storage_path)
    if not p.is_absolute():
        return JSONResponse({"error": "请输入绝对路径"}, status_code=400)
    save_settings({"storage_path": str(p)})
    return JSONResponse({"ok": True})


# === 统一相册（跨品类搜索） ===

@app.get("/album", response_class=HTMLResponse)
async def album_all(request: Request, q: str = ""):
    all_artifacts = []
    for c in CATEGORIES:
        data = load_metadata(c)
        for a in data["artifacts"]:
            a["_category"] = c
            a["_label"] = CATEGORY_LABELS[c]
            all_artifacts.append(a)

    # 模糊搜索：匹配所有字符串字段
    if q.strip():
        keyword = q.strip().lower()
        filtered = []
        for a in all_artifacts:
            # 将所有字段值拼成一个字符串用于搜索
            search_text = " ".join(
                str(v).lower() for v in a.values()
                if isinstance(v, str)
            )
            if keyword in search_text:
                filtered.append(a)
        all_artifacts = filtered

    return templates.TemplateResponse(request, "album_all.html", {
        "artifacts": all_artifacts,
        "query": q,
        "total": len(all_artifacts),
    })


# === 上传页（必须在 /{category} 之前注册，否则被通配路由拦截）===

@app.get("/upload/{category}", response_class=HTMLResponse)
async def upload_page(request: Request, category: str):
    if not validate_category(category):
        return HTMLResponse("不存在的品类", status_code=404)
    return templates.TemplateResponse(request, "upload.html", {
        "category": category,
        "label": CATEGORY_LABELS[category],
    })


@app.post("/upload/{category}")
async def upload_photo(category: str, file: UploadFile = File(...)):
    if not validate_category(category):
        return JSONResponse({"error": "不存在的品类"}, status_code=404)

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse({"error": f"不支持的文件格式: {ext}"}, status_code=400)

    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = UPLOAD_DIR / filename
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    result = process_photo(str(file_path), category)

    if file_path.exists():
        file_path.unlink()

    if "error" in result:
        return JSONResponse(result, status_code=400)

    return JSONResponse(result)


# === 批量导入 ===

@app.get("/batch", response_class=HTMLResponse)
async def batch_scan_page(request: Request):
    return templates.TemplateResponse(request, "batch_scan.html", {})


@app.post("/batch/scan")
async def batch_scan(request: Request):
    body = await request.json()
    directory = body.get("directory", "").strip()
    if not directory:
        return JSONResponse({"error": "请输入目录路径"}, status_code=400)
    try:
        session = create_session(directory)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"session_id": session["id"], "file_count": len(session["files"])})


@app.post("/batch/upload-files")
async def batch_upload_files(request: Request):
    """接收浏览器上传的文件，创建临时会话目录"""
    import tempfile
    form = await request.form()
    uploaded = form.getlist("files")

    if not uploaded:
        return JSONResponse({"error": "没有选择文件"}, status_code=400)

    # 创建临时会话目录
    tmp_root = BASE_DIR / "uploads" / "sessions"
    tmp_root.mkdir(parents=True, exist_ok=True)
    session_id = uuid.uuid4().hex
    session_dir = tmp_root / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for i, f in enumerate(uploaded):
        safe_name = Path(f.filename).name
        dest = session_dir / safe_name
        with open(dest, "wb") as out:
            content = await f.read()
            out.write(content)
        files.append({
            "index": len(files),
            "path": str(dest),
            "name": safe_name,
            "category": None,
            "location": None,
        })

    if not files:
        shutil.rmtree(session_dir)
        return JSONResponse({"error": "没有有效的图片文件"}, status_code=400)

    # 复用 session_manager 的数据结构
    session = {
        "id": session_id,
        "directory": str(session_dir),
        "files": files,
        "default_location": "",
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone(__import__("datetime").timedelta(hours=8))).isoformat(),
    }

    save_session(session)
    return JSONResponse({"session_id": session_id, "file_count": len(files)})


@app.get("/batch/{session_id}", response_class=HTMLResponse)
async def batch_tag_page(request: Request, session_id: str):
    session = get_session(session_id)
    if not session:
        return HTMLResponse("会话不存在或已过期", status_code=404)
    return templates.TemplateResponse(request, "batch_tag.html", {
        "session": session,
    })


@app.get("/batch-preview/{session_id}/{index}")
async def serve_batch_preview(session_id: str, index: int):
    from fastapi.responses import FileResponse
    session = get_session(session_id)
    if not session:
        return HTMLResponse("Session not found", status_code=404)
    try:
        file_info = session["files"][int(index)]
    except (IndexError, ValueError):
        return HTMLResponse("File not found", status_code=404)
    return FileResponse(file_info["path"])


@app.post("/batch/{session_id}/tag")
async def batch_tag(session_id: str, request: Request):
    body = await request.json()
    indices = body.get("indices", [])
    category = body.get("category")
    if category is not None and category not in CATEGORIES:
        return JSONResponse({"error": "Invalid category"}, status_code=400)
    try:
        session = tag_files(session_id, indices, category)
    except KeyError:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse({"ok": True, "files": session["files"]})


@app.post("/batch/{session_id}/location")
async def batch_location(session_id: str, request: Request):
    body = await request.json()
    location = body.get("location", "").strip()
    indices = body.get("indices")
    try:
        session = set_location(session_id, location, indices)
    except KeyError:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse({"ok": True, "files": session["files"]})


@app.post("/batch/{session_id}/process")
async def batch_process(session_id: str):
    session = get_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    to_process = [(f, f["category"]) for f in session["files"]
                  if f["category"] in CATEGORIES]

    if not to_process:
        return JSONResponse({"error": "没有标记任何照片"}, status_code=400)

    results = []
    for file_info, category in to_process:
        location = file_info.get("location") or session.get("default_location", "")
        try:
            artifact = process_photo(file_info["path"], category, location=location)
            results.append({"file": file_info["name"], "ok": True, "artifact": artifact})
        except Exception as e:
            results.append({"file": file_info["name"], "ok": False, "error": str(e)})

    return JSONResponse({"results": results, "total": len(to_process)})


# === 分享链接 ===

@app.get("/share/{share_id}", response_class=HTMLResponse)
async def share_view(request: Request, share_id: str):
    share = get_share(share_id)
    if not share:
        return HTMLResponse("链接不存在或已过期", status_code=404)
    data = load_metadata(share["category"])
    artifact = next((a for a in data["artifacts"] if a["id"] == share["artifact_id"]), None)
    if not artifact:
        return HTMLResponse("记录已被删除", status_code=404)
    return templates.TemplateResponse(request, "share_view.html", {
        "category": share["category"],
        "label": CATEGORY_LABELS[share["category"]],
        "artifact": artifact,
        "share_id": share_id,
    })


@app.post("/api/share/{category}/{artifact_id}")
async def create_share_link(category: str, artifact_id: str):
    if not validate_category(category):
        return JSONResponse({"error": "不存在的品类"}, status_code=404)
    share = create_share(artifact_id, category)
    return JSONResponse({"share_id": share["id"], "url": f"/share/{share['id']}"})


@app.delete("/api/share/{share_id}")
async def revoke_share_link(share_id: str):
    ok = delete_share(share_id)
    if not ok:
        return JSONResponse({"error": "Share not found"}, status_code=404)
    return JSONResponse({"ok": True})


# === 品类相册 ===

@app.get("/{category}", response_class=HTMLResponse)
async def album_view(request: Request, category: str):
    if not validate_category(category):
        return HTMLResponse("不存在的品类", status_code=404)
    data = load_metadata(category)
    return templates.TemplateResponse(request, "album.html", {
        "category": category,
        "label": CATEGORY_LABELS[category],
        "artifacts": data["artifacts"],
    })


# === JSON API（必须在 /{category}/{artifact_id} 之前注册）===

@app.get("/api/{category}")
async def api_artifacts(category: str):
    if not validate_category(category):
        return JSONResponse({"error": "不存在的品类"}, status_code=404)
    data = load_metadata(category)
    return JSONResponse(data["artifacts"])


# === 详情页 ===

@app.get("/{category}/{artifact_id}", response_class=HTMLResponse)
async def detail(request: Request, category: str, artifact_id: str):
    if not validate_category(category):
        return HTMLResponse("不存在的品类", status_code=404)
    data = load_metadata(category)
    artifact = next((a for a in data["artifacts"] if a["id"] == artifact_id), None)
    if not artifact:
        return HTMLResponse("记录不存在", status_code=404)
    return templates.TemplateResponse(request, "detail.html", {
        "category": category,
        "label": CATEGORY_LABELS[category],
        "artifact": artifact,
    })

# === 删除 ===

@app.delete("/{category}/{artifact_id}")
async def remove_artifact(category: str, artifact_id: str):
    if not validate_category(category):
        return JSONResponse({"error": "不存在的品类"}, status_code=404)
    ok = delete_artifact(category, artifact_id)
    if not ok:
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    return JSONResponse({"ok": True})


# === 编辑 ===

@app.post("/{category}/{artifact_id}/edit")
async def edit_artifact(category: str, artifact_id: str, request: Request):
    if not validate_category(category):
        return JSONResponse({"error": "不存在的品类"}, status_code=404)

    form = await request.form()
    from vision import generate_description

    updates = {}
    for field, val in form.items():
        if val:
            updates[field] = val

    artifact = update_artifact(category, artifact_id, updates)
    if not artifact:
        return JSONResponse({"error": "记录不存在"}, status_code=404)

    # 关键字段变化时重新生成简介
    trigger_fields = ["name", "chinese_name", "dynasty", "species", "habitat", "distribution"]
    if any(k in updates for k in trigger_fields):
        try:
            artifact["description"] = generate_description(artifact, category)
            update_artifact(category, artifact_id, {"description": artifact["description"]})
        except Exception:
            pass

    return JSONResponse({"ok": True, "artifact": artifact})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
