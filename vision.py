"""识别路由器。

按品类分发:
    relic   → Qwen-VL-Max (与之前一致)
    animal  → iNat CV 主路径，低置信度兜底 Qwen-VL-Max；分类学缺字段由 Qwen-plus 补全
    plant   → Pl@ntNet 主路径，同样的兜底 + 补全模式

对外接口保持 recognize(filename, category) / generate_description(info, category)。
"""
from __future__ import annotations

import io
import json
import os
import base64
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

from secrets_loader import get_secret

RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2"}
PREPROCESS_MAX_DIM = 2048   # iNat / Pl@ntNet 都有 ~5MB 上限，2048px JPEG 远低于

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
RECOGNITION_MODEL = "qwen-vl-max"
TEXT_MODEL = "qwen-plus"


def _get_api_key() -> str:
    key = get_secret("DASHSCOPE_API_KEY")
    if key:
        return key
    # Windows 本地: 兜底 Claude Code settings.json
    settings_path = os.path.expandvars(r"%USERPROFILE%\.claude\settings.json")
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            settings = json.load(f)
        return settings.get("env", {}).get("DASHSCOPE_API_KEY", "")
    return ""


def _call_dashscope(messages: list, model: str, temperature: float = 0.3) -> str:
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }).encode()
    req = urllib.request.Request(
        DASHSCOPE_URL, data=body,
        headers={
            "Authorization": f"Bearer {_get_api_key()}",
            "Content-Type": "application/json",
        }
    )
    resp = urllib.request.urlopen(req, timeout=90)
    data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def _image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    ext = os.path.splitext(image_path)[1].lower().replace(".", "")
    mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp"}
    mime = mime_map.get(ext, "image/jpeg")
    return f"data:{mime};base64,{img_b64}"


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
    return raw.strip()


# === 品类 Prompt 配置 ===

RECOGNITION_PROMPTS = {
    "relic": """你是一个文物鉴定专家。请识别这张照片中的文物，严格按以下JSON格式输出，不要输出任何JSON以外的内容：

{
  "name": "文物名称",
  "dynasty": "具体朝代/年代",
  "dynasty_period": "所属大朝代及其时间范围，例如'清朝 (1644-1912)'",
  "gregorian_years": "该文物的公元纪年区间，例如'1736-1795'",
  "material": "材质",
  "category": "类别（青铜器、瓷器、书画、玉器、金银器、陶器、石刻、漆器等）",
  "museum": "当前收藏博物馆（可辨识时填写）",
  "discovery_place": "发现/出土地地址",
  "confidence": "高/中/低"
}

注意事项：
- dynasty_period 填大朝代范围，gregorian_years 填该文物的具体年代区间
- discovery_place 尽可能具体（省/市/遗址名）
- 如果某个字段无法确定，填 "未知"
- 如果完全无法识别这不是文物，name 填 "未识别"
- 只输出 JSON，不要有任何其他文字""",

    "animal": """你是一个动物学家。请识别这张照片中的动物，严格按以下JSON格式输出，不要输出任何JSON以外的内容：

{
  "chinese_name": "中文名称",
  "scientific_name": "学名（拉丁名）",
  "kingdom": "界",
  "phylum": "门",
  "class": "纲",
  "order": "目",
  "family": "科",
  "genus": "属",
  "species": "种",
  "distribution": "分布区域描述（具体到国家和地理区域）",
  "habitat": "栖息环境",
  "confidence": "高/中/低"
}

注意事项：
- scientific_name 用标准的拉丁学名
- 界门纲目科属种逐级完整填写，如果某一级不确定填"未知"
- distribution 尽可能具体，如"分布于中国西南部、东南亚热带地区"
- 如果完全无法识别这不是动物，chinese_name 填 "未识别"
- 只输出 JSON，不要有任何其他文字""",

    "plant": """你是一个植物学家。请识别这张照片中的植物，严格按以下JSON格式输出，不要输出任何JSON以外的内容：

{
  "chinese_name": "中文名称",
  "scientific_name": "学名（拉丁名）",
  "kingdom": "界",
  "phylum": "门",
  "class": "纲",
  "order": "目",
  "family": "科",
  "genus": "属",
  "species": "种",
  "distribution": "分布区域描述（具体到国家和地理区域）",
  "habitat": "生长环境",
  "confidence": "高/中/低"
}

注意事项：
- scientific_name 用标准的拉丁学名
- 界门纲目科属种逐级完整填写，如果某一级不确定填"未知"
- distribution 尽可能具体，如"分布于中国长江以南、日本、韩国"
- 如果完全无法识别这不是植物，chinese_name 填 "未识别"
- 只输出 JSON，不要有任何其他文字""",
}


