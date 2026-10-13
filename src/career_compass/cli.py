"""命令行入口。

设计原则：默认零参数即可跑通完整流程（``career-compass demo``），
所有进阶能力通过子命令暴露，不产生任何交互式阻塞。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from . import __version__
from .data_loader import (
    load_careers,
    load_dimension_names,
    load_group_names,
    load_likert_scale,
    load_questions,
)
from .llm import KNOWN_MODELS
from .models import GROUP_ORDER, Question
from .recommend import recommend
from .report import render_html, render_markdown
from .scoring import compute_profile

# ---------------------------------------------------------------------------
# 示例作答生成：让 demo 模式能产出「像真人」的结果
# ---------------------------------------------------------------------------

#: 五套人格模板，用于 demo 模式生成不同倾向的作答
PERSONA_TEMPLATES: dict[str, dict[str, float]] = {
    "tech": {
        "academic.logic": 88,
        "academic.numeric": 84,
        "academic.spatial": 74,
        "academic.verbal": 58,
        "skill.tech": 88,
        "skill.creative": 62,
        "skill.social": 42,
        "skill.manage": 56,
        "trait.openness": 78,
        "trait.conscientiousness": 76,
        "trait.extraversion": 40,
        "trait.agreeableness": 58,
        "trait.stability": 68,
        "trait.grit": 78,
        "trait.risk": 56,
        "interest.realistic": 66,
        "interest.investigative": 90,
        "interest.artistic": 48,
        "interest.social": 34,
        "interest.enterprising": 46,
        "interest.conventional": 64,
    },
    "people": {
        "academic.logic": 62,
        "academic.numeric": 54,
        "academic.spatial": 50,
        "academic.verbal": 84,
        "skill.tech": 40,
        "skill.creative": 62,
        "skill.social": 92,
        "skill.manage": 70,
        "trait.openness": 72,
        "trait.conscientiousness": 74,
        "trait.extraversion": 84,
        "trait.agreeableness": 90,
        "trait.stability": 78,
        "trait.grit": 76,
        "trait.risk": 42,
        "interest.realistic": 34,
        "interest.investigative": 58,
        "interest.artistic": 62,
        "interest.social": 94,
        "interest.enterprising": 66,
        "interest.conventional": 60,
    },
    "business": {
        "academic.logic": 74,
        "academic.numeric": 72,
        "academic.spatial": 52,
        "academic.verbal": 80,
        "skill.tech": 50,
        "skill.creative": 74,
        "skill.social": 84,
        "skill.manage": 90,
        "trait.openness": 82,
        "trait.conscientiousness": 72,
        "trait.extraversion": 86,
        "trait.agreeableness": 60,
        "trait.stability": 82,
        "trait.grit": 88,
        "trait.risk": 88,
        "interest.realistic": 42,
        "interest.investigative": 64,
        "interest.artistic": 62,
        "interest.social": 64,
        "interest.enterprising": 94,
        "interest.conventional": 54,
    },
    "creative": {
        "academic.logic": 60,
        "academic.numeric": 46,
        "academic.spatial": 82,
        "academic.verbal": 82,
        "skill.tech": 58,
        "skill.creative": 94,
        "skill.social": 62,
        "skill.manage": 52,
        "trait.openness": 92,
        "trait.conscientiousness": 62,
        "trait.extraversion": 66,
        "trait.agreeableness": 68,
        "trait.stability": 64,
        "trait.grit": 76,
        "trait.risk": 72,
        "interest.realistic": 44,
        "interest.investigative": 66,
        "interest.artistic": 96,
        "interest.social": 60,
        "interest.enterprising": 62,
        "interest.conventional": 38,
    },
    "steady": {
        "academic.logic": 70,
        "academic.numeric": 82,
        "academic.spatial": 56,
        "academic.verbal": 72,
        "skill.tech": 58,
        "skill.creative": 42,
        "skill.social": 64,
        "skill.manage": 74,
        "trait.openness": 48,
        "trait.conscientiousness": 92,
        "trait.extraversion": 52,
        "trait.agreeableness": 72,
        "trait.stability": 84,
        "trait.grit": 82,
        "trait.risk": 28,
        "interest.realistic": 48,
        "interest.investigative": 60,
        "interest.artistic": 34,
        "interest.social": 60,
        "interest.enterprising": 48,
        "interest.conventional": 90,
    },
}


def _target_to_likert(target: float, rng: random.Random) -> int:
    """把 0~100 的目标倾向映射为 1~5 的作答值，并加入噪声。"""
    base = 1 + target / 100.0 * 4.0
    noisy = base + rng.gauss(0, 0.55)
    return int(min(5, max(1, round(noisy))))


def generate_demo_answers(
    questions: Sequence[Question],
    persona: str = "tech",
    seed: int = 42,
    answer_noise: float = 0.12,
) -> dict[str, object]:
    """按人格模板生成一份「像真人」的示例作答。

    Args:
        questions: 题库。
        persona: ``tech`` / ``people`` / ``business`` / ``creative`` / ``steady``。
        seed: 随机种子，保证可复现。
        answer_noise: 客观题的失误率上浮量，用于制造真实的错题分布。

    Returns:
        ``{question_id: value}``
    """
    if persona not in PERSONA_TEMPLATES:
        raise ValueError(f"未知人格模板 {persona}，可选：{', '.join(PERSONA_TEMPLATES)}")
    template = PERSONA_TEMPLATES[persona]
    rng = random.Random(seed)
    answers: dict[str, object] = {}

    for q in questions:
        target = template.get(q.dim, 55.0)
        if q.type == "likert":
            answers[q.id] = _target_to_likert(target, rng)
        else:
            # 能力越强的维度，答对概率越高
            p_correct = min(0.96, 0.30 + 0.62 * (target / 100.0)) - answer_noise
            n_opts = len(q.options) or 4
            if rng.random() < p_correct:
                answers[q.id] = q.answer
            else:
                wrong = [i for i in range(n_opts) if i != q.answer]
                answers[q.id] = rng.choice(wrong)
    return answers


# ---------------------------------------------------------------------------
# 答题包 I/O
# ---------------------------------------------------------------------------


def save_answers(path: Path, answers: dict[str, object], extra: dict | None = None) -> None:
    """把作答保存为 JSON。"""
    payload = {
        "meta": {
            "tool": "career-compass",
            "version": __version__,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
        "answers": answers,
    }
    if extra:
        payload["meta"].update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_answers(path: Path) -> dict[str, object]:
    """读取作答 JSON，兼容「裸 dict」与「带 meta 包装」两种格式。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "answers" in raw:
        return dict(raw["answers"])
    if isinstance(raw, dict):
        return {k: v for k, v in raw.items() if not k.startswith("_") and k != "meta"}
    raise ValueError(f"无法识别的作答文件格式：{path}")


