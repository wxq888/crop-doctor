# 作物医生 CropDoctor

> 基于 YOLO11s 与 RAG 的农作物病害智能检测与问诊平台（毕业设计）

## 项目简介

面向智慧农业场景，构建「**视觉诊断 → 风险预警 → 知识问诊 → 答疑闭环**」的一体化平台。**双端角色严格分工**：H5 用户端面向普通用户（纯功能使用），PC 管理端面向管理员（管用户 / 盯数据 / 答疑惑）：

1. **智能检测（H5 主线）**：自训练 YOLO11s 检测模型，覆盖 PlantVillage 38 个作物病害/健康类别，支持**图片 / 摄像头实时**（WebSocket 抓帧画框）两种检测方式；检测后自动进行**严重度分级**（规则引擎），并可异步生成 **Grad-CAM 病灶热力图**；
2. **检测记录（H5 独立 Tab）**：用户仅可查看**本账号**的历史检测记录（列表 / 筛选 / 详情），他人数据不可见；
3. **病害预警（天气驱动）**：和风天气预报 ×「病害-气象条件」规则库（**25 条权威来源规则**）→ 预测可能爆发的病虫害并推送风险预警（高/中/低）；**H5 端经 WebSocket 实时弹出**，PC 预警中心同步触达；
4. **智能问诊（独立对话页）**：基于 RAG 的领域问答助手，支持直接打字提问与检测后携带结果上下文问诊两种模式，回答附带**可折叠的引用来源**；分档策略——植保问题严守知识库红线（不编造药剂），一般问题正常回答；
5. **反馈答疑（工单闭环）**：用户反馈问题或标记检测结果对错 → 工单 → 管理员回复 → 未读通知 → 可继续追问（多轮往来）；
6. **知识库门户**：一病一档的病害防治资料（含 12 篇健康类识别文档），浏览、语义搜索与 RAG 向量化共用同一数据源；
7. **PC 管理端（管理员专用）**：用户管理 · **实时监控大屏**（WebSocket 事件流 + 统计图表，暗色主题）· 反馈工单中心 · 预警中心（规则 + 记录）· 检测记录管理 · 知识库管理 · 模型管理。

## 当前状态

| 模块 | 状态 | 说明 |
|---|---|---|
| 检测模型（训练/推理/评测） | ✅ | YOLO11s · 38 类 · Kaggle 训练 · 抽测准确率 93.8% |
| FastAPI 后端（9 个业务模块） | ✅ | auth · detection · weather · chat(RAG) · admin · monitor(WS) · warning · feedback · knowledge |
| H5 用户端（5 Tab + 检测详情等二级页） | ✅ | Vue3 + Vant4；含摄像头实时检测（WS）、Grad-CAM 轮询、天气施药提示 |
| PC 管理端（8 个页面） | ✅ | Vue3 + ElementPlus + ECharts；暗色默认 + 亮色切换；监控大屏 WS 事件流 |
| 知识库 | ✅ | **38 篇文档 / 14 种作物 / 209 向量块**，全部经人工审校（`review_status=verified`） |
| 气象预警规则 | ✅ | **25 条**（覆盖 25/26 个病害），全部来自权威来源（农业农村厅 / 农科院等，见 `kb/weather-rules.json`） |
| LLM | ✅ | Moonshot **Kimi kimi-k2.6**（OpenAI 兼容协议；环境变量沿用 `DEEPSEEK_*` 历史命名） |
| 自动化测试 | ✅ | **265 项，0 失败**（backend pytest） |
| 检测标准指标（mAP/PR/混淆矩阵） | ⬜ | 下一阶段优先补齐 |
| Docker 部署 / 论文答辩 | ⬜ | 编排文件已备（MySQL/Redis） |

## 快速启动

> 前置：本机已装 Python（项目用 `.venv`）、Node.js 18+；MySQL 与 Redis 为 Windows 服务（`MySQL80` / `Redis`，开机自启）。

