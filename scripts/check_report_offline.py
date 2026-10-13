#!/usr/bin/env python
"""校验生成的 HTML 报告不引用任何外部资源。

为什么需要这个脚本：报告会被用户保存到本地、丢进邮件、放进聊天窗口。
只要有一个 CDN 链接，离线打开时样式和图就会全丢。
这个检查把「零外链」从口头约定变成 CI 里的硬性门禁。

用法::

    python scripts/check_report_offline.py report.html [report2.html ...]

退出码 0 表示通过，1 表示发现了外部资源引用。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: SVG 命名空间不是资源请求，是规范要求的声明，必须放行
ALLOWED_URLS = {
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xlink",
}

#: 会被浏览器主动请求的属性
RESOURCE_ATTRS = (
    "src",
    "href",
    "srcset",
    "data",
    "poster",
    "action",
)

URL_RE = re.compile(r"""https?://[^"'()\s>]+""")
TAG_RE = re.compile(r"<(script|link|img|iframe|video|audio|source|embed|object)\b[^>]*>", re.I)
ATTR_RE = re.compile(r"""(\w[\w-]*)\s*=\s*["']([^"']*)["']""")


def check(path: Path) -> list[str]:
    """返回问题列表，空列表表示通过。"""
    html = path.read_text(encoding="utf-8")
    problems: list[str] = []

    # 1) 任何 url(...) 形式的 CSS 外部引用
    for m in re.finditer(r"url\(\s*['\"]?(https?:)?//[^)]*\)", html, re.I):
        problems.append(f"CSS url() 引用了外部资源: {m.group(0)[:90]}")

    # 2) 所有出现的 http(s) 链接，排除白名单
    for m in URL_RE.finditer(html):
        url = m.group(0)
        if url in ALLOWED_URLS:
            continue
        problems.append(f"发现外部 URL: {url[:90]}")

    # 3) 会触发资源加载的标签
    for m in TAG_RE.finditer(html):
        tag = m.group(0)
        name = m.group(1).lower()
        # <a href> 是导航链接，不算资源加载，但要提醒
        if name == "script":
            if "src=" in tag.lower():
                problems.append(f"存在外部 <script src>: {tag[:90]}")
        else:
            for attr, value in ATTR_RE.findall(tag):
                if attr.lower() in RESOURCE_ATTRS and value.strip():
                    problems.append(f"<{name}> 的 {attr} 指向资源: {value[:70]}")

    return problems


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    failed = False
    for name in argv[1:]:
        path = Path(name)
        if not path.is_file():
            print(f"[x] 文件不存在: {path}")
            failed = True
            continue
        problems = check(path)
        if problems:
            failed = True
            print(f"[x] {path} 存在 {len(problems)} 处外部依赖：")
            for p in problems[:20]:
                print(f"    - {p}")
            if len(problems) > 20:
                print(f"    ... 另有 {len(problems) - 20} 处")
        else:
            size_kb = path.stat().st_size / 1024
            print(f"[ok] {path} 零外部依赖（{size_kb:.1f} KB）")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
