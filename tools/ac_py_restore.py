"""autocorrect-on-py 手术回植：把非 docstring 的字符串字面量恢复为 HEAD 原文。

autocorrect 对 py 是平文处理器——``--fix`` 连运行时字符串一起改写（会破坏
测试夹具/协议字面量字节）。py 面 CJK 标点归一的正确姿势是两段式：

    autocorrect --fix FILE...          # 先全量 fix
    tools/ac_py_restore.py FILE...     # 再回植字符串

本脚本对每个文件：tokenize 新旧两侧（旧 = ``git show HEAD:<file>``）、按
token 序对齐，把 STRING/FSTRING_MIDDLE 中非 docstring 的 token 文本回植为
旧版；token 流错位/回植校验失败/残余 code 面改动则整文件回退 HEAD。
回植后复跑 ``autocorrect --lint`` 残余违规应只剩字符串内（有意保留的）。

用法：``python3 tools/ac_py_restore.py FILE [FILE ...]``（目标=已被 --fix
改写的 tracked py 文件；未变更文件自动跳过）。
"""

import ast
import difflib
import io
import subprocess
import sys
import token as tokmod
import tokenize
from collections import Counter
from pathlib import Path

FSTRING_MIDDLE = getattr(tokmod, "FSTRING_MIDDLE", -1)

targets = sys.argv[1:]
stats = Counter()
reports = []


def doc_lines_of(src: str) -> set[int]:
    lines: set[int] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return lines
    for node in ast.walk(tree):
        if (
            isinstance(
                node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            b0 = node.body[0]
            lines.update(range(b0.lineno, (b0.end_lineno or b0.lineno) + 1))
    return lines


def comment_lines(toks) -> set[int]:
    return {t.start[0] for t in toks if t.type == tokenize.COMMENT}


for f in targets:
    p = Path(f)
    if not p.exists():
        continue
    old = subprocess.run(
        ["git", "show", f"HEAD:{f}"], capture_output=True, text=True
    ).stdout
    new = p.read_text()
    if old == new:
        continue
    doc_lines = doc_lines_of(old)
    try:
        ot = list(tokenize.generate_tokens(io.StringIO(old).readline))
        nt = list(tokenize.generate_tokens(io.StringIO(new).readline))
    except Exception:
        subprocess.run(["git", "checkout", "HEAD", "--", f], check=False)
        stats["revert_tokenize_fail"] += 1
        reports.append(f"REVERT tokenize-fail {f}")
        continue
    if [t.type for t in ot] != [t.type for t in nt]:
        subprocess.run(["git", "checkout", "HEAD", "--", f], check=False)
        stats["revert_token_misalign"] += 1
        reports.append(f"REVERT token-misalign {f}")
        continue

    nlines = new.splitlines(keepends=True)
    edits = []  # (start_line,start_col,end_line,end_col,old_text)
    for o, n in zip(ot, nt, strict=True):
        if o.type not in (tokenize.STRING, FSTRING_MIDDLE):
            continue
        o_lines = set(range(o.start[0], o.end[0] + 1))
        if o_lines and o_lines <= doc_lines:
            continue  # docstring：保留新（已归一）文本
        if o.string != n.string:
            edits.append((n.start[0], n.start[1], n.end[0], n.end[1], o.string))
    if not edits:
        stats["already_clean"] += 1
        continue
    # 从后往前回植，offset 不漂移
    for sl, sc, el, ec, text in sorted(edits, reverse=True):
        if sl == el:
            nlines[sl - 1] = nlines[sl - 1][:sc] + text + nlines[sl - 1][ec:]
        else:
            head = nlines[sl - 1][:sc]
            tail = nlines[el - 1][ec:]
            nlines[sl - 1 : el] = [head + text + tail]
    spliced = "".join(nlines)
    try:
        ast.parse(spliced)
        st = list(tokenize.generate_tokens(io.StringIO(spliced).readline))
    except Exception:
        subprocess.run(["git", "checkout", "HEAD", "--", f], check=False)
        stats["revert_splice_broken"] += 1
        reports.append(f"REVERT splice-broken {f}")
        continue
    # 校验：spliced 的非 docstring 字符串 token 文本须与 old 完全一致
    # （docstring 是有意保留新文本的，不参与比较）
    if len(st) != len(ot):
        subprocess.run(["git", "checkout", "HEAD", "--", f], check=False)
        stats["revert_verify_fail"] += 1
        reports.append(f"REVERT verify-fail {f}")
        continue
    bad = False
    for o_t, s_t in zip(ot, st, strict=True):
        if o_t.type != s_t.type:
            bad = True
            break
        if o_t.type not in (tokenize.STRING, FSTRING_MIDDLE):
            continue
        o_lines = set(range(o_t.start[0], o_t.end[0] + 1))
        if o_lines and o_lines <= doc_lines:
            continue
        if s_t.string != o_t.string:
            bad = True
            break
    if bad:
        subprocess.run(["git", "checkout", "HEAD", "--", f], check=False)
        stats["revert_verify_fail"] += 1
        reports.append(f"REVERT verify-fail {f}")
        continue
    # 残余 diff 只允许落在注释/docstring 行（old 口径）
    com_lines = comment_lines(ot)
    resid_bad = []
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(
        None, old.splitlines(), spliced.splitlines(), autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        for ln in range(i1 + 1, i2 + 1):
            if ln not in com_lines and ln not in doc_lines:
                resid_bad.append(ln)
    if resid_bad:
        subprocess.run(["git", "checkout", "HEAD", "--", f], check=False)
        stats["revert_resid_code"] += 1
        reports.append(f"REVERT resid-code {f} lines={resid_bad[:8]}")
        continue
    p.write_text(spliced)
    stats["spliced"] += 1

print(dict(stats))
for r in reports:
    print(r)
