r"""_builtins_csfix — undefined_cs/already_def 按 cs 名打靶修复原语 (C3 拆分)。

``cs_targeted_fix``: cs→修复表 (strip_pkg/usepackage/cs_map/polyfill 组合序,
``engines.{eng}`` 子表覆盖) + glue-残骸前缀拆分兜底; ``undefine_for_redef``:
already_def ``\\let\\X\\@undefined`` 让位注入 (寄存器/盒型分配名护栏)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    _AT_LETTER_POST,
    _AT_LETTER_PRE,
    PDFTEX_PRIMS,
    _drop_pkg_loads,
    _fixloop_log,
    _inject_after_docclass,
    _let_cs,
    _map_tex_files,
    _undefine_cs,
)
from texlate.compile.inject import find_docclass_ends
from texlate.textutil import DOCCLASS_RX, iter_depth0, mask_tex

if TYPE_CHECKING:
    from collections.abc import Iterable

    from texlate.compile.fixloop.engine import Engine, LoopCtx


#: biblatex bbl-2.8 ``\sortlist`` 读者 polyfill —— svjour cls shim bbl arm
#: (90-shim-legacy.yaml svjour_body) 的 cs_table 泛化移植, 零裸 ``@`` 化。
#: ``backend=bibtex`` 稿的 bundled .bbl 是 2.8/2.9 格式, TL biblatex 3.21
#: 不再定义 ``\sortlist`` → ``.bbl:19`` 起 ``undefined_cs`` (1907.03923/
#: 1706.00220/1706.00324/1706.02744/1803.03145 ×5)。defer 必需: preamble
#: ``\providecommand`` 会抢占 biblatex 装载期 ``\newcommand`` 名
#: (bibinitdelim/bibnamedelim*/bibrangedash/revsdnamepunct already_def
#: 级联, 1706.00221 实证)。但普通 ``\AtBeginDocument`` (= begindocument
#: 钩 top-level 标) 不可用: lthooks 把 top-level 块排在钩尾, biblatex
#: 的 biblatex-标块先跑 ``\blx@bblinput`` 读 .bbl → 读者仍未定义
#: (本机 live 实证, top-level 块在 "Trying to load bibliographic data"
#: 之后才执行)。``begindocument/before`` 钩先于一切 begindocument 块,
#: 又在整段 preamble 之后 → biblatex 已就位 provide 自动 no-op, 未装时
#: polyfill 兜底, 正文 ``\input``/``\printbibliography`` 两种读法通吃。
#: doc 面 ``@``=12 → ``define@key``/``endsortlist``/``current@color`` 全走
#: ``\csname``/``\ifcsname`` 形, 内部名纯字母 ``tlsv*``。
#: ``\list``/``\verb`` 是内核基底宏 —— 只在 ``\sortlist`` ``\begingroup``
#: 组内重定义, 不外泄。``\verb{fld}`` + ``\verb 内容\endverb`` 是
#: bbl-2.8 verbatim 域对 (eprint/url/file): ``\futurelet`` 分流 ——
#: 带花参形吞域名, 裸形吞到 ``\endverb`` 止 (域内容 verbatim-catcode
#: 敏感, gobble 保编译不渲染)。``\keyw`` 同理须组内 gobble: biblatex
#: ``\blx@bblstart`` 绑的 ``\keyw`` 展开 ``\abx@field@entrykey``, 该内部
#: 名只在真 ``\entry`` 处理器下设 (live 实证 undefined_cs 级联)。
#: ``\true``/``\false`` 同族但 gobble 不适用: ``\blx@bblstart`` 把它们
#: ``\let`` 到 ``\blx@bbl@booltrue/false`` (biblatex.sty:9018-19),
#: 其 ``\csgappto`` 写经 ``\blx@bbl@data`` —— 该 csname 指针宏由真
#: ``\blx@bbl@entry`` 在自己组内 ``\edef`` (:8687), 我们的 gobble
#: ``\entry`` 不设 → 组内补一个 scratch 指针 + 预建空目标宏,
#: ``\csgappto`` 写入即被吸收, 对一切写经此指针的 handler 通吃
#: (1706.02744 ``\true{moreauthor}`` 实证)。
#: ``\ifx\csname`` 须 ``\expandafter`` 先展开 ``\csname`` —— ``\ifx``
#: 不展开操作数, 裸写恒假 (守卫死码)。
_SORTLIST_BBL_POLYFILL = r"""
\AddToHook{begindocument/before}{%
\providecommand{\bibinitperiod}{.}%
\providecommand{\bibinitdelim}{}%
\providecommand{\bibnamedelima}{ }%
\providecommand{\bibnamedelimb}{ }%
\providecommand{\bibnamedelimd}{ }%
\providecommand{\bibrangedash}{--}%
\providecommand{\revsdnamepunct}{,}%
\expandafter\ifx\csname default@color\endcsname\relax
  \expandafter\gdef\csname default@color\endcsname{gray 0}\fi
\expandafter\ifx\csname current@color\endcsname\relax
  \expandafter\gdef\csname current@color\endcsname{gray 0}\fi
\def\tlsvempty{}%
\def\tlsvfldtitle{title}\def\tlsvfldbooktitle{booktitle}%
\def\tlsvfldjtitle{journaltitle}\def\tlsvfldyear{year}%
\def\tlsvfldvol{volume}\def\tlsvfldnum{number}%
\def\tlsvfldpages{pages}\def\tlsvfldnote{note}%
\def\tlsvfldseries{series}\def\tlsvfldschool{school}%
\def\tlsvfldinst{institution}\def\tlsvfldorg{organization}%
\def\tlsvfldemit#1#2{\def\tlsvfk{#1}%
  \ifx\tlsvfk\tlsvfldtitle\textit{#2} \fi
  \ifx\tlsvfk\tlsvfldbooktitle\textit{#2} \fi
  \ifx\tlsvfk\tlsvfldjtitle#2 \fi
  \ifx\tlsvfk\tlsvfldyear#2 \fi
  \ifx\tlsvfk\tlsvfldvol#2 \fi
  \ifx\tlsvfk\tlsvfldnum#2 \fi
  \ifx\tlsvfk\tlsvfldpages#2 \fi
  \ifx\tlsvfk\tlsvfldnote#2 \fi
  \ifx\tlsvfk\tlsvfldseries#2 \fi
  \ifx\tlsvfk\tlsvfldschool#2 \fi
  \ifx\tlsvfk\tlsvfldinst#2 \fi
  \ifx\tlsvfk\tlsvfldorg#2 \fi}%
\ifcsname define@key\endcsname
  \csname define@key\endcsname{tlfn}{family}{\def\tlsvfam{#1}}%
  \csname define@key\endcsname{tlfn}{given}{\def\tlsvgiv{#1}}%
  \csname define@key\endcsname{tlfn}{prefix}{\def\tlsvpre{#1}}%
  \csname define@key\endcsname{tlfn}{suffix}{\def\tlsvsuf{#1}}%
  \csname define@key\endcsname{tlfn}{familyi}{}%
  \csname define@key\endcsname{tlfn}{giveni}{}%
  \csname define@key\endcsname{tlfn}{prefixi}{}%
  \csname define@key\endcsname{tlfn}{suffixi}{}%
  \csname define@key\endcsname{tlfn}{hash}{}%
  \csname define@key\endcsname{tlfn}{useprefix}{}%
  \csname define@key\endcsname{tlfn}{usehash}{}%
  \csname define@key\endcsname{tlfn}{gender}{}%
\fi
\def\tlsvnil{\tlsvnil}%
\def\tlsvnelt#1#2{\let\tlsvfam\tlsvempty\let\tlsvgiv\tlsvempty
  \let\tlsvpre\tlsvempty\let\tlsvsuf\tlsvempty
  \ifcsname setkeys\endcsname\setkeys{tlfn}{#2}\fi
  \ifx\tlsvpre\tlsvempty\else\tlsvpre~\fi
  \ifx\tlsvgiv\tlsvempty\else\tlsvgiv~\fi
  \ifx\tlsvfam\tlsvempty\else\tlsvfam\fi
  \ifx\tlsvsuf\tlsvempty\else, \tlsvsuf\fi, }%
\def\tlsvnwalk#1{\def\tlsvcur{#1}\ifx\tlsvcur\tlsvnil
  \else\tlsvnelt#1\expandafter\tlsvnwalk\fi}%
\def\tlsvverbdecide{\ifx\tlsvnt\bgroup
  \expandafter\tlsvgobbleone\else\expandafter\tlsvverbread\fi}%
\def\tlsvgobbleone#1{}%
\def\tlsvverbread#1\endverb{}%
\providecommand{\sortlist}[2][]{%
  \par
  \ifcsname refname\endcsname\else\def\refname{References}\fi
  \subsection*{\refname}%
  \expandafter\ifx\csname current@color\endcsname\relax
    \expandafter\def\csname current@color\endcsname{gray 0}\fi
  \begingroup\parindent=0pt\parskip=\itemsep
  \def\list##1##2##3{##3 }%
  \def\entry##1##2##3{\par\hangindent=1.5em\hangafter=1\noindent}%
  \def\endentry{}%
  \def\strng##1##2{}%
  \def\keyw##1{}%
  \def\name##1##2##3##4{\tlsvnwalk##4\tlsvnil}%
  \def\field##1##2{\tlsvfldemit{##1}{##2}}%
  \def\verb{\futurelet\tlsvnt\tlsvverbdecide}%
  \def\endverb{}%
  \expandafter\def\csname blx@bbl@data\endcsname{blx@data@tlsv}%
  \expandafter\def\csname blx@data@tlsv\endcsname{}%
}%
\expandafter\ifx\csname endsortlist\endcsname\relax
  \expandafter\def\csname endsortlist\endcsname{\par\endgroup}\fi
}
"""


#: crossreftools 1.0 splitter 字段臂修补 (2211.04538): 上游
#: ``\crt@cref@splitter@<field>#1#2`` 按 cleveref ≤0.21 双组
#: ``\r@<l>@cref`` 形 ``{[t][n][]r}{[p][]p}`` 取参; ≥0.21.1 五组形
#: ``{[t][n][]r}{[p][]p}{}{}{}`` 残留 ``{}{}{}`` 直接落进
#: ``\csname cref@<type>{}{}{}@name`` 构造 → 组内 csname-relax 化
#: orphan token 存进 ``\@currentlabelname``/toc whatsit → 写期
#: ``undefined_cs|cref@section`` (preamble ``\def`` 该名无用 —— orphan
#: 名带 ``{}{}{}`` 后缀且 relax 绑定随组蒸发, r2-r9 实证)。根修 =
#: splitter 第三参 ``#3\fi`` 定界吞尾组再回吐 ``\fi`` —— 双组/五组
#: 两形通吃, 字段层名 (``@counter/@number/@result/@reference/@page``)
#: 直改: 包装载期 ``\let`` 快照链 ``firstarg→counter`` 在钩点已
#: 完成, 改 arg 层够不到字段层 → 须覆写字段名本体。``#`` 参数用
#: 单 ``#`` 形 —— lthooks 存钩码不折叠 ``##`` (kernel≥2020 实证)。
_CRT_CREF_SPLITTER_FIX = r"""
\makeatletter
\AddToHook{begindocument/before}{%
\def\crt@cref@splitter@counter#1#2#3\fi{\expandafter\crt@@cref@@splitter@@first#1\@nil\fi}%
\def\crt@cref@splitter@number#1#2#3\fi{\expandafter\crt@@cref@@splitter@@second#1\@nil\fi}%
\def\crt@cref@splitter@result#1#2#3\fi{\expandafter\crt@@cref@@splitter@@third#1\@nil\fi}%
\def\crt@cref@splitter@reference#1#2#3\fi{\expandafter\crt@@cref@@splitter@@fourth#1\@nil\fi}%
\def\crt@cref@splitter@page#1#2#3\fi{\expandafter\crt@@cref@@splitter@@fourth#2\@nil\fi}%
}
\makeatother
"""


#: undefined_cs → 定向修复表 (cs_targeted_fix 的默认表, rules/
#: params.cs_table 可扩)。spec 键: strip_pkg / usepackage / cs_map /
#: guard / guard_pre / polyfill / polyfill_pre / engines{eng: 覆盖 spec}
#: —— 组合语义见 cs_targeted_fix。
_CS_FIX_TABLE: dict[str, dict[str, Any]] = {
    # 1909.05039: breakurl 的 shipout 钩调 \headerps@out —— 该宏只在
    # hyperref dvips/ps2pdf 驱动下有定义, xetex/tectonic 走 hdvipdfm →
    # 未定义即炸。breakurl 对 pdf 直出引擎本就无意义, 剥装载点是根修。
    "headerps@out": {"strip_pkg": "breakurl"},
    # 2301.01267: \mathbbm ← bbm。xelatex/TL2026 装 bbm-macros 即可;
    # tectonic 侧 bbm 是 MF-only 死路 (font_sub_shim 同族) → 换 dsfont\mathds。
    "mathbbm": {
        "usepackage": "bbm",
        "engines": {
            "tectonic": {
                "strip_pkg": "bbm",
                "usepackage": "dsfont",
                "cs_map": {"mathbbm": "mathds"},
            }
        },
    },
    # 2308.04212/2403.00111: WileyNJD-v2.cls:248 \reserveinserts{28} ——
    # LaTeX2e<2015 kernel 原语 (旧式 insert 寄存器预留); etex.sty 在新
    # 内核下整段跳过 → 名未定义。cls 在 \documentclass 内执行, 缝后
    # 注入鞭长莫及 → polyfill_pre 落 docclass 行前。新内核分配器本就
    # 免预留 → providecommand 一参 gobble 语义无损 (\@gobble 形需
    # @-letter 语境, providecommand 形在 .tex 顶零依赖)。
    "reserveinserts": {"polyfill_pre": r"\providecommand\reserveinserts[1]{}"},
    # biblatex backend=bibtex 稿的 bundled .bbl 是 2.8/2.9 格式 (1907.03923/
    # 1706.00220/1706.00324/1706.02744/1803.03145, shimdiag #171 cluster-A):
    # TL biblatex 3.21 不载旧读者 → .bbl 顶层 \sortlist undefined_cs。
    # bbl_regen (80-bib.yaml) 的 has_ext:.bcf 门对 bibtex-backend 稿恒空
    # (.bcf 是 biber 专属), svjour shim 的同款读者又困在 missing_file 臂
    # 够不到 → 泛化成默认表 polyfill, 细节见 _SORTLIST_BBL_POLYFILL 头注。
    "sortlist": {"polyfill": _SORTLIST_BBL_POLYFILL},
    # 2105.12363 main.tex:215 \def\And{...\rule{\z@}{24pt}} —— doc 体
    # @=other catcode 下 \z@ 分词为 cs \z + 字符 @, 作者本意是 kernel
    # 私有 \z@ (0pt 寄存器) 零宽竖线; \ificlr\else 臂恒活 → \z 裸缺
    # + @ 字符残留触发 Missing number/Illegal unit 级联。@-分隔
    # \def\z@{0pt} 让 \z 吞掉跟随的 @ 字面吐 0pt —— 与 kernel \z@
    # 语义逐字符一致, 非 @ 场景永不触发 (裸 \z 调用形不存在)。
    # \ifdefined 护: cls 已备 \z 时不抢名。
    "z": {"polyfill": r"\ifdefined\z\else\def\z@{0pt}\fi"},
    # 1503.00273 rjparticle.cls:316-317 \let\oldcr\\ 于 \affil 组内 +
    # {\def\\{\oldcr \ignorespaces}\xdef\AB@temp{#2}} —— 2013 稿照抄
    # authblk 97 年代形: 旧内核 \\ 是可展宏, \let 冻结含义进 xdef 安全;
    # 现代内核 \\ 是 \protected → xdef 内不可展, \oldcr 字面嵌入
    # \AB@affillist, \endgroup 后局部 let 蒸发 → \@author 排版期
    # undefined (sinaia.log:564 l.561 \maketitle 实证)。全局 \newline
    # 替身: 语义 = let 点想冻结的文本 \\ ({\centering\@author} 块内
    # 换行); 不取 \\ 本体 —— 若同族稿 \def\\{\oldcr…} 重绑后 xdef
    # 无 let 冻结, \oldcr→\\→\oldcr 自指死循环, \newline 恒免疫。
    "oldcr": {"polyfill": r"\providecommand\oldcr{\newline}"},
    # astro-ph/9612039 (fix_residuals): vendored aaspp4.sty:96-98
    # \def\references{...\bgroup...\def\refpar{\par\hangindent=3em
    # \hangafter=1}} —— \refpar 作用域锁死在 references env 组内
    # (上游 aaspp4/aasms4 原构), 而稿在 thebibliography 裸调
    # \reference{key}→\refpar (:133), env 外无定义 → undefined_cs
    # (pfsd96_pp.tex:475 实证)。provide 同体全局替身: env 内局部
    # \def 仍遮罩 (同体零语义差), env 外调用有兜底。
    "refpar": {"polyfill": r"\providecommand\refpar{\par\hangindent=3em\hangafter=1}"},
    # 2211.04538 (csfix8): crossreftools 1.0 splitter × cleveref ≥0.21.1
    # 五组 ``*@cref`` newlabel 形 → 写期 ``\csname`` orphan —— 修补字段层
    # splitter (机理与 hook 点选择见 _CRT_CREF_SPLITTER_FIX 头注)。
    "cref@section": {"polyfill": _CRT_CREF_SPLITTER_FIX},
    # 1206.1993 (csfix8): 95-targeted.yaml cs_table 已有 ``Bar`` 键但
    # payload 是小写 ``bar`` —— 精确大小写查表落空。eulervm 稿 ``\Bar``
    # 展开 ``\bar``, eulervm 版不设 ``\bar`` 数学重音 → 裸缺。defer 必需:
    # preamble ``\providecommand`` 会抢 eulervm ``\DeclareMathAccent``
    # 名 → AtBeginDocument 复查点先让位, 已定义则不覆。
    "bar": {
        "polyfill": r"\AtBeginDocument{\providecommand\bar[1]{\overline{#1}}}",
    },
    # 2504.01669 (csfix8): doc 体直调 ``\inputencoding{latin1}`` —
    # xelatex 下 inputenc 不载 (inputenc_strip 臂只应 inputenc_unicode
    # 类, 此格是裸 undefined_cs) → 一参 gobble。
    "inputencoding": {"polyfill": r"\providecommand\inputencoding[1]{}"},
    # 2009.11007 (csfix8): doc 自有 ``{\red 这是译文}`` 色切宏无定义
    # → xcolor 装载 + 组内色切替身。
    "red": {
        "usepackage": "xcolor",
        "polyfill": r"\providecommand{\red}{\color{red}}",
    },
    # cond-mat/0111246 (csfix8): 2.09 代 tabbing 重音 ``\+'e`` 裸调
    # (tabbing env 外无定义) → 零参 gobble 脱壳留 'e 文本;
    # tabbing env 内 ``\+`` 由 env 自重绑, providecommand 不干扰。
    "+": {"polyfill": r"\providecommand{\+}{}"},
}


def _rewrite_cs_map(t: str, cmap: dict[str, str]) -> tuple[str, int]:
    r"""``\old``→``\new`` 逐对改写 (词边界定) → (新文本, 是否改动)。"""
    nt = t
    for old, new in cmap.items():
        nt = re.sub(rf"\\{old}\b", rf"\\{new}", nt)
    return nt, int(nt != t)


def _ensure_usepackage(ctx: LoopCtx, eng: Engine, pkg: str) -> list[str]:
    r"""主文件 ``\documentclass`` 后注入 ``\RequirePackage{pkg}`` + 装文件 → 已做事项。"""
    out = []
    if not re.search(
        rf"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{{[^}}]*\b{re.escape(pkg)}\b",
        mask_tex(ctx.source_blob()),  # 注释掉的 %\usepackage 不算已装载
    ) and _inject_after_docclass(ctx, f"\\RequirePackage{{{pkg}}} % fixloop: cs-fix"):
        out.append(f"inject \\RequirePackage{{{pkg}}}")
    if eng.probe_file(f"{pkg}.sty") or eng.install_file(f"{pkg}.sty"):
        out.append(f"{pkg}.sty available")
    else:
        out.append(f"{pkg}.sty still missing")
    return out


#: cs_targeted_fix 的 glue-残骸前缀拆分默认头表 —— 只收语料实证过的
#: 粘连头 (n100 undefined_cs 24/24 均为 splice/join 合并残骸; ``in`` 头
#: 前缀面太热 (int/indent/input/index… 真宏云集), 留在 cs_table 显式条目)。
_SPLIT_HEADS: tuple[str, ...] = (
    "linebreak",
    "item",
    "nabla",
    "Delta",
    "hline",
    "frac",
    "par",
    "dd",
    "bf",
    "it",
    "rm",
)
#: 与头同前缀的真宏名守卫 —— 命中即不拆 (part/parbox/parskip 是 kernel
#: 命令; ddot/ddots 是 amsmath; itemize/fraction 同理)。残余门之外的双保险。
_SPLIT_GUARD: frozenset[str] = frozenset(
    {
        "part",
        "para",
        "parbox",
        "parskip",
        "itemize",
        "itemsep",
        "ddot",
        "ddots",
        "fraction",
    }
)
#: 拆分残余的长度门 (语料残余全 ≤4: FSU/Cd/i/and/r…; 更长残余的真宏名
#: 还有 guard 兜底)。
_SPLIT_REST_MAX = 4


def _split_glued_cs(cs: str, heads: Iterable[str], guard: Iterable[str]) -> str | None:
    """``cs`` = 已知粘连头 + 残余 → ``"head rest"``; 不可拆返回 None。

    残余门: 大写起首或 ≤_SPLIT_REST_MAX 字符; ``@`` 含名是包内私有 cs
    (版本偏斜类), 非粘连残骸, 不拆。
    """
    if "@" in cs or cs in guard:
        return None
    for head in sorted(heads, key=len, reverse=True):
        if not cs.startswith(head):
            continue
        rest = cs[len(head) :]
        if rest and (rest[0].isupper() or len(rest) <= _SPLIT_REST_MAX):
            return f"{head} {rest}"
    return None


def _inject_before_docclass(ctx: LoopCtx, snippet: str) -> bool:
    r"""主文件首个活 ``\documentclass`` 行首前注入 snippet (幂等)。

    cls 内调用面专用: ``\documentclass`` 执行期的 undefined_cs ——
    halt_on_error 下缝后注入永远够不到。首个 depth-0 docclass token
    的行首前落位; 无 depth-0 docclass (宏代理形/残缺稿) 退文件头,
    preamble 顶仍先于一切 cls 执行。多臂 ``\if..\else..\fi`` 分支
    docclass 是已知残余 (注进首臂, 不烂义)。
    """
    main = ctx.main_path()
    if main is None:
        return False
    t = ctx.read(main) or ""
    if snippet in t:
        return False
    masked = mask_tex(t)
    pos = 0
    for m in iter_depth0(DOCCLASS_RX, masked):
        if masked[m.start() : m.end()] != t[m.start() : m.end()]:
            continue  # 跨遮盖区命中 —— verbatim/死臂内假 docclass
        pos = t.rfind("\n", 0, m.start()) + 1
        break
    ctx.write(main, t[:pos] + snippet + "\n" + t[pos:])
    return True


#: cs_targeted_fix ``guard``/``guard_pre`` 值形归一 —— ``true`` → 零参空体;
#: ``"[1]"`` 串 → argspec (空 body); dict ``{args, body}`` → 全形。
#: emission 恒走 ``\csname`` 包裹: 裸 ``\providecommand\foo@bar`` 在 @=other
#: 读面把名断成 ``\foo``+stray 字母 (静默错义 + ``Missing \begin{document}``
#: 级联), ``\providecommand\csname`` 直写又把 ``\csname`` 当已定义名而
#: 静默 no-op —— 双死形, ``\expandafter`` 先行展开是唯一通解
#: (lane-renewguard forms/forms3.tex 全形实证)。``Command \X undefined``
#: (renew-on-undefined 内核签) 与 ``\csname`` 派发/@-名 cs_table 条目
#: 的本键一并收 —— provide 预置, doc 侧 ``\renewcommand`` 合法接管;
#: body 即未 renew 时的 use-site 兜底, 语义同 polyfill 但名自表键出。
def _guard_snippet(cs: str, guard: object) -> str | None:
    r"""``guard`` spec → csname 形 ``\providecommand`` 预置 snippet; 不合法返回 None。"""
    if guard is True:
        args, body = "", ""
    elif isinstance(guard, str):
        args, body = guard, ""
    elif isinstance(guard, dict):
        args, body = str(guard.get("args") or ""), str(guard.get("body") or "")
    else:
        return None
    if not cs or re.search(r"[\\{}\s]", cs):
        return None
    return (
        "\\expandafter\\providecommand\\expandafter"
        f"{{\\csname {cs}\\endcsname}}{args}{{{body}}}"
    )


def cs_targeted_fix(  # noqa: C901, PLR0912 - spec 键序分派表, 每键一处
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""undefined_cs 按 cs 修复表打靶 (handoff §2.2 cs→包表项)。

    spec 键组合序: ``strip_pkg`` 剥装载点 → ``usepackage`` 注入+装文件
    → ``cs_map`` ``\old``→``\new`` 逐文件改写 → ``guard``/``guard_pre``
    csname 形 ``\providecommand`` 预置 (renew-on-undefined 与 @-名专用,
    语义见 ``_guard_snippet`` 头注) → ``polyfill`` 注原始 TeX body
    (docclass 缝后) → ``polyfill_pre`` 同形注 docclass 行前 (cls 执行期
    调用面专用, ``\reserveinserts`` 类)。``engines.{eng_name}`` 子表整体
    覆盖顶层同名词 (引擎差异修, 如 bbm→dsfont)。payload 不在表 → 试
    ``split_heads`` glue-残骸前缀拆分 (合成 cs_map 项); 仍不中 → False
    落 undefined_cs_guess。
    """
    table = dict(_CS_FIX_TABLE)
    table.update(params.get("cs_table") or {})
    cs = (payload or "").lstrip("\\")
    base = table.get(cs)
    if not base:
        split = _split_glued_cs(
            cs,
            params.get("split_heads") or _SPLIT_HEADS,
            params.get("split_guard") or _SPLIT_GUARD,
        )
        if split is None:
            return False, f"{payload} not in cs-fix table"
        base = {"cs_map": {cs: split}}
    spec = {k: v for k, v in base.items() if k != "engines"}
    spec.update((base.get("engines") or {}).get(ctx.engine_name) or {})
    done: list[str] = []
    if strip := spec.get("strip_pkg"):
        n = _map_tex_files(
            ctx,
            (".tex", ".sty", ".cls"),
            lambda t: _drop_pkg_loads(t, str(strip)),
        )
        if n:
            done.append(f"strip \\usepackage{{{strip}}} x{n}")
    if use := spec.get("usepackage"):
        done.extend(_ensure_usepackage(ctx, eng, str(use)))
    if cmap := spec.get("cs_map"):
        n = _map_tex_files(ctx, (".tex", ".sty"), lambda t: _rewrite_cs_map(t, cmap))
        if n:
            done.append(f"cs_map in {n} files")
    for gkey, pre in (("guard", False), ("guard_pre", True)):
        if g := spec.get(gkey):
            snip = _guard_snippet(cs, g)
            if snip and (
                _inject_before_docclass(ctx, snip)
                if pre
                else _inject_after_docclass(ctx, snip)
            ):
                done.append(
                    "pre-docclass guard injected" if pre else "guard seed injected"
                )
    if spec.get("polyfill") and _inject_after_docclass(ctx, str(spec["polyfill"])):
        done.append("polyfill injected")
    if spec.get("polyfill_pre") and _inject_before_docclass(
        ctx, str(spec["polyfill_pre"])
    ):
        done.append("pre-docclass polyfill injected")
    if not done:
        return False, f"cs-fix spec for {cs} applied nothing"
    return True, "; ".join(done)


#: 寄存器/盒型分配的裸 cs 形 (plain/cls 内码常见): ``\newbox\splitbox``。
#: ``\newif\ifX`` 伴生 ``\Xtrue``/``\Xfalse``; ``*def`` 系 primitive 同把名
#: 绑进寄存器槽位——``\let\X\@undefined`` 后名被后载包抢占, 原 ``\setbox``/
#: ``\advance`` 点变 Missing number (2211.04482 aastex62 ``\splitbox`` 实证)。
_ALLOC_CS_RE = re.compile(
    r"\\(?:newbox|newcount|newdimen|newskip|newmuskip|newtoks|newread"
    r"|newwrite|newif|newinsert|newmarks|newfont|newlanguage"
    r"|chardef|mathchardef|countdef|dimendef|skipdef|muskipdef"
    r"|toksdef|font)\s*\\([A-Za-z@]+)"
)
#: LaTeX 花括号形: ``\newlength{\x}``/``\newsavebox{\x}`` 直给寄存器名;
#: ``\newcounter{c}`` 分配 ``\c@c``; ``\newboolean{b}`` 内部走 ``\newif\ifb``。
_ALLOC_BRACE_RE = re.compile(
    r"\\(newlength|newsavebox|newcounter|newboolean|provideboolean)"
    r"\s*\{\s*\\?([A-Za-z@]+)\s*\}"
)


def _allocated_cs_names(masked_blob: str) -> frozenset[str]:
    r"""遮盖视图上扫寄存器/盒型分配名集 (含 ``\newif``/``\newboolean`` 伴生)。"""
    names: set[str] = set()
    for m in _ALLOC_CS_RE.finditer(masked_blob):
        n = m.group(1)
        names.add(n)
        if n.startswith("if") and n[2:]:
            names.add(n[2:] + "true")
            names.add(n[2:] + "false")
    for m in _ALLOC_BRACE_RE.finditer(masked_blob):
        kind, n = m.group(1), m.group(2)
        if kind in ("newlength", "newsavebox"):
            names.add(n)
        elif kind == "newcounter":
            names.add("c@" + n)
        else:  # newboolean/provideboolean → \newif\ifn 同构
            names.add("if" + n)
            names.add(n + "true")
            names.add(n + "false")
    return frozenset(names)


#: log 内 Command-形 already_def 撞名全扫 —— 三引号形同收:
#: ``Command \X already defined`` / ``Command `\X' already defined``
#: (老 ``\@ifdefinable`` 报错) / ``Command '\X' already defined`` (ltcmd)。
_ALREADY_DEF_CS_RE = re.compile(
    r"Command\s+[`'\"]?\\([A-Za-z@]+)[`'\"]?\s+already\s+defined"
)

#: 再定义命令站点面 (site-prepend 清位目标) —— 只收"名必须未定义"族
#: (撞名才产 already_def): renewcommand/RenewDocumentCommand 要名已定义,
#: 前置 ``\let\@undefined`` 反使其炸; providecommand 族撞名静默不报错,
#: 清位反夺 cls 既有定义 —— 均不入列; ``\def``/``\newtheorem`` 系亦
#: 不产 Command 签。DeclareMath{Symbol,Delimiter,Accent,Radical} 四件
#: 与 DeclareMathAlphabet 同走 ``\ifx\csname X\endcsname\relax`` 自有
#: 守卫 (latex.ltx:13462/13511/13594/13696 ``Command `\X' already
#: defined``, 非 ``\@ifdefinable``) —— ``\let\X\@undefined`` 清位有效。
#: DeclareSymbolFontAlphabet 不收: 其守卫查的是 space-后缀伴生名
#: ``\X␣`` (latex.ltx:13753-13763), 清 ``\X`` 本体是徒劳。
#: ``\newfont{\X}{spec}`` (2.09/AMS 字体绑名, ``\@ifdefinable`` 恒拒
#: 产 Command 签; astro-ph/0307459 ``\Bbb`` 实证) 亦收 —— 裸形
#: ``\newfont\X`` 仍由 ``_ALLOC_CS_RE`` 分配名护栏剔出, 只花括号形入站点面。
_SITE_DEF_CMDS: tuple[str, ...] = (
    "newcommand",
    "DeclareRobustCommand",
    "NewDocumentCommand",
    "DeclareDocumentCommand",
    "DeclareMathAlphabet",
    "newmathalphabet",
    "NewMathAlphabet",
    "DeclareMathSymbol",
    "DeclareMathDelimiter",
    "DeclareMathAccent",
    "DeclareMathRadical",
    "DeclareMathOperator",
    "newfont",
)
#: ``\providecommand`` 族只收 end* 名站点: 非恒拒名撞名静默不产
#: already_def (前置清位反夺 cls 先定义 —— 不入 _SITE_DEF_CMDS 之理);
#: 但 undefined 态对 end* 名必走 ``\new@command`` → ``\@ifdefinable``
#: 恒炸 already_def (W151 ``\providecommand{\endproof}`` r1→r2 死循环
#: 实证), 此时 rc@ 前置恰保留 provide 语义 (defined→skip/undefined→define)。
_PROVIDE_SITE_CMDS: tuple[str, ...] = ("providecommand",)
#: ``\@ifdefinable`` 路由命令 —— end* 名站点前置换 ``\let\@ifdefinable
#: \@rc@ifdefinable`` 单发旁路 (kernel 内建同款, latex.ltx:1294
#: ``\renew@command`` / :1402 ``\declare@robustcommand@auxii``: rc@ 被
#: 消费时先还原 ``\@@ifdefinable`` 再续定义体 —— 恰放行紧邻一次
#: ``\@ifdefinable`` 调用后自愈, defined/undefined 两态皆过, 不泄检查面)。
#: ltcmd ``\NewDocumentCommand``/``\DeclareDocumentCommand`` 走
#: ``\cs_if_exist`` 无 end 守卫 (``\__cmd_check_end`` 只服务 env copy/show);
#: ``\DeclareMathAlphabet`` 族走自有 ``\ifx\csname X\endcsname\relax``
#: (``\csname`` 把 undefined 名冻结成 ``\relax`` → ``\let\X\@undefined``
#: 对其本就有效, fixprobe 实证) —— DeclareMath{Symbol,Delimiter,Accent,
#: Radical} 同此守卫 (latex.ltx:13505/13585/13455/13652 ``\expandafter
#: \ifx\csname\@gobble\string#1\endcsname\relax`` 形), 且 end* 名无
#: ``\@qend`` 拒径 (非 ``\@ifdefinable`` → 不查 ``\@qend``) —— 均不食
#: ``\@ifdefinable``, 前置 rc@ 会泄给下个用户 → 不入列。
_IFN_ROUTED_CMDS: frozenset[str] = frozenset(
    {
        "newcommand",
        "providecommand",
        "DeclareRobustCommand",
        "DeclareMathOperator",
        "newfont",
    }
)
#: ``\@ifdefinable`` 双恒拒名形之二 (latex.ltx:1301 ``\@qrelax`` 全名形):
#: ``\relax`` 是 primitive —— ``\let\relax\@undefined`` 注毁其义, rc@ 旁路
#: 真把它重定义掉, 皆全局灾难 → 无安全清位路径, 与寄存器分配名同列弃修。
_RESERVED_UNDEFINABLE: frozenset[str] = frozenset({"relax"})


def _endstar_name(name: str) -> bool:
    r"""Cs 名 ``\@ifdefinable`` 恒拒形判定 (end* 前缀)。

    ``\@carcube`` 取名前 3 字符 = ``\@qend``("end") 即 ``\@notdefinable``
    (latex.ltx:1296-1305), 与该名是否已定义无关 —— ``\let\X\@undefined``
    清位后 ``\newcommand`` 族仍炸同一 already_def 签名。
    """
    return name.startswith("end")


def _site_clear_line(cmd: str, name: str) -> str | None:
    r"""站点前置串 (csname-let 形 —— 免 ``\makeatletter`` 对, 全宿主 catcode 安全)。

    None = 该 (命令, 名形) 组合不收站点 (``\providecommand`` 族非恒拒名)。
    ``\@ifdefinable`` 路由命令 × end* 名 → ``\@rc@ifdefinable`` 单发旁路;
    其余 → ``\let\X\@undefined`` 等价 csname 形 (名可含 ``@``)。
    """
    if cmd in _PROVIDE_SITE_CMDS and not _endstar_name(name):
        return None
    if _endstar_name(name) and cmd in _IFN_ROUTED_CMDS:
        return _let_cs("@ifdefinable", "@rc@ifdefinable")
    return _undefine_cs(name)


def _redef_site_map(
    ctx: LoopCtx,
    site_re: re.Pattern[str],
    allocated: frozenset[str],
) -> dict[Any, set[str]]:
    r"""逐文件 live 站点名集 (遮罩复核剔死区, 剔寄存器/``\@qrelax`` 保留名)。

    ``site_re`` group(1)=命令名, group(2)=cs 名; ``\providecommand`` 族
    只收 ``_endstar_name`` 恒拒名形 (非恒拒名撞名静默, 前置清位反夺
    cls 先定义)。
    """
    out: dict[Any, set[str]] = {}
    # .bbl 亦收: 用户件 shipped .bbl 内的 \newcommand 站是同款"名必须
    # undefined"面 —— revtex4-1 rtx@thebibliography env-end \auto@bib@innerbib
    # 把 \jobname.bbl 二次 input, bbl 自体双 input 撞名 (1907.10621 \enquote
    # 实证); 锚在 \bibliography/\input 外侧的清位够不到 bbl 内互撞。
    for f in ctx.tex_files((".tex", ".sty", ".cls", ".bbl")):
        t = ctx.read(f) or ""
        masked = mask_tex(t)
        names = (
            {
                m.group(2)
                for m in site_re.finditer(masked)
                if masked[m.start() : m.end()] == t[m.start() : m.end()]
                and _site_clear_line(m.group(1), m.group(2)) is not None
            }
            - allocated
            - _RESERVED_UNDEFINABLE
        )
        if names:
            out[f] = names
    return out


def _prepend_sites_in_text(
    t: str,
    masked: str,
    site_re: re.Pattern[str],
    targets: set[str],
) -> tuple[str, int]:
    r"""单文件内 ``targets`` 站点前置清位串 → (新文本, 前置数)。

    前置形态由 ``_site_clear_line`` 按 (命令, 名形) 分流; 遮盖命中文本
    逐字节复核剔死区 (``\iffalse``/verbatim), 上轮已 prepend 的站点按
    128 字前缀窗幂等跳过 (新 csname 形与旧 ``\let\X\@undefined`` 形双查)。
    """
    out: list[str] = []
    prev, n = 0, 0
    for m in site_re.finditer(masked):
        name = m.group(2)
        if name not in targets:
            continue
        ins = _site_clear_line(m.group(1), name)
        if ins is None:
            continue  # 非恒拒名 provide 站点 —— 同 _redef_site_map 过滤
        if masked[m.start() : m.end()] != t[m.start() : m.end()]:
            continue  # 跨遮盖区命中 —— 死代码内站点不数不动
        window = t[max(0, m.start() - 128) : m.start()]
        if (
            ins in window
            or f"\\let\\{name}\\@undefined" in window  # 上轮旧形 emit
            or (
                _endstar_name(name) and "\\let\\@ifdefinable\\@rc@ifdefinable" in window
            )
        ):
            continue  # 上轮已 prepend 过的站点
        out.append(t[prev : m.start()])
        out.append(ins + "\n")
        prev = m.start()
        n += 1
    if not n:
        return t, 0
    out.append(t[prev:])
    return "".join(out), n


def _undefine_sites(
    ctx: LoopCtx,
    guilty: Iterable[Any],
    site_re: re.Pattern[str],
    targets: set[str],
) -> int:
    r"""Guilty 文件内 ``targets`` 站点前置清位 → 改写文件数。

    前置形态按 (命令, 名形) 分流: ``\@ifdefinable`` 路由命令
    (``_IFN_ROUTED_CMDS``) × end* 恒拒名 → ``\@rc@ifdefinable`` 单发旁路
    (``\let\X\@undefined`` 对恒拒名是徒劳: 重定义侧仍过 ``\@ifdefinable``
    炸同一 already_def 签名, W151); 其余站点 → undefine 等价 csname 形
    (ltcmd ``\cs_if_exist`` 与 mathalphabet ``\csname``-freeze 检查均认
    其为 undefined)。

    csname 形零字面 ``@``, 全文件类统一裸前置 —— ``.cls``/``.sty`` 宿主
    @=letter、``.tex``/``.bbl`` 宿主 @=other、doc 自带 ``\makeatletter``
    区三语境同写; 旧 ``\makeatletter`` 对在 @=letter 宿主内会把尾段强翻
    回 12 (1803.02902 ``\widebar`` 体 ``\@ne`` 级联实证), 已退役。
    """
    n_files = 0
    for f in guilty:
        t = ctx.read(f)
        if t is None:
            continue
        nt, _n = _prepend_sites_in_text(t, mask_tex(t), site_re, targets)
        if nt != t:
            ctx.write(f, nt)
            n_files += 1
    return n_files


#: file:line 形 already_def 错误的肇事包定位 —— ``path/<pkg>.sty:N:
#: LaTeX Error: Command `\X' already defined`` 同时给出肇事包茎与撞名。
#: 报错包在执行序上恒为后定义者 (先定义者无论在哪都已跑完), 故其
#: 每个用户件装载点前清位序恒正确 —— 与 docclass 块互补: 缝位在
#: preamble 先定义者 (``\usepackage{newtxmath}`` 类) 尚未执行时
#: ``\let`` 是纯 no-op (bbkresid 4 格同型实证), 装载点前清位才
#: 落在先/后定义者之间。``.cls`` 不收: 类文件无 usepackage 装载点
#: 可锚 (其内互撞归站点臂/abstain)。
_PKG_ERR_FILE_RE = re.compile(
    r"^[ \t]*\S*?([\w.+-]+)\.sty:\d+:\s*LaTeX Error:"
    r"\s*Command\s+[`'\"]?\\([A-Za-z@]+)[`'\"]?\s+already\s+defined",
    re.MULTILINE,
)


def _pkg_err_stems(log: str) -> dict[str, set[str]]:
    r"""file:line 形 already_def 行扫 → ``{撞名: {肇事包 sty 茎 (小写)}}``。"""
    out: dict[str, set[str]] = {}
    for m in _PKG_ERR_FILE_RE.finditer(log):
        out.setdefault(m.group(2), set()).add(m.group(1).lower())
    return out


#: ``\usepackage``/``\RequirePackage`` 装载点 —— group(1)=花括内逗号列
#: 元素串 (``[opts]`` 跳过)。无行首锚: ``\if..\RequirePackage..\fi``
#: 单行条件形也收, 前置在 token 前序位恒正确。
_LOAD_SITE_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]\n]*\])?\s*\{([^}]*)\}"
)


def _undefine_pkg_sites(
    ctx: LoopCtx, cs_stems: dict[str, set[str]]
) -> tuple[int, set[str]]:
    r"""肇事包茎的用户件装载点前 ``\let\X\@undefined`` → (前置站数, 覆盖撞名集)。

    肇事包恒为后定义者 → 其每个 live 装载点 (opts/逗号列元素匹配茎名,
    dup 站全收) 前清位序恒正确; 遮盖复核剔注释/verbatim 死站, 上轮
    已前置的 cs 按 256 字前缀窗幂等跳过 (新 csname 形与旧
    ``\let\X\@undefined`` 形双查)。csname 形零字面 ``@`` —— 全文件类
    统一裸前置, 不再按 ``.tex``/``.sty`` 分 ``\makeatletter`` 对。
    肇事茎无用户件装载点 (cls 内传递装载) 的撞名不进返回集 → 调用方以
    docclass 块兜底。
    """
    want = set().union(*cs_stems.values()) if cs_stems else set()
    covered: set[str] = set()
    n_sites = 0
    for f in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(f)
        if not t:
            continue
        masked = mask_tex(t)
        out: list[str] = []
        prev = 0
        for m in _LOAD_SITE_RE.finditer(masked):
            if masked[m.start() : m.end()] != t[m.start() : m.end()]:
                continue  # 跨遮盖区命中 —— 注释/verbatim 内死站不锚
            elems = {e.strip().lower() for e in m.group(1).split(",") if e.strip()}
            if not (elems & want):
                continue
            window = t[max(0, m.start() - 256) : m.start()]
            names = sorted(
                cs
                for cs, stems in cs_stems.items()
                if stems & elems
                and f"\\let\\{cs}\\@undefined" not in window
                and f"\\csname {cs}\\endcsname" not in window
            )
            if not names:
                continue
            ins = "".join(_undefine_cs(n) for n in names)
            out.append(t[prev : m.start()])
            out.append(ins + "\n")
            prev = m.start()
            covered.update(names)
            n_sites += 1
        if out:
            out.append(t[prev:])
            ctx.write(f, "".join(out))
    return n_sites, covered


#: file:line 形 already_def 的归因行 —— ``path/<file>.<ext>:N:`` + Command 签。
#: group(1)=基名茎 group(2)=扩展 group(3)=行号 group(4)=撞名。判 ``\AtBeginDocument``
#: 钩内 deferred 定义者用: 钩体在 ``\begin{document}`` 执行期才跑, 其内定义撞名
#: 的 file:line 归因恒落在 ``\begin{document}`` 所在行 (1706.00033 russianb.ldf
#: ``\DeclareMathOperator{\sh}`` vs 用户 ``\def\sh`` 实证)。
_ABD_ERR_FILE_RE = re.compile(
    r"^[ \t]*\S*?([\w.+-]+)\."
    r"(tex|sty|cls|bbl|ldf|def|clo|ltx|dtx|ins|fd):(\d+):"
    r"\s*(?:LaTeX Error:\s*)?Command\s+[`'\"]?\\([A-Za-z@]+)[`'\"]?"
    r"\s+already\s+defined",
    re.IGNORECASE | re.MULTILINE,
)


def _abd_deferred(ctx: LoopCtx, blob: str) -> set[str]:
    r"""归因行 = live ``\begin{document}`` 的 already_def 撞名集。

    ``\AtBeginDocument`` 钩内 deferred 定义者 (包/类装载期注册, ``\begin{document}``
    执行时才定义) 的专属判据: 钩执行期错误的 file:line 归因恒为钩所在文件的
    ``\begin{document}`` 行。立即 ``\let`` (docclass 块/装载点前) 恒错序 ——
    先于用户 preamble 定义跑完, 钩内定义者照样撞; 站点臂亦够不到包内钩体。
    文件按基名匹配 wdir 件集, 归因行遮罩后须仍见 live ``\begin{document}``
    (剔注释/verbatim 假行)。
    """
    files = {
        f.name.lower(): f
        for f in ctx.tex_files((".tex", ".sty", ".cls", ".bbl", ".ltx", ".dtx"))
    }
    out: set[str] = set()
    for m in _ABD_ERR_FILE_RE.finditer(blob):
        f = files.get(f"{m.group(1)}.{m.group(2)}".lower())
        if f is None:
            continue
        t = ctx.read(f)
        if t is None:
            continue
        lines = mask_tex(t).splitlines()
        n = int(m.group(3))
        if 1 <= n <= len(lines) and "\\begin{document}" in lines[n - 1]:
            out.add(m.group(4))
    return out


def _abd_hook_clear(
    ctx: LoopCtx, main_t: str, offenders: set[str], blob: str
) -> set[str]:
    r"""``\AtBeginDocument`` 迟延定义者臂 → 本轮钩内清位名集 (空 = 臂未接管)。

    撞名归因行 = live ``\begin{document}`` → 后定义者在 pkg/cls 注册的钩体内
    (babel .ldf ``\DeclareMathOperator`` 族), 一切立即 ``\let`` (docclass
    块/装载点前) 恒错序 —— 钩执行晚于全部 preamble 行。修 = 声明点行前注
    ``\AtBeginDocument{<csname-let 清位串>}`` —— 钩按注册序 FIFO 执行, 先于一切
    pkg/cls 钩注册 → 钩执行时先清位, 迟延定义者再定义赢 (1706.00033 ``\sh``
    实证)。无任何声明点 → 不接管 (209 稿 ``\documentstyle`` 亦锚:
    209-rewrite 换核后钩生效, 不换则死代码无害); ``_inject_before_docclass``
    失败 (snippet 已在) 同样不接管。end* 名不入: 迟延定义者仍是
    ``\@ifdefinable`` 恒拒, 钩内 ``\let`` 同样徒劳。已注册钩的名不重注
    (本轮 ``main_t`` 文本复核)。
    """
    if not find_docclass_ends(main_t):
        return set()
    abd = [
        n
        for n in sorted(_abd_deferred(ctx, blob) & offenders)
        if not _endstar_name(n)
        and f"\\let\\{n}\\@undefined" not in main_t
        and f"\\csname {n}\\endcsname" not in main_t
    ]
    if not abd or not _inject_before_docclass(
        ctx,
        "\\AtBeginDocument{"
        + "".join(_undefine_cs(n) for n in abd)
        + "} % fixloop: deferred-definer clear",
    ):
        return set()
    return set(abd)


def undefine_for_redef(  # noqa: C901 - 四修形并施 + 护栏逐门, 分派即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``already_def`` → ``\let\X\@undefined`` 让位 (批量化 + 站点前置版)。

    撞名集 = payload ∪ 本轮 log ``Command \X already defined`` 全扫
    (``_ALREADY_DEF_CS_RE`` 三引号形; 含 ``@`` 的包内名滤除 —— 寄存器
    内码险区, ``\c@X`` 类分配名由 ``_allocated_cs_names`` 护栏再兜)。
    payload 非 cs 形或不在 log 撞名集 (Theorem-style 等非 Command 签名
    的 already_def payload) → 丢弃只信 log。

    四修形并施:
      1. 站点前置 —— 撞名站点所在文件 (guilty file, 含 shipped .bbl) 内
         全部 ``_SITE_DEF_CMDS`` 站点前插 csname-let 清位串。halt_on_error
         每轮 log 只见首撞名, 站点簇扩
         才是一轮清场的机制 (1206.0299: 6 名连撞单轮全清); 未撞名站点
         前置是语义无操作 (undefine+define≡define)。盖 doc 内双定义与
         "包在 docclass 之后才定义"的窗口 (astro-ph/0408445
         ``\DeclareMathAlphabet{\mathbfit}`` 撞 bm 包定义) 与 .bbl 自体
         双 input 撞名 (revtex4-1 ``\auto@bib@innerbib`` 再 input
         ``\jobname.bbl``, 1907.10621 ``\enquote``)。end* 恒拒名形
         (``\@ifdefinable`` ``\@qend`` 前缀拒, 与定义态无关) 在
         ``\@ifdefinable`` 路由命令站点换 ``\@rc@ifdefinable`` 单发旁路;
         ``\providecommand`` 族站点只收该名形。
      2. 包装载点前置 —— file:line 形错误行抽肇事包茎, 其每个用户件
         ``\usepackage``/``\RequirePackage`` 装载点 (opts/逗号列/dup
         站全收) 前清位。报错包恒为后定义者 → 序恒正确, 修 docclass
         块鞭长莫及的 "preamble 包先定义, 后载包再定义" 互撞
         (bbkresid: newtxmath→amssymb ``\Bbbk`` 同型 4 格)。end* 名
         不入此臂: ``\let\X\@undefined`` 对恒拒名徒劳, rc@ 旁路又不能
         跨包体前置 (会被包内首个 ``\@ifdefinable`` 调用消费错目标)。
      3. ``\AtBeginDocument`` 钩臂 —— 错误归因行 = live ``\begin{document}``
         → 后定义者在 pkg/cls 注册的钩体内 (babel .ldf
         ``\DeclareMathOperator`` 族), 一切立即 ``\let`` 恒错序。声明点
         行前注 ``\AtBeginDocument{\let\X\@undefined}`` —— 钩 FIFO, 先注册
         先清位, 迟延定义者再定义赢 (1706.00033 ``\sh``)。无任何声明点
         → 不接管。
      4. docclass 块 —— 只对证实撞名集 (payload∪log 扫描, 不扩站点
         兄弟) 早清位, 兜无站点可指的撞名 (cls 内传递装载等)。装载点
         前置/钩臂已覆盖的名不入此块; end* 名亦不入: 无站点可指时
         ``\let\endX\@undefined`` 纯徒劳 (重定义侧仍恒拒) 且毁既有义 ——
         弃修交下位规则。

    ``params.min_batch`` (缺省 1) 门批量下限, 计数 = 撞名 ∪ guilty 文件
    站点名 (halt_on_error 下单撞名证据 + 同文件多站点即达批): order
    110.5 批规则传 2, 孤站单撞名格 (文件仅一处 ``\newcommand``) 让位
    renew(111) 已验证路径 —— 但撞名集含 end* 名时恒按 1 (renew 对
    undefined-end* 的 ``\@ifundefined`` 报错在 halt_on_error 下同样
    卡死, 该名形不能让位); payload=None (``other`` 类反引号签,
    taxonomy 不产 payload) 恒按 1 —— 该面无其他规则接手。
    """
    del eng
    log = _fixloop_log(ctx)
    scanned = {n for n in _ALREADY_DEF_CS_RE.findall(log) if "@" not in n}
    offenders: set[str] = set()
    cs = (payload or "").lstrip("\\")
    if cs and re.fullmatch(r"[A-Za-z@]+", cs) and (not scanned or cs in scanned):
        offenders.add(cs)
    offenders |= scanned
    allocated = _allocated_cs_names(mask_tex(ctx.source_blob()))
    had_names = bool(offenders)
    offenders -= allocated
    offenders -= _RESERVED_UNDEFINABLE
    if not offenders:
        return False, (
            "all collided cs are allocated/reserved names — abstain"
            if had_names
            else "no collided cs to clear"
        )

    site_cmds = tuple(str(c) for c in (params.get("site_cmds") or _SITE_DEF_CMDS))
    site_re = re.compile(
        r"\\("
        + "|".join((*site_cmds, *_PROVIDE_SITE_CMDS))
        + r")\s*\*?\s*\{?\s*\\([A-Za-z@]+)\s*\}?"
    )
    site_map = _redef_site_map(ctx, site_re, allocated)
    guilty = [f for f, names in site_map.items() if names & offenders]
    expanded = set().union(*(site_map[f] for f in guilty)) if guilty else set()
    fire_set = offenders | expanded
    min_batch = (
        1
        if payload is None or any(map(_endstar_name, fire_set))
        else int(params.get("min_batch") or 1)
    )
    if len(fire_set) < min_batch:
        return False, f"<{min_batch} collided+site-sibling cs — single path owns it"

    done: list[str] = []
    if guilty and expanded:
        n_sites = _undefine_sites(ctx, guilty, site_re, expanded)
        if n_sites:
            done.append(
                f"site-prepend guards in {n_sites} file(s) for {len(expanded)} cs"
            )

    cs_stems = {
        n: s
        for n, s in _pkg_err_stems(log).items()
        if n in offenders and not _endstar_name(n)
    }
    pkg_covered: set[str] = set()
    if cs_stems:
        n_load, pkg_covered = _undefine_pkg_sites(ctx, cs_stems)
        if n_load:
            done.append(
                f"pkg-load-site clears {len(pkg_covered)} cs "
                f"at {n_load} usepackage site(s)"
            )

    main = ctx.main_path()
    main_t = (ctx.read(main) or "") if main is not None else ""
    # \AtBeginDocument 迟延定义者臂 —— 机制见 _abd_hook_clear。
    abd = _abd_hook_clear(ctx, main_t, offenders, (ctx.err_head or "") + "\n" + log)
    if abd:
        done.append(f"AtBeginDocument hook clears {len(abd)} deferred cs")

    fresh = [
        n
        for n in sorted(offenders)
        if not _endstar_name(n)
        and n not in pkg_covered
        and n not in abd
        and f"\\let\\{n}\\@undefined" not in main_t
        and f"\\csname {n}\\endcsname" not in main_t
    ]
    if fresh:
        block = "% fixloop: batch undefine for redefinition\n" + "\n".join(
            _undefine_cs(n) for n in fresh
        )
        if _inject_after_docclass(ctx, block):
            done.append(f"docclass block clears {len(fresh)} cs")
    if not done:
        endstar = sorted(n for n in offenders if _endstar_name(n))
        if endstar:
            return False, (
                f"end*-name offenders {', '.join(endstar)} have no "
                "\\@ifdefinable-routed site — \\let\\X\\@undefined is futile "
                "for always-rejected names, defer"
            )
        return False, "all offenders already cleared"
    return True, "; ".join(done) + f" — {', '.join(sorted(fire_set))}"


# ═══ expl3 ``Control sequence`` 撞名缝顶清位格 (chineseclear, 2403.00013) ═══

#: ``Control sequence \X already defined`` —— expl3 ``\cs_new`` 系
#: ``\cs_if_exist`` 检查的 already-defined 签名 (Command 形 ``\@ifdefinable``
#: 报的姊妹签; taxonomy 只收 Command → 本签落 other 无 payload)。名字面
#: 纯字母类即闸: ``\c__fontspec_*``/``\ctex@*`` 内码名中 ``_``/``@`` 与
#: 紧跟的 `` already defined`` 邻接要求互斥, 天然排除 —— ``fontspec_
#: double_merge`` 的 ``\c__fontspec_shape_*`` 面与包内私有名都不进此格。
_CTLSEQ_DEF_RE = re.compile(r"Control sequence \\([A-Za-z]+) already defined")

#: file-line-error 行首 ``path/file.ext:NNN:`` 前缀 —— 第二定义者文件定位
#: (无此前缀的非 file-line-error log 不定界, 该名跳过)。``.cls`` 不收:
#: 类文件在 ``\documentclass`` 内执行, 其错必在缝前, 缝顶 ``\let`` 鞭长莫及。
_CTLSEQ_ERRFILE_RE = re.compile(
    r"^[ \t]*(\S+?\.(?:sty|def|cfg|clo|ltx)):[0-9]+:", re.IGNORECASE
)

#: 注入 CJK 块装载树的文件名头表 —— 错误文件落此才证第二定义者在缝位块内
#: (ctex 行 → ctexhook/ctexpatch/fix-cm/everysel/xeCJK → fontspec/zhnumber
#: 链; xecjk 模 fallback 块同树)。fontspec 恒在注入块装载树 (ctex/xeCJK
#: 双模都经其装载) → 其 ``\cs_new`` 撞名的第二定义者必在缝位。
_CTLSEQ_FILE_HEADS = (
    "ctex",
    "xecjk",
    "zhnum",
    "zhlineskip",
    "everysel",
    "fix-cm",
    "cjkfntef",
    "cjkulem",
    "fandol",
    "fontspec",
)

#: texlate 注入 CJK 块在档校验标记 (inject_cjk 只往 docclass 缝位写) ——
#: 缝顶 ``\let`` 只在注入块贴身缝位时保证第一定义者 ∈ cls 链 (块前零用户
#: preamble 行执行); 无标记 = 用户自备 ctex/未注入, 撞名机制不在本格。
_CJK_SEAM_MARKS = ("% [texlate injected]", "% texlate: CJK via xeCJK")

#: 清位禁区名表 —— ``Control sequence`` 签下 ``end*`` 形名义上可清
#: (``\cs_if_exist`` 无 ``\@qend`` 名拒, 与 ``\@ifdefinable`` 不同),
#: 但原语/内核命令被 ``\let\@undefined`` 即全局灾难, 与寄存器护栏并施。
_CTLSEQ_RESERVED = frozenset(
    {
        "relax",
        "end",
        "begin",
        "par",
        "input",
        "include",
        "endinput",
        "csname",
        "endcsname",
        "expandafter",
        "noexpand",
        "def",
        "gdef",
        "edef",
        "xdef",
        "let",
        "newcommand",
        "renewcommand",
        "providecommand",
        "newenvironment",
        "renewenvironment",
        "newtheorem",
        "documentclass",
        "documentstyle",
        "usepackage",
        "RequirePackage",
        "hbox",
        "vbox",
        "vtop",
        "vcenter",
        "font",
        "nullfont",
        "fi",
        "else",
        "or",
        "ifx",
        "ifnum",
        "ifdim",
        "ifcase",
        "ifeof",
        "iftrue",
        "iffalse",
        "ifmmode",
        "ifhmode",
        "ifvmode",
        "ifinner",
        "ifvoid",
        "ifhbox",
        "ifvbox",
        "ifcat",
        "ifdefined",
        "ifcsname",
        "ifpdf",
        "ifincsname",
        "iffontchar",
    }
    | set(PDFTEX_PRIMS)
)


def _ctlseq_collided(blob: str, heads: tuple[str, ...]) -> tuple[set[str], set[str]]:
    r"""逐行扫 ``Control sequence`` 撞名 → (CJK 块内撞名集, 肇事文件基名集)。

    双重定界: 签名行须带 ``file:N:`` 前缀 (非 file-line-error 形不定界
    不收), 且文件基名 ∈ 注入 CJK 块装载树头表 —— 非族文件的同名撞名
    (包间互撞) 不连坐。
    """
    names: set[str] = set()
    files: set[str] = set()
    for line in blob.splitlines():
        cm = _CTLSEQ_DEF_RE.search(line)
        if cm is None:
            continue
        fm = _CTLSEQ_ERRFILE_RE.match(line)
        if fm is None:
            continue  # 无 file:line 前缀不定界 —— 该名不收
        base = fm.group(1).rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        if base.startswith(heads):
            names.add(cm.group(1))
            files.add(base)
    return names, files


def ctlseq_undefine(  # noqa: PLR0911 - 逐门 decline 注释即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Control sequence \X already defined`` → docclass 缝顶 ``\let\X\@undefined``。

    expl3 ``\cs_new`` 系撞名格, 与 ``undefine_for_redef`` 同教义 (清先定义
    位让后定义者赢) 但分域更窄: 只收 file-line-error 行文件头落在注入
    CJK 块装载树 (``_CTLSEQ_FILE_HEADS``) 内的撞名 —— 该约束同时保证
    第一定义者 ∈ ``\documentclass`` cls 链 (注入块贴身缝位, 块前零用户
    preamble 行), 缝顶 ``\let`` 序位正确 (cls 先定义已跑, ctex 后定义
    未跑)。非 CJK 块文件的 ``Control sequence`` 撞名 (包间互撞/包内
    互撞) 一律不碰 —— 缝顶清位对它们是错序白烧。

    撞名集扫描面 = err_head ∪ 本轮编译 log (``_fixloop_log``): halt_on_
    error 只见首错, best_effort 探针 log 内同文件簇连撞一轮批清。
    护栏: 纯字母名 (签名邻接天然排 ``_``/``@`` 内码) ∩ ``_allocated_
    cs_names`` 寄存器/盒型分配名 ∩ ``_CTLSEQ_RESERVED`` 原语名三滤;
    ``params.file_heads`` 可覆写文件头表。
    """
    del eng, payload
    heads = tuple(
        str(h).lower() for h in (params.get("file_heads") or _CTLSEQ_FILE_HEADS)
    )
    blob = (ctx.err_head or "") + "\n" + _fixloop_log(ctx)
    names, files = _ctlseq_collided(blob, heads)
    if not names:
        return False, "no Control-sequence collision in CJK-block files"
    names -= _allocated_cs_names(mask_tex(ctx.source_blob()))
    names -= _CTLSEQ_RESERVED
    if not names:
        return False, "all collided cs are allocated/reserved names — abstain"
    main = ctx.main_path()
    main_t = (ctx.read(main) or "") if main is not None else ""
    if not any(m in main_t for m in _CJK_SEAM_MARKS):
        return False, "no texlate CJK block at docclass seam"
    if not find_docclass_ends(main_t):
        return False, "no docclass seam"  # 退文件头 = cls 前清位, 错序
    fresh = [
        n
        for n in sorted(names)
        if f"\\let\\{n}\\@undefined" not in main_t
        and f"\\csname {n}\\endcsname" not in main_t
    ]
    if not fresh:
        return False, "all offenders already cleared"
    block = "% fixloop: ctlseq undefine before CJK block\n" + "\n".join(
        _undefine_cs(n) for n in fresh
    )
    if not _inject_after_docclass(ctx, block):
        return False, "docclass seam injection failed"
    return True, f"seam-clear {', '.join(fresh)} (files: {', '.join(sorted(files))})"


# ═══ pdfstring 字母常量扫描肇事 cs 空降格 (W165, 2607.10569) ═══

#: ``Improper alphabetic constant`` 行后紧随的 ``<to be read again>``
#: 展示行给出肇事 token——pdfstring/书签域 `` `\cs `` 字母常量扫描只炸
#: 多字符 cs (`` `\x `` 单字符是合法字母常量形, TeX 不报)。
_ALPHA_BAD_CS_RE = re.compile(
    r"Improper alphabetic constant\.\s*\n<to be read again>\s*\n? *(\\[A-Za-z@]+)"
)


def pdfstring_cs_disarm(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""`` `\cs `` pdfstring 字母常量扫描炸 → 肇事 cs 书签域 ``\def`` 空降格。

    触发面: ``$\\times$``/``$\\pdo$`` 类数学进 ``\title``/``\section``/
    ``\author`` 等 moving-arg——hyperref ``\pdfstringdef`` 展开书签时
    `` `\cs `` 扫描撞多字符 cs + intcalc 级联 (acmart+hyperref+xelatex
    上游脆面, 与类无关; tmp/lane-pdo 最小复现 ``$\times$`` in ``\title``)。
    上游文档化逃生舱 ``\pdfstringdefDisableCommands`` 只动书签域——
    正文排版零接触, 比 ``\texorpdfstring`` 逐处包源干净一个量级;
    ``\def\cs{}`` 空降格顺带消掉 "removing `\cs'" 警告 (cs 在展开期
    已消失)。注入走 docclass 缝+``\ifdefined`` 双闸: hyperref 缺席稿
    整件死文本不炸。
    """
    del eng, payload, params
    blob = (ctx.err_head or "") + "\n" + _fixloop_log(ctx)
    names = sorted(
        {
            n
            for n in _ALPHA_BAD_CS_RE.findall(blob)
            if len(n) > 2  # noqa: PLR2004 - 2 = 反斜杠+单字符合法形 (\x) 滤界
        }
    )
    if not names:
        return False, "no multi-char cs behind Improper alphabetic constant"
    main = ctx.main_path()
    if main is None:
        return False, "no main file"
    t = ctx.read(main) or ""
    todo = [n for n in names if f"\\def{n}{{}}" not in t]
    if not todo:
        return False, "offenders already disarmed"
    defs = "".join(f"\\def{n}{{}}" for n in todo)
    snippet = (
        "\\ifdefined\\pdfstringdefDisableCommands\n"
        f"  \\pdfstringdefDisableCommands{{{defs}}}\n"
        "\\fi"
    )
    if not _inject_after_docclass(ctx, snippet):
        nt = t.replace("\\begin{document}", snippet + "\n\\begin{document}", 1)
        if nt == t:
            return False, "no injection point"
        ctx.write(main, nt)
    return True, f"pdfstring-disarm {', '.join(todo)}"


# ═══ phantom Incomplete \if — 脆弱前稿 cs 族 eTeX \protected 重定义 (B05 姊妹臂) ═══

#: 展开态 phantom 链的宿主面: frontmatter/moving-arg 里常被 ``\edef``/
#: ``\xdef``/``\MakeUppercase``/``\pdfstringdef`` 展开的 cs——``\footnote``/
#: ``\thanks`` (amsproc ``\shortauthors`` → ``\markboth`` edef 实证) +
#: 2.09 字体声明 ``\bf\it\rm\sf\tt\sc\sl`` (myectaart ``\xdef\@argi{#1}``
#: 实证)。保护后其 ``\newif``-setter 替换体里的 ``\if@X\iffalse`` 不再被
#: 执行——未定义名经 ``\ifdefined`` 闸跳过, 不造新坏定义。
_IFPROT_FAMILY: tuple[str, ...] = (
    "footnote",
    "thanks",
    "bf",
    "it",
    "rm",
    "sf",
    "tt",
    "sc",
    "sl",
)

#: 字面扫描器已跑过的凭据: ``unclosed_if_close`` (order 196) 的 run_tool
#: note 固定带 ``ifclose:`` 判词 (``noop``/``injected`` 皆证"本轮已查字面
#: 平衡")。该凭据缺席 = 扫描器 cond-skip (python3 缺位) 或 order 未达——
#: 字面亏格可能悬着, 本规则的 ``\protected`` 域不含它, 保守不收。
_IFPROT_SCANNER_RULE = "unclosed_if_close"


def if_phantom_protect(  # noqa: PLR0911 - 逐门 decline 即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Phantom ``Incomplete \if`` → 脆弱前稿 cs 族 ``\protected`` let-wrap 重定义。

    phantom 机制: ``\let\if@X\iffalse`` 形 ``\newif``-setter 的替换体含活
    conditional——``\edef``/``\xdef`` 展开扫描里 ``\let`` 惰性但 ``\if@X``
    (=\iffalse) 执行 → 假 open 吞 token 到 EOF。源件字面平衡 → 196 号
    字面扫描器 noop (applied 烧 dedup 位后下轮才轮到本规则)。eTeX
    ``\protected`` 属性钉在 cs 自身, 不受 ``\let\protect\relax`` 剥除影响
    (``\DeclareRobustCommand`` 的死穴) → 被护 cs 在 edef 扫描内整体带过,
    setter 链根本走不到。正文体正常展开域里 wrapper 逐跳还原旧义, 语义
    零变化 (min8 ``\protected\def\footnote`` / t2 ``\bf`` 双臂已实证出 PDF)。

    注入 ``\AtBeginDocument`` 块 (docclass 缝): 全 preamble+包重定义
    (hyperref 改 ``\footnote`` 等) 跑完才护, 不被反超; ``\maketitle`` 内
    edef 触发时保护已就位。逐 cs ``\ifdefined`` 闸。
    """
    del eng, payload
    fam = tuple(str(c).lstrip("\\") for c in (params.get("cs") or _IFPROT_FAMILY))
    if not fam:
        return False, "empty cs family"
    seen = None
    for a in ctx.actions:
        if a.get("rule") == _IFPROT_SCANNER_RULE and "ifclose:" in str(a.get("detail")):
            seen = str(a.get("detail"))  # 最新一轮判词为准
    if seen is None:
        return False, "literal if-scanner verdict not on ledger — abstain"
    m = re.search(r"phantom=(\d+)", seen)
    if m is not None and int(m.group(1)) > 0:
        # 跳读形嫌疑在场 (\let operand/名位/def 参位内 \if-token + 活条件
        # 帧) —— \protected 域不含此机制, 注了修不到 → abstain。
        return (
            False,
            f"skip-phantom suspects on ledger (phantom={m.group(1)}) — abstain",
        )
    main = ctx.main_path()
    if main is None:
        return False, "no main file"
    # 退文件头 = cls 加载前, \AtBeginDocument 未定义 → 必须有 docclass 缝
    if not find_docclass_ends(ctx.read(main) or ""):
        return False, "no docclass seam"
    lines = "".join(
        f"\\ifdefined\\{n}\\let\\TXLorig{n}\\{n}"
        f"\\protected\\def\\{n}{{\\TXLorig{n}}}\\fi\n"
        for n in fam
    )
    snippet = (
        "% fixloop: phantom Incomplete \\if — \\protected frontmatter cs\n"
        "\\AtBeginDocument{%\n" + lines + "}"
    )
    if not _inject_after_docclass(ctx, snippet):
        return False, "protected re-defs already injected"
    return True, f"protected {len(fam)} frontmatter cs ({', '.join(fam)})"


# ═══ premature provider-cs: Missing \begin{document} @件装载补供格 (2009.11053) ═══

#: file:line 形 ``Missing \begin{document}`` —— ``path/<file>.<ext>:N:``
#: 前缀给出肇事执行文件 (随源 .sty 常见), ``l.N`` 上下文行给出肇事 cs。
_MBD_ERR_RE = re.compile(
    r"^[ \t]*\S*?([\w.+-]+)\.(sty|cls|tex|def|clo):\d+:"
    r"\s*LaTeX Error:\s*Missing \\begin\{document\}",
    re.MULTILINE,
)
#: ``l.N`` 上下文行 —— TeX 行内截到炸点, 最后一个 cs 即肇事者。
_L_CTX_LINE_RE = re.compile(r"(?m)^l\.\d+[^\n]*")
_L_CTX_CS_RE = re.compile(r"\\([A-Za-z@]+)")

#: 肇事 cs → 供方包 (``params.cs_pkg`` 可扩) —— 供方先装载即真 def
#: 就位; gobble/空 polyfill 会静默吞掉计数器重编号语义, 只收真实供方。
_PREMATURE_CS_PKG: dict[str, str] = {
    # 2009.11053: mystyle.sty:33 \numberwithin —— amsmath 在 ms.tex:48
    # 逗号列才装, 供方晚于消费方 → 前置到 \usepackage{mystyle} 前。
    "numberwithin": "amsmath",
}


def _mbd_pairs(blob: str) -> list[tuple[str, str, str]]:
    r"""``Missing \begin{document}`` 行与 ``l.N`` 上下文配对 → [(肇事茎, 扩展名, cs)]。

    错误行后首个 ``l.N`` 行即本错上下文 (TeX 序: 错误行→help→l.行);
    行内最后一个 cs 是炸点肇事者 (左到右执行序)。
    """
    out = []
    for em in _MBD_ERR_RE.finditer(blob):
        lm = _L_CTX_LINE_RE.search(blob, em.end())
        if lm is None:
            continue
        css = _L_CTX_CS_RE.findall(lm.group(0))
        if not css:
            continue
        out.append((em.group(1), em.group(2), css[-1]))
    return out


def premature_cs_guard(  # noqa: C901, PLR0912, PLR0915 - 双臂逐站分派 + seen 幂等, 逐门 decline 即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Missing \begin{document}`` @件装载 → 供方包前置到消费方装载点。

    触发面: 随源 .sty 在装载期调 ``\numberwithin`` 类排版 cs, 而供方包
    (amsmath) 由更靠后的 ``\usepackage`` 行才装 —— kernel 对 preamble
    期排版动作报 ``Missing \begin{document}`` (级联签, syntax 类)。
    修 = 供方 ``\usepackage`` 前置到肇事 sty 的每个 live 用户件装载点
    之前 (供方先跑, 消费方整件覆盖, 真 def 语义无损 —— 非 gobble);
    同文件内已先装供方的站跳过 (含上轮自注行, 天然幂等)。肇事文件是
    .tex (main/``\input`` 件) 无 usepackage 锚点 → docclass 缝顶补供方
    (先于一切 preamble 行); 肇事 ``.cls``/``.def``/``.clo`` 系 cls/包
    内传递装载, 缝位对 cls 执行期鞭长莫及 → abstain 交下位。
    """
    del payload
    table = dict(_PREMATURE_CS_PKG)
    table.update(params.get("cs_pkg") or {})
    stem_provs: dict[str, set[str]] = {}
    seam_provs: set[str] = set()
    blob = (ctx.err_head or "") + "\n" + _fixloop_log(ctx)
    for stem, ext, cs in _mbd_pairs(blob):
        prov = table.get(cs)
        if prov is None:
            continue  # 表外肇事 cs —— 供方不可考, 不收
        if ext == "tex":
            seam_provs.add(prov)
        elif ext == "sty":
            stem_provs.setdefault(stem.lower(), set()).add(prov)
        # cls/def/clo 系传递装载无用户件锚点 —— abstain
    if not stem_provs and not seam_provs:
        return False, "no premature-cs pair in Missing-\\begin{document} error"

    done: list[str] = []
    n_sites = 0
    if stem_provs:
        for f in ctx.tex_files((".tex", ".sty", ".cls")):
            t = ctx.read(f)
            if not t:
                continue
            masked = mask_tex(t)
            seen: set[str] = set()
            out: list[str] = []
            prev = 0
            for m in _LOAD_SITE_RE.finditer(masked):
                if masked[m.start() : m.end()] != t[m.start() : m.end()]:
                    continue  # 死区装载点
                elems = {e.strip().lower() for e in m.group(1).split(",") if e.strip()}
                provs = sorted(
                    {
                        p
                        for stem, ps in stem_provs.items()
                        if stem in elems
                        for p in ps
                        if p not in seen
                    }
                )
                seen.update(elems)  # 本文件先装供方 → 后站免前置 (幂等)
                if not provs:
                    continue
                ins = "".join(
                    f"\\usepackage{{{p}}} % fixloop: premature provider\n"
                    for p in provs
                )
                out.append(t[prev : m.start()])
                out.append(ins)
                prev = m.start()
                seen.update(provs)
                n_sites += 1
            if out:
                out.append(t[prev:])
                ctx.write(f, "".join(out))
    if n_sites:
        done.append(f"provider prepend at {n_sites} load site(s)")

    if seam_provs:
        main = ctx.main_path()
        main_t = (ctx.read(main) or "") if main is not None else ""
        masked_main = mask_tex(main_t)
        loaded = {
            e.strip().lower()
            for m in _LOAD_SITE_RE.finditer(masked_main)
            if masked_main[m.start() : m.end()] == main_t[m.start() : m.end()]
            for e in m.group(1).split(",")
            if e.strip()
        }
        todo = sorted(p for p in seam_provs if p not in loaded)
        if todo and _inject_after_docclass(
            ctx,
            "\n".join(
                f"\\RequirePackage{{{p}}} % fixloop: premature provider" for p in todo
            ),
        ):
            done.append(f"docclass-seam provider {', '.join(todo)}")

    if not done:
        return False, "no reachable consumer load site — abstain"
    provs = sorted({p for ps in stem_provs.values() for p in ps} | seam_provs)
    missing = [
        p
        for p in provs
        if not (eng.probe_file(f"{p}.sty") or eng.install_file(f"{p}.sty"))
    ]
    if missing:
        done.append(f"WARNING: {', '.join(missing)}.sty not found")
    return True, "; ".join(done)


# ═══ doc-latent @-def 站 exact-restore 包裹格 (spacefactor lane, 1206.0445) ═══

#: ``@``=catcode-12 宿主下 ``\@cs`` 断名成 ``\@``+裸字母 —— ``\@`` 即
#: ``\spacefactor\@m`` 间距宏, 展开点执行 → ``You can't use '\spacefactor'
#: in vertical mode`` / ``in math mode`` / ``Improper \spacefactor`` /
#: ``Package calc Error: '\spacefactor' invalid`` 四头 (全落 other 类)。
#: def 域内 ``\\[A-Za-z]*@[A-Za-z]`` 即肇事形 (``\l@section``/``\@secpenalty``
#: /``\hb@xt@``/``\c@footnote``); 裸 ``\@ `` (句读间距宏) 不带后继字母, 不中。
_AT_TOKEN_RE = re.compile(r"\\[A-Za-z]*@[A-Za-z]")

#: ambient @ 事件 —— ``\makeatletter``/``\makeatother``/``\catcode`@=N``/
#: ``\catcode 64=N``/``\catcode"40=N``/``\catcode'100=N``; 本族 restore cs
#: (``_AT_LETTER_*`` 与 pkgload ``_SHIP_WRAP_*`` 的复元符) 只裹非 letter 站,
#: 复元值恒为 other —— 走查直接建模。
_ATDEF_EVENT_RE = re.compile(
    r"\\makeat(letter|other)(?![A-Za-z])"
    r"|\\catcode\s*(?:`@|64|\"40|'100)\s*=\s*(\d+)"
    r"|\\TeXlate(?:At|StyIn)Restore(?![A-Za-z])"
)

#: def 命令面 —— 名+参+体跨域收 ``\@`` 站: ``\renewcommand*\l@section`` 名断
#: (体随文执行) 与 ``\newcommand\foo{...\@x...}`` 体断同修; ``\def`` 族
#: (``\long``/``\outer``/``\global``/``\protected`` 前缀任序) 走参数文本
#: 扫描, 其余走 ``[opt]``/``{grp}`` 贪婪组列。``\let``/``\newif`` 无体
#: def 不收 (断名产裸字母非 ``\@``)。
_ATDEF_CMD_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand"
    r"|NewDocumentCommand|DeclareDocumentCommand|RenewDocumentCommand"
    r"|ProvideDocumentCommand|newenvironment|renewenvironment|newtheorem"
    r"|newfont|newmathalphabet|NewMathAlphabet|DeclareMathAlphabet"
    r"|DeclareMathOperator|DeclareMathSymbol|DeclareMathDelimiter"
    r"|DeclareMathAccent|DeclareMathRadical)(?![A-Za-z])"
    r"|(?:\\(?:long|outer|global|protected)(?![A-Za-z])[ \t]*)*"
    r"\\(?:gdef|edef|xdef|def)(?![A-Za-z])"
)

#: ``\def`` 参数文本窗上限 —— 无 ``{`` 体 (残缺稿) 按名末截域, 不吞全文。
_DEF_PARAM_MAX = 64

#: ``\csname`` 形 def 名的随尾 ``\endcsname`` —— ``_def_extent`` 名位专用。
_ENDCSNAME_RE = re.compile(r"\\endcsname(?![A-Za-z])")


def _skip_ws(vis: str, pos: int) -> int:
    while pos < len(vis) and vis[pos] in " \t":
        pos += 1
    return pos


def _brace_end(vis: str, pos: int) -> int:
    r"""``vis[pos]=='{'`` → 配对 ``}`` 后 offset; 未配对 → ``len(vis)``。"""
    depth, j = 1, pos + 1
    while j < len(vis) and depth:
        c = vis[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        j += 1
    return j


def _cs_end(vis: str, pos: int) -> int:
    r"""``vis[pos]=='\\'`` → cs 名末 offset (字母+``@`` 连读; 单字符 cs 收一)。"""
    j = pos + 1
    if j < len(vis) and (vis[j].isalpha() or vis[j] == "@"):
        while j < len(vis) and (vis[j].isalpha() or vis[j] == "@"):
            j += 1
        return j
    return j + 1


def _def_extent(vis: str, pos: int, is_def: bool) -> int:
    r"""def 域末 offset: 可选 ``*`` → 名 (``{grp}``/``\cs``) → 参/体组列。

    ``\def`` 族: 参数文本跑到首个 ``{`` (``\{`` 转义不算) 再收一组即停
    (单体形); 参数文本超 ``_DEF_PARAM_MAX``/遇 ``\n\n``/无 ``{`` → 按名末
    截域。其余族: ``[opt]``/``{grp}`` 贪婪连收 (``\newenvironment`` 的
    beg/end 双组, ``\newtheorem`` 的 within opt 同形)。``\csname`` 名
    (``\renewcommand\csname l@section\endcsname``) 吞到 ``\endcsname``
    再续组列 —— 名本体免疫 catcode 但 ``{体}`` 内 ``\@`` 仍断名。
    """
    n = len(vis)
    pos = _skip_ws(vis, pos)
    if pos < n and vis[pos] == "*":
        pos = _skip_ws(vis, pos + 1)
    if pos < n and vis[pos] == "{":
        pos = _brace_end(vis, pos)
    elif pos < n and vis[pos] == "\\":
        if vis.startswith("\\csname", pos) and (
            pos + 7 >= n or not vis[pos + 7].isalpha()
        ):
            m = _ENDCSNAME_RE.search(vis, pos + 7)
            pos = n if m is None else m.end()
        else:
            pos = _cs_end(vis, pos)
    pos = _skip_ws(vis, pos)
    if is_def:
        j = pos
        while j < n and vis[j] != "{":
            if vis[j] == "\\":
                j += 2
                continue
            if vis[j : j + 2] == "\n\n":
                return pos
            j += 1
        if j >= n or j - pos > _DEF_PARAM_MAX:
            return pos
        return _brace_end(vis, j)
    while pos < n:
        if vis[pos] == "[":
            k = vis.find("]", pos + 1)
            pos = _skip_ws(vis, n if k < 0 else k + 1)
        elif vis[pos] == "{":
            pos = _skip_ws(vis, _brace_end(vis, pos))
        else:
            break
    return pos


def _atdef_sites(vis: str) -> list[tuple[int, int, bool]]:
    r"""遮盖视图走查 def 站 → ``[(start, extent_end, at_letter)]``。

    ``\makeatletter``/``\makeatother``/``\catcode`` 事件按组局部语义入栈 —
    — ``{`` 推现值 ``}`` 复元 (bare 组内事件读侧执行, 组末自动回); def 域
    整体跳过 (替换体在读侧惰性 —— 体内 ``\makeatletter`` 是调用期 token,
    不影响后续顶读的 ambient; 域内站点由外层站的包裹一并罩住)。
    """
    sites: list[tuple[int, int, bool]] = []
    at_letter = False
    stack: list[bool] = []
    pos, n = 0, len(vis)
    while pos < n:
        c = vis[pos]
        if c == "\\":
            ev = _ATDEF_EVENT_RE.match(vis, pos)
            if ev is not None:
                if ev.group(1) is not None:
                    at_letter = ev.group(1) == "letter"
                elif ev.group(2) is not None:
                    at_letter = ev.group(2) == "11"
                else:  # 本族 restore cs —— 只裹非 letter 站, 复元恒 other
                    at_letter = False
                pos = ev.end()
                continue
            d = _ATDEF_CMD_RE.match(vis, pos)
            if d is not None:
                end = _def_extent(vis, d.end(), d.group(0).rstrip().endswith("def"))
                sites.append((pos, end, at_letter))
                pos = end
                continue
            pos += 2
            continue
        if c == "{":
            stack.append(at_letter)
            pos += 1
            continue
        if c == "}":
            if stack:
                at_letter = stack.pop()
            pos += 1
            continue
        pos += 1
    return sites


def spacefactor_atdef_wrap(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""doc-latent @-def 站 exact-restore @=11 包裹 → ``\@cs`` 断名根修。

    2.09-era 稿把 cls 内码抄进 preamble def 体而无 ``\makeatletter``:
    ``\renewcommand*\l@section[2]{...\addpenalty\@secpenalty...\hb@xt@...}``
    (1206.0445 :399-412), ``\newcommand\makepapertitle{...\renewcommand
    \thefootnote{\@fnsymbol\c@footnote}...\@thanks}`` (0905.0664) —— 体在
    @=12 下 tokenize → ``\@cs`` 断名成 ``\@``+裸字母 → def 站行或调用点
    ``\@`` 执行 → ``\spacefactor`` vmode/math/Improper/calc 四头。

    包裹取 svglov3.clo exact-restore idiom (``_AT_LETTER_PRE``/``_POST``):
    ``\edef`` 存 ``\catcode 64`` 现值 → ``=11`` 读域 → 复元 —— ``\input``
    跨界件宿主 ambient 不可测时恒等安全, 裸 ``\makeatletter`` 对会把
    letter 宿主尾段强翻回 12 (1803.02902 ``\widebar`` 实证)。dedup 键
    ``{rule}:None`` 全族共位 → 单轮全文件集扫净; 复跑时自注的
    ``\catcode 64=11`` 事件使域内站点天然 at_letter 跳过 (幂等)。
    ``params.exts`` 可覆写扫描面 (缺省 ``.tex`` —— ``.sty``/``.cls`` 装载
    期 @ 本即 letter)。
    """
    del eng, payload
    head = ctx.err_head or ""
    log = _fixloop_log(ctx)
    gate = params.get("gate_terms", ("spacefactor",))
    if gate and not any(t in head or t in log for t in gate):
        return False, f"no gate signature ({'|'.join(gate)})"
    exts = tuple(params.get("exts") or (".tex",))
    changed: list[str] = []
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or "@" not in t:
            continue
        vis = mask_tex(t)
        edits = [
            (s, e)
            for s, e, al in _atdef_sites(vis)
            if not al and _AT_TOKEN_RE.search(vis[s:e])
        ]
        if not edits:
            continue
        out = t
        for s, e in reversed(edits):
            out = out[:s] + _AT_LETTER_PRE + out[s:e] + _AT_LETTER_POST + out[e:]
        if out != t:
            ctx.write(f, out)
            changed.append(f"{f.name}(x{len(edits)})")
    return (bool(changed)), f"@def exact-restore wrap in {', '.join(changed)}"


# ═══ \def\X<lit> 字面尾译文蚀除 → 逐站补回 (csdelim lane, 5 cells) ═══

#: TeX 错误头 ``Use of \X doesn't match its definition.`` —— X 是 def 时
#: 带字面参数文本的 cs。``\S+?`` 懒惰: 词型 (``\ch``) 收满字母段,
#: 符型 (``\0``/``\~``) 收单字符。
_MISMATCH_ERR_RE = re.compile(r"Use of \\(\S+?) doesn't match its definition")

#: ``\def`` 族的 cs 名 + 字面参数尾 —— 前缀 ``\long``/``\outer``/
#: ``\protected``/``\global`` 可叠, 本体 ``[egx]def``。尾 = ``{``/换行前的
#: 原文: ``\def\c3h2{`` → ``3h2``; ``\def\b {`` → 空 (裸参宏); ``\def\a#1{``
#: → ``#1`` 含 ``#`` 即真参宏, 不收。``\``/``{``/``}`` 入尾同理不收。
_DEF_TAIL_RE = re.compile(
    r"(?:\\(?:long|outer|protected|global)\s*)*"
    r"\\[egx]?def\s*"
    r"\\([A-Za-z@]+|[^A-Za-z\s])"
    r"([^\n{]*)"
)

#: 词型 cs 后的空白吸收 —— TeX 在 control word 后跳过 space token 序列
#: (``\n`` 亦按一 space 计); 符型 cs 不吸收 (``\0 `` 的空格进正文)。
_DELIM_SKIP_RE = re.compile(r"[ \t]*(?:\n[ \t]*)?")

#: 字面尾不可含的字符 —— ``#`` 真参 / ``\`` cs / ``{}`` 定界, 皆出机制面。
_TAIL_BAD_RE = re.compile(r"[#\\{}]")


def _tail_align(vis: str, pos: int, rest: str) -> tuple[int, int, int]:
    r"""``rest`` 在 ``vis[pos:]`` 上的乱序对齐 → (consumed, end, junk)。

    逐字符扫: 命中 ``rest[i]`` 前进; 非 ASCII 字 (译文残骸) 跳过记 junk;
    ASCII 未命中时仅在 junk 已见 (有蚀除证据) 时前视 ``rest`` 后段 ——
    蚀除吃掉的是居间 tail 字。``end`` = 最后一枚命中字符的后界。
    """
    i = 0
    q = pos
    last = pos
    junk = 0
    seen = False
    n = len(vis)
    while q < n and i < len(rest):
        c = vis[q]
        if c == rest[i]:
            i += 1
            q += 1
            last = q
            seen = False
        elif not c.isascii():
            q += 1
            junk += 1
            seen = True
        elif seen:
            nxt = rest.find(c, i)
            if nxt < 0:
                break
            i = nxt + 1
            q += 1
            last = q
            seen = False
        else:
            break
    return i, last, junk


def _delim_sites(  # noqa: C901 - 逐站证据分派, 每门即归因
    vis: str,
    site_rx: re.Pattern[str],
    tail_pos: list[tuple[int, str | None]],
    global_tail: str | None,
    *,
    letter_cs: bool,
) -> list[tuple[int, int, str]]:
    """单文件内某 cs 的蚀除站 → [(start, end, replacement)] 编辑面。

    有效尾 = 站点前最近的本文件 def 尾; 本文件无此 cs 的 def 时回落
    全局唯一尾 (def 在他件的 preamble 装载序)。def 在站点之后 = 该站
    沿用更早定义 (上游本就不同的语义) → 不收; 全局多尾歧义 → 不收。
    全对齐 → REPLACE 损毁域为尾 (junk 夹在两枚幸存尾字间 = 必为蚀除);
    部分对齐/零对齐 + 蚀除证据 (junk>0 或已消费>0) → 已配前缀后 INSERT
    残余尾 (零内容损失); 无证据 → 上游本就断裂, 不动。
    """
    edits: list[tuple[int, int, str]] = []
    n = len(vis)
    for m in site_rx.finditer(vis):
        pos = m.start()
        eff: str | None = None
        later_def = False
        for dp, dt in tail_pos:
            if dp < pos:
                eff = dt
            else:
                later_def = True
                break
        if later_def and eff is None:
            continue  # 站先于本文件一切 def —— 上游语义不可考
        if not tail_pos:
            eff = global_tail
        if not eff:
            continue
        j = m.end()
        if letter_cs:
            sm = _DELIM_SKIP_RE.match(vis, j)
            j = sm.end() if sm else j
        k = 0
        while k < len(eff) and j + k < n and vis[j + k] == eff[k]:
            k += 1
        if k == len(eff):
            continue  # 字面尾完好 (含 def 行自身)
        i, last, junk = _tail_align(vis, j + k, eff[k:])
        if i == len(eff) - k:
            edits.append((j, last, eff))
        elif junk > 0 or i > 0:
            edits.append((j + k, j + k, eff[k:]))
    return edits


def cs_delim_tail_fix(  # noqa: C901, PLR0912 - def 扫面 × 逐 cs 分派, 每门即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Use of \X doesn't match its definition`` → ``\def\X<lit>`` 字面尾补回。

    机制 (5 cells 同族): 作者用 ``\def\c3h2{...}``/``\def\b0bmode{...}``/
    ``\def\0cc{...}``/``\def\ch3oh{...}`` 造伪多名宏 —— TeX 解为 cs +
    字面参数文本, 上游一切调用点 ``\X<lit>`` 合法; 译者把尾中字母段当
    正文吃掉 (``\c3h2`` → ``\c3这是译文2``, ``\ch3oh`` → ``\ch3这是译文…``)
    → 调用点不再带全尾 → def-match 断。修 = 站点字面尾补回:
    蚀除域可证 (乱序对齐全命中) 时整域还原, 部分证据时插缺 (零删字)。
    多 def 取站点前最近者 (``\def\b``→``\def\b0bmode`` 重定义序,
    hep-ex/0408083 实证); def 在 .sty/.cls 时跨文件全局唯一尾回落
    (astro-ph/0408446 ``0343.sty`` 实证) —— 同侪 .tex 的装载序不可考,
    错补到沿用前义的站会静默改内容, 回落只信非 .tex def。包内
    delimited 宏 (工程外 def 不可见) 无尾可查 → abstain。
    """
    del eng, payload
    blob = (ctx.err_head or "") + "\n" + _fixloop_log(ctx)
    names: list[str] = []
    for m in _MISMATCH_ERR_RE.finditer(blob):
        if m.group(1) not in names:
            names.append(m.group(1))
    if not names:
        return False, "no cs in Use-of-doesn't-match error"

    exts = tuple(
        params.get("exts")
        or (".tex", ".sty", ".cls", ".def", ".clo", ".bbl", ".inc", ".cfg")
    )
    files = ctx.tex_files(exts)
    views: dict[Any, tuple[str, str]] = {}
    defs: dict[str, dict[Any, list[tuple[int, str | None]]]] = {}
    tails: dict[str, set[str]] = {}
    nontex_def: set[str] = set()
    for f in files:
        t = ctx.read(f)
        if t is None:
            continue
        vis = mask_tex(t)
        views[f] = (t, vis)
        for dm in _DEF_TAIL_RE.finditer(vis):
            cs = dm.group(1)
            if cs not in names:
                continue
            tail = dm.group(2).strip()
            entry: str | None = None
            if tail and not _TAIL_BAD_RE.search(tail):
                entry = tail
            defs.setdefault(cs, {}).setdefault(f, []).append((dm.start(), entry))
            if entry:
                tails.setdefault(cs, set()).add(entry)
            if f.suffix.lower() != ".tex":
                nontex_def.add(cs)

    changed: list[str] = []
    for cs in names:
        per_file = defs.get(cs, {})
        cst = tails.get(cs, set())
        global_tail = next(iter(cst)) if len(cst) == 1 and cs in nontex_def else None
        letter_cs = cs[:1].isalpha() or cs[:1] == "@"
        site_rx = re.compile(
            r"(?<!\\)\\" + re.escape(cs) + (r"(?![A-Za-z@])" if letter_cs else "")
        )
        for f, (t, vis) in views.items():
            if site_rx.search(vis) is None:
                continue
            edits = _delim_sites(
                vis, site_rx, per_file.get(f, []), global_tail, letter_cs=letter_cs
            )
            if not edits:
                continue
            out = t
            for s, e, rep in reversed(edits):
                out = out[:s] + rep + out[e:]
            if out != t:
                ctx.write(f, out)
                changed.append(f"{f.name}(\\{cs} x{len(edits)})")
    if not changed:
        return False, "no doc-side delimited def or intact sites only"
    return True, f"delim-tail restore in {', '.join(changed)}"
