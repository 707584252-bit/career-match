"""答题页生成与作答导入的测试。

这个模块专门盯两件容易出错、且出错代价很大的事：

1. **泄题** —— 答题页是给被测者打开的文件，一旦把 ``answer`` 字段渲染进去，
   查看源码就能看到答案，整份测评立刻失去意义。
2. **作答编码不一致** —— 客观题在评分引擎里是 0 基下标、李克特题是 1~5。
   页面导出时若用了 1 基，客观题会**整体错位**：选第 1 项被当成第 2 项。
   这种错误不会报错、不会崩溃，只会静默给出错误的分数，所以必须有测试守着。
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from career_compass.data_loader import (
    load_dimension_names,
    load_group_names,
    load_likert_scale,
    load_questions,
)
from career_compass.models import DIMENSION_TREE, GROUP_ORDER, Question
from career_compass.questionnaire import (
    STORAGE_KEY,
    build_questionnaire_payload,
    render_questionnaire,
)
from career_compass.scoring import compute_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
IMPORT_SCRIPT = REPO_ROOT / "scripts" / "import_answers.py"


@pytest.fixture(scope="module")
def payload():
    return build_questionnaire_payload(
        load_questions(), load_dimension_names(), load_group_names(), load_likert_scale()
    )


@pytest.fixture(scope="module")
def html():
    return render_questionnaire(
        load_questions(), load_dimension_names(), load_group_names(), load_likert_scale()
    )


def _flatten(payload: dict) -> list[dict]:
    return [q for g in payload["groups"] for d in g["dims"] for q in d["questions"]]


def _embedded_data(html: str) -> dict:
    """从页面里把 DATA 载荷抠出来。"""
    m = re.search(r"var DATA = (\{.*?\});\n", html, re.S)
    assert m, "页面里找不到 DATA 载荷"
    return json.loads(m.group(1).replace("\\u003c", "<"))


# ---------------------------------------------------------------------------
# 载荷结构
# ---------------------------------------------------------------------------


def test_payload_covers_every_question_exactly_once(payload):
    bank = {q.id for q in load_questions()}
    got = [q["id"] for q in _flatten(payload)]
    assert len(got) == len(set(got)), "同一题号出现了多次"
    assert set(got) == bank


def test_payload_total_matches_actual_count(payload):
    assert payload["total"] == len(_flatten(payload))


def test_payload_leaks_no_answer_fields(payload):
    """最重要的一条：答案、难度、权重、来源都不许出现在给被测者的文件里。"""
    forbidden = {"answer", "difficulty", "weight", "source", "reverse"}
    for q in _flatten(payload):
        leaked = forbidden & set(q)
        assert not leaked, f"{q['id']} 泄漏了字段 {leaked}"


def test_payload_has_no_answer_key_anywhere(html):
    """即使字段名换位置，序列化后的文本里也不该出现答案键。"""
    assert '"answer"' not in html


def test_objective_questions_keep_options_likert_do_not(payload):
    for q in _flatten(payload):
        if q["type"] == "objective":
            assert len(q["options"]) >= 2, f"{q['id']} 客观题应带选项"
            assert all(isinstance(o, str) and o for o in q["options"])
        else:
            assert q["options"] == [], f"{q['id']} 自评题不应带选项"


def test_groups_follow_group_order(payload):
    assert [g["key"] for g in payload["groups"]] == GROUP_ORDER


def test_dims_within_group_follow_dimension_tree(payload):
    """子维度顺序应与 models.DIMENSION_TREE 一致，让同维度题聚在一起。"""
    for g in payload["groups"]:
        got = [d["key"].split(".", 1)[1] for d in g["dims"]]
        expected = [s for s in DIMENSION_TREE[g["key"]] if s in got]
        assert got == expected, f"{g['key']} 的子维度顺序与 DIMENSION_TREE 不符"


def test_question_count_per_group_is_nonzero(payload):
    for g in payload["groups"]:
        assert sum(len(d["questions"]) for d in g["dims"]) > 0


def test_likert_labels_come_from_scale(payload):
    assert payload["labels"] == load_likert_scale()["labels"]


# ---------------------------------------------------------------------------
# 渲染出的 HTML
# ---------------------------------------------------------------------------


def test_html_is_self_contained(html):
    """与报告同一条硬规则：不引用任何外部资源，断网也能打开。"""
    urls = set(re.findall(r"https?://[^\"'\s)]+", html))
    assert not urls, f"答题页引用了外部资源：{urls}"
    assert "<link" not in html, "不应有外链样式表"
    assert "<img" not in html


def test_html_has_no_unreplaced_placeholder(html):
    assert "/*__WB_" not in html, "模板占位符没被替换掉"


def test_html_embeds_the_full_payload(html, payload):
    data = _embedded_data(html)
    assert data["total"] == payload["total"]
    assert len(_flatten(data)) == len(_flatten(payload))


def test_html_escapes_script_tags_in_question_text():
    """题面里若出现 ``</script>``，不转义会把脚本标签提前闭合，页面直接崩。"""
    evil = Question(
        id="X1",
        dim="skill.tech",
        type="likert",
        stem="正常题面</script><script>alert(1)</script>",
    )
    page = render_questionnaire(
        [evil],
        load_dimension_names(),
        load_group_names(),
        load_likert_scale(),
    )
    assert "</script><script>alert(1)" not in page
    # 数据仍然能正确取回，说明只是转义而非丢内容
    assert _embedded_data(page)["groups"][0]["dims"][0]["questions"][0]["stem"] == evil.stem


def test_html_exposes_progress_and_export_controls(html):
    for needle in ("btn-export", "btn-copy", "btn-jump", "barfill", "已答"):
        assert needle in html, f"页面缺少 {needle}"


def test_html_uses_versioned_storage_key(html):
    """localStorage 键要带版本号，将来改题目结构时可以平滑失效。"""
    assert json.dumps(STORAGE_KEY) in html
    assert "v1" in STORAGE_KEY


def test_html_renders_every_question_id(html):
    """题目必须真的进入页面，而不是只存在于载荷里。"""
    for q in load_questions():
        assert q.id in html, f"页面里找不到题号 {q.id}"


def test_payload_option_order_matches_bank_order(payload):
    """页面按顺序渲染选项；顺序错位同样会导致静默错分。"""
    bank = {q.id: q for q in load_questions()}
    for q in _flatten(payload):
        if q["type"] == "objective":
            assert q["options"] == bank[q["id"]].options


# ---------------------------------------------------------------------------
# 作答编码契约（0 基客观题 / 1~5 李克特）
# ---------------------------------------------------------------------------


def test_objective_answers_are_zero_based_indices():
    """把「全部答对」喂回评分引擎，验证页面的下标约定与 scoring 一致。

    页面里客观题的取值是 ``选项下标``（第 1 个选项 = 0）。若哪天改成 1 基，
    这条断言会挂——这正是它存在的意义。
    """
    questions = load_questions()
    answers = {q.id: q.answer for q in questions if q.type == "objective"}
    assert all(isinstance(v, int) for v in answers.values())

    profile = compute_profile(questions, answers, load_dimension_names())
    for sub in ("logic", "numeric", "verbal", "spatial"):
        assert profile.details[f"academic.{sub}"].score == pytest.approx(100.0), (
            f"academic.{sub} 全答对却不是满分，说明下标约定与 scoring 不一致"
        )


def test_likert_answers_use_raw_1_to_5():
    """李克特题导出的是原始 1~5；反向计分是 scoring 的职责，页面不得插手。

    验证方式：全选 5 分时，不含反向题的维度应满分，含反向题的维度应低于满分。
    如果页面错误地做了预翻转，两者的结果会正好反过来。
    """
    questions = load_questions()
    answers = {q.id: 5 for q in questions if q.type == "likert"}
    profile = compute_profile(questions, answers, load_dimension_names())

    reverse_dims = {q.dim for q in questions if q.type == "likert" and q.reverse}
    assert reverse_dims, "题库里应有反向题，否则这个测试就失去意义了"

    checked = 0
    for dim, detail in profile.details.items():
        if not dim.startswith(("skill.", "trait.", "interest.")):
            continue
        if dim in reverse_dims:
            assert detail.score < 100.0, f"{dim} 含反向题，全选 5 不该拿到满分"
        else:
            assert detail.score == pytest.approx(100.0), f"{dim} 无反向题，全选 5 应满分"
        checked += 1
    assert checked >= 10, "应覆盖到大多数自评维度"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_questionnaire_writes_self_contained_page(tmp_path):
    from career_compass.cli import main

    out = tmp_path / "q.html"
    assert main(["questionnaire", "-o", str(out)]) == 0
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "职业能力测评问卷" in text
    assert not re.findall(r"https?://", text)


def test_cli_questionnaire_creates_parent_directory(tmp_path):
    from career_compass.cli import main

    out = tmp_path / "a" / "b" / "q.html"
    assert main(["questionnaire", "-o", str(out)]) == 0
    assert out.is_file()


# ---------------------------------------------------------------------------
# 导入脚本
# ---------------------------------------------------------------------------


def _load_import_script():
    spec = importlib.util.spec_from_file_location("import_answers", IMPORT_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def importer():
    return _load_import_script()


def test_parse_accepts_wrapped_and_bare(importer):
    wrapped = json.dumps({"meta": {"tool": "career-compass"}, "answers": {"LOG01": 2}})
    bare = json.dumps({"LOG01": 2})
    assert importer.parse_answers(wrapped) == {"LOG01": 2}
    assert importer.parse_answers(bare) == {"LOG01": 2}


def test_parse_drops_nulls_and_blank_keys(importer):
    text = json.dumps({"answers": {"LOG01": 2, "LOG02": None, "": 3}})
    assert importer.parse_answers(text) == {"LOG01": 2}


@pytest.mark.parametrize(
    "text",
    ["不是 JSON", "[]", "{}", json.dumps({"answers": {}}), json.dumps({"answers": "x"})],
)
def test_parse_rejects_bad_input(importer, text):
    with pytest.raises(ValueError):
        importer.parse_answers(text)


def test_validate_flags_unknown_type_and_range(importer):
    unknown, bad_type, bad_range = importer.validate_against_bank(
        {
            "NOT_A_REAL_ID": 1,  # 题库里没有
            "LOG01": "二",  # 类型不对
            "LOG02": 99,  # 客观题下标越界
            "SKT01": 9,  # 李克特超出 1~5
            "SKT02": 3,  # 正常
        }
    )
    assert unknown == ["NOT_A_REAL_ID"]
    assert bad_type == ["LOG01"]
    assert set(bad_range) == {"LOG02", "SKT01"}


def test_validate_accepts_a_clean_answer_set(importer):
    questions = load_questions()
    answers = {q.id: (q.answer if q.type == "objective" else 3) for q in questions}
    unknown, bad_type, bad_range = importer.validate_against_bank(answers)
    assert not (unknown or bad_type or bad_range)


def test_find_in_downloads_prefers_newest(importer, tmp_path, monkeypatch):
    dl = tmp_path / "Downloads"
    dl.mkdir()
    older = dl / "career-compass-answers.json"
    older.write_text("{}", encoding="utf-8")
    import os
    import time

    newer = dl / "career-compass-answers (1).json"
    newer.write_text("{}", encoding="utf-8")
    # 显式拉开 mtime，避免同一秒内创建导致排序不稳定
    os.utime(older, (time.time() - 600, time.time() - 600))

    assert importer.find_in_downloads(tmp_path) == newer


def test_find_in_downloads_returns_none_when_absent(importer, tmp_path):
    assert importer.find_in_downloads(tmp_path) is None


def test_import_script_end_to_end(tmp_path):
    """从作答文件导入并直接出报告——这是用户实际要走的路径。"""
    from career_compass.cli import generate_demo_answers

    answers = generate_demo_answers(load_questions(), persona="people", seed=3)
    src = tmp_path / "browser_export.json"
    src.write_text(
        json.dumps(
            {"meta": {"source": "browser-questionnaire"}, "answers": answers},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "my-answers.json"
    report = tmp_path / "report.html"

    r = subprocess.run(
        [
            sys.executable,
            str(IMPORT_SCRIPT),
            "--from",
            str(src),
            "--out",
            str(out),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.is_file() and report.is_file()
    assert "已导入" in r.stdout
    # 导出的文件必须能被 CLI 正常读回
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["answers"] == answers


def test_import_script_aborts_on_bad_answers(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"answers": {"NOPE": 1}}), encoding="utf-8")
    out = tmp_path / "should-not-exist.json"

    r = subprocess.run(
        [sys.executable, str(IMPORT_SCRIPT), "--from", str(bad), "--out", str(out)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )
    assert r.returncode == 2
    assert not out.exists(), "校验失败时不应写出任何文件"


def test_import_script_reports_missing_file(tmp_path):
    r = subprocess.run(
        [sys.executable, str(IMPORT_SCRIPT), "--from", str(tmp_path / "nope.json")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )
    assert r.returncode == 1
    assert "文件不存在" in r.stdout


# ---------------------------------------------------------------------------
# 导入脚本的 --open：把「生成好了，请自己去找」这一步省掉
# ---------------------------------------------------------------------------


def _prepare_browser_export(tmp_path):
    from career_compass.cli import generate_demo_answers

    src = tmp_path / "browser_export.json"
    src.write_text(
        json.dumps(
            {"meta": {"source": "browser-questionnaire"}, "answers": generate_demo_answers(load_questions())},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return src


def test_import_open_implies_a_default_report_name(importer, tmp_path, monkeypatch):
    """只给 ``--open`` 时，必须自动补一个 HTML 报告名。

    否则 ``--open`` 会静默失效——用户以为会弹出报告，结果什么都没发生。
    这里替换掉真正的 ``cli.main``，避免测试真的去拉起浏览器。
    """
    import career_compass.cli as cli_mod

    captured: list[list[str]] = []

    def fake_main(argv):
        captured.append(list(argv))
        return 0

    monkeypatch.setattr(cli_mod, "main", fake_main)
    monkeypatch.chdir(tmp_path)

    src = _prepare_browser_export(tmp_path)
    assert importer.main(["import_answers.py", "--from", str(src), "--open"]) == 0

    assert len(captured) == 1
    argv = captured[0]
    assert argv[0] == "report"
    assert "--open" in argv, "必须把 --open 透传给 report 子命令"
    assert "--html" in argv, "--open 需要一份 HTML 才有意义"
    assert argv[argv.index("--html") + 1] == "my-report.html"


def test_import_without_report_flags_does_not_invoke_the_reporter(importer, tmp_path, monkeypatch):
    """没有任何出报告的参数时，不该去调用 report——只导入作答就好。"""
    import career_compass.cli as cli_mod

    called: list[list[str]] = []
    monkeypatch.setattr(cli_mod, "main", lambda argv: called.append(list(argv)) or 0)
    monkeypatch.chdir(tmp_path)

    src = _prepare_browser_export(tmp_path)
    assert importer.main(["import_answers.py", "--from", str(src)]) == 0
    assert not called, "没有 --report / --md / --open 时不应生成报告"
