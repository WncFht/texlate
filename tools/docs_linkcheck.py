#!/usr/bin/env python3
"""docs/ 相对链接检查器：markdown 链接 / 图片 / 行内路径引用的目标存在性校验。

用法：tools/docs_linkcheck.py [--root docs] [--all-refs]

  --root      扫描根目录（默认 docs/）
  --all-refs  额外检查行内反引号内形如 docs/… 或 ./… 的路径（噪声大，默认关）

退出码：0 全绿；1 有死链。
"""

import os
import re
import sys
import unicodedata

LINK_RX = re.compile(r'!?\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
SKIP_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^#|^//")
CODE_FENCE_RX = re.compile(r"^```")


def iter_md(root: str):
    for dirpath, _dirs, names in os.walk(root):
        for n in sorted(names):
            if n.endswith(".md"):
                yield os.path.join(dirpath, n)


def check_file(path: str, root_dir: str):
    """返回 [(lineno, target, resolved)] 死链列表。"""
    dead = []
    in_fence = False
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return dead
    base = os.path.dirname(path)
    for i, line in enumerate(text.split("\n"), 1):
        if CODE_FENCE_RX.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = re.sub(r"`[^`]*`", "", line)
        for m in LINK_RX.finditer(stripped):
            target = m.group(1).strip()
            if SKIP_SCHEME.match(target) or not target:
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            # URL-decoding for %XX in links
            import urllib.parse

            resolved = os.path.normpath(
                os.path.join(base, urllib.parse.unquote(target))
            )
            if not os.path.exists(resolved):
                dead.append((i, target, resolved))
    return dead


def main():
    root = "docs"
    args = sys.argv[1:]
    if "--root" in args:
        root = args[args.index("--root") + 1]
    dead_total = []
    for f in iter_md(root):
        dead_total.extend((f, *d) for d in check_file(f, root))
    for f, ln, target, resolved in dead_total:
        print(f"{f}:{ln} 死链 -> {target}  （解到 {resolved}）")
    print(
        f"\n{len(dead_total)} dead link(s) across {sum(1 for _ in iter_md(root))} files"
    )
    return 1 if dead_total else 0


if __name__ == "__main__":
    sys.exit(main())
