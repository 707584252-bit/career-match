"""评分引擎单元测试。"""

from __future__ import annotations

import pytest

from career_compass.data_loader import load_dimension_names, load_questions
from career_compass.models import DIMENSION_TREE, GROUP_ORDER
from career_compass.scoring import (
    NEUTRAL_FILL,
    compute_profile,
    difficulty_weight,
    likert_item_score,
    normalize_group_weights,
    objective_item_score,
)

# ---------------------------------------------------------------------------
# 单题计分
# ---------------------------------------------------------------------------


def test_likert_min_max_mapping():
    assert likert_item_score(1) == 0.0
    assert likert_item_score(5) == 100.0
    assert likert_item_score(3) == pytest.approx(50.0)


def test_likert_reverse_scoring():
    assert likert_item_score(5, reverse=True) == 0.0
    assert likert_item_score(1, reverse=True) == 100.0
    # 反向 + 正向应互为补数
    for v in range(1, 6):
        assert likert_item_score(v) + likert_item_score(v, reverse=True) == pytest.approx(100.0)


def test_likert_out_of_range_raises():
    with pytest.raises(ValueError):
        likert_item_score(0)
    with pytest.raises(ValueError):
        likert_item_score(6)


def test_objective_score():
    assert objective_item_score(True) == 100.0
    assert objective_item_score(False) == 0.0


def test_difficulty_weight_bounds():
    assert difficulty_weight(0.0) == pytest.approx(0.4)
    assert difficulty_weight(1.0) == pytest.approx(1.0)
    # 越界输入应被截断而不是抛错
    assert difficulty_weight(-3) == pytest.approx(0.4)
    assert difficulty_weight(9) == pytest.approx(1.0)


def test_normalize_group_weights():
    w = normalize_group_weights({"a": 2.0, "b": 6.0})
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["b"] == pytest.approx(0.75)
    # 全为 0 时应退化为等权，而不是除零崩溃
    assert normalize_group_weights({"a": 0, "b": 0}) == {"a": 0.5, "b": 0.5}


# ---------------------------------------------------------------------------
# 画像计算
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def questions():
    return load_questions()


@pytest.fixture(scope="module")
def dim_names():
    return load_dimension_names()


def _all_likert(questions, value):
    return {q.id: value for q in questions if q.type == "likert"}


def _all_objective_correct(questions):
    return {q.id: q.answer for q in questions if q.type == "objective"}


def test_profile_covers_all_21_dimensions(questions, dim_names):
    profile = compute_profile(questions, {}, dim_names)
    assert len(profile.dim_scores) == 21
    for g in GROUP_ORDER:
        for sub in DIMENSION_TREE[g]:
            assert f"{g}.{sub}" in profile.dim_scores


def test_empty_answers_fill_neutral_and_warn(questions, dim_names):
    profile = compute_profile(questions, {}, dim_names)
    assert all(abs(v - NEUTRAL_FILL) < 1e-6 for v in profile.dim_scores.values())
    assert profile.completion == 0.0
    assert profile.warnings, "空作答必须产生提示，不能静默处理"
    assert any("没有作答" in w for w in profile.warnings)


def test_objective_all_correct_gives_full_marks(questions, dim_names):
    answers = _all_objective_correct(questions)
    profile = compute_profile(questions, answers, dim_names)
    for sub in DIMENSION_TREE["academic"]:
        d = profile.details[f"academic.{sub}"]
        assert d.score == pytest.approx(100.0)
        assert d.raw_rate == 1.0


def test_objective_all_wrong_gives_zero(questions, dim_names):
    answers = {q.id: (q.answer + 1) % len(q.options) for q in questions if q.type == "objective"}
    profile = compute_profile(questions, answers, dim_names)
    for sub in DIMENSION_TREE["academic"]:
        assert profile.details[f"academic.{sub}"].score == pytest.approx(0.0)


def test_likert_ceiling_raises_group_scores(questions, dim_names):
    """全选「非常符合」时：无反向题的组应到顶，含反向题的组到不了顶。"""
    answers = _all_likert(questions, 5)
    profile = compute_profile(questions, answers, dim_names)

    # skill 组没有反向计分题
    assert profile.group_scores["skill"] == pytest.approx(100.0)

    # trait 组含 TRS03 / TRG03 两道反向题，interest 组含 INA03
    assert profile.group_scores["trait"] < 100.0
    assert profile.group_scores["interest"] < 100.0
    assert profile.details["trait.stability"].score == pytest.approx(200 / 3, abs=0.1)
    assert profile.details["trait.grit"].score == pytest.approx(200 / 3, abs=0.1)
    assert profile.details["interest.artistic"].score == pytest.approx(200 / 3, abs=0.1)


def test_reverse_items_lower_score_when_agreed(questions, dim_names):
    """对反向计分题也选「非常符合」，应拉低该维度得分。"""
    answers = _all_likert(questions, 5)
    profile = compute_profile(questions, answers, dim_names)
    # trait.stability 中含一道反向题（TRS03），因此不会到 100
    assert profile.details["trait.stability"].score < 100.0
    # interest.artistic 的 INA03 为反向题
    assert profile.details["interest.artistic"].score < 100.0


def test_straight_lining_detected(questions, dim_names):
    answers = _all_likert(questions, 3)
    profile = compute_profile(questions, answers, dim_names)
    assert any("直线作答" in w for w in profile.warnings)
    # 全选同一项时，各题得分完全相同，标准差为 0，一致性应为满分
    assert profile.details["trait.grit"].reliability == pytest.approx(1.0)


def test_inconsistent_answers_lower_reliability(questions, dim_names):
    likert_qs = {g: [q for q in questions if q.dim == f"trait.{s}"] for g, s in [("trait", "grit")]}
    grit_items = likert_qs["trait"]
    answers = {}
    for i, q in enumerate(grit_items):
        answers[q.id] = 1 if i % 2 == 0 else 5  # 同一维度内两极摇摆
    profile = compute_profile(questions, answers, dim_names)
    assert profile.details["trait.grit"].reliability < 0.2


def test_holland_code_is_three_letters(questions, dim_names):
    answers = _all_likert(questions, 4)
    # 让研究型明显最高
    for q in questions:
        if q.dim == "interest.investigative":
            answers[q.id] = 5
        elif q.dim.startswith("interest."):
            answers[q.id] = 1
    profile = compute_profile(questions, answers, dim_names)
    assert len(profile.holland_code) == 3
    assert profile.holland_code[0] == "I"
    assert set(profile.holland_code) <= set("RIASEC")


def test_quality_index_bounds(questions, dim_names):
    answers = _all_likert(questions, 4)
    profile = compute_profile(questions, answers, dim_names)
    assert 0.0 <= profile.quality <= 1.0
    assert profile.completion == pytest.approx(len(answers) / len(questions), abs=1e-3)
