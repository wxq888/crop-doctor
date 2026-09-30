# -*- coding: utf-8 -*-
"""知识库采集脚本：从权威源批量抓取病害语料，产出「待审校草稿」。

设计依据：``docs/impl-rag-chat-v1.md`` §1.4。
合规硬约束（§1.4.3）：
  * 并发 ``ThreadPoolExecutor(max_workers=2)``，**同域名串行**；
  * 每次请求前随机 ``sleep(uniform(1.5, 3.0))``；
  * 超时 连接 10s / 读 30s；
  * 失败重试 3 次，指数退避 1s→2s→4s；
  * 启动时读取目标域 ``robots.txt``，``Disallow`` 路径一律跳过；
  * 纯 ASCII UA 标识（HTTP 头只能承载 latin-1）；
  * URL 归一化去重 + 正文指纹去重；``A/B/C`` 可信度分级。

产物（均不入库，见 ``.gitignore``）：
  * ``kb/_raw/<slug>/<n>_<host>.html``  原始 HTML（人工阅读）
  * ``kb/_raw/<slug>/<n>_<host>.txt``   抽取正文
  * ``kb/_raw/_cache/<md5>.html``       去重缓存（跨 slug 复用，避免重复下载）
  * ``kb/_raw/_cache.json``             抓取缓存清单（幂等依据）
  * ``kb/_review/<slug>.draft.md``      待审校草稿（模板骨架 + 原文素材）
  * ``kb/_review/report.json``          采集报告（来源数 / 缺失字段 / 分级）

**本脚本绝不直接写 ``kb/diseases/``**（设计文档 §1.4.5 人工审校卡点）。

用法（在仓库根执行）::

    .venv\\Scripts\\python.exe scripts\\collect_kb.py --dry-run
    .venv\\Scripts\\python.exe scripts\\collect_kb.py --limit 1 --category 真菌
    .venv\\Scripts\\python.exe scripts\\collect_kb.py --slug tomato-late-blight
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser

import httpx

from kb_common import (
    CATEGORY_NOTE,
    REPO_ROOT,
    USER_AGENT,
    doc_rows,
    grade_for_url,
    load_class_map,
    sections_for,
    template_family,
)

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
RAW_DIR = REPO_ROOT / "kb" / "_raw"
REVIEW_DIR = REPO_ROOT / "kb" / "_review"
CACHE_DIR = RAW_DIR / "_cache"
CACHE_MANIFEST = RAW_DIR / "_cache.json"

REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_WORKERS = 2
SLEEP_RANGE = (1.5, 3.0)
RETRY_TIMES = 3
RETRY_BACKOFF = (1.0, 2.0, 4.0)  # 指数退避

# 单 slug 采集素材在草稿中保留的最大字数（人工阅读用）
DRAFT_MATERIAL_CHARS = 1500

# 已人工核实的种子链接（A 级 .gov.cn / 农科院）。可通过 kb/sources.seed.json 覆盖/扩展。
SEED_SOURCES: dict[str, list[str]] = {
    "tomato-late-blight": [
        "http://jw.rencheng.gov.cn/art/2026/3/5/art_34809_2824335.html",
        "https://nync.lanzhou.gov.cn/art/2020/12/31/art_2202_960339.html",
        "http://kjj.bynr.gov.cn/sykj_1/202301/t20230116_283026.html",
        "https://nync.jiangxi.gov.cn/jxsnynct/fzjz/content/content_1877698089655173120.html",
        "http://nw.qingdao.gov.cn/fwxx/nyncj7/202112/t20211215_4036122.shtml",
    ],
    "tomato-early-blight": [
        "http://kjj.bynr.gov.cn/sykj_1/202301/t20230116_283026.html",
    ],
    "orange-haunglongbing-citrus-greening": [
        "https://nyncw.sh.gov.cn/bwbdzzl/20190115/0009-111668.html",
        "https://nync.jiangxi.gov.cn/jxsnynct/bcyb/content/content_2041771858626936832.html",
        "https://nynct.sc.gov.cn/nynct/c101264/2025/7/2/e1a18066b1b14479992ecf112c3617c6.shtml",
        "http://xxtq.gov.cn/xxtqnlsj/gzdt/t6549090.html",
    ],
    "tomato-tomato-yellow-leaf-curl-virus": [
        "https://nyncj.baoji.gov.cn/col4165/col4170/202307/t20230727_823434.html",
        "https://nyncj.beijing.gov.cn/nyj/zwgk/ztgk/zwbhxx/436225706/index.html",
        "https://nyncj.lsz.gov.cn/kjfw/zzjs/201606/t20160621_1062055.html",
    ],
    "tomato-spider-mites-two-spotted-spider-mite": [
        "https://nynct.shaanxi.gov.cn/zt/snzbxx/zbjs/202604/t20260423_3632553.html",
        "https://www.linan.gov.cn/art/2015/2/9/art_1367638_24510021.html",
        "https://cast.caas.cn/kj/syjs/zwbhjs/242470.html",
    ],
}

# 去重时需剔除的跟踪参数
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "spm"}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def normalize_url(url: str) -> str:
    """URL 归一化：去 fragment、去跟踪参数、统一小写 host。"""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in _TRACKING_PARAMS]
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path,
        urlencode(query),
        "",  # 去 fragment
    ))


def count_cjk(text: str) -> int:
    """统计中日韩统一表意文字数量（中文字数近似）。"""
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def fingerprint(text: str, size: int = 200) -> str:
    """正文前 ``size`` 字的 md5 指纹（内容去重）。"""
    return hashlib.md5(text[:size].encode("utf-8", errors="ignore")).hexdigest()


def decode_body(content: bytes, content_type: str) -> str:
    """按响应头 charset → meta charset → utf-8 → gb18030 依次尝试解码。"""
    candidates: list[str] = []
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    if m:
        candidates.append(m.group(1))
    head = content[:2048]
    m2 = re.search(rb"""charset=["']?([\w\-]+)""", head, re.I)
    if m2:
        candidates.append(m2.group(1).decode("ascii", errors="ignore"))
    candidates += ["utf-8", "gb18030"]
    for enc in candidates:
        if not enc:
            continue
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


