r"""文本小件单源 —— 遮盖视图/校验签名/env 读取的跨层宿主包。

``textutil.py`` C1 拆分产物：公共面经本 facade 全量 re-export——
``from texlate.textutil import X`` 与 ``textutil.X`` 属性面逐名守恒，
``__all__`` 原样。自包含大簇出叶：

- ``decls``：文档声明/结构探测正则族（docclass/docstyle/input/声明名清洗）。
- ``mask``：``mask_comments``/``mask_tex`` 等长遮盖机 + 逐字/失活环境
  注册表（``VERBATIM_ENVS``/``DEAD_ENVS``）+ 遮盖视图迭代件。
- ``cjk``：排序不相交区间的 bisect 判定件 + ``CJK_RANGES``/``CJK_RX``/
  ``is_cjk_cp`` 码点面。
- ``encoding``：arXiv 源码字节 → 编码判定/解码簇（``sniff_tex_encoding``/
  ``decode_tex``/``decode_tex_with``/``EncodingVerdict``）。

留在本 facade 的均属**跨域宿主件**——reaudit「注明跨域定位」方案：
校验域知识（``bare_cs_net``/``ph_in_cs_net``/``cs_events_spans``/``MATH_CS``/
``PH_FUZZY_RX``/``lev_capped``/``JSON_FENCE_RX``）的消费方在
validate/xlat/fixloop 层，迁往任何一层都会破坏 import 面（validate 不能
import xlat 等），故宿于本层只注记不出叶；``env_flag``/``env_str``/
``env_float``/``data_root`` 与 ``safe_resolve``/``safe_is_file`` 是各层
共用的 os 边界小件，同理留本层。
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Final

from .cjk import CJK_RANGES, CJK_RX, is_cjk_cp
from .decls import (
    BEGIN_DOC_RX,
    CMD_BOUNDARY,
    DECL_NAME_RX,
    DECL_TAIL,
    DOCCLASS_DECL_RX,
    DOCCLASS_NAMES,
    DOCCLASS_ONLY_RX,
    DOCCLASS_OPTS_RX,
    DOCCLASS_RX,
    DOCSTYLE_DECL_RX,
    DOCSTYLE_RX,
    END_DOC_RX,
    INPUT_BARE_RX,
    INPUT_BRACED_RX,
    LOADER_CMDS,
    SUBFILES_CHILD_RX,
    clean_decl_name,
)

# 私有转口——tests/ 钉点经 ``from texlate.textutil import _x`` 与
# ``textutil._x`` 属性面消费（各带 noqa: SLF001），拆分后口径不变。
from .encoding import (  # noqa: F401
    _TAR_HEADER_LEN,
    EncodingVerdict,
    _char_class,
    _declared_name,
    _decode_tex_with_memo,
    _eol_norm,
    _tar_disguised,
    _tar_header_ok,
    decode_tex,
    decode_tex_with,
    sniff_tex_encoding,
)
from .mask import (  # noqa: F401
    _MEMO_MAX_INPUT,
    _VERBATIM_BEGIN_RX,
    DEAD_ENVS,
    VERBATIM_ENVS,
    _mask_tex_memo,
    dead_end_anchored,
    dead_env_end,
    iter_depth0,
    mask_comments,
    mask_tex,
)

__all__ = [
    "BEGIN_DOC_RX",
    "CJK_RANGES",
    "CJK_RX",
    "CMD_BOUNDARY",
    "DEAD_ENVS",
    "DECL_NAME_RX",
    "DECL_TAIL",
    "DOCCLASS_DECL_RX",
    "DOCCLASS_NAMES",
    "DOCCLASS_ONLY_RX",
    "DOCCLASS_OPTS_RX",
    "DOCCLASS_RX",
    "DOCSTYLE_DECL_RX",
    "DOCSTYLE_RX",
    "END_DOC_RX",
    "INPUT_BARE_RX",
    "INPUT_BRACED_RX",
    "JSON_FENCE_RX",
    "LOADER_CMDS",
    "MATH_CS",
    "PH_FUZZY_RX",
    "PH_RX",
    "SUBFILES_CHILD_RX",
    "VERBATIM_ENVS",
    "EncodingVerdict",
    "bare_cs_net",
    "clean_decl_name",
    "cs_events_spans",
    "data_root",
    "dead_end_anchored",
    "dead_env_end",
    "decode_tex",
    "decode_tex_with",
    "env_flag",
    "env_float",
    "env_opt",
    "env_raw",
    "env_str",
    "is_cjk_cp",
    "iter_depth0",
    "lev_capped",
    "mask_comments",
    "mask_tex",
    "ph_in_cs_net",
    "safe_is_file",
    "safe_resolve",
    "sniff_tex_encoding",
]


# ------------------------------------------------------- 校验域知识（跨域宿主件）
# 本节以下为 validate/xlat/fixloop 层共用口径——迁往任一消费层都会破坏 import
# 面（validate 不能 import xlat），按 reaudit「注明跨域定位」方案宿于 facade，
# 不出叶。

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
    """文本域 cs 名 Counter——span 内出现不计。"""
    return Counter(n for n, p in evs if not any(a <= p < b for a, b in spans))


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


# ---------------------------------------------------------------- 路径防御
def safe_resolve(path: Path) -> Path | None:
    r"""``Path.resolve()`` 防御层：symlink loop/NUL/ENAMETOOLONG → ``None``。

    不可解析按不存在处理——上游恶意/病态名（``\\input`` 巨参、LLM patch
    ``p.file``、log 解析出的文件名）触发的 ``OSError``/``RuntimeError``/
    ``ValueError`` 一律收敛为缺席语义。
    """
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def safe_is_file(path: Path) -> bool:
    r"""``Path.is_file()`` 防御层：NUL ``ValueError`` + 非豁免 ``OSError`` → False。

    pathlib 自吞 ``OSError``，但内嵌 NUL 字节的路径抛 ``ValueError`` 不豁免——
    攻击者可控名（``\\includegraphics`` 参数、fixloop 供给的 fname）直达即崩。
    """
    try:
        return path.is_file()
    except (OSError, ValueError):
        return False


# ------------------------------------------------------------------ env 读取
# ``TEXLATE_*`` env 读取的单一事实源——布尔旗标统一 ``1/true/yes/on`` 真值表
# （strip+lower 后判定）；字符串选择器统一 strip+lower 归一；浮点参数统一
# 解析失败/nan/inf 回默认（范围裁剪归调用方）；数据根统一
# ``TEXLATE_DATA_DIR`` > ``~/.texlate``（只定位不 mkdir，副作用归调用方）。
_TRUE_WORDS: Final = frozenset({"1", "true", "yes", "on"})


def env_flag(name: str, *, default: bool) -> bool:
    """读布尔 env：``1/true/yes/on``（strip+lower 后）为真；未设置取 ``default``。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_WORDS


