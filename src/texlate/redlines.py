r"""红线信号单源注册表（★2 收敛点）：同一概念的多层拼写在此并列登记。

背景：同一红线概念曾四层三拼写——``missing_chars``（engine）/
``missing_char``（rules.yaml warnings:）/``missing_glyph``（l2）——
nullfont 豁免三联改（36f926d/89b2784/0f5c1d6）靠人肉同步，已漂过。
且各层 pattern **有真分歧**而非纯拼写问题：``invalid_utf8`` 曾三层三种
写法，现 engine/l2 同形（裸串 + ``replaced by U\+FFFD`` 变体）、rules
另折叠 FFFD misschar；l2 ``file_not_found`` 是 engine ``missing_graphic`` +
``degraded_file`` 两条的粒度并集；judge 持 gate+nullfont 双生探针。
强收单 pattern 必改行为，故本表按 concept 行登记各层
``(发射名, pattern)``，消费者各取本层切片，分歧并列可见即防再漂。

消费面对应（emit 名逐字节保留旧值，零行为变）：

- ``engine`` → ``compile/engine.py`` ``WARNING_RED_LINES``（全文检索 →
  ``LogInfo.warnings_hit`` → judge ``warn:*`` reasons）
- ``rules``  → ``compile/fixloop/rules.yaml`` ``warnings:`` 段——**镜像**，
  fixloop loader 照旧读 yaml；一致性由 ``tests/test_redlines.py`` pin
- ``l2``     → ``validate/l2.py`` ``_WARNING_RULES`` 行级归类名/模式 +
  ``_REDLINE_CLASSES`` 红线集（``l2_redline`` 标记）
- ``judge``  → ``compile/judge.py`` 门控/探针 regex；``name`` 即 reason
  词干（``missing_character×N`` / ``missing_character_nullfont×N``）

本模块零依赖（不进 compile/ 是因 l2 在 validate/——``compile→validate``
边不存在，反向分层会使只读层依赖消费层；与 textutil/texlog 同层两包可达）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "ENGINE_RED_LINES",
    "L2_REDLINE_CLASSES",
    "L2_WARNING_RULES",
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
#: （logpipe pin#4，与 l2 census 口径同源）。
#: engine ``missing_chars`` / rules ``missing_char`` / judge 门控 / l2
#: ``missing_glyph_nullfont`` 四处共用同一窗口语义（l2 逐行应用时跨行
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

    ``pattern=None`` 表示该层无独立检索模式：l2 派生类（按码点细分）
    或该层把本概念并入他行（见各行注释）。
    """

    name: str
    pattern: str | None = None


@dataclass(frozen=True, slots=True)
class RedLine:
    """一条红线概念的全层登记。"""

    id: str  # canonical 概念 id（注册表内部键，不外发）
    engine: LayerSpec | None = None  # engine.py WARNING_RED_LINES 条目
    rules: LayerSpec | None = None  # rules.yaml warnings: 镜像条目
    l2: LayerSpec | None = None  # l2 _WARNING_RULES 行级类
    l2_redline: bool = False  # l2 类是否入 _REDLINE_CLASSES
    judge: LayerSpec | None = None  # judge 门控/探针 regex + reason 词干


