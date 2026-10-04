r"""红线信号单源注册表（★2 收敛点）：同一概念的多层拼写在此并列登记。

背景：同一红线概念曾四层三拼写——``missing_chars``（engine）/
``missing_char``（rules/ warnings:）/``missing_glyph``（logattr）——
nullfont 豁免三联改（36f926d/89b2784/0f5c1d6）靠人肉同步，已漂过。
且各层 pattern **有真分歧**而非纯拼写问题：``invalid_utf8`` 曾三层三种
写法，现 engine/logattr 同形（裸串 + ``replaced by U\+FFFD`` 变体）、rules
另折叠 FFFD misschar；logattr ``file_not_found`` 是 engine ``missing_graphic`` +
``degraded_file`` 两条的粒度并集；judge 持 gate+nullfont 双生探针。
强收单 pattern 必改行为，故本表按 concept 行登记各层
``(发射名, pattern)``，消费者各取本层切片，分歧并列可见即防再漂。

消费面对应（emit 名逐字节保留旧值，零行为变）：

- ``engine`` → ``compile/engine.py`` ``WARNING_RED_LINES``（全文检索 →
  ``LogInfo.warnings_hit`` → judge ``warn:*`` reasons）
- ``rules``  → ``compile/fixloop/rules/`` ``warnings:`` 段——**镜像**，
  fixloop loader 照旧读 yaml；一致性由 ``tests/compile/test_redlines.py`` pin
- ``logattr``     → ``validate/logattr.py`` ``_WARNING_RULES`` 行级归类名/模式 +
  ``_REDLINE_CLASSES`` 红线集（``logattr_redline`` 标记）
- ``judge``  → ``compile/judge.py`` 门控/探针 regex；``name`` 即 reason
  词干（``missing_character×N`` / ``missing_character_nullfont×N``）

本模块零依赖（不进 compile/ 是因 logattr 在 validate/——``compile→validate``
边不存在，反向分层会使只读层依赖消费层；与 textutil/texlog 同层两包可达）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "ENGINE_RED_LINES",
    "LOGATTR_REDLINE_CLASSES",
    "LOGATTR_WARNING_RULES",
    "REDLINES",
    "REDLINES_BY_ID",
    "RULES_WARNINGS",
    "LayerSpec",
    "RedLine",
    "name_pattern",
]

#: ``Missing character:`` 门控（非 nullfont）——tempered lookahead 限界窗：
#: 排除 ``in font nullfont``（试排/测量盒吞字良性，nullfont-scout-2026-09-17
#: ~30/37 格纯噪音）。窗口界 = 本消息体内——逐字符 temper 于
#: ``Missing character``（下一条缺字起点）与 ``in font ``（本消息字体声明
#: 终止符）双闸：消息已声明字体后同行的 ``in font nullfont`` 字样不再误豁免
#: （logpipe pin#2）；至多跨一个折行续行（79 列 wrap），续行内同域再限
#: {0,90}。冒号前缀即真消息形态——``Missing characters ...`` 行文不计缺字
#: （logpipe pin#4，与 logattr census 口径同源）。
#: engine ``missing_chars`` / rules ``missing_char`` / judge 门控 / logattr
#: ``missing_glyph_nullfont`` 四处共用同一窗口语义（logattr 逐行应用时跨行
#: 分支不触发——折行豁免需消费层先拼续行，见 missing_char_nullfont 行注）。
_MISSCHAR_WINDOW: Final = (
    r"(?:(?!Missing character|in font )[^\n]){0,90}?"
    r"(?:\n(?:(?!Missing character|in font )[^\n]){0,90}?)?"
)
_MISSCHAR_GATE: Final = (
    r"Missing character:(?!" + _MISSCHAR_WINDOW + r"in font nullfont)"
)
#: 同一限界窗正向取——nullfont 良性命中进 judge notes 观察项。
_MISSCHAR_NULLFONT_PROBE: Final = (
    r"Missing character:(?=" + _MISSCHAR_WINDOW + r"in font nullfont)"
)


@dataclass(frozen=True, slots=True)
class LayerSpec:
    """某消费层对一条红线概念的发射名与检索模式。

    ``pattern=None`` 表示该层无独立检索模式：logattr 派生类（按码点细分）
    或该层把本概念并入他行（见各行注释）。
    """

    name: str
    pattern: str | None = None


@dataclass(frozen=True, slots=True)
class RedLine:
    """一条红线概念的全层登记。"""

    id: str  # canonical 概念 id（注册表内部键，不外发）
    engine: LayerSpec | None = None  # engine.py WARNING_RED_LINES 条目
    rules: LayerSpec | None = None  # rules/ warnings: 镜像条目
    logattr: LayerSpec | None = None  # logattr _WARNING_RULES 行级类
    logattr_redline: bool = False  # logattr 类是否入 _REDLINE_CLASSES
    judge: LayerSpec | None = None  # judge 门控/探针 regex + reason 词干
    concept_only: bool = False  # 零层切片概念锚点行（判据在 log regex 域外）


#: 行序 = engine 发射序（invalid_utf8/fffd/missing_chars/missing_graphic/
#: degraded_file）；rules 镜像序、logattr 类集均由本表过滤导出。
REDLINES: Final[tuple[RedLine, ...]] = (
    RedLine(
        id="invalid_utf8",
        # rules 层把 FFFD misschar 折叠进本行 pattern（与 fffd_glyph 分行
        # 相对——fixloop 侧 ``warn_utf8`` 单路由吃掉两种源）。
        engine=LayerSpec("invalid_utf8", r"Invalid UTF-8 byte|replaced by U\+FFFD"),
        rules=LayerSpec(
            "invalid_utf8",
            r"Invalid UTF-8 byte|Missing character.*U\+FFFD|replaced by U\+FFFD",
        ),
        logattr=LayerSpec("invalid_utf8", r"Invalid UTF-8 byte|replaced by U\+FFFD"),
        logattr_redline=True,
    ),
    RedLine(
        id="fffd_glyph",
        # 缺 U+FFFD 替换符字形——invalid_utf8 源被排版成缺字。engine 层
        # 独占行（pattern = gate 窗 + FFFD 码点段）；rules 层折叠进
        # invalid_utf8；logattr 层为 missing_glyph 命中的码点==0xFFFD 派生类。
        engine=LayerSpec("fffd_glyph", _MISSCHAR_GATE + r'[^\n]*\((?:"|U\+)FFFD\)'),
        logattr=LayerSpec("fffd_glyph"),
        logattr_redline=True,
    ),
    RedLine(
        id="missing_char",
        # 缺字形红线本体。三层同一 tempered pattern（engine 全文/rules
        # 全文/judge 门控）；logattr 行级归类只需裸 ``Missing character:``
        # （nullfont 行已被其独立类先行吃掉，见下行）。
        engine=LayerSpec("missing_chars", _MISSCHAR_GATE),
        rules=LayerSpec("missing_char", _MISSCHAR_GATE),
        logattr=LayerSpec("missing_glyph", r"Missing character:"),
        logattr_redline=True,
        judge=LayerSpec("missing_character", _MISSCHAR_GATE),
    ),
    RedLine(
        id="missing_char_nullfont",
        # 良性试排吞字——**无一层判红**：judge 进 notes 观察项、logattr 独立
        # 类留 by_class/samples 观察面；engine/rules 的排除已内嵌在
        # missing_char 行 tempered pattern 的负向前瞻里。logattr 行级类与 judge
        # 探针同 pattern（窗口语义单源）：同行 ``in font `` 已声明真字体后
        # 尾缀 nullfont 不再误豁免；79 列折行豁免要求消费层把续行拼回
        # （窗口跨一个 ``\n`` 分支在逐行应用下天然不触发）。
        logattr=LayerSpec("missing_glyph_nullfont", _MISSCHAR_NULLFONT_PROBE),
        judge=LayerSpec("missing_character_nullfont", _MISSCHAR_NULLFONT_PROBE),
    ),
    RedLine(
        id="missing_char_sweep",
        # C0 测量扫掠（picinpar ``\computeilg`` ``\hbox{\char\tcl}``
        # tcl=0..127 逐码位试排丢盒）——豁免判定是算法标记（同字体名下
        # ≥25 条严格升序 C0+DEL 缺字消息链），单行 pattern 表达不了，
        # 故各检索层无切片：engine 豁免内联在 loginfo ``missing_chars``
        # 分支、judge 计数面在 ``count_missing_chars`` 内减除（两路同调
        # ``texlog.misschar_sweep_hits``）。本行只登记 judge notes 词干
        # ``missing_character_sweep×N``（与 nullfont×N 同形观察项）。
        judge=LayerSpec("missing_character_sweep"),
    ),
    RedLine(
        id="missing_glyph_cjk",
        # logattr 派生类：missing_glyph 命中按 ``_MISSING_CHAR_RX`` 码点
        # ``is_cjk_cp`` 细分（中文静默丢失信号），无独立 pattern。
        logattr=LayerSpec("missing_glyph_cjk"),
        logattr_redline=True,
    ),
    RedLine(
        id="missing_graphic",
        # logattr ``file_not_found`` 是本行 + degraded_file 的粒度并集
        # （行级 ``File `x' not found`` 不分 graphic/包文件）。
        engine=LayerSpec(
            "missing_graphic",
            r"File `[^']+\.(?:pdf|png|jpg|jpeg|eps|mps|bb)' not found"
            r"|Cannot determine size of graphic|Unknown graphics extension",
        ),
        rules=LayerSpec(
            "missing_graphic",
            r"File `[^']+\.(eps|png|jpg|pdf)' not found|cannot (find|open) image",
        ),
        logattr=LayerSpec(
            "file_not_found",
            r"File `[^']+' not found|cannot (?:find|open)|Could not locate",
        ),
        logattr_redline=True,
    ),
    RedLine(
        id="degraded_file",
        # tectonic 缺包静默降级行（continue-on-errors 把 missing .sty 降为
        # 可恢复，跳包续出残页 pdf——engine-matrix §7.4 暗雷）。logattr 侧无
        # 对应类：``^!`` 行在 logattr 计入错误而非 warning。
        engine=LayerSpec("degraded_file", r"^!.*(?:File|package)[^\n]*not found"),
        rules=LayerSpec("tectonic_degrade", r"^!+ .*not found"),
    ),
    RedLine(
        id="overfull_hbox",
        # fixloop 专用行：``Overfull \hbox`` 是版面缺陷 (qc layout:overfull
        # /geo_margin_breach 部分同源) 的 log 面标记，无 '!' 错时经
        # warn_overfull 伪类别驱动 para_loosen 修复轮。只挂 rules 切片
        # ——engine 层命中会作为 ``warn:*`` reason 污 verdict (overfull
        # 是版面质量问题非编译健康问题，判红面不收); logattr 已有独立观察类
        # ``overfull`` (行级归类，非本表托管——pattern 分歧并列原则下
        # 不抢其所有权); judge 同理不挂。
        rules=LayerSpec("overfull_hbox", r"Overfull \\hbox"),
    ),
    RedLine(
        id="float_too_large",
        # fixloop 专用行：``LaTeX Warning: Float too large for page`` 是
        # 浮体超高 (qc layout:float_lost/float_fit 部分同源) 的 log 面
        # 标记——[H] 钉死的超高非浮体盒会被页缘截杀，warn_float_big
        # 伪类别驱动 float_h_demote 降级翻回真浮体。rules-only 同
        # overfull_hbox 行注 (版面信号不进判红面)。
        rules=LayerSpec("float_too_large", r"Float too large for page"),
    ),
    RedLine(
        id="undef_ref_warn",
        # fixloop 专用行：``LaTeX Warning: Reference/Citation/Label ...
        # undefined`` + ``There were undefined references`` 尾标 →
        # warn_undef_ref 伪类别（10-taxonomy ``warn_id`` 门），消费臂 =
        # 80-bib pagerange/endlabel 注入族 + bbl_cite_undef_regen。首遍
        # 噪音由引擎 _resolve_tail 出货前解析趟吸收（aux 已播种 + marks
        # 命中自适应补趟）——本 id 只在末遍编译 log 仍报 undefined 时点火。
        # rules-only 同 overfull_hbox 行注（判红面不收警告类）。
        rules=LayerSpec(
            "undef_ref_warn",
            r"LaTeX Warning: (Reference|Citation|Label).{0,80}undefined"
            r"|There were undefined references",
        ),
    ),
    RedLine(
        id="bbl_version",
        # fixloop 专用行：biblatex ``File X.bbl is wrong format version``
        # 警告 → warn_bbl_version → bbl_version_regen（80-bib）。
        # warning-only 稿无 ``!`` 行，原 bbl_regen 的 undefined_cs 门
        # 永不命中——本 id 是 warning 域的独立点火口。
        rules=LayerSpec("bbl_version", r"is wrong format version"),
    ),
    RedLine(
        id="overfull_vbox",
        # fixloop 专用行：``Overfull \vbox`` → 10-taxonomy 别名行复用
        # warn_overfull 伪类别（tabular/math/display/gfx 各消费臂自门
        # 谓词；专属 vbox 臂 vbox_geometry_clamp builtin 未注册，落地后
        # 可拆伪类别）。rules-only 同 overfull_hbox 行注。
        rules=LayerSpec("overfull_vbox", r"Overfull \\vbox"),
    ),
    RedLine(
        id="restatable_loss",
        # thm-restate ``\begin{restatable}{env}{key}`` 的 env-name 参被译
        # （argspec ungate 前的 opacity 缺口类，及一切再泄漏路径）→ 存体
        # ``\csname #2\endcsname`` 打未定义 env 名——``\csname`` 对未定义名
        # 自动 \relax **零消息**（lane-silentthm 实证 ``{定理}{main}``：
        # 全链 0 个 ``!`` 行、无 warning，定理头静默丢失 body 照排，site
        # 与 ``\main*`` recall 两处同丢）。key 参被译不属本行域——recall
        # ``\key`` 未定义=普通 undefined_cs 显见。log 面无任何事件行可挂，
        # 唯一可检信号 = 包加载痕迹（file-stack ``(…/thm-restate.sty`` /
        # ``Package: thm-restate`` 行），故只登记 judge 探针记 notes 观察项
        # （presence≠loss：包在场≠env 用≠参被译；纸真 CJK env 名亦合法）。
        # engine/rules 不挂：presence 非判红语义（``warn:*`` 会污 verdict）；
        # logattr 不可挂：``_WARNING_RULES`` 预筛只吃 Warning 形态行，包名行
        # 永不进分类器。真·判定信号在 vtex 源面（env-name 参非 ASCII/非
        # 已声明 env）——属 judge source-scan 探针，非 log pattern，不入本表。
        judge=LayerSpec(
            "thm_restate_loaded",
            r"thm-restate\.sty|Package: thm-restate\b",
        ),
    ),
    RedLine(
        id="upstream_asset_absent",
        # 上游资产缺席（known-limitation 概念行，零层切片）：文档引用而
        # arXiv e-print tarball 根本没 ship 的图档——singlesweep mech_buckets
        # 21 格实证（``fig/plot2 (1).png``/``Figs/tikz_two_event.pdf`` 等
        # payload，``missing_graphic|<path>`` 标记 + tarball 清单核对归因，
        # bucket 名 ``upstream-asset-absent``）。构造上不可修：任何 fixloop
        # arm 都变不出上游从未 ship 的字节——占位图出残页即诚实上限。
        # 各层不挂的判据：log 面信号与可修 missing_graphic（路径打错、改名
        # 漂移、ext 不匹配）逐字节同形，无任何行级 pattern 能切出本子集；
        # 真·判据 = e-print 清单核对（source/offline 介质），不属任一层
        # log regex 语义（judge LayerSpec 语义=log regex，同 restatable_loss
        # 行注——源面信号不入本表）。登记只为归因面留概念锚点：
        # ``REDLINES_BY_ID`` 供 census/bucket 报告引 id，对
        # ENGINE_RED_LINES/RULES_WARNINGS/LOGATTR_* 切片零贡献（``is not None``
        # 过滤天然豁免）。
        concept_only=True,
    ),
    RedLine(
        id="perpage_fnsymbol_firstpass",
        # perpage+fnsymbol 首遍计数器溢出（known-limitation 概念行，零层
        # 切片）：footmisc[marginal,perpage,symbol] + starred
        # ``\DefineFNsymbols*{dagfirst}`` 六符上限——fresh .aux 首遍按全局
        # 编号，footnote 数 >6 即 ``\@ctrerr`` Counter too large；warm .aux
        # 次遍 perpage 标签就位按页重置 → 自愈。footmisc census 实证
        # 2105.03751 单格：wave-5 down-flip = splice_rebuilt fresh workdir
        # 的 aux-freshness artifact（loop1 passes=2 clean / loop2,3
        # passes=1 ctrerr），非规致、非文档缺陷。构造上限：首遍溢出属
        # LaTeX 语义真错——引擎层 ``_xelatex`` rc!=0 break 先于
        # rerun-hint check，无 hint 发射的硬错拿不到次遍（rerunhint
        # census 另行评估普适受害面）。各层不挂判据：``\@ctrerr`` log 行
        # 与真计数器溢出（非首遍 quirk）同形，行级 pattern 切不出子集；
        # 真·判据 = .aux 新鲜度 + ``\DefineFNsymbols*`` 符数 vs footnote
        # 计数——source/build-state 介质非 log regex 语义。登记只为归因
        # 面留概念锚点，对 ENGINE_RED_LINES/RULES_WARNINGS/LOGATTR_* 零贡献。
        concept_only=True,
    ),
    RedLine(
        id="latex209_class_absent",
        # LaTeX 2.09 文档类缺席类表（known-limitation 概念行，零层切片）：
        # ``\documentstyle{X}`` 的 X 不在 latex209.py 类表（:181 amsart
        # 等收录面）→ 引擎按能力边界正确 reject，非规致亦非文档缺陷。
        # singles3 普查实证 math/0111109 ``\documentstyle{amsppt}`` 单格
        # （amsppt = AMS preprint 类，从未入表）。各层不挂判据：reject
        # 发生在编译前，log 面无事件行可检索；真·判据 = 类表成员核对
        # （config/source 介质非 log regex 语义）。登记只为归因面留概念
        # 锚点，对 ENGINE_RED_LINES/RULES_WARNINGS/LOGATTR_* 零贡献。
        concept_only=True,
    ),
)

REDLINES_BY_ID: Final[dict[str, RedLine]] = {r.id: r for r in REDLINES}


def name_pattern(spec: LayerSpec | None) -> tuple[str, str]:
    """层 spec 窄化为 ``(name, pattern)``——pattern 缺失属登记错误。"""
    if spec is None or spec.pattern is None:
        msg = "redline layer spec lacks pattern"
        raise ValueError(msg)
    return spec.name, spec.pattern


#: ``engine.WARNING_RED_LINES`` 切片：``(发射名，全文 pattern)`` 保持登记序。
ENGINE_RED_LINES: Final[tuple[tuple[str, str], ...]] = tuple(
    name_pattern(r.engine) for r in REDLINES if r.engine is not None
)

#: rules/ ``warnings:`` 段镜像期望 ``(id, pattern)`` 保持登记序——
#: ``tests/compile/test_redlines.py`` 用它 pin 住镜像（yaml 照旧由 fixloop loader 读）。
RULES_WARNINGS: Final[tuple[tuple[str, str], ...]] = tuple(
    name_pattern(r.rules) for r in REDLINES if r.rules is not None
)

#: ``logattr._REDLINE_CLASSES`` 切片（含无 pattern 的派生类）。
LOGATTR_REDLINE_CLASSES: Final[frozenset[str]] = frozenset(
    r.logattr.name for r in REDLINES if r.logattr is not None and r.logattr_redline
)

#: ``logattr._WARNING_RULES`` 中本表托管的 ``canonical id → (发射名，行级
#: pattern)``（派生类无 pattern 不在内；非红线 warning 类仍由 logattr 本层持有）。
LOGATTR_WARNING_RULES: Final[dict[str, tuple[str, str]]] = {
    r.id: name_pattern(r.logattr)
    for r in REDLINES
    if r.logattr is not None and r.logattr.pattern is not None
}
