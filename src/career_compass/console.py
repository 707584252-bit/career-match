"""控制台输出的编码兜底。

这个模块解决的是一个真实踩过的坑：**Windows 的默认控制台代码页无法编码中文**
（英文系统是 cp1252，只认西欧字符）。此时直接 ``print`` 中文不是"显示成乱码"，
而是抛 ``UnicodeEncodeError``，把命令在最后一步直接打断——用户什么结果都拿不到。

CI 的 windows 任务正是死在这里，本地中文系统反而看不出来。

:func:`ensure_utf8_output` 做两件事，且是幂等的：

1. Windows 下把控制台输出代码页切到 UTF-8（65001），中文才能正常显示；
   非 Windows 或调用失败时安静跳过。
2. 把 ``sys.stdout`` / ``sys.stderr`` 重配置为 UTF-8，并把无法编码的字符降级为 ``?``
   （``errors="replace"``）。因此输出被重定向到文件或管道时同样是 UTF-8，
   日志里不会出现乱码。

用法::

    from career_compass.console import ensure_utf8_output

    ensure_utf8_output()   # 在打印任何内容之前调用一次
"""

from __future__ import annotations

import os
import sys

#: Windows 的 UTF-8 代码页编号
WINDOWS_UTF8_CODE_PAGE = 65001

#: 视为「已经是 UTF-8」的编码名写法
_UTF8_ALIASES = frozenset({"utf8", "utf8mb4", "cp65001", "u8", "unicode11utf8"})


def _normalize(encoding: str | None) -> str:
    return (encoding or "").lower().replace("-", "").replace("_", "")


def is_utf8(encoding: str | None) -> bool:
    """判断编码名是否等价于 UTF-8。"""
    return _normalize(encoding) in _UTF8_ALIASES


def _switch_windows_console_to_utf8() -> bool:
    """把 Windows 控制台输出代码页切到 UTF-8，返回是否成功。

    非 Windows 平台、无控制台（输出被重定向）或调用失败时返回 ``False``，
    调用方无需关心失败原因——第 2 步的 ``errors="replace"`` 已经保证不会崩。
    """
    if os.name != "nt":  # pragma: no cover - 平台分支
        return False
    try:
        import ctypes
    except ImportError:  # pragma: no cover - 标准库，正常不会失败
        return False
    try:
        return bool(ctypes.windll.kernel32.SetConsoleOutputCP(WINDOWS_UTF8_CODE_PAGE))
    except (AttributeError, OSError):  # pragma: no cover - 依赖具体平台
        return False


def ensure_utf8_output() -> None:
    """保证标准输出与标准错误能够安全打印任意 Unicode 文本。

    幂等：重复调用没有副作用；流已经是 UTF-8 时不做任何改动。
    """
    _switch_windows_console_to_utf8()

    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            # 被外部包装过的流（测试框架的捕获对象、日志包装器）不支持重配置，
            # 跳过即可：它们本身不写控制台，不会触发编码错误。
            continue
        if is_utf8(getattr(stream, "encoding", None)):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - 流已关闭等异常情况
            pass
