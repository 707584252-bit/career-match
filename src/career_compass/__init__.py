"""career-compass：职业能力测评与加权职业推荐引擎。

零第三方依赖，纯标准库实现。

典型用法::

    from career_compass.data_loader import load_dimension_names, load_questions
    from career_compass.scoring import compute_profile
    from career_compass.recommend import recommend
    from career_compass.report import render_html

    questions = load_questions()
    answers = {"LOG01": 2, "NUM01": 1, ...}
    profile = compute_profile(questions, answers, load_dimension_names())
    recs = recommend(profile, top_n=5)
    html = render_html(profile, recs)
"""

from .data_loader import (
    DataNotFoundError,
    load_careers,
    load_dimension_names,
    load_group_names,
    load_market_stats,
    load_question_bank,
    load_questions,
    load_role_models,
)
from .llm import DeepSeekClient, LLMError, MissingAPIKeyError, generate_narrative
from .models import (
    DIMENSION_TREE,
    GROUP_ORDER,
    Career,
    DimensionScore,
    Profile,
    Question,
    Recommendation,
    RoleModel,
)
from .recommend import DEFAULT_GROUP_WEIGHTS, match_profile, recommend
from .report import render_html, render_markdown
from .scoring import compute_profile

__version__ = "1.0.0"

__all__ = [
    "__version__",
    # 数据
    "DataNotFoundError",
    "load_questions",
    "load_question_bank",
    "load_dimension_names",
    "load_group_names",
    "load_careers",
    "load_role_models",
    "load_market_stats",
    # 模型
    "Question",
    "Career",
    "RoleModel",
    "DimensionScore",
    "Profile",
    "Recommendation",
    "DIMENSION_TREE",
    "GROUP_ORDER",
    # 计算
    "compute_profile",
    "match_profile",
    "recommend",
    "DEFAULT_GROUP_WEIGHTS",
    # 渲染
    "render_html",
    "render_markdown",
    # LLM
    "DeepSeekClient",
    "LLMError",
    "MissingAPIKeyError",
    "generate_narrative",
]