HINTED_PROMPT_TEMPLATE = """{base}

【重要提示】其他识别系统给了候选物种，请结合图片辨别哪一个是对的（如果都不对，按你独立的判断填写）：
{candidates}
"""


COMPLETION_PROMPT = """根据以下已知字段补全空缺的物种信息，严格按 JSON 输出：

已知字段:
{known}

补全规则:
- 不要修改已经填写的字段（视它们为权威）
- 空字符串字段需要你补全
- 学名层级（kingdom/phylum/class/order/family/genus/species）按权威分类学填写，不确定填"未知"
- distribution: 具体到国家和地理区域，例如"分布于中国西南部、东南亚热带地区"
- habitat: 栖息环境（动物）/ 生长环境（植物），1-2 句话
- chinese_name 若空缺，根据 scientific_name 填中文常用名
- 输出完整 JSON（包含已知 + 补全字段），不要有 JSON 以外的文字
- 若需要，confidence 字段保留输入的值"""


INTRODUCTION_PROMPTS = {
    "relic": """你是一个博物馆讲解员。请为以下文物撰写一段200-300字的中文简介，
要求通俗易懂、信息丰富，适合普通观展者阅读。

文物信息：
- 名称：{name}
- 朝代：{dynasty}
- 朝代时间：{dynasty_period}
- 公元纪年：{gregorian_years}
- 材质：{material}
- 类别：{category}
- 博物馆：{museum}
- 发现地址：{discovery_place}

简介内容应包括：文物的历史背景、工艺特点、文化意义、以及出土地点相关的考古信息（如有）。
请直接输出简介内容，不要输出标题或前缀。""",

    "animal": """你是一个动物学家和科普作家。请为以下动物撰写一段200-300字的中文简介，
要求通俗易懂、适合自然爱好者阅读。

动物信息：
- 中文名：{chinese_name}
- 学名：{scientific_name}
- 界：{kingdom} 门：{phylum} 纲：{class}
- 目：{order} 科：{family}
- 属：{genus} 种：{species}
- 分布：{distribution}
- 栖息环境：{habitat}

简介内容应包括：该动物的分类地位、形态特征、生活习性、分布特点、保护现状等。
请直接输出简介内容，不要输出标题或前缀。""",

    "plant": """你是一个植物学家和科普作家。请为以下植物撰写一段200-300字的中文简介，
要求通俗易懂、适合自然爱好者阅读。

植物信息：
- 中文名：{chinese_name}
- 学名：{scientific_name}
- 界：{kingdom} 门：{phylum} 纲：{class}
- 目：{order} 科：{family}
- 属：{genus} 种：{species}
- 分布：{distribution}
- 生长环境：{habitat}

简介内容应包括：该植物的分类地位、形态特征、生态习性、分布特点、经济或观赏价值等。
请直接输出简介内容，不要输出标题或前缀。""",
}


# === 公共接口 ===

def recognize(filename: str, category: str) -> dict:
    """主识别入口。返回与 RECOGNITION_PROMPTS 模板一致的 schema dict。

    自动处理 RAW: 先抽嵌入 JPEG 缩到 2048px 给下游 API（Pl@ntNet/iNat 不收 RAW）。
    """
    working_path = filename
    tmp_to_cleanup: str | None = None
    if Path(filename).suffix.lower() in RAW_EXTS:
        tmp_to_cleanup = _raw_to_jpeg_tmp(filename)
        if tmp_to_cleanup is None:
            raise RuntimeError(f"无法从 RAW 抽嵌入 JPEG: {filename}")
        working_path = tmp_to_cleanup

    try:
        if category == "animal":
            return _recognize_animal(working_path)
        if category == "plant":
            return _recognize_plant(working_path)
        return _recognize_with_qwen_vl(working_path, category)
    finally:
        if tmp_to_cleanup:
            try:
                os.unlink(tmp_to_cleanup)
            except OSError:
                pass


def _raw_to_jpeg_tmp(raw_path: str) -> str | None:
    """RAW → 临时 JPEG（先抽嵌入预览，再用 PIL 缩到 2048px）。失败返回 None。"""
    try:
        import rawpy
        from PIL import Image
    except ImportError as e:
        print(f"[vision] RAW dependency missing: {e}")
        return None
    try:
        with rawpy.imread(raw_path) as raw:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                img = Image.open(io.BytesIO(thumb.data))
            elif thumb.format == rawpy.ThumbFormat.BITMAP:
                img = Image.fromarray(thumb.data)
            else:
                return None
    except Exception as e:
        print(f"[vision] RAW extract_thumb failed: {e}")
        return None

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max(img.size) > PREPROCESS_MAX_DIM:
        img.thumbnail((PREPROCESS_MAX_DIM, PREPROCESS_MAX_DIM), Image.Resampling.LANCZOS)
    fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="recog_")
    os.close(fd)
    try:
        img.save(tmp, "JPEG", quality=88, optimize=True)
        return tmp
    except Exception as e:
        print(f"[vision] save tmp jpeg failed: {e}")
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return None


