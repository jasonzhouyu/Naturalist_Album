"""把已入库的 artifact 用当前 vision.py 流水线重新跑一遍。

行为:
    1. 自动备份 metadata_*.json → metadata_*.bak.json
    2. 对每个 artifact 找源文件（source_path 或 album dir）
    3. 调用 recognize() + generate_description() 拿新结果
    4. 打印 OLD/NEW 对比 + 是否变化
    5. 写回 metadata_*.json

使用:
    python scripts/reprocess.py              # 处理全部品类
    python scripts/reprocess.py plant        # 只处理植物
    python scripts/reprocess.py plant animal # 多个品类
    python scripts/reprocess.py --dry-run    # 只打印不写

注意: 这会用真实 API 配额。8 张植物 ≈ 24 次 API 调用（iNat + Qwen-plus + 简介）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

# Windows 默认 GBK 控制台扛不住 unicode；强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 确保能 import 项目根目录的模块
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
os.chdir(str(PROJECT_DIR))

from utils import load_metadata, save_metadata, get_album_dir, get_metadata_file, CATEGORIES
from vision import recognize, generate_description


def find_source(art: dict, category: str) -> Path | None:
    """artifact 的源文件位置，优先 source_path（索引模式），回落到 album 目录。"""
    src = art.get("source_path")
    if src and Path(src).exists():
        return Path(src)
    album_path = get_album_dir(category) / art.get("filename", "")
    if album_path.exists():
        return album_path
    return None


def short(s: str | None, limit: int = 30) -> str:
    if not s:
        return "-"
    s = str(s)
    return s if len(s) <= limit else s[:limit - 1] + "…"


def reprocess_category(category: str, dry_run: bool = False) -> dict:
    data = load_metadata(category)
    artifacts = data["artifacts"]
    if not artifacts:
        print(f"[{category}] (empty)")
        return {"category": category, "total": 0, "changed": 0, "errors": 0, "skipped": 0}

    print(f"\n=== {category}: {len(artifacts)} artifacts ===")

    if not dry_run:
        meta_file = get_metadata_file(category)
        backup = meta_file.with_suffix(meta_file.suffix + ".bak")
        shutil.copy2(meta_file, backup)
        print(f"  [backup] {backup.name}")

    changed = errors = skipped = 0
    for i, art in enumerate(artifacts, 1):
        aid = art.get("id", "?")
        old_name = art.get("chinese_name") or art.get("name") or "?"
        old_sci = art.get("scientific_name") or ""

        src = find_source(art, category)
        if src is None:
            print(f"  {i:>2}. [skip] {aid} {short(old_name)} — file missing")
            skipped += 1
            continue

        t = time.time()
        try:
            new_info = recognize(str(src), category)
        except Exception as e:
            print(f"  {i:>2}. [err]  {aid} {short(old_name)} — recognize: {type(e).__name__}: {e}")
            errors += 1
            continue

        # 内部字段（_inat_score 等）不写入 artifact
        clean = {k: v for k, v in new_info.items() if not k.startswith("_")}

        try:
            clean["description"] = generate_description(clean, category)
        except Exception as e:
            print(f"  {i:>2}. [warn] {aid} description failed: {e}")
            clean["description"] = art.get("description", "")

        new_name = clean.get("chinese_name") or clean.get("name") or "?"
        new_sci = clean.get("scientific_name") or ""
        conf = clean.get("confidence", "?")
        delta = (old_name != new_name) or (old_sci != new_sci)

        marker = "*" if delta else " "
        debug_extra = ""
        if "_inat_score" in new_info:
            debug_extra += f" iNat={new_info['_inat_score']}"
        if "_plantnet_score" in new_info:
            debug_extra += f" PlantNet={new_info['_plantnet_score']}"
        if "_candidates" in new_info:
            debug_extra += f" cands={len(new_info['_candidates'])}"

        elapsed = time.time() - t
        print(f"  {i:>2}.{marker} {aid} ({elapsed:.1f}s, conf={conf}{debug_extra})")
        if delta:
            print(f"        OLD: {short(old_name, 24)} / {short(old_sci, 30)}")
            print(f"        NEW: {short(new_name, 24)} / {short(new_sci, 30)}")
        else:
            print(f"        SAME: {short(old_name, 24)} / {short(old_sci, 30)}")

        if delta:
            changed += 1

        # 更新 artifact in-place（保留 id, created_at, filename, source_path 等不会被识别覆盖的字段）
        for k, v in clean.items():
            art[k] = v

    if not dry_run:
        save_metadata(category, data)
        print(f"  [saved] {category}: {changed} changed, {errors} errors, {skipped} skipped")
    else:
        print(f"  [dry]  {category}: {changed} would change, {errors} errors, {skipped} skipped")

    return {"category": category, "total": len(artifacts), "changed": changed,
            "errors": errors, "skipped": skipped}


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    targets = args if args else CATEGORIES

    for c in targets:
        if c not in CATEGORIES:
            print(f"unknown category: {c}")
            sys.exit(1)

    print(f"reprocess: {targets} {'(dry-run)' if dry_run else ''}")
    summary = []
    for c in targets:
        summary.append(reprocess_category(c, dry_run=dry_run))

    print("\n=== SUMMARY ===")
    for s in summary:
        print(f"  {s['category']:>6}: {s['total']:>3} total, {s['changed']:>3} changed, "
              f"{s['errors']:>2} errors, {s['skipped']:>2} skipped")


if __name__ == "__main__":
    main()