```bash
# ① 后端（端口 8000；交互式文档 /docs）
cd D:\Gpt\crop-doctor\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# ② H5 用户端（端口 5173）
cd D:\Gpt\crop-doctor\frontend-h5
npm run dev

# ③ PC 管理端（端口以启动日志为准，5173 被占时自动顺延）
cd D:\Gpt\crop-doctor\frontend-pc
npm run dev
```

- **账号**：`admin` / `Admin@123456`（管理员，PC 端用）；H5 可自行注册普通用户
- 改 `.env` 后**必须重启后端**（只在启动时读取一次）
- 首次部署新机器：`python -m venv .venv` → `.venv\Scripts\pip install -r backend\requirements.txt` → 两个前端 `npm install`
- 初始化/重置管理员：`.venv\Scripts\python.exe scripts\seed_admin.py --username admin --password <新密码> --nickname 管理员`

## 检测模型（主线）

### 数据集

- **来源**：PlantVillage 公开数据集
- **规模**：39 个类别文件夹，共 **61,486 张**图像，存放于 `ml/data/raw/plantvillage/`
- **类别不均衡**：多数类别约 1000 张，少数类别明显偏多（Orange 5,507 / Tomato YLCV 5,357 / Soybean 5,090）
- 原始图与权重体积较大，通过 `.gitignore` 排除，不入库

### 模型

| 项 | 值 |
|---|---|
| 架构 | YOLO11s（Ultralytics） |
| 类别数 | **38**（不含背景类） |
| 权重 | `ml/exports/yolo11s-plantvillage38-v1.pt`（约 19 MB） |
| 训练环境 | Kaggle 云端 GPU |
| 训练代码 | 训练 notebook 与 YOLO 格式标注数据在 Kaggle 侧，仓库内只保留推理权重、评测脚本与报告 |

> 注：模型 38 类中不包含 `Background_without_leaves`。数据集里的背景类用于验证模型的拒识能力——对背景图不产生任何检测框即为正确。

### 评测结果

评测方式：`scripts/eval_all.py` 从每个类别文件夹中随机抽 8 张（随机种子固定为 42），置信度阈值 `conf=0.25`，取一张图中置信度最高的检测框类别与文件夹名比对。

```
口径一（含背景类）  285 / 312 = 91.3%
口径二（仅 38 类）  285 / 304 = 93.8%   ← 建议对外采用此口径
背景类拒识          8 / 8      = 100%
非背景类未检出      12 张
```

- **27 / 38 个类别达到 100%**
- **弱项类别**（准确率 < 90%）：

| 类别 | 准确率 | 主要问题 |
|---|---|---|
| Tomato___Septoria_leaf_spot | 62% | 2 张误判为晚疫病 |
| Tomato___Target_Spot | 62% | 2 张误判为红蜘蛛 |
| Grape___Leaf_blight | 75% | 2 张未检出 |
| Squash___Powdery_mildew | 75% | 2 张未检出 |
| Tomato___Bacterial_spot | 75% | 1 张未检出、1 张误判为斑枯病 |
| Tomato___Spider_mites | 75% | 2 张未检出 |
| Apple___Apple_scab / Peach___Bacterial_spot / Potato___Early_blight / Raspberry___healthy / Tomato___Late_blight | 88% | 各有 1 张未检出或误判 |

误判集中在番茄类内部互相混淆（斑枯病 ↔ 晚疫病 ↔ 靶斑病 ↔ 红蜘蛛），几类病斑在视觉上确实接近。

完整报告见 `ml/exports/eval-report-yolo11s-plantvillage38-v1.txt`。

### 已知局限

1. **只报告了抽测命中率**：目前尚无 mAP50 / mAP50-95 / Precision / Recall / 混淆矩阵等检测领域标准指标，也未包含训练过程的 loss 曲线；每类仅抽 8 张，统计置信区间较宽。
2. **存在域偏移风险**：PlantVillage 为单叶片、居中、纯色背景的实验室拍摄样本，与农户实拍的复杂背景、多叶片、逆光场景差异较大，93.8% 不能直接等同于田间可用性。
3. **背景拒识未做负样本压力测试**：仅在数据集自带背景类上验证，未用真实田间背景图测试。

### 支持的 38 个类别