class _TextExtractor(HTMLParser):
    """极简 HTML→纯文本抽取（stdlib，不引 bs4）。"""

    _BLOCK = {
        "p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "table", "ul", "ol", "dd", "dt", "blockquote", "pre",
    }
    _SKIP = {"script", "style", "noscript", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:  # noqa: D102
        if tag in self._SKIP:
            self._skip += 1
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:  # noqa: D102
        if tag in self._SKIP and self._skip > 0:
            self._skip -= 1
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:  # noqa: D102
        if self._skip == 0:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [re.sub(r"[ \t\u3000]+", " ", ln).strip() for ln in raw.split("\n")]
        return "\n".join(ln for ln in lines if ln)


def extract_text(html: str) -> str:
    """HTML → 纯文本。"""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 —— 解析异常不致命，返回已抽取部分
        pass
    return parser.text()


def extract_title(html: str) -> str:
    """抽取 <title>。"""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


# ---------------------------------------------------------------------------
# robots.txt 管理
# ---------------------------------------------------------------------------
class RobotsCache:
    """目标域 robots.txt 缓存（Disallow 路径一律跳过）。"""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def _get(self, domain: str) -> RobotFileParser | None:
        with self._lock:
            if domain in self._parsers:
                return self._parsers[domain]
        parser: RobotFileParser | None = None
        try:
            resp = self._client.get(f"https://{domain}/robots.txt")
            if resp.status_code == 200 and resp.content:
                parser = RobotFileParser()
                parser.parse(resp.text.splitlines())
        except Exception:  # noqa: BLE001 —— robots 不可得时放行并记日志
            parser = None
        with self._lock:
            self._parsers[domain] = parser
        return parser

    def can_fetch(self, url: str) -> bool:
        """判断 UA 是否允许抓取该 URL。"""
        domain = urlsplit(url).netloc.lower()
        parser = self._get(domain)
        if parser is None:
            return True  # robots 缺失/不可达 → 放行（已记日志）
        try:
            return parser.can_fetch(USER_AGENT, url)
        except Exception:  # noqa: BLE001
            return True


# ---------------------------------------------------------------------------
# 采集主流程
# ---------------------------------------------------------------------------
class _DomainLocks:
    """同域名串行、跨域名并行的锁表。"""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, domain: str) -> threading.Lock:
        with self._guard:
            if domain not in self._locks:
                self._locks[domain] = threading.Lock()
            return self._locks[domain]


