# -*- coding: utf-8 -*-
"""终验（Task #12）QA 独立验证补充用例。

本轮变动面（此前无人验证的组合）：
- **A 的审校三态闸门**：``reviewed_by`` 的 ``null`` / ``PENDING:`` / 真实姓名三态，
  ``kb/index/chunks.json`` 的 ``review_status`` 覆盖与一致性，``scripts/ingest_kb.py`` 闸门行为；
- **B 的 Kimi 适配**：``_build_kwargs`` 注入 ``extra_body={"thinking":{"type":"disabled"}}``、
  非 0.6 温度强制纠正并告警、``reasoning_content`` 不串入正文、429 不重试、连接错误重试 1 次、
  HTTP 状态错误不重试；
- **RAG 作物域约束**（P1-1 修复）：库外作物 ``scope_miss=True`` 且**不回退**捞别作物；
- **SSE ``meta`` 契约**：必带字段齐备；``crop_scope`` 契约偏差以 ``xfail`` 如实记录。

设计依据：``docs/impl-rag-chat-v1.md`` §1.4.6 / §3.2 / §5、``docs/impl-backend-v1.md`` §5.3。
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, RateLimitError

from app.core.config import REPO_ROOT, settings
from tests.conftest import auth_headers

# 先导入 rag 模块：其在导入期 setdefault HF_ENDPOINT / HF_HUB_DISABLE_XET
import app.services.rag  # noqa: E402,F401

BASE = "/api/v1/chat"
SCRIPTS_DIR = REPO_ROOT / "scripts"
CLASS_MAP = settings.kb_class_map_abs
CHUNKS = settings.faiss_index_path / "chunks.json"


# ============================================================
# 工具：SSE 解析 / 脚本导入 / 异步驱动
# ============================================================
def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """解析 SSE 报文 → ``[(event, data), ...]``；忽略心跳注释帧。"""
    events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block or block.startswith(":"):
            continue
        event: str | None = None
        data: str | None = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        if event is not None and data is not None:
            events.append((event, json.loads(data)))
    return events


def _load_ingest_module():
    """导入 ``scripts/ingest_kb.py``（其依赖 ``kb_common``，需要 scripts 目录在 sys.path）。"""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import ingest_kb  # noqa: PLC0415

    return ingest_kb


async def _drain(agen) -> list[str]:
    """消费异步生成器，返回全部 token。"""
    return [tok async for tok in agen]


def _collect(svc, messages: list[dict]) -> list[str]:
    """同步驱动 ``LLMService.stream_chat`` 并收集 token。"""
    return asyncio.run(_drain(svc.stream_chat(messages)))


def _expect_error(svc, messages: list[dict], exc_type) -> None:
    """同步驱动到异常，断言异常类型。"""

    async def _run() -> None:
        async for _ in svc.stream_chat(messages):
            pass

    with pytest.raises(exc_type):
        asyncio.run(_run())


# ============================================================
# 一、知识库审校三态（A 的改动复验）
# ============================================================
def _review_state(row: dict) -> str:
    """与 ``kb_common.review_state`` 同义的本地判定（用于独立交叉验证）。"""
    val = row.get("reviewed_by")
    if val is None or not str(val).strip():
        return "unverified"
    if str(val).startswith("PENDING:"):
        return "pending"
    return "verified"


def test_class_map_review_tri_state_distribution() -> None:
    """class-map 三态分布：39 行（含 1 忽略行）；38 篇文档已全部经用户本人审校（verified）。"""
    rows = json.loads(CLASS_MAP.read_text(encoding="utf-8"))
    assert len(rows) == 39, f"应有 39 行，实际 {len(rows)}"

    doc_rows = [r for r in rows if r.get("doc_type") != "ignore"]
    ignore_rows = [r for r in rows if r.get("doc_type") == "ignore"]
    assert len(doc_rows) == 38, f"文档行应为 38，实际 {len(doc_rows)}"
    assert len(ignore_rows) == 1, "应有且仅有 1 行忽略行（Background）"

    states = [_review_state(r) for r in doc_rows]
    assert states.count("verified") == 38, (
        f"用户审校后应 38 篇 verified，实际 {states.count('verified')}"
    )
    assert states.count("pending") == 0, "不应残留 PENDING 态"
    assert states.count("unverified") == 0, "不应存在未审校（null）行"

    # 每篇的 reviewed_by 必须非空、非 PENDING 前缀，且都有审校日期与对应文档
    for r in doc_rows:
        rb = r.get("reviewed_by")
        assert rb and not str(rb).startswith("PENDING:"), (
            f"{r['slug']} 应为真实审校人，实际 {rb!r}"
        )
        assert r.get("reviewed_at"), f"{r['slug']} 缺 reviewed_at"
        assert (settings.kb_diseases_path / f"{r['slug']}.md").exists(), f"{r['slug']} 缺文档"


def test_chunks_review_status_full_coverage_verified() -> None:
    """chunks.json：全部 chunk 都带 review_status 且与 class-map 派生一致（用户审校后应全为 verified）。"""
    if not CHUNKS.exists():
        pytest.skip("kb/index/chunks.json 未构建")
    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    assert chunks, "chunks.json 不应为空"

    missing = [c.get("i") for c in chunks if "review_status" not in c]
    assert not missing, f"以下 chunk 缺 review_status 字段：{missing}"

    # 与 class-map 的派生结果逐条一致（单一事实来源，不漂移）
    by_slug = {r["slug"]: r for r in json.loads(CLASS_MAP.read_text(encoding="utf-8"))}
    for c in chunks:
        row = by_slug.get(c["doc_slug"])
        assert row is not None, f"chunk 的 doc_slug {c['doc_slug']} 不在 class-map 中"
        assert c["review_status"] == _review_state(row), (
            f"{c['doc_slug']} 的 review_status={c['review_status']} 与 class-map 派生不一致"
        )

    # 全覆盖：38 篇文档类（不含忽略行）每篇至少 1 条 chunk
    covered = {c["doc_slug"] for c in chunks}
    expected = {r["slug"] for r in by_slug.values() if r.get("doc_type") != "ignore"}
    uncovered = expected - covered
    assert not uncovered, f"以下文档无任何 chunk：{sorted(uncovered)}"
    assert {c["review_status"] for c in chunks} == {"verified"}, "用户审校后应全为 verified"


def test_review_state_three_states_including_whitespace() -> None:
    """``review_state`` 三态判定：null/空串/纯空白 → unverified；PENDING: → pending；真名 → verified。"""
    kb_common = _load_ingest_module()  # 顺便触发 kb_common 导入
    from kb_common import review_state  # noqa: PLC0415

    assert review_state({"reviewed_by": None}) == "unverified"
    assert review_state({"reviewed_by": ""}) == "unverified"
    assert review_state({"reviewed_by": "   \t "}) == "unverified"
    assert review_state({}) == "unverified"
    assert review_state({"reviewed_by": "PENDING:团队代整理"}) == "pending"
    assert review_state({"reviewed_by": "张三"}) == "verified"
    assert kb_common is not None  # 保持引用，避免 lint 未使用


def test_ingest_gate_rejects_null_reviewed_by(tmp_path) -> None:
    """入库闸门①：``reviewed_by`` 为 null → 拒绝（退出码非 0）。"""
    ingest = _load_ingest_module()
    row = {"slug": "apple-apple-scab", "reviewed_by": None, "sources": [{"grade": "A"}]}
    reason = ingest._validate(row, tmp_path / "x.md", "内容", force=False)
    assert reason is not None and "诚信红线" in reason, f"应拒绝，实际 reason={reason}"


def test_ingest_gate_allows_pending_but_grade_a_still_enforced(tmp_path) -> None:
    """入库闸门②：``PENDING:`` 允许入库，但 **A 级来源红线照旧强制**。"""
    ingest = _load_ingest_module()

    # PENDING + 有 A 级来源 + 文档存在 → 通过（reason=None）
    md = settings.kb_diseases_path / "tomato-late-blight.md"
    ok_row = {"slug": "tomato-late-blight", "reviewed_by": "PENDING:团队代整理", "sources": [{"grade": "A"}]}
    assert ingest._validate(ok_row, md, md.read_text(encoding="utf-8"), force=False) is None

    # PENDING + 仅 B/C 级来源 → 仍被 A 级红线拒绝
    bad_row = {"slug": "tomato-late-blight", "reviewed_by": "PENDING:团队代整理", "sources": [{"grade": "B"}]}
    reason = ingest._validate(bad_row, md, md.read_text(encoding="utf-8"), force=False)
    assert reason is not None and "A 级来源" in reason, f"PENDING 不应绕过 A 级红线，实际 reason={reason}"

    # 真实姓名 + A 级来源 → 正常通过
    verified_row = {"slug": "tomato-late-blight", "reviewed_by": "张三", "sources": [{"grade": "A"}]}
    assert ingest._validate(verified_row, md, md.read_text(encoding="utf-8"), force=False) is None


def test_ingest_gate_cli_exit_codes() -> None:
    """入库脚本 CLI：38 篇均已审校 → dry-run 退出码 0（闸门放行）。
    拒绝路径由 test_ingest_gate_rejects_null_reviewed_by 与
    test_ingest_gate_allows_pending_but_grade_a_still_enforced 以合成行覆盖（不经 CLI）。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    def _run(slug: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "scripts/ingest_kb.py", "--dry-run", "--slug", slug],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    for slug in ("apple-apple-scab", "tomato-late-blight", "pepper-bell-bacterial-spot"):
        r = _run(slug)
        assert r.returncode == 0, (
            f"{slug} 已审校，dry-run 应退出码 0，实际 {r.returncode}；输出：{r.stdout}{r.stderr}"
        )
        assert "拒绝入库" not in (r.stdout + r.stderr), f"{slug} 不应被拒"


