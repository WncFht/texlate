r"""``\input/\include`` 展平（docs/07 §7）。

触发面八形态：``\input/\include/\InputIfFileExists/\subfile/\import/
\subimport/\includestandalone/\CatchFileBetweenTags`` + 裸文件名形
``\input file``（读 ``[A-Za-z0-9._/-]+`` 至空白/反斜杠）。

- 查找序：including 文件目录 → 项目根 → paper topdir（可选兜底，
  e-print 解压根＝LaTeX 编译 cwd 语义）→ basename 补 ``.tex`` → 裸名。
- 注释内 ``\input`` 在 Mouth 层吞掉天然不触发；verbatim env / ``\verb`` 内不触发。
- ``\subfile``/``\includestandalone`` 展开时剥 document 壳
  （``\begin{document}`` 前与 ``\end{document}`` 起的内容丢弃——子文件自带
  document 壳时正文才能见光，``\end{document}`` 只在顶层截停，2609.06443 实修）。
- 防护：``MAX_INPUTS=8`` 深度 + ``_seen`` 祖先栈断环
  （W12 已修：栈内命中断真环，兄弟位合法重包含照常内联；
  主文件路径在 ``parse_file`` 预种——``\input{self}`` 直接断）。
  ``\includeonly`` 忽略。
"""

from __future__ import annotations

import re
from pathlib import Path

from texlate.latex.model import (
    ScanWarning,
    env_name_at,
    match_brace,
    read_cmd_name,
    skip_verb_at,
    ws_skip,
)
from texlate.latex.tables import FILENAME_CHARS, MAX_INPUTS, VERBATIM_ENVS
from texlate.textutil import decode_tex, mask_tex

_DOC_BEGIN_RX = re.compile(r"\\begin\s*\{document\}")
_DOC_END_RX = re.compile(r"\\end\s*\{document\}")


def strip_doc_shell(tex: str) -> str:
    r"""剥 ``\documentclass…\begin{document}`` / ``\end{document}`` 壳（subfile/standalone）。

    找不到 ``\begin{document}`` → 原样返回；只有壳标记残缺时尽力取正文。
    壳标记查找跑 ``mask_tex`` 视图——注释/逐字里的假 ``\begin{document}``
    （arXiv 子文件常见注释掉的备用壳）不参与定位（W11 同源修复）。
    """
    masked = mask_tex(tex)
    b = _DOC_BEGIN_RX.search(masked)
    if not b:
        return tex
    body = tex[b.end() :]
    e = _DOC_END_RX.search(mask_tex(body))
    return body[: e.start()] if e else body


def _resolve(
    fname: str, file_dir: str, root_dir: str, *, top_dir: str | None = None
) -> str | None:
    r"""查找序：including 目录 → 项目根 → paper topdir → basename 补 .tex → 裸名。

    ``top_dir`` 是论文顶层目录兜底（深位 root 文件按 e-print 根的相对路径
    ``\input``，hep-ex/0307068 ``./LaTeX/zeus/…`` 实例）；缺省即旧两级行为。
    """
    cands = (
        [fname]
        if fname.lower().endswith(".tex")
        else [fname, fname + ".tex", fname + ".TEX"]  # 野存在大写扩展名（corpus_v3）
    )
    dirs = tuple(
        dict.fromkeys(
            (file_dir, root_dir) if top_dir is None else (file_dir, root_dir, top_dir)
        )
    )  # file_dir==root_dir 常见——去重免重复 stat
    for d in dirs:
        for c in cands:
            p = Path(d) / c
            if p.exists():
                return str(p)
    stem = Path(fname).name
    for d in dirs:
        for ext in (".tex", ".TEX"):
            p = Path(d) / (stem + ext)
            if p.exists():
                return str(p)
    for d in dirs:
        p = Path(d) / fname
        if p.exists():
            return str(p)
    return None


def _read_file(path: str) -> str:
    """文件读取接缝（bench ``flatten_reach`` 的 open 记录器经 shim 重绑这里）。"""
    return decode_tex(Path(path).read_bytes())


