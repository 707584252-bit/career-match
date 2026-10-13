#!/usr/bin/env python3
"""本地启动器菜单（Windows 上由同目录的 ``run.cmd`` 调用）。

为什么菜单放在 Python 里，而不是写在 .cmd 里
--------------------------------------------
菜单原来直接写在 ``run.cmd`` 里，结果连踩两个坑，用户报的症状是「run 打不开」：

1. **行尾符**：Windows 批处理必须是 ``CRLF``。用普通文本工具写出来的是裸 ``LF``，
   cmd.exe 会把它解析成乱码行，``goto`` 标签对不上，双击时窗口一闪就关。
2. **编码**：批处理里的中文要求文件编码与控制台代码页严格一致。而本项目启动
   Python 时会把控制台输出代码页切成 UTF-8（见 :mod:`career_compass.console`），
   批处理里排在后面的中文就跟着花了。

把菜单搬进 Python 之后，``run.cmd`` 退化成一段纯 ASCII 的转发脚本 —— 换行是
LF 还是 CRLF、控制台是 936 还是 65001，都不再影响它；中文输出统一交给
:func:`career_compass.console.ensure_utf8_output` 兜底。

用法::

    python scripts/menu.py          # 交互式菜单
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from career_compass.console import ensure_utf8_output  # noqa: E402

#: 生成物统一放在项目根目录，方便用户双击（层级越浅越不容易找不到）
QUESTIONNAIRE_NAME = "questionnaire.html"
SAMPLE_REPORT_NAME = "sample-report.html"
MY_REPORT_NAME = "my-report.html"
IMPORT_SCRIPT = _ROOT / "scripts" / "import_answers.py"

MENU = """
  ============================================================
    career-compass · 职业能力测评
  ============================================================

    ● 开始做测评
      [1]  生成答题页并用浏览器打开
      [2]  导入我的作答，生成报告

    ● 先看效果 / 其他
      [3]  用示例数据生成一份报告（不用答题）
      [4]  检查 DeepSeek API 配置
      [5]  示例报告 + AI 解读（需要有余额的 API Key）
      [6]  运行全部测试
      [7]  退出

    提示：答题请用 [1] 打开的那个浏览器窗口。若页面出现在本对话
          的预览框里，请点页面顶部黄条里的「在独立标签页打开」，
          否则「导出作答文件」会被浏览器拦掉。
"""


def _pause() -> None:
    try:
        input("\n  按回车返回菜单...")
    except (EOFError, KeyboardInterrupt):
        print()


def _run_cli(argv: list[str]) -> int:
    """调用 career-compass 本体。"""
    from career_compass.cli import main as cli_main

    return cli_main(argv)


def _import_answers() -> int:
    """调用导入脚本；用子进程是为了让它保持「可单跑」的独立入口。"""
    return subprocess.run(
        [
            sys.executable,
            str(IMPORT_SCRIPT),
            "--report",
            MY_REPORT_NAME,
            "--open",
        ],
        cwd=str(_ROOT),
        check=False,
    ).returncode


def _run_tests() -> int:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(_ROOT),
        check=False,
    ).returncode


#: 选项 → (说明, 执行体)。执行体返回进程退出码。
ACTIONS = {
    "1": (
        "生成答题页",
        lambda: _run_cli(["questionnaire", "--out", QUESTIONNAIRE_NAME, "--open"]),
    ),
    "2": ("导入作答并生成报告", _import_answers),
    "3": (
        "示例报告",
        lambda: _run_cli(["demo", "--persona", "tech", "--html", SAMPLE_REPORT_NAME, "--open"]),
    ),
    "4": ("检查 API 配置", lambda: _run_cli(["llm-test"])),
    "5": (
        "示例报告 + AI 解读",
        lambda: _run_cli(["demo", "--persona", "tech", "--llm", "--html", SAMPLE_REPORT_NAME, "--open"]),
    ),
    "6": ("运行全部测试", _run_tests),
}


def run() -> int:
    """交互式菜单主循环。返回进程退出码。"""
    ensure_utf8_output()
    while True:
        print(MENU)
        try:
            choice = input("  请输入编号后回车: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  已退出。")
            return 0

        if choice in {"7", "q", "Q", "quit", "exit"}:
            print("\n  已退出。")
            return 0

        action = ACTIONS.get(choice)
        if action is None:
            print(f"\n  [!] 没有 {choice!r} 这个选项，请输入 1-7。")
            continue

        label, run_action = action
        print(f"\n  >>> {label}\n")
        try:
            run_action()
        except KeyboardInterrupt:
            print("\n  [!] 已中断这一步，回到菜单。")
        except Exception as e:  # noqa: BLE001 - 菜单不该因为某一步失败就整体退出
            print(f"\n  [!] 这一步出错了：{type(e).__name__}: {e}")
        _pause()


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