class _RecordingLogger:
    """记录 warning/info 的桩 logger（monkeypatch 替换 llm.py 里的 loguru logger 用）。"""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.errors: list[str] = []

    def warning(self, message: object) -> None:
        self.warnings.append(str(message))

    def info(self, message: object) -> None:
        self.infos.append(str(message))

    def error(self, message: object) -> None:
        self.errors.append(str(message))

    def exception(self, message: object) -> None:
        self.errors.append(str(message))

    def __getattr__(self, name: str):  # 其余 loguru 方法兜底为空操作
        def _noop(*args: object, **kwargs: object) -> None:
            return None
        return _noop


def test_build_kwargs_injects_thinking_disabled(monkeypatch) -> None:
    """``_build_kwargs`` 确实注入 ``extra_body={"thinking":{"type":"disabled"}}``，且温度纠正为 0.6。"""
    from app.services.llm import LLMService

    rec = _RecordingLogger()
    monkeypatch.setattr("app.services.llm.logger", rec)
    monkeypatch.setattr("app.services.llm._llm_disable_thinking", lambda: True)
    monkeypatch.setattr(settings, "llm_temperature", 0.9)  # 故意设非法温度

    kwargs = LLMService()._build_kwargs([{"role": "user", "content": "x"}], stream=True,
                                        temperature=None, max_tokens=None)
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert kwargs["temperature"] == 0.6, "非法温度必须被强制纠正为 0.6"
    assert any("已强制纠正" in w for w in rec.warnings), f"应打印温度纠正告警，实际 {rec.warnings}"


