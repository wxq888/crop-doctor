# -*- coding: utf-8 -*-
"""应用配置：基于 pydantic-settings 读取仓库根 ``.env``，并解析为绝对路径。

约定：``Settings`` 字段名小写，环境变量名大写，pydantic-settings 自动映射。
``.env`` 位于仓库根（``D:\\Gpt\\crop-doctor\\.env``），此处以 ``Path(__file__)``
向上回溯定位仓库根，从而兼容任意 CWD 启动以及 Windows 中文路径。
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 仓库根定位：backend/app/core/config.py -> 上溯 3 层到仓库根
REPO_ROOT: Path = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """全局配置对象。"""

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== 应用 =====
    app_env: str = "dev"
    app_secret_key: str = "change-me-to-a-random-string"

    # ===== JWT（签名密钥复用 APP_SECRET_KEY，不另设）=====
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 天

    # ===== 文件上传 =====
    upload_dir: str = "backend/uploads"
    max_upload_mb: int = 10

    # ===== 数据库 / Redis =====
    mysql_root_password: str = "devpass"
    database_url: str = "mysql+pymysql://root:devpass@localhost:3306/crop_doctor"
    redis_url: str = "redis://localhost:6379/0"

    # ===== LLM（智能客服）=====
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"

    # ===== Embedding（RAG 向量化）=====
    embedding_model: str = "BAAI/bge-small-zh-v1.5"

    # ===== 知识库数据链路（kb/ 采集与一病一档）=====
    # 模型下载镜像：huggingface.co 不可达，必须走镜像
    hf_endpoint: str = "https://hf-mirror.com"
    # hf-xet 会绕开普通 HTTP 走 Xet CAS，而 hf-mirror 不代理 Xet → 必须置 1 关闭
    hf_hub_disable_xet: str = "1"
    kb_diseases_dir: str = "kb/diseases"
    kb_class_map_path: str = "kb/class-map.json"
    faiss_index_dir: str = "kb/index"

    # ===== RAG 检索参数 =====
    # P2 修复：4 → 8。知识库仅 30 chunk（近零成本），而「症状描述 + 用药意图」混合提问会把
    # 「四、防治方法」章节挤到第 5~10 名（分数仍在 min_score 之上）→ top_k=4 时漏召回，
    # 模型误答「知识库暂无相关资料」。提高召回条数即可覆盖防治章节（不改 min_score 语义）。
    rag_top_k: int = 8
    rag_min_score: float = 0.35
    # query 侧指令前缀（BGE 中文 s2p 推荐）；置空即关闭
    rag_query_instruction: str = "为这个句子生成表示以用于检索相关文章："
    rag_chunk_max_chars: int = 600
    rag_chunk_overlap_chars: int = 60
    embedding_batch_size: int = 32

    # ===== LLM 生成参数（chat 后端）=====
    llm_timeout_seconds: int = 60
    llm_max_tokens: int = 800
    llm_temperature: float = 0.3
    chat_context_messages: int = 8
    # Moonshot Kimi（kimi-k2.6 等）为推理模型：关闭「思考」输出，避免思考链混入正文
    llm_disable_thinking: bool = True

    # ===== YOLO 检测模型 =====
    yolo_weights_path: str = "ml/exports/yolo11s-plantvillage38-v1.pt"
    yolo_conf_threshold: float = 0.35

    # ===== 可解释性（Grad-CAM 热力图）=====
    resnet_weights_path: str = "ml/exports/resnet50-plantvillage39-v1.pt"
    gradcam_enabled: bool = True

    # ===== 病害严重度分级（规则引擎阈值）=====
    severity_spot_count_minor: int = 2
    severity_spot_count_moderate: int = 5
    severity_area_ratio_moderate: float = 0.05
    severity_area_ratio_severe: float = 0.15

    # ===== 天气服务（施药建议联动）=====
    weather_api_key: str = ""
    weather_base_url: str = "https://devapi.qweather.com"
    weather_location: str = "101010100"
    weather_cache_ttl: int = 3600

    # ===== 预警定时刷新（warning 模块）=====
    warning_enabled: bool = True  # 定时刷新总开关
    warning_refresh_interval_minutes: int = 360  # 后台刷新周期（分钟，默认 6h）
    warning_forecast_days: int = 3  # 参与评估的预报天数（≤3）
    # 多条件叠加提权：true=四维（温度·湿度·降雨·作物）齐全才保留原级别，声明不全则降一级；
    # false=回退旧行为（命中即按规则原级别，不降级）。见 weather_risk.py::_grade_level。
    warning_require_full_dimensions: bool = True

    # ===== 实时监控事件总线（monitor 模块）=====
    monitor_redis_channel: str = "cropdoctor:monitor:events"  # Redis Pub/Sub 频道
    monitor_recent_key: str = "cropdoctor:monitor:recent"  # 事件快照 LIST 键（断线补拉）
    monitor_recent_max: int = 50  # 快照保留条数
    monitor_heartbeat_seconds: int = 25  # 服务端 WS 心跳间隔（秒）
    monitor_max_connections: int = 20  # 单进程最大 WS 连接数

    # ===== 知识库重新向量化（knowledge 模块）=====
    kb_reindex_timeout_seconds: int = 300  # 重建索引子进程超时（秒）

    # ---- 派生绝对路径：兼容任意 CWD 启动 ----
    @property
    def upload_path(self) -> Path:
        """上传根目录的绝对路径。"""
        path = Path(self.upload_dir)
        return path if path.is_absolute() else (REPO_ROOT / path)

    @property
    def yolo_weights_abs(self) -> Path:
        """YOLO 权重的绝对路径。"""
        path = Path(self.yolo_weights_path)
        return path if path.is_absolute() else (REPO_ROOT / path)

    @property
    def resnet_weights_abs(self) -> Path:
        """ResNet50 权重的绝对路径。"""
        path = Path(self.resnet_weights_path)
        return path if path.is_absolute() else (REPO_ROOT / path)

    @property
    def kb_diseases_path(self) -> Path:
        """``kb/diseases`` 一病一档目录的绝对路径。"""
        path = Path(self.kb_diseases_dir)
        return path if path.is_absolute() else (REPO_ROOT / path)

    @property
    def kb_class_map_abs(self) -> Path:
        """``kb/class-map.json`` 映射表的绝对路径。"""
        path = Path(self.kb_class_map_path)
        return path if path.is_absolute() else (REPO_ROOT / path)

    @property
    def faiss_index_path(self) -> Path:
        """``kb/index`` FAISS 索引目录的绝对路径。"""
        path = Path(self.faiss_index_dir)
        return path if path.is_absolute() else (REPO_ROOT / path)

    @property
    def ml_exports_path(self) -> Path:
        """``ml/exports`` 模型权重目录的绝对路径（模型热切换持久化落点）。"""
        return REPO_ROOT / "ml" / "exports"

    @property
    def active_model_file(self) -> Path:
        """当前生效 YOLO 权重名的持久化文件（``ml/exports/active_model.json``）。

        team-lead 裁决：模型热切换**持久化到该 JSON 文件**（不进 DB、不加表），
        重启后仍生效；文件缺失时回退 ``YOLO_WEIGHTS_PATH`` 默认权重。
        """
        return self.ml_exports_path / "active_model.json"

    @property
    def is_prod(self) -> bool:
        """是否生产环境。"""
        return self.app_env.lower() in {"prod", "production"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取配置单例（避免重复解析 .env）。"""
    return Settings()


# 模块级单例：全项目统一从此处引用
settings: Settings = get_settings()
