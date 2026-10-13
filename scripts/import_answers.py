#!/usr/bin/env python3
"""把浏览器答题页导出的作答导入到本地，并可选直接生成报告。

为什么需要这个脚本
------------------
答题页有两种导出方式，都会让非技术用户卡在「文件在哪」：

* **下载文件** —— 浏览器默认丢进 ``下载`` 文件夹，用户得自己找路径；
* **复制作答** —— 内容在剪贴板里，没有文件可指。

本脚本把这两条路统一成一条命令：不给参数时，先看剪贴板，再按修改时间
找下载目录里最新的 ``career-compass-answers*.json``。

用法::

    python scripts/import_answers.py                      # 自动找作答，只导入
    python scripts/import_answers.py --open               # 导入 + 出报告 + 打开浏览器
    python scripts/import_answers.py --from my.json        # 指定文件
    python scripts/import_answers.py --report report.html  # 顺带生成报告
    python scripts/import_answers.py --report r.html --llm # 再加 AI 解读

退出码：0 成功；1 没找到可用作答；2 找到了但内容不合法。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# 让脚本在未安装包的情况下也能跑（直接从仓库运行）
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from career_compass.console import ensure_utf8_output  # noqa: E402

#: 下载目录里查找的候选文件名模式（按优先级）
NAME_PATTERNS = ("career-compass-answers*.json", "*answers*.json")

DEFAULT_OUT = "my-answers.json"


# ---------------------------------------------------------------------------
# 来源一：剪贴板
# ---------------------------------------------------------------------------


def read_clipboard() -> str | None:
    """读取系统剪贴板文本。取不到就返回 ``None``（不是错误，换下一个来源即可）。"""
    try:
        if sys.platform.startswith("win"):
            # 必须显式指定 UTF-8，否则中文题面会按代码页损坏
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw",
                ],
                capture_output=True,
                timeout=20,
                check=False,
            )
            return out.stdout.decode("utf-8", errors="replace")
        if sys.platform == "darwin":
            out = subprocess.run(["pbpaste"], capture_output=True, timeout=10, check=False)
            return out.stdout.decode("utf-8", errors="replace")
        for cmd in (["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]):
            if shutil.which(cmd[0]):
                out = subprocess.run(cmd, capture_output=True, timeout=10, check=False)
                return out.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return None


# ---------------------------------------------------------------------------
# 来源二：下载文件夹
# ---------------------------------------------------------------------------


def find_in_downloads(home: Path | None = None) -> Path | None:
    """在下载目录里按修改时间找最新的作答文件。"""
    base = (home or Path.home()) / "Downloads"
    if not base.is_dir():
        return None
    found: list[Path] = []
    for pattern in NAME_PATTERNS:
        found.extend(p for p in base.glob(pattern) if p.is_file())
        if found:
            break  # 先按精确模式找；找到就不看宽泛模式，避免误选无关文件
    if not found:
        return None
    return max(found, key=lambda p: p.stat().st_mtime)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def parse_answers(text: str) -> dict[str, object]:
    """把文本解析成 ``{id: 作答}``。格式不对抛 ``ValueError``。"""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"不是合法的 JSON（{e}）") from e

    if not isinstance(raw, dict):
        raise ValueError("JSON 顶层应为对象")

    # 兼容 save_answers() 的 {"meta":..., "answers":{...}} 与裸 dict
    body = raw.get("answers") if "answers" in raw else raw
    if not isinstance(body, dict) or not body:
        raise ValueError("没有找到 answers 字段，或作答为空")

    cleaned: dict[str, object] = {}
    for k, v in body.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if v is None:
            continue
        cleaned[k] = v
    if not cleaned:
        raise ValueError("作答里没有任何有效条目")
    return cleaned


def validate_against_bank(answers: dict[str, object]) -> tuple[list[str], list[str], list[str]]:
    """与题库比对，返回 ``(未知题号, 类型不符, 值域不符)`` 三类问题。"""
    from career_compass.data_loader import load_questions

    by_id = {q.id: q for q in load_questions()}
    unknown: list[str] = []
    bad_type: list[str] = []
    bad_range: list[str] = []

    for qid, value in answers.items():
        q = by_id.get(qid)
        if q is None:
            unknown.append(qid)
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            bad_type.append(qid)
            continue
        if q.type == "objective":
            if not (0 <= value < len(q.options)):
                bad_range.append(qid)
        elif not (1 <= value <= 5):
            bad_range.append(qid)
    return unknown, bad_type, bad_range


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    ensure_utf8_output()
    ap = argparse.ArgumentParser(
        description="导入浏览器答题页的作答，并可一键生成报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python scripts/import_answers.py\n"
            "  python scripts/import_answers.py --report report.html\n"
            "  python scripts/import_answers.py --from ~/Downloads/career-compass-answers.json\n"
        ),
    )
    ap.add_argument("--from", dest="src", help="指定作答 JSON 文件；不给则自动查找")
    ap.add_argument("--out", "-o", default=DEFAULT_OUT, help=f"写入路径（默认 {DEFAULT_OUT}）")
    ap.add_argument("--report", help="顺带生成 HTML 报告到该路径")
    ap.add_argument("--md", help="顺带生成 Markdown 报告到该路径")
    ap.add_argument("--top", "-n", type=int, default=5, help="推荐职业数量（默认 5）")
    ap.add_argument("--llm", action="store_true", help="报告里附上 DeepSeek 个性化解读")
    ap.add_argument("--open", action="store_true", help="生成 HTML 报告后用默认浏览器打开")
    ap.add_argument("--allow-partial", action="store_true", help="容忍未知题号等小问题，照常继续")
    args = ap.parse_args(argv[1:])

    text: str | None = None
    origin = ""

    if args.src:
        p = Path(args.src).expanduser()
        if not p.is_file():
            print(f"[x] 文件不存在：{p}")
            return 1
        text = p.read_text(encoding="utf-8", errors="replace")
        origin = str(p)
    else:
        clip = read_clipboard() or ""
        if clip.strip().startswith("{"):
            text = clip
            origin = "剪贴板"
        else:
            found = find_in_downloads()
            if found:
                text = found.read_text(encoding="utf-8", errors="replace")
                origin = str(found)

    if text is None:
        print("[x] 没有找到作答。可以这样做：")
        print("      1) 在答题页点「导出作答文件」，让它下载到默认位置，然后重跑本命令；")
        print("      2) 在答题页点「复制作答」，然后重跑本命令（会读剪贴板）；")
        print("      3) 直接指定路径：python scripts/import_answers.py --from <作答文件>")
        return 1

    try:
        answers = parse_answers(text)
    except ValueError as e:
        print(f"[x] 来自{origin}的内容无法解析：{e}")
        print("     若剪贴板里是别的内容，请用 --from 指定作答文件。")
        return 2

    unknown, bad_type, bad_range = validate_against_bank(answers)
    problems = bool(unknown or bad_type or bad_range)
    if problems:
        print(f"[!] 作答来源：{origin}，共 {len(answers)} 条，但存在以下问题：")
        for label, ids in (
            ("题库中没有的题号", unknown),
            ("取值类型不对", bad_type),
            ("取值超出范围", bad_range),
        ):
            if ids:
                shown = ", ".join(sorted(ids)[:8])
                more = f" 等 {len(ids)} 个" if len(ids) > 8 else ""
                print(f"      - {label}：{shown}{more}")
        if not args.allow_partial:
            print("     已中止（未写入任何文件）。确认无误可加 --allow-partial 继续。")
            return 2

    out = Path(args.out)
    out.write_text(
        json.dumps(
            {"meta": {"tool": "career-compass", "imported_from": origin}, "answers": answers},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[ok] 已导入 {len(answers)} 条作答（来源：{origin}）→ {out}")
    if args.report or args.md or args.open:
        from career_compass.cli import main as cc_main

        # --open 要有 HTML 才打得开：用户只加了 --open 时补一个默认文件名，
        # 而不是让这个参数静默失效。
        report_path = args.report
        if args.open and not report_path:
            report_path = "my-report.html"

        cmd = ["report", "-i", str(out), "-n", str(args.top)]
        if report_path:
            cmd += ["--html", report_path]
        if args.md:
            cmd += ["--md", args.md]
        if args.llm:
            cmd += ["--llm"]
        if args.open:
            cmd += ["--open"]
        print()
        rc = cc_main(cmd)
        if rc == 0 and report_path:
            print()
            print(f"     报告文件：{Path(report_path).resolve()}")
            print("     以后想重新生成：")
            print(f"       career-compass report -i {out} --html {report_path}")
        return rc

    print("     下一步，生成一份报告：")
    print(f"       career-compass report -i {out} --html my-report.html --open")
    print("     （或直接重跑本命令并加上 --open，导入与出报告一次完成）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