def test_build_kwargs_no_warning_on_legal_temperature(monkeypatch) -> None:
    """温度为合法的 0.6 时：不纠正、不告警（避免日志噪音）。"""
    from app.services.llm import LLMService

    rec = _RecordingLogger()
    monkeypatch.setattr("app.services.llm.logger", rec)
    monkeypatch.setattr("app.services.llm._llm_disable_thinking", lambda: True)
    monkeypatch.setattr(settings, "llm_temperature", 0.6)

    kwargs = LLMService()._build_kwargs([{"role": "user", "content": "x"}], stream=True,
                                        temperature=None, max_tokens=None)
    assert kwargs["temperature"] == 0.6
    assert rec.warnings == [], f"合法温度不应告警，实际 {rec.warnings}"


class _Delta:
    def __init__(self, content=None, reasoning=None) -> None:
        self.content = content
        self.reasoning_content = reasoning


class _Choice:
    def __init__(self, delta) -> None:
        self.delta = delta


class _Chunk:
    def __init__(self, delta) -> None:
        self.choices = [_Choice(delta)]


class _FakeStream:
    def __init__(self, chunks) -> None:
        self._chunks = chunks

    def __aiter__(self):
        self._it = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Completions:
    def __init__(self, stream=None, exc=None) -> None:
        self._stream = stream
        self._exc = exc
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._stream


class _Chat:
    def __init__(self, completions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, completions) -> None:
        self.chat = _Chat(completions)


