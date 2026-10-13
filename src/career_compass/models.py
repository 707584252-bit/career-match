"""数据模型定义。

所有模型均为纯数据结构，不包含业务逻辑，便于单元测试与序列化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 维度体系常量
# ---------------------------------------------------------------------------

#: 四大维度（组）及其下的子维度 key，顺序即为报告中的展示顺序
DIMENSION_TREE: dict[str, list[str]] = {
    "academic": ["logic", "numeric", "verbal", "spatial"],
    "skill": ["tech", "creative", "social", "manage"],
    "trait": [
        "openness",
        "conscientiousness",
        "extraversion",
        "agreeableness",
        "stability",
        "grit",
        "risk",
    ],
    "interest": [
        "realistic",
        "investigative",
        "artistic",
        "social",
        "enterprising",
        "conventional",
    ],
}

GROUP_ORDER: list[str] = ["academic", "skill", "trait", "interest"]

#: 霍兰德六种兴趣类型 → 单字母代码
HOLLAND_LETTERS: dict[str, str] = {
    "realistic": "R",
    "investigative": "I",
    "artistic": "A",
    "social": "S",
    "enterprising": "E",
    "conventional": "C",
}

#: 中性维度：这些维度没有「越高越好」的方向，差距分析时不做优劣判断
NEUTRAL_DIMS = {"trait.risk", "trait.extraversion", "trait.agreeableness"}


def all_dim_keys() -> list[str]:
    """返回全部子维度 key，形如 ``academic.logic``。"""
    return [f"{g}.{s}" for g in GROUP_ORDER for s in DIMENSION_TREE[g]]


# ---------------------------------------------------------------------------
# 题目 / 职业 / 名人
# ---------------------------------------------------------------------------


@dataclass
class Question:
    """一道测评题。

    Attributes:
        id: 题目唯一标识，如 ``LOG01``。
        dim: 归属维度，``group.sub`` 格式，如 ``academic.logic``。
        type: ``objective``（客观题，有唯一正确答案）或 ``likert``（李克特自评题）。
        stem: 题干。
        weight: 题目在维度内的基础权重。
        reverse: 是否反向计分（仅李克特题有意义）。
        options: 选项列表。客观题为 4 个选项；李克特题由量表统一生成。
        answer: 客观题正确选项的下标。
        difficulty: 难度系数 0~1，用于客观题的难度加权。
        source: 题项设计所参照的来源说明。
    """

    id: str
    dim: str
    type: str
    stem: str
    weight: float = 1.0
    reverse: bool = False
    options: list[str] = field(default_factory=list)
    answer: int | None = None
    difficulty: float = 0.5
    source: str = ""

    @property
    def group(self) -> str:
        return self.dim.split(".", 1)[0]

    @property
    def sub(self) -> str:
        return self.dim.split(".", 1)[1]


@dataclass
class Career:
    """一个职业画像。"""

    id: str
    name: str
    category: str
    holland: str
    summary: str
    entry_path: str
    profile: dict[str, float]
    role_model_ids: list[str] = field(default_factory=list)


@dataclass
class RoleModel:
    """一位名人典范的能力画像。"""

    id: str
    name: str
    field: str
    holland: str
    traits: dict[str, float]
    insight: str


@dataclass
class MarketStat:
    """一个职业的行业大盘数据。"""

    career_id: str
    outlook: float = 0.6
    growth: float = 0.5
    ai_risk: float = 0.4
    salary_band: str = ""
    note: str = ""


# ---------------------------------------------------------------------------
# 评分结果
# ---------------------------------------------------------------------------


@dataclass
class DimensionScore:
    """单个子维度的得分。"""

    key: str  # academic.logic
    group: str
    sub: str
    name: str  # 中文名
    score: float  # 0~100
    items: int  # 参与的题目数
    answered: int  # 实际作答的题目数
    method: str  # objective | likert | mixed
    reliability: float = 1.0  # 作答一致性 0~1
    raw_rate: float | None = None  # 客观题原始正确率 0~1


@dataclass
class Profile:
    """一次完整测评得到的用户画像。"""

    dim_scores: dict[str, float] = field(default_factory=dict)
    group_scores: dict[str, float] = field(default_factory=dict)
    holland_code: str = ""
    holland_sorted: list[str] = field(default_factory=list)
    quality: float = 0.0  # 数据质量指数 0~1
    completion: float = 0.0  # 完成率 0~1
    details: dict[str, DimensionScore] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    """一条职业推荐结果。"""

    career: Career
    match_score: float  # 画像匹配度 0~100
    market_score: float  # 行业大盘分 0~100
    final_score: float  # 加权总分 0~100
    holland_overlap: int  # 与用户霍兰德代码重合的字母数
    group_match: dict[str, float] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)  # 用户超出该职业要求的维度
    gaps: list[str] = field(default_factory=list)  # 用户低于要求的维度
    advice: list[str] = field(default_factory=list)
    role_models: list[RoleModel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "career_id": self.career.id,
            "career": self.career.name,
            "category": self.career.category,
            "holland": self.career.holland,
            "match_score": round(self.match_score, 1),
            "market_score": round(self.market_score, 1),
            "final_score": round(self.final_score, 1),
            "holland_overlap": self.holland_overlap,
            "strengths": self.strengths,
            "gaps": self.gaps,
            "advice": self.advice,
        }
