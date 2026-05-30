"""为所有缺失 JPG 缩略图的 artifact 从源文件生成缩略图。"""
import json, os, sys, io
from pathlib import Path

BASE = Path(r'C:\Users\jason\Projects\relic-album')
THUMBS = BASE / 'thumbs'
PHOTOS_ROOT = r'\\DX4600-HOMENAS\personal_folder\Photos'
CATEGORIES = ['relic', 'animal', 'plant']

try:
    from PIL import Image
    import rawpy
except ImportError as e:
    print(f'缺少依赖: {e}')
    sys.exit(1)

def extract_preview(raw_path):
    try:
        with rawpy.imread(str(raw_path)) as raw:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                return Image.open(io.BytesIO(thumb.data))
            elif thumb.format == rawpy.ThumbFormat.BITMAP:
                return Image.fromarray(thumb.data)
    except Exception as e:
        print(f'  rawpy 失败: {e}')
    return None

fixed = 0
for cat in CATEGORIES:
    meta = BASE / f'metadata_{cat}.json'
    if not meta.exists():
        continue
    data = json.loads(meta.read_text(encoding='utf-8'))
    thumb_dir = THUMBS / cat
    thumb_dir.mkdir(parents=True, exist_ok=True)

    for a in data['artifacts']:
        fn = a.get('filename', '')
        stem = Path(fn).stem
        jpg = thumb_dir / f'{stem}.jpg'

        if jpg.exists() and jpg.stat().st_size > 1000:
            continue

        sp = a.get('source_path', '')
        print(f'[{cat}] 缺失: {stem}.jpg', end='')

        if not sp:
            print(' (无 source_path)')
            continue

        # 构建完整路径
        if os.path.isabs(sp):
            src = Path(sp)
        else:
            src = Path(PHOTOS_ROOT) / sp.replace('/', '\\')

        if not src.exists():
            print(f' 源文件不存在: {src}')
            continue

        print(f' ← {src.name}', end='')

        # 从 RAW 提取或直接打开
        if src.suffix.lower() in ['.cr3', '.cr2', '.nef', '.arw', '.dng', '.orf', '.rw2']:
            img = extract_preview(src)
        else:
            img = Image.open(src)

        if img is None:
            print(' 无法提取')
            continue

        img.thumbnail((400, 400))
        img.save(str(jpg), 'JPEG', quality=85)
        sz = jpg.stat().st_size
        print(f' ✅ {sz//1024}KB')
        fixed += 1

print(f'\n完成! 修复了 {fixed} 个缩略图')
