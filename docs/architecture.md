# 系统架构设计 v2.1（双端角色分工版）

> 状态：已定稿 · 本文与 README.md 同步维护 · 后端/前端开发以此为准

## 1. 总体架构

模块化单体：一个 FastAPI 应用承载全部业务，模型推理走线程池，Grad-CAM 异步生成，不做微服务。

**双端角色严格分工**：H5 用户端 = 普通用户的功能使用入口；PC 管理端 = 管理员工作台（管用户 / 盯数据 / 答疑惑）。

```
H5 用户端 (Vue3+Vant4, 5 Tab) ──┐                ┌── PC 管理端 (Vue3+ElementPlus, 管理员专用)
   │ REST + WebSocket + SSE      │                │  REST + WebSocket(监控事件流)
   └──────────────┬─────────────┴────────────────┴──────────────┘
                  ▼
        FastAPI 统一后端（8 路由模块）
   auth · detection · chat · knowledge · warning · weather · feedback · admin
                  │
        ┌─────────┼───────────┬──────────────┬─────────────┐
        ▼         ▼           ▼              ▼             ▼
   YOLO 推理   Grad-CAM    RAG 问诊      工单服务①      天气风险引擎②
   (YOLO11s)  (ResNet50)   (FAISS+SSE)   (答疑多轮)   (和风预报×病害气象规则)
        │         │           │              │             │
        └──── MySQL 8 ───────┴──── Redis 7 ──┴──── FAISS ──┘
                                （外部：DeepSeek API · 和风天气 API）

   三大闭环：① 答疑（用户反馈→管理员回复→通知→追问）
            ② 预警（天气预报×病害-气象规则→爆发风险推送 H5+PC）
            ③ 监控（用户检测数据实时汇聚→PC 大屏 WebSocket 事件流）
```

## 2. 前端页面清单

### 2.1 H5 用户端（Vant 4，底部 5 个一级 Tab，面向普通用户）

| Tab | 页面 | 内容 |
|---|---|---|
| 首页 | 拍照检测 / 相册上传 / 摄像头实时检测 + **今日风险预警卡片②** | 实时检测 getUserMedia 抓帧（2-5fps）→ WebSocket；风险卡片展示天气驱动的当前病害爆发风险，点击进入预警中心 |
| 记录 | **检测记录（仅本人可见）** | 本账号历史记录列表 · 按病害/时间筛选 · 详情（分级·热力图·天气建议·反馈入口）；他人数据严格隔离 |
| 问诊 | **独立对话页（RAG）** | 聊天气泡 · SSE 流式输出 · 引用来源 · 快捷问题 · 会话历史；**无需先检测，可直接打字提问**；检测详情「去问诊」携带上下文进入 |
| 知识库 | 病害知识门户 | 作物分类浏览 · 搜索 · 病害详情（症状/发生条件/防治方案） |
| 我的 | 个人中心 | 登录注册 · 资料头像 · **我的反馈（含管理员回复，未读标记）** · 预警消息入口 · 设置 |

二级页面：检测详情页（标注图 · 检测框列表 · 严重度分级 · Grad-CAM 热力图异步加载 · 天气施药建议 · 反馈/标记对错 · 「去问诊」）；预警中心列表页（天气驱动风险预警详情）；反馈对话页（与管理员的多轮往来）。

### 2.2 PC 管理端（Element Plus + ECharts，仅管理员，三大职责 + 运营）

| 页面 | 职责 | 内容 |
|---|---|---|
| 登录 | — | 管理员账号登录 |
| **实时监控大屏③** | 盯数据 | WebSocket 实时事件流（最新检测/反馈/预警滚动）· 检测量趋势 · 患病率排行 · 健康率走势 · 按作物下钻 · 预警统计 · 天气面板 |
| **反馈工单中心①** | 答疑惑 | 工单列表（待回复/已回复/已关闭筛选）· 对话式回复界面 · 关闭工单 · 检测对错标记类工单的样本查看 |
| 用户管理 | 管用户 | 用户列表 · 用户详情（其检测记录/反馈历史/预警记录）· 禁用启用 · 重置密码 |
| 预警中心② | 预警运营 | 病害-气象条件规则配置（温度/湿度/降雨区间 × 风险等级）· 当前风险总览 · 预警记录与推送情况 |
| 检测记录管理 | 盯数据 | 全局检测记录 · 筛选 · 详情（含热力图/分级/反馈状态）· 检测异常趋势监测 |
| 知识库管理 | 运营 | 文档上传/编辑 → 自动向量化 · 状态查看 |
| 模型管理 | 运营 | 权重上传 · 版本切换（热更新） |

## 3. 后端 API 模块（backend/app/api/v1/）

