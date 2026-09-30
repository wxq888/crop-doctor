# -*- coding: utf-8 -*-
r"""播种脚本：把 ``kb/weather-rules.json`` 幂等 upsert 进 ``disease_weather_rules``。

设计要点
--------
* **按 ``disease`` 去重**：存在则更新（保留原 ``id``、``created_at``），不存在则插入。
* **幂等**：同一份 JSON 反复执行结果一致；第二次应为「新增 0 / 更新 N」。
* **``--dry-run``**：只读校验 + 统计「将新增/将更新」，**任何写操作均回滚**、不落库。
* **溯源**：目标表无 ``source`` 字段，来源简称已写进 ``advice``；
  完整溯源（标题 + URL + 分级 + 抓取时间）保留在 ``kb/weather-rules.json`` 的
  ``sources`` 字段与 ``kb/weather-rules.report.json``。

用法（在仓库根执行）::

    .venv\Scripts\python.exe scripts\seed_weather_rules.py --dry-run
    .venv\Scripts\python.exe scripts\seed_weather_rules.py

退出码：``0`` 成功；``1`` 数据/校验错误。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 把 backend 目录加入 sys.path，保证可 import app 包（与 seed_admin.py 一致）
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.warning import DiseaseWeatherRule  # noqa: E402

DEFAULT_RULES_PATH = REPO_ROOT / "kb" / "weather-rules.json"

# 可写字段（不含主键 / 时间戳）
WRITABLE_FIELDS = (
    "crop",
    "temp_min",
    "temp_max",
    "humidity_min",
    "humidity_max",
    "rain_condition",
    "risk_level",
    "advice",
    "enabled",
)
_VALID_RAIN = {"any", "rain", "no_rain"}
_VALID_RISK = {"high", "mid", "low"}
_ADVICE_MAX = 500


def load_rules(path: Path) -> list[dict[str, Any]]:
    """读取并做基础结构校验，返回规则列表（保持文件顺序）。

    Raises:
        ValueError: 文件不存在 / 非 JSON 数组 / 必填字段缺失或取值非法。
    """
    if not path.exists():
        raise ValueError(f"规则文件不存在：{path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("规则文件顶层必须是 JSON 数组")

    rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"第 {idx} 条规则不是对象")
        disease = (item.get("disease") or "").strip()
        if not disease:
            raise ValueError(f"第 {idx} 条规则缺少 disease")
        if disease in seen:
            raise ValueError(f"规则文件内 disease 重复：{disease}")
        seen.add(disease)

        rain = item.get("rain_condition", "any")
        if rain not in _VALID_RAIN:
            raise ValueError(f"{disease}: rain_condition 非法：{rain}")
        risk = item.get("risk_level")
        if risk not in _VALID_RISK:
            raise ValueError(f"{disease}: risk_level 非法：{risk}")
        advice = item.get("advice")
        if advice is not None and len(str(advice)) > _ADVICE_MAX:
            raise ValueError(f"{disease}: advice 超过 {_ADVICE_MAX} 字")

        rules.append(item)
    return rules


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    """把 JSON 条目规整为可写字段字典（补默认值，缺省字段显式置 None）。"""
    norm: dict[str, Any] = {
        "crop": item.get("crop"),
        "temp_min": _as_float(item.get("temp_min")),
        "temp_max": _as_float(item.get("temp_max")),
        "humidity_min": _as_float(item.get("humidity_min")),
        "humidity_max": _as_float(item.get("humidity_max")),
        "rain_condition": item.get("rain_condition", "any"),
        "risk_level": item.get("risk_level"),
        "advice": item.get("advice"),
        "enabled": int(item.get("enabled", 1)),
    }
    return norm


def _as_float(value: Any) -> float | None:
    """宽松数值转换：None / 空串 → None，其余转 float。"""
    if value is None or value == "":
        return None
    return float(value)


def seed(rules: list[dict[str, Any]], *, dry_run: bool = False) -> tuple[int, int, int]:
    """把规则幂等 upsert 进库。

    Args:
        rules: ``load_rules`` 返回的规则列表。
        dry_run: 为 True 时只统计不写库（事务回滚）。

    Returns:
        ``(inserted, updated, skipped)`` 三元组。
    """
    inserted = updated = skipped = 0
    db: Session = SessionLocal()
    try:
        for item in rules:
            disease = item["disease"].strip()
            values = _normalize(item)
            existing = db.scalar(
                select(DiseaseWeatherRule).where(DiseaseWeatherRule.disease == disease)
            )
            if existing is None:
                db.add(DiseaseWeatherRule(disease=disease, **values))
                inserted += 1
            else:
                for field in WRITABLE_FIELDS:
                    setattr(existing, field, values[field])
                updated += 1

        if dry_run:
            db.rollback()
            print(f"[dry-run] 将新增 {inserted} / 将更新 {updated} / 跳过 {skipped}（未写库）")
        else:
            db.commit()
            print(f"完成：新增 {inserted} / 更新 {updated} / 跳过 {skipped}")
        return inserted, updated, skipped
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    """解析参数并执行播种。"""
    parser = argparse.ArgumentParser(description="幂等播种病害气象预警规则")
    parser.add_argument(
        "--rules",
        default=str(DEFAULT_RULES_PATH),
        help="规则 JSON 路径（默认 kb/weather-rules.json）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只校验、统计，不写库")
    args = parser.parse_args()

    try:
        rules = load_rules(Path(args.rules))
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"规则校验失败：{exc}", file=sys.stderr)
        return 1

    print(f"读取规则 {len(rules)} 条（{args.rules}）")
    try:
        seed(rules, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 —— 顶层兜底，保证退出码可控
        print(f"播种失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