| 作物 | 类别 |
|---|---|
| Apple | Apple_scab · Black_rot · Cedar_apple_rust · healthy |
| Blueberry | healthy |
| Cherry | Powdery_mildew · healthy |
| Corn | Cercospora_leaf_spot/Gray_leaf_spot · Common_rust · Northern_Leaf_Blight · healthy |
| Grape | Black_rot · Esca_(Black_Measles) · Leaf_blight_(Isariopsis_Leaf_Spot) · healthy |
| Orange | Haunglongbing_(Citrus_greening) |
| Peach | Bacterial_spot · healthy |
| Pepper,_bell | Bacterial_spot · healthy |
| Potato | Early_blight · Late_blight · healthy |
| Raspberry | healthy |
| Soybean | healthy |
| Squash | Powdery_mildew |
| Strawberry | Leaf_scorch · healthy |
| Tomato | Bacterial_spot · Early_blight · Late_blight · Leaf_Mold · Septoria_leaf_spot · Spider_mites(Two-spotted) · Target_Spot · Tomato_Yellow_Leaf_Curl_Virus · Tomato_mosaic_virus · healthy |

## 旁支方案：ResNet50 分类 + Grad-CAM（可解释性服务）

早期探索阶段的另一条技术路线，**现作为系统的「可解释性服务」**：

- 权重：`ml/exports/resnet50-plantvillage39-v1.pt`（39 类，ResNet50 + 自定义分类头）
- 脚本：`scripts/test_model.py` — 分类输出 Top-3，并用 Grad-CAM 生成热力图，取热力最高的前 20% 区域的最大连通域作为病斑框
- 结果图：`ml/runs/resnet50-gradcam-v1/`
- **系统中的角色**：检测主线仍为 YOLO11s（定位 + 分类能力强）；ResNet50 不再承担检测任务，而是对检测结果异步生成 Grad-CAM 热力图，在检测详情页展示「模型关注的病灶区域」——双模型各司其职，同时为论文提供可解释性分析素材
- 与主线的差异：分类模型无法在一张图中检出多个目标，定位框依赖 CAM 反推而非直接回归，因此检测能力弱于 YOLO11s

## 智能问诊与知识库（已实现）

- **知识库**：`kb/diseases/` 一病一档（含 12 篇健康类识别文档），文档内容来自权威站点采集并经人工审校（`kb/class-map.json` 的 `reviewed_by` 字段可溯源）；入库有「诚信红线」闸门（`scripts/ingest_kb.py`：未经审校拒绝入库，A 级来源强制）
- **向量化与检索**：BAAI/bge-small-zh-v1.5（本地 CPU）→ FAISS（`kb/index/`，209 块）；RAG 检索带**作物域约束**（库外作物诚实告知，不跨作物硬凑）
- **生成**：Moonshot Kimi（OpenAI 兼容协议），SSE 流式输出；**分档策略**——植保问题严守知识库（资料未覆盖时如实说明，**严禁编造农药名称/剂量/安全间隔期**），与植保无关的一般问题正常回答
- **引用来源**：回答附 [n] 引用，前端折叠展示（流式不遮挡正文，完成后点击展开）
- **天气联动**：施药建议结合当地未来 3 天预报（降雨窗口提示）

## 病害预警（已实现）

- **规则库**：`disease_weather_rules` 25 条（温度区间 × 湿度 × 降雨条件 → 高/中/低风险），来源见 `kb/weather-rules.json`（每条附权威来源 URL）；定级采用**多条件叠加**——温/湿/雨/作物四维齐全才判 high，否则降级
- **引擎**：`services/weather_risk.py` 定时（默认 6 小时，可 `POST /warning/refresh` 手动）拉和风预报 → 匹配规则 → 去重写库 → WebSocket 事件广播
- **触达**：PC 监控大屏实时事件流；**H5 WebSocket 实时弹窗**（按用户隔离：全局广播 + 定向本人，绝不串号）+ 未读角标
- **天气服务**：和风天气**专属 API Host**（公共域名已停服）+ Redis 缓存 1 小时；未配 key / 上游异常 / 限流时**优雅降级**（`degraded=true`，零写库零事件，绝不 500）

## 系统架构