def _extract_tag_region(tex: str, tag: str) -> str | None:
    r"""``\CatchFileBetweenTags`` 的标签区提取：``%<*tag>`` … ``%</tag>``。"""
    start_rx = re.compile(r"%\s*<\*?" + re.escape(tag) + r">")
    end_rx = re.compile(r"%\s*</" + re.escape(tag) + r">")
    s = start_rx.search(tex)
    if not s:
        return None
    e = end_rx.search(tex, s.end())
    return tex[s.end() : e.start() if e else len(tex)]


def flatten_inputs(  # noqa: C901, PLR0912, PLR0913, PLR0915 — 单遍逐字符主循环，分支序即语义（docs/07 §3 五条铁律）
    tex: str,
    file_dir: str,
    root_dir: str | None = None,
    depth: int = 0,
    _seen: set[str] | None = None,
    warnings: list[ScanWarning] | None = None,
    *,
    top_dir: str | None = None,
) -> str:
    r"""展开 ``\input/\include`` 族（八形态 + 裸文件名）。

    先相对当前文件目录，再相对主文件目录（LaTeX/TEXINPUTS 语义）；
    ``top_dir`` 给定论文顶层目录时作第三级兜底（深位 root 的
    e-print 根相对 ``\input``）。注释掉的 ``\input`` 不展开；verbatim
    环境内不展开。
    """
    if root_dir is None:
        root_dir = file_dir
    if depth > MAX_INPUTS:
        return tex
    if _seen is None:
        _seen = set()
    out: list[str] = []
    i, n = 0, len(tex)
    verb_env: str | None = None  # verbatim 类环境内不展开
    while i < n:
        c = tex[i]
        if verb_env is not None:
            pat = "\\end{" + verb_env + "}"
            if verb_env.startswith("filecontents"):
                # 与 v2 segmenter 同款锚定（W26）：filecontents 闭环境须行首
                # 独占——裸 find 会被体内 PostScript/注释的行中 \end 诱饵截短
                fm = re.compile(rf"(?m)^[ \t]*{re.escape(pat)}").search(tex, i)
                k = -1 if fm is None else fm.end() - len(pat)
            else:
                k = tex.find(pat, i)
            if k < 0:
                out.append(tex[i:])
                break
            out.append(tex[i : k + len(pat)])
            i = k + len(pat)
            verb_env = None
            continue
        if c == "%":
            k = tex.find("\n", i)
            out.append(tex[i : n if k < 0 else k])
            i = n if k < 0 else k
            continue
        if c != "\\":
            out.append(c)
            i += 1
            continue
        name, j = read_cmd_name(tex, i)
        if name == "begin":
            env, e2 = env_name_at(tex, j)
            if env in VERBATIM_ENVS:
                verb_env = env
            out.append(tex[i : e2 or j])
            i = e2 or j
            continue
        if name == "endinput":
            out.append(tex[i:j])
            break  # TeX 语义：丢弃当前文件余下内容
        if name in ("verb", "lstinline"):
            # 与 scanner._handle_verb 同一判据：EOL 上限 + lstinline[opt] 前缀
            e = skip_verb_at(tex, name, j)
            if e is not None:
                out.append(tex[i:e])
                i = e
                continue
            out.append(tex[i:j])
            i = j
            continue
        hit = _try_input(
            tex,
            i,
            name,
            j,
            file_dir,
            root_dir,
            depth,
            _seen,
            warnings,
            top_dir=top_dir,
        )
        if hit is not None:
            expanded, i = hit
            out.append(expanded)
            continue
        # 整段命令吐字面：控制符号（\\、\% 等）的第二字节不得重新起词法——
        # 逐字推进会把它当新转义起点（\\input 误内联、\\endinput 误截断）
        out.append(tex[i:j])
        i = j
    return "".join(out)


