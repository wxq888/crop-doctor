# -*- coding: utf-8 -*-
"""业务异常定义。

``BusinessError`` 携带业务错误码与 HTTP 状态码，由 ``main.py`` 的全局
``exception_handler`` 统一转换为 ``{code, message, data}`` 响应体。
错误码取值见设计文档 §5.3。
"""


class BusinessError(Exception):
    """业务异常基类。

    Args:
        code: 业务错误码（见设计文档 §5.3）。
        message: 面向用户的错误信息。
        http_status: 传输层 HTTP 状态码。
    """

    def __init__(self, code: int, message: str, http_status: int = 400) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class ModelLoadError(BusinessError):
    """模型加载失败（YOLO / ResNet50）。"""

    def __init__(self, message: str = "模型加载失败") -> None:
        super().__init__(code=9000, message=message, http_status=500)


class InferenceError(BusinessError):
    """推理过程异常。"""

    def __init__(self, message: str = "推理失败") -> None:
        super().__init__(code=9000, message=message, http_status=500)


class GradCamDisabledError(BusinessError):
    """Grad-CAM 功能被禁用（``GRADCAM_ENABLED=false``）。"""

    def __init__(self, message: str = "Grad-CAM 功能未启用") -> None:
        super().__init__(code=3001, message=message, http_status=200)


class GradCamError(BusinessError):
    """Grad-CAM 生成失败。"""

    def __init__(self, message: str = "热力图生成失败") -> None:
        super().__init__(code=9000, message=message, http_status=500)


# 常用错误码常量（与设计文档 §5.3 对齐，避免魔法数字散落）
CODE_USERNAME_EXISTS = 1001
CODE_BAD_CREDENTIALS = 1002
CODE_UNAUTHORIZED = 1003
CODE_FORBIDDEN = 1004
CODE_OLD_PASSWORD_WRONG = 1005
CODE_UNSUPPORTED_IMAGE = 2001
CODE_IMAGE_TOO_LARGE = 2002
CODE_NO_DETECTION = 2003
CODE_RECORD_NOT_FOUND = 2004
CODE_WEATHER_DEGRADED = 3001
# ==== chat 问诊模块（4001~4003，见 impl-rag-chat-v1.md §3.4）====
CODE_CHAT_SESSION_NOT_FOUND = 4001  # 会话不存在或无权访问（HTTP 404，防探测）
CODE_LLM_UNAVAILABLE = 4002  # 大模型服务不可用（HTTP 200，已降级为知识库原文）
CODE_BAD_QUESTION = 4003  # 问题为空或超长（HTTP 400）
CODE_INTERNAL = 9000


class ChatSessionNotFoundError(BusinessError):
    """会话不存在或无权访问（统一 4001 / 404，防探测）。"""

    def __init__(self, message: str = "会话不存在或无权访问") -> None:
        super().__init__(code=CODE_CHAT_SESSION_NOT_FOUND, message=message, http_status=404)


class BadQuestionError(BusinessError):
    """问题为空或超长（4003 / 400）。"""

    def __init__(self, message: str = "问题为空或超长") -> None:
        super().__init__(code=CODE_BAD_QUESTION, message=message, http_status=400)


# ============================================================
# 本轮五模块新增错误码（见 docs/impl-pc-admin-v1.md §1.5）
# ============================================================
# ---- warning 预警模块（5001~5002）----
CODE_ALERT_NOT_FOUND = 5001  # 预警记录不存在或无权访问（HTTP 404，防探测）
CODE_RULE_NOT_FOUND = 5002  # 预警规则不存在（HTTP 404）
# ---- feedback 工单模块（6001~6003）----
CODE_TICKET_NOT_FOUND = 6001  # 工单不存在或无权访问（HTTP 404，防探测）
CODE_TICKET_CLOSED = 6002  # 工单已关闭，不可继续回复（HTTP 409）
CODE_TICKET_BAD_STATE = 6003  # 工单状态非法流转（HTTP 409）
# ---- knowledge 知识库模块（7001~7002）----
CODE_KB_DOC_NOT_FOUND = 7001  # 知识文档不存在（HTTP 404）
CODE_KB_DOC_EXISTS = 7002  # 知识文档已存在（slug 冲突，HTTP 409）
# ---- admin 管理模块（8001~8003）----
CODE_USER_NOT_FOUND = 8001  # 用户不存在（HTTP 404）
CODE_USER_OP_FORBIDDEN = 8002  # 不允许的操作（禁用自己 / 禁用最后一个管理员，HTTP 409）
CODE_MODEL_UNAVAILABLE = 8003  # 模型文件不存在或不可用（HTTP 400）


# ---- admin 模块专用异常子类（便于端点内简洁 raise）----
class UserNotFoundError(BusinessError):
    """用户不存在（8001 / 404）。"""

    def __init__(self, message: str = "用户不存在") -> None:
        super().__init__(code=CODE_USER_NOT_FOUND, message=message, http_status=404)


class UserOpForbiddenError(BusinessError):
    """不允许的用户操作（8002 / 409）。"""

    def __init__(self, message: str = "不允许的操作") -> None:
        super().__init__(code=CODE_USER_OP_FORBIDDEN, message=message, http_status=409)


class ModelUnavailableError(BusinessError):
    """模型文件不存在或不可用（8003 / 400）。"""

    def __init__(self, message: str = "模型文件不存在或不可用") -> None:
        super().__init__(code=CODE_MODEL_UNAVAILABLE, message=message, http_status=400)
