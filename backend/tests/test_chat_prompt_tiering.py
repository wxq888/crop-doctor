# -*- coding: utf-8 -*-
"""系统提示词「分档策略」回归测试（提示词放宽改造，2025 QA 裁决）。

背景：旧 SYSTEM_PROMPT 第 1 条「只依据【参考资料】回答，否则拒答」把**一切**非知识库
问题（问候 / 闲聊 / 常识 / 数学）都压成「知识库暂无相关权威资料」——用户实测「1+1 等于
多少」也被拒。改造为**分档**：

- 植保相关问题：仍严守知识库红线（不编造农药 / 剂量 / 安全间隔期，病毒病不荐杀菌剂等）；
- 一般问题：正常自然回答，不受【参考资料】限制。

本文件用**桩 LLM** 验证（不触真实 API）：
1. 一般问题 → 桩正文原样下发，**不得**混入拒答文案（旧版回归防线）；
2. 植保 + 有资料 → 引用编号规则仍在（[1] 标注约束对植保回答生效）；
3. 植保 + 无资料 → 拒答话术仍在提示词中；用户提示词注入「（无）」参考资料；
4. 红线原文回归：反编造四条（农药/剂量/安全间隔期、病毒病、检疫性、杀螨剂）逐字保留。

说明：桩 LLM 只能证明「正文 = 桩产出、meta 契约不回归」；提示词对真实模型行为的约束
由 SYSTEM_PROMPT 内容断言 + 真实 LLM 三条实测（见交付报告）共同覆盖。
"""
import json

import pytest

from app.api.v1.chat import SYSTEM_PROMPT
from app.core.config import settings
from tests.conftest import auth_headers

BASE = "/api/v1/chat"


# ============================================================
# 工具与桩
# ============================================================
def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """解析 SSE 报文 → ``[(event, data_dict), ...]``；忽略心跳注释帧。"""
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


def _joined_deltas(text: str) -> str:
    """拼接所有 delta 帧文本。"""
    return "".join(d.get("text", "") for n, d in _parse_sse(text) if n == "delta")


class _ScriptedLLM:
    """脚本化 LLM 桩：按收到的 messages 逐字产出脚本 token，并记录 messages 供断言。"""

    is_configured = True

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.last_messages: list[dict] | None = None

    async def stream_chat(self, messages, *, temperature=None, max_tokens=None):  # noqa: ANN001
        self.last_messages = messages
        for token in self.tokens:
            yield token


class _FakeChunk:
    """最小 ``RetrievedChunk`` 替身（番茄晚疫病资料）。"""

    doc_slug = "tomato-late-blight"
    doc_db_id = 1
    title = "番茄晚疫病"
    class_name = "Tomato___Late_blight"
    crop_cn = "番茄"
    category = "卵菌"
    section = "四、防治方法"
    text = "发病初期喷施保护性杀菌剂，严格按农药标签使用、遵守安全间隔期。"
    score = 0.9
    source_path = "kb/diseases/tomato-late-blight.md"

    def to_citation(self) -> dict:
        return {
            "doc_id": self.doc_slug,
            "title": f"{self.title}·{self.section}",
            "snippet": self.text[:120].replace("\n", " "),
        }


class _SearchResult:
    def __init__(self, chunks: list, scope_miss: bool = False, crop_scope: str | None = None) -> None:
        self.chunks = chunks
        self.scope_miss = scope_miss
        self.crop_scope = crop_scope


def _install_rag(monkeypatch, chunks: list) -> None:
    """把检索替换为可控桩（新契约 SearchResult）。"""
    monkeypatch.setattr(
        "app.api.v1.chat._load_rag",
        lambda: type("R", (), {"search": staticmethod(lambda q, top_k=None, crop=None: _SearchResult(chunks))})(),
    )


