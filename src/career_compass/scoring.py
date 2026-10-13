"""评分引擎。

分层：数据层（data_loader）→ 计算层（本模块）→ 渲染层（report）。
本模块为纯函数实现，不读写文件、不触碰 DOM，方便单元测试。

计分规则
--------
客观题（academic.*）
    ``得分 = Σ(题权重 × 难度权重 × 是否答对 × 100) / Σ(题权重 × 难度权重)``
    难度权重 = ``0.4 + 0.6 × difficulty``（把 difficulty 从 [0,1] 映射到 [0.4,1.0]，
    避免过难的题权重被压到 0，也避免简单题完全不计分）。
    难度加权让「答对难题」比「答对简单题」获得更多分数。

李克特题（skill.* / trait.* / interest.*）
    反向计分后再线性映射：``得分 = (均值 - 1) / (5 - 1) × 100``
    一致性信度：``1 - 标准差 / 50``（截断到 [0,1]），用于识别「乱答 / 前后矛盾」。

数据质量指数
    ``quality = 0.55 × 平均一致性 + 0.45 × 完成率``
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable, Sequence

from .models import (
    DIMENSION_TREE,
    GROUP_ORDER,
    HOLLAND_LETTERS,
    NEUTRAL_DIMS,
    DimensionScore,
    Profile,
    Question,
)

LIKERT_MIN = 1
LIKERT_MAX = 5

#: 未作答时的中性填充值（并在 warnings 中提示，不做静默处理）
NEUTRAL_FILL = 50.0

#: 一致性低于该阈值视为「作答前后矛盾」
CONSISTENCY_WARN_THRESHOLD = 0.60

#: 同一选项占比高于该阈值视为「直线作答」
STRAIGHTLINE_THRESHOLD = 0.85


# ---------------------------------------------------------------------------
# 单题计分
# ---------------------------------------------------------------------------


def likert_item_score(value: float, reverse: bool = False) -> float:
    """把李克特单题原始分（1~5）换算为 0~100。"""
    if value is None:
        raise ValueError("李克特题分值不能为 None")
    v = float(value)
    if not (LIKERT_MIN <= v <= LIKERT_MAX):
        raise ValueError(f"李克特题分值必须在 {LIKERT_MIN}~{LIKERT_MAX} 之间，收到 {v}")
    if reverse:
        v = LIKERT_MIN + LIKERT_MAX - v
    return (v - LIKERT_MIN) / (LIKERT_MAX - LIKERT_MIN) * 100.0


def objective_item_score(is_correct: bool) -> float:
    """客观题单题满分或零分。"""
    return 100.0 if is_correct else 0.0


def difficulty_weight(difficulty: float) -> float:
    """把题目难度映射为权重，范围 [0.4, 1.0]。"""
    d = min(max(float(difficulty), 0.0), 1.0)
    return 0.4 + 0.6 * d


# ---------------------------------------------------------------------------
# 维度聚合
# ---------------------------------------------------------------------------


def _aggregate_dimension(
    dim_key: str, name: str, items: Sequence[Question], answers: dict[str, object]
) -> DimensionScore:
    """计算单个子维度的得分。"""
    group, sub = dim_key.split(".", 1)

    answered_items = [q for q in items if q.id in answers and answers[q.id] is not None]
    if not answered_items:
        return DimensionScore(
            key=dim_key,
            group=group,
            sub=sub,
            name=name,
            score=NEUTRAL_FILL,
            items=len(items),
            answered=0,
            method="empty",
            reliability=0.0,
        )

    types = {q.type for q in answered_items}
    method = types.pop() if len(types) == 1 else "mixed"

    obj_items = [q for q in answered_items if q.type == "objective"]
    lik_items = [q for q in answered_items if q.type == "likert"]

    # --- 客观题部分 ---
    obj_score: float | None = None
    raw_rate: float | None = None
    if obj_items:
        num = 0.0
        den = 0.0
        correct = 0
        for q in obj_items:
            w = q.weight * difficulty_weight(q.difficulty)
            is_right = answers[q.id] == q.answer
            correct += 1 if is_right else 0
            num += w * objective_item_score(is_right)
            den += w
        obj_score = num / den if den else 0.0
        raw_rate = correct / len(obj_items)

    # --- 李克特部分 ---
    lik_score: float | None = None
    reliability = 1.0
    lik_item_scores: list[float] = []
    if lik_items:
        num = 0.0
        den = 0.0
        for q in lik_items:
            s = likert_item_score(float(answers[q.id]), reverse=q.reverse)
            lik_item_scores.append(s)
            num += q.weight * s
            den += q.weight
        lik_score = num / den if den else 0.0
        if len(lik_item_scores) >= 2:
            sd = statistics.pstdev(lik_item_scores)
            # 0~100 区间内，极端两极分化时标准差最大为 50
            reliability = max(0.0, min(1.0, 1.0 - sd / 50.0))

    # --- 混合维度：按题量权重合成 ---
    if obj_score is not None and lik_score is not None:
        n_obj = sum(q.weight for q in obj_items)
        n_lik = sum(q.weight for q in lik_items)
        total = n_obj + n_lik
        score = (obj_score * n_obj + lik_score * n_lik) / total if total else 0.0
    elif obj_score is not None:
        score = obj_score
    else:
        score = lik_score if lik_score is not None else NEUTRAL_FILL

    return DimensionScore(
        key=dim_key,
        group=group,
        sub=sub,
        name=name,
        score=round(score, 2),
        items=len(items),
        answered=len(answered_items),
        method=method,
        reliability=round(reliability, 3),
        raw_rate=round(raw_rate, 3) if raw_rate is not None else None,
    )


# ---------------------------------------------------------------------------
# 用户画像
# ---------------------------------------------------------------------------


def compute_profile(
    questions: Sequence[Question],
    answers: dict[str, object],
    dimension_names: dict[str, str] | None = None,
) -> Profile:
    """把作答数据计算为完整用户画像。

    Args:
        questions: 题库。
        answers: ``{question_id: value}``。客观题为选项下标，李克特题为 1~5。
        dimension_names: ``{维度 key: 中文名}``，缺省时用 key 顶替。

    Returns:
        Profile 对象。
    """
    dimension_names = dimension_names or {}
    by_dim: dict[str, list[Question]] = {
        k: [] for k in (f"{g}.{s}" for g in GROUP_ORDER for s in DIMENSION_TREE[g])
    }
    for q in questions:
        by_dim.setdefault(q.dim, []).append(q)

    details: dict[str, DimensionScore] = {}
    for dim_key, items in by_dim.items():
        name = dimension_names.get(dim_key, dim_key)
        details[dim_key] = _aggregate_dimension(dim_key, name, items, answers)

    dim_scores = {k: v.score for k, v in details.items()}

    # 组得分 = 组内子维度等权平均（仅统计有作答的子维度）
    group_scores: dict[str, float] = {}
    for g in GROUP_ORDER:
        vals = [dim_scores[k] for k in by_dim if k.startswith(g + ".") and details[k].answered > 0]
        group_scores[g] = round(sum(vals) / len(vals), 2) if vals else NEUTRAL_FILL

    # 霍兰德代码
    interest_pairs = sorted(
        ((HOLLAND_LETTERS[sub], dim_scores[f"interest.{sub}"]) for sub in DIMENSION_TREE["interest"]),
        key=lambda x: x[1],
        reverse=True,
    )
    holland_sorted = [letter for letter, _ in interest_pairs]
    holland_code = "".join(holland_sorted[:3])

    # --- 数据质量 ---
    total_items = len(questions)
    answered_count = sum(1 for q in questions if answers.get(q.id) is not None)
    completion = answered_count / total_items if total_items else 0.0

    likert_dims = [d for d in details.values() if d.method in ("likert", "mixed") and d.answered > 0]
    consistency = sum(d.reliability for d in likert_dims) / len(likert_dims) if likert_dims else 1.0
    quality = round(0.55 * consistency + 0.45 * completion, 3)

    warnings: list[str] = []
    empty_dims = [d.name for d in details.values() if d.answered == 0]
    if empty_dims:
        warnings.append("以下维度没有作答，已按中性值 50 填充，结果参考价值下降：" + "、".join(empty_dims))
    if completion < 0.9:
        warnings.append(f"完成率仅 {completion:.0%}，建议完成全部题目后再看结论。")
    if consistency < CONSISTENCY_WARN_THRESHOLD and likert_dims:
        warnings.append(
            f"作答一致性偏低（{consistency:.0%}），部分维度内前后答案矛盾，"
            "建议稍后重测，或回想一下是否对题目理解有偏差。"
        )

    lik_answers = [
        int(answers[q.id]) for q in questions if q.type == "likert" and answers.get(q.id) is not None
    ]
    if len(lik_answers) >= 10:
        top_ratio = Counter(lik_answers).most_common(1)[0][1] / len(lik_answers)
        if top_ratio >= STRAIGHTLINE_THRESHOLD:
            warnings.append(
                f"检测到 {top_ratio:.0%} 的自评题选择了同一个选项，"
                "存在「直线作答」倾向，结论的区分度会明显下降。"
            )

    return Profile(
        dim_scores=dim_scores,
        group_scores=group_scores,
        holland_code=holland_code,
        holland_sorted=holland_sorted,
        quality=quality,
        completion=round(completion, 3),
        details=details,
        warnings=warnings,
    )


def group_of(dim_key: str) -> str:
    """取维度 key 所属的组名。"""
    return dim_key.split(".", 1)[0]


def normalize_group_weights(raw: dict[str, float]) -> dict[str, float]:
    """把组权重归一化到总和为 1。"""
    total = sum(v for v in raw.values() if v > 0)
    if total <= 0:
        return {k: 1.0 / len(raw) for k in raw} if raw else {}
    return {k: v / total for k, v in raw.items()}


def top_dims(profile: Profile, n: int = 5, exclude_neutral: bool = False) -> list[DimensionScore]:
    """取得分最高的 n 个子维度。"""
    ds: Iterable[DimensionScore] = profile.details.values()
    if exclude_neutral:
        ds = [d for d in ds if d.key not in NEUTRAL_DIMS]
    return sorted(ds, key=lambda d: d.score, reverse=True)[:n]


def bottom_dims(profile: Profile, n: int = 5) -> list[DimensionScore]:
    """取得分最低的 n 个子维度。"""
    return sorted(profile.details.values(), key=lambda d: d.score)[:n]
