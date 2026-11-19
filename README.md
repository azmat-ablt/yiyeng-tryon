# 衣影 YIYING · 虚拟试衣间

上传一张全身照 + 一件衣服，约 30 秒生成上身 / 下装 / 全身的试穿效果。**全本地推理，人像不出本机。**

基于 [CatVTON](https://github.com/Zheng-Chong/CatVTON) 的扩散式虚拟试衣方案，配套完整的三层工程实现：Web 前端、业务 API、GPU 推理服务，以及衣橱与试衣档案功能。

---

## 功能

- **虚拟试衣** — 人像 + 衣物 → 合成结果，支持上衣 / 下装 / 全身三种类型
- **前后对比** — 结果画布可拖动分割线对比原图与效果图
- **衣橱** — 保存自有单品，随时选用；支持添加、删除（同步删除磁盘原图）
- **档案** — 试穿结果自动归档，可回看、可删除（同步删除成图文件）
- **状态反馈** — 后端探活状态灯、合成耗时、任务编号、失败原因
- **快捷键** — `Enter` 开始试穿、`R` 重置、`1–3` 快速切换单品

## 架构

```
┌──────────────┐   HTTP    ┌──────────────────┐   HTTP    ┌────────────────────┐
│  web  3000   │ ────────▶ │  server  8000    │ ────────▶ │  inference  9000   │
│  Next.js 14  │ ◀──────── │  FastAPI 业务层   │ ◀──────── │  FastAPI + CatVTON │
└──────────────┘  轮询任务  └──────────────────┘   PNG     └────────────────────┘
                              │ 落盘 data/uploads
                              │ 成图 data/results
                              ▼
                        data/library.json
                       （衣橱 / 档案索引）
```

**数据流**：上传人像 → 上传衣物 → 提交任务（返回 `202`）→ 后台协程调 9000 推理 → 前端每 1.5s 轮询任务状态 → 拿到结果 URL → 自动归档。

一次推理约 30 秒，所以任务必须异步化，不能同步等待。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 14.2 · React 18.3 · TypeScript 5.6 · 原生 CSS（CSS 变量做设计令牌） |
| 业务 API | FastAPI 0.115 · Uvicorn · Pydantic v2 · httpx（异步转发）· asyncio 任务队列 |
| 推理 | PyTorch 2.7 · diffusers 0.29 · transformers 4.44 · CatVTON · SCHP · OpenCV |
| 存储 | 本地磁盘 + JSON 索引；`/files` 静态挂载 |

## 目录结构

```
.
├── web/                      # Next.js 前端（3000）
│   ├── app/page.tsx          # 工作室 / 衣橱 / 档案 三视图
│   ├── app/globals.css       # 设计令牌与全部样式
│   └── lib/api.ts            # 后端接口封装
├── server/                   # 业务 API（8000）
│   ├── app/api/routes.py     # 路由
│   ├── app/jobs.py           # 进程内任务队列
│   ├── app/library.py        # 衣橱 / 档案 JSON 索引
│   ├── app/storage.py        # 本地存储与按 URL 删除
│   └── app/inference/        # 推理 Provider 抽象（stub / local / remote）
├── inference/                # 推理服务（9000）
│   ├── service.py            # FastAPI 入口
│   ├── catvton_runner.py     # 模型加载、推理与后处理
│   └── masker.py             # SCHP 人体解析与掩码构建
├── 启动衣影.bat              # 一键启动三个服务（Windows）
├── 关闭衣影.bat
└── start-api.bat             # 只重启业务 API
```

## 快速开始

### 0. 环境要求

- Python 3.12、Node.js 18+
- NVIDIA GPU（本项目在 RTX 5060 Laptop 8GB 上验证，输出 768×1024）
- Windows（`.bat` 脚本）或手动分别启动三个服务

### 1. 获取第三方代码与模型权重（不入库，需自行下载）

```bash
# CatVTON 上游代码
git clone https://github.com/Zheng-Chong/CatVTON.git inference/vendor/CatVTON-main
```

模型权重需放置到以下位置（体积约 2.6 GB，参考 CatVTON 官方 HuggingFace 权重包与
`runwayml/stable-diffusion-inpainting`）：

```
inference/models/
├── base-inpainting/            # SD Inpainting 的 unet + scheduler
├── vae/                        # VAE
└── catvton/
    ├── mix-48k-1024/attention/model.safetensors   # CatVTON 注意力权重
    └── SCHP/                   # 人体解析：LIP 与 ATR 两套
        ├── exp-schp-201908261155-lip.pth
        └── exp-schp-201908301523-atr.pth
```

### 2. 安装依赖

```bash
# 业务 API
cd server && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
cp .env.example .env          # 按需修改端口与地址

# 推理服务
cd ../inference && python -m venv .venv && .venv/Scripts/pip install -r requirements-catvton.txt

# 前端
cd ../web && npm install
```

### 3. 启动

```bash
# 方式一：Windows 一键启动（三个独立窗口）
启动衣影.bat

# 方式二：手动分别启动
cd inference && .venv/Scripts/python -m uvicorn service:app --host 127.0.0.1 --port 9000
cd server    && .venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd web       && npm run dev
```

打开 <http://localhost:3000>。首次启动推理服务需要加载模型，请等待
`GET /health` 返回 `{"ready": true, "device": "cuda"}`。

### 4. 没有 GPU 也能跑（stub 模式）

只想看界面和交互、不想下载 2.6 GB 权重的，可以跳过第 1 步，并让业务层使用占位推理：

```bash
# server/.env
VTON_INFERENCE_PROVIDER=stub
```

此时不需要启动 `inference` 服务，`server` + `web` 两个进程即可。上传、建任务、轮询、
衣橱、档案、前后对比的完整流程都能走通，只是任务返回的是原图而不是合成结果
（`stub` 的实现见 `server/app/inference/stub.py`，只有几行）。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务健康检查 |
| POST | `/api/photos` | 上传人像（multipart `file`） |
| POST | `/api/garments` | 上传衣物；`save=true` 时入库衣橱 |
| GET / DELETE | `/api/garments` · `/api/garments/{id}` | 衣橱列表 / 删除（同时删原图） |
| POST | `/api/tryon` | 创建任务 `{person_id, garment_id, cloth_type}` → `202` |
| GET | `/api/jobs/{id}` | 查询任务 `queued / running / succeeded / failed` |
| GET / POST / DELETE | `/api/archive` · `/api/archive/{id}` | 档案列表 / 存档 / 删除（同时删成图） |

限制：仅 JPEG / PNG / WebP，单张 ≤ 10 MB。

## 实现要点

- **异步任务队列** — `asyncio.create_task` + 前端轮询；接口对上层是「提交即返回」。量大时可换 Redis + Celery，接口保持不变。
- **Provider 抽象** — `TryOnProvider` 接口下挂 `stub`（占位）/ `local`（本地 GPU）/ `remote`（第三方 API），改 `.env` 一行即可切换。
- **掩码不是矩形** — LIP 与 ATR 两套解析结果取并集，再用凸包补洞；手部单独做肤色检测保护，避免手被"融进"衣服。
- **后处理** — 在 LAB 色彩空间对齐原图光照，仅对掩码区域混合，让合成结果贴合原背景；头发做 alpha 还原。
- **精度取舍** — `bfloat16` 混合精度 + 20 步采样，显存减半、速度提升一倍多，肉眼几乎无差异。
- **删除是真删除** — 删记录的同时反解 URL 并 `unlink` 磁盘文件，避免"前端看不见但磁盘一直涨"。
- **索引持久化** — `library.json` 落盘，重启后衣橱中的单品仍可正常参与推理。

## 已知限制

- 单机单卡，推理用 `threading.Lock` 串行，**不支持并发多用户**
- 任务队列在进程内存中，**服务重启后运行中的任务会丢失**
- 衣橱记录的类型默认记为「上衣」，修改只作用于本次试穿
- 删除为物理删除，不可恢复（前端做了两步确认）

## 许可与致谢

本项目为课程作业。虚拟试衣能力基于 [CatVTON](https://github.com/Zheng-Chong/CatVTON)
及其上游依赖（Stable Diffusion Inpainting、Self-Correction-Human-Parsing），
相关代码与模型权重的版权归原作者所有，使用前请遵守上游仓库的许可协议。