```
┌──────────────────────────────┐    ┌──────────────────────────────┐
│         H5 用户端（5 Tab）      │    │       PC 管理端（管理员专用）    │
│         Vue3 + Vant4          │    │     Vue3 + ElementPlus        │
│ 首页：拍照/实时检测 + 风险卡片②  │    │ 管用户：用户管理·用户行为详情     │
│ 记录：仅本账号历史检测记录        │    │ 盯数据：实时监控大屏③(WebSocket) │
│ 问诊：RAG 独立对话页            │    │ 答疑惑：反馈工单中心① 回复解答    │
│ 知识库 · 我的（反馈①/预警②/资料） │    │ 预警规则②·知识库·模型运营        │
└──────────────┬───────────────┘    └──────────────┬───────────────┘
               └──────────┬───────── REST/WS/SSE ─┘
                          ▼
            ┌─────────────────────────────┐
            │        FastAPI 统一后端        │
            │ auth·detection·chat·knowledge│
            │ warning·weather·feedback·admin│
            │ monitor（事件总线 + WS）        │
            └──────┬──────┬──────┬────────┘
                   ▼      ▼      ▼
     ┌──────────┐┌────────┐┌──────────────┐
     │ YOLO 推理  ││GradCAM ││ RAG 问诊      │    ① 工单服务：反馈答疑多轮往来
     │ +分级引擎  ││ResNet50││ FAISS·SSE    │    ② 天气风险引擎：和风预报×
     └──────────┘└────────┘└──────┬───────┘       病害-气象规则→爆发预测
     ┌──────────────────┐   ┌────▼─────────┐  ┌────────────────┐
     │ MySQL 8·Redis 7   │   │ Kimi API     │  │ 和风天气 API     │
     │ FAISS 向量库       │   │ （问诊生成）    │  │ （预报，缓存1h）  │
     └──────────────────┘   └──────────────┘  └────────────────┘

   三大闭环：① 答疑（用户反馈→管理员回复→通知追问）
            ② 预警（天气×病害规则→风险推送 H5+PC）
            ③ 监控（用户数据实时汇聚→PC 大屏）
   实时通道：WebSocket（实时检测帧 / 预警推送 / PC 监控事件流）· SSE（问诊流式输出）
```

> 检测 → 分级为同步链路；Grad-CAM 热力图、预警评估为异步；天气服务失败降级不影响检测；问诊独立入口，检测上下文按需注入。

## 技术栈

| 层 | 选型 |
|---|---|
| 检测 | **Ultralytics YOLO11s** · PyTorch · OpenCV |
| 可解释性 | ResNet50 + **grad-cam** · torchvision |
| 训练 | Kaggle 云端 GPU |
| 后端 | Python 3.14（`.venv`）· FastAPI · SQLAlchemy · Alembic · WebSocket · SSE · loguru |
| 问诊 | BAAI/bge-small-zh-v1.5（本地 Embedding）· FAISS · **Moonshot Kimi**（OpenAI 兼容） |
| 天气 | 和风天气（专属 API Host）· Redis 缓存 |
| H5 端 | Vue 3 · Vant 4 · Vite · Pinia · getUserMedia |
| PC 端 | Vue 3 · Element Plus · ECharts · Pinia |
| 数据 | MySQL 8.0.28 · Redis 7.4 |
| 部署 | Docker Compose（MySQL / Redis 基础设施） |

## 目录结构

> 与磁盘实际结构 1:1 对应（枚举自真实目录；已排除 `.git` / `.venv` / `node_modules` / `__pycache__` 等非源码内容）。

