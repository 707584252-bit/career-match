"""命令行与报告渲染的集成测试。"""

from __future__ import annotations

import json

import pytest

from career_compass.cli import (
    PERSONA_TEMPLATES,
    build_llm_payload,
    build_parser,
    generate_demo_answers,
    load_answers,
    main,
    save_answers,
)
from career_compass.data_loader import load_dimension_names, load_group_names, load_questions
from career_compass.llm import DeepSeekClient, LLMError, MissingAPIKeyError, load_dotenv
from career_compass.recommend import recommend
from career_compass.report import render_html, render_markdown
from career_compass.scoring import compute_profile

# ---------------------------------------------------------------------------
# 示例作答生成
# ---------------------------------------------------------------------------


def test_demo_answers_are_reproducible():
    qs = load_questions()
    a1 = generate_demo_answers(qs, persona="tech", seed=7)
    a2 = generate_demo_answers(qs, persona="tech", seed=7)
    a3 = generate_demo_answers(qs, persona="tech", seed=8)
    assert a1 == a2, "相同种子必须产出相同作答"
    assert a1 != a3, "不同种子应产出不同作答"


@pytest.mark.parametrize("persona", sorted(PERSONA_TEMPLATES))
def test_all_personas_produce_valid_answers(persona):
    qs = load_questions()
    answers = generate_demo_answers(qs, persona=persona, seed=1)
    assert len(answers) == len(qs)
    for q in qs:
        v = answers[q.id]
        if q.type == "likert":
            assert 1 <= v <= 5
        else:
            assert 0 <= v < len(q.options)


def test_unknown_persona_raises():
    with pytest.raises(ValueError):
        generate_demo_answers(load_questions(), persona="nope")


# ---------------------------------------------------------------------------
# 作答文件读写
# ---------------------------------------------------------------------------


def test_answers_round_trip(tmp_path):
    qs = load_questions()
    answers = generate_demo_answers(qs, seed=3)
    path = tmp_path / "a.json"
    save_answers(path, answers, {"mode": "test"})

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["meta"]["tool"] == "career-compass"
    assert raw["meta"]["mode"] == "test"
    assert load_answers(path) == answers


def test_load_answers_accepts_bare_dict(tmp_path):
    path = tmp_path / "bare.json"
    path.write_text(json.dumps({"LOG01": 2}), encoding="utf-8")
    assert load_answers(path) == {"LOG01": 2}


# ---------------------------------------------------------------------------
# 报告渲染
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rendered():
    qs = load_questions()
    answers = generate_demo_answers(qs, persona="tech", seed=42)
    profile = compute_profile(qs, answers, load_dimension_names())
    recs = recommend(profile, top_n=5)
    return profile, recs


def test_html_report_is_self_contained(rendered):
    profile, recs = rendered
    html = render_html(profile, recs)
    # 唯一允许出现的 http 是 SVG 命名空间（不是资源请求）
    import re

    urls = set(re.findall(r"https?://[^\"' )]+", html)) - {"http://www.w3.org/2000/svg"}
    assert not urls, f"报告引用了外部资源：{urls}"
    for marker in ("<svg", "</html>", "职业能力测评报告", "霍兰德"):
        assert marker in html


def test_html_report_escapes_untrusted_text(rendered):
    """大模型返回的内容可能含 HTML，必须被转义而不是直出。"""
    profile, recs = rendered
    html = render_html(profile, recs, narrative="<script>alert('xss')</script>")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_markdown_report_has_all_sections(rendered):
    profile, recs = rendered
    md = render_markdown(profile, recs)
    for section in ("# 职业能力测评报告", "## 一、四大维度总览", "## 二、能力明细", "## 三、职业推荐"):
        assert section in md
    for r in recs:
        assert r.career.name in md


def test_markdown_includes_narrative_section():
    qs = load_questions()
    profile = compute_profile(qs, generate_demo_answers(qs, seed=5), load_dimension_names())
    md = render_markdown(profile, recommend(profile, top_n=2), narrative="## 我的解读\n内容")
    assert "个性化解读" in md
    assert "我的解读" in md


# ---------------------------------------------------------------------------
# LLM 载荷与客户端
# ---------------------------------------------------------------------------


def test_llm_payload_shape(rendered):
    profile, recs = rendered
    payload = build_llm_payload(profile, recs)
    assert payload["holland_code"] == profile.holland_code
    assert len(payload["dimension_scores"]) == 21
    assert len(payload["top_recommendations"]) == len(recs)
    assert set(payload["group_scores"]) == set(load_group_names().values())
    # 必须可 JSON 序列化，否则请求会失败
    json.dumps(payload, ensure_ascii=False)


def test_client_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("CAREER_COMPASS_NO_DOTENV", "1")
    # 用显式 None 构造一个没有 key 的客户端（并绕过 .env 干扰）
    client = DeepSeekClient(api_key="")
    client.api_key = ""
    assert not client.enabled
    with pytest.raises(MissingAPIKeyError):
        client.chat([{"role": "user", "content": "hi"}])