def _try_input(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915, PLR0917 — 八形态各一段参数语法，平铺即规格（docs/07 §7 触发面表）
    tex: str,
    i: int,
    name: str,
    j: int,
    file_dir: str,
    root_dir: str,
    depth: int,
    seen: set[str],
    warnings: list[ScanWarning] | None,
    *,
    top_dir: str | None = None,
) -> tuple[str, int] | None:
    r"""尝试把一个 ``\\`` 命令解释为 \\input 触发形态。

    返回 ``(展开文本, 消费后位)``；不是触发形/文件不存在 → None（调用方逐字）。
    """
    n = len(tex)
    shell = False
    fname: str | None = None
    tag: str | None = None
    end = j
    pos = ws_skip(tex, j)

    if name in ("input", "include", "@input"):
        if pos < n and tex[pos] == "{":
            e = match_brace(tex, pos)
            if not e:
                return None
            fname, end = tex[pos + 1 : e - 1].strip(), e
        elif name in ("input", "@input") and pos < n and tex[pos] in FILENAME_CHARS:
            k = pos
            while k < n and tex[k] in FILENAME_CHARS:
                k += 1
            fname, end = tex[pos:k], k
        else:
            return None
    elif name in ("subfile", "includestandalone"):
        if pos < n and tex[pos] == "{":
            e = match_brace(tex, pos)
            if not e:
                return None
            fname, end, shell = tex[pos + 1 : e - 1].strip(), e, True
        else:
            return None
    elif name in ("import", "subimport"):
        if pos < n and tex[pos] == "{":
            e = match_brace(tex, pos)
            if not e:
                return None
            subdir = tex[pos + 1 : e - 1].strip()
            p2 = ws_skip(tex, e)
            if p2 < n and tex[p2] == "{":
                e3 = match_brace(tex, p2)
                if not e3:
                    return None
                fname, end = tex[p2 + 1 : e3 - 1].strip(), e3
                fname = str(Path(subdir) / fname) if subdir else fname
            else:
                return None
        else:
            return None
    elif name == "InputIfFileExists":
        if pos < n and tex[pos] == "{":
            e = match_brace(tex, pos)
            if not e:
                return None
            fname, end = tex[pos + 1 : e - 1].strip(), e
            # {then}{else} 参数留在流内继续逐字
        else:
            return None
    elif name == "CatchFileBetweenTags":
        # \CatchFileBetweenTags\cs{file}{tag}
        p = ws_skip(tex, j)
        if p < n and tex[p] == "\\":
            _cs, p = read_cmd_name(tex, p)
        p = ws_skip(tex, p)
        if p < n and tex[p] == "{":
            e = match_brace(tex, p)
            if not e:
                return None
            fname = tex[p + 1 : e - 1].strip()
            p2 = ws_skip(tex, e)
            if p2 < n and tex[p2] == "{":
                e3 = match_brace(tex, p2)
                if not e3:
                    return None
                tag, end = tex[p2 + 1 : e3 - 1].strip(), e3
            else:
                return None
        else:
            return None
    else:
        return None

    if not fname:
        return None
    hit = _resolve(fname, file_dir, root_dir, top_dir=top_dir)
    if hit is None:
        if warnings is not None:
            warnings.append(ScanWarning("missing_input", i, f"{name}:{fname}"))
        return None
    rpath = str(Path(hit).resolve())
    if rpath in seen:
        # seen 是**祖先栈**语义（展开期间驻留、返回后弹出）——只断真环
        # a→b→a；兄弟位序合法重包含照常内联（W12 修复：曾为全局
        # once-set，第二个 \input{shared} 的内容整体丢失）。
        return None
    try:
        sub = _read_file(hit)
    except OSError:
        return None
    if shell:
        sub = strip_doc_shell(sub)
    if tag is not None:
        region = _extract_tag_region(sub, tag)
        if region is None:
            return None
        sub = region
    seen.add(rpath)
    sub = flatten_inputs(
        sub,
        str(Path(hit).parent),
        root_dir,
        depth + 1,
        seen,
        warnings,
        top_dir=top_dir,
    )
    seen.discard(rpath)
    return sub, end
