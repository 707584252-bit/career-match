#!/usr/bin/env python
"""确认 pyproject.toml 里的运行时依赖为空。

「零第三方运行时依赖」是本项目的核心承诺：克隆下来就能跑，不需要先装一堆包。
承诺一旦被悄悄破掉，受害者是用户，所以这里把它做成硬性门禁。

用法::

    python scripts/check_no_runtime_deps.py

退出码 0 表示通过，1 表示依赖不为空或字段缺失。

为什么不直接在 CI 里写 ``python -c "..."``：多行内联代码要经过不同 shell
（bash / pwsh）的引号与换行处理，在 Windows runner 上会变形。写成脚本文件
是唯一在各平台都稳定的做法。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from career_compass.console import ensure_utf8_output  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES_RE = re.compile(r"^dependencies\s*=\s*\[(.*?)\]", re.S | re.M)


def main() -> int:
    ensure_utf8_output()

    path = REPO_ROOT / "pyproject.toml"
    if not path.is_file():
        print(f"[x] 找不到 {path}")
        return 1

    match = DEPENDENCIES_RE.search(path.read_text(encoding="utf-8"))
    if match is None:
        print(f"[x] {path} 中找不到 dependencies 字段")
        return 1

    deps = match.group(1).strip()
    if deps:
        print(f"[x] 运行时依赖必须为空，实际为：{deps}")
        return 1

    print("[ok] 运行时依赖确实为空")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