def test_client_enabled_with_key():
    assert DeepSeekClient(api_key="sk-test").enabled


def test_load_dotenv_parses_quotes_and_comments(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        '# 注释\nDEEPSEEK_API_KEY="sk-abc"\nOTHER=plain\n\n# tail\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OTHER", raising=False)
    found = load_dotenv(str(env))
    assert found["DEEPSEEK_API_KEY"] == "sk-abc"
    assert found["OTHER"] == "plain"


def test_llm_errors_share_base_class():
    assert issubclass(MissingAPIKeyError, LLMError)


# ---------------------------------------------------------------------------
# 请求体构造（拦截 _post，不发真实网络请求）
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_request(monkeypatch):
    """返回一个 dict，调用 chat 后里面会是实际发送的请求体。"""
    from career_compass.llm import DeepSeekClient

    box: dict = {}

    def fake_post(payload):
        box.clear()
        box.update(payload)
        return {"choices": [{"message": {"content": "ok", "reasoning_content": "想了一下"}}]}

    client = DeepSeekClient(api_key="sk-test")
    monkeypatch.setattr(client, "_post", fake_post)
    return client, box


def test_default_model_and_base_url(captured_request):
    from career_compass.llm import DEFAULT_MODEL

    client, box = captured_request
    client.chat([{"role": "user", "content": "hi"}])
    assert box["model"] == DEFAULT_MODEL == "deepseek-flash"
    assert client.base_url == "https://api.deepseek.com"
    assert box["stream"] is False


def test_thinking_disabled_by_default_and_temperature_applies(captured_request):
    client, box = captured_request
    client.chat([{"role": "user", "content": "hi"}], temperature=0.7)
    assert box["thinking"] == {"type": "disabled"}
    assert box["temperature"] == pytest.approx(0.7)


def test_thinking_mode_enables_flag_and_drops_temperature(captured_request):
    """思考模式下 temperature 不生效（官方行为），因此不应出现在请求体里。"""
    client, box = captured_request
    client.chat(
        [{"role": "user", "content": "hi"}],
        temperature=0.7,
        thinking=True,
        reasoning_effort="max",
    )
    assert box["thinking"] == {"type": "enabled"}
    assert "temperature" not in box
    assert box["reasoning_effort"] == "max"


def test_reasoning_effort_is_validated(captured_request):
    client, _ = captured_request
    with pytest.raises(ValueError):
        client.chat([{"role": "user", "content": "hi"}], thinking=True, reasoning_effort="ultra")


def test_chat_detailed_returns_reasoning_content(captured_request):
    client, _ = captured_request
    out = client.chat_detailed([{"role": "user", "content": "hi"}], thinking=True)
    assert out["content"] == "ok"
    assert out["reasoning_content"] == "想了一下"
    assert out["model"] == "deepseek-flash"


def test_system_prompt_forbids_fabrication():
    """系统提示词必须包含「不得编造」与免责声明要求，这是安全底线。"""
    from career_compass.llm import SYSTEM_PROMPT

    assert "不得编造" in SYSTEM_PROMPT
    assert "免责声明" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def test_parser_accepts_all_subcommands():
    parser = build_parser()
    cases = [
        ["demo"],
        ["demo", "--persona", "creative", "--top", "3"],
        ["run", "--non-interactive"],
        ["report", "-i", "x.json", "--html", "a.html"],
        ["score", "-i", "x.json"],
        ["questions"],
        ["list-careers"],
        ["llm-test"],
    ]
    for argv in cases:
        ns = parser.parse_args(argv)
        assert callable(ns.func)


def test_cli_demo_end_to_end(tmp_path, capsys):
    html = tmp_path / "r.html"
    md = tmp_path / "r.md"
    answers = tmp_path / "a.json"
    code = main(
        [
            "demo",
            "--persona",
            "people",
            "--html",
            str(html),
            "--md",
            str(md),
            "--save-answers",
            str(answers),
        ]
    )
    assert code == 0
    assert html.exists() and md.exists() and answers.exists()
    assert "霍兰德代码" in capsys.readouterr().out


def test_cli_report_from_saved_answers(tmp_path):
    qs = load_questions()
    src = tmp_path / "a.json"
    save_answers(src, generate_demo_answers(qs, persona="steady", seed=11))
    out = tmp_path / "r.html"
    assert main(["report", "-i", str(src), "--html", str(out)]) == 0
    assert out.exists()


def test_cli_score_writes_json(tmp_path):
    qs = load_questions()
    src = tmp_path / "a.json"
    save_answers(src, generate_demo_answers(qs, seed=2))
    out = tmp_path / "s.json"
    assert main(["score", "-i", str(src), "-o", str(out), "-n", "3"]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["recommendations"]) == 3
    assert "holland_code" in data["profile"]


def test_cli_llm_test_without_key_returns_error_code(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # 避开项目里的 .env
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert main(["llm-test"]) == 2


def test_cli_reports_missing_input_file(tmp_path, capsys):
    assert main(["report", "-i", str(tmp_path / "nope.json")]) == 1
    assert "文件未找到" in capsys.readouterr().err
