# 作物医生 CropDoctor

> 基于 YOLOv8 与检索增强生成（RAG）的农作物病虫害智能诊断与咨询平台（毕业设计）

## 项目简介

面向智慧农业场景，构建「**视觉诊断 + 知识问答**」一体化平台：

1. **智能检测**：自训练 YOLOv8 模型识别农作物病虫害（当前聚焦番茄 6 类病害），支持图片 / 视频 / 摄像头实时检测；
2. **智能客服**：基于 RAG 的领域问答助手，YOLO 识别结果自动注入对话上下文，结合病害防治知识库给出有据可查的防治建议——**「识别即问诊」闭环**；
3. **双端覆盖**：H5 移动端（农户拍照问诊）+ PC 管理端（数据大屏与知识库运营）。

## 核心特性（规划）

### 检测（YOLO，自训练模型）

- 自训练 YOLOv8 检测模型，番茄 6 类病害（灰叶斑病、晚疫病、细菌性斑疹病、叶霉病、潜叶蛾虫害、药害）的定位与分类
- 图片 / 视频 / 实时摄像头三种检测方式
- Precision / Recall / mAP50 / mAP50-95 评估，含消融对比实验（n/s/m 模型规模、数据增强策略）

### 客服（RAG + LLM）

- 病害防治知识库：文档上传 → 自动切分 → 向量化（bge-small-zh）→ FAISS 检索
- 检测结果（病害类别 + 置信度）作为检索条件注入对话，抑制大模型幻觉
- DeepSeek API 流式生成（SSE），回答附带引用来源（文档名 + 段落）
- 多轮对话记忆

### H5 用户端

拍照 / 相册上传 → 查看标注结果图 → 一键问诊 → 多轮追问 → 历史记录

### PC 管理端

检测量 / 病害分布大屏（ECharts）· 检测记录管理 · 知识库管理（上传与向量化状态）· 用户管理 · 模型权重热更新

## 系统架构

```
┌─────────────────┐      ┌─────────────────┐
│    PC 管理端     │      │    H5 用户端     │
│ Vue3+ElementPlus │      │   Vue3+Vant4    │
└────────┬────────┘      └────────┬────────┘
         └──────────┬─────────────┘
                    ▼
        ┌──────────────────────────┐
        │      FastAPI 统一后端      │
        │ 认证 │ 检测 │ 客服 │ 管理统计 │
        └────┬────────────────┬────┘
             ▼                ▼
   ┌────────────────┐  ┌──────────────────────┐
   │  YOLO 检测服务   │─→│    RAG 智能客服服务    │
   │   自训练权重     │  │ FAISS 检索 + 重排序    │
   │  线程池推理      │  │ 上下文拼接 + 引用溯源   │
   └────────────────┘  └──────────┬───────────┘
                                   ▼
                          ┌────────────────┐
                          │ LLM API DeepSeek│
                          └────────────────┘

   数据层：MySQL │ Redis │ FAISS 向量库
```

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.10+ · FastAPI · SQLAlchemy · Alembic |
| 检测 | Ultralytics YOLOv8 · PyTorch · OpenCV |
| 客服 | bge-small-zh（Embedding）· FAISS · DeepSeek API（OpenAI 兼容） |
| H5 端 | Vue 3 · Vant 4 · Vite |
| PC 端 | Vue 3 · Element Plus · ECharts · Pinia |
| 数据 | MySQL 8 · Redis 7 |
| 部署 | Docker · Docker Compose |
| 训练 | 云 GPU（Colab / Kaggle / AutoDL） |

## 目录结构

