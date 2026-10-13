"""本机启动器（run.cmd / terminal.cmd / menu.py）的回归测试。

背景：这两个 .cmd 曾经被写成**裸 LF** 行尾，cmd.exe 解析不了，用户双击时窗口
一闪就关、菜单全是乱码，症状是「run 打不开」且没有任何报错。事后定位成本很高，
所以这里把「批处理必须 CRLF + 纯 ASCII」变成会失败的测试。

.cmd 是本机生成物（内含绝对路径，不入库），CI 上不存在，因此相关用例会跳过；
但 ``render_*`` 这层是纯函数，任何平台都能测。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"


def _load_make_launchers():
    spec = importlib.util.spec_from_file_location("make_launchers", SCRIPTS / "make_launchers.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _has_bare_lf(text: str) -> int:
    """统计裸 LF（即前面不是 CR 的 LF）数量。"""
    return text.count("\n") - text.count("\r\n")


# ---------------------------------------------------------------------------
# 纯函数层：任何平台都能测
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("render", ["render_run_cmd", "render_terminal_cmd"])
def test_rendered_launcher_uses_crlf_only(render):
    text = getattr(_load_make_launchers(), render)()
    assert _has_bare_lf(text) == 0, "批处理出现裸 LF，cmd.exe 会解析失败（双击一闪就关）"
    assert text.count("\r\n") >= 5
    assert text.startswith("@echo off\r\n")


@pytest.mark.parametrize("render", ["render_run_cmd", "render_terminal_cmd"])
def test_rendered_launcher_is_pure_ascii(render):
    """批处理里只要出现非 ASCII，控制台代码页一变就会花屏。中文交给 Python 输出。"""
    text = getattr(_load_make_launchers(), render)()
    assert text.isascii()
    text.encode("ascii")  # 不抛异常即通过


def test_run_cmd_keeps_passthrough_and_pauses_on_error():
    text = _load_make_launchers().render_run_cmd()
    assert "career_compass %*" in text, "透传模式丢了：run.cmd <子命令> 必须能转发给 CLI"
    assert "menu.py" in text, "菜单入口丢了"
    assert "if errorlevel 1 pause" in text, "出错时窗口会一闪就关，用户看不到任何信息"


def test_terminal_cmd_launches_bash():
    text = _load_make_launchers().render_terminal_cmd()
    assert "--login -i" in text


# ---------------------------------------------------------------------------
# 真实文件层：本机才有（.cmd 不入库）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (REPO_ROOT / "run.cmd").is_file(),
    reason="run.cmd 是本机生成物，仓库里没有",
)
def test_local_launchers_are_healthy():
    issues = _load_make_launchers().problems()
    assert issues == [], "启动器有问题：\n" + "\n".join(issues)


@pytest.mark.skipif(
    not (REPO_ROOT / "run.cmd").is_file(),
    reason="run.cmd 是本机生成物，仓库里没有",
)
def test_check_mode_reports_ok():
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "make_launchers.py"), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# 菜单：至少要能起来、能退出、能拒绝乱输入
# ---------------------------------------------------------------------------


def _run_menu(keys: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "menu.py")],
        input=keys,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )


def test_menu_starts_and_quits():
    r = _run_menu("7\n")
    assert r.returncode == 0
    assert "职业能力测评" in r.stdout, "菜单没打印出来（中文输出坏了？）"
    assert "已退出" in r.stdout
    # 菜单必须自带「去哪答题」的指引，否则用户又会卡在同一个地方
    assert "导出作答文件" in r.stdout


def test_menu_rejects_unknown_choice_then_quits():
    r = _run_menu("9\n7\n")
    assert r.returncode == 0
    assert "没有" in r.stdout and "9" in r.stdout


def test_menu_survives_stdin_close():
    """stdin 直接关闭（如被管道截断）时不该抛异常。"""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "menu.py")],
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0
    assert "Traceback" not in r.stderr