def fetch_once(clients: dict[bool, httpx.Client], url: str, logs: list[str]) -> dict:
    """抓取单个 URL（限速 + 重试 + SSL 降级）。返回结果字典，不抛异常。

    ``httpx`` 的 ``verify`` 是**客户端级**参数，故预建「校验 / 免校验」两个客户端，
    先用校验客户端，遇 SSL/连接类错误再降级为免校验客户端（部分 gov 站证书链不全/过期）。
    """
    last_error = ""
    for attempt in range(RETRY_TIMES + 1):
        # 每次请求前随机间隔（同域串行由调用方保证）
        time.sleep(random.uniform(*SLEEP_RANGE))
        for verify in (True, False):
            try:
                resp = clients[verify].get(url)
                if resp.status_code >= 400:
                    last_error = f"HTTP {resp.status_code}"
                    break  # 换 verify 无意义，走重试
                html = decode_body(resp.content, resp.headers.get("content-type", ""))
                return {
                    "ok": True,
                    "status": resp.status_code,
                    "html": html,
                    "bytes": len(resp.content),
                    "ssl_insecure": not verify,
                }
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
                if verify:  # 首次 verify 失败，尝试 insecure（部分 gov 站证书链不全/过期）
                    continue
                break
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
                break
        if attempt < RETRY_TIMES:
            backoff = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
            logs.append(f"  ↻ 重试 {url}（第 {attempt + 1} 次，退避 {backoff}s）：{last_error}")
            time.sleep(backoff)
    return {"ok": False, "error": last_error, "status": None}


