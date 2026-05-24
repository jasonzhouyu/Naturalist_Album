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


# === 上传页 ===

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


# === JSON API ===

@app.get("/api/{category}")
async def api_artifacts(category: str):
    if not validate_category(category):
        return JSONResponse({"error": "不存在的品类"}, status_code=404)
    data = load_metadata(category)
    return JSONResponse(data["artifacts"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
