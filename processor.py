import os
import shutil
from pathlib import Path

from utils import (
    is_raw, is_image, generate_filename, create_thumbnail,
    add_artifact, get_album_dir, make_relative_source,
)
from vision import recognize, generate_description
from cache_manager import check_cache, put_cache


def extract_raw_preview(raw_path: str) -> str | None:
    try:
        import rawpy
        with rawpy.imread(raw_path) as raw:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                jpg_path = raw_path.rsplit(".", 1)[0] + "_preview.jpg"
                with open(jpg_path, "wb") as f:
                    f.write(thumb.data)
                return jpg_path
    except Exception:
        pass

    try:
        import rawpy
        import imageio
        with rawpy.imread(raw_path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, half_size=True)
        jpg_path = raw_path.rsplit(".", 1)[0] + "_preview.jpg"
        imageio.imsave(jpg_path, rgb, quality=85)
        return jpg_path
    except Exception:
        return None


def process_photo(file_path: str, category: str, location: str = "", index_only: bool = False) -> dict:
    """处理单张照片：RAW提取 → 缓存检查 → 识别 → 简介 → 命名 → 归档"""
    filename = os.path.basename(file_path)
    original_filename = filename
    ext = Path(filename).suffix.lower()

    # Step 1: RAW 提取预览
    working_path = file_path
    if is_raw(filename):
        preview = extract_raw_preview(file_path)
        if preview is None:
            return {"error": f"无法解析 RAW 文件: {filename}"}
        working_path = preview
        ext = ".jpg"  # RAW 提取的预览始终是 JPEG

    if not is_image(Path(working_path).name) and not is_raw(filename):
        if not is_image(filename):
            return {"error": f"不支持的文件格式: {ext}"}

    # Step 2: 检查缓存或调用千问 VL 识别
    cached = check_cache(working_path, category)
    if cached:
        info = cached["recognition"]
        description = cached["description"]
    else:
        try:
            info = recognize(working_path, category, location=location)
        except Exception as e:
            return {"error": f"识别失败: {str(e)}"}

        # 检查是否未识别
        name_key = "name" if category == "relic" else "chinese_name"
        if info.get(name_key) == "未识别":
            return {"error": f"未能识别图片中的{category}，请尝试其他照片"}

        # Step 3: 生成简介
        try:
            description = generate_description(info, category)
        except Exception as e:
            description = f"简介生成失败: {str(e)}"

        # 写入缓存
        try:
            put_cache(working_path, category, info, description)
        except Exception:
            pass

    # Step 4: 归档文件（index_only 模式下跳过复制，仅记录原始路径）
    new_filename = generate_filename(category, info, ext, location=location)
    if not index_only:
        album_dir = get_album_dir(category)
        dest = album_dir / new_filename
        shutil.copy2(working_path, dest)

    # Step 5: 缩略图
    create_thumbnail(working_path, category, new_filename)

    # Step 6: 写入 metadata
    artifact_fields = {
        **info,
        "description": description,
        "distribution_geo": None,
        "map_source": None,
        "filename": new_filename,
        "original_filename": original_filename,
        "size": os.path.getsize(file_path),
        "location": location,
    }
    if index_only:
        artifact_fields["source_path"] = make_relative_source(os.path.abspath(file_path))
    artifact = add_artifact(category, artifact_fields)

    return artifact
