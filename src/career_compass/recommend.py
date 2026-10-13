"""加权职业推荐引擎。

推荐公式
--------
1. **画像匹配度 match**（0~100）
   按四大维度分组计算，职业画像中未列出的维度不参与计算，
   组权重会在实际参与计算的组之间重新归一化：

   ``sim(dim) = clamp(1 - (|用户得分 - 职业要求| / 55) ^ 1.3, 0, 1)``
   ``match = Σ_g 组权重_g × (Σ_dim sim / 已列维度数) × 100``

   相似度用**非线性惩罚**而非线性差值：线性差值过于宽容（差 20 分只扣 0.20），
   会让几乎所有职业都落在 75~90 区间，丧失区分度。改为幂次惩罚后，
   差距越大边际代价越高，不合适的职业会被迅速排到底部。

   **为什么两个方向都罚？** 能力远超岗位要求（overqualification）在组织行为学中
   同样与较低的岗位满意度和更高的离职率相关；对兴趣与特质维度而言，
   取向错配本身就是双向代价。因此采用对称惩罚，理由见 docs/THEORY.md。

   组权重默认 ``兴趣 0.35 / 特质 0.25 / 技能 0.25 / 学术 0.15``，
   依据是职业心理学中「兴趣对职业满意度与留任率的预测力通常高于能力」
   这一反复被验证的经验结论（见 docs/THEORY.md）。

2. **行业大盘分 market**（0~100）
   ``market = 景气度 × 0.45 + 增长性 × 0.25 + (1 - AI替代风险) × 0.30``

3. **最终得分 final**
   ``final = 0.80 × match + 0.20 × market``
   匹配度为主、大盘为辅：大盘数据用于在能力相近的备选之间做排序微调，
   不应当把一个「非常不适合」的职业因为「行业很热」推上去。

4. **霍兰德重合度**作为可解释性指标单独展示，并用于同分时的排序微调。
"""

from __future__ import annotations

from .data_loader import (
    load_careers,
    load_dimension_names,
    load_market_stats,
    load_market_weights,
    load_role_models,
)
from .models import (
    DIMENSION_TREE,
    GROUP_ORDER,
    NEUTRAL_DIMS,
    MarketStat,
    Profile,
    Recommendation,
    RoleModel,
)
from .scoring import normalize_group_weights

#: 默认组权重：兴趣 > 特质 = 技能 > 学术
DEFAULT_GROUP_WEIGHTS: dict[str, float] = {
    "interest": 0.35,
    "trait": 0.25,
    "skill": 0.25,
    "academic": 0.15,
}

#: 匹配度与大盘分的合成权重
MATCH_BLEND = 0.80
MARKET_BLEND = 0.20

#: 判定「优势」与「差距」的阈值（分差）
GAP_THRESHOLD = 12.0

#: 相似度惩罚的标尺：分差达到该值时相似度归零
PENALTY_SPAN = 55.0

#: 相似度惩罚的幂次：>1 使大差距的边际代价急剧上升
PENALTY_EXP = 1.30

#: 每个维度对应的提升建议模板
ADVICE_BY_DIM: dict[str, str] = {
    "academic.logic": "刻意练习结构化拆解：读完一个复杂问题后，先用一句话写下「结论 + 前提」，再逐步验证每个前提是否成立。",
    "academic.numeric": "恢复数感训练：每周完成 3 组快速计算与百分比心算练习，重点补「比例、增长率、概率」三类。",
    "academic.verbal": "提升表达精度：把工作中一段模糊表述改写成「谁、在什么条件下、做什么、达到什么结果」。",
    "academic.spatial": "训练空间表征：动手做一次折叠/装配类任务，或练习看图还原三维结构。",
    "skill.tech": "选一门与你目标岗位直接相关的工具，用「做一个小项目」而非「看完教程」作为完成标准。",
    "skill.creative": "建立输出习惯：每天限时 15 分钟产出一个粗糙方案，先追求数量再追求质量。",
    "skill.social": "练习低风险社交：每周主动与一位不熟的同事或同行聊 10 分钟，话题围绕对方的工作展开。",
    "skill.manage": "从一个小项目开始统筹：把任务拆成清单、标注依赖关系、设一个明确的截止时间并对外承诺。",
    "trait.openness": "主动接触陌生领域：每月读一本与本职完全无关的书，或参加一次跨行业交流。",
    "trait.conscientiousness": "用外置系统替代记性：把所有待办写进同一个清单，并给每项设截止日期与下一步动作。",
    "trait.extraversion": "这个维度没有优劣之分。若目标岗位高频需要对外表达，可以先把「表达」当作一项技能来练，而非改变性格。",
    "trait.agreeableness": "这个维度没有优劣之分。在需要推进结果的场景中，可以刻意练习「明确拒绝」和「提出不同意见」。",
    "trait.stability": "建立压力预案：提前写下「当我焦虑时固定做的三件事」，用流程替代情绪化的临场反应。",
    "trait.grit": "降低启动门槛：把长期目标切成「小到不需要意志力就能开始」的最小步骤，靠频率而非强度取胜。",
    "trait.risk": "这个维度没有优劣之分。稳定型路径（体制、大企业）与高波动路径（创业、销售）各自需要不同的风险管理方式，重点是让选择与自己的承受能力匹配。",
    "interest.realistic": "多接触实物场景：去现场、车间、实验室看一次，真实感受比想象更可靠。",
    "interest.investigative": "把「好奇」升级为「追问」：遇到结论时习惯性多问一层「这个结论的机制是什么」。",
    "interest.artistic": "建立作品集：哪怕很小，也要留下可被他人看到的完整产出。",
    "interest.social": "找一个能帮到别人的场景持续投入，比如带新人、做志愿者、写科普。",
    "interest.enterprising": "练习把想法变成提案：写一份 1 页纸的方案，包含目标、路径、资源需求与预期回报。",
    "interest.conventional": "建立个人规范：给重复性事务固定模板与检查清单，把「严谨」变成可复用的资产。",
}