# ---------------------------------------------------------------------------
# 交互式答题
# ---------------------------------------------------------------------------


def run_interactive(questions: Sequence[Question], assume_yes: bool = False) -> dict[str, object]:
    """在终端逐题作答。``q`` 跳过，``b`` 返回上一题。"""
    scale = load_likert_scale()
    labels = scale["labels"]
    answers: dict[str, object] = {}
    idx = 0
    total = len(questions)

    print("\n=== 职业能力测评 ===")
    print(f"共 {total} 题。自评题输入 1-5；选择题输入选项序号。")
    print("输入 q 跳过当前题，输入 b 返回上一题，输入 quit 保存并结束。\n")

    while idx < total:
        q = questions[idx]
        print(f"--- [{idx + 1}/{total}] {q.id} ---")
        print(q.stem)
        if q.type == "objective":
            for i, opt in enumerate(q.options):
                print(f"  {i + 1}. {opt}")
            valid = [str(i + 1) for i in range(len(q.options))]
        else:
            for i, lab in enumerate(labels):
                print(f"  {i + 1}. {lab}")
            valid = [str(i + 1) for i in range(len(labels))]
        print()

        try:
            raw = input("你的选择 > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已中断，保存当前进度。")
            break

        if raw in ("quit", "exit"):
            break
        if raw == "q":
            idx += 1
            continue
        if raw == "b":
            idx = max(0, idx - 1)
            continue
        if raw not in valid:
            print(f"请输入 {valid[0]}-{valid[-1]}，或 q/b/quit。\n")
            continue

        value = int(raw) - 1
        answers[q.id] = value
        idx += 1

    return answers


