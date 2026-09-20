r"""依赖记录解析：编译器自述输入集（``.fls`` INPUT / ``dependencies.mk``）。

xelatex ``-recorder`` 产 ``{stem}.fls``；tectonic ``--makefile-rules`` 产
``dependencies.mk``（Make 转义 + 未转义续行双形态）。``compiled_dependencies``
是**翻译文件集权威**（docs/spec/compile.md）；静态 ``\input`` 图只作编译失败时的
降级（probe 层）。本模块纯解析，leaf 层，不依赖引擎实现。
"""

from __future__ import annotations

import re
from pathlib import Path


def _makefile_inputs(text: str) -> list[str] | None:  # noqa: C901, PLR0912
    r"""解析 tectonic `--makefile-rules` 产物首条依赖行（含 Make 转义文件名）。

    移植自 texglot makefile_inputs——Make 转义规则刁钻，保持上游实现原样。
    """
    text = re.sub(r"\\\r?\n", " ", text)
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        separator = None
        i = 0
        while i < len(line):
            if line[i] == "\\" and i + 1 < len(line) and line[i + 1] in " \\#:\t":
                i += 2
                continue
            if line[i] == ":" and (i + 1 == len(line) or line[i + 1].isspace()):
                separator = i
                break
            i += 1
        if separator is None:
            return None
        values, current = [], []
        i = separator + 1
        while i < len(line):
            char = line[i]
            if char == "\\" and i + 1 < len(line) and line[i + 1] in " \\#:\t":
                current.append(line[i + 1])
                i += 2
                continue
            if char == "#":
                break
            if char.isspace():
                if current:
                    values.append("".join(current).replace("$$", "$"))
                    current = []
            else:
                current.append(char)
            i += 1
        if current:
            values.append("".join(current).replace("$$", "$"))
        return values
    return None


def _tectonic_unescaped_inputs(text: str) -> list[str]:
    """补解析 tectonic 未转义 prerequisite 名（每物理行一个）。保持上游实现。"""
    values = []
    started = False
    for raw in text.splitlines():
        line = raw
        if not started:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            separator = re.search(r"(?<!\\):(?=\s|$)", line)
            if separator is None:
                return []
            line = line[separator.end() :]
            started = True
        continued = line.endswith("\\")
        value = (line[:-1] if continued else line).strip()
        if value:
            values.append(value)
        if not continued:
            break
    return values


def _deps_from_record(main: str, out: Path, engine: str) -> list[str] | None:
    """读依赖记录文件（.fls INPUT / dependencies.mk）→ 原始名字列表。"""
    if engine == "tectonic":
        record = out / "dependencies.mk"
        if not record.is_file():
            return None
        content = record.read_text(encoding="utf-8", errors="replace")
        names = _makefile_inputs(content)
        if names is None:
            return None
        return names + _tectonic_unescaped_inputs(content)
    record = out / (Path(main).stem + ".fls")
    if not record.is_file():
        return None
    lines = record.read_text(encoding="utf-8", errors="replace").splitlines()
    names = [ln[6:] for ln in lines if ln.startswith("INPUT ")]
    return names or None


def compiled_dependencies(
    root: Path, main: str, out: Path, engine: str
) -> list[str] | None:
    r"""编译器自述的真实输入集——**翻译文件集权威**（docs/spec/compile.md）。

    xelatex 读 `-recorder` 产的 `.fls` INPUT 行；tectonic 读
    `--makefile-rules` 产物。静态 `\input` 图只作编译失败时的降级。
    图件（.eps 等）不算 TeX 输入层——不做开关，恒不收。
    """
    root = root.resolve()
    cwd = (root / main).parent
    out = out.resolve()
    names = _deps_from_record(main, out, engine)
    if names is None:
        return None
    files = set()
    extensions = {".tex", ".sty", ".cls", ".cfg", ".def", ".clo", ".fd", ".ltx"}
    for name in names:
        path = Path(name)
        candidates = [path] if path.is_absolute() else [cwd / path]
        # tectonic 的 Make 规则把 input 写成相对 outdir 的名字，
        # 尽管实际读取是相对主文件目录——两种解都试。
        if engine == "tectonic":
            candidates.extend(
                cwd / value.relative_to(out)
                for value in (path, path.resolve())
                if value.is_relative_to(out)
            )
        for cand in candidates:
            resolved = cand.resolve()
            if (
                resolved.is_relative_to(root)
                and resolved.is_file()
                and resolved.suffix.lower() in extensions
            ):
                files.add(resolved.relative_to(root).as_posix())
                break
    if Path(main).as_posix() not in files:
        return None
    return sorted(files)