```
crop-doctor/
├── README.md                 # 本文件
├── .gitignore
├── .env.example              # 环境变量模板（复制为 .env 后填写）
├── docker-compose.yml        # 本地一键编排（MySQL / Redis）
│
├── backend/                  # FastAPI 统一后端（模块化单体）
│   ├── app/
│   │   ├── main.py           # 应用入口（待实现）
│   │   ├── core/             # 配置、安全（JWT）、公共依赖
│   │   ├── api/v1/           # 路由层：auth 认证 / detection 检测 / chat 客服 / admin 管理
│   │   ├── services/         # 业务层：YOLO 推理、RAG 检索、LLM 调用
│   │   ├── models/           # SQLAlchemy ORM 模型
│   │   ├── schemas/          # Pydantic 请求 / 响应模型
│   │   └── utils/            # 工具函数
│   ├── tests/                # 单元 / 接口测试
│   ├── requirements.txt
│   └── Dockerfile            # 待实现
│
├── frontend-pc/              # PC 管理端（Vue3 + Element Plus + ECharts）
│   └── src/
│       ├── views/            # 大屏 / 检测记录 / 知识库 / 用户 / 模型管理
│       ├── components/
│       ├── router/
│       ├── stores/           # Pinia
│       └── api/              # 后端接口封装
│
├── frontend-h5/              # H5 用户端（Vue3 + Vant 4）
│   └── src/
│       ├── views/            # 拍照检测 / 智能问诊 / 历史记录
│       ├── components/
│       ├── router/
│       └── stores/
│
├── ml/                       # YOLO 检测模型训练（独立于后端运行）
│   ├── data/
│   │   ├── raw/              # 原始数据集（不入库）
│   │   └── datasets/         # YOLO 格式数据集（不入库，Roboflow 导出放这里）
│   ├── notebooks/            # 数据探索 / 训练 / 评估 notebook
│   └── exports/              # 导出的推理权重（不入库，供 backend 加载）
│
├── kb/                       # RAG 知识库源文档（入库，随代码版本管理）
│   ├── diseases/             # 病害防治资料（按病害名一病一档）
│   └── faq/                  # 常见问答
│
├── docs/                     # 设计文档（架构 / 数据库 ER / API 约定）
└── scripts/                  # 辅助脚本（数据格式转换、环境自检等）
```

## 环境要求

- Python 3.10+
- Node.js 18+
- Docker & Docker Compose（可选，用于 MySQL / Redis）
- 模型训练：云 GPU（Colab / Kaggle 免费额度或 AutoDL 租用）

## 快速开始（待实现）

```bash
# 1. 克隆仓库
git clone <repo-url>
cd crop-doctor

# 2. 启动基础设施（可选）
docker compose up -d mysql redis

# 3. 后端
cp .env.example .env        # 填写 DEEPSEEK_API_KEY 等
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# 4. 前端（脚手架就绪后）
# cd frontend-h5 && npm i && npm run dev
# cd frontend-pc && npm i && npm run dev
```

## 开发里程碑

| 阶段 | 周期 | 内容 |
|---|---|---|
| M1 | 第 1~2 周 | 开题报告、数据集获取与清洗（Roboflow 导出 YOLO 格式） |
| M2 | 第 3~4 周 | YOLO 训练与评估（目标 mAP50 ≥ 0.85），导出权重 |
| M3 | 第 5~6 周 | 后端：认证 / 检测接口 / YOLO 推理服务 |
| M4 | 第 7~8 周 | RAG 客服：知识库构建 / 检索 / DeepSeek 接入 / SSE 流式 |
| M5 | 第 9~10 周 | H5 + PC 前端开发与联调 |
| M6 | 第 11~12 周 | Docker Compose 部署、整体测试、论文撰写、答辩 |

## 参考项目

- [pest-detector](https://github.com/aiibooouuu/pest-detector) — YOLOv8 + CBAM 农业害虫检测，检测后自动生成治疗建议
- [Langchain-Chatchat](https://github.com/chatchat-space/Langchain-Chatchat) — 本地知识库 RAG 问答引擎架构参考
- [garbage-classification](https://github.com/lizuju/garbage-classification) — 前后端分离检测系统（用户体系 / 管理后台 / 模型迭代）结构参考
- [rag-custom-agent](https://github.com/codemaster1024/rag-custom-agent) — RAG 智能客服 Agent 流程参考（意图识别 → 检索 → 重排 → 生成）

## License

MIT
