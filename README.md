# Naturalist Album — 自然观察相册

一个轻量级的本地 Web 应用，帮助自然爱好者和文博爱好者管理观察记录。

上传照片 → AI 自动识别 → 生成简介 → 归档重命名。

## 支持品类

| 品类 | 识别内容 | 文件命名 |
|------|---------|---------|
| 文物 | 名称、朝代、公元纪年、材质、类别、博物馆、发现地址 | `文物名_朝代_编号` |
| 动物 | 界门纲目科属种、学名、分布区域、栖息环境 | `中文名_种名_编号` |
| 植物 | 界门纲目科属种、学名、分布区域、生长环境 | `中文名_种名_编号` |

## 技术栈

- **后端**: Python FastAPI
- **前端**: Jinja2 + Pico.css + 原生 JS
- **AI**: 阿里云百炼 DashScope (Qwen-VL-Max + Qwen-Plus)
- **RAW**: rawpy (支持佳能 .CR2/.CR3)

## 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 设置 API Key (二选一)
export DASHSCOPE_API_KEY=your_key
# 或写入 ~/.claude/settings.json 的 env 块

# 启动
python main.py
# 浏览器打开 http://localhost:8000
```

## Docker 部署

```bash
echo "DASHSCOPE_API_KEY=your_key" > .env
docker compose up -d
# 访问 http://localhost:8000
```

## 项目结构

```
├── main.py              # FastAPI 路由
├── processor.py         # 识别管道 (RAW→识别→简介→归档)
├── vision.py            # DashScope API (Qwen-VL + Qwen)
├── utils.py             # 文件/元数据管理
├── templates/           # Jinja2 页面
├── static/              # CSS/JS
├── album/               # 归档照片
├── thumbs/              # 缩略图
└── metadata_*.json      # 元数据
```

## 许可

MIT