# ---------------------------------------------------------------------------
# 结构化结果 → LLM 提示词载荷
# ---------------------------------------------------------------------------


def build_llm_payload(profile, recs) -> dict:
    """把画像与推荐结果整理成精简的 JSON 载荷，交给大模型。"""
    dim_names = load_dimension_names()
    group_names = load_group_names()
    return {
        "holland_code": profile.holland_code,
        "data_quality": {"quality_index": profile.quality, "completion": profile.completion},
        "reliability_warnings": profile.warnings,
        "group_scores": {group_names.get(g, g): profile.group_scores.get(g, 0.0) for g in GROUP_ORDER},
        "dimension_scores": {dim_names.get(k, k): round(v, 1) for k, v in sorted(profile.dim_scores.items())},
        "top_recommendations": [
            {
                "career": r.career.name,
                "category": r.career.category,
                "match_score": r.match_score,
                "market_score": r.market_score,
                "final_score": r.final_score,
                "holland": r.career.holland,
                "strengths": r.strengths,
                "gaps": r.gaps,
            }
            for r in recs
        ],
    }


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------


def _emit_report(
    profile,
    recs,
    out_html: Path | None,
    out_md: Path | None,
    narrative: str | None,
    quiet: bool = False,
) -> None:
    if out_md:
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(render_markdown(profile, recs, narrative), encoding="utf-8")
        if not quiet:
            print(f"[ok] Markdown 报告：{out_md}")
    if out_html:
        out_html.parent.mkdir(parents=True, exist_ok=True)
        out_html.write_text(render_html(profile, recs, narrative), encoding="utf-8")
        if not quiet:
            print(f"[ok] HTML 报告：{out_html}")


def _print_summary(profile, recs) -> None:
    group_names = load_group_names()
    print("\n=== 四大维度 ===")
    for g in GROUP_ORDER:
        print(f"  {group_names.get(g, g):<10} {profile.group_scores.get(g, 0):5.1f}")
    print(f"\n霍兰德代码：{profile.holland_code}")
    print(f"数据质量指数：{profile.quality:.0%}（完成率 {profile.completion:.0%}）")
    for w in profile.warnings:
        print(f"  ! {w}")
    print(f"\n=== 职业推荐 Top {len(recs)} ===")
    for i, r in enumerate(recs, 1):
        print(
            f"  {i}. {r.career.name:<18} 最终 {r.final_score:5.1f} | "
            f"匹配 {r.match_score:5.1f} | 大盘 {r.market_score:5.1f} | 霍兰德 {r.career.holland}"
        )


def cmd_questions(args) -> int:
    """导出纯问卷 JSON（不含答案），便于接到自己的前端。"""
    questions = load_questions()
    scale = load_likert_scale()
    out = {
        "version": __version__,
        "scale": scale,
        "groups": load_group_names(),
        "dimensions": load_dimension_names(),
        "questions": [
            {
                "id": q.id,
                "dim": q.dim,
                "type": q.type,
                "stem": q.stem,
                "options": q.options if q.type == "objective" else scale["labels"],
                "difficulty": q.difficulty if q.type == "objective" else None,
                "weight": q.weight,
                "source": q.source,
            }
            for q in questions
        ],
    }
    # 刻意不导出 answer 字段，避免把「答案」泄漏给前端
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[ok] 已导出 {len(out['questions'])} 道题目：{args.out}")
    else:
        print(text)
    return 0


def cmd_list(args) -> int:
    """列出职业库与行业大盘数据。"""
    careers = load_careers()
    from .data_loader import load_market_stats

    market = load_market_stats()
    print(f"{'id':<22}{'职业':<22}{'类别':<14}{'霍兰德':<8}{'景气':<8}{'AI风险'}")
    for c in careers:
        m = market.get(c.id)
        outlook = f"{m.outlook:.2f}" if m else "-"
        risk = f"{m.ai_risk:.2f}" if m else "-"
        print(f"{c.id:<22}{c.name:<22}{c.category:<14}{c.holland:<8}{outlook:<8}{risk}")
    print(f"\n共 {len(careers)} 个职业。")
    return 0


