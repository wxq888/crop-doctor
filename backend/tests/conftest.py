# -*- coding: utf-8 -*-
"""pytest 公共夹具：内存 SQLite + TestClient + 依赖覆写 + 上传目录隔离。

关键隔离点（QA 补充，修复"测试污染仓库 backend/uploads/"问题）：
- **数据库**：每个测试用独立内存 SQLite（``StaticPool`` 保证同一内存库被所有
  连接共享），并通过 ``dependency_overrides`` 覆写 ``get_db``；同时开启
  ``PRAGMA foreign_keys=ON``，让 ``ON DELETE CASCADE`` 生效（与 MySQL 行为一致）。
- **上传目录**：把 ``settings.upload_dir`` 指向 ``tmp_path`` 下的临时目录，
  保证 ``pytest`` 跑完不在仓库 ``backend/uploads/`` 残留任何文件。
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 保证可 import app 包
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: E402,F401  登记全部模型
from app.core.config import settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import yolo_infer  # noqa: E402
from app.services.yolo_infer import DetBox, DetectionResult  # noqa: E402


# ============================================================
# 造图工具（供各测试模块 import 复用）
# ============================================================
def jpeg_bytes(width: int = 64, height: int = 64, color: tuple = (40, 140, 70)) -> bytes:
    """生成一张可解码的 JPEG 字节流。"""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = color
    ok, buf = cv2.imencode(".jpg", img)
    assert ok, "JPEG 编码失败"
    return buf.tobytes()


def png_bytes(width: int = 64, height: int = 64, color: tuple = (40, 140, 70)) -> bytes:
    """生成一张可解码的 PNG 字节流。"""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = color
    ok, buf = cv2.imencode(".png", img)
    assert ok, "PNG 编码失败"
    return buf.tobytes()


def webp_bytes(width: int = 64, height: int = 64, color: tuple = (40, 140, 70)) -> bytes | None:
    """生成一张可解码的 WEBP 字节流；当前 OpenCV 不支持时返回 ``None``。"""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = color
    ok, buf = cv2.imencode(".webp", img)
    return buf.tobytes() if ok else None


def auth_headers(token: str) -> dict:
    """构造 Bearer 头。"""
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# 数据库夹具
# ============================================================
@pytest.fixture
def engine():
    """每个测试独立的内存 SQLite 引擎（开启外键约束）。"""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _enable_fk(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def db_session(engine):
    """测试用数据库会话。"""
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    session = testing_session()
    try:
        yield session
    finally:
        session.close()


# ============================================================
# 上传目录隔离夹具（核心修复：测试不得写真实 backend/uploads/）
# ============================================================
@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """把 ``settings.upload_dir`` 指向临时目录，保证测试不污染仓库上传目录。"""
    root = tmp_path / "uploads"
    for sub in ("images", "annotated", "gradcam"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "upload_dir", str(root))
    return root


# ============================================================
# 共享 Redis 天气缓存清理（autouse）
# ============================================================
@pytest.fixture(autouse=True)
def _clear_weather_cache():
    """每个用例前后清掉共享 Redis 的 ``weather:*`` 键。

    背景：天气服务**先读 Redis 缓存**再决定是否降级。若缓存中残留真实调用或桩数据写入的
    ``weather:now:<loc>`` / ``weather:forecast:<loc>:<days>``，断言「WEATHER_API_KEY 为空应降级」
    的用例（test_warning / test_weather_degraded）会拿到缓存命中而 ``degraded=False`` → 假失败。
    该问题此前多次污染全量跑，这里统一在夹具层堵住（Redis 不可用时静默跳过，不影响用例）。
    """

    def _clear() -> None:
        try:
            import redis as _redis

            r = _redis.Redis.from_url(settings.redis_url)
            keys = list(r.scan_iter("weather:*"))
            if keys:
                r.delete(*keys)
            r.close()
        except Exception:  # noqa: BLE001 —— Redis 不可用不应让用例失败
            pass

    _clear()
    yield
    _clear()


# ============================================================
# 应用客户端夹具
# ============================================================
@pytest.fixture
def client(db_session, upload_dir, monkeypatch):
    """TestClient：覆写 get_db 指向内存库、隔离上传目录、默认禁用 Grad-CAM 与天气外部调用。"""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "gradcam_enabled", False)
    # 默认清空天气密钥，避免测试误发外网请求；需要时由用例自行覆写
    monkeypatch.setattr(settings, "weather_api_key", "")
    # 禁用预警定时刷新调度器：TestClient lifespan 会启动后台调度线程（首轮延迟 60s），
    # 而monkeypatch 为函数级、测试间隙还原 —— 调度线程在长测试套件运行到 60s+ 时会读到
    # 真实 WEATHER_API_KEY 拉取真预报并写共享 Redis（weather:forecast:*），
    # 污染 test_warning 的「空 key 应降级」用例（degraded=False 假失败）。
    monkeypatch.setattr(settings, "warning_enabled", False)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ============================================================
# 用户 / 检测桩夹具
# ============================================================
@pytest.fixture
def make_user(client):
    """辅助夹具：注册并登录一个用户，返回 (token, user_dict)。"""

    def _make(username: str, password: str = "secret123", nickname: str | None = None) -> tuple[str, dict]:
        client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": password, "nickname": nickname},
        )
        resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        body = resp.json()
        return body["data"]["access_token"], body["data"]["user"]

    return _make


@pytest.fixture
def stub_infer(monkeypatch):
    """返回工厂：把 ``detector.infer`` 替换为确定性桩，可控框数 / 面积占比 / 类别名。"""

    def _install(
        spot_count: int = 1,
        area_ratio: float = 0.02,
        label: str = "Apple___Apple_scab",
        top_conf: float = 0.93,
    ):
        def fake_infer(image_bgr, conf=None):  # noqa: ANN001
            if spot_count <= 0:
                return DetectionResult(
                    boxes=[],
                    top_label=None,
                    top_conf=None,
                    spot_count=0,
                    area_ratio=0.0,
                    annotated_bgr=image_bgr.copy(),
                )
            boxes = [
                DetBox(
                    cls_id=i,
                    label=label if i == 0 else f"Other___cls{i}",
                    conf=max(0.0, top_conf - i * 0.01),
                    bbox=[2 + i, 2, 30 + i, 30],
                )
                for i in range(spot_count)
            ]
            return DetectionResult(
                boxes=boxes,
                top_label=boxes[0].label,
                top_conf=boxes[0].conf,
                spot_count=len(boxes),
                area_ratio=area_ratio,
                annotated_bgr=image_bgr.copy(),
            )

        monkeypatch.setattr(yolo_infer.detector, "infer", fake_infer)
        return fake_infer

    return _install


@pytest.fixture
def stub_gradcam(monkeypatch):
    """把后台 Grad-CAM 任务替换为 no-op，保证响应确定性。"""
    monkeypatch.setattr("app.api.v1.detection.run_gradcam_job", lambda record_id: None)


@pytest.fixture
def create_record(client, stub_infer, stub_gradcam):
    """返回工厂：上传一张（桩推理的）图片，返回创建响应的 ``data``。"""

    def _create(token: str, spot_count: int = 1, area_ratio: float = 0.02,
                label: str = "Apple___Apple_scab", location: str | None = None) -> dict:
        stub_infer(spot_count=spot_count, area_ratio=area_ratio, label=label)
        data = {"location": location} if location is not None else None
        resp = client.post(
            "/api/v1/detection/image",
            headers=auth_headers(token),
            files={"file": ("leaf.jpg", jpeg_bytes(), "image/jpeg")},
            data=data,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    return _create


def count_upload_files(root: Path) -> int:
    """统计上传目录（递归）下的文件数，用于断言测试不落盘到真实目录。"""
    return sum(1 for p in Path(root).rglob("*") if p.is_file())
