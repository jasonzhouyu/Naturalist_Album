# Naturalist Album · 自然观察相册

本地优先的自然观察照片管理工具。指向一个目录 → 浏览器选目录扫描 → AI 识别动物/植物/文物 → 自动生成中文简介、补全分类学、按学名规范化命名。RAW 文件原地索引，仅生成缩略图与元数据，**不复制原片**。

支持单机运行或部署到家庭 NAS Docker。

---

## 功能一览

| 模块 | 当前状态 |
|---|---|
| 批量导入 | 服务器端目录浏览器（支持 UNC / SMB），单次扫描 1751 张 RAW 不卡 |
| 缩略图 | 按需 512px JPEG 缓存到 `uploads/session_thumbs/`，RAW 直接抽嵌入 JPEG 不解 demosaic |
| 分页渲染 | 批量页 IntersectionObserver 增量渲染（首屏 200 张），相册页 60 张/批懒加载 |
| 识别 | 三品类各走不同路径（详见下文） |
| 归档 | 默认 **index-only**：原文件留在原位，元数据保存绝对路径 |
| 分享 | 单条记录生成只读链接 |
| 部署 | Windows 本地 / NAS Docker 双轨；`deploy_nas.py` 一键推送 |
| JWT 续约 | NAS 上独立 sidecar 容器跑 Playwright，每 24h 自动登录 iNat 拿新 token |

---

## 识别流水线

```
照片
  ├─ relic   → Qwen-VL-Max（直接结构化 JSON）
  │
  ├─ animal  → iNaturalist CV API
  │            ├─ combined_score ≥ 70  → iNat 结果 → Qwen-plus 补分类学/分布/栖息地
  │            ├─ 35 ≤ score < 70      → iNat top-3 作为提示给 Qwen-VL-Max
  │            └─ score < 35 / iNat 故障 → Qwen-VL-Max 兜底
  │
  └─ plant   → Pl@ntNet API (organs=auto, lang=zh)
               ├─ score ≥ 0.40 → Pl@ntNet 结果 → Qwen-plus 补分类学/分布/生境
               ├─ 0.10 ≤ score < 0.40 → Pl@ntNet top-3 作为提示给 Qwen-VL-Max
               └─ score < 0.10 / Pl@ntNet 故障 → Qwen-VL-Max 兜底
```

**为什么这样分**: Qwen-VL-Max 对中国本土物种缺乏地理上下文（容易把欧洲种张冠李戴到新疆样本上），但中文名和文物常识强；iNat 在动物分类上权威（鸟类、中大型哺乳类尤其），Pl@ntNet 对植物区分姐妹种最强；用前两者做硬识别、Qwen-plus 做"补全 + 不改写已知字段"，命中率显著提升。

实测：18 张新疆动物中 5 张被修正（红尾鵟→棕尾鵟、白肩雕→草原雕等）；7 张郁金香中 2 张被修正到分布更合理的种。

---

## 快速启动（Windows 本地）

```cmd
cd C:\Users\jason\Projects\relic-album
pip install -r requirements.txt
python main.py
```

→ 浏览器打开 http://localhost:8000

