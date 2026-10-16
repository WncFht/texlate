#!/usr/bin/env python3
"""验证 docs 本地链接，并从统一入口检查每份 Markdown 的导航可达性。"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


def check(root: Path) -> list[str]:
    """所有页面都检查链接；只有入口可达的页面才能使后继页面可达。"""
    root = root.resolve()
    pages = set(root.rglob("*.md"))
    parser = MarkdownIt()
    edges: dict[Path, set[Path]] = {}
    errors = []
    for page in sorted(pages):
        edges[page] = set()
        for token in parser.parse(page.read_text(encoding="utf-8")):
            for child in token.children or []:
                target = (
                    child.attrGet("href")
                    if child.type == "link_open"
                    else child.attrGet("src")
                    if child.type == "image"
                    else None
                )
                if not target:
                    continue
                url = urlsplit(target)
                if url.scheme or url.netloc or not url.path:
                    continue
                destination = (page.parent / unquote(url.path)).resolve()
                if not destination.exists():
                    errors.append(f"{page.relative_to(root)}：本地链接不存在：{target}")
                if destination in pages:
                    edges[page].add(destination)
    pending = [root / "README.md"]
    reached = set()
    while pending:
        page = pending.pop()
        if page in reached:
            continue
        reached.add(page)
        pending.extend(edges.get(page, ()))
    if root / "README.md" not in pages:
        errors.append("缺少统一入口 README.md")
    for page in sorted(pages - reached):
        errors.append(f"{page.relative_to(root)}：无法从 README.md 导航到此页面")
    print(f"docs 页面 {len(pages)} 份，入口可达 {len(pages & reached)} 份")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("docs"))
    args = parser.parse_args()
    errors = check(args.root)
    for error in errors:
        print(error)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
