r"""校验域知识件 —— net 检测器簇与共享口径件（validate/xlat/fixloop 跨层宿主）。

消费方在 validate/xlat/fixloop 层，迁往任何一层都会破坏 import 面
（validate 不能 import xlat），故宿于 textutil 底叶，叶间只引
``cjk``/``mask`` 兄弟件不回引 facade：

- net 检测器：``ph_in_cs_net``/``bare_cs_net``/``residual_en_net`` 译文
  缺陷签名件 + ``cs_events_spans`` 单遍扫描件 + ``MATH_CS`` 数学命令表。
- 共享口径件：``JSON_FENCE_RX``（LLM 应答 fence 剥皮）/``PH_RX``/
  ``PH_FUZZY_RX``/``PH_ANY_LIKE_RX``（占位符词法）/``CS_OR_SYM_RX``/
  ``prose_text``/``est_tokens``/``lev_capped``。
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from typing import Final

from .cjk import CJK_RX
from .mask import mask_comments

#: LLM JSON 应答的 ```json fence 剥皮——response_format 在 3003 网关被静默
#: 忽略，模型按习惯包 fence 是常态；剥一层再 json.loads 才算尽力。
#: xlat.pipeline slots 应答与 fixloop llm_hook 共用本口径。
JSON_FENCE_RX: Final = re.compile(
    r"^\s*```[A-Za-z]*\s*\n(?P<body>.*?)\n?\s*```\s*$", re.DOTALL
)


#: 带号占位符 ``[[TYPE_n]]`` 整 token 形（无分组：findall 直接出整 token）。
#: 签发侧词法唯一定义——canonical 面 ``latex.placeholder.PH_RX`` 转口本件；
#: 消费方含 arxiv html 降级链（最底层）与 xlat.placeholders，跨层宿主同
#: ``PH_FUZZY_RX`` 例。
PH_RX: Final = re.compile(r"\[\[[A-Z_]+_\d+\]\]")

#: 模糊占位符候选（zh 侧变体）：完整 ``[[..]]`` / 缺右括号 / 单层 ``[X_n]``
#: / 全角 ``【..】``。各臂 lookahead 要求内部至少一枚 ASCII 字母——纯数字/
#: 纯 CJK 的 ``【1】`` ``【图1】`` ``[[图]]`` 是中文正文的自然全角括号用法，
#: 非占位符变体。L0 ``_check_placeholder`` 与 xlat ``placeholders.diff``
#: 共用本口径（validate 不能 import xlat，单源落本模块）。
PH_FUZZY_RX: Final = re.compile(
    r"\[\[(?=[^\[\]\n]{0,47}[A-Za-z])[^\[\]\n]{1,48}?\]\]"  # [[..]] 完整
    r"|\[\[(?=[^\[\]\n]{0,47}[A-Za-z])[^\[\]\n]{1,48}?\](?!\])"  # [[..] 缺右括号
    r"|(?<!\[)\[[A-Za-z_]+_?-?\d+\](?!\])"  # [X_1] 单层括号
    r"|【(?=[^【】\n]{0,47}[A-Za-z])[^【】\n]{1,48}?】"  # 【..】 CJK 括号
)


_PH_IN_CS_RX: Final = re.compile(r"\\[a-zA-Z@]+\[\[[^\[\]\n]{1,48}?\]\][a-zA-Z@]")


def ph_in_cs_net(src: str, zh: str) -> Counter[str]:
    r"""``\cs名[[..]]字母`` 双侧夹持签名净差（zh 侧多出，Counter 多重集）。

    splice 逐字节替换 ``[[PH]]`` 后 ``\fo[[PH]]o`` → ``\fo<payload>o`` 断
    cs 成未定义命令——挪位缺陷签名（scout-spliceguard 实证）。双侧字母夹持
    必需：``\cs[[PH]]`` 尾邻是合法高频形（corpus 271 处 ``\protect[[REF_n]]``
    系）；``+`` 排除 ``\[[PH]]`` display-math 与 ``\\[[PH]]`` 控制符号。
    注释区 ``mask_comments`` 屏蔽；src 自带同形按多重集差豁免。L0
    ``_check_ph_in_cs`` 与 pipeline ``_intercept_ph_in_cs`` 共用本口径。
    """
    return Counter(_PH_IN_CS_RX.findall(mask_comments(zh))) - Counter(
        _PH_IN_CS_RX.findall(mask_comments(src))
    )


#: 数学模式专用命令（文本域出现即 ``Missing $`` 编译炸弹——realpostfix2
#: 0905.4907 ``\alpha 发射体`` 实证签名）。收录内核 + amsmath/amssymb
#: 高频名；表外新名退化走 L0 ``macro`` 泛 warn 兜底，不静默。
#: 刻意不收双模式名（``\ldots``/``\quad``/``\phantom``/``\ensuremath``
#: 文本域合法）与文本族名（``\dag``/``\S``/``\pounds``/``\eqref``）。
MATH_CS: Final = frozenset(
    """
    alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi
    pi rho sigma tau upsilon phi chi psi omega varepsilon varphi varpi varrho varsigma
    vartheta varkappa digamma Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
    aleph beth daleth gimel hbar hslash imath jmath ell wp Re Im partial nabla
    infty prime emptyset varnothing angle measuredangle sphericalangle triangle triangledown vartriangle square diamond lozenge complement
    backslash forall exists nexists neg lnot top bot flat natural sharp clubsuit diamondsuit heartsuit
    spadesuit mho Finv Game eth Bbbk mathbb mathcal mathfrak mathscr mathbf mathit mathrm mathsf
    mathtt mathnormal boldsymbol bm pmb times div pm mp cdot cdots vdots ddots dotsb
    dotsc dotsi dotsm dotso ldotp cdotp ast star circ bullet oplus ominus otimes oslash
    odot bigodot bigoplus bigotimes cup cap uplus sqcap sqcup setminus smallsetminus amalg wr triangleleft
    triangleright vartriangleleft vartriangleright trianglelefteq trianglerighteq ntriangleleft ntriangleright ntrianglelefteq ntrianglerighteq bigcirc dagger ddagger vee wedge
    barwedge doublebarwedge curlyvee curlywedge lhd rhd unlhd unrhd ltimes rtimes leftthreetimes rightthreetimes divideontimes dotplus
    intercal boxdot boxplus boxminus boxtimes doublecap doublecup Cap Cup veebar circledast circledcirc circleddash circledS
    circledR maltese checkmark land lor leq le geq ge neq ne equiv sim simeq
    approx approxeq asymp cong ncong nsim backsim backsimeq eqsim thicksim thickapprox doteq doteqdot eqcirc
    circeq risingdotseq fallingdotseq triangleq bumpeq Bumpeq iff prec succ preceq succeq preccurlyeq succcurlyeq curlyeqprec
    curlyeqsucc precapprox succapprox precsim succsim precnapprox succnapprox nprec nsucc npreceq nsucceq ll gg llless
    ggless lessapprox gtrapprox lesssim gtrsim lesseqgtr gtreqless lesseqqgtr gtreqqless lessdot gtrdot lessgtr gtrless lneq
    lneqq gneq gneqq leqslant geqslant eqslantless eqslantgtr nleq ngeq nleqslant ngeqslant nleqq ngeqq nless
    ngtr lnsim gnsim lnapprox gnapprox subset supset subseteq supseteq sqsubset sqsupset sqsubseteq sqsupseteq subsetneq
    supsetneq subseteqq supseteqq varsubsetneq varsupsetneq varsubsetneqq varsupsetneqq nsubseteq nsupseteq nsubseteqq nsupseteqq Subset Supset in
    ni notin owns vdash dashv vDash Vdash Vvdash nvdash nvDash nVdash nVDash models perp
    mid nmid parallel nparallel shortmid shortparallel smile smallsmile frown smallfrown bowtie Join propto varpropto
    between pitchfork therefore because multimap implies impliedby to gets mapsto mapsfrom hookrightarrow hookleftarrow rightarrow
    leftarrow Rightarrow Leftarrow leftrightarrow Leftrightarrow nrightarrow nleftarrow nRightarrow nLeftarrow nleftrightarrow nLeftrightarrow rightleftarrows rightrightarrows leftleftarrows
    Lleftarrow Rrightarrow twoheadrightarrow twoheadleftarrow rightarrowtail leftarrowtail looparrowleft looparrowright circlearrowleft circlearrowright curvearrowleft curvearrowright dashrightarrow dashleftarrow
    uparrow downarrow updownarrow Uparrow Downarrow Updownarrow upuparrows downdownarrows upharpoonleft upharpoonright downharpoonleft downharpoonright rightharpoonup rightharpoondown
    leftharpoonup leftharpoondown rightleftharpoons leftrightharpoons nearrow searrow swarrow nwarrow longrightarrow longleftarrow Longrightarrow Longleftarrow longleftrightarrow Longleftrightarrow
    longmapsto rightsquigarrow leadsto xrightarrow xleftarrow arccos arcsin arctan arg cos cosh cot coth csc
    deg det dim exp gcd hom inf injlim ker lg lim liminf limsup ln
    log max min mod pmod bmod pod Pr projlim sec sin sinh sup tan
    tanh varinjlim varliminf varlimsup varprojlim sum prod int iint iiint iiiint oint oiint idotsint
    coprod bigcap bigcup bigvee bigwedge bigsqcup biguplus smallint intop left right middle big bigg
    Big Bigg bigl bigr bigm biggl biggr Bigl Bigr Bigm Biggl Biggr biggm Biggm
    langle rangle lceil rceil lfloor rfloor ulcorner urcorner llcorner lrcorner vert Vert lvert rvert
    lVert rVert lgroup rgroup lmoustache rmoustache bracevert arrowvert Arrowvert acute grave ddot dddot ddddot
    tilde bar breve check hat vec dot mathring overline overbrace underbrace widehat widetilde overleftarrow
    overrightarrow overleftrightarrow underleftarrow underrightarrow underleftrightarrow frac dfrac tfrac cfrac binom dbinom tbinom choose sqrt
    over atop above stackrel overset underset sideset substack operatorname mathop mathrel mathbin mathord mathopen
    mathclose mathinner mathpunct displaystyle textstyle scriptstyle scriptscriptstyle limits nolimits nonumber smash boxed tag intertext
    shortintertext not colon centerdot medspace thickspace negthinspace negmedspace negthickspace sb sp
    """.split()  # noqa: SIM905 -- 词表字面量即规格形态
)

#: 裸 cs 扫描单遍正则：cs 名（``[a-zA-Z]`` 起头、``@`` 可续）/ bs 跳脱
#: （``\\$``/``\\\\``/``\\%`` 等不被误当定界符或 cs）/ ``$`` 定界候选。
_BARE_CS_SCAN_RX: Final = re.compile(r"\\[a-zA-Z][a-zA-Z@]*|\\.|\$")

#: 粘合 cs 判定要求的最短 src 前缀长——``\toX`` 类短基名误粘面大，不判。
_MIN_FUSED_PREFIX: Final = 3


def cs_events_spans(
    masked: str,
) -> tuple[list[tuple[str, int]], list[tuple[int, int]]]:
    r"""``(cs 名+pos 事件, 配对数学 span 表)``——单遍扫描产物。"""
    css: list[tuple[str, int]] = []
    evs: list[tuple[str, int]] = []
    for m in _BARE_CS_SCAN_RX.finditer(masked):
        t, p = m.group(0), m.start()
        if t[0] == "\\" and len(t) > 1 and t[1].isalpha():
            css.append((t[1:], p))
        elif t == "$" or t in ("\\(", "\\)", "\\[", "\\]"):
            evs.append((t, p))
    return css, _math_spans(evs)


def _math_spans(evs: list[tuple[str, int]]) -> list[tuple[int, int]]:
    r"""定界符事件 → 配对数学区间（``$..$``/``$$..$$``/``\\(..\\)``/``\\[..\\]``）。

    TeX 序读口径——预合并 ``$$`` 会把「inline 闭 ``$`` + 相邻 ``$``」错并成
    display 开，挂起开区间吞掉全文配对（``$a\alpha$$b\beta$$`` 实证：两枚
    inline 域 cs 全被误报为文本域裸 cs）。状态机：文本态见相邻 ``$$`` 开
    display、否则开 inline；inline 态单 ``$`` 即闭；display 态只认相邻
    ``$$``（内部单 ``$`` 是字面字符）；``\(``/``\[`` 各认 ``\)``/``\]``，
    异种定界符与裸 ``\)``/``\]`` 不接管。未闭合定界符其后全部按文本域
    处理（配对不齐由 L0 ``math`` 规则另行承接）。
    """
    closer = {"\\(": "\\)", "\\[": "\\]"}
    spans: list[tuple[int, int]] = []
    open_: tuple[str, int] | None = None
    i = 0
    while i < len(evs):
        d, p = evs[i]
        nxt = evs[i + 1] if i + 1 < len(evs) else None
        pair = nxt is not None and nxt[0] == "$" and nxt[1] == p + 1
        if open_ is None:
            if d == "$":
                open_ = ("$$", p) if pair else ("$", p)
                i += pair
            elif d in closer:
                open_ = (d, p)
        elif open_[0] == "$$":
            if d == "$" and pair:
                spans.append((open_[1], p + 2))
                open_ = None
                i += 1
        elif open_[0] == "$":
            if d == "$":
                spans.append((open_[1], p + 1))
                open_ = None
        elif d == closer[open_[0]]:
            spans.append((open_[1], p + len(d)))
            open_ = None
        i += 1
    return spans


def _cs_out_of_math(
    evs: list[tuple[str, int]], spans: list[tuple[int, int]]
) -> Counter[str]:
    """文本域 cs 名 Counter——span 内出现不计。

    ``_math_spans`` 产出的 span 按起点升序且互不重叠——bisect 定位
    最后一个 ``a <= p`` 的 span 即唯一候选，免去逐 cs × 逐 span 的
    O(#cs × #spans) 线性扫。
    """
    starts = [a for a, _ in spans]
    return Counter(
        n
        for n, p in evs
        if not ((i := bisect_right(starts, p) - 1) >= 0 and p < spans[i][1])
    )


def bare_cs_net(src: str, zh: str) -> Counter[str]:
    r"""译文侧裸 cs 注入净差（编译炸弹两类，Counter 多重集）。

    - **数学域外数学 cs**：``MATH_CS`` 表名出现在 zh 文本域（zh 自带
      ``$..$``/``\\(\\)`` 内豁免——那是合法修正方向）净超 src 文本域
      同计数 → ``Missing $`` 炸弹（realpostfix2 0905.4907 ``\alpha``
      实证）。
    - **粘合 cs**：zh 新增名 = src 某 cs（≥3 字母）前缀 + 含大写后缀
      ——``\itemOC``/``\linebreakGF``/``\csnamebibitemNoStop``（cs 吞掉
      间隔空格、后随词首字母粘上）→ 未定义 cs 炸弹。后缀须含大写：
      ``\citep``/``\refname``/``\textbf`` 类全小写延申是真实 cs 不炸。

    注释区 ``mask_comments`` 屏蔽；src 自带同形按多重集差豁免。L0
    ``_check_bare_cs`` 与 pipeline ``_intercept_bare_cs`` 共用本口径；
    拆分子类判 ``nme in MATH_CS``（两族不交——粘合类跳过表内名）。
    """
    snc, znc = mask_comments(src), mask_comments(zh)
    s_ev, s_sp = cs_events_spans(snc)
    z_ev, z_sp = cs_events_spans(znc)
    sn = Counter(n for n, _ in s_ev)
    zn = Counter(n for n, _ in z_ev)
    new = zn - sn
    if not new:
        return Counter()
    out: Counter[str] = Counter()
    for nme, n in (_cs_out_of_math(z_ev, z_sp) - _cs_out_of_math(s_ev, s_sp)).items():
        if nme in MATH_CS:
            out[nme] = n
    for nme, n in new.items():
        if nme in MATH_CS or nme in out:
            continue
        pre = max(
            (s for s in sn if len(s) >= _MIN_FUSED_PREFIX and nme.startswith(s)),
            key=len,
            default=None,
        )
        if pre is not None and any(c.isupper() for c in nme[len(pre) :]):
            out[nme] = n
    return out


#: 危险控制序列表——zh 译文侧新增这些 cs 名即注入签名（与 ``bare_cs_net``
#: 两子类不交：良形非数学危险 cs 由本网兜底）。四族：IO 与文件/进程面
#: （``\input``/``\write18``——词法件是 ``write``+``18``，表内 ``write``
#: 即兜住——``\openout`` 等）、定义覆写与 cs 名构造（``\def`` 原语族 +
#: ``\csname``/``\expandafter`` 名构造族）、catcode/字符码改写、装包与
#: 全局态（``\usepackage``/``\batchmode`` 族）。已知盲区挂账：
#: ``\begin{filecontents}`` 类 env 名参数写文件不产 cs 事件，归 env 名
#: 面另网，不进本表。
DANGEROUS_CS: Final = frozenset(
    {
        # IO 与文件/进程面
        "input",
        "include",
        "includeonly",
        "endinput",
        "stop",
        "openin",
        "openout",
        "read",
        "readline",
        "write",
        "immediate",
        "special",
        "font",
        "directlua",
        # 定义覆写与 cs 名构造（def 原语族）
        "def",
        "edef",
        "gdef",
        "xdef",
        "let",
        "futurelet",
        "csname",
        "endcsname",
        "expandafter",
        "noexpand",
        "string",
        "meaning",
        "newcommand",
        "renewcommand",
        "providecommand",
        "DeclareRobustCommand",
        "newtheorem",
        "chardef",
        "mathchardef",
        "countdef",
        "dimendef",
        "skipdef",
        "muskipdef",
        "toksdef",
        # catcode / 字符码改写
        "catcode",
        "lccode",
        "uccode",
        "sfcode",
        "mathcode",
        "delcode",
        "makeatletter",
        "makeatother",
        # 装包与全局态
        "usepackage",
        "RequirePackage",
        "RequirePackageWithOptions",
        "documentclass",
        "LoadClass",
        "LoadClassWithOptions",
        "AtBeginDocument",
        "AtEndDocument",
        "AtBeginDvi",
        "AtEndOfClass",
        "AtEndOfPackage",
        "setcounter",
        "setlength",
        "batchmode",
        "nonstopmode",
        "scrollmode",
        "errorstopmode",
        "errmessage",
    }
)


def dangerous_cs_net(src: str, zh: str) -> Counter[str]:
    r"""译文侧危险 cs 注入净差（Counter 多重集）。

    ``DANGEROUS_CS`` 表名在 zh 中出现计数净超 src → 注入签名
    （``\input{/etc/passwd}``/``\write18``/``\def\x``/``\catcode`` 逃逸族）。
    数学域**不豁免**——``$\input$`` 照样执行；注释区 ``mask_comments``
    屏蔽；src 自带同形按多重集差豁免（src 行文引用命令名时 zh 保留
    不冤）。L0 ``_check_dangerous_cs`` 与 pipeline
    ``_intercept_dangerous_cs`` 共用本口径。
    """
    s_ev, _ = cs_events_spans(mask_comments(src))
    z_ev, _ = cs_events_spans(mask_comments(zh))
    diff = Counter(n for n, _ in z_ev) - Counter(n for n, _ in s_ev)
    return Counter({n: c for n, c in diff.items() if n in DANGEROUS_CS})


#: 带号/无号占位符剥皮——``[[TYPE_n]]`` 与 ``[[TYPE]]`` 整 token 形
#: （``xlat.placeholders.ANY_PH_RX`` 的宽口径姊妹：那边按签发面逐型收口，
#: 校验域只须"占位符样 token 全剥"一件——prose 口径/注释占位符共用本件；
#: 原 l0 私有件下沉单源，placeholders.py 头注的「两处口径同步」所指即此）。
PH_ANY_LIKE_RX: Final = re.compile(r"\[\[[A-Z][A-Z0-9_]*(?:_\d+)?\]\]")

#: 控制序列/控制符号剥皮——``\cs名[*]`` 与 ``\`` 后随单字符（``\%``/``\,`` 族）。
CS_OR_SYM_RX: Final = re.compile(r"\\[a-zA-Z@]+\*?|\\[\s\S]")


def prose_text(s: str) -> str:
    """剥占位符 + 控制序列 + 空白折叠后的散文本体（长度比/回显/残英共用口径）。"""
    t = PH_ANY_LIKE_RX.sub(" ", s)
    t = CS_OR_SYM_RX.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def est_tokens(s: str) -> float:
    """Token 代理估计：CJK 1 字≈1 token，其余可见字符≈4/token。

    无 tokenizer 依赖的标定口径——误差双侧对冲后 qualbase-2026-09-18
    全池实测 zh/src 比 p0=0.76 / p50=1.18 / p99.5=1.80。
    """
    cjk = len(CJK_RX.findall(s))
    nonws = sum(1 for c in s if not c.isspace())
    return cjk + (nonws - cjk) / 4


#: 残英 run 门槛（``residual_en_net``）——回显 Tier-A 的 est 下限沿用
#: ``_MIN_PROSE_TOKENS`` 口径（纯占位符/短残段不判）；Tier-B 按词数+字符
#: 双闸防短语/inline 术语误伤。
_RESID_EN_MIN_EST: Final = 10
_RESID_EN_MIN_WORDS: Final = 8
_RESID_EN_MIN_LATIN: Final = 40
#: 豁免：run 内 alpha token ≥3 且 ≥70% 落在「首字母大写词 + 邮箱/URL
#: span」内视为人名/专名/地址列——C10 人名原样、邮箱/URL verbatim 同为
#: 正确态（``John Smith, Jane Doe``/``D.Bukhvalov@science.ru.nl`` 不判）。
_RESID_EN_NAME_MIN_TOKENS: Final = 3
_RESID_EN_NAME_CAP_SHARE: Final = 0.70
#: run 内 alpha 词形（连字符/撇号内连算一词——``closed-loop``/``teacher's``）。
_RESID_EN_WORD_RX: Final = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")
#: 地址类 span（邮箱/URL 字面）——span 内词计入豁免覆盖。
_RESID_EN_ADDR_RX: Final = re.compile(
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|(?:https?://|www\.)[\w./?=&%#+:-]+"
)
#: 人名列小写连接词（nobiliary/romance 颗粒）——计入豁免覆盖而非稀释
#: 大写占比：``Ministerio de Ciencia y Universidade``、``École
#: Polytechnique Fédérale de Lausanne`` 机构/人名靠 de/y/di 等颗粒
#: 串接，纯大写口径实测只能到 ~50%（e2e_real 残英误杀实证）。
_RESID_EN_LINKERS: Final = frozenset(
    {
        "al",
        "d",
        "da",
        "das",
        "de",
        "del",
        "den",
        "der",
        "des",
        "di",
        "dos",
        "du",
        "e",
        "el",
        "het",
        "i",
        "l",
        "la",
        "le",
        "ten",
        "ter",
        "van",
        "von",
        "y",
    }
)
#: 撇号省略形人名颗粒（``d'Ormesson``/``l'Oréal``）——WORD_RX 把
#: ``d'Ormesson`` 收成一词后首字母小写不沾大写豁免，单列一类。
_RESID_EN_ELISION_RX: Final = re.compile(r"[a-z]+'[A-Z]")
#: 「技术负载 token」签名——token 内含 数字/=<>_{}\/.()[]:*+ 或以 ``-`` 起首
#: （命令行 flag）。命令行调用、XML/标记块、代码/查询片段 verbatim 照抄是
#: 正确态而非漏翻：英文散句的 tech 份额实测 ≤0.25，payload ≥0.5
#: （e2e_real 探针批：texttt{foldseek easy-search …}/ccs2012 块/
#: {rotate QRcode} 链/Cypher 查询/Python def 全被 Tier-A 误杀）。
#: 刻意不收 ``'``（撇号人名走 ``_RESID_EN_ELISION_RX`` 豁免）与 ``,``
#: （英文句 however, 类词会被打成 tech——清单签名归 ``_ident_list_run``）。
_RESID_EN_TECH_RX: Final = re.compile(r"[\d=<>_{}\\/.()\[\]:*+]")
_RESID_EN_TECH_SHARE: Final = 0.5
#: 括号枚举 marker 形（``(i)``/``(iv)``/``[2]``/``a)``）——散文枚举
#: 编号不是技术负载：扩表后 ``()``/``[]`` 若照单全收，``(i) gather
#: (ii) normalize`` 类枚举残英会凑满 tech 份额误放（verify 实证
#: 回归）。须带收尾括号——``(j:Ticket``/``exp(0.2`` 半开形仍是 tech。
_RESID_EN_ENUM_RX: Final = re.compile(r"[(\[]?[a-z0-9]{1,4}[)\]]")

#: run 边缘非标点剥离——CJK 切出的 run 会带 ``。，`` 等界标点，
#: verbatim 回显的 src 子串判定须先剥边缘才不被界标点卡掉短回显。
_RESID_EN_EDGE_RX: Final = re.compile(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$")


def _keep_verbatim_run(run: str) -> bool:
    """Run 是否人名/专名/地址列签名。

    ≥70% 词是首字母大写、人名连接词、或落在邮箱/URL span 内即豁免——
    句子夹个把名字/邮箱凑不够 70%，整句英文不误放。
    """
    wms = list(_RESID_EN_WORD_RX.finditer(run))
    if len(wms) < _RESID_EN_NAME_MIN_TOKENS:
        return False
    spans = [m.span() for m in _RESID_EN_ADDR_RX.finditer(run)]
    covered = sum(
        1
        for m in wms
        if m.group(0)[:1].isupper()
        or m.group(0).lower() in _RESID_EN_LINKERS
        or _RESID_EN_ELISION_RX.match(m.group(0))
        or any(s <= m.start() < e for s, e in spans)
    )
    return covered / len(wms) >= _RESID_EN_NAME_CAP_SHARE


def _tech_run(core: str) -> bool:
    """Run 是否技术负载（命令行/XML/代码/查询 payload）而非英文散句。

    逐 token 判定：含数字/结构符/括号/冒号/点号（``scipy.a.b(c)`` 调用
    形、``MATCH (n:Label)`` 查询形）或以 ``-`` 起首（``-s``/
    ``-{}-alignment-type`` flag 形）计一票——``(i)``/``[2]`` 类枚举
    marker 除外（``_RESID_EN_ENUM_RX``，散文编号非负载）。份额
    ≥0.5 豁免——两 token 的短 run 必是纯 payload 才够 est 门槛。
    """
    toks = core.split()
    if not toks:
        return False
    tech = sum(
        1
        for t in toks
        if (_RESID_EN_TECH_RX.search(t) or t.startswith("-"))
        and _RESID_EN_ENUM_RX.fullmatch(t) is None
    )
    return tech / len(toks) >= _RESID_EN_TECH_SHARE


#: 逗号分隔小写标识符清单的 token 形（``atexit,``/``enum``）——模块名/
#: 关键字 CSV 表 verbatim 照抄豁免用；逗号进不了 tech 表（英文句
#: however, 类词会被打成 tech），清单签名单列。
_RESID_EN_IDENT_RX: Final = re.compile(r"[a-z_][a-z0-9_]*,?")
_RESID_EN_IDENT_MIN_TOKENS: Final = 6
_RESID_EN_IDENT_SHARE: Final = 0.6
#: 逗号收尾 token 占比下限——真 CSV 清单 ~0.83；散文 ``However, the
#: method, when applied, …`` 逗号率 ~0.3、散文夹名表句 ~0.4，绝对
#: 枚数闸（≥2）挡不住它们过闸误放（verify 实证），须按密度判。
_RESID_EN_IDENT_COMMA_SHARE: Final = 0.5


def _ident_list_run(core: str) -> bool:
    """Run 是否逗号分隔全小写标识符清单（``atexit, builtins, …`` 名表）。

    ≥6 token、≥60% 形如 ``ident``/``ident,``、逗号收尾占比 ≥50%
    三闸并举——只在 verbatim 路径生效（``core in ss`` 前置），非
    照抄的英文清单仍归 Tier-B 判定不误放。
    """
    toks = core.split()
    if len(toks) < _RESID_EN_IDENT_MIN_TOKENS:
        return False
    ident = sum(1 for t in toks if _RESID_EN_IDENT_RX.fullmatch(t))
    comma = sum(1 for t in toks if t.endswith(","))
    return (
        ident / len(toks) >= _RESID_EN_IDENT_SHARE
        and comma / len(toks) >= _RESID_EN_IDENT_COMMA_SHARE
    )


def residual_en_net(src: str, zh: str) -> list[str]:
    r"""译文段内残留英文 run 检测（半译/原文回退的出货签名）。

    行级修复把 audit 失败的行按 ``src_l`` 原文装回、或模型整段应答里夹了
    未翻英文句——``same_source`` 只拦整段回显、``length`` CJK 占比只在
    拉丁主导时 warn，段内单句英文两网全盲（t_84c406c2 seq-49/51 实证：
    阶梯 ``recovered`` 落 DB ``ok`` 静默出货）。

    口径：zh 剥注释/占位符/cs 成 prose 后**按 CJK 字符切极大非 CJK run**
    （不按句号切——``English verbatim. 中文`` 混合段骗不过 run 切分）：

    - **Tier-A 回显**：剥边缘后 ``est_tokens ≥ 10`` 且 run 是 src prose
      子串——行级 ``src_l`` 回退/整句照抄的确切签名；
    - **Tier-B 混血**：run 不在 src 且 alpha 词 ≥8 且拉丁字母 ≥40——
      非照抄的整句英文（改写/漏翻长句）；
    - **技术负载豁免**：run 半数以上 token 含数字/结构符/括号或以
      ``-`` 起首（``_tech_run``）、或 verbatim run 整体是逗号分隔
      小写标识符清单（``_ident_list_run``，模块/关键字名表照抄）——
      命令行/XML/代码 payload 与名表照抄是正确态；
    - **人名/地址豁免**：run 为近全大写人名/专名列（de/y/von 类
      连接词计入覆盖）、或词几乎全落在邮箱/URL span 内
      （``_keep_verbatim_run``）不判。

    门槛：``src`` 含 ``[[BIB_`` → ``[]``（文献直通留英合法，同
    ``same_source`` 豁免口径）；zh prose 零 CJK → ``[]``（全英译文归
    ``same_source``/``length`` 管辖，本网只收"中文里夹英文"）。
    命中返回 run 列表（剥后形），L0 ``_check_residual_en`` 与 pipeline
    ``_intercept_residual_en`` 共用本口径。
    """
    if "[[BIB_" in src:
        return []
    ss = prose_text(mask_comments(src))
    sz = prose_text(mask_comments(zh))
    if not CJK_RX.search(sz):
        return []
    hits: list[str] = []
    for seg in CJK_RX.split(sz):
        run = seg.strip()
        core = _RESID_EN_EDGE_RX.sub("", run)
        if not core:
            continue
        words = _RESID_EN_WORD_RX.findall(run)
        if _tech_run(core) or _keep_verbatim_run(run):
            continue
        if core in ss and _ident_list_run(core):
            continue
        if est_tokens(core) >= _RESID_EN_MIN_EST and core in ss:
            hits.append(run)
            continue
        lat = sum(1 for c in core if c.isascii() and c.isalpha())
        if (
            core not in ss
            and len(words) >= _RESID_EN_MIN_WORDS
            and (lat >= _RESID_EN_MIN_LATIN)
        ):
            hits.append(run)
    return hits


def lev_capped(a: str, b: str, cap: int) -> int:
    """Levenshtein 距离，超 cap 提前返回 cap+1。

    行最小值全超 cap 可早退（最优路径行经值不降，终值必超 cap）；但
    末行仍可能「行内最低点 ≤cap 而终值 >cap」——收尾同须压回 cap+1，
    否则返回值越契约界（实证：``aaab``/``babbbbb`` cap=3 实距 5）。
    """
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        rowmin = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            rowmin = min(rowmin, v)
        if rowmin > cap:
            return cap + 1
        prev = cur
    return min(prev[-1], cap + 1)


# ---------------------------------------------------------------- 接缝判据
# 尾字符必须真字母：孤 ``\@`` 是控制符号而非控制词尾——``\@x`` 的 ``@``
# 不吞后继空格，``_rappend``/``seg_join`` 若按 ``\\[@]+`` 收它会补伪
# ``" "`` 破 identity（S1）；``\ds@list`` 族中位 ``@`` 不受影响。
# ``\Z`` 严格串尾（体尾 ``\n`` 已阻断 token 合并，放宽会收过头）。
# 严格接缝族单源——``reconstruct.seg_join`` 同形经 ``needs_seam_space``
# 消费（``xlat.batch`` 的 ``\*?`` 星形 + ``$`` 收尾变体与 bench parsebench
# 的松径是有意分歧，不随本件）。原宿 ``latex/segmenter/_common``——
# ``latex.reconstruct``/``segmenter.core`` 消费，迁往任一消费层都破坏
# import 面，下沉本叶。
cs_letter_tail_rx: Final = re.compile(r"\\[a-zA-Z@]*[a-zA-Z]\Z")
#: 旧锚名——canonical 名 ``cs_letter_tail_rx``。
_LETTER_TAIL_RX = cs_letter_tail_rx


def _starts_letter(s: str) -> bool:
    r"""首字符是 ASCII 字母（TeX 控制词名续名判据——``\\foo``+``中`` 不算熔合）。"""
    return bool(s) and s[0].isascii() and s[0].isalpha()


def needs_seam_space(prev: str, nxt: str) -> bool:
    r"""``prev`` 尾落 ``\letters`` 控制词形 + ``nxt`` ASCII 字母头 → 接缝补 ``" "`` 判据。

    ``_rappend``/``seg_join``/``letters_cut`` 同闸单源。头字符定死
    ASCII-only（``_starts_letter``）——ident 轨 byte-identity 要求
    （裸 ``isalpha`` 会在 CJK 头前补伪空格）；``seg_join`` 侧 TeX
    吸收该空格本无所谓，统一取严口径顺带消 ``\cs``+CJK 的
    letters_cut 假阳性面。
    """
    return _starts_letter(nxt) and cs_letter_tail_rx.search(prev) is not None
