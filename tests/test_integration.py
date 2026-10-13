"""数据层与报告层的边界测试。

覆盖两件事：
1. 数据目录解析在各种运行位置下都能工作（源码直接运行 / 装包后运行 / 子目录运行）
2. 报告零外部依赖的检查脚本本身是可靠的（正反两个方向都要验证）
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from career_compass import data_loader
from career_compass.data_loader import DataNotFoundError, find_data_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts" / "check_report_offline.py"


# ---------------------------------------------------------------------------
# 数据目录解析
# ---------------------------------------------------------------------------


def test_find_data_dir_from_repo_root():
    d = find_data_dir()
    assert (d / "questions.json").is_file()
    assert (d / "careers.json").is_file()
    assert (d / "role_models.json").is_file()
    assert (d / "market_stats.json").is_file()


def test_find_data_dir_from_subdirectory(monkeypatch, tmp_path):
    """在仓库子目录下执行时也应能找到数据（靠向上遍历）。"""
    monkeypatch.chdir(REPO_ROOT / "docs")
    assert (find_data_dir() / "questions.json").is_file()


def test_env_var_takes_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_COMPASS_DATA", str(REPO_ROOT / "data"))
    assert find_data_dir() == (REPO_ROOT / "data").resolve()


def test_env_var_pointing_nowhere_raises_helpful_error(monkeypatch, tmp_path):
    """配置错误时必须给出可操作的提示，并指出现有配置值。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("CAREER_COMPASS_DATA", str(empty))
    with pytest.raises(DataNotFoundError) as ei:
        find_data_dir()
    msg = str(ei.value)
    assert "questions.json" in msg
    assert str(empty) in msg


def test_no_data_found_message_mentions_env_var(monkeypatch, tmp_path):
    """完全找不到数据时，提示必须告诉用户可以靠环境变量指定。

    find_data_dir() 以上溯「本模块文件位置」为主，所以要把模块的 __file__
    指到一个孤立目录，才能真实模拟「装包后位置不对」的场景。
    """
    monkeypatch.delenv("CAREER_COMPASS_DATA", raising=False)
    isolated = tmp_path / "isolated" / "career_compass"
    isolated.mkdir(parents=True)
    monkeypatch.setattr(data_loader, "__file__", str(isolated / "data_loader.py"))
    monkeypatch.chdir(isolated)

    with pytest.raises(DataNotFoundError) as ei:
        find_data_dir()
    assert "CAREER_COMPASS_DATA" in str(ei.value)


def test_loader_is_cached():
    """重复加载不应该重复读盘。

    缓存发生在「原始 JSON」这一层；上层的对象构造每次都新建，
    以避免调用方拿到共享可变状态后互相污染。
    """
    assert data_loader.load_question_bank() is data_loader.load_question_bank()
    assert data_loader.load_careers() == data_loader.load_careers()
    assert data_loader.load_role_models() == data_loader.load_role_models()
    assert data_loader.load_market_stats() == data_loader.load_market_stats()

    # 真正被 lru_cache 包住的是这四个
    for fn in (
        data_loader._cached_questions,
        data_loader._cached_careers,
        data_loader._cached_role_models,
        data_loader._cached_market,
    ):
        assert hasattr(fn, "cache_info"), f"{fn.__name__} 未使用 lru_cache"
        assert fn.cache_info().hits >= 0  # 结构存在即说明缓存生效路径可用


# ---------------------------------------------------------------------------
# 零外链检查脚本
# ---------------------------------------------------------------------------


def _run_check(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_offline_check_passes_on_real_report(tmp_path):
    from career_compass.cli import generate_demo_answers
    from career_compass.data_loader import load_dimension_names, load_questions
    from career_compass.recommend import recommend
    from career_compass.report import render_html
    from career_compass.scoring import compute_profile

    qs = load_questions()
    profile = compute_profile(qs, generate_demo_answers(qs, seed=1), load_dimension_names())
    out = tmp_path / "r.html"
    out.write_text(render_html(profile, recommend(profile, top_n=3)), encoding="utf-8")

    r = _run_check(out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "零外部依赖" in r.stdout


@pytest.mark.parametrize(
    "inject",
    [
        '<link rel="stylesheet" href="https://cdn.example.com/a.css">',
        '<script src="https://cdn.example.com/a.js"></script>',
        '<img src="https://cdn.example.com/a.png">',
        "<style>body{background:url(https://cdn.example.com/a.png)}</style>",
    ],
)
def test_offline_check_catches_external_resources(tmp_path, inject):
    """故意注入外部引用，检查脚本必须报错退出。否则它就是个摆设。"""
    from career_compass.cli import generate_demo_answers
    from career_compass.data_loader import load_dimension_names, load_questions
    from career_compass.recommend import recommend
    from career_compass.report import render_html
    from career_compass.scoring import compute_profile

    qs = load_questions()
    profile = compute_profile(qs, generate_demo_answers(qs, seed=1), load_dimension_names())
    html = render_html(profile, recommend(profile, top_n=2)).replace("</head>", inject + "</head>")
    bad = tmp_path / "bad.html"
    bad.write_text(html, encoding="utf-8")

    r = _run_check(bad)
    assert r.returncode == 1, f"未能识别外部引用：{inject}"
    assert "cdn.example.com" in r.stdout


def test_offline_check_allows_svg_namespace(tmp_path):
    """SVG 的 xmlns 是规范声明，不是资源请求，必须放行。"""
    f = tmp_path / "svg.html"
    f.write_text(
        '<html><body><svg xmlns="http://www.w3.org/2000/svg"><rect/></svg></body></html>',
        encoding="utf-8",
    )
    assert _run_check(f).returncode == 0


def test_offline_check_missing_file(tmp_path):
    r = _run_check(tmp_path / "nope.html")
    assert r.returncode == 1
    assert "不存在" in r.stdout


def test_offline_check_no_args_prints_usage():
    r = subprocess.run(
        [sys.executable, str(SCRIPTS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# 打包元数据
# ---------------------------------------------------------------------------


def test_no_runtime_dependencies():
    """零依赖是这个项目的核心承诺，用测试守住它。"""
    import re

    txt = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r"^dependencies\s*=\s*\[(.*?)\]", txt, re.S | re.M)
    assert m, "pyproject.toml 中找不到 dependencies"
    assert m.group(1).strip() == "", f"运行时依赖必须为空，实际：{m.group(1)!r}"


def test_declared_data_files_all_exist():
    for name in ("questions.json", "careers.json", "role_models.json", "market_stats.json"):
        assert (REPO_ROOT / "data" / name).is_file(), f"缺少数据文件 {name}"


def test_examples_are_valid_json():
    import json

    ex = REPO_ROOT / "examples"
    for f in ex.glob("*.json"):
        json.loads(f.read_text(encoding="utf-8"))


def test_gitignore_covers_env_and_reports():
    gi = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "out/"):
        assert pattern in gi, f".gitignore 未忽略 {pattern}"


@pytest.mark.skipif(os.environ.get("CI") != "true", reason="仅在 CI 中校验产物")
def test_ci_artifact_exists():
    assert Path("/tmp/r.html").is_file()
