# -*- coding: utf-8 -*-
"""API v1 路由汇总（条件挂载）。

设计依据：``docs/impl-pc-admin-v1.md`` §1.3。

并行开发期存在「模块文件尚未落地」的窗口；若此处硬 ``import`` 会导致整个应用
启动失败。故改为**条件导入**：模块未落地时仅打 warning 跳过，应用照常启动；
各模块工程师只需新建自己的文件即可自动挂载，无需改动本文件。

注意：仅当 ``ModuleNotFoundError`` 指向**目标模块本身**时才跳过；
若目标模块内部依赖缺失（``exc.name`` 不是该模块），说明是真错误，继续向上抛。
"""
from importlib import import_module

from fastapi import APIRouter
from loguru import logger

api_router = APIRouter()

# (模块名, 前缀, 标签) —— 与 architecture.md §3 端点组一致
_MODULES: list[tuple[str, str, str]] = [
    ("auth", "/auth", "认证"),
    ("detection", "/detection", "检测"),
    ("weather", "/weather", "天气"),
    ("chat", "/chat", "问诊"),
    ("knowledge", "/knowledge", "知识库"),  # 门户（需登录，与 H5 一致）
    ("warning", "/warning", "预警"),  # H5 + PC 规则
    ("feedback", "/feedback", "反馈"),  # H5 工单
    ("admin", "/admin", "管理"),  # 统计/全局检测/用户/模型
    ("monitor", "/admin", "监控"),  # /admin/ws/monitor
]

# 模块内额外 admin 子路由（避免与上面的前缀重复挂载）
_EXTRA: list[tuple[str, str, str, str]] = [  # (module, attr, prefix, tag)
    ("feedback", "admin_router", "/admin/feedback", "工单管理"),
    ("knowledge", "admin_router", "/admin/knowledge", "知识库管理"),
]


def _is_missing_target(exc: ModuleNotFoundError, name: str) -> bool:
    """判断 ``ModuleNotFoundError`` 是否为「目标模块自身未落地」。

    ``exc.name`` 指向缺失的那一层模块：
    - 等于 ``app.api.v1.<name>`` → 目标模块文件不存在，可安全跳过；
    - 其它值（如目标模块内部 import 的缺失）→ 真错误，不可吞。
    """
    return exc.name == f"app.api.v1.{name}"


for _name, _prefix, _tag in _MODULES:
    try:
        _mod = import_module(f"app.api.v1.{_name}")
        api_router.include_router(_mod.router, prefix=_prefix, tags=[_tag])
    except ModuleNotFoundError as exc:
        if not _is_missing_target(exc, _name):  # 内部依赖缺失 → 真错误，向上抛
            raise
        logger.warning(f"路由模块暂未落地，跳过：{_name}")

for _name, _attr, _prefix, _tag in _EXTRA:
    try:
        _mod = import_module(f"app.api.v1.{_name}")
        _sub = getattr(_mod, _attr, None)
        if _sub is not None:
            api_router.include_router(_sub, prefix=_prefix, tags=[_tag])
    except ModuleNotFoundError as exc:
        if not _is_missing_target(exc, _name):
            raise
        logger.warning(f"子路由暂未落地，跳过：{_name}.{_attr}")

__all__ = ["api_router"]
