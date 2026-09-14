#!/usr/bin/env python3
r"""miniscanner — 最小 LaTeX 半解析器 spike.

架构: 容错分割 + 占位符保护 + 区间替换重建. 不做 AST.
  单次正向扫描 → pieces 流(literal / [[TYPE_n]] 占位符 / [[CHUNK_n]] 可译块)
  → protected_tex(占位符版模板) + chunks[] + 宏表
  → reconstruct: pieces splice + 不动点展开嵌套占位符

与 ieeA 管线的本质区别(教训见 bench/results/ieeA-baseline-report.md):
  * 逐字符 tokenizer 而非逐行正则 → \% vs \\%、\verb|a%b|、\url{..%20..} 全对
  * 顺序: verbatim/环境识别 → 注释 → 宏表 → 分段提取 (一次扫描内完成,
    verbatim 内容在 % 判定之前已被整段吃掉)
  * 宏表: \newcommand/\renewcommand/\def/\NewDocumentCommand 调用点查表,
    结构宏(\be→\begin{equation})展开保护, 数学宏(\dR)整体保护,
    含引用宏(\figref#1→figure~\ref{#1})按参数位置保护 key
  * caption/footnote/section 的 chunk 抽取在保护扫描*之中*递归进行,
    块内 $ \cite \ref 永远先被占位 → 无 ieeA "caption 内 \cite 裸漏"
  * reconstruct 对 chunk/保护占位符统一迭代至不动点 → 三层嵌套无死 token

区间模型: pieces 覆盖全文(含注释逐字保留); reconstruct 输出恒可 splice 回
与 protected_tex 同构的完整文档. identity 重建 = 原文逐字节一致.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------- 命令族表

# 数学环境族 → [[MATH_n]] (含 * 变体)
MATH_ENVS = {
    "equation",
    "align",
    "gather",
    "multline",
    "flalign",
    "alignat",
    "eqnarray",
    "subequations",
    "IEEEeqnarray",
    "dmath",
    "empheq",
    "math",
    "displaymath",
    "cases",
    "split",
    "gathered",
    "aligned",
    "alignedat",
    "array",
    "matrix",
    "pmatrix",
    "bmatrix",
    "vmatrix",
    "Bmatrix",
    "smallmatrix",
    "equationarray",
    "xxalignat",
}
MATH_ENVS |= {e + "*" for e in list(MATH_ENVS)}

# 逐字环境: 整体跳过, % 不是注释, 内部不挖 caption
VERBATIM_ENVS = {"verbatim", "lstlisting", "minted", "comment", "Verbatim"}
VERBATIM_ENVS |= {e + "*" for e in list(VERBATIM_ENVS)}

# 保护环境: 整段 → [[ENV_n]], 但内部递归挖 \caption/\footnote 为 chunk
PROTECTED_ENVS = {
    "figure",
    "figure*",
    "table",
    "table*",
    "tabular",
    "tabularx",
    "tabulary",
    "longtable",
    "sidewaystable",
    "wraptable",
    "wrapfigure",
    "algorithm",
    "algorithm2e",
    "algorithmic",
    "algorithmicx",
    "tikzpicture",
    "pgfpicture",
    "picture",
    "pspicture",
}

# 参数挖为独立 chunk 的命令 (不受 20 字符阈值限制)
CHUNK_ARG_NAMES = {
    "section",
    "subsection",
    "subsubsection",
    "paragraph",
    "subparagraph",
    "chapter",
    "part",
    "sect",
    "subsect",  # ptptex 旧式
    "caption",
    "subcaption",
    "captionof",
    "title",
    "subtitle",
    "thanks",
    "footnote",
    "footnotetext",
    "abst",
    "keywords",
}

# 整块保护命令 (\author{..} 等 → [[AUTHOR_n]])
PROTECT_BLOCK_NAMES = {
    "author",
    "inst",
    "address",
    "affiliation",
    "date",
    "markboth",
    "markright",
    "preprintnumber",
    "recdate",
    "publishedin",
    "institute",
    "email",
    "orcid",
}

# cite/ref 两族 (词族匹配见 _dispatch_cmd)
CITE_NAMES = {
    "cite",
    "citep",
    "citet",
    "citealp",
    "citealt",
    "citeauthor",
    "citeyear",
    "citeyearpar",
    "citetext",
    "citeonline",
    "parencite",
    "textcite",
    "footcite",
    "smartcite",
    "supercite",
    "autocite",
    "fullcite",
    "shortcite",
    "citeN",
    "citeasnoun",
    "citenum",
    "nocite",
    "upcite",
    "citeyearnp",
}
REF_NAMES = {
    "ref",
    "eqref",
    "autoref",
    "cref",
    "Cref",
    "crefrange",
    "cpageref",
    "pageref",
    "nameref",
    "vref",
    "vpageref",
    "fref",
    "Fref",
    "subref",
    "labelcref",
    "labelpageref",
}
PROTECT_NAMES = {
    "label",
    "url",
    "includegraphics",
    "bibliography",
    "bibliographystyle",
    "index",
    "gls",
    "Gls",
    "doi",
    "path",
    "includepdf",
    "bibitem",
    "inputminted",
    "lstinputlisting",
    "verbatiminput",
    "lstinline",
}

# 透明命令: 参数内联扫描 (inner text 进入当前 run/chunk)
TRANSPARENT_NAMES = {
    "emph",
    "textbf",
    "textit",
    "textsc",
    "textsl",
    "textsf",
    "texttt",
    "textrm",
    "textmd",
    "textup",
    "textnormal",
    "underline",
    "mbox",
    "hbox",
    "fbox",
    "makebox",
    "framebox",
    "textcolor",
    "colorbox",
    "hl",
    "sout",
    "uline",
    "uwave",
    "noindent",
    "hspace",
    "vspace",
    "footnote",
    "footnotemark",
}
TRANSPARENT_NAMES.discard("footnote")  # footnote 是 chunk-arg 命令
TRANSPARENT_NAMES.discard("hspace")
TRANSPARENT_NAMES.discard("vspace")

# 行级字面命令: 文本 run 的硬边界, 本体逐字保留
BOUNDARY_NAMES = {
    "item",
    "maketitle",
    "centering",
    "centerline",
    "hline",
    "toprule",
    "midrule",
    "bottomrule",
    "cline",
    "cmidrule",
    "newpage",
    "clearpage",
    "cleardoublepage",
    "pagebreak",
    "linebreak",
    "nopagebreak",
    "tableofcontents",
    "listoffigures",
    "listoftables",
    "appendix",
    "vspace",
    "hspace",
    "vfill",
    "hfill",
    "vskip",
    "hskip",
    "smallskip",
    "medskip",
    "bigskip",
    "indent",
    "par",
    "newline",
    "columnbreak",
    "balance",
    "onecolumn",
    "twocolumn",
    "newcounter",
    "setcounter",
    "addtocounter",
    "setlength",
    "addtolength",
    "setstretch",
    "pagestyle",
    "thispagestyle",
    "pagenumbering",
    "makeatletter",
    "makeatother",
    "frontmatter",
    "mainmatter",
    "backmatter",
    "bibliographystyle_",
    "documentclass",
    "documentstyle",
    "usepackage",
    "RequirePackage",
    "newtheorem",
}
BOUNDARY_NAMES.discard("bibliographystyle_")

# 零参/单字符安全字面命令 (行内, 不破 run): 重音、符号、品牌名
ACCENT_CHARS = set("'`^\"~=.uvHtcdbkz")
INLINE_LITERAL_CMDS = {
    "LaTeX",
    "TeX",
    "LaTeXe",
    "today",
    "quad",
    "qquad",
    "ldots",
    "dots",
    "dotsb",
    "dotsc",
    "dotsm",
    "textasciitilde",
    "textasciicircum",
    "textbackslash",
    "textdegree",
    "dag",
    "dagger",
    "ddag",
    "ddagger",
    "S",
    "P",
    "copyright",
    "pounds",
    "aa",
    "AA",
    "ae",
    "AE",
    "oe",
    "OE",
    "o",
    "O",
    "l",
    "L",
    "ss",
    "i",
    "j",
    "enspace",
    "thinspace",
    "negthinspace",
    "enskip",
    "hline_",
    "textquoteright",
}
INLINE_LITERAL_CMDS.discard("hline_")

# 旧式 2.09 字体开关: 无参, 行内字面
FONT_SWITCHES = {
    "rm",
    "bf",
    "it",
    "sl",
    "sf",
    "tt",
    "sc",
    "em",
    "cal",
    "mit",
    "tiny",
    "scriptsize",
    "footnotesize",
    "small",
    "normalsize",
    "large",
    "Large",
    "LARGE",
    "huge",
    "Huge",
    "HUGE",
    "normalfont",
    "bfseries",
    "mdseries",
    "itshape",
    "slshape",
    "scshape",
    "upshape",
    "ttfamily",
    "sffamily",
    "rmfamily",
}

# \begin 后要吞掉强制 {arg} 的环境 (宽/格式参数, 非文本)
ENV_MANDATORY_ARG = {
    "minipage",
    "parbox",
    "tabular",
    "tabularx",
    "tabulary",
    "array",
    "list",
    "thebibliography",
    "subfigure",
    "wrapfigure",
    "wraptable",
}

COND_RX = re.compile(r"^(if[a-zA-Z@]*|else|fi|or)$")
CHUNK_MIN = 20


def _cname(ph: str) -> str:
    return "[[" + ph + "]]"


@dataclass
class Macro:
    name: str
    nargs: int = 0
    has_opt: bool = False
    kind: str = "transparent"  # env_begin/env_end/opaque/transparent/literal
    target_env: str = ""
    protect_args: Tuple[bool, ...] = ()
    body: str = ""


@dataclass
class Chunk:
    id: int
    content: str  # 原文区间 verbatim (含内嵌 [[TYPE_n]])
    context: str = "paragraph"


@dataclass
class ScanResult:
    protected_tex: str
    chunks: List[Chunk]
    ph_map: Dict[str, str]
    macros: Dict[str, Macro]
    pieces: List[Tuple[str, object]] = field(default_factory=list)
    inputs: List[Tuple[int, str]] = field(default_factory=list)


class Scanner:
    """单次正向扫描器. pos 单调递增, 永不回退."""

    def __init__(self, macros: Optional[Dict[str, Macro]] = None):
        self.macros: Dict[str, Macro] = macros if macros is not None else {}
        self.chunks: List[Chunk] = []
        self.ph_map: Dict[str, str] = {}
        self.pieces: List[Tuple[str, object]] = []
        self.inputs: List[Tuple[int, str]] = []
        self._ctr = [0]  # 占位符计数器 (子扫描器共享, 防编号冲突)
        self._mined_only = False  # 保护环境内部: 只挖 caption/footnote
        self._arg_inline = False  # chunk 参数内部: 嵌套 chunk-arg 内联化
        self._force_chunk = False  # \item 后: 下一 run 不受 20 字符阈值限制

    # ------------------------------------------------------------ 小工具
    def _ph(self, typ: str, body: str) -> str:
        self._ctr[0] += 1
        p = _cname(f"{typ}_{self._ctr[0]}")
        self.ph_map[p] = body
        return p

    def _chunk(self, content: str, context: str) -> str:
        cid = len(self.chunks)
        self.chunks.append(Chunk(cid, content, context))
        return _cname(f"CHUNK_{cid}")

    def _emit(self, s: str) -> None:
        if s:
            self.pieces.append(("lit", s))

    @staticmethod
    def _ws(tex: str, i: int) -> int:
        n = len(tex)
        while i < n and tex[i] in " \t\n":
            i += 1
        return i

    def _match_brace(self, tex: str, i: int, verbatim: bool = False) -> Optional[int]:
        """tex[i]=='{' → 匹配 '}' 的后一位. verbatim=False 时 %..EOL 内括号不计."""
        if i >= len(tex) or tex[i] != "{":
            return None
        depth, j, n = 1, i + 1, len(tex)
        while j < n:
            c = tex[j]
            if c == "\\":
                j += 2
                continue
            if c == "%" and not verbatim:
                k = tex.find("\n", j)
                j = n if k < 0 else k + 1
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return None

    def _match_bracket(self, tex: str, i: int) -> Optional[int]:
        """tex[i]=='[' → 匹配 ']'. 允许内嵌 {..} 组与注释."""
        if i >= len(tex) or tex[i] != "[":
            return None
        j, n = i + 1, len(tex)
        while j < n:
            c = tex[j]
            if c == "\\":
                j += 2
                continue
            if c == "{":
                e = self._match_brace(tex, j)
                j = e if e else j + 1
                continue
            if c == "[":
                e = self._match_bracket(tex, j)
                j = e if e else j + 1
                continue
            if c == "%":
                k = tex.find("\n", j)
                j = n if k < 0 else k + 1
                continue
            if c == "]":
                return j + 1
            j += 1
        return None

    def _args(
        self, tex: str, i: int, nargs: int, has_opt: bool = False
    ) -> Tuple[List[Tuple[int, int, int, int]], int]:
        """从 i 起读 [opt]?{a1}..{an}.
        返回 ([(cs,ce,fs,fe)], end) — cs:ce 内容区间, fs:fe 含括号整段."""
        pos = self._ws(tex, i)
        out: List[Tuple[int, int, int, int]] = []
        if has_opt and pos < len(tex) and tex[pos] == "[":
            e = self._match_bracket(tex, pos)
            if e:
                out.append((pos + 1, e - 1, pos, e))
                pos = self._ws(tex, e)
        for _ in range(nargs):
            if pos < len(tex) and tex[pos] == "[":
                e = self._match_bracket(tex, pos)
                if e is None:
                    break
                out.append((pos + 1, e - 1, pos, e))
                pos = self._ws(tex, e)
            elif pos < len(tex) and tex[pos] == "{":
                e = self._match_brace(tex, pos)
                if e is None:
                    break
                out.append((pos + 1, e - 1, pos, e))
                pos = self._ws(tex, e)
            elif pos < len(tex) and tex[pos] not in " \t\n":
                out.append((pos, pos + 1, pos, pos + 1))  # 单 token 参数
                pos += 1
            else:
                break
        return out, pos

    def _env_name_at(self, tex: str, i: int) -> Tuple[Optional[str], int]:
        pos = self._ws(tex, i)
        if pos < len(tex) and tex[pos] == "{":
            e = self._match_brace(tex, pos)
            if e:
                return tex[pos + 1 : e - 1].strip(), e
        return None, i

    def _find_env_end(self, tex: str, i: int, env: str) -> Optional[int]:
        """找 env 的匹配 \\end (含宏端点 \\ee). 注释安全. 返回 end 后一位."""
        depth, n = 1, len(tex)
        while i < n:
            c = tex[i]
            if c == "%":
                k = tex.find("\n", i)
                i = n if k < 0 else k + 1
                continue
            if c == "\\":
                name, j = self._read_cmd_name(tex, i)
                if name == "begin":
                    sub, e2 = self._env_name_at(tex, j)
                    if sub == env:
                        depth += 1
                    i = e2 if e2 else j
                    continue
                if name == "end":
                    sub, e2 = self._env_name_at(tex, j)
                    if sub == env:
                        depth -= 1
                        if depth == 0:
                            return e2
                    i = e2 if e2 else j
                    continue
                m = self.macros.get(name)
                if m and m.kind == "env_begin" and m.target_env == env:
                    depth += 1
                elif m and m.kind == "env_end" and m.target_env == env:
                    depth -= 1
                    if depth == 0:
                        return j
                i = j
                continue
            i += 1
        return None

    @staticmethod
    def _read_cmd_name(tex: str, i: int) -> Tuple[str, int]:
        """tex[i]=='\\' → (名字, 命令后一位). 字母串或非字母单字符."""
        j = i + 1
        n = len(tex)
        if j < n and tex[j].isalpha():
            k = j
            while k < n and (tex[k].isalpha() or tex[k] == "@"):
                k += 1
            return tex[j:k], k
        if j < n:
            return tex[j], j + 1
        return "", j

    # ------------------------------------------------------------ 宏表
    def _register_macro(self, name: str, nargs: int, has_opt: bool, body: str) -> None:
        if not name:
            return
        m = Macro(name=name, nargs=nargs, has_opt=has_opt, body=body)
        stripped = body.strip()
        b = re.fullmatch(r"\\begin\{([^}]*)\}", stripped)
        e = re.fullmatch(r"\\end\{([^}]*)\}", stripped)
        if b:
            m.kind, m.target_env = "env_begin", b.group(1).strip()
        elif e:
            m.kind, m.target_env = "env_end", e.group(1).strip()
        elif not self._body_has_text(body):
            m.kind = "opaque"
        else:
            m.kind = "transparent"
            m.protect_args = self._protected_param_positions(body, nargs)
        self.macros[name] = m

    @staticmethod
    def _body_has_text(body: str) -> bool:
        """宏体是否含自然文本 (去命令/参数记号后 ≥2 连续字母)."""
        s = re.sub(r"#[1-9]?", " ", body)
        s = re.sub(r"\\[a-zA-Z@]+\*?", " ", s)
        s = re.sub(r"\\[^a-zA-Z]", " ", s)
        s = re.sub(r"[^a-zA-Z]", " ", s)
        return bool(re.search(r"[a-zA-Z]{2,}", s))

    @staticmethod
    def _protected_param_positions(body: str, nargs: int) -> Tuple[bool, ...]:
        """#i 落在 \\ref/\\cite/\\label/\\url 等命令参数位 → 该参数保护."""
        flags = [False] * nargs
        if nargs == 0:
            return ()
        cur_protect = False
        for m in re.finditer(r"\\[a-zA-Z@]+\*?|#([1-9])", body):
            tok = m.group(0)
            if tok.startswith("#"):
                flags[int(tok[1]) - 1] = flags[int(tok[1]) - 1] or cur_protect
            else:
                name = tok.lstrip("\\").rstrip("*")
                cur_protect = name in (
                    CITE_NAMES | REF_NAMES | {"label", "url", "includegraphics"}
                )
        return tuple(flags)

    def _scan_macro_def(self, tex: str, i: int, name: str) -> int:
        r"""定义命令 → 登记宏表, 返回整段后一位. 全部逐字保留."""
        pos = i + 1 + len(name)
        n = len(tex)
        if name == "newenvironment":
            p = self._ws(tex, pos)
            envname, p = self._env_name_at(tex, p)
            if envname:
                p = self._ws(tex, p)
                nargs = 0
                if p < n and tex[p] == "[":
                    e2 = self._match_bracket(tex, p)
                    if e2:
                        try:
                            nargs = int(tex[p + 1 : e2 - 1].strip() or 0)
                        except ValueError:
                            nargs = 0
                        p = e2
                bb = self._ws(tex, p)
                eb = self._match_brace(tex, bb)
                if eb:
                    body_b = tex[bb + 1 : eb - 1]
                    ee = self._match_brace(tex, self._ws(tex, eb))
                    kind = (
                        "protect_env"
                        if self._env_kind_of(body_b) == "protected"
                        else "custom_env"
                    )
                    self.macros["env:" + envname] = Macro(
                        name=envname, nargs=nargs, kind=kind
                    )
                    return ee if ee else eb
            return pos
        if name in ("newcommand", "renewcommand", "providecommand"):
            pos = self._ws(tex, pos)
            if pos < n and tex[pos] == "*":
                pos += 1
            pos = self._ws(tex, pos)
            mname: Optional[str] = None
            if pos < n and tex[pos] == "{":
                e2 = self._match_brace(tex, pos)
                if e2:
                    mname = tex[pos + 1 : e2 - 1].strip().lstrip("\\")
                    pos = e2
            elif pos < n and tex[pos] == "\\":
                mname, pos = self._read_cmd_name(tex, pos)
            if mname is None:
                return pos
            nargs, has_opt = 0, False
            for k in range(2):
                p2 = self._ws(tex, pos)
                if p2 < n and tex[p2] == "[":
                    e2 = self._match_bracket(tex, p2)
                    if e2 is None:
                        break
                    if k == 0:
                        try:
                            nargs = int(tex[p2 + 1 : e2 - 1].strip() or 0)
                        except ValueError:
                            nargs = 0
                    else:
                        has_opt = True
                    pos = e2
                else:
                    break
            p2 = self._ws(tex, pos)
            if p2 < n and tex[p2] == "{":
                e2 = self._match_brace(tex, p2)
                if e2:
                    self._register_macro(mname, nargs, has_opt, tex[p2 + 1 : e2 - 1])
                    return e2
            return pos
        if name == "def":
            pos = self._ws(tex, pos)
            mname = None
            if pos < n and tex[pos] == "\\":
                mname, pos = self._read_cmd_name(tex, pos)
            elif pos < n and tex[pos] == "{":
                e2 = self._match_brace(tex, pos)
                if e2:
                    mname = tex[pos + 1 : e2 - 1].strip().lstrip("\\")
                    pos = e2
            if mname is None:
                return pos
            nargs = 0
            while pos < n:
                if tex[pos] == "#" and pos + 1 < n and tex[pos + 1].isdigit():
                    nargs += 1
                    pos += 2
                elif tex[pos] in " \t":
                    pos += 1
                else:
                    break
            pos = self._ws(tex, pos)
            if pos < n and tex[pos] == "{":
                e2 = self._match_brace(tex, pos)
                if e2:
                    self._register_macro(mname, nargs, False, tex[pos + 1 : e2 - 1])
                    return e2
            return pos
        if name in (
            "NewDocumentCommand",
            "RenewDocumentCommand",
            "ProvideDocumentCommand",
            "DeclareDocumentCommand",
        ):
            pos = self._ws(tex, pos)
            mname = None
            if pos < n and tex[pos] == "{":
                e2 = self._match_brace(tex, pos)
                if e2:
                    mname = tex[pos + 1 : e2 - 1].strip().lstrip("\\")
                    pos = e2
            elif pos < n and tex[pos] == "\\":
                mname, pos = self._read_cmd_name(tex, pos)
            if mname is None:
                return pos
            pos = self._ws(tex, pos)
            nargs, has_opt = 0, False
            if pos < n and tex[pos] == "{":
                e2 = self._match_brace(tex, pos)
                if e2:
                    for ch in tex[pos + 1 : e2 - 1]:
                        if ch == "m":
                            nargs += 1
                        elif ch in "oO":
                            has_opt = True
                    pos = e2
            pos = self._ws(tex, pos)
            if pos < n and tex[pos] == "{":
                e2 = self._match_brace(tex, pos)
                if e2:
                    self._register_macro(mname, nargs, has_opt, tex[pos + 1 : e2 - 1])
                    return e2
            return pos
        return pos

    @staticmethod
    def _env_kind_of(body: str) -> str:
        return "protected" if "caption" in body or "figure" in body else "x"

    def _register_macros_in(self, tex: str) -> None:
        """preamble 区间: 只找定义命令登记宏表, 不产出 pieces."""
        i, n = 0, len(tex)
        while i < n:
            c = tex[i]
            if c == "%":
                k = tex.find("\n", i)
                i = n if k < 0 else k + 1
                continue
            if c == "\\":
                name, j = self._read_cmd_name(tex, i)
                if name in (
                    "newcommand",
                    "renewcommand",
                    "providecommand",
                    "def",
                    "NewDocumentCommand",
                    "RenewDocumentCommand",
                    "DeclareDocumentCommand",
                    "newenvironment",
                ):
                    end = self._scan_macro_def(tex, i, name)
                    i = max(end, j)
                    continue
                i = j
                continue
            i += 1

    # ------------------------------------------------------------ 主扫描
    def scan(
        self, tex: str, preamble_end: int = 0, mined_only: bool = False
    ) -> ScanResult:
        """扫 tex → pieces. preamble_end: \\begin{document} 的后一位 (0=无)."""
        self._mined_only = mined_only
        n = len(tex)
        if preamble_end:
            pre = tex[:preamble_end]
            self._emit(pre)
            self._register_macros_in(pre)
            i = preamble_end
        else:
            i = 0
        run: List[str] = []

        def flush_run() -> None:
            s = "".join(run)
            run.clear()
            if not s.strip():
                self._emit(s)
                return
            if self._mined_only:
                self._emit(s)
                return
            lead = re.match(r"\s*", s).group(0)
            trail = re.search(r"\s*$", s).group(0)
            core = s[len(lead) : len(s) - len(trail) if trail else len(s)]
            clean = re.sub(r"\[\[[A-Z_]+_\d+\]\]", " ", core)
            clean = re.sub(r"\\[a-zA-Z@]+\*?|\\[^a-zA-Z]", " ", clean)
            clean = re.sub(r"[^a-zA-Z]", " ", clean).strip()
            force = self._force_chunk
            self._force_chunk = False
            if len(clean) < CHUNK_MIN and not (force and clean):
                self._emit(s)
                return
            # 首尾空白作字面保留 → chunk 为纯文本核, identity 无损
            self._emit(lead)
            self.pieces.append(("chunkph", self._chunk(core, "paragraph")))
            self._emit(trail)

        while i < n:
            c = tex[i]

            # ---- 注释: % 到行尾逐字保留 (% 已被 \\% 单字符命令先行吃掉)
            if c == "%":
                flush_run()
                k = tex.find("\n", i)
                self._emit(tex[i : n if k < 0 else k])
                i = n if k < 0 else k
                continue

            # ---- 命令
            if c == "\\":
                name, j = self._read_cmd_name(tex, i)
                i = self._dispatch_cmd(tex, i, name, j, run, flush_run)
                continue

            # ---- 数学 $..$ $$..$$
            if c == "$":
                if tex.startswith("$$", i):
                    e = tex.find("$$", i + 2)
                    if e >= 0 and "\n\n" not in tex[i:e]:
                        run.append(self._ph("MATH", tex[i : e + 2]))
                        i = e + 2
                        continue
                    run.append("$")
                    i += 1
                    continue
                j = i + 1
                ok = False
                while j < n:
                    if tex[j] == "\\":
                        j += 2
                        continue
                    if tex[j] == "$":
                        ok = True
                        break
                    if tex[j] == "\n" and j + 1 < n and tex[j + 1] == "\n":
                        break
                    j += 1
                if ok and "\n\n" not in tex[i : j + 1]:
                    run.append(self._ph("MATH", tex[i : j + 1]))
                    i = j + 1
                else:
                    run.append("$")
                    i += 1
                continue

            # ---- 空行分段: \n 后跳过空白仍是 \n → 段落边界
            if c == "\n":
                k = i + 1
                while k < n and tex[k] in " \t":
                    k += 1
                if k < n and tex[k] == "\n":
                    run.append(tex[i:k])
                    flush_run()
                    i = k
                    continue
                run.append(c)
                i += 1
                continue

            # ---- 普通字符 (含 { } ~ 等, 逐字入 run)
            run.append(c)
            i += 1

        flush_run()
        return ScanResult(
            protected_tex=self._render(),
            chunks=self.chunks,
            ph_map=self.ph_map,
            macros=self.macros,
            pieces=self.pieces,
            inputs=self.inputs,
        )

    def _render(self) -> str:
        return "".join(v for _, v in self.pieces)

    # ------------------------------------------------------------ 命令分派
    def _dispatch_cmd(
        self, tex: str, i: int, name: str, j: int, run: list, flush_run
    ) -> int:
        n = len(tex)

        # \verb|..| / \verb*X..X
        if name == "verb":
            k = j
            if k < n and tex[k] == "*":
                k += 1
            if k < n:
                d = tex[k]
                e = tex.find(d, k + 1)
                if e > 0:
                    run.append(self._ph("VERB", tex[i : e + 1]))
                    return e + 1
            run.append(tex[i:j])
            return j

        # 定义命令: 逐字保留, 登记宏表
        if name in (
            "newcommand",
            "renewcommand",
            "providecommand",
            "def",
            "NewDocumentCommand",
            "RenewDocumentCommand",
            "DeclareDocumentCommand",
            "newenvironment",
        ):
            flush_run()
            end = self._scan_macro_def(tex, i, name)
            self._emit(tex[i:end])
            return end
        if name == "newif":
            flush_run()
            p = self._ws(tex, j)
            cond, e2 = self._read_cmd_name(tex, p)
            if cond.startswith("if"):
                base = cond[2:]
                self.macros.setdefault(
                    base + "true", Macro(base + "true", kind="literal")
                )
                self.macros.setdefault(
                    base + "false", Macro(base + "false", kind="literal")
                )
            self._emit(tex[i : e2 if e2 else j])
            return e2 if e2 else j

        # \begin{env}
        if name == "begin":
            env, e2 = self._env_name_at(tex, j)
            if env is None:
                run.append(tex[i:j])
                return j
            return self._handle_env(tex, i, env, e2, run, flush_run)

        # \end{env}
        if name == "end":
            env, e2 = self._env_name_at(tex, j)
            flush_run()
            if env == "document" and e2:
                self._emit(tex[i:e2])  # \end{document} 本体
                self._emit(tex[e2:])  # 之后全逐字
                return n
            self._emit(tex[i : e2 if e2 else j])
            return e2 if e2 else j

        # 保护命令族 (整调用 → [[TYPE_n]])
        if name in CITE_NAMES or name.startswith("cite"):
            return self._protect_call(tex, i, j, "CITE", run)
        if name in REF_NAMES or (
            name.endswith("ref") and name not in TRANSPARENT_NAMES and name != "href"
        ):
            return self._protect_call(tex, i, j, "REF", run)
        if name in PROTECT_NAMES:
            typ = {
                "includegraphics": "GRAPHICS",
                "url": "URL",
                "path": "URL",
                "label": "LABEL",
                "bibliography": "BIB",
                "bibliographystyle": "BIB",
                "bibitem": "BIB",
            }.get(name, "CMD")
            vb = name in ("url", "path")
            return self._protect_call(tex, i, j, typ, run, verbatim=vb)

        # \href{url}{text}: url→[[HREF]], text 继续扫
        if name == "href":
            pos = self._ws(tex, j)
            if pos < n and tex[pos] == "{":
                e = self._match_brace(tex, pos, verbatim=True)
                if e:
                    run.append(tex[i:pos] + self._ph("HREF", tex[pos:e]))
                    return e
            run.append(tex[i:j])
            return j

        # \input/\include: 记录引用点 (展开由 flatten_inputs 处理)
        if name in ("input", "include"):
            pos = self._ws(tex, j)
            if pos < n and tex[pos] == "{":
                e = self._match_brace(tex, pos)
                if e:
                    self.inputs.append((i, tex[pos + 1 : e - 1].strip()))
                    flush_run()
                    self._emit(tex[i:e])
                    return e
            run.append(tex[i:j])
            return j

        # chunk 参数命令
        if name in CHUNK_ARG_NAMES:
            return self._handle_chunk_arg(tex, i, j, name, run, flush_run)

        # 整块保护 (\author{..} 等)
        if name in PROTECT_BLOCK_NAMES:
            flush_run()
            pos = self._ws(tex, j)
            if pos < n and tex[pos] == "[":
                e2 = self._match_bracket(tex, pos)
                if e2:
                    pos = self._ws(tex, e2)
            if pos < n and tex[pos] == "{":
                e = self._match_brace(tex, pos)
                if e:
                    self._emit(self._ph("AUTHOR", tex[i:e]))
                    return e
            self._emit(self._ph("AUTHOR", tex[i:j]))
            return j

        # 透明命令: 参数内联扫描
        if name in TRANSPARENT_NAMES:
            run.append(tex[i:j])
            return j

        # 边界命令 (文本 run 硬边界, 逐字 piece)
        if name in BOUNDARY_NAMES:
            flush_run()
            self._emit(tex[i:j])
            if name == "item":
                self._force_chunk = True  # item 文本恒可译
            return j

        # 条件命令 / \newif 注册的字面宏
        if COND_RX.match(name):
            flush_run()
            self._emit(tex[i:j])
            return j
        m0 = self.macros.get(name)
        if m0 is not None and m0.kind == "literal":
            flush_run()
            self._emit(tex[i:j])
            return j

        # 数学定界 \[ \( \) \]
        if name == "[":
            e = tex.find("\\]", j)
            if e > 0 and "\n\n" not in tex[i:e]:
                run.append(self._ph("MATH", tex[i : e + 2]))
                return e + 2
            run.append(tex[i:j])
            return j
        if name == "(":
            e = tex.find("\\)", j)
            if e > 0 and "\n\n" not in tex[i:e]:
                run.append(self._ph("MATH", tex[i : e + 2]))
                return e + 2
            run.append(tex[i:j])
            return j
        if name in ("]", ")"):
            run.append(tex[i:j])
            return j

        # 行内字面 (重音/符号/品牌/旧式字体开关/单字符命令)
        if (
            name in INLINE_LITERAL_CMDS
            or name in FONT_SWITCHES
            or (len(name) == 1 and (name in ACCENT_CHARS or not name.isalpha()))
        ):
            run.append(tex[i:j])
            return j

        # 宏表命中
        m = self.macros.get(name)
        if m is not None:
            return self._handle_macro(tex, i, j, name, m, run, flush_run)

        # 未知命令: 带 {..}/[..] 参数则整体保护 (保守: 防 key 泄漏)
        pos = self._ws(tex, j)
        if pos < n and tex[pos] in "{[":
            args, end = self._args(tex, j, 6, True)
            if args:
                run.append(self._ph("CMD", tex[i:end]))
                return end
        run.append(tex[i:j])
        return j

    def _protect_call(
        self, tex: str, i: int, j: int, typ: str, run: list, verbatim: bool = False
    ) -> int:
        """命令 + *? + [opt]* + {args}* 整段 → [[typ_n]]. 返回 end."""
        n = len(tex)
        pos = j
        if pos < n and tex[pos] == "*":
            pos += 1
        for _ in range(3):
            p2 = self._ws(tex, pos)
            if p2 < n and tex[p2] == "[":
                e = self._match_bracket(tex, p2)
                if e:
                    pos = e
                    continue
            break
        end = pos
        for _ in range(3):
            p2 = self._ws(tex, end)
            if p2 < n and tex[p2] == "{":
                e = self._match_brace(tex, p2, verbatim=verbatim)
                if e is None:
                    break
                end = e
            else:
                break
        run.append(self._ph(typ, tex[i:end]))
        return end

    def _handle_chunk_arg(
        self, tex: str, i: int, j: int, name: str, run: list, flush_run
    ) -> int:
        """\\section[opt]{arg}: 前缀逐字, arg → 独立 chunk (内联递归保护)."""
        n = len(tex)
        pos = self._ws(tex, j)
        if pos < n and tex[pos] == "*":
            pos += 1
        pos = self._ws(tex, pos)
        if pos < n and tex[pos] == "[":
            e2 = self._match_bracket(tex, pos)
            if e2:
                pos = self._ws(tex, e2)
        if pos < n and tex[pos] == "{":
            e = self._match_brace(tex, pos)
            if e:
                inner = tex[pos + 1 : e - 1]
                if not inner.strip():
                    run.append(tex[i:e])
                    return e
                sub = self._spawn()
                sub._arg_inline = True
                r = sub.scan(inner, preamble_end=0, mined_only=True)
                rendered = r.protected_tex
                if self._arg_inline:
                    # 嵌套 chunk-arg 内联化: 文本并入父 chunk
                    run.append(tex[i : pos + 1] + rendered + "}")
                else:
                    flush_run()
                    self._emit(tex[i : pos + 1])
                    self.pieces.append(("chunkph", self._chunk(rendered, name)))
                    self._emit("}")
                return e
        run.append(tex[i:j])
        return j

    def _handle_macro(
        self, tex: str, i: int, j: int, name: str, m: Macro, run: list, flush_run
    ) -> int:
        if m.kind == "env_begin":
            env = m.target_env
            end = self._find_env_end(tex, j, env)
            if end is None:
                run.append(tex[i:j])
                return j
            if env in MATH_ENVS:
                run.append(self._ph("MATH", tex[i:end]))
            elif env in VERBATIM_ENVS:
                flush_run()
                self._emit(self._ph("VERB", tex[i:end]))
            elif env in PROTECTED_ENVS:
                flush_run()
                self._emit(self._env_with_mined(tex, i, j, env, end))
            else:
                run.append(self._ph("ENV", tex[i:end]))
            return end
        if m.kind == "env_end":
            run.append(tex[i:j])
            return j
        if m.kind == "opaque":
            args, end = self._args(tex, j, m.nargs, m.has_opt)
            run.append(self._ph("MACRO", tex[i:end]))
            return end
        # transparent: 保护位参数→[[KEY]], 文本位参数→内联扫描
        args, end = self._args(tex, j, m.nargs, m.has_opt)
        if not args:
            run.append(tex[i:end])
            return end
        run.append(tex[i:j])
        prev = j
        for k, (cs, ce, fs, fe) in enumerate(args):
            run.append(tex[prev:fs])  # 参数间空白逐字
            run.append(tex[fs:cs])  # 开括号 (单 token 参数为 '')
            if k < len(m.protect_args) and m.protect_args[k]:
                run.append(self._ph("KEY", tex[cs:ce]))
            else:
                sub = self._spawn()
                r = sub.scan(tex[cs:ce], preamble_end=0, mined_only=True)
                run.append(r.protected_tex)
            run.append(tex[ce:fe])  # 闭括号
            prev = fe
        run.append(tex[prev:end])
        return end

    def _handle_env(
        self, tex: str, i: int, env: str, j: int, run: list, flush_run
    ) -> int:
        """\\begin{env} 已读到 j (env 名 } 后)."""
        n = len(tex)
        if env in VERBATIM_ENVS:
            flush_run()
            pat = "\\end{" + env + "}"
            k = tex.find(pat, j)
            if k < 0:
                run.append(tex[i:j])
                return j
            self._emit(self._ph("VERB", tex[i : k + len(pat)]))
            return k + len(pat)
        if env in MATH_ENVS:
            end = self._find_env_end(tex, j, env)
            if end is None:
                run.append(tex[i:j])
                return j
            run.append(self._ph("MATH", tex[i:end]))
            return end
        if env in PROTECTED_ENVS:
            end = self._find_env_end(tex, j, env)
            if end is None:
                run.append(tex[i:j])
                return j
            flush_run()
            self._emit(self._env_with_mined(tex, i, j, env, end))
            return end
        # 其余 env (theorem/itemize/abstract/minipage/unknown): 透明,
        # 但 \begin 行本身是结构 → 字面 piece, 不进 chunk
        flush_run()
        pos = self._ws(tex, j)
        if pos < n and tex[pos] == "[":
            e2 = self._match_bracket(tex, pos)
            if e2:
                pos = self._ws(tex, e2)
        if env in ENV_MANDATORY_ARG and pos < n and tex[pos] == "{":
            e2 = self._match_brace(tex, pos)
            if e2:
                pos = self._ws(tex, e2)
        self._emit(tex[i:pos])
        return pos

    def _env_with_mined(self, tex: str, i: int, j: int, env: str, end: int) -> str:
        """保护环境 → [[ENV_n]]; 内部 mined_only 扫描挖 caption/footnote."""
        tag = "\\end{" + env + "}"
        inner_end = end - len(tag) if tex.startswith(tag, end - len(tag)) else end
        inner = tex[j:inner_end]
        sub = self._spawn()
        r = sub.scan(inner, preamble_end=0, mined_only=True)
        body = tex[i:j] + r.protected_tex + tex[inner_end:end]
        return self._ph("ENV", body)

    def _spawn(self) -> "Scanner":
        """子扫描器: 共享宏表/chunks/ph_map/计数器 (递归保护→占位符连续编号)."""
        sub = Scanner(self.macros)
        sub._ctr = self._ctr
        sub.chunks = self.chunks
        sub.ph_map = self.ph_map
        return sub