依赖：Python 3.12+，无需 venv。`fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `Pillow`, `rawpy`, `paramiko`（仅 NAS deploy 用）, `dashscope`。可选 `playwright`（仅 JWT 自动续约用）。

---

## API Key 配置

按品类需要的最小集：

| Key | 用途 | 取得 | 不配会怎样 |
|---|---|---|---|
| `DASHSCOPE_API_KEY` | Qwen-VL-Max + Qwen-plus | https://bailian.console.aliyun.com/ | 完全无法识别 |
| `PLANTNET_API_KEY` | 植物识别主路径 | https://my.plantnet.org/account/settings → API | 植物降级走 Qwen-VL-Max |
| `INATURALIST_USERNAME` + `INATURALIST_PASSWORD` | 动物识别（自动续 JWT） | https://www.inaturalist.org/signup | 动物降级走 Qwen-VL-Max |

写入 `Y:\Openclaw\workspace\.env`（多项目共享）或项目根 `.env`：

```bash
DASHSCOPE_API_KEY=sk-...
PLANTNET_API_KEY=2b10...
INATURALIST_USERNAME=your_inat_login
INATURALIST_PASSWORD=your_inat_password
INATURALIST_JWT=                # 由 refresh_inat_jwt.py 自动写入
```

`secrets_loader.py` 会自动按优先级查找；环境变量 > `.env` 文件。

iNat 24 小时 JWT 由 `scripts/refresh_inat_jwt.py` 用 Playwright 无头登录自动续。本地可手动跑或挂 Windows 计划任务，NAS 上有 sidecar 容器自动跑。

---

## NAS Docker 部署

```cmd
python deploy_nas.py
```

这会：
1. 把当前代码 tar.gz 推到 NAS via SSH
2. 在 NAS 上构建主镜像 `nature-album`
3. 拉取 `mcr.microsoft.com/playwright/python:v1.59.0-noble`（首次 ~800MB）
4. 启动两个容器:
   - **nature-album** (port 8000)
   - **inat-jwt-refresher** (sidecar, network_mode: host, 每 24h 自动续 JWT)
5. 自动同步 `Y:\Openclaw\workspace\.env` 中的 PLANTNET_API_KEY / 凭证 到 NAS 对应位置

NAS 路径 `/home/pcwork/nature-album/keys/` 下的文件跨 redeploy 持久（包含 cookie 缓存、Playwright 状态、JWT 输出）。

访问 http://192.168.31.233:8000

---

## 主要工作流

### 批量导入（Index-only 模式，默认）

1. `/batch` → 服务器端目录浏览器，可点击驱动器或 UNC `\\DX4600-HOMENAS\...` 进入
2. 选定目录 → "扫描目录" → 创建 session 列出所有图片（不复制）
3. `/batch/{session_id}` → 给每张照片打类（文物/动物/植物/跳过）+ 可选地点
4. "处理全部" → 对已标记照片调用 `process_photo()`：缩略图生成 + 识别 + 简介 + 归档
5. 原文件留在原位，artifact 元数据中存 `source_path`

### 单张上传

`/upload/{category}` → 表单上传 → 即时识别 → 入库

### 浏览

- `/{category}` 单品类相册（懒加载分页）
- `/album` 跨品类搜索（关键字模糊匹配所有字段）
- `/{category}/{artifact_id}` 详情页（可编辑、删除、生成分享链接）
- `/share/{share_id}` 只读分享视图

---

## 关键脚本

| 脚本 | 作用 |
|---|---|
| `scripts/refresh_inat_jwt.py` | Playwright 登录 iNat，写 JWT 到 `.env` 或 `--output-file` |
| `scripts/reprocess.py [category]` | 用当前 vision.py 流水线重跑已入库的 artifacts，备份 .bak.json，打印 OLD/NEW 差异 |
| `deploy_nas.py` | 推送代码到 NAS、构建 Docker、起容器 |

---

## 项目结构

```
main.py                  FastAPI 路由（按 CLAUDE.md 中的顺序约束注册）
processor.py             单张照片处理：RAW 抽预览 → 缓存 → 识别 → 简介 → 命名 → 归档
vision.py                识别路由器：按 category 分发到 inat/plantnet/qwen-vl
inat.py                  iNat CV API 客户端 + 结果 → schema 解析
plantnet.py              Pl@ntNet API 客户端 + 结果 → schema 解析
secrets_loader.py        env 变量 + .env 多源加载，特别处理 INAT_JWT_FILE
thumb_cache.py           批量页缩略图按需生成 + 磁盘缓存
session_manager.py       批量会话状态: per-session JSON 文件 + 内存缓存
share_manager.py         分享链接 (shares.json)
settings_manager.py      存储路径配置 (settings.json)
cache_manager.py         LLM 识别结果缓存（SHA256 文件 hash × category）
utils.py                 元数据 CRUD、文件命名、缩略图生成
log_setup.py             stdout/stderr 自动 tee 到 relic-album.log
deploy_nas.py            paramiko-based 部署器
templates/               Jinja2 模板（自定义 CSS，无框架）
static/style.css         Apple-inspired 设计系统
scripts/                 一次性运维脚本
```

### 路由顺序（关键）

FastAPI 按注册顺序匹配。具体路径**必须**在通配 `/{category}` 和 `/{category}/{artifact_id}` 之前注册，否则被拦截。详见 `CLAUDE.md`。

---

## 性能优化要点

| 维度 | 做法 |
|---|---|
| 目录浏览（NAS UNC） | `os.scandir()` 取代 `Path.iterdir()`，单条目零 stat 调用；500 子目录上限、1000 图片上限早退 |
| 批量页 1000+ 缩略图 | IntersectionObserver 分页（200/批），按需生成 + HTTP 缓存 1 天 |
| RAW 缩略图 | `rawpy.extract_thumb()` 优先取嵌入 JPEG（毫秒级），失败才 demosaic |
| Session JSON | 每会话独立文件 `batch_sessions/{id}.json` + 内存 LRU 缓存，避免每次请求全量读盘 |
| 相册页 | 同样的 60/批懒加载 |
| 识别 API 调用 | LLM 缓存按文件 hash×category，重复识别零 API |

服务端日志全程落盘 `relic-album.log`（带毫秒时间戳）；浏览器 console 也同步打印 `[browse-dir]`、`[batch-preview]` 等关键事件。

---

## 已知问题 / TODO

- 多次重跑可能因为 iNat / Pl@ntNet 偶发网络抖动导致部分 artifact 走 Qwen-VL 兜底，结果会有差异
- Pl@ntNet 的 commonNames 里偶有错别字（e.g. "川赤苟"），未自动校正
- 批量页处理是同步的，UI 没实时进度——拟接 SSE
- 详情页缺"在外部应用打开（Lightroom）"按钮，拟加
- 暂无图片放大灯箱（PhotoSwipe v5 待接入）
- 暂无相册批量删除/重新打类的入口

---

## 许可

MIT