| 模块 | 端点组 | 说明 |
|---|---|---|
| auth | 注册/登录/资料/改密 | JWT，普通用户 vs 管理员 |
| detection | 图片检测、`ws://` 实时检测、**我的记录（仅本人，强制 user_id 过滤）** | YOLO 线程池推理；检测完成同步触发分级；Grad-CAM 异步 |
| chat | 问诊对话（SSE）、会话管理 | 支持 `detection_id` 参数注入检测上下文 |
| knowledge | 门户分类/搜索/详情 | 与 RAG 共用 knowledge_docs 数据源 |
| warning | **风险预警查询（H5）、病害-气象规则 CRUD、风险总览（PC）** | 天气驱动：weather_risk 引擎生成 alert_records；H5 未读数 |
| weather | 当前天气 + 3 天预报 | 和风 API 代理，Redis 缓存 1h |
| feedback | **工单创建、我的工单列表、工单消息往来（多轮）、未读数（H5）；工单列表/回复/关闭（PC admin）** | 两类工单：问题咨询 / 检测结果对错标记（附 record_id 与样本图） |
| admin | 实时监控事件流（`ws://`）、大屏统计、全局检测记录、用户管理（详情/禁用/重置）、反馈工单处理、预警管理、知识库/模型管理 | 仅管理员权限 |

## 4. 服务层（backend/app/services/）

| 服务 | 职责 | 关键设计 |
|---|---|---|
| yolo_infer | YOLO11s 推理 | 线程池执行，不阻塞事件循环 |
| severity | **严重度分级引擎** | 纯规则：病斑数 + 面积占比 → 0无/1轻微/2中等/3严重；阈值读 .env 可调 |
| gradcam | Grad-CAM 热力图 | ResNet50 旁支模型；**异步任务**，检测响应先返回，热力图稍后可查 |
| rag | 向量化/FAISS 检索/重排 | kb/ 文档 → 切分 → bge-small-zh → FAISS |
| llm | DeepSeek 客户端 | OpenAI 兼容协议，SSE 流式 |
| weather | 和风天气客户端 | Redis 缓存 TTL 1h，失败降级（不阻塞主流程） |
| weather_risk | **②病害爆发预测引擎** | 病害-气象条件规则（disease_weather_rules）× 天气预报 → 高/中/低风险 → 生成 alert_records 推送 H5/PC；定时任务刷新 |
| ticket | **①答疑工单服务** | feedbacks（工单头）+ feedback_messages（往来消息）；管理员回复后置未读标记；状态机 待回复/已回复/已关闭 |
| monitor | **③实时监控事件流** | 检测/反馈/预警事件 → Redis Pub/Sub → admin WebSocket 推送 |

## 5. 数据模型（MySQL，核心表）

| 表 | 关键字段 |
|---|---|
| users | id, username, password_hash, role(user/admin), avatar, status, created_at |
| detection_records | id, user_id, image_path, **severity_level**, top_disease, top_conf, **gradcam_path**, created_at |
| detection_details | id, record_id, class_name, conf, bbox |
| feedbacks（工单头） | id, user_id, **type(question / result_verdict)**, record_id 可空, title, **status(pending / replied / closed)**, last_reply_at, created_at |
| feedback_messages（工单消息） | id, feedback_id, sender_role(user / admin), sender_id, content, **is_read**, created_at |
| disease_weather_rules（②病害-气象规则） | id, disease, temp_min, temp_max, humidity_min, humidity_max, rain_condition, risk_level, advice, enabled |
| alert_records（②预警记录） | id, **source(weather / detection)**, disease, risk_level(high / mid / low), content, user_id 可空（全局/定向）, is_read, created_at |
| knowledge_docs | id, title, crop, disease, content_md, vector_status, created_at |
| chat_sessions / chat_messages | 会话与消息（含引用来源 JSON） |

> 检测数据隔离：detection 模块所有「我的记录」查询强制 `user_id = 当前登录用户`；admin 模块才可查全局。

## 6. 关键架构决策

1. **双端角色严格分工**：H5 = 用户功能入口（检测/记录/问诊/知识库/预警/反馈/个人中心）；PC = 管理员工作台（管用户 / 盯数据 / 答疑惑 + 运营）。两端共用同一后端，权限层隔离。
2. **双模型各司其职**：YOLO11s 检测（定位+分类），ResNet50 转正为可解释性服务（Grad-CAM 热力图），旁支资产复用。
3. **分级用规则引擎而非模型**：零训练成本，阈值可配置，答辩可解释。
4. **实时检测用前端抓帧**：getUserMedia + WebSocket（2-5fps），不做服务端 MJPEG 推流，复杂度最低。
5. **预警以天气驱动为主（事前预测）**：病害-气象条件规则库 × 和风预报 → 爆发风险，主动推送；检测异常趋势作为管理端监控视角（source=detection 预留），不再是预警主链路。
6. **反馈升级为工单式答疑闭环**：用户提问/标记对错 → 管理员回复 → 未读通知 → 可追问（多轮）；同时保留检测对错标记数据为将来样本回流预留。
7. **知识库一份数据两个出口**：kb/ 一病一档 → 门户浏览 + RAG 向量化，不维护两份。
8. **异步化不阻塞主链路**：检测响应 = 框+分级（同步）；Grad-CAM、预警刷新为异步；天气失败降级不影响检测。
9. **检测记录数据隔离**：H5 记录 Tab 仅本人数据（服务端强制过滤），PC 管理端按职责查看全局。

## 7. 与 README 的关系

README 承载「项目总览 + 进度」，本文承载「详细设计」。功能或结构变更时，两份文档同步更新。
