"""报告渲染层：Markdown + 自包含 HTML。

约束：HTML 报告必须**零外部依赖**——不引用任何 CDN、字体或图表库，
所有图表（雷达图、条形图、进度条）都用内联 SVG 手写，
因此报告可以离线打开、可以直接丢进邮件或聊天窗口。
"""

from __future__ import annotations

import html
import math
import re
from collections.abc import Sequence
from datetime import datetime

from .data_loader import load_dimension_names, load_group_names
from .models import DIMENSION_TREE, GROUP_ORDER, Profile, Recommendation

# ---------------------------------------------------------------------------
# 颜色（浅色主题）
# ---------------------------------------------------------------------------

PALETTE = {
    "academic": "#3b6fd4",
    "skill": "#0f9d8c",
    "trait": "#c4711f",
    "interest": "#8b5cf6",
}
INK = "#1f2430"
INK_SOFT = "#5a6472"
LINE = "#e3e7ee"
BG = "#ffffff"
BG_SOFT = "#f6f8fb"


# ---------------------------------------------------------------------------
# 内联 SVG 图表
# ---------------------------------------------------------------------------


def _polar(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def svg_radar(
    labels: Sequence[str],
    values: Sequence[float],
    size: int = 300,
    color: str = "#3b6fd4",
) -> str:
    """手写 SVG 雷达图（任意轴数）。"""
    n = len(labels)
    if n < 3:
        return ""
    pad = 54
    cx = cy = size / 2
    r_max = size / 2 - pad
    angles = [-90 + i * 360.0 / n for i in range(n)]

    parts: list[str] = [
        f'<svg viewBox="0 0 {size} {size}" width="100%" style="max-width:{size}px" '
        f'role="img" aria-label="雷达图" xmlns="http://www.w3.org/2000/svg">'
    ]

    # 网格
    for frac in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(
            f"{_polar(cx, cy, r_max * frac, a)[0]:.1f},{_polar(cx, cy, r_max * frac, a)[1]:.1f}"
            for a in angles
        )
        parts.append(f'<polygon points="{pts}" fill="none" stroke="{LINE}" stroke-width="1"/>')
    for a in angles:
        x, y = _polar(cx, cy, r_max, a)
        parts.append(
            f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{LINE}" stroke-width="1"/>'
        )

    # 数据多边形
    dpts = []
    for a, v in zip(angles, values):
        vr = r_max * max(0.0, min(100.0, float(v))) / 100.0
        x, y = _polar(cx, cy, vr, a)
        dpts.append(f"{x:.1f},{y:.1f}")
    parts.append(
        f'<polygon points="{" ".join(dpts)}" fill="{color}" fill-opacity="0.18" '
        f'stroke="{color}" stroke-width="2"/>'
    )
    for pt in dpts:
        x, y = pt.split(",")
        parts.append(f'<circle cx="{x}" cy="{y}" r="3.2" fill="{color}"/>')

    # 轴标签
    for a, lab, v in zip(angles, labels, values):
        lx, ly = _polar(cx, cy, r_max + 26, a)
        anchor = "middle"
        if lx > cx + 8:
            anchor = "start"
        elif lx < cx - 8:
            anchor = "end"
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" dominant-baseline="middle" '
            f'font-size="12" font-family="inherit" fill="{INK}">{html.escape(lab)}</text>'
        )
        parts.append(
            f'<text x="{lx:.1f}" y="{ly + 13:.1f}" text-anchor="{anchor}" dominant-baseline="middle" '
            f'font-size="11" font-weight="600" font-family="inherit" fill="{color}">{v:.0f}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def svg_bar_list(
    rows: Sequence[tuple[str, float, str]],
    width: int = 620,
    row_h: int = 26,
    label_w: int = 132,
) -> str:
    """横向条形图列表。``rows`` 为 ``[(标签, 分值 0~100, 颜色)]``。"""
    if not rows:
        return ""
    height = row_h * len(rows) + 12
    bar_x = label_w + 10
    bar_max = width - bar_x - 46

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="条形图" '
        f'xmlns="http://www.w3.org/2000/svg">'
    ]
    for i, (label, value, color) in enumerate(rows):
        y = 6 + i * row_h
        v = max(0.0, min(100.0, float(value)))
        w = bar_max * v / 100.0
        parts.append(
            f'<text x="0" y="{y + row_h * 0.62:.1f}" font-size="12.5" font-family="inherit" '
            f'fill="{INK}" text-anchor="start">{html.escape(label)}</text>'
        )
        parts.append(f'<rect x="{bar_x}" y="{y + 4}" width="{bar_max}" height="11" rx="5.5" fill="{LINE}"/>')
        parts.append(f'<rect x="{bar_x}" y="{y + 4}" width="{w:.1f}" height="11" rx="5.5" fill="{color}"/>')
        parts.append(
            f'<text x="{bar_x + bar_max + 8}" y="{y + row_h * 0.62:.1f}" font-size="12" '
            f'font-weight="600" font-family="inherit" fill="{INK_SOFT}">{v:.0f}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def svg_donut(value: float, size: int = 132, color: str = "#3b6fd4", label: str = "") -> str:
    """单值圆环进度。"""
    r = size / 2 - 12
    c = 2 * math.pi * r
    v = max(0.0, min(100.0, float(value)))
    cx = cy = size / 2
    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" '
        f'aria-label="{html.escape(label)}" xmlns="http://www.w3.org/2000/svg">'
        f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="{LINE}" stroke-width="10"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" stroke="{color}" stroke-width="10" '
        f'stroke-linecap="round" stroke-dasharray="{c * v / 100:.1f} {c:.1f}" '
        f'transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-size="22" font-weight="700" '
        f'font-family="inherit" fill="{INK}">{v:.0f}</text>'
        f'<text x="{cx}" y="{cy + 18}" text-anchor="middle" font-size="11" font-family="inherit" '
        f'fill="{INK_SOFT}">{html.escape(label)}</text>'
        f"</svg>"
    )


