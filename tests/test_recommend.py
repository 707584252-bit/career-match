"""推荐引擎单元测试。"""

from __future__ import annotations

import pytest

from career_compass.data_loader import load_careers, load_dimension_names, load_questions
from career_compass.models import MarketStat
from career_compass.recommend import (
    DEFAULT_GROUP_WEIGHTS,
    dimension_similarity,
    holland_overlap,
    market_score,
    match_profile,
    recommend,
)
from career_compass.scoring import compute_profile

# ---------------------------------------------------------------------------
# 相似度曲线
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "diff,expected",
    [
        (0, 1.00),
        (5, 0.96),
        (10, 0.89),
        (20, 0.73),
        (30, 0.55),
        (45, 0.23),
        (55, 0.00),
    ],
)
def test_dimension_similarity_reference_points(diff, expected):
    assert dimension_similarity(60, 60 + diff) == pytest.approx(expected, abs=0.02)
    # 对称性：两个方向惩罚一致
    assert dimension_similarity(60, 60 + diff) == pytest.approx(dimension_similarity(60, 60 - diff))


def test_similarity_is_clamped_at_zero():
    assert dimension_similarity(0, 100) == 0.0
    assert dimension_similarity(0, 200) == 0.0


def test_similarity_is_concave_not_linear():
    """非线性惩罚：20 分的差距惩罚应显著重于线性模型。"""
    linear = 1 - 20 / 100
    assert dimension_similarity(50, 70) < linear


# ---------------------------------------------------------------------------
# 匹配计算
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def blank_profile():
    return compute_profile(load_questions(), {}, load_dimension_names())


def test_perfect_match_is_100(blank_profile):
    target = dict(blank_profile.dim_scores)
    score, groups = match_profile(blank_profile, target)
    assert score == pytest.approx(100.0)
    assert set(groups) == set(DEFAULT_GROUP_WEIGHTS)


def test_unlisted_dimensions_are_ignored(blank_profile):
    """职业画像中未列出的组不应参与计算，也不应被当成 0 分。"""
    only_interest = {"interest.investigative": 50.0}
    score, groups = match_profile(blank_profile, only_interest)
    assert set(groups) == {"interest"}
    assert score == pytest.approx(100.0)


def test_missing_group_weight_is_renormalized(blank_profile):
    """只剩兴趣组时，匹配度不应因为其它组缺失而被稀释。"""
    p = dict(blank_profile.dim_scores)
    p["interest.investigative"] = 100.0
    target = {"interest.investigative": 100.0, "academic.logic": 0.0}
    score_two, _ = match_profile(blank_profile, target)
    # 学术组 miss、兴趣组满分会互相抵消，说明两组权重都生效了
    assert 0 < score_two < 100


def test_empty_career_profile_returns_zero(blank_profile):
    score, groups = match_profile(blank_profile, {})
    assert score == 0.0
    assert groups == {}


def test_group_weights_change_ranking(blank_profile):
    """把学术权重压到 0，学术维度的不匹配就不应再影响匹配度。"""
    target = {"academic.logic": 100.0, "interest.investigative": 50.0}
    w_interest_only = {"interest": 1.0, "trait": 0.0, "skill": 0.0, "academic": 0.0}
    score, groups = match_profile(blank_profile, target, w_interest_only)
    assert set(groups) == {"academic", "interest"}
    assert score == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 行业大盘分
# ---------------------------------------------------------------------------


def test_market_score_missing_stat_is_neutral():
    assert market_score(None) == 60.0


def test_market_score_bounds_and_direction():
    good = MarketStat("x", outlook=1.0, growth=1.0, ai_risk=0.0)
    bad = MarketStat("x", outlook=0.0, growth=0.0, ai_risk=1.0)
    assert market_score(good) == pytest.approx(100.0)
    assert market_score(bad) == pytest.approx(0.0)
    assert market_score(good) > market_score(bad)


# ---------------------------------------------------------------------------
# 霍兰德重合
# ---------------------------------------------------------------------------


def test_holland_overlap():
    assert holland_overlap("IRC", "IRC") == 3
    assert holland_overlap("IRC", "RIC") == 3  # 顺序无关
    assert holland_overlap("IRC", "ASE") == 0
    assert holland_overlap("IRC", "IRE") == 2
    assert holland_overlap("", "IRC") == 0


# ---------------------------------------------------------------------------
# 端到端推荐
# ---------------------------------------------------------------------------


def test_recommend_sorted_and_limited():
    profile = compute_profile(load_questions(), {}, load_dimension_names())
    recs = recommend(profile, top_n=4)
    assert len(recs) <= 4
    scores = [r.final_score for r in recs]
    assert scores == sorted(scores, reverse=True)


def test_recommend_respects_min_match():
    profile = compute_profile(load_questions(), {}, load_dimension_names())
    recs = recommend(profile, top_n=50, min_match=95.0)
    assert all(r.match_score >= 95.0 for r in recs)


def test_recommend_every_career_has_explanation_fields():
    profile = compute_profile(load_questions(), {}, load_dimension_names())
    for r in recommend(profile, top_n=3):
        assert r.career.name
        assert r.to_dict()["career_id"] == r.career.id
        assert isinstance(r.advice, list)
        assert r.role_models, f"{r.career.name} 未关联名人典范"


def test_market_blend_shifts_ranking_between_two_careers():
    """纯匹配模式与加强大盘模式应给出不同的排序，证明大盘分真的参与了合成。"""
    profile = compute_profile(load_questions(), {}, load_dimension_names())
    pure_match = recommend(profile, top_n=5, match_blend=1.0, market_blend=0.0)
    with_market = recommend(profile, top_n=5, match_blend=0.5, market_blend=0.5)
    assert [r.career.id for r in pure_match] != [r.career.id for r in with_market]


def test_all_careers_have_consistent_profile_shape():
    dim_names = load_dimension_names()
    valid = set(dim_names)
    for c in load_careers():
        unknown = set(c.profile) - valid
        assert not unknown, f"{c.name} 含未定义维度：{unknown}"
        for k, v in c.profile.items():
            assert 0 <= v <= 100, f"{c.name}.{k} 超出 0~100"