def env_float(name: str, default: float) -> float:
    """读浮点 env：strip 后 ``float()`` 解析；未设置/解析失败/nan/inf 一律回 ``default``。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        v = float(raw.strip())
    except ValueError:
        return default
    return v if math.isfinite(v) else default


def env_str(name: str) -> str:
    """读字符串 env：strip+lower 归一返回；未设置返 ``""``（选择器类旗标同口径）。"""
    return os.environ.get(name, "").strip().lower()


def env_raw(name: str) -> str:
    """读字符串 env：strip 归一但**不** lower；未设置返 ``""``。

    路径/URL/model/key 等值敏感场用（选择器类旗标用 ``env_str``）。set-empty
    与未设置同归 ``""``——需要区分两者时用 ``env_opt``。
    """
    return os.environ.get(name, "").strip()


def env_opt(name: str) -> str | None:
    """读字符串 env：未设置 → ``None``；已设置 → strip 后原样（空串保留）。

    「置空串」带独立语义的场用（如 ``TEXLATE_TEX_BUNDLE=""`` 表引擎自带
    默认 bundle）——``env_raw`` 会把 set-empty 与未设置混同。
    """
    raw = os.environ.get(name)
    return raw.strip() if raw is not None else None


def data_root() -> Path:
    """数据根：``TEXLATE_DATA_DIR`` > ``~/.texlate``——只定位不 mkdir。"""
    raw = os.environ.get("TEXLATE_DATA_DIR")
    return Path(raw).expanduser() if raw else Path.home() / ".texlate"