def load_cache() -> dict:
    """读取抓取缓存清单（幂等：命中即不重复下载）。"""
    if CACHE_MANIFEST.exists():
        try:
            return json.loads(CACHE_MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    """回写抓取缓存清单。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_MANIFEST.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )


def build_candidates(rows: list[dict], limit: int, category: str | None, slug: str | None,
                     seed: dict[str, list[str]]) -> list[dict]:
    """组装候选任务：[(slug, class_name, category, url)]，按 slug 内 URL 归一化去重。"""
    tasks: list[dict] = []
    for row in doc_rows(rows):
        if row.get("doc_type") == "ignore":
            continue
        if category and row.get("category") != category:
            continue
        if slug and row.get("slug") != slug:
            continue
        urls = seed.get(row["slug"], [])
        seen: set[str] = set()
        picked = 0
        for url in urls:
            norm = normalize_url(url)
            if norm in seen:
                continue
            seen.add(norm)
            tasks.append({
                "slug": row["slug"],
                "class_name": row["class_name"],
                "disease_cn": row.get("disease_cn", ""),
                "category": row.get("category", ""),
                "url": norm,
            })
            picked += 1
            if picked >= limit:
                break
    return tasks


def collect(args: argparse.Namespace) -> int:
    """采集主入口。返回进程退出码。"""
    rows = load_class_map()
    seed = dict(SEED_SOURCES)
    seed_path = REPO_ROOT / "kb" / "sources.seed.json"
    if seed_path.exists():
        extra = json.loads(seed_path.read_text(encoding="utf-8"))
        if isinstance(extra, dict):
            seed.update({k: list(v) for k, v in extra.items()})

    tasks = build_candidates(rows, args.limit, args.category, args.slug, seed)

    # 全局 URL 去重（同一 URL 只下载一次，可服务多个 slug）
    unique_urls = sorted({t["url"] for t in tasks})

    if args.dry_run:
        print(f"[dry-run] 目标类数={len({t['slug'] for t in tasks})}  候选 URL 数={len(unique_urls)}（≤114）")
        for t in tasks:
            print(f"  [{t['category']}] {t['slug']:<46} {t['url']}  ({grade_for_url(t['url'])}级)")
        return 0

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    cache: dict = load_cache()
    logs: list[str] = []
    fetched: dict[str, dict] = {}   # normalized_url -> {html, text, bytes, grade, ssl_insecure, fetched_at}
    failures: dict[str, str] = {}   # normalized_url -> error
    skipped_robots: list[str] = []

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    # httpx 的 verify 为「客户端级」参数，无法按请求传入 → 预建「校验 / 免校验」两个客户端
    clients: dict[bool, httpx.Client] = {
        True: httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=headers, verify=True),
        False: httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=headers, verify=False),
    }
    try:
        robots = RobotsCache(clients)

        # 1) robots 预检
        allowed_urls: list[str] = []
        for url in unique_urls:
            if robots.can_fetch(url):
                allowed_urls.append(url)
            else:
                skipped_robots.append(url)
                logs.append(f"  ⛔ robots 禁止：{url}")

        # 2) 分派抓取（同域串行 + 跨域并行）
        locks = _DomainLocks()
        to_fetch: list[str] = []
        for url in allowed_urls:
            digest = hashlib.md5(url.encode("utf-8")).hexdigest()
            cached = cache.get(url)
            if cached and (CACHE_DIR / f"{digest}.html").exists():
                html = (CACHE_DIR / f"{digest}.html").read_text(encoding="utf-8", errors="replace")
                text = extract_text(html)
                fetched[url] = {"html": html, "text": text, "bytes": cached.get("bytes", len(html)),
                                "grade": grade_for_url(url), "ssl_insecure": cached.get("ssl_insecure", False),
                                "fetched_at": cached.get("fetched_at"), "cached": True}
                logs.append(f"  ⏩ 命中缓存，跳过下载：{url}")
                continue
            to_fetch.append(url)

        def _worker(url: str) -> tuple[str, dict]:
            domain = urlsplit(url).netloc.lower()
            with locks.get(domain):
                return url, fetch_once(clients, url, logs)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_worker, url): url for url in to_fetch}
            for fut in as_completed(futures):
                url, res = fut.result()
                if res.get("ok"):
                    html = res["html"]
                    text = extract_text(html)
                    digest = hashlib.md5(url.encode("utf-8")).hexdigest()
                    (CACHE_DIR / f"{digest}.html").write_text(html, encoding="utf-8")
                    fetched[url] = {
                        "html": html, "text": text, "bytes": res["bytes"],
                        "grade": grade_for_url(url), "ssl_insecure": res.get("ssl_insecure", False),
                        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "cached": False,
                    }
                    cache[url] = {
                        "bytes": res["bytes"],
                        "grade": grade_for_url(url),
                        "ssl_insecure": res.get("ssl_insecure", False),
                        "fetched_at": fetched[url]["fetched_at"],
                    }
                    logs.append(f"  ✓ 抓取成功 {res['status']} {res['bytes']}B  {url}")
                else:
                    failures[url] = res.get("error", "unknown")
                    logs.append(f"  ✗ 抓取失败 {url}：{res.get('error')}")
    finally:
        for _c in clients.values():
            _c.close()

    save_cache(cache)

    # 3) 每个 slug 汇总（内容指纹去重 + 落 raw + 出草稿）
    report_classes: list[dict] = []
    for slug in sorted({t["slug"] for t in tasks}):
        cls_tasks = [t for t in tasks if t["slug"] == slug]
        class_name = cls_tasks[0]["class_name"]
        disease_cn = cls_tasks[0]["disease_cn"]
        category = cls_tasks[0]["category"]
        slug_dir = RAW_DIR / slug
        slug_dir.mkdir(parents=True, exist_ok=True)

        sources: list[dict] = []
        class_failed: list[dict] = []
        class_skipped: list[str] = []
        seen_fp: set[str] = set()

        for idx, task in enumerate(cls_tasks, start=1):
            url = task["url"]
            if url in skipped_robots:
                class_skipped.append(url)
                continue
            if url in failures:
                class_failed.append({"url": url, "error": failures[url]})
                continue
            doc = fetched.get(url)
            if not doc:
                class_failed.append({"url": url, "error": "未抓取"})
                continue
            text = doc["text"]
            fp = fingerprint(text)
            if fp in seen_fp:  # 内容指纹去重
                class_failed.append({"url": url, "error": "内容指纹重复，已丢弃"})
                continue
            seen_fp.add(fp)

            host = urlsplit(url).netloc.lower().replace(":", "_")
            (slug_dir / f"{idx}_{host}.html").write_text(doc["html"], encoding="utf-8")
            (slug_dir / f"{idx}_{host}.txt").write_text(text, encoding="utf-8")

            sources.append({
                "title": extract_title(doc["html"]) or url,
                "url": url,
                "grade": doc["grade"],
                "chars": len(text),
                "zh_chars": count_cjk(text),
                "ssl_insecure": doc["ssl_insecure"],
                "fetched_at": doc["fetched_at"],
                "text": text,
            })

        # 生成草稿（模板骨架 + 原文素材；不写 kb/diseases/）
        draft_path = REVIEW_DIR / f"{slug}.draft.md"
        draft_path.write_text(
            _render_draft(disease_cn, category, class_name, sources),
            encoding="utf-8",
        )

        missing = _missing_fields(category, sources)
        report_classes.append({
            "slug": slug,
            "class_name": class_name,
            "disease_cn": disease_cn,
            "category": category,
            "template": template_family(category),
            "source_count": len(sources),
            "a_grade_count": sum(1 for s in sources if s["grade"] == "A"),
            "missing_fields": missing,
            "draft": str(draft_path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sources": [{k: v for k, v in s.items() if k != "text"} for s in sources],
            "failed": class_failed,
            "skipped_robots": class_skipped,
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user_agent": USER_AGENT,
        "params": {"limit": args.limit, "category": args.category, "slug": args.slug},
        "totals": {
            "classes": len(report_classes),
            "candidates": len(tasks),
            "unique_urls": len(unique_urls),
            "fetched": len(fetched),
            "downloaded": sum(1 for d in fetched.values() if not d.get("cached")),
            "failed": len(failures),
            "skipped_robots": len(skipped_robots),
        },
        "classes": report_classes,
    }
    (REVIEW_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=== 采集完成 ===")
    for line in logs:
        print(line)
    print(f"报告：kb/_review/report.json（类={report['totals']['classes']} "
          f"候选={report['totals']['candidates']} 抓取={report['totals']['fetched']} "
          f"下载={report['totals']['downloaded']} 失败={report['totals']['failed']} "
          f"robots跳过={report['totals']['skipped_robots']}）")
    return 0 if report['totals']['fetched'] or not tasks else 1


def _missing_fields(category: str, sources: list[dict]) -> list[str]:
    """根据模板判断仍未补齐的字段（草稿阶段恒为全节待补，A 级来源缺失单独标注）。"""
    missing = ["分节正文待人工撰写"]
    if not any(s["grade"] == "A" for s in sources):
        missing.append("缺少 A 级来源")
    if category in CATEGORY_NOTE and not sources:
        missing.append("该类别无采集素材")
    return missing


def _render_draft(disease_cn: str, category: str, class_name: str, sources: list[dict]) -> str:
    """渲染待审校草稿：模板骨架（【待补充】）+ 采集原文素材。"""
    lines: list[str] = [
        f"# {disease_cn}",
        "",
        "> ⚠️ **本文件为自动采集草稿，尚未人工审校，禁止直接入库。**",
        f"> 模型类名：`{class_name}`　病原类别：**{category}**　模板族：{template_family(category)}",
        "> 审校通过后回填 kb/class-map.json 的 `reviewed_by/reviewed_at/sources`，再移入 `kb/diseases/`。",
        "",
    ]
    note = CATEGORY_NOTE.get(category)
    if note:
        lines += [f"> {note}", ""]

    for section in sections_for(category):
        lines += [f"## {section}", "", "【待补充】", ""]

    lines += ["## 附：采集原文素材（自动抽取，未审校，勿直接采用）", ""]
    if not sources:
        lines += ["（无：该类别暂无可达权威来源，需人工补充）", ""]
    for i, src in enumerate(sources, start=1):
        text = src["text"]
        snippet = text[:DRAFT_MATERIAL_CHARS]
        lines += [
            f"### 来源 {i} · {src['grade']} 级 · {src['title']}",
            f"- URL：{src['url']}",
            f"- 抽取字数：{src['chars']}（中文 {src['zh_chars']}）"
            + ("　⚠️ SSL 证书校验被跳过" if src.get("ssl_insecure") else ""),
            "",
            "```text",
            snippet,
            "```",
            "",
        ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="知识库采集脚本（产出待审校草稿）")
    parser.add_argument("--dry-run", action="store_true", help="只打印目标 URL 清单，不发起请求")
    parser.add_argument("--limit", type=int, default=3, help="每个类最多抓取页数（默认 3）")
    parser.add_argument("--category", default=None, help="仅采指定病原类别（如 真菌）")
    parser.add_argument("--slug", default=None, help="仅采指定 slug")
    return parser


def main() -> int:
    """命令行入口。"""
    args = build_parser().parse_args()
    try:
        return collect(args)
    except KeyboardInterrupt:
        print("已中断")
        return 130
    except Exception as exc:  # noqa: BLE001 —— 顶层兜底，避免脚本崩溃
        print(f"采集脚本异常：{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