# ---------------------------------------------------------------- 顶层 API

_PREAMBLE_RX = re.compile(r"\\(documentclass|documentstyle)(?![a-zA-Z])")


def parse_tex(tex: str) -> ScanResult:
    """主入口: 单文件文本 → ScanResult."""
    sc = Scanner()
    mdoc = re.search(r"\\begin\{document\}", tex)
    mpream = _PREAMBLE_RX.search(tex)
    preamble_end = mdoc.end() if (mpream and mdoc) else 0
    return sc.scan(tex, preamble_end=preamble_end)


def reconstruct(
    res: ScanResult, translations: Optional[Dict[int, str]] = None, max_iter: int = 20
) -> str:
    """译文 splice: pieces 渲染 → 占位符统一不动点展开.

    chunk 占位符 ([[CHUNK_n]]) 可出现在任意位置: 顶层 piece、字面 run
    (\\caption{[[CHUNK_3]]})、[[ENV]] 体、乃至另一 chunk 内 —— 全部纳入
    同一张替换表迭代至不动点, 嵌套深度不限 (修 ieeA 死 token bug)."""
    s = res.protected_tex
    trans_map = {}
    for c in res.chunks:
        t = translations.get(c.id) if translations else None
        trans_map[_cname(f"CHUNK_{c.id}")] = t if t is not None else c.content
    all_map = dict(res.ph_map)
    all_map.update(trans_map)
    for _ in range(max_iter):
        changed = False
        for ph, orig in all_map.items():
            if ph in s:
                s = s.replace(ph, orig)
                changed = True
        if not changed:
            break
    return s


