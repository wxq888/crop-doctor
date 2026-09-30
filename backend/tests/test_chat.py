# -*- coding: utf-8 -*-
"""chat 问诊模块测试：会话 CRUD / SSE 流式 / 降级 / 检测上下文注入 / 数据隔离。

要点：
- **RAG 静默**：``_load_rag`` 被替换为返回 ``None``，等价于「空知识库」，保证用例确定且不加载模型。
- **LLM 桩**：分别覆盖「未配 key 降级」「正常流式」「流式中断」三条分支。
- **数据隔离红线**：用户 A/B 交叉访问会话/消息/发消息/删除，一律 404 / 4001。
"""
import json

import pytest

from app.core.config import settings
from app.services.llm import LLMRateLimitError, LLMService, LLMStreamError
from tests.conftest import auth_headers

BASE = "/api/v1/chat"


# ============================================================
# 工具
# ============================================================
def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """解析 SSE 报文 → ``[(event, data_dict), ...]``；忽略注释帧（心跳）。"""
    events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block or block.startswith(":"):
            continue
        event: str | None = None
        data: str | None = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if event is not None and data is not None:
            events.append((event, json.loads(data)))
    return events


def _event_names(text: str) -> list[str]:
    """仅取事件名序列。"""
    return [name for name, _ in _parse_sse(text)]


def _joined_deltas(text: str) -> str:
    """拼接所有 delta 帧文本。"""
    return "".join(data.get("text", "") for name, data in _parse_sse(text) if name == "delta")


@pytest.fixture(autouse=True)
def _empty_rag(monkeypatch):
    """把所有检索降级为空（等价空知识库），用例确定且不触发模型加载。"""
    monkeypatch.setattr("app.api.v1.chat._load_rag", lambda: None)


