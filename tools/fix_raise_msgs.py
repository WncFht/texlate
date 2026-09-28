#!/usr/bin/env python3
"""raise 字面量外提 codemod——TRY003/EM101/EM102 消债批处理器。

`raise E(<lit>)` → `msg = <lit>` + `raise E(msg)`；f-string/多实参/关键字实参同口径，
多行字面量加括号续行；单行 `if c: raise` 拒绝并打 SKIP。默认 dry-run 只报不改，
--write 才落盘；目标默认 src/（目录递归 *.py，也可传单文件）。

用法: .venv/bin/python tools/fix_raise_msgs.py [PATH ...] [--write]
退出码: 0 全净/写完；1 dry-run 有待改；2 有文件读/解析/产出复检错误。
"""

import argparse
import ast
import sys
from pathlib import Path


def line_starts(src: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(src):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def offset_of(lines: list[str], starts: list[int], lineno: int, col: int) -> int:
    """ast col_offset/end_col_offset 是该行 utf-8 字节偏移（非字符列）——
    含 CJK/全角行直接 starts+col 会越位，按字节截断 decode 回字符列。"""
    return starts[lineno - 1] + len(
        lines[lineno - 1].encode("utf-8")[:col].decode("utf-8")
    )


def transform_src(src: str, path: Path) -> tuple[str, int] | None:
    """对 src 跑外提变换；返回 (新源码, 外提数)，无改动返回 None。"""
    tree = ast.parse(src)
    lines = src.splitlines()
    starts = line_starts(src)
    edits = []  # (start_off, end_off, new_text)；msg 赋值插入记为 raise 行首的零宽 edit 同通道
    n = 0

    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise):
            continue
        exc = node.exc
        if not isinstance(exc, ast.Call):
            continue
        lit_args = [
            (i, a)
            for i, a in enumerate(exc.args)
            if isinstance(a, (ast.JoinedStr,))
            or (isinstance(a, ast.Constant) and isinstance(a.value, str))
        ]
        lit_args += [
            (f"kw:{kw.arg}", kw.value)
            for kw in exc.keywords
            if isinstance(kw.value, (ast.JoinedStr,))
            or (isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str))
        ]
        if not lit_args:
            continue
        raise_line = node.lineno
        line_text = lines[raise_line - 1]
        indent = line_text[: len(line_text) - len(line_text.lstrip())]
        # one-liner `if cond: raise ...` — refuse (handle manually)
        prefix = line_text[: node.col_offset]
        if prefix.strip():
            print(f"SKIP one-liner {path}:{raise_line}: {line_text.strip()}")
            continue
        names = []
        for j, (_ai, arg) in enumerate(lit_args):
            name = "msg" if len(lit_args) == 1 else f"msg{j + 1}"
            seg = ast.get_source_segment(src, arg)
            assert seg is not None
            if "\n" in seg:
                seg = (
                    "(\n"
                    + indent
                    + "    "
                    + seg.replace("\n", "\n" + indent + "    ")
                    + "\n"
                    + indent
                    + ")"
                )
            names.append((name, seg))
            a0 = offset_of(lines, starts, arg.lineno, arg.col_offset)
            a1 = offset_of(lines, starts, arg.end_lineno, arg.end_col_offset)
            edits.append((a0, a1, name))
            n += 1
        assign_lines = "".join(f"{indent}{nm} = {sg}\n" for nm, sg in names)
        edits.append((starts[raise_line - 1], starts[raise_line - 1], assign_lines))

    if not edits:
        return None

    # 全部偏移锚定原始 src，自底向上一次应用——insert 走零宽 edit 与替换同通道，
    # 多行字面量折叠不再使后续赋值按旧行号插错位（tmp 原件的行号簿记漂移已修）。
    for a0, a1, txt in sorted(edits, key=lambda e: e[0], reverse=True):
        src = src[:a0] + txt + src[a1:]
    return src, n


def iter_paths(paths):
    """每个 PATH：文件→自身，目录→sorted(rglob("*.py"))。"""
    for p in paths:
        q = Path(p)
        if q.is_dir():
            yield from sorted(q.rglob("*.py"))
        else:
            yield q


def process(path: Path, write: bool) -> int:
    """单文件处理：变换+产出 ast.parse 复检，write=True 才落盘；返回外提数，-1=错误。"""
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"ERROR {path}: 读取失败 ({e})")
        return -1
    try:
        out = transform_src(src, path)
    except (SyntaxError, AssertionError) as e:
        print(f"ERROR {path}: 源文件解析失败，跳过 ({e})")
        return -1
    if out is None:
        return 0
    new_src, n = out
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"ERROR {path}: transform 产出非法语法，未写 ({e})")
        return -1
    if write:
        try:
            path.write_text(new_src, encoding="utf-8")
        except OSError as e:
            print(f"ERROR {path}: 写盘失败 ({e})")
            return -1
        print(f"{path}: {n} hoisted")
    else:
        print(f"WOULD {path}: {n} hoisted")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(
        description="raise 字面量外提 codemod（TRY003/EM101/EM102 消债用）"
    )
    ap.add_argument(
        "paths",
        nargs="*",
        default=["src"],
        help="目标文件或目录，目录递归 *.py（默认 src/）",
    )
    ap.add_argument(
        "--write",
        action="store_true",
        help="实际落盘（默认 dry-run 只报不改）",
    )
    args = ap.parse_args()

    total = 0
    errors = 0
    for p in iter_paths(args.paths):
        c = process(p, args.write)
        if c < 0:
            errors += 1
        else:
            total += c
    if args.write:
        print(f"TOTAL {total} written")
    else:
        print(f"TOTAL {total} (dry-run; --write 落地)")
    if errors:
        return 2
    if not args.write and total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