def flatten_inputs(
    tex: str,
    file_dir: str,
    root_dir: Optional[str] = None,
    depth: int = 0,
    _seen: Optional[set] = None,
) -> str:
    r"""展开 \input/\include: 先相对当前文件目录, 再相对主文件目录
    (LaTeX/TEXINPUTS 语义 — 修 ieeA 只按被包含文件目录解析的 bug).
    注释掉的 \input 不展开 (逐字符扫, % 行不判命令)."""
    if root_dir is None:
        root_dir = file_dir
    if depth > 8:
        return tex
    if _seen is None:
        _seen = set()
    out = []
    i, n = 0, len(tex)
    sc = Scanner()
    verb_env: Optional[str] = None  # verbatim 类环境内不展开
    while i < n:
        c = tex[i]
        if verb_env is not None:
            pat = "\\end{" + verb_env + "}"
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
        if c == "\\":
            name, j = sc._read_cmd_name(tex, i)
            if name == "begin":
                env, e2 = sc._env_name_at(tex, j)
                if env in VERBATIM_ENVS:
                    verb_env = env
                out.append(tex[i : e2 if e2 else j])
                i = e2 if e2 else j
                continue
            if name == "verb":
                k = j + (1 if j < n and tex[j] == "*" else 0)
                if k < n:
                    e = tex.find(tex[k], k + 1)
                    if e > 0:
                        out.append(tex[i : e + 1])
                        i = e + 1
                        continue
            if name in ("input", "include"):
                pos = sc._ws(tex, j)
                if pos < n and tex[pos] == "{":
                    e = sc._match_brace(tex, pos)
                    if e:
                        fname = tex[pos + 1 : e - 1].strip()
                        cand = (
                            [fname]
                            if fname.endswith(".tex")
                            else [fname, fname + ".tex"]
                        )
                        hit = None
                        for cdir in (file_dir, root_dir):
                            for cf in cand:
                                p = os.path.join(cdir, cf)
                                if os.path.exists(p):
                                    hit = p
                                    break
                            if hit:
                                break
                        if hit is None:
                            for cdir in (file_dir, root_dir):
                                p = os.path.join(cdir, os.path.basename(fname) + ".tex")
                                if os.path.exists(p):
                                    hit = p
                                    break
                        if hit and os.path.abspath(hit) not in _seen:
                            _seen.add(os.path.abspath(hit))
                            with open(hit, encoding="utf-8", errors="replace") as f:
                                sub = f.read()
                            out.append(
                                flatten_inputs(
                                    sub,
                                    os.path.dirname(hit),
                                    root_dir,
                                    depth + 1,
                                    _seen,
                                )
                            )
                            i = e
                            continue
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_file(path: str, flatten: bool = True) -> ScanResult:
    with open(path, encoding="utf-8", errors="replace") as f:
        tex = f.read()
    if flatten:
        d = os.path.dirname(os.path.abspath(path))
        tex = flatten_inputs(tex, d, d)
    return parse_tex(tex)