def cmd_demo(args) -> int:
    """无需作答，用内置人格模板生成一份完整示例报告。"""
    questions = load_questions()
    answers = generate_demo_answers(questions, persona=args.persona, seed=args.seed)
    if args.save_answers:
        save_answers(
            Path(args.save_answers), answers, {"mode": "demo", "persona": args.persona, "seed": args.seed}
        )
        print(f"[ok] 示例作答已保存：{args.save_answers}")

    profile = compute_profile(questions, answers, load_dimension_names())
    recs = recommend(profile, top_n=args.top)

    narrative = None
    if args.llm:
        narrative = _try_llm(profile, recs, args)
    _print_summary(profile, recs)
    _emit_report(
        profile, recs, Path(args.html) if args.html else None, Path(args.md) if args.md else None, narrative
    )
    return 0


def _try_llm(profile, recs, args) -> str | None:
    """尝试调用大模型生成叙述报告；失败则降级并提示，不影响主流程。"""
    from .llm import DeepSeekClient, LLMError, generate_narrative

    thinking = bool(getattr(args, "reasoning", False))
    try:
        client = DeepSeekClient(model=args.model) if args.model else DeepSeekClient()
        mode = "思考模式" if thinking else "普通模式"
        print(f"[..] 正在调用 DeepSeek（{client.model}，{mode}）生成个性化解读…")
        text = generate_narrative(
            build_llm_payload(profile, recs),
            client=client,
            model=args.model,
            thinking=thinking,
            reasoning_effort="high" if thinking else None,
        )
        print("[ok] 个性化解读生成完成")
        return text
    except LLMError as e:
        print(f"[!] 大模型调用失败，已跳过个性化解读，其余报告照常生成。原因：{e}")
        return None


def cmd_run(args) -> int:
    """交互式答题并生成报告。"""
    questions = load_questions()
    if args.persona or args.non_interactive:
        answers = generate_demo_answers(questions, persona=args.persona or "tech", seed=args.seed)
        print(f"[i] 非交互模式，使用示例作答（persona={args.persona or 'tech'}）。")
    else:
        answers = run_interactive(questions)
        if not answers:
            print("[!] 没有任何作答，已退出。")
            return 1

    if args.save_answers:
        save_answers(Path(args.save_answers), answers)

    profile = compute_profile(questions, answers, load_dimension_names())
    recs = recommend(profile, top_n=args.top)
    narrative = _try_llm(profile, recs, args) if args.llm else None
    _print_summary(profile, recs)
    _emit_report(
        profile, recs, Path(args.html) if args.html else None, Path(args.md) if args.md else None, narrative
    )
    return 0


def cmd_report(args) -> int:
    """从已保存的作答文件重新生成报告。"""
    questions = load_questions()
    answers = load_answers(Path(args.input))
    profile = compute_profile(questions, answers, load_dimension_names())
    recs = recommend(profile, top_n=args.top)
    narrative = _try_llm(profile, recs, args) if args.llm else None
    _print_summary(profile, recs)
    _emit_report(
        profile, recs, Path(args.html) if args.html else None, Path(args.md) if args.md else None, narrative
    )
    return 0