def _install_fake_client(monkeypatch, *, stream=None, exc=None):
    """把 LLMService 的客户端替换为可控桩，返回 ``_Completions`` 以统计调用次数。"""
    from app.services.llm import LLMService

    monkeypatch.setattr(settings, "deepseek_api_key", "sk-stub")
    completions = _Completions(stream=stream, exc=exc)
    svc = LLMService()
    monkeypatch.setattr(svc, "_get_client", lambda: _FakeClient(completions))
    return svc, completions


def test_reasoning_content_not_leaked_into_body(monkeypatch) -> None:
    """零 content 防御前置：推理模型只吐 ``reasoning_content`` 时，正文**不含思考过程**。"""
    stream = _FakeStream([
        _Chunk(_Delta(content=None, reasoning="用户在问番茄晚疫病……")),
        _Chunk(_Delta(content="番茄晚疫病", reasoning=None)),
        _Chunk(_Delta(content=None, reasoning="（继续思考）")),
    ])
    svc, _ = _install_fake_client(monkeypatch, stream=stream)

    tokens = _collect(svc, [{"role": "user", "content": "问"}])
    assert tokens == ["番茄晚疫病"], f"reasoning_content 不得串入正文，实际 {tokens}"
    assert "思考" not in "".join(tokens)


def test_rate_limit_raises_and_does_not_retry(monkeypatch) -> None:
    """429：**不重试**（create 只调 1 次）→ 抛 LLMRateLimitError（带用户友好文案）。"""
    from app.services.llm import LLMRateLimitError

    req = httpx.Request("POST", "http://stub/v1/chat/completions")
    resp = httpx.Response(429, request=req, json={"error": {"message": "rate"}})
    exc = RateLimitError("429 rate", response=resp, body=None)

    svc, completions = _install_fake_client(monkeypatch, exc=exc)
    _expect_error(svc, [{"role": "user", "content": "问"}], LLMRateLimitError)
    assert completions.calls == 1, f"429 不得重试，实际调用 {completions.calls} 次"

    err = LLMRateLimitError()
    assert "请求过于频繁" in err.user_message, "429 应带用户友好文案供降级使用"


def test_connection_error_retries_once_then_unavailable(monkeypatch) -> None:
    """首包前连接失败：重试 1 次（共 2 次），仍失败 → LLMUnavailableError。"""
    from app.services.llm import LLMUnavailableError

    req = httpx.Request("POST", "http://stub/v1/chat/completions")
    svc, completions = _install_fake_client(monkeypatch, exc=APIConnectionError(request=req))
    _expect_error(svc, [{"role": "user", "content": "问"}], LLMUnavailableError)
    assert completions.calls == 2, f"连接错误应重试 1 次共 2 次，实际 {completions.calls} 次"


def test_http_status_error_does_not_retry(monkeypatch) -> None:
    """HTTP 状态错误（如 400）：**不重试**（1 次）→ LLMUnavailableError。"""
    from app.services.llm import LLMUnavailableError

    req = httpx.Request("POST", "http://stub/v1/chat/completions")
    resp = httpx.Response(400, request=req, json={"error": {"message": "bad"}})
    exc = APIStatusError("bad request", response=resp, body=None)

    svc, completions = _install_fake_client(monkeypatch, exc=exc)
    _expect_error(svc, [{"role": "user", "content": "问"}], LLMUnavailableError)
    assert completions.calls == 1, f"HTTP 状态错误不得重试，实际 {completions.calls} 次"


# ============================================================
# 三、RAG 作物域约束（P1-1 修复，真实 rag_service）
# ============================================================
def _rag_ready_or_skip():
    """确保 RAG 就绪；索引/模型不可用则跳过（不产生假失败）。"""
    from app.services.rag import rag_service

    if not rag_service.ensure_loaded():
        pytest.skip("RAG 索引/模型不可用，跳过作物域约束验证")
    return rag_service


def test_rag_out_of_kb_crop_returns_scope_miss_without_fallback() -> None:
    """库外作物（水稻，不在 PlantVillage-38 覆盖范围）：``scope_miss=True``、``chunks=[]``，**绝不回退**。"""
    rag = _rag_ready_or_skip()

    res = rag.search("水稻稻瘟病用什么药", crop="水稻")
    assert res.scope_miss is True, "库外作物应 scope_miss=True"
    assert res.chunks == [], "库外作物不得回退捞别作物"


