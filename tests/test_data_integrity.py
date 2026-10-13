"""数据完整性测试。

这组测试的作用是「数据一改就报警」：题库、职业画像、名人画像、大盘数据
是四个独立文件，靠 id 互相引用，最容易在手工编辑时引入静默错误。
"""

from __future__ import annotations

from career_compass.data_loader import (
    load_careers,
    load_dimension_names,
    load_group_names,
    load_likert_scale,
    load_market_stats,
    load_questions,
    load_role_models,
)
from career_compass.models import DIMENSION_TREE, GROUP_ORDER, HOLLAND_LETTERS

QUESTIONS = load_questions()
CAREERS = load_careers()
ROLE_MODELS = load_role_models()
MARKET = load_market_stats()
DIM_NAMES = load_dimension_names()
GROUP_NAMES = load_group_names()


# ---------------------------------------------------------------------------
# 题库
# ---------------------------------------------------------------------------


def test_question_ids_unique():
    ids = [q.id for q in QUESTIONS]
    assert len(ids) == len(set(ids)), "题目 id 重复"


def test_question_count_is_reasonable():
    # 一份职业测评 40~90 题是合理区间，太少信度不足，太多会劝退作答者
    assert 40 <= len(QUESTIONS) <= 90


def test_every_question_dim_is_defined():
    for q in QUESTIONS:
        assert q.dim in DIM_NAMES, f"{q.id} 使用了未定义的维度 {q.dim}"
        assert q.dim in {f"{g}.{s}" for g in GROUP_ORDER for s in DIMENSION_TREE[g]}


def test_every_dimension_has_enough_items():
    """每个子维度至少 3 题，否则内部一致性无法评估。"""
    counts: dict = {}
    for q in QUESTIONS:
        counts[q.dim] = counts.get(q.dim, 0) + 1
    for g in GROUP_ORDER:
        for sub in DIMENSION_TREE[g]:
            key = f"{g}.{sub}"
            assert counts.get(key, 0) >= 3, f"{key} 只有 {counts.get(key, 0)} 题，少于 3 题"


def test_objective_questions_well_formed():
    for q in QUESTIONS:
        if q.type != "objective":
            continue
        assert len(q.options) >= 3, f"{q.id} 选项少于 3 个"
        assert q.answer is not None, f"{q.id} 缺少正确答案"
        assert 0 <= q.answer < len(q.options), f"{q.id} 正确答案下标越界"
        assert 0.0 <= q.difficulty <= 1.0, f"{q.id} 难度越界"
        assert len(set(q.options)) == len(q.options), f"{q.id} 存在重复选项"


def test_likert_questions_have_no_objective_fields():
    for q in QUESTIONS:
        if q.type != "likert":
            continue
        assert q.answer is None, f"{q.id} 是自评题却带正确答案"
        assert not q.options, f"{q.id} 是自评题却带自定义选项"


def test_objective_first_option_is_not_always_answer():
    """正确答案不能总在同一位置，否则会被「全选 A」刷分。"""
    positions = [q.answer for q in QUESTIONS if q.type == "objective"]
    assert len(set(positions)) >= 3, f"正确答案分布过于集中：{positions}"


def test_reverse_items_exist():
    """反向计分题用于识别「一路同意」的作答，必须存在。"""
    assert any(q.reverse for q in QUESTIONS), "题库中没有任何反向计分题"


# ---------------------------------------------------------------------------
# 职业画像
# ---------------------------------------------------------------------------


def test_career_ids_unique():
    ids = [c.id for c in CAREERS]
    assert len(ids) == len(set(ids))


def test_career_holland_code_valid():
    for c in CAREERS:
        assert 2 <= len(c.holland) <= 3, f"{c.name} 的霍兰德代码长度异常：{c.holland}"
        assert all(ch in HOLLAND_LETTERS.values() for ch in c.holland), f"{c.name} 代码非法：{c.holland}"


def test_career_profile_covers_multiple_groups():
    """职业画像至少要覆盖 3 个组，否则匹配会退化成单维度比较。"""
    for c in CAREERS:
        groups = {k.split(".")[0] for k in c.profile}
        assert len(groups) >= 3, f"{c.name} 只覆盖了 {groups}"
        assert len(c.profile) >= 8, f"{c.name} 画像维度太少（{len(c.profile)}）"


def test_career_role_models_exist():
    for c in CAREERS:
        assert c.role_model_ids, f"{c.name} 没有关联任何名人典范"
        for rid in c.role_model_ids:
            assert rid in ROLE_MODELS, f"{c.name} 引用了不存在的名人 {rid}"


# ---------------------------------------------------------------------------
# 名人典范
# ---------------------------------------------------------------------------


def test_role_model_profiles_valid():
    for m in ROLE_MODELS.values():
        assert m.name and m.insight
        assert len(m.traits) >= 5, f"{m.name} 特质维度太少"
        for k, v in m.traits.items():
            assert k in DIM_NAMES, f"{m.name} 含未知维度 {k}"
            assert 0 <= v <= 100


def test_every_role_model_is_referenced():
    used = {rid for c in CAREERS for rid in c.role_model_ids}
    unused = set(ROLE_MODELS) - used
    assert not unused, f"以下名人未被任何职业引用：{unused}"


# ---------------------------------------------------------------------------
# 行业大盘
# ---------------------------------------------------------------------------


def test_market_covers_every_career():
    missing = {c.id for c in CAREERS} - set(MARKET)
    assert not missing, f"以下职业缺少大盘数据：{missing}"


def test_market_values_in_unit_range():
    for cid, s in MARKET.items():
        for name, v in (("outlook", s.outlook), ("growth", s.growth), ("ai_risk", s.ai_risk)):
            assert 0.0 <= v <= 1.0, f"{cid}.{name} 越界：{v}"


# ---------------------------------------------------------------------------
# 元数据
# ---------------------------------------------------------------------------


def test_scale_and_group_names_complete():
    scale = load_likert_scale()
    assert scale["min"] == 1 and scale["max"] == 5
    assert len(scale["labels"]) == 5
    assert set(GROUP_NAMES) == set(GROUP_ORDER)
    assert len(DIM_NAMES) == sum(len(v) for v in DIMENSION_TREE.values()) == 21