def cmd_score(args) -> int:
    """只输出结构化评分 JSON（便于接入你自己的前端或下游系统）。"""
    questions = load_questions()
    answers = load_answers(Path(args.input))
    profile = compute_profile(questions, answers, load_dimension_names())
    recs = recommend(profile, top_n=args.top)
    out = {
        "profile": {
            "group_scores": profile.group_scores,
            "dimension_scores": profile.dim_scores,
            "holland_code": profile.holland_code,
            "quality": profile.quality,
            "completion": profile.completion,
            "warnings": profile.warnings,
        },
        "recommendations": [r.to_dict() for r in recs],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[ok] 评分结果：{args.out}")
    else:
        print(text)
    return 0


def cmd_llm_test(args) -> int:
    """验证 DeepSeek API 是否配置正确。"""
    from .llm import DeepSeekClient, LLMError

    client = DeepSeekClient(model=args.model) if args.model else DeepSeekClient()
    if not client.enabled:
        print("[x] 未检测到 API Key。请设置环境变量 DEEPSEEK_API_KEY，")
        print("    或在项目根目录创建 .env 文件写入：DEEPSEEK_API_KEY=sk-xxxx")
        print("    详细步骤见 docs/DEEPSEEK.md")
        return 2
    print(f"[..] base_url = {client.base_url}")
    print(f"[..] model    = {client.model}")
    print("[..] 正在发送测试请求…")
    try:
        reply = client.test_connection()
        print(f"[ok] 连通成功，模型回复：{reply.strip()}")
        return 0
    except LLMError as e:
        print(f"[x] 调用失败：{e}")
        return 1


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="career-compass",
        description="职业能力测评与加权职业推荐引擎（零第三方依赖）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  career-compass demo --html report.html          # 用示例作答直接出报告\n"
            "  career-compass demo --persona creative --llm     # 示例 + DeepSeek 解读\n"
            "  career-compass run --save-answers me.json        # 交互式答题\n"
            "  career-compass report --input me.json --html r.html --llm\n"
            "  career-compass score --input me.json             # 只看结构化评分\n"
            "  career-compass questions --out q.json            # 导出问卷给自建前端\n"
            "  career-compass llm-test                          # 验证 API 配置\n"
        ),
    )
    p.add_argument("-V", "--version", action="version", version=f"career-compass {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp, need_input=False):
        if need_input:
            sp.add_argument("--input", "-i", required=True, help="作答 JSON 文件路径")
        sp.add_argument("--top", "-n", type=int, default=5, help="推荐职业数量（默认 5）")
        sp.add_argument("--html", help="输出 HTML 报告路径")
        sp.add_argument("--md", help="输出 Markdown 报告路径")
        sp.add_argument("--llm", action="store_true", help="额外调用 DeepSeek 生成个性化解读")
        sp.add_argument(
            "--model",
            help=f"覆盖模型名，可选 {' 或 '.join(KNOWN_MODELS)}（默认 deepseek-flash）",
        )
        sp.add_argument(
            "--reasoning",
            action="store_true",
            help="开启思考模式（更慢更贵，写报告一般不需要）",
        )

    sp = sub.add_parser("demo", help="用内置人格模板生成示例报告")
    sp.add_argument(
        "--persona",
        default="tech",
        choices=sorted(PERSONA_TEMPLATES),
        help="人格模板（默认 tech）",
    )
    sp.add_argument("--seed", type=int, default=42, help="随机种子")
    sp.add_argument("--save-answers", help="把示例作答保存到该路径")
    add_common(sp)
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("run", help="交互式答题并生成报告")
    sp.add_argument("--non-interactive", action="store_true", help="不交互，改用示例作答")
    sp.add_argument("--persona", choices=sorted(PERSONA_TEMPLATES), help="非交互模式下的人格模板")
    sp.add_argument("--seed", type=int, default=42)
    sp.add_argument("--save-answers", help="保存作答到该路径")
    add_common(sp)
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("report", help="从作答文件生成报告")
    add_common(sp, need_input=True)
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("score", help="只输出结构化评分 JSON")
    sp.add_argument("--input", "-i", required=True)
    sp.add_argument("--top", "-n", type=int, default=5)
    sp.add_argument("--out", "-o", help="输出 JSON 路径，缺省打印到标准输出")
    sp.set_defaults(func=cmd_score)

    sp = sub.add_parser("questions", help="导出问卷 JSON（不含答案）")
    sp.add_argument("--out", "-o", help="输出路径，缺省打印到标准输出")
    sp.set_defaults(func=cmd_questions)

    sp = sub.add_parser("list-careers", help="列出职业库")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("llm-test", help="验证 DeepSeek API 配置")
    sp.add_argument("--model", help="覆盖模型名")
    sp.set_defaults(func=cmd_llm_test)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except FileNotFoundError as e:
        print(f"[x] 文件未找到：{e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"[x] 输入有误：{e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