```text
crop-doctor/
├── README.md
├── .env                      # 实际配置（不入库；模板见 .env.example）
├── .env.example              # 环境变量模板
├── .gitignore
├── docker-compose.yml        # 本地基础设施（MySQL / Redis）
│
├── backend/                  # FastAPI 统一后端
│   ├── alembic.ini · pytest.ini · requirements.txt
│   ├── logs/ · uploads/      # 运行期日志与上传文件【不入库】
│   ├── migrations/versions/0001_initial_schema.py   # Alembic 迁移
│   ├── tests/                # pytest 套件（27 个 test_*.py / 265 项）
│   │   ├── conftest.py       # 夹具（内存 SQLite / 关预警调度防 Redis 污染）
│   │   ├── test_auth.py · test_detection.py · test_chat.py · test_warning.py
│   │   │   · test_knowledge.py · test_feedback.py · test_admin.py · test_monitor.py
│   │   │   · test_realtime.py · test_risk_grading.py · …（按模块组织）
│   │   └── test_chat_prompt_tiering.py   # 提示词红线逐字断言
│   └── app/
│       ├── main.py           # 入口（lifespan：YOLO 加载 / 预警调度 / RAG 预热 / monitor 启停）
│       ├── api/v1/           # 9 个业务路由（router.py 条件挂载）
│       │   ├── auth.py       # 注册 / 登录 / 资料 / 改密
│       │   ├── detection.py  # 图片检测 / 记录 CRUD / Grad-CAM / WS 实时检测
│       │   ├── weather.py    # 实况 / 预报 / 施药建议
│       │   ├── chat.py       # 问诊 SSE 流式 + 会话（SYSTEM_PROMPT 分档策略在此）
│       │   ├── knowledge.py  # 门户（分类/搜索/详情）+ 管理端 CRUD / 重建索引
│       │   ├── warning.py    # 预警（H5 拉取 + WS 实时推送）/ 规则 CRUD / 手动评估
│       │   ├── feedback.py   # 反馈工单（多轮往来 / 未读）
│       │   ├── admin.py      # 管理端（统计 / 用户 / 检测 / 工单 / 知识库 / 模型）
│       │   └── monitor.py    # PC 监控事件流 WS（仅管理员）
│       ├── core/             # config（51 键）/ security(JWT) / deps / response(统一信封)
│       │   ├── exceptions.py # 业务错误码（1001~1004 / 4001~4003 / 5001~8003）
│       │   ├── database.py / redis_client.py / logging.py / concurrency.py
│       ├── models/           # SQLAlchemy ORM（10 表：user / detection / chat /
│       │                     #   feedback / knowledge / warning 等）
│       ├── schemas/          # Pydantic 模型（按模块 10 个文件）
│       └── services/         # 业务服务（14 个）
│           ├── yolo_infer.py # YOLO 推理 + 标注图（PIL 中文烧字）
│           ├── severity.py   # 严重度四级分级（健康类豁免）
│           ├── gradcam.py    # ResNet50 Grad-CAM 热力图（异步）
│           ├── rag.py        # FAISS 检索（作物域约束 + 软过滤）
│           ├── llm.py        # Kimi 流式（分档提示词 / 关思考 / 429 降级）
│           ├── weather.py    # 和风天气（缓存 1h / 降级 / 施药建议）
│           ├── weather_risk.py   # 气象预警引擎（多条件叠加定级 + 调度器）
│           ├── monitor.py    # 事件总线（Redis Pub/Sub + 本地扇出 + 监听器）
│           ├── ticket.py / knowledge_admin.py
│           └── annotate.py / classmap.py / model_registry.py
│
├── frontend-h5/              # H5 用户端（Vue3 + Vant4，hash 路由）
│   ├── .env.development / .env.production   # API 地址
│   ├── .npmrc                # 腾讯云 npm 镜像
│   ├── index.html / vite.config.js / package.json
│   └── src/
│       ├── main.js / App.vue         # 入口 + TabBar 容器
│       ├── router/index.js           # 13 条路由 + 登录守卫
│       ├── api/                      # 9 个接口模块（request.js 统一封装信封/token）
│       ├── views/                    # 14 个页面
│       │   ├── HomePage / RecordsPage / ChatPage / KnowledgePage / MinePage  （5 Tab）
│       │   ├── LoginPage / DetectionDetailPage / RealtimePage（摄像头实时）
│       │   ├── AlertsPage / FeedbackListPage / FeedbackDetailPage
│       │   └── KnowledgeDocPage / SettingsPage / AboutPage
│       ├── components/chat/          # MessageBubble / MessageList / CitationBar(折叠)
│       │                             # ChatInputBar / DetectionContextCard / QuickQuestions
│       ├── components/common/        # SeverityTag / EmptyState / PageNav
│       ├── components/layout/TabBar.vue   # 5 Tab 底部导航（凸出问诊）
│       ├── stores/                   # user / chat / badge（未读角标）
│       ├── utils/                    # sse（流式）/ alertsWs（预警推送）/ geo（定位）
│       │                             # markdown（轻量渲染）/ format
│       └── styles/tokens.css         # 设计令牌（语义色 / 圆角 / 字号阶梯）
│
├── frontend-pc/              # PC 管理端（Vue3 + ElementPlus + ECharts）
│   ├── .env.development / .env.production   # API 地址（根文件同 H5）
│   └── src/
│       ├── layouts/AdminLayout.vue   # 侧边栏框架（暗色默认 / 亮色切换）
│       ├── views/                    # 8 个页面：Login / Dashboard(大屏) / Feedback
│       │                             # Users / Warning / Detections / Knowledge / Model
│       ├── components/charts/        # BaseChart + 趋势/排行/健康率/饼图 + WeatherPanel
│       ├── components/monitor/       # EventStream / EventItem（WS 实时事件流）
│       ├── components/{detections,feedback,knowledge,model,users,common}/   # 抽屉/对话框
│       ├── api/ · stores/(user/monitor/theme) · router/
│       ├── utils/(ws/echarts/theme/url) · styles/(tokens/element-dark)
│
├── kb/                       # 知识库
│   ├── class-map.json        # 38 类映射表（中文名 / 作物 / 来源 / 审校状态——单一事实来源）
│   ├── weather-rules.json    # 25 条气象预警规则（每条附权威来源 URL）
│   ├── weather-rules.report.json   # 覆盖率报告（25/26，未覆盖清单）
│   ├── sources.seed.json     # 采集种子源
│   ├── diseases/             # 38 篇定稿文档（一病一档，文末附来源）
│   ├── index/                # FAISS 索引（chunks.json / faiss.index / meta.json）
│   └── _review/              # 38 篇采集草稿 + REVIEW-INDEX.md 审校索引【过程产物】
│
├── ml/
│   ├── data/raw/plantvillage/  # 数据集：39 类文件夹 61,486 张【不入库】
│   ├── exports/              # 两个权重（19M / 95M）+ 评测报告【不入库】
│   └── runs/                 # 评测结果图：gradcam 72 张 / detect 58 张【不入库·论文配图素材】
│
├── docs/                     # 5 篇设计文档
│   ├── architecture.md       # 架构 v2.1（页面 / API / 服务 / 数据模型 / 三大闭环）
│   ├── ui-design.md          # UI 规范 v1（视觉系统 / 线框 / 组件映射）
│   ├── impl-backend-v1.md    # 后端 Phase 1 实现级设计（§5 API 契约 / §5.3 错误码）
│   ├── impl-rag-chat-v1.md   # RAG + chat + H5 实现级设计（§5 SSE 契约 / §16 闸门）
│   └── impl-pc-admin-v1.md   # PC 管理端 + 后端五模块（§5 WS 协议）
│
└── scripts/                  # 辅助脚本（12 个）
    ├── test_yolo.py          # YOLO 单图 / 整类抽测（主线）
    ├── eval_all.py           # 38 类全量抽测 → 评测报告
    ├── test_model.py         # ResNet50 分类 + Grad-CAM（可解释性）
    ├── repack_pt.py          # 权重打包还原（一次性工具）
    ├── collect_kb.py         # 知识库批量采集（限速 / 合规 / 断点续采）
    ├── verify_class_map.py   # 映射表校验
    ├── review_index.py       # 审校索引生成
    ├── ingest_kb.py          # 入库（诚信红线闸门：审校 / A 级来源）
    ├── build_index.py        # FAISS 索引构建
    ├── kb_common.py          # 知识库公共库（审校三态派生）
    ├── seed_weather_rules.py # 气象预警规则入库（幂等 upsert）
    └── seed_admin.py         # 管理员初始化 / 重置
```


