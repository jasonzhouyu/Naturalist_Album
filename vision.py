import os
import json
import base64
import urllib.request
import urllib.error

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
RECOGNITION_MODEL = "qwen-vl-max"
TEXT_MODEL = "qwen-plus"


def _get_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if key:
        return key
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


def recognize(filename: str, category: str) -> dict:
    """识别图片中的物体，返回结构化 JSON。category 为 relic/animal/plant。"""
    img_url = _image_to_base64(filename)
    prompt = RECOGNITION_PROMPTS[category]
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": img_url}},
            {"type": "text", "text": prompt},
        ]
    }]
    raw = _call_dashscope(messages, RECOGNITION_MODEL, temperature=0.1)
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
    return json.loads(raw)


def generate_description(info: dict, category: str) -> str:
    """生成简介。info 包含识别结果的所有字段。"""
    template = INTRODUCTION_PROMPTS[category]
    prompt = template.format(**info)
    messages = [{"role": "user", "content": prompt}]
    return _call_dashscope(messages, TEXT_MODEL, temperature=0.7)