# ---------------------------------------------------------------------------
# 匹配计算
# ---------------------------------------------------------------------------


def dimension_similarity(user: float, target: float) -> float:
    """单个维度的拟合度，返回 0~1。

    ``sim = clamp(1 - (|diff| / 55) ^ 1.3, 0, 1)``

    Reference points（便于理解曲线的形状）::

        分差   0   5    10    20    30    45    55
        拟合  1.0  0.96 0.89 0.73 0.55 0.23 0.0
    """
    diff = abs(float(user) - float(target))
    if diff <= 0:
        return 1.0
    penalty = (diff / PENALTY_SPAN) ** PENALTY_EXP
    return max(0.0, min(1.0, 1.0 - penalty))


def match_profile(
    profile: Profile,
    career_profile: dict[str, float],
    group_weights: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    """计算用户画像与某个职业画像的匹配度。

    Args:
        profile: 用户画像。
        career_profile: 职业画像稀疏向量 ``{维度 key: 0~100}``。
        group_weights: 组权重，缺省用 :data:`DEFAULT_GROUP_WEIGHTS`。

    Returns:
        ``(匹配度 0~100, {组: 该组相似度 0~100})``
    """
    gw = normalize_group_weights(group_weights or DEFAULT_GROUP_WEIGHTS)

    per_group: dict[str, float] = {}
    for g in GROUP_ORDER:
        dims = {k: v for k, v in career_profile.items() if k.startswith(g + ".")}
        if not dims:
            continue
        sims = []
        for k, target in dims.items():
            user = profile.dim_scores.get(k)
            if user is None:
                continue
            sims.append(dimension_similarity(user, target))
        if sims:
            per_group[g] = sum(sims) / len(sims) * 100.0

    if not per_group:
        return 0.0, {}

    active_weight = sum(gw[g] for g in per_group)
    if active_weight <= 0:
        return 0.0, per_group

    match = sum(gw[g] * s for g, s in per_group.items()) / active_weight
    return round(match, 2), {g: round(s, 2) for g, s in per_group.items()}


def market_score(stat: MarketStat | None, weights: dict[str, float] | None = None) -> float:
    """计算行业大盘分 0~100。"""
    if stat is None:
        # 无大盘数据时给中性分，避免因为数据缺失而惩罚该职业
        return 60.0
    w = weights or {"outlook": 0.45, "growth": 0.25, "ai_risk_inverse": 0.30}
    return round(
        (
            stat.outlook * w["outlook"]
            + stat.growth * w["growth"]
            + (1.0 - stat.ai_risk) * w["ai_risk_inverse"]
        )
        * 100.0,
        2,
    )


def holland_overlap(user_code: str, career_code: str) -> int:
    """计算用户与职业霍兰德代码的重合字母数。"""
    if not user_code or not career_code:
        return 0
    return len(set(user_code) & set(career_code))


# ---------------------------------------------------------------------------
# 差距分析与建议
# ---------------------------------------------------------------------------


def analyse_gap(
    profile: Profile,
    career_profile: dict[str, float],
    dim_names: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    """对比用户与职业要求，产出（优势、差距、建议）。"""
    strengths: list[str] = []
    gaps: list[str] = []
    advice: list[str] = []

    for dim_key, target in sorted(career_profile.items(), key=lambda kv: kv[1], reverse=True):
        user = profile.dim_scores.get(dim_key)
        if user is None:
            continue
        name = dim_names.get(dim_key, dim_key)
        diff = user - target
        is_neutral = dim_key in NEUTRAL_DIMS

        if diff >= GAP_THRESHOLD:
            tag = "（该维度无优劣之分，仅代表取向差异）" if is_neutral else ""
            strengths.append(f"{name} 高于该职业要求 {diff:.0f} 分{tag}")
        elif diff <= -GAP_THRESHOLD:
            if is_neutral:
                gaps.append(f"{name} 低于该职业常见取向 {abs(diff):.0f} 分（并非缺陷，但需要心理准备）")
            else:
                gaps.append(f"{name} 低于该职业要求 {abs(diff):.0f} 分")

    # 建议优先针对「要求高但用户差距大」的维度，最多给 3 条
    for dim_key, target in sorted(career_profile.items(), key=lambda kv: kv[1], reverse=True):
        if len(advice) >= 3:
            break
        user = profile.dim_scores.get(dim_key)
        if user is None or dim_key in NEUTRAL_DIMS:
            continue
        if user - target <= -GAP_THRESHOLD:
            tip = ADVICE_BY_DIM.get(dim_key)
            if tip:
                advice.append(f"{dim_names.get(dim_key, dim_key)}：{tip}")
        elif user - target <= -GAP_THRESHOLD / 2:
            tip = ADVICE_BY_DIM.get(dim_key)
            if tip:
                advice.append(f"{dim_names.get(dim_key, dim_key)}（略微不足）：{tip}")

    return strengths[:4], gaps[:4], advice


def match_role_models(profile: Profile, limit: int = 3) -> list[tuple[RoleModel, float]]:
    """找出与用户能力画像最接近的名人典范。

    Returns:
        ``[(RoleModel, 匹配度)]``，按匹配度降序。
    """
    models = load_role_models()
    out: list[tuple[RoleModel, float]] = []
    for m in models.values():
        score, _ = match_profile(profile, m.traits)
        out.append((m, score))
    out.sort(key=lambda x: x[1], reverse=True)
    return out[:limit]


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def recommend(
    profile: Profile,
    top_n: int = 5,
    match_blend: float = MATCH_BLEND,
    market_blend: float = MARKET_BLEND,
    min_match: float = 40.0,
) -> list[Recommendation]:
    """生成职业推荐列表。

    Args:
        profile: 用户画像。
        top_n: 返回条数。
        match_blend / market_blend: 匹配度与大盘分的合成权重，会自动归一化。
        min_match: 匹配度下限，低于该值的职业不进入推荐（避免推荐明显不适合的方向）。

    Returns:
        按最终得分降序排列的 :class:`Recommendation` 列表。
    """
    careers = load_careers()
    market = load_market_stats()
    mw = load_market_weights()
    dim_names = load_dimension_names()
    role_models = load_role_models()

    total = match_blend + market_blend
    wm = match_blend / total if total else MATCH_BLEND
    wmkt = market_blend / total if total else MARKET_BLEND

    results: list[Recommendation] = []
    for career in careers:
        m_score, per_group = match_profile(profile, career.profile)
        if m_score < min_match:
            continue

        mk_score = market_score(market.get(career.id), mw)
        overlap = holland_overlap(profile.holland_code, career.holland)
        final = wm * m_score + wmkt * mk_score

        strengths, gaps, advice = analyse_gap(profile, career.profile, dim_names)
        models = [role_models[i] for i in career.role_model_ids if i in role_models]

        results.append(
            Recommendation(
                career=career,
                match_score=m_score,
                market_score=mk_score,
                final_score=round(final, 2),
                holland_overlap=overlap,
                group_match=per_group,
                strengths=strengths,
                gaps=gaps,
                advice=advice,
                role_models=models,
            )
        )

    # 排序：最终得分 > 霍兰德重合度 > 匹配度
    results.sort(key=lambda r: (r.final_score, r.holland_overlap, r.match_score), reverse=True)
    return results[:top_n]


def describe_group_scores(profile: Profile, group_names: dict[str, str]) -> list[str]:
    """把四大维度得分翻译成人话。"""
    lines: list[str] = []
    for g in GROUP_ORDER:
        score = profile.group_scores.get(g, 0.0)
        if score >= 75:
            level = "显著优势"
        elif score >= 62:
            level = "较强"
        elif score >= 50:
            level = "中等"
        else:
            level = "相对偏弱"
        lines.append(f"{group_names.get(g, g)}：{score:.0f} 分 · {level}")
    return lines


def dimension_tree_keys() -> dict[str, list[str]]:
    """暴露维度树，供报告层遍历。"""
    return {g: list(DIMENSION_TREE[g]) for g in GROUP_ORDER}