## 知识库重建（修改 kb/diseases 后执行）

```bash
.venv\Scripts\python.exe scripts\ingest_kb.py      # 入库（诚信闸门校验）
.venv\Scripts\python.exe scripts\build_index.py    # 重建 FAISS 索引
.venv\Scripts\python.exe scripts\seed_weather_rules.py   # 气象预警规则入库（幂等）
```

## 自动化测试

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest --basetemp=.pytest_tmp --junitxml=.pytest_tmp/junit.xml
# 当前 265 项：0 失败 / 0 错误（3 skipped 为需真实环境的冒烟用例，1 xpassed）
# 夹具会自动清空共享 Redis 的 weather:* 键，避免缓存污染降级类断言
```

## 环境变量（.env，模板见 .env.example）

| 键 | 说明 |
|---|---|
| `DATABASE_URL` | MySQL 连接（`mysql+pymysql://root:***@localhost:3306/crop_doctor`） |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `APP_SECRET_KEY` | JWT 签名密钥 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `LLM_MODEL` | **LLM 配置（历史命名，现为 Moonshot Kimi）** |
| `WEATHER_API_KEY` / `WEATHER_BASE_URL` / `WEATHER_LOCATION` | 和风天气（**须用专属 API Host**）+ 默认位置（遵义 101260201） |
| `EMBEDDING_MODEL` / `HF_ENDPOINT` | 本地向量模型与镜像源 |
| `YOLO_WEIGHTS_PATH` / `RESNET_WEIGHTS_PATH` | 模型权重路径 |
| `WARNING_*` / `MONITOR_*` | 预警刷新周期 / WS 事件总线参数 |