#: 行序 = engine 发射序（invalid_utf8/fffd/missing_chars/missing_graphic/
#: degraded_file）；rules 镜像序、l2 类集均由本表过滤导出。
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
        l2=LayerSpec("invalid_utf8", r"Invalid UTF-8 byte|replaced by U\+FFFD"),
        l2_redline=True,
    ),
    RedLine(
        id="fffd_glyph",
        # 缺 U+FFFD 替换符字形——invalid_utf8 源被排版成缺字。engine 层
        # 独占行（pattern = gate 窗 + FFFD 码点段）；rules 层折叠进
        # invalid_utf8；l2 层为 missing_glyph 命中的码点==0xFFFD 派生类。
        engine=LayerSpec("fffd_glyph", _MISSCHAR_GATE + r'[^\n]*\((?:"|U\+)FFFD\)'),
        l2=LayerSpec("fffd_glyph"),
        l2_redline=True,
    ),
    RedLine(
        id="missing_char",
        # 缺字形红线本体。三层同一 tempered pattern（engine 全文/rules
        # 全文/judge 门控）；l2 行级归类只需裸 ``Missing character:``
        # （nullfont 行已被其独立类先行吃掉，见下行）。
        engine=LayerSpec("missing_chars", _MISSCHAR_GATE),
        rules=LayerSpec("missing_char", _MISSCHAR_GATE),
        l2=LayerSpec("missing_glyph", r"Missing character:"),
        l2_redline=True,
        judge=LayerSpec("missing_character", _MISSCHAR_GATE),
    ),
    RedLine(
        id="missing_char_nullfont",
        # 良性试排吞字——**无一层判红**：judge 进 notes 观察项、l2 独立
        # 类留 by_class/samples 观察面；engine/rules 的排除已内嵌在
        # missing_char 行 tempered pattern 的负向前瞻里。l2 行级类与 judge
        # 探针同 pattern（窗口语义单源）：同行 ``in font `` 已声明真字体后
        # 尾缀 nullfont 不再误豁免；79 列折行豁免要求消费层把续行拼回
        # （窗口跨一个 ``\n`` 分支在逐行应用下天然不触发）。
        l2=LayerSpec("missing_glyph_nullfont", _MISSCHAR_NULLFONT_PROBE),
        judge=LayerSpec("missing_character_nullfont", _MISSCHAR_NULLFONT_PROBE),
    ),
    RedLine(
        id="missing_glyph_cjk",
        # l2 派生类：missing_glyph 命中按 ``_MISSING_CHAR_RX`` 码点
        # ``is_cjk_cp`` 细分（中文静默丢失信号），无独立 pattern。
        l2=LayerSpec("missing_glyph_cjk"),
        l2_redline=True,
    ),
    RedLine(
        id="missing_graphic",
        # l2 ``file_not_found`` 是本行 + degraded_file 的粒度并集
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
        l2=LayerSpec(
            "file_not_found",
            r"File `[^']+' not found|cannot (?:find|open)|Could not locate",
        ),
        l2_redline=True,
    ),
    RedLine(
        id="degraded_file",
        # tectonic 缺包静默降级行（continue-on-errors 把 missing .sty 降为
        # 可恢复，跳包续出残页 pdf——engine-matrix §7.4 暗雷）。l2 侧无
        # 对应类：``^!`` 行在 l2 计入错误而非 warning。
        engine=LayerSpec("degraded_file", r"^!.*(?:File|package)[^\n]*not found"),
        rules=LayerSpec("tectonic_degrade", r"^!+ .*not found"),
    ),
)

REDLINES_BY_ID: Final[dict[str, RedLine]] = {r.id: r for r in REDLINES}


def name_pattern(spec: LayerSpec | None) -> tuple[str, str]:
    """层 spec 窄化为 ``(name, pattern)``——pattern 缺失属登记错误。"""
    if spec is None or spec.pattern is None:
        msg = "redline layer spec lacks pattern"
        raise ValueError(msg)
    return spec.name, spec.pattern


#: ``engine.WARNING_RED_LINES`` 切片：``(发射名, 全文 pattern)`` 保持登记序。
ENGINE_RED_LINES: Final[tuple[tuple[str, str], ...]] = tuple(
    name_pattern(r.engine) for r in REDLINES if r.engine is not None
)

#: rules.yaml ``warnings:`` 段镜像期望 ``(id, pattern)`` 保持登记序——
#: ``tests/test_redlines.py`` 用它 pin 住镜像（yaml 照旧由 fixloop loader 读）。
RULES_WARNINGS: Final[tuple[tuple[str, str], ...]] = tuple(
    name_pattern(r.rules) for r in REDLINES if r.rules is not None
)

#: ``l2._REDLINE_CLASSES`` 切片（含无 pattern 的派生类）。
L2_REDLINE_CLASSES: Final[frozenset[str]] = frozenset(
    r.l2.name for r in REDLINES if r.l2 is not None and r.l2_redline
)

#: ``l2._WARNING_RULES`` 中本表托管的 ``canonical id → (发射名, 行级
#: pattern)``（派生类无 pattern 不在内；非红线 warning 类仍由 l2 本层持有）。
L2_WARNING_RULES: Final[dict[str, tuple[str, str]]] = {
    r.id: name_pattern(r.l2)
    for r in REDLINES
    if r.l2 is not None and r.l2.pattern is not None
}
