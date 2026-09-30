r"""builtins._csfix_table — undefined_cs 定向修复表数据叶 (csfix 拆分)。

biblatex bbl-2.8 ``\sortlist`` 读者 polyfill / crossreftools splitter
修补两大 payload 常量 + ``_CS_FIX_TABLE`` cs→spec 默认表 —— 纯数据,
``_csfix_target`` 运行时查表, rules/ params.cs_table 叠加其上。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


__all__ = [
    "_CRT_CREF_SPLITTER_FIX",
    "_CS_FIX_TABLE",
    "_SORTLIST_BBL_POLYFILL",
]


#: biblatex bbl-2.8 ``\sortlist`` 读者 polyfill —— svjour cls shim bbl 臂
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
