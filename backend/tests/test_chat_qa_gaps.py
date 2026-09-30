# -*- coding: utf-8 -*-
"""QA 独立验证补充用例：chat 的 SSE 报头/降级有命中/边界值契约。

与 ``test_chat.py`` 互补（不重复其已有断言），重点覆盖：
- SSE 响应头契约（§3.2：``text/event-stream`` + ``no-cache`` + ``X-Accel-Buffering: no``）；
- 「未配 LLM 但检索有命中」的降级分支：meta.citations 有值 + 正文逐字来自知识库 + 末帧 error(4002)；
- 问题边界：空串 / 超长 —— 期望 **HTTP 400 / 业务码 4003**（§3.4 用户契约）。

说明：``schemas/chat.py`` 已按 §3.4 裁决**退化为无约束 str**，空/超长改由 handler 层
``_validate_question`` 抛 ``BusinessError(4003, 400)``，故以下两条为常规断言（非 xfail）。
"""
import json

import pytest

from app.core.config import settings
from tests.conftest import auth_headers

BASE = "/api/v1/chat"


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """解析 SSE 报文 → ``[(event, data_dict), ...]``。"""
    events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block or block.startswith(":"):
            continue
        event = data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        if event is not None and data is not None:
            events.append((event, json.loads(data)))
    return events


class _FakeChunk:
    """最小 RetrievedChunk 替身（只需 chat 侧消费的字段 + to_citation）。"""

    def __init__(self, slug: str, title: str) -> None:
        self.i = 0
        self.doc_slug = slug
        self.doc_db_id = 1
        self.title = title
        self.class_name = "Tomato___Late_blight"
        self.crop_cn = "番茄"
        self.category = "卵菌"
        self.section = "二、症状识别"
        self.text = "【番茄】【番茄晚疫病】\n## 二、症状识别\n叶尖叶缘水渍状暗绿斑，湿度大时叶背生白霉。"
        self.score = 0.81
        self.source_path = f"kb/diseases/{slug}.md"

    def to_citation(self) -> dict:
        return {
            "doc_id": self.doc_slug,
            "title": f"{self.title}·{self.section}",
            "snippet": self.text[:120].replace("\n", " "),
        }


@pytest.fixture(autouse=True)
def _no_llm_key(monkeypatch):
    """默认清空 DEEPSEEK_API_KEY，走降级分支。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "")


def test_sse_headers_contract(client, make_user) -> None:
    """SSE 响应头符合 §3.2 冻结契约。"""
    token, _ = make_user("qa_sse_hdr")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "你好"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("x-accel-buffering") == "no"


def test_degraded_with_hits_streams_kb_original(client, make_user, monkeypatch) -> None:
    """未配 LLM 但检索有命中：meta.citations 有值、正文逐字来自知识库、末帧 error(4002)。"""
    monkeypatch.setattr(
        "app.api.v1.chat._load_rag",
        lambda: type("R", (), {"search": staticmethod(lambda q, class_name=None: [_FakeChunk("tomato-late-blight", "番茄晚疫病")])})(),
    )
    token, _ = make_user("qa_deg_hits")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "番茄晚疫病怎么防治"})
    assert resp.status_code == 200, resp.text

    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "error"
    assert events[-1][1]["code"] == 4002
    assert events[0][1]["degraded"] is True
    # meta 携带引用（来自检索结果）
    assert len(events[0][1]["citations"]) == 1
    assert events[0][1]["citations"][0]["doc_id"] == "tomato-late-blight"
    # 降级正文逐字包含知识库原文 + 声明抬头
    text = "".join(d.get("text", "") for n, d in events if n == "delta")
    assert "大模型服务未配置" in text
    assert "叶尖叶缘水渍状暗绿斑" in text


def test_citations_persisted_to_assistant_message(client, make_user, monkeypatch) -> None:
    """降级落库：assistant 消息 citations 与 meta 一致，user 消息 citations 为空。"""
    monkeypatch.setattr(
        "app.api.v1.chat._load_rag",
        lambda: type("R", (), {"search": staticmethod(lambda q, class_name=None: [_FakeChunk("tomato-late-blight", "番茄晚疫病")])})(),
    )
    token, _ = make_user("qa_cit_persist")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "番茄晚疫病怎么防治"})
    sid = _parse_sse(resp.text)[0][1]["session_id"]
    items = client.get(f"{BASE}/sessions/{sid}/messages", headers=auth_headers(token)).json()["data"]["items"]
    by_role = {m["role"]: m for m in items}
    assert by_role["assistant"]["citations"], "assistant 消息应落库引用"
    assert by_role["assistant"]["citations"][0]["doc_id"] == "tomato-late-blight"
    assert by_role["user"]["citations"] is None


def test_empty_string_question_contract(client, make_user) -> None:
    """空串问题：返回 400 / 4003（handler 层校验，§3.4 用户契约）。"""
    token, _ = make_user("qa_empty_q")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": ""})
    assert resp.status_code == 400, f"实际 {resp.status_code}: {resp.text}"
    assert resp.json()["code"] == 4003


def test_overlong_question_contract(client, make_user) -> None:
    """超长问题（501 字）：返回 400 / 4003（handler 层校验，§3.4 用户契约）。"""
    token, _ = make_user("qa_long_q")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "病" * 501})
    assert resp.status_code == 400, f"实际 {resp.status_code}: {resp.text}"
    assert resp.json()["code"] == 4003


def test_exactly_500_chars_is_accepted(client, make_user) -> None:
    """边界内侧：500 字应被接受（HTTP 200）。"""
    token, _ = make_user("qa_500_q")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "病" * 500})
    assert resp.status_code == 200, f"实际 {resp.status_code}: {resp.text}"