# ---------------------------------------------------------------------------
# Markdown 报告
# ---------------------------------------------------------------------------


def render_markdown(
    profile: Profile,
    recs: Sequence[Recommendation],
    narrative: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    """生成 Markdown 版报告。"""
    load_dimension_names()
    group_names = load_group_names()
    ts = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M")
    L: list[str] = []

    L.append("# 职业能力测评报告")
    L.append("")
    L.append(f"生成时间：{ts}")
    L.append("")
    L.append(
        f"霍兰德代码：**{profile.holland_code}**　|　"
        f"数据质量指数：**{profile.quality:.0%}**　|　完成率：**{profile.completion:.0%}**"
    )
    L.append("")

    if profile.warnings:
        L.append("> **结果可靠性提示**")
        for w in profile.warnings:
            L.append(f"> - {w}")
        L.append("")

    # 四大维度
    L.append("## 一、四大维度总览")
    L.append("")
    L.append("| 维度 | 得分 | 水平 |")
    L.append("| --- | --- | --- |")
    for g in GROUP_ORDER:
        s = profile.group_scores.get(g, 0.0)
        level = "显著优势" if s >= 75 else "较强" if s >= 62 else "中等" if s >= 50 else "相对偏弱"
        L.append(f"| {group_names.get(g, g)} | {s:.0f} | {level} |")
    L.append("")

    # 子维度明细
    L.append("## 二、能力明细（21 个子维度）")
    L.append("")
    for g in GROUP_ORDER:
        L.append(f"### {group_names.get(g, g)}")
        L.append("")
        L.append("| 子维度 | 得分 | 计分方式 | 作答一致性 |")
        L.append("| --- | --- | --- | --- |")
        for sub in DIMENSION_TREE[g]:
            d = profile.details[f"{g}.{sub}"]
            method = {"objective": "客观题", "likert": "自评题", "mixed": "混合", "empty": "未作答"}.get(
                d.method, d.method
            )
            cons = f"{d.reliability:.0%}" if d.method in ("likert", "mixed") else "—"
            raw = f"（正确率 {d.raw_rate:.0%}）" if d.raw_rate is not None else ""
            L.append(f"| {d.name} | {d.score:.0f}{raw} | {method} | {cons} |")
        L.append("")

    # 职业推荐
    L.append("## 三、职业推荐（加权排序）")
    L.append("")
    L.append("| 排名 | 职业 | 最终得分 | 画像匹配 | 行业大盘 | 霍兰德 |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for i, r in enumerate(recs, 1):
        L.append(
            f"| {i} | {r.career.name} | **{r.final_score:.0f}** | {r.match_score:.0f} | "
            f"{r.market_score:.0f} | {r.career.holland}（重合 {r.holland_overlap}） |"
        )
    L.append("")

    for i, r in enumerate(recs, 1):
        L.append(f"### {i}. {r.career.name}（{r.career.category}）")
        L.append("")
        L.append(f"{r.career.summary}")
        L.append("")
        if r.career.entry_path:
            L.append(f"- **常见入口**：{r.career.entry_path}")
        if r.strengths:
            L.append(f"- **你的优势**：{'；'.join(r.strengths)}")
        if r.gaps:
            L.append(f"- **待补差距**：{'；'.join(r.gaps)}")
        if r.advice:
            L.append("- **提升建议**：")
            for a in r.advice:
                L.append(f"  - {a}")
        if r.role_models:
            L.append("- **可参考的典范**：")
            for m in r.role_models:
                L.append(f"  - **{m.name}**（{m.field}）— {m.insight}")
        L.append("")

    if narrative:
        L.append("## 四、个性化解读（由大模型生成）")
        L.append("")
        L.append(narrative.strip())
        L.append("")

    L.append("---")
    L.append("")
    L.append(
        "本报告由 career-compass 依据自评问卷与规则模型生成，"
        "题库与职业画像均为公开资料整理与专家赋值，**不构成职业决策或投资建议**。"
    )
    return "\n".join(L)


# ---------------------------------------------------------------------------
# HTML 报告
# ---------------------------------------------------------------------------


def _md_to_html(md: str) -> str:
    """把大模型返回的 Markdown 做最小化转换（标题/粗体/列表/段落）。"""
    out: list[str] = []
    in_ul = False
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if in_ul:
                out.append("</ul>")
                in_ul = False
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            lvl = min(6, len(m.group(1)) + 2)
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            continue
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue
        if in_ul:
            out.append("</ul>")
            in_ul = False
        out.append(f"<p>{_inline(line)}</p>")
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def _inline(text: str) -> str:
    s = html.escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def render_html(
    profile: Profile,
    recs: Sequence[Recommendation],
    narrative: str | None = None,
    generated_at: datetime | None = None,
    title: str = "职业能力测评报告",
) -> str:
    """生成零外部依赖的自包含 HTML 报告。"""
    dim_names = load_dimension_names()
    group_names = load_group_names()
    ts = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M")

    # --- 组雷达图 ---
    radar = svg_radar(
        [group_names.get(g, g) for g in GROUP_ORDER],
        [profile.group_scores.get(g, 0.0) for g in GROUP_ORDER],
    )

    # --- 子维度条形图 ---
    rows: list[tuple[str, float, str]] = []
    for g in GROUP_ORDER:
        for sub in DIMENSION_TREE[g]:
            d = profile.details[f"{g}.{sub}"]
            rows.append((f"{d.name}", d.score, PALETTE[g]))
    bars = svg_bar_list(rows)

    # --- 霍兰德六边形雷达 ---
    holland_radar = svg_radar(
        [dim_names[f"interest.{s}"] for s in DIMENSION_TREE["interest"]],
        [profile.dim_scores[f"interest.{s}"] for s in DIMENSION_TREE["interest"]],
        size=280,
        color=PALETTE["interest"],
    )

    # --- 卡片 ---
    warn_html = ""
    if profile.warnings:
        items = "".join(f"<li>{html.escape(w)}</li>" for w in profile.warnings)
        warn_html = f'<div class="warn"><strong>结果可靠性提示</strong><ul>{items}</ul></div>'

    group_cards = "".join(
        f'<div class="gcard"><div class="gname">{html.escape(group_names.get(g, g))}</div>'
        f'<div class="gval" style="color:{PALETTE[g]}">{profile.group_scores.get(g, 0):.0f}</div></div>'
        for g in GROUP_ORDER
    )

    rec_html: list[str] = []
    for i, r in enumerate(recs, 1):
        strengths = (
            "".join(f"<li>{html.escape(s)}</li>" for s in r.strengths)
            or "<li>暂未发现明显超出要求的维度</li>"
        )
        gaps = "".join(f"<li>{html.escape(s)}</li>" for s in r.gaps) or "<li>无明显短板</li>"
        advice = "".join(f"<li>{html.escape(a)}</li>" for a in r.advice) or "<li>按岗位要求补齐相关经验</li>"
        models = ""
        if r.role_models:
            inner = "".join(
                f'<div class="rm"><div class="rmn">{html.escape(m.name)}'
                f'<span class="rmf">{html.escape(m.field)}</span></div>'
                f'<div class="rmi">{html.escape(m.insight)}</div></div>'
                for m in r.role_models
            )
            models = f'<div class="sect"><div class="sect-t">可参考的典范</div>{inner}</div>'

        rec_html.append(
            f"""<article class="rec">
  <div class="rec-head">
    <div class="rank">{i}</div>
    <div class="rec-title">
      <h3>{html.escape(r.career.name)}</h3>
      <div class="meta">{html.escape(r.career.category)} · 霍兰德 {html.escape(r.career.holland)}（重合 {r.holland_overlap}）</div>
    </div>
    <div class="rec-score">
      <div class="big">{r.final_score:.0f}</div><div class="small">最终得分</div>
    </div>
  </div>
  <div class="minibars">
    <div class="mb"><span>画像匹配</span><div class="track"><i style="width:{r.match_score:.1f}%;background:#3b6fd4"></i></div><b>{r.match_score:.0f}</b></div>
    <div class="mb"><span>行业大盘</span><div class="track"><i style="width:{r.market_score:.1f}%;background:#0f9d8c"></i></div><b>{r.market_score:.0f}</b></div>
  </div>
  <p class="desc">{html.escape(r.career.summary)}</p>
  <div class="sect"><div class="sect-t">常见入口</div><p class="desc">{html.escape(r.career.entry_path)}</p></div>
  <div class="two">
    <div class="sect"><div class="sect-t ok">你的优势</div><ul>{strengths}</ul></div>
    <div class="sect"><div class="sect-t gap">待补差距</div><ul>{gaps}</ul></div>
  </div>
  <div class="sect"><div class="sect-t">提升建议</div><ul>{advice}</ul></div>
  {models}
</article>"""
        )

    narrative_html = ""
    if narrative:
        narrative_html = (
            '<section class="panel"><h2>四、个性化解读（由大模型生成）</h2>'
            f'<div class="narr">{_md_to_html(narrative)}</div></section>'
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{
    --ink: {INK}; --ink-soft: {INK_SOFT}; --line: {LINE};
    --bg: {BG}; --bg-soft: {BG_SOFT};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0 16px 64px;
    background: var(--bg-soft); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
                 "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    line-height: 1.68; font-size: 16px;
  }}
  .wrap {{ max-width: 940px; margin: 0 auto; }}
  header.top {{ padding: 40px 0 20px; }}
  header.top h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: -0.2px; }}
  .stamp {{ color: var(--ink-soft); font-size: 13.5px; }}
  .kpis {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 20px 0 8px; }}
  .kpi {{
    background: #fff; border: 1px solid var(--line); border-radius: 14px;
    padding: 12px 18px; min-width: 132px; flex: 1 1 132px;
  }}
  .kpi .k {{ font-size: 12.5px; color: var(--ink-soft); }}
  .kpi .v {{ font-size: 22px; font-weight: 700; margin-top: 2px; }}
  .panel {{
    background: #fff; border: 1px solid var(--line); border-radius: 18px;
    padding: 24px; margin: 18px 0;
  }}
  .panel h2 {{ margin: 0 0 16px; font-size: 19px; }}
  .chartrow {{ display: flex; flex-wrap: wrap; gap: 28px; align-items: center; }}
  .chartrow > div {{ flex: 1 1 300px; min-width: 260px; }}
  .gcards {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px; }}
  .gcard {{
    flex: 1 1 150px; background: var(--bg-soft); border-radius: 14px; padding: 14px 16px;
    border: 1px solid var(--line);
  }}
  .gname {{ font-size: 13px; color: var(--ink-soft); }}
  .gval {{ font-size: 30px; font-weight: 700; line-height: 1.2; }}
  .warn {{
    background: #fff7ed; border: 1px solid #fed7aa; color: #7c2d12;
    border-radius: 14px; padding: 14px 18px; margin: 16px 0; font-size: 14.5px;
  }}
  .warn ul {{ margin: 8px 0 0; padding-left: 20px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14.5px; }}
  th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--line); }}
  th {{ color: var(--ink-soft); font-weight: 600; font-size: 13px; }}
  td:first-child {{ white-space: nowrap; }}
  .rec {{
    background: #fff; border: 1px solid var(--line); border-radius: 18px;
    padding: 22px 24px; margin: 16px 0;
  }}
  .rec-head {{ display: flex; align-items: flex-start; gap: 14px; }}
  .rank {{
    width: 34px; height: 34px; border-radius: 10px; background: var(--bg-soft);
    border: 1px solid var(--line); display: flex; align-items: center; justify-content: center;
    font-weight: 700; color: var(--ink-soft); flex: 0 0 auto;
  }}
  .rec-title {{ flex: 1 1 auto; }}
  .rec-title h3 {{ margin: 2px 0 4px; font-size: 19px; }}
  .rec-title .meta {{ font-size: 13px; color: var(--ink-soft); }}
  .rec-score {{ text-align: right; flex: 0 0 auto; }}
  .rec-score .big {{ font-size: 28px; font-weight: 700; color: #3b6fd4; line-height: 1.1; }}
  .rec-score .small {{ font-size: 11.5px; color: var(--ink-soft); }}
  .minibars {{ margin: 16px 0 6px; display: grid; gap: 8px; }}
  .mb {{ display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--ink-soft); }}
  .mb span {{ width: 62px; flex: 0 0 auto; }}
  .mb b {{ width: 30px; text-align: right; color: var(--ink); flex: 0 0 auto; }}
  .track {{ flex: 1 1 auto; height: 9px; background: var(--line); border-radius: 5px; overflow: hidden; }}
  .track i {{ display: block; height: 100%; border-radius: 5px; }}
  .desc {{ font-size: 14.5px; color: var(--ink-soft); margin: 6px 0 0; }}
  .sect {{ margin-top: 14px; }}
  .sect-t {{ font-size: 13px; font-weight: 700; color: var(--ink); margin-bottom: 6px; }}
  .sect-t.ok {{ color: #0f7a5f; }}
  .sect-t.gap {{ color: #b45309; }}
  .sect ul, .narr ul {{ margin: 0; padding-left: 20px; font-size: 14.5px; color: var(--ink-soft); }}
  .sect li, .narr li {{ margin: 4px 0; }}
  .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  .rm {{ border-left: 3px solid var(--line); padding: 4px 0 4px 12px; margin: 10px 0; }}
  .rmn {{ font-weight: 700; font-size: 14.5px; }}
  .rmf {{ font-weight: 400; color: var(--ink-soft); font-size: 12.5px; margin-left: 8px; }}
  .rmi {{ font-size: 13.5px; color: var(--ink-soft); }}
  .narr h3 {{ font-size: 17px; margin: 18px 0 8px; }}
  .narr h4 {{ font-size: 15px; margin: 14px 0 6px; }}
  .narr p {{ font-size: 14.5px; color: var(--ink-soft); margin: 8px 0; }}
  code {{
    background: var(--bg-soft); padding: 2px 6px; border-radius: 6px;
    font-size: 13.5px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  footer {{
    text-align: center; color: var(--ink-soft); font-size: 12.5px;
    margin-top: 28px; line-height: 1.8;
  }}
  @media (max-width: 720px) {{
    body {{ font-size: 15.5px; padding: 0 12px 48px; }}
    header.top {{ padding: 26px 0 12px; }}
    header.top h1 {{ font-size: 22px; }}
    .panel, .rec {{ padding: 18px 16px; border-radius: 16px; }}
    .two {{ grid-template-columns: 1fr; gap: 10px; }}
    table {{ font-size: 13.5px; }}
    th, td {{ padding: 8px 6px; }}
    .rec-head {{ flex-wrap: wrap; }}
    .rec-score {{ margin-left: 48px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>{html.escape(title)}</h1>
    <div class="stamp">生成时间：{ts}　·　由 career-compass 规则引擎计算</div>
    <div class="kpis">
      <div class="kpi"><div class="k">霍兰德代码</div><div class="v">{html.escape(profile.holland_code)}</div></div>
      <div class="kpi"><div class="k">数据质量指数</div><div class="v">{profile.quality:.0%}</div></div>
      <div class="kpi"><div class="k">完成率</div><div class="v">{profile.completion:.0%}</div></div>
      <div class="kpi"><div class="k">核心兴趣类型</div><div class="v" style="font-size:15px;padding-top:5px">{html.escape(dim_names.get("interest." + profile.holland_sorted[0].lower(), "") if profile.holland_sorted else "")}</div></div>
    </div>
    {warn_html}
  </header>

  <section class="panel">
    <h2>一、四大维度总览</h2>
    <div class="chartrow">
      <div>{radar}</div>
      <div>{holland_radar}</div>
    </div>
    <div class="gcards">{group_cards}</div>
  </section>

  <section class="panel">
    <h2>二、能力明细（21 个子维度）</h2>
    {bars}
  </section>

  <section class="panel">
    <h2>三、职业推荐（加权排序）</h2>
    <table>
      <thead><tr><th>#</th><th>职业</th><th>最终</th><th>匹配</th><th>大盘</th><th>霍兰德</th></tr></thead>
      <tbody>
        {"".join(f"<tr><td>{i}</td><td>{html.escape(r.career.name)}</td><td><strong>{r.final_score:.0f}</strong></td><td>{r.match_score:.0f}</td><td>{r.market_score:.0f}</td><td>{html.escape(r.career.holland)}</td></tr>" for i, r in enumerate(recs, 1))}
      </tbody>
    </table>
  </section>

  {"".join(rec_html)}

  {narrative_html}

  <footer>
    本报告由 career-compass 依据自评问卷与规则模型生成。<br>
    题库与职业画像来自公开资料整理与专家赋值，结果仅供参考，<strong>不构成职业决策或投资建议</strong>。<br>
    部署后的页面为公开可访问，请勿在其中填入真实敏感信息。
  </footer>
</div>
</body>
</html>
"""
