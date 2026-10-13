"""数据加载层。

负责定位 ``data/`` 目录并把 JSON 解析为 ``models`` 中的数据结构。
所有带缓存的加载函数都在模块级做了 lru_cache，避免重复读盘。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from .models import Career, MarketStat, Question, RoleModel


class DataNotFoundError(FileNotFoundError):
    """找不到数据目录时抛出。"""


def find_data_dir() -> Path:
    """按优先级定位数据目录。

    查找顺序：
    1. 环境变量 ``CAREER_COMPASS_DATA`` 指定的目录；
    2. 从本文件所在位置逐级向上查找 ``data/questions.json``（覆盖源码直接运行）；
    3. 从当前工作目录向上查找（覆盖在仓库任意子目录下执行）。
    """
    env = os.environ.get("CAREER_COMPASS_DATA")
    if env:
        p = Path(env).expanduser()
        if (p / "questions.json").exists():
            return p
        raise DataNotFoundError(f"CAREER_COMPASS_DATA 指向的目录中没有 questions.json: {p}")

    candidates: list[Path] = []
    here = Path(__file__).resolve()
    candidates.extend(parent / "data" for parent in here.parents)
    candidates.extend(parent / "data" for parent in Path.cwd().resolve().parents)
    candidates.append(Path.cwd() / "data")

    for c in candidates:
        if (c / "questions.json").exists():
            return c

    raise DataNotFoundError(
        "未找到数据目录。请设置环境变量 CAREER_COMPASS_DATA 指向项目 data/ 目录，或在项目根目录下运行。"
    )


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=8)
def _cached_questions(data_dir_str: str) -> dict:
    return _read_json(Path(data_dir_str) / "questions.json")


@lru_cache(maxsize=8)
def _cached_careers(data_dir_str: str) -> dict:
    return _read_json(Path(data_dir_str) / "careers.json")


@lru_cache(maxsize=8)
def _cached_role_models(data_dir_str: str) -> dict:
    return _read_json(Path(data_dir_str) / "role_models.json")


@lru_cache(maxsize=8)
def _cached_market(data_dir_str: str) -> dict:
    return _read_json(Path(data_dir_str) / "market_stats.json")


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def load_question_bank() -> dict:
    """返回题库原始 dict（含 _meta 与 questions）。"""
    return _cached_questions(str(find_data_dir()))


def load_questions() -> list[Question]:
    """返回题目列表。"""
    raw = load_question_bank()
    return [
        Question(
            id=q["id"],
            dim=q["dim"],
            type=q["type"],
            stem=q["stem"],
            weight=float(q.get("weight", 1.0)),
            reverse=bool(q.get("reverse", False)),
            options=list(q.get("options", [])),
            answer=q.get("answer"),
            difficulty=float(q.get("difficulty", 0.5)),
            source=q.get("source", ""),
        )
        for q in raw["questions"]
    ]


def load_dimension_names() -> dict[str, str]:
    """返回 ``{维度 key: 中文名}`` 映射。"""
    return dict(load_question_bank()["_meta"]["dimensions"])


def load_group_names() -> dict[str, str]:
    """返回 ``{组 key: 中文名}`` 映射。"""
    return dict(load_question_bank()["_meta"]["groups"])


def load_likert_scale() -> dict:
    """返回李克特量表定义。"""
    return dict(load_question_bank()["_meta"]["scale"])


def load_careers() -> list[Career]:
    """返回职业画像列表。"""
    raw = _cached_careers(str(find_data_dir()))
    return [
        Career(
            id=c["id"],
            name=c["name"],
            category=c.get("category", ""),
            holland=c.get("holland", ""),
            summary=c.get("summary", ""),
            entry_path=c.get("entry_path", ""),
            profile={k: float(v) for k, v in c.get("profile", {}).items()},
            role_model_ids=list(c.get("role_model_ids", [])),
        )
        for c in raw["careers"]
    ]


def load_role_models() -> dict[str, RoleModel]:
    """返回 ``{id: RoleModel}`` 映射。"""
    raw = _cached_role_models(str(find_data_dir()))
    out: dict[str, RoleModel] = {}
    for m in raw["role_models"]:
        out[m["id"]] = RoleModel(
            id=m["id"],
            name=m["name"],
            field=m.get("field", ""),
            holland=m.get("holland", ""),
            traits={k: float(v) for k, v in m.get("traits", {}).items()},
            insight=m.get("insight", ""),
        )
    return out


def load_market_stats() -> dict[str, MarketStat]:
    """返回 ``{career_id: MarketStat}`` 映射。"""
    raw = _cached_market(str(find_data_dir()))
    return {
        cid: MarketStat(
            career_id=cid,
            outlook=float(v.get("outlook", 0.6)),
            growth=float(v.get("growth", 0.5)),
            ai_risk=float(v.get("ai_risk", 0.4)),
            salary_band=v.get("salary_band", ""),
            note=v.get("note", ""),
        )
        for cid, v in raw.get("market", {}).items()
    }


def load_market_weights() -> dict[str, float]:
    """返回行业大盘分的权重配置。"""
    raw = _cached_market(str(find_data_dir()))
    return {
        "outlook": float(raw.get("weights", {}).get("outlook", 0.45)),
        "growth": float(raw.get("weights", {}).get("growth", 0.25)),
        "ai_risk_inverse": float(raw.get("weights", {}).get("ai_risk_inverse", 0.30)),
    }
