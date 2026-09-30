# -*- coding: utf-8 -*-
"""知识库公共工具：路径引导、slug 生成、映射表加载、可信度分级、分节模板。

被 ``scripts/collect_kb.py``、``scripts/ingest_kb.py``、``scripts/build_index.py``
共用，保证「映射表加载 / slug 规则 / 分级规则 / 分节模板」在本仓库**只有一处实现**，
避免规则漂移（设计文档 §1.2 / §1.3 / §1.4.4）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

# 把 backend 目录加入 sys.path，保证可 import app 包（与 scripts/seed_admin.py 一致）
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
BACKEND_DIR: Path = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402

# 采集 User-Agent。
# 说明：HTTP 请求头只能承载 latin-1，设计文档里的中文 UA 无法作为请求头发送，
# 故此处使用等价的纯 ASCII 表述（学术非商业 + 指向仓库 README 取联系方式）。
USER_AGENT: str = (
    "CropDoctorBot/1.0 (+academic graduation project, non-commercial; "
    "contact: see repo README)"
)

# ---------------------------------------------------------------------------
# 可信度分级（设计文档 §1.4.4）
#   A = 官方/权威（.gov.cn 各级政府与农业农村部门、中国农科院、农药信息网、农技推广中心）
#   B = 权威百科（百度百科）
#   C = 其他（仅线索，一般不采）
# ---------------------------------------------------------------------------
_A_DOMAIN_SUFFIXES: tuple[str, ...] = (
    ".gov.cn",                 # 各级政府 / 农业农村部门（含省市级农技推广）
    "moa.gov.cn",              # 农业农村部
    ".caas.cn",                # 中国农业科学院（含 cast.caas.cn 中国农业科技信息网）
    "ippcaas.cn",              # 中国农科院植物保护研究所
    "chinapesticide.org.cn",   # 中国农药信息网
    "natesc.org.cn",           # 全国农技推广服务中心
)
_B_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "baike.baidu.com",
    "wapbaike.baidu.com",
)


def grade_for_url(url: str) -> str:
    """按域名给出可信度分级 ``A`` / ``B`` / ``C``。"""
    try:
        host = urlsplit(url).netloc.lower().split(":")[0]
    except (ValueError, AttributeError):
        return "C"
    if not host:
        return "C"
    for suffix in _A_DOMAIN_SUFFIXES:
        if host == suffix or host.endswith("." + suffix) or host.endswith(suffix):
            return "A"
    for suffix in _B_DOMAIN_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return "B"
    return "C"


# ---------------------------------------------------------------------------
# slug 生成（设计文档 §1.2）
# ---------------------------------------------------------------------------
def slugify(class_name: str) -> str:
    """把模型原始英文类名转为文件名主体 slug。

    规则：括号/逗号/空格/下划线（含 ``___``）→ ``-`` → 转小写 → 合并连续 ``-`` → 去首尾 ``-``。
    例：``Corn___Cercospora_leaf_spot Gray_leaf_spot`` →
    ``corn-cercospora-leaf-spot-gray-leaf-spot``。
    """
    text = class_name
    for ch in ("(", ")", ",", " ", "_"):
        text = text.replace(ch, "-")
    text = re.sub(r"-+", "-", text)
    return text.strip("-").lower()


# ---------------------------------------------------------------------------
# 映射表加载（单一事实来源 kb/class-map.json）
# ---------------------------------------------------------------------------
def load_class_map(path: Path | None = None) -> list[dict]:
    """加载 ``kb/class-map.json``；返回数组（每行一个类别对象）。"""
    target = Path(path) if path is not None else settings.kb_class_map_abs
    if not target.exists():
        raise FileNotFoundError(f"映射表不存在：{target}")
    with open(target, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"映射表结构应为数组：{target}")
    return data


def save_class_map(rows: list[dict], path: Path | None = None) -> None:
    """把映射表回写为 UTF-8 JSON（保留可读缩进）。"""
    target = Path(path) if path is not None else settings.kb_class_map_abs
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def doc_rows(rows: list[dict]) -> list[dict]:
    """返回需要生成知识文档的行（``doc_type != 'ignore'``）。"""
    return [row for row in rows if row.get("doc_type") != "ignore"]


def has_grade_a_source(row: dict) -> bool:
    """判断某行是否含 ≥1 个 A 级来源（入库/建索引的诚信卡点）。"""
    sources = row.get("sources") or []
    return any((src or {}).get("grade") == "A" for src in sources)


# PENDING 前缀：机器可识别的「团队代整理、用户本人尚未复核」标记（用户拍板方案 a）
PENDING_PREFIX: str = "PENDING:"


def review_state(row: dict) -> str:
    """由 ``reviewed_by`` 派生审校三态（入库闸门 / chunk 元数据共用同一判定）。

    * ``PENDING:`` 前缀 → ``"pending"``（团队代整理、待用户本人复核；**允许入库供演示**）；
    * 有值且非 ``PENDING`` → ``"verified"``（真实审校人，正常入库）；
    * ``None`` / 空串 / 纯空白 → ``"unverified"``（**拒绝入库【诚信红线】**）。
    """
    val = row.get("reviewed_by")
    if val is None or not str(val).strip():
        return "unverified"
    if str(val).startswith(PENDING_PREFIX):
        return "pending"
    return "verified"


# ---------------------------------------------------------------------------
# 文档分节模板（设计文档 §1.3，5 套模板）
# ---------------------------------------------------------------------------
SECTION_TITLES: dict[str, list[str]] = {
    # 模板 A · 真菌 / 细菌 / 卵菌
    "真菌": [
        "一、病害概述", "二、症状识别", "三、发病条件",
        "四、防治方法", "五、易混淆病害与鉴别要点", "六、用药安全与注意",
    ],
    "细菌": [
        "一、病害概述", "二、症状识别", "三、发病条件",
        "四、防治方法", "五、易混淆病害与鉴别要点", "六、用药安全与注意",
    ],
    "卵菌": [
        "一、病害概述", "二、症状识别", "三、发病条件",
        "四、防治方法", "五、易混淆病害与鉴别要点", "六、用药安全与注意",
    ],
    # 模板 B · 病毒（无「药剂防治」）
    "病毒": [
        "一、病害概述", "二、症状识别", "三、发病条件",
        "四、防治方法", "五、易混淆病害与鉴别要点", "六、用药安全与注意",
    ],
    # 模板 C · 虫害（杀螨剂逻辑）
    "虫害": [
        "一、发生概述", "二、识别要点（虫体与为害状）", "三、发生条件",
        "四、防治方法", "五、易混淆与鉴别要点", "六、用药安全与注意",
    ],
    # 模板 D · 检疫性
    "检疫性": [
        "一、病害概述", "二、症状识别", "三、发病条件",
        "四、防治方法", "五、易混淆与鉴别要点", "六、用药安全与注意",
    ],
    # 模板 E · 健康（无「防治方法」）
    "健康": [
        "一、健康状态说明", "二、健康叶片识别要点",
        "三、易混淆的相似病害（早期预警）", "四、保持健康的农事建议",
    ],
}

# category → 模板族（A/B/C/D/E）
TEMPLATE_FAMILY: dict[str, str] = {
    "真菌": "A", "细菌": "A", "卵菌": "A",
    "病毒": "B", "虫害": "C", "检疫性": "D", "健康": "E", "背景": "-",
}

# 采集/草稿中需要凸显的类别提示（防止模板误用）
CATEGORY_NOTE: dict[str, str] = {
    "病毒": "⚠️ 病毒病无有效治疗药剂：防治以切断传播途径（防控媒介）、抗病品种、拔除病株为主，不含「药剂防治」节。",
    "虫害": "⚠️ 虫害使用杀螨剂逻辑：标注作用机理、注意轮换用药防抗性，不套用真菌杀菌剂写法。",
    "检疫性": "⚠️ 检疫性病害不写「喷药治病」：防治 = 防控传播媒介 + 清除病株 + 苗木检疫（引用官方检疫要求）。",
    "健康": "⚠️ 健康类不含「防治方法」：改「健康识别要点 / 易混淆相似病害 / 保持健康的农事建议」。",
}

# 允许的类别枚举（校验用）
CATEGORY_ENUM: tuple[str, ...] = (
    "真菌", "细菌", "卵菌", "病毒", "虫害", "检疫性", "健康", "背景",
)


def sections_for(category: str) -> list[str]:
    """按病原类别返回该文档的 H2 分节标题列表。"""
    return SECTION_TITLES.get(category, SECTION_TITLES["真菌"])


def template_family(category: str) -> str:
    """按病原类别返回模板族标识（A/B/C/D/E）。"""
    return TEMPLATE_FAMILY.get(category, "A")


__all__ = [
    "REPO_ROOT",
    "BACKEND_DIR",
    "USER_AGENT",
    "grade_for_url",
    "slugify",
    "load_class_map",
    "save_class_map",
    "doc_rows",
    "has_grade_a_source",
    "review_state",
    "PENDING_PREFIX",
    "SECTION_TITLES",
    "TEMPLATE_FAMILY",
    "CATEGORY_NOTE",
    "CATEGORY_ENUM",
    "sections_for",
    "template_family",
]