@pytest.fixture(autouse=True)
def _no_llm_key(monkeypatch):
    """默认清空 DEEPSEEK_API_KEY，走降级分支；需要时用例覆盖为桩。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "")


class _OkLLM:
    """正常流式的 LLM 桩：记录收到的 messages，逐字产出。"""

    is_configured = True

    def __init__(self, tokens: list[str] | None = None) -> None:
        self.tokens = tokens or ["番茄", "晚疫病", "防治", "方法"]
        self.last_messages: list[dict] | None = None

    async def stream_chat(self, messages, *, temperature=None, max_tokens=None):  # noqa: ANN001
        self.last_messages = messages
        for token in self.tokens:
            yield token


class _ErrLLM:
    """中途失败的 LLM 桩：先产出部分文本，再抛 LLMStreamError。"""

    is_configured = True

    def __init__(self) -> None:
        self.last_messages: list[dict] | None = None

    async def stream_chat(self, messages, *, temperature=None, max_tokens=None):  # noqa: ANN001
        self.last_messages = messages
        yield "部分"
        raise LLMStreamError("模拟流式中断")


class _RateLimitLLM:
    """模拟 429 限流：进入流式即抛 LLMRateLimitError。"""

    is_configured = True

    async def stream_chat(self, messages, *, temperature=None, max_tokens=None):  # noqa: ANN001
        if False:  # 使其成为 async generator（不实际产出）
            yield ""
        raise LLMRateLimitError("模拟 429 限流")


class _EmptyLLM:
    """模拟「流式结束但零 content」：一帧都不产出（如 reasoning_content 吃光 token）。"""

    is_configured = True

    async def stream_chat(self, messages, *, temperature=None, max_tokens=None):  # noqa: ANN001
        if False:
            yield ""


class _FakeChunk:
    """模拟 ``RetrievedChunk``。"""

    def __init__(self, title: str, section: str, text: str, *, doc_slug: str = "slug") -> None:
        self.doc_slug = doc_slug
        self.title = title
        self.section = section
        self.text = text
        self.class_name = "Tomato___Late_blight"
        self.crop_cn = "番茄"
        self.category = "卵菌"
        self.score = 0.9
        self.source_path = None

    def to_citation(self) -> dict:
        return {
            "doc_id": self.doc_slug,
            "title": f"{self.title}·{self.section}",
            "snippet": self.text[:120],
        }


class _SearchResult:
    """模拟 A 的新 ``SearchResult``。"""

    def __init__(self, chunks: list, scope_miss: bool = False, crop_scope: str | None = None) -> None:
        self.chunks = chunks
        self.scope_miss = scope_miss
        self.crop_scope = crop_scope


class _NewRag:
    """模拟 A 的**新契约**：``search(query, top_k=None, crop=None) -> SearchResult``。"""

    def __init__(self, chunks: list | None = None, scope_miss: bool = False, crop_scope: str | None = None) -> None:
        self._chunks = chunks or []
        self._scope_miss = scope_miss
        self._crop_scope = crop_scope
        self.calls: list[dict] = []

    def search(self, query: str, top_k=None, crop=None):  # noqa: ANN001
        self.calls.append({"query": query, "crop": crop})
        return _SearchResult(self._chunks, self._scope_miss, self._crop_scope)


class _OldRag:
    """模拟**旧契约**：``search(query, top_k=None, class_name=None, min_score=None) -> list``。"""

    def __init__(self, chunks: list | None = None) -> None:
        self._chunks = chunks or []
        self.calls: list[dict] = []

    def search(self, query: str, top_k=None, class_name=None, min_score=None):  # noqa: ANN001
        self.calls.append({"query": query, "class_name": class_name})
        return list(self._chunks)


def _create_session(client, token, title: str | None = "会话", detection_id: int | None = None) -> int:
    """建会话并返回 id。"""
    payload: dict = {}
    if title is not None:
        payload["title"] = title
    if detection_id is not None:
        payload["detection_id"] = detection_id
    resp = client.post(f"{BASE}/sessions", headers=auth_headers(token), json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    return body["data"]["id"]


# ============================================================
# 会话 CRUD
# ============================================================
def test_create_and_list_sessions(client, make_user) -> None:
    """建会话 + 列表：仅见本人会话，时间带 Z。"""
    token, _ = make_user("chat_alice")
    sid = _create_session(client, token, title="我的第一问")

    body = client.get(f"{BASE}/sessions", headers=auth_headers(token)).json()
    assert body["code"] == 0
    assert body["data"]["total"] == 1
    item = body["data"]["items"][0]
    assert item["id"] == sid
    assert item["title"] == "我的第一问"
    assert item["created_at"].endswith("Z")
    assert item["updated_at"].endswith("Z")


def test_create_session_with_detection_id(client, make_user, create_record) -> None:
    """带 detection_id 建会话：详情返回检测上下文卡片数据。"""
    token, _ = make_user("chat_det_ref")
    rec = create_record(token, label="Tomato___Late_blight", spot_count=6, area_ratio=0.2)
    sid = _create_session(client, token, title="检测会话", detection_id=rec["id"])

    detail = client.get(f"{BASE}/sessions/{sid}", headers=auth_headers(token)).json()["data"]
    assert detail["detection_id"] == rec["id"]
    assert detail["message_count"] == 0
    ctx = detail["detection_context"]
    assert ctx["detection_id"] == rec["id"]
    assert ctx["class_name"] == "Tomato___Late_blight"
    assert ctx["severity_level"] == 3
    assert ctx["severity_label"] == "严重"


def test_create_session_with_other_users_detection_forbidden(client, make_user, create_record) -> None:
    """引用他人检测记录建会话 → 404 / 4001。"""
    token_a, _ = make_user("chat_ref_a")
    token_b, _ = make_user("chat_ref_b")
    rec_b = create_record(token_b, label="Tomato___Late_blight")

    resp = client.post(
        f"{BASE}/sessions",
        headers=auth_headers(token_a),
        json={"title": "越权", "detection_id": rec_b["id"]},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == 4001


def test_delete_session_cascades_messages(client, make_user) -> None:
    """删会话：消息级联删除，之后取会话/消息均 404 / 4001。"""
    token, _ = make_user("chat_del")
    sid = _create_session(client, token)
    client.post(f"{BASE}/sessions/{sid}/messages", headers=auth_headers(token), json={"question": "你好"})

    assert client.delete(f"{BASE}/sessions/{sid}", headers=auth_headers(token)).status_code == 200
    assert client.get(f"{BASE}/sessions/{sid}", headers=auth_headers(token)).status_code == 404
    assert client.get(f"{BASE}/sessions/{sid}/messages", headers=auth_headers(token)).status_code == 404

    listing = client.get(f"{BASE}/sessions", headers=auth_headers(token)).json()["data"]
    assert listing["total"] == 0


# ============================================================
# SSE：降级（未配 key）
# ============================================================
def test_ask_degraded_no_key_sse(client, make_user) -> None:
    """未配 key：HTTP 200 + SSE 正常流，事件序列 meta → delta… → error(4002)。"""
    token, _ = make_user("chat_deg")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "番茄叶子发黄怎么办"})

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    names = _event_names(resp.text)
    assert names[0] == "meta"
    assert names[-1] == "error"
    assert "delta" in names

    events = _parse_sse(resp.text)
    meta = events[0][1]
    assert meta["degraded"] is True
    assert meta["session_id"] > 0
    assert meta["citations"] == []
    last = events[-1][1]
    assert last["code"] == 4002
    assert last["degraded"] is True
    # 无命中 → 固定提示
    assert "DEEPSEEK_API_KEY" in _joined_deltas(resp.text)


def test_ask_degraded_with_detection_context(client, make_user, create_record) -> None:
    """空知识库 + detection_id：回答体现病害类别 / 置信度 / 分级。"""
    token, _ = make_user("chat_ctx_deg")
    rec = create_record(token, label="Tomato___Late_blight", spot_count=6, area_ratio=0.2)

    resp = client.post(
        f"{BASE}/ask",
        headers=auth_headers(token),
        json={"question": "这个病害怎么防治", "detection_id": rec["id"]},
    )
    assert resp.status_code == 200, resp.text
    text = _joined_deltas(resp.text)
    # 病害类别（class-map 就位时为中文，缺失时回退原始类名）
    assert ("番茄" in text or "Tomato" in text)
    assert ("晚疫病" in text or "Late_blight" in text)
    assert "93%" in text  # 置信度（stub_infer 默认 top_conf=0.93）
    assert "严重" in text  # 分级标签

    # 自动建的会话已关联检测记录
    sid = _parse_sse(resp.text)[0][1]["session_id"]
    detail = client.get(f"{BASE}/sessions/{sid}", headers=auth_headers(token)).json()["data"]
    assert detail["detection_id"] == rec["id"]


# ============================================================
# SSE：正常流式 / 中断
# ============================================================
def test_stream_success_done(client, make_user, monkeypatch) -> None:
    """已配 LLM：事件序列 meta → delta… → done，assistant 消息落库。"""
    fake = _OkLLM()
    monkeypatch.setattr("app.api.v1.chat.llm_service", fake)

    token, _ = make_user("chat_ok")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "晚疫病怎么防治"})
    assert resp.status_code == 200, resp.text

    names = _event_names(resp.text)
    assert names[0] == "meta"
    assert names[-1] == "done"
    assert _joined_deltas(resp.text) == "番茄晚疫病防治方法"

    done = _parse_sse(resp.text)[-1][1]
    assert done["finish_reason"] == "stop"
    assert done["assistant_message_id"] > 0

    # messages 组装：system 首帧，user 末帧
    assert fake.last_messages[0]["role"] == "system"
    assert fake.last_messages[-1]["role"] == "user"

    # 消息落库：user + assistant 各一条
    sid = _parse_sse(resp.text)[0][1]["session_id"]
    messages = client.get(f"{BASE}/sessions/{sid}/messages", headers=auth_headers(token)).json()["data"]
    assert messages["total"] == 2
    roles = sorted(m["role"] for m in messages["items"])
    assert roles == ["assistant", "user"]


def test_detection_context_injected_into_prompt(client, make_user, create_record, monkeypatch) -> None:
    """检测上下文注入 user 提示词（§5.2 模板）。"""
    fake = _OkLLM()
    monkeypatch.setattr("app.api.v1.chat.llm_service", fake)

    token, _ = make_user("chat_ctx_prompt")
    rec = create_record(token, label="Tomato___Late_blight", spot_count=6, area_ratio=0.2)

    resp = client.post(
        f"{BASE}/ask",
        headers=auth_headers(token),
        json={"question": "怎么防治", "detection_id": rec["id"]},
    )
    assert resp.status_code == 200, resp.text

    prompt = fake.last_messages[-1]["content"]
    assert "【检测上下文】" in prompt
    assert ("番茄" in prompt or "Tomato" in prompt)
    assert ("晚疫病" in prompt or "Late_blight" in prompt)
    assert "93%" in prompt
    assert "严重" in prompt
    assert "【参考资料】" in prompt
    assert "【用户问题】\n怎么防治" in prompt
    # meta 携带 class_filter（原始类名逐字，用于 RAG 软过滤）
    meta = _parse_sse(resp.text)[0][1]
    assert meta["class_filter"] == "Tomato___Late_blight"


def test_stream_midway_error_emits_error_event(client, make_user, monkeypatch) -> None:
    """流式中途异常：推 error 帧并带 code，保留已产出文本，HTTP 200 不裸崩。"""
    fake = _ErrLLM()
    monkeypatch.setattr("app.api.v1.chat.llm_service", fake)

    token, _ = make_user("chat_err")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "测试中断"})
    assert resp.status_code == 200, resp.text

    names = _event_names(resp.text)
    assert names[0] == "meta"
    assert names[-1] == "error"
    assert "部分" in _joined_deltas(resp.text)

    err = _parse_sse(resp.text)[-1][1]
    assert err["code"] == 4002
    assert err["degraded"] is True


def test_rate_limit_degrades_without_crash(client, make_user, monkeypatch) -> None:
    """429 限流：直接降级（不重试、不裸崩），降级回答给出「请求过于频繁」提示。"""
    monkeypatch.setattr("app.api.v1.chat.llm_service", _RateLimitLLM())

    token, _ = make_user("chat_429")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "番茄晚疫病怎么治"})
    assert resp.status_code == 200, resp.text

    events = _parse_sse(resp.text)
    assert events[0][0] == "meta"
    assert events[-1][0] == "error"
    err = events[-1][1]
    assert err["code"] == 4002
    assert "请求过于频繁" in err["message"]

    body = _joined_deltas(resp.text)
    assert "请求过于频繁" in body
    assert "以下为知识库检索原文" not in body  # 限流降级不再拼 KB 原文


def test_empty_content_defense(client, make_user, monkeypatch) -> None:
    """零 content 防御：不静默吐空，推 error 帧给出明确原因，并降级为知识库原文。"""
    monkeypatch.setattr("app.api.v1.chat.llm_service", _EmptyLLM())

    token, _ = make_user("chat_empty_content")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "番茄晚疫病症状"})
    assert resp.status_code == 200, resp.text

    events = _parse_sse(resp.text)
    assert events[0][0] == "meta"
    assert events[-1][0] == "error"
    err = events[-1][1]
    assert err["code"] == 4002
    assert "未返回任何回答内容" in err["message"]
    # 已降级为知识库固定提示（空知识库场景）
    assert "DEEPSEEK_API_KEY" in _joined_deltas(resp.text)


def test_build_kwargs_disables_thinking_and_coerces_temperature(monkeypatch) -> None:
    """约束1/2：关闭思考 → 注入 extra_body 关思考 + temperature 强制 0.6；max_tokens 读到 settings。"""
    monkeypatch.setattr("app.services.llm._llm_disable_thinking", lambda: True)
    monkeypatch.setattr(settings, "llm_temperature", 0.9)  # 故意设非法值

    kwargs = LLMService()._build_kwargs(
        [{"role": "user", "content": "x"}], stream=True, temperature=None, max_tokens=None
    )
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert kwargs["temperature"] == 0.6
    assert kwargs["max_tokens"] == settings.llm_max_tokens  # 读到 .env 的 2048


def test_build_kwargs_thinking_enabled_keeps_temperature(monkeypatch) -> None:
    """开关关闭时：不注入 extra_body，temperature 原样保留。"""
    monkeypatch.setattr("app.services.llm._llm_disable_thinking", lambda: False)
    monkeypatch.setattr(settings, "llm_temperature", 0.9)

    kwargs = LLMService()._build_kwargs(
        [{"role": "user", "content": "x"}], stream=True, temperature=None, max_tokens=None
    )
    assert "extra_body" not in kwargs
    assert kwargs["temperature"] == 0.9


# ============================================================
# RAG 契约适配（新 SearchResult / 旧 list 兼容 / scope_miss / 引用一致性）
# ============================================================
def test_new_contract_crop_passed_and_citations_consistent(client, make_user, create_record, monkeypatch) -> None:
    """新契约：传 crop=（由 class_name 派生）+ 读 .chunks；降级正文引用数 == meta.citations 数。"""
    fake = _NewRag(
        chunks=[
            _FakeChunk("番茄晚疫病", "四、防治方法", "正文A"),
            _FakeChunk("番茄晚疫病", "一、病害概述", "正文B"),
            _FakeChunk("番茄早疫病", "四、防治方法", "正文C"),
        ]
    )
    monkeypatch.setattr("app.api.v1.chat._load_rag", lambda: fake)

    token, _ = make_user("chat_new_contract")
    rec = create_record(token, label="Tomato___Late_blight", spot_count=6, area_ratio=0.2)
    resp = client.post(
        f"{BASE}/ask", headers=auth_headers(token), json={"question": "怎么防治", "detection_id": rec["id"]}
    )
    assert resp.status_code == 200, resp.text
    assert fake.calls[-1]["crop"] == "番茄"  # class-map 反查 crop_cn

    meta = _parse_sse(resp.text)[0][1]
    assert meta["kb_scope_miss"] is False
    assert len(meta["citations"]) == 3

    body = _joined_deltas(resp.text)
    for n in ("[1]", "[2]", "[3]"):
        assert n in body
    assert "[4]" not in body  # 引用数与 citations 数一致（无悬空引用）


def test_scope_miss_propagated_and_body_honest(client, make_user, create_record, monkeypatch) -> None:
    """scope_miss=True：meta.kb_scope_miss=True，降级正文不再吐别的作物资料，而是明确告知库外。"""
    fake = _NewRag(chunks=[], scope_miss=True, crop_scope="苹果")
    monkeypatch.setattr("app.api.v1.chat._load_rag", lambda: fake)

    token, _ = make_user("chat_scope_miss")
    rec = create_record(token, label="Tomato___Late_blight", spot_count=1, area_ratio=0.02)
    resp = client.post(
        f"{BASE}/ask", headers=auth_headers(token), json={"question": "怎么防治", "detection_id": rec["id"]}
    )
    assert resp.status_code == 200, resp.text
    meta = _parse_sse(resp.text)[0][1]
    assert meta["kb_scope_miss"] is True
    assert meta["citations"] == []

    body = _joined_deltas(resp.text)
    assert "知识库暂无【苹果】的病害资料" in body
    assert "以下为知识库检索原文" not in body  # 不再吐原文


def test_old_contract_list_tolerated(client, make_user, monkeypatch) -> None:
    """并行窗口：A 仍返回 list 时，用 getattr 兜住，检索照常生效、kb_scope_miss 默认 False。"""
    fake = _OldRag(chunks=[_FakeChunk("番茄晚疫病", "二、症状识别", "正文X")])
    monkeypatch.setattr("app.api.v1.chat._load_rag", lambda: fake)

    token, _ = make_user("chat_old_contract")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "番茄病害"})
    assert resp.status_code == 200, resp.text

    meta = _parse_sse(resp.text)[0][1]
    assert meta["kb_scope_miss"] is False
    assert len(meta["citations"]) == 1
    assert "正文X" in _joined_deltas(resp.text)


def test_meta_carries_crop_scope_when_present(client, make_user, monkeypatch) -> None:
    """设计文档 §3.2 v1.1：检索生效了作物范围时，meta.crop_scope 原样回显。"""
    fake = _NewRag(
        chunks=[_FakeChunk("番茄晚疫病", "四、防治方法", "正文Y")],
        crop_scope="番茄",
    )
    monkeypatch.setattr("app.api.v1.chat._load_rag", lambda: fake)

    token, _ = make_user("chat_crop_scope_on")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "晚疫病怎么防治"})
    assert resp.status_code == 200, resp.text

    meta = _parse_sse(resp.text)[0][1]
    assert meta["crop_scope"] == "番茄"
    assert meta["class_filter"] is None  # 既有字段保持不变（纯新增）
    assert meta["kb_scope_miss"] is False


def test_meta_crop_scope_null_when_absent(client, make_user, monkeypatch) -> None:
    """未生效作物约束（crop_scope=None）时，meta.crop_scope 为 null。"""
    fake = _NewRag(chunks=[_FakeChunk("番茄晚疫病", "一、病害概述", "正文Z")], crop_scope=None)
    monkeypatch.setattr("app.api.v1.chat._load_rag", lambda: fake)

    token, _ = make_user("chat_crop_scope_off")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "晚疫病怎么防治"})
    assert resp.status_code == 200, resp.text

    meta = _parse_sse(resp.text)[0][1]
    assert meta["crop_scope"] is None


def test_meta_crop_scope_null_old_contract(client, make_user, monkeypatch) -> None:
    """旧契约（list 形态，无 crop_scope 属性）：getattr 兜为 None，不抛错、字段仍下发。"""
    fake = _OldRag(chunks=[_FakeChunk("番茄晚疫病", "二、症状识别", "正文W")])
    monkeypatch.setattr("app.api.v1.chat._load_rag", lambda: fake)

    token, _ = make_user("chat_crop_scope_old")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "番茄病害"})
    assert resp.status_code == 200, resp.text

    meta = _parse_sse(resp.text)[0][1]
    assert "crop_scope" in meta
    assert meta["crop_scope"] is None


# ============================================================
# 校验 / 鉴权
# ============================================================
def test_question_boundaries_4003(client, make_user) -> None:
    """问题四边界（空串 / 纯空白 / 500 字 / 501 字）在**两个入口**都返回 400 / 4003。"""
    token, _ = make_user("chat_bounds")

    # /chat/ask：空串 / 纯空白 / 501 字 → 400 / 4003；500 字 → 200
    for bad in ["", "   ", "\t\n ", "好" * 501]:
        resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": bad})
        assert resp.status_code == 400, (bad[:10], resp.text)
        assert resp.json()["code"] == 4003
        assert set(resp.json().keys()) == {"code", "message", "data"}
    assert client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "好" * 500}).status_code == 200

    # /chat/sessions/{id}/messages：同上
    sid = _create_session(client, token)
    for bad in ["", "   ", "好" * 501]:
        resp = client.post(f"{BASE}/sessions/{sid}/messages", headers=auth_headers(token), json={"question": bad})
        assert resp.status_code == 400, (bad[:10], resp.text)
        assert resp.json()["code"] == 4003
    ok_resp = client.post(
        f"{BASE}/sessions/{sid}/messages", headers=auth_headers(token), json={"question": "好" * 500}
    )
    assert ok_resp.status_code == 200
    assert ok_resp.headers["content-type"].startswith("text/event-stream")


def test_requires_auth(client) -> None:
    """无 token → 401 / 1003。"""
    resp = client.get(f"{BASE}/sessions")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1003


# ============================================================
# 数据隔离红线
# ============================================================
def test_session_isolation(client, make_user) -> None:
    """用户 A 的会话对用户 B 不可见；交叉访问会话/消息/发消息/删除一律 404 / 4001。"""
    token_a, _ = make_user("chat_iso_a")
    token_b, _ = make_user("chat_iso_b")
    sid = _create_session(client, token_a, title="A 的会话")
    client.post(f"{BASE}/sessions/{sid}/messages", headers=auth_headers(token_a), json={"question": "A 的问题"})

    # B 的列表为空
    listing_b = client.get(f"{BASE}/sessions", headers=auth_headers(token_b)).json()["data"]
    assert listing_b["total"] == 0
    assert all(item["id"] != sid for item in listing_b["items"])

    def _assert_4001(resp) -> None:
        assert resp.status_code == 404, resp.text
        body = resp.json()
        assert body["code"] == 4001
        assert set(body.keys()) == {"code", "message", "data"}

    _assert_4001(client.get(f"{BASE}/sessions/{sid}", headers=auth_headers(token_b)))
    _assert_4001(client.get(f"{BASE}/sessions/{sid}/messages", headers=auth_headers(token_b)))
    _assert_4001(client.post(f"{BASE}/sessions/{sid}/messages", headers=auth_headers(token_b), json={"question": "探"}))

    # B 试图用 session_id 借用 A 的会话提问
    _assert_4001(client.post(f"{BASE}/ask", headers=auth_headers(token_b), json={"question": "探", "session_id": sid}))

    # B 删除 A 的会话无效，A 的会话与消息安然无恙
    _assert_4001(client.delete(f"{BASE}/sessions/{sid}", headers=auth_headers(token_b)))
    assert client.get(f"{BASE}/sessions/{sid}", headers=auth_headers(token_a)).status_code == 200
    # A 的会话仍含 user + assistant 两条消息（降级路径也落库 assistant）
    assert (
        client.get(f"{BASE}/sessions/{sid}/messages", headers=auth_headers(token_a)).json()["data"]["total"] == 2
    )


def test_nonexistent_session_returns_4001(client, make_user) -> None:
    """不存在的会话 id → 404 / 4001（与越权同码，防探测）。"""
    token, _ = make_user("chat_none")
    assert client.get(f"{BASE}/sessions/99999999", headers=auth_headers(token)).json()["code"] == 4001
    assert client.get(f"{BASE}/sessions/99999999/messages", headers=auth_headers(token)).json()["code"] == 4001
    assert (
        client.post(
            f"{BASE}/sessions/99999999/messages",
            headers=auth_headers(token),
            json={"question": "x"},
        ).json()["code"]
        == 4001
    )
    assert client.delete(f"{BASE}/sessions/99999999", headers=auth_headers(token)).json()["code"] == 4001
