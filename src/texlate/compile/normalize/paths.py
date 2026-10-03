r"""compile.normalize.paths — 越界路径 rebase 与审计叶 (compile.normalize 域缝叶)。

``rebase_project_paths``：``\input/../foo.tex`` 越界引用重写为包内正确
相对路径（只修剥掉 ``../`` 后能在包内找到同名文件的情形）；
``source_path_violations``：``\input/\include/\includegraphics/\openin/
\openout`` 越界/绝对路径/管道审计（早失败 + 可诊断层）。
transcode 的 ``_read_tex_path`` 经本叶保留 ``normalize`` 门面的转口
再导出语义。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from texlate.compile.mask import TEX_SOURCE_SUFFIXES, visible_tex
from texlate.compile.transcode import (
    AUX_BIB_SUFFIXES,
    _iter_files,
    _read_tex,
    _read_tex_path,  # noqa: F401  # 转口再导出（与本件 ``_iter_files`` 同款先例）
)
from texlate.textutil import safe_is_file, safe_resolve

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------- 12. 越界路径 rebase
def _apply_rebase_edits(
    root: Path, path: Path, text: str, edits: list[tuple[int, int, str]]
) -> list[str]:
    """单文件逆序回放 rebase 编辑 → 改动位次表；写失败 → 原样不动、无位次。

    ``text`` 用枚举臂已解码的原文——不重复 read/decode（位次在遮蔽视图
    与原文等长，定位坐标两视图通用）。
    """
    locations = []
    for start, end, relative in sorted(edits, reverse=True):
        locations.append(
            f"{path.relative_to(root)}:{text.count(chr(10), 0, start) + 1}"
        )
        text = text[:start] + relative + text[end:]
    try:
        path.write_text(text, encoding="utf-8", newline="")
    except OSError:
        return []  # 写不进不记位次，保持原样
    return locations


def rebase_project_paths(root: Path, main: str) -> list[str]:
    r"""`\input/../foo.tex` 越界引用重写为包内正确相对路径。

    只修"剥掉 ../ 后能在包内找到同名文件"的情形；返回改动位置列表
    `relpath:lineno` 供日志。解不开的越界引用原样保留。
    """
    root = root.resolve()
    cwd = (root / main).parent
    changes: dict[Path, list[tuple[int, int, str]]] = {}
    decoded: dict[Path, str] = {}
    for path in _iter_files(root, TEX_SOURCE_SUFFIXES | AUX_BIB_SUFFIXES):
        raw = _read_tex(path)
        if raw is None:
            continue
        text = visible_tex(raw)
        # 成员集刻意窄收 \input/\include：本站是 ``../`` 前缀改写的手术
        # 面，仅限 tex 包含命令。
        for match in re.finditer(
            r"\\(?:input|include)(?![A-Za-z@])\s*"
            r"(?:\{([^{}]*)\}|([^\s{}%]+))",
            text,
        ):
            group = 1 if match[1] is not None else 2
            name = match[group].strip()
            if not name.startswith("../") or re.search(r"[\\#{}~]", name):
                continue
            while name.startswith("../"):
                name = name[3:]
            candidate = safe_resolve(root / name)
            if (
                candidate is not None
                and candidate.is_relative_to(root)
                and safe_is_file(candidate)
            ):
                relative = Path(os.path.relpath(candidate, cwd)).as_posix()
                changes.setdefault(path, []).append((*match.span(group), relative))
                decoded[path] = raw
    locations = []
    for path, edits in changes.items():
        locations.extend(_apply_rebase_edits(root, path, decoded[path], edits))
    return sorted(locations)


def _is_within(root: Path, candidate: Path) -> bool:
    """``candidate`` 解后是否落 ``root`` 内；解不开 → 按越界计（审计面宁报不漏）。"""
    resolved = safe_resolve(candidate)
    return resolved is not None and resolved.is_relative_to(root)


def source_path_violations(
    root: Path, main: str | None = None
) -> Iterator[tuple[Path, re.Match[str], str]]:
    r"""审计 `\input/\include/\includegraphics/\openin/\openout` 越界/绝对路径/管道。

    逐文件 yield `(path, match, message)`；编译本身另有
    `-no-shell-escape`/`--untrusted` + env 白名单兜底（§4.4），这里是
    "早失败 + 可诊断"层。`rebase_project_paths` 修不掉的在这暴露。
    """
    root = root.resolve()
    cwd = (root / main).parent if main else root
    for p in _iter_files(root, TEX_SOURCE_SUFFIXES | AUX_BIB_SUFFIXES):
        text = _read_tex(p)
        if text is None:
            continue  # 不可读件/tar 伪装件——成员文本里的路径引用不算越界证据
        text = visible_tex(text)
        # \input 族审计集与 textutil ``INPUT_BRACED_RX``/``INPUT_BARE_RX``、
        # ``arxiv.locate._REF_RES`` 刻意不同集（textutil 注记明写该族不按
        # 单枚正则单源）：本站收「单路径实参」的越界向量——
        # input/include/includegraphics + openin/openout 的 ``\cs=<file>``
        # 形；``_REF_RES`` 拓扑全扫另含双参 import 族/subfile/bibliography
        # 等不适用单名捕获的命令，rebase 手术面则收窄到 input/include。
        for match in re.finditer(
            r"\\(?:input|include|includegraphics)(?![A-Za-z@])\s*"
            r"(?:\[[^]]*\])?\s*(?:\{([^{}]*)\}|([^\s{}%]+))"
            # \openin/\openout 实参是 \cs=<file>（或 <num>=<file>）——
            # 旧式把 `\w=|cmd` 整体当名字，管道符被吞 → 漏检
            r"|\\(?:openin|openout)(?![A-Za-z@])\s*"
            r"(?:\\[a-zA-Z@]+|\d+)\s*=\s*(?:\{([^{}]*)\}|([^\s{}%]+))",
            text,
        ):
            name = next(g for g in match.groups() if g is not None).strip()
            absolute = re.match(r"/|~|[A-Za-z]:", name)
            outside = ".." in Path(name).parts and not _is_within(root, cwd / name)
            if absolute or outside or name.startswith("|"):
                message = (
                    r"源码包含外部命令输入（\input{|cmd}），受限编译不支持"
                    if name.startswith("|")
                    else "引用超出工程目录，请将依赖文件放入源码包并使用相对路径"
                )
                yield p, match, message