@pytest.fixture(autouse=True)
def _no_llm_key(monkeypatch):
    """默认清空 key（桩用例会以 monkeypatch llm_service 覆盖，降级分支不触真实 API）。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "")


@pytest.fixture(autouse=True)
def _empty_rag(monkeypatch):
    """默认空检索（等价空知识库）；需要资料的用例用 _install_rag 覆盖。"""
    monkeypatch.setattr("app.api.v1.chat._load_rag", lambda: None)


# ============================================================
# 用例 1：一般问题不再被拒答文案压制
# ============================================================
def test_general_question_answered_normally(client, make_user, monkeypatch) -> None:
    """「1+1 等于多少」：桩返回 2 → 正文含 2，且**不含**旧版一刀切拒答文案。"""
    fake = _ScriptedLLM(["2"])
    monkeypatch.setattr("app.api.v1.chat.llm_service", fake)

    token, _ = make_user("tier_general")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "你先告诉我1+1等于多少？"})
    assert resp.status_code == 200, resp.text

    names = [n for n, _ in _parse_sse(resp.text)]
    assert names[0] == "meta"
    assert names[-1] == "done"  # 正常流式完成，非降级 error 帧

    body = _joined_deltas(resp.text)
    assert "2" in body, f"一般问题应正常回答，实际正文：{body}"
    assert "知识库暂无相关权威资料" not in body, "一般问题不得被拒答文案压制（旧版回归防线）"

    # 提示词分档：system 首帧含「先判断用户问题的类型」，且旧一刀切规则已移除
    system_content = fake.last_messages[0]["content"]
    assert "先判断用户问题的类型" in system_content
    assert "与植保无关的一般问题" in system_content
    assert "问候、闲聊、简单常识、数学" in system_content
    # 旧版原句必须彻底消失
    assert "只依据下方【参考资料】回答；参考资料未覆盖的内容，回答「知识库暂无相关权威资料" not in system_content


# ============================================================
# 用例 2：植保 + 有资料 → 引用编号约束仍在
# ============================================================
def test_plant_protection_with_refs_keeps_citation_rule(client, make_user, monkeypatch) -> None:
    """植保问题且有资料命中：桩正文带 [1] 原样下发；提示词保留「结尾标注参考资料编号」。"""
    _install_rag(monkeypatch, [_FakeChunk()])
    fake = _ScriptedLLM(["1. 发病初期喷施杀菌剂 [1]"])
    monkeypatch.setattr("app.api.v1.chat.llm_service", fake)

    token, _ = make_user("tier_plant_refs")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "番茄晚疫病怎么防治"})
    assert resp.status_code == 200, resp.text

    names = [n for n, _ in _parse_sse(resp.text)]
    assert names[-1] == "done"

    body = _joined_deltas(resp.text)
    assert "[1]" in body, f"植保回答应保留引用编号，实际正文：{body}"

    # 提示词：植保回答的引用规则仍在（且明确「一般问题」豁免）
    system_content = fake.last_messages[0]["content"]
    assert "结尾用 [1][2] 标注所引用的参考资料编号" in system_content
    assert "一般问题正常回答即可" in system_content

    # meta 契约不回归：citations 与检索一致
    meta = _parse_sse(resp.text)[0][1]
    assert meta["degraded"] is False
    assert meta["kb_scope_miss"] is False
    assert len(meta["citations"]) == 1
    assert meta["citations"][0]["doc_id"] == "tomato-late-blight"


# ============================================================
# 用例 3：植保 + 无资料 → 拒答话术仍在、参考资料注入「（无）」
# ============================================================
def test_plant_protection_no_refs_refusal_text_kept(client, make_user, monkeypatch) -> None:
    """植保问题但知识库未覆盖：拒答话术保留在提示词中；user 提示词注入「（无）」；
    桩按提示词返回拒答正文时不得携带任何药剂名。"""
    fake = _ScriptedLLM(
        ["知识库暂无相关权威资料，建议咨询当地植保站。一般可加强田间通风降湿，避免盲目用药。"]
    )
    monkeypatch.setattr("app.api.v1.chat.llm_service", fake)

    token, _ = make_user("tier_plant_no_ref")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "水稻稻瘟病用什么药"})
    assert resp.status_code == 200, resp.text
    assert _parse_sse(resp.text)[-1][0] == "done"

    body = _joined_deltas(resp.text)
    assert "知识库暂无相关权威资料" in body, "植保无资料场景的拒答话术必须保留"

    # user 提示词：无命中时参考资料为「（无）」
    user_content = fake.last_messages[-1]["content"]
    assert "【参考资料】\n（无）" in user_content

    # meta：无引用、非降级
    meta = _parse_sse(resp.text)[0][1]
    assert meta["citations"] == []
    assert meta["degraded"] is False


# ============================================================
# 用例 4：反编造红线原文回归（QA 最认可的答辩设计点，一字不动）
# ============================================================
def test_anti_fabrication_redlines_verbatim() -> None:
    """SYSTEM_PROMPT 反编造四条红线**逐字保留**，分档放宽不得波及植保硬约束。"""
    # 第 2 条：药剂必须来自资料
    assert (
        "2. 严禁编造农药名称、剂量、安全间隔期；凡涉及药剂，必须来自参考资料，"
        "并提示「严格按农药标签使用、遵守安全间隔期」。" in SYSTEM_PROMPT
    )
    # 第 3 条：病毒病不荐杀菌剂
    assert (
        "3. 病毒病不得推荐杀菌剂（防治以防控传播媒介、抗病品种、拔除病株为主）。" in SYSTEM_PROMPT
    )
    # 第 4 条：检疫性病害不荐治疗药剂
    assert (
        "4. 检疫性病害（如柑橘黄龙病）不得推荐治疗药剂（防治以防控媒介、清除病株、苗木检疫为主）。"
        in SYSTEM_PROMPT
    )
    # 第 5 条：虫害杀螨剂逻辑
    assert "5. 虫害（如叶螨）应使用杀螨剂逻辑，并提示轮换用药防抗性。" in SYSTEM_PROMPT
    # 第 1 条植保分档仍含「严禁编造农药名称、剂量、安全间隔期」
    assert "但严禁编造农药名称、剂量、安全间隔期" in SYSTEM_PROMPT