## 开发里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| M1 | 开题报告、数据集获取与清洗 | ✅ |
| M2 | YOLO11s 训练与评估（38 类，93.8%） | ✅ |
| M2.5 | 补齐检测标准指标（mAP / PR / 混淆矩阵）、田间泛化性验证 | ⬜ |
| M3 | 后端核心（认证/检测/分级/记录） | ✅ |
| M3.5 | Grad-CAM 服务 / 天气服务 | ✅ |
| M4 | RAG 智能问诊（知识库 / 检索 / LLM / SSE 流式对话页） | ✅ |
| M4.5 | 预警中心（气象规则引擎 + WS 实时推送）/ 反馈工单系统 | ✅ |
| M5 | H5 前端 / PC 前端 + 联调 | ✅ |
| M6 | Docker Compose 部署、论文撰写、答辩 | ⬜ |

## 已知限制与注意事项

1. **模型层**：见「检测模型 · 已知局限」（抽测口径 / 域偏移 / 背景拒识压力测试缺失）。
2. **LLM 频率限制**：Moonshot 免费账号 `max RPM = 3`，连续提问会触发 429——系统会**优雅降级**为知识库原文回答，不崩溃。
3. **天气额度**：和风免费版有调用频率限制；Redis 缓存（1 小时）已挡住大部分重复请求，触发限流时天气相关展示会降级提示。
4. **预警密度**：定级采用多条件叠加（四维齐全才判 high），单次评估可能产生数十条中低风险预警；PC 预警中心可按等级筛选。
5. **知识库覆盖**：38 类中「葡萄埃斯卡病」无权威气象指标故无预警规则；「葡萄叶枯病」规则仅约束湿度与降雨（温度留空）。
6. **安全**：MySQL 为开发配置（root 弱密码、监听 0.0.0.0）；生产部署前须收紧并更换 JWT 密钥与全部 API 密钥。

## 参考项目

- [pest-detector](https://github.com/aiibooouuu/pest-detector) — YOLO 农业害虫检测，检测后自动生成治疗建议
- [Langchain-Chatchat](https://github.com/chatchat-space/Langchain-Chatchat) — 本地知识库 RAG 问答引擎架构参考
- [garbage-classification](https://github.com/lizuju/garbage-classification) — 前后端分离检测系统（用户体系 / 管理后台 / 模型迭代）结构参考
- [rag-custom-agent](https://github.com/codemaster1024/rag-custom-agent) — RAG 智能客服 Agent 流程参考（意图识别 → 检索 → 重排 → 生成）

## License

MIT