def test_rag_in_kb_crop_strictly_filtered() -> None:
    """域内作物（番茄）：命中 chunk 的 ``crop_cn`` 必须**严格等于**请求作物，无跨作物污染。"""
    rag = _rag_ready_or_skip()

    res = rag.search("晚疫病怎么识别和防治", crop="番茄")
    assert res.scope_miss is False
    assert res.chunks, "番茄域内应能命中知识库"
    assert all(c.crop_cn == "番茄" for c in res.chunks), "命中 chunk 必须全部属于番茄"

    # 类名形态入参也走同一条派生路径：Tomato___Late_blight → 番茄
    res2 = rag.search("症状识别", crop="Tomato___Late_blight")
    assert res2.crop_scope == "番茄"
    assert all(c.crop_cn == "番茄" for c in res2.chunks)


# ============================================================
# 四、SSE meta 契约（§3.2）
# ============================================================
class _FakeChunk:
    def __init__(self, slug: str, title: str) -> None:
        self.i = 0
        self.doc_slug = slug
        self.doc_db_id = 1
        self.title = title
        self.class_name = "Tomato___Late_blight"
        self.crop_cn = "番茄"
        self.category = "卵菌"
        self.section = "二、症状识别"
        self.text = "【番茄】【番茄晚疫病】\n## 二、症状识别\n叶尖叶缘水渍状暗绿斑。"
        self.score = 0.81
        self.source_path = f"kb/diseases/{slug}.md"

    def to_citation(self) -> dict:
        return {"doc_id": self.doc_slug, "title": f"{self.title}·{self.section}",
                "snippet": self.text[:120].replace("\n", " ")}


class _FakeRag:
    def __init__(self, chunks, scope_miss: bool = False, crop_scope: str | None = None) -> None:
        self._chunks = chunks
        self._scope_miss = scope_miss
        self._crop_scope = crop_scope

    def search(self, query, top_k=None, crop=None):  # noqa: ANN001
        return type("R", (), {"chunks": self._chunks, "scope_miss": self._scope_miss,
                              "crop_scope": self._crop_scope})()


@pytest.fixture
def _degraded_env(monkeypatch):
    """未配 LLM + 可控检索，走降级分支（不触真实 API）。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "")


def test_sse_meta_required_fields_present(client, make_user, monkeypatch, _degraded_env) -> None:
    """``meta`` 必为第一帧，且必带 session_id / user_message_id / citations / degraded /
    class_filter / kb_scope_miss。"""
    monkeypatch.setattr("app.api.v1.chat._load_rag",
                        lambda: _FakeRag([_FakeChunk("tomato-late-blight", "番茄晚疫病")]))

    token, _ = make_user("qa_meta_fields")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "番茄晚疫病怎么防治"})
    assert resp.status_code == 200, resp.text

    events = _parse_sse(resp.text)
    assert events[0][0] == "meta", "meta 必为第一帧"
    meta = events[0][1]
    for key in ("session_id", "user_message_id", "citations", "degraded", "class_filter", "kb_scope_miss"):
        assert key in meta, f"meta 缺少必带字段 {key}"
    assert meta["degraded"] is True
    assert meta["kb_scope_miss"] is False
    assert len(meta["citations"]) == 1
    assert events[-1][0] == "error"


@pytest.mark.xfail(
    reason="契约偏差：设计 §3.2 v1.1 要求 meta 回显 crop_scope（SearchResult.crop_scope），"
           "chat.py 的 meta 未透传该字段（仅透传 kb_scope_miss / class_filter）",
    strict=False,
)
def test_sse_meta_carries_crop_scope(client, make_user, monkeypatch, _degraded_env) -> None:
    """契约偏差记录：``meta`` 应回显作物域 ``crop_scope``（§3.2 v1.1 新增字段表）。"""
    monkeypatch.setattr("app.api.v1.chat._load_rag",
                        lambda: _FakeRag([], scope_miss=True, crop_scope="苹果"))

    token, _ = make_user("qa_meta_cropscope")
    resp = client.post(f"{BASE}/ask", headers=auth_headers(token), json={"question": "苹果黑星病怎么治"})
    meta = _parse_sse(resp.text)[0][1]
    assert meta.get("crop_scope") == "苹果", f"meta 应回显 crop_scope，实际 {meta.get('crop_scope')!r}"