def generate_description(info: dict, category: str) -> str:
    template = INTRODUCTION_PROMPTS[category]
    safe = {k: (v if v not in (None, "") else "未知") for k, v in info.items()}
    prompt = template.format(**{k: safe.get(k, "未知") for k in _placeholder_names(template)})
    messages = [{"role": "user", "content": prompt}]
    return _call_dashscope(messages, TEXT_MODEL, temperature=0.7)


def _placeholder_names(template: str) -> list[str]:
    import string
    return [fname for _, fname, _, _ in string.Formatter().parse(template) if fname]


# === 动物路径 ===

def _recognize_animal(filename: str) -> dict:
    import inat
    try:
        partial = inat.recognize_animal(filename)
    except inat.InatLowConfidence as e:
        # 低置信度: 把候选作为 hint 给 Qwen-VL
        return _recognize_with_qwen_vl(filename, "animal", candidates=e.candidates)
    except inat.InatError as e:
        print(f"[vision] iNat unavailable, falling back to Qwen-VL: {e}")
        return _recognize_with_qwen_vl(filename, "animal")

    return _complete_with_qwen_plus(partial, category="animal")


# === 植物路径 ===

def _recognize_plant(filename: str) -> dict:
    import plantnet
    try:
        partial = plantnet.recognize_plant(filename)
    except plantnet.PlantnetLowConfidence as e:
        return _recognize_with_qwen_vl(filename, "plant", candidates=e.candidates)
    except plantnet.PlantnetError as e:
        print(f"[vision] Pl@ntNet unavailable, falling back to Qwen-VL: {e}")
        return _recognize_with_qwen_vl(filename, "plant")

    return _complete_with_qwen_plus(partial, category="plant")


# === Qwen-VL 主流程（文物/兜底） ===

def _recognize_with_qwen_vl(filename: str, category: str, candidates: list[dict] | None = None) -> dict:
    img_url = _image_to_base64(filename)
    base_prompt = RECOGNITION_PROMPTS[category]
    if candidates:
        formatted = _format_candidates(candidates)
        prompt = HINTED_PROMPT_TEMPLATE.format(base=base_prompt, candidates=formatted)
    else:
        prompt = base_prompt

    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": img_url}},
            {"type": "text", "text": prompt},
        ]
    }]
    raw = _call_dashscope(messages, RECOGNITION_MODEL, temperature=0.1)
    return json.loads(_strip_code_fences(raw))


def _format_candidates(candidates: list[dict]) -> str:
    lines = []
    for i, c in enumerate(candidates, 1):
        sci = c.get("scientific_name", "")
        common = c.get("common_name") or (c.get("common_names") or [""])[0]
        score = c.get("score", "")
        lines.append(f"{i}. {sci}（{common}）— 置信度 {score}")
    return "\n".join(lines) if lines else "(无候选)"


# === Qwen-plus 补全分类学和描述 ===

def _complete_with_qwen_plus(partial: dict, category: str) -> dict:
    # 把内部字段（_inat_score 等）剔除，只把面向 schema 的传给模型
    clean = {k: v for k, v in partial.items() if not k.startswith("_")}
    prompt = COMPLETION_PROMPT.format(known=json.dumps(clean, ensure_ascii=False, indent=2))
    messages = [{"role": "user", "content": prompt}]
    try:
        raw = _call_dashscope(messages, TEXT_MODEL, temperature=0.2)
        completed = json.loads(_strip_code_fences(raw))
    except Exception as e:
        print(f"[vision] taxonomy completion failed, returning iNat/PlantNet partial: {e}")
        completed = clean
        # 把空字段填 "未知" 避免下游模板报错
        for k in ["chinese_name", "scientific_name", "kingdom", "phylum", "class",
                  "order", "family", "genus", "species", "distribution", "habitat"]:
            if not completed.get(k):
                completed[k] = "未知"
        if not completed.get("confidence"):
            completed["confidence"] = "中"

    # 保留权威字段（如学名）不被改写
    for k in ["scientific_name", "kingdom"]:
        if clean.get(k):
            completed[k] = clean[k]
    return completed
