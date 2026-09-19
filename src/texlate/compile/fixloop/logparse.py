"""logparse — .log 解析 + taxonomy 分类 (rules/ 目录第一层)。

移植自 bench/py/fixloop.py L48-125 (`first_error`/`classify`), 增强两点
(docs/research/latex/fixloop-rules.md §5 spec):
  - ctx 内 ``l.<N>`` 行号 → ``ErrReport.line_no``
  - ``(`` 开括号文件栈追踪 → ``ErrReport.file_stack`` (定位出错 .tex/.sty)

另加 rules/ ``warnings:`` 段扫描 (docs/08 §4.3 红线) → ``warnings`` 字段;
``invalid_utf8`` 命中在无 '!' 错时升级为 ``warn_utf8`` 伪类别 (v1.1 扩展,
驱动 non_utf8_source 修复轮)。``_FILE_ATTRIBUTED_WARNS`` 的输入侧警告按
警告行文件栈顶归因——系统 texmf/bundle 件与 DOS 魔数 EPS 源降
``warnings_sys`` 观察项, 不再驱动 ``warn_*`` (loginfo ``warnings_hit``/
``warnings_sys`` 裂口在本侧的镜像; utf8census 实证 sys 件坏字节曾使
``warn_utf8`` 每轮空转再生, 污染 census)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from texlate.texlog import (
    CTX_LINES,
    ERR_FILELINE_RE,
    ERR_FNAME,
    FATAL_TRAILER_SRC,
    L_NUM_ROW_SRC,
    L_NUM_SRC,
    TAIL_LINES,
    WARN_MSG_SRC,
    file_stack_at,
    is_dos_eps,
    is_project_file,
    patch_graphic_top,
    update_file_stack,
)

__all__ = ["ErrReport", "Taxonomy", "parse_log", "parse_text"]

#: ``Overfull \vbox ... while \output is active`` —— ``\clearpage`` 输出例程
#: 死循环签名（gr-qc/0104075 实证：``\end{document}`` 期暴走 73,595 页烧满
#: 240s SIGKILL）。健康编译也偶发少量同形告警，成串才判 runaway——
#: 阈值内正常档过量告警永远够不着，病态档轻松过线几个量级。
_RUNAWAY_VBOX_RX = re.compile(r"Overfull \\vbox[^\n]*while \\output is active")
_RUNAWAY_VBOX_MIN = 30
#: ``[N]`` shipout 页标——输出例程页产率签名（str 形供事后判据；活哨侧
#: bytes 编译形 ``compile.proc._PAGE_MARK_RX`` 同词素两介质）。
_RUNAWAY_PAGE_RX = re.compile(r"\[\d+\]")
#: 页产率硬顶——健康论文页数百级以下，病态输出例程 ~400 页/秒
#: （gr-qc/0104075 ~97K 页/240s 实证）。计数制非 max 值：文本偶发的
#: ``[12345]`` 引用/编号单发不误伤。
_RUNAWAY_PAGE_MAX = 10_000
#: vbox 密度闸——签名数须 > DENSITY × 页标数才判暴走：「逐页一条」的
#: 慢性告警是良性排版溢出（1003.2165 实证：46 签名/46 页、36s 干净编译，
#: 旧累计≥30 闸在 ~15.6s 误杀）；签名远超页产才是无进展空转。K=4 容忍
#: 单页多次 ``\output`` 调用（插页/footnote 冲刷、告警先于 ``[N]`` 落行）。
_RUNAWAY_VBOX_DENSITY = 4


def _is_runaway_output(text: str) -> bool:
    r"""Log 输出例程暴走判据——与 ``proc._RunawaySentry`` 活哨同语义双臂。

    - ``[N]`` 页标计数 ≥ ``_RUNAWAY_PAGE_MAX``：病态页产率（单调计数越阈
      即返，不等全扫）；
    - vbox 签名 ≥ ``_RUNAWAY_VBOX_MIN`` ∧ 签名数 > ``_RUNAWAY_VBOX_DENSITY``
      × 页标数：无 shipout 空转签名。密度按**全文终值**评估——中途的高
      密度前奏（告警先于页标落行）不抢判，逐页慢性告警文档永不误伤。
    """
    page_marks = 0
    for page_marks, _m in enumerate(_RUNAWAY_PAGE_RX.finditer(text), 1):
        if page_marks >= _RUNAWAY_PAGE_MAX:
            return True
    vbox_hits = sum(1 for _m in _RUNAWAY_VBOX_RX.finditer(text))
    return (
        vbox_hits >= _RUNAWAY_VBOX_MIN
        and vbox_hits > _RUNAWAY_VBOX_DENSITY * page_marks
    )


#: ctx 内 ``l.N`` 行号——词素单源 = ``texlog.L_NUM_SRC``; 本侧变体加
#: (?m)/``[ \t]*`` 宽容在 ctx blob 内检索 (texlog ``L_NUM_RE`` 是
#: strip 后严格行首形)。非行首的 ``l.5`` 字样 (如 ``file:5:`` 残片/正文)
#: 不误中。
_LINE_NO_RE = re.compile(r"(?m)^[ \t]*" + L_NUM_SRC)
#: subclassify 收窄的冒犯 cs 判定域: ctx 首个 ``l.N`` 行 + cs 名抽取。
#: 行词素单源 = ``texlog.L_NUM_ROW_SRC`` (本侧刻意不加空白宽容——
#: 与上面 blob 检索的宽容形是有意分歧, 行判定走严格 ``^l.``)。
_LN_ROW_RE = re.compile(r"(?m)^" + L_NUM_ROW_SRC + r"[^\n]*")
_CS_NAME_RE = re.compile(r"\\([a-zA-Z@]+)")
#: ctx 头行 ``<name>`` —— TeX 错误上下文对伪输入层 (``<recently read>``
#: 最近 \input/\read、``<argument>`` 宏参展开、``<write>`` 等) 的标记。
#: 顶行止于该层冒犯 token, 故行内末位 cs 是冒犯候选; ``...`` 省略前缀
#: 使"紧跟字面量"不可靠 (1811.03624 ``<argument> ...\@classz \or``)。
#: 语料面 (15k logs, 2026-09-18): 带 cs 的同错头行 = recently read 209 /
#: argument 87 / write 3 文件, 恒居 ctx 行1 (最深层); ``<inserted text>``
#: /``<to be read again>`` 的 token 在续行, 头行本身不携 cs。
_CTX_HEAD_RE = re.compile(r"^[ \t]*<[a-zA-Z ]+>")
# ── capacity payload 提取 (taxonomy ``payload_scan: capacity``) ──
#: ``TeX capacity exceeded, sorry [<name>=<n>]`` bracket 名归一 +
#: ctx 首层 pending cs → pay 形 ``<tag>|<cs>`` (triage 路由键:
#: input_stack=递归, main_memory=暴走, save_size=组泄漏;
#: capacity-scout-2026-09-17 4/4 格皆 input_stack)。bracket 距 exceeded
#: 恒在 ~30 字符内 (file-line 形态 sorry 词可折行到 ctx[1]), 上限 40
#: 防截断 log 误衔下游 ``[x]``; 名段限字母+空格+40 字符上限 (真名
#: ≤22) 且钉 ``=<n>`` —— TeX 容量名固定句式, ``[1]``/``[fig]`` 不误中。
_CAP_BRACKET_RX = re.compile(
    r"TeX capacity exceeded[^\[\]]{0,40}?\[\s*([a-zA-Z][a-zA-Z ]{0,40}?)\s*=\s*\d+\s*\]"
)
#: bracket 原名 → 短 tag。未收名走 ``_cap_bracket_tag`` 全词 snake 兜底
#: (``trie size`` → ``trie_size``), 确定性优先于名表完备。
_CAP_BRACKET_TAG = {
    "input stack size": "input_stack",
    "main memory size": "main_memory",
    "save size": "save_size",
    "pool size": "pool_size",
    "parameter stack size": "parameter_stack",
    "semantic nest size": "semantic_nest",
    "buffer size": "buffer_size",
    "hash size": "hash_size",
    "hash extra": "hash_extra",
    "text input levels": "text_input_levels",
    "grouping levels": "grouping_levels",
    "pattern memory": "pattern_memory",
    "pattern memory ops": "pattern_memory_ops",
    "number of strings": "strings",
    "string vacancies": "string_vacancies",
    "exception dictionary": "exception_dict",
    "font info": "font_info",
    "font mem size": "font_mem",
    "pdf memory size": "pdf_mem",
}
#: cs 词素——expl3 时代 ``_``/``:`` 计字母 (``\l__xeCJK_tmp_int``);
#: nonletter cs 恰一字符 (与 undefined_cs 签同口径)。字母串截 64 字符:
#: max_print_line=10000 病态行可产近万字符 cs 名撑爆 records。
_CAP_CS_RX = re.compile(r"\\([a-zA-Z@_:]{1,64}|[^\s\\{}])")
#: ctx 层头三形 (皆顶格): 宏展开层 ``\name<params>->`` / 伪输入层
#: ``<argument>``/``<to be read again>`` / ``l.N`` 顶层行。缩进续行
#: 永不作层头——宽松前导会把 ``{\@par }`` 残片/``#1<-`` 参绑行误判。
_CAP_MACRO_RX = re.compile(r"^\\([a-zA-Z@_:]{1,64}|[^\s\\{}])")
_CAP_HEAD_RX = re.compile(r"^<[a-zA-Z ]+>")
_CAP_LN_ROW_RX = re.compile(r"^l\.\d+")
# `-file-line-error` 模式下错误行是 `path:line: msg` (无 '!' 前缀) ——
# impl-compile 的 xelatex 命令行带此旗标, 只数 '!' 会漏全部错误。
# Warning 行 (`./f.tex:5: LaTeX Warning: ...`) 同格式但非错误, 须排除,
# 否则 `n_bang==0 → clean` 门永远不通。``ERR_FILELINE_RE`` 单源 =
# ``texlate.texlog``（叶子层——fixloop→compile.engine 环边已掐）。
#: 非错误双腿与 texlog ``_NONERR_*`` 同词素（``WARN_MSG_SRC``/
#: ``FATAL_TRAILER_SRC``）但分隔符刻意更严：本侧 Warning 腿锁 ``: ``
#: 字面单空格（texlog 整行形是 ``:\s*`` 宽松前导）。本对仅在
#: ``ERR_FILELINE_RE`` 闸内咨询（其 ``:\d+: \S`` 已钉死空格+非空白界），
#: 闸内两形等价——保留更严形态防豁免面无意扩到闸外非错误形态行。
_WARN_FILELINE_RE = re.compile(r"^" + ERR_FNAME + r":\d+: " + WARN_MSG_SRC)
#: ``==> Fatal error occurred`` 汇总尾行也是 ``file:line:`` 形态——
#: 同一失败的复述（单空格变体存在），计入会多报一个错误。
_FATAL_TRAILER_RE = re.compile(r"^" + ERR_FNAME + r":\d+:\s*" + FATAL_TRAILER_SRC)


def _is_err_line(ln: str) -> bool:
    """`!` 行或 `-file-line-error` 行 (排除 Warning 伪命中与 ==> 汇总尾行)。"""
    if ln.startswith("!"):
        return True
    return (
        bool(ERR_FILELINE_RE.match(ln))
        and not _WARN_FILELINE_RE.match(ln)
        and not _FATAL_TRAILER_RE.match(ln)
    )


#: ``ErrReport.errs`` 收集上限——全错误面逐条 (err_line, ctx blob) 供次级
#: 错误派发 (twinhead); 病态刷屏 log 的 '!' 行可上千, 截尾保内存。
_ERRS_MAX = 32

#: 首错行**之前**纳入 ``ErrReport.pre`` 的行数——``No file X.fd.`` 型签名
#: 先于错误行落 log (NFSS ``\@input@`` \typeout 在 ``\@latex@error`` 前
#: ~2 行), 前向 ctx8 窗天然够不着。仅 ``use_pre: true`` 的 taxonomy 条目
#: 在 ``pre + head`` 拼接 blob 上检索 (``classify_head`` 实现), 其余条目
#: 保持 head-only——pre 行内宽词 (``Missing``/``Illegal`` 等) 不扰既有
#: 评估序, 不被 syntax 族抢签。
_PRE_LINES = 4

#: 输入侧 byte-level 警告 id——警告行文件栈顶即肇事文件, 按产生者归因
#: (``invalid_utf8`` 是读入字节告警; ``loginfo._scan_error_lines`` 同口径,
#: 两侧共用 texlog 归因原语)。输出侧警告 (``missing_char`` 缺字形——栈顶
#: 是排版执行位而非字源, 且缺字照样落 PDF) 与其余 warn id 刻意不归因,
#: 走全文扫描原语义。归因按**行**进行: 收进本集的 id 其 pattern 须是行内
#: 匹配形 (跨行 pattern 在本面不命中, 与全文 ``re.search`` 有语义差)。
_FILE_ATTRIBUTED_WARNS = frozenset({"invalid_utf8"})


@dataclass(slots=True)
class ErrReport:
    """一次编译的 log 摘要 (首个错误 + 计数 + tail + 结构定位 + warnings)。"""

    first: str | None = None  # 首个 '!' 行 (strip 后)
    ctx: str | None = None  # 首错行起 ≤8 行
    #: 首错行**之前** ≤``_PRE_LINES`` 行 (log 原序)——``No file X.fd.`` 型
    #: 签名先于错误行落盘, 前向 ctx 窗够不着; taxonomy ``use_pre: true``
    #: 条目在 ``pre + head`` blob 上检索 (``classify_head(pre=...)``)。
    pre: str = ""
    n_bang: int = 0  # '!' 行总数
    tail: str = ""  # 末 30 行
    line_no: int | None = None  # ctx 内 l.N 行号
    file_stack: list[str] = field(default_factory=list)  # 出错时打开的文件栈
    #: 首错行之前已弹出的文件名（pop 序；``None`` 非文件配对帧已滤）——
    #: ``File ended while scanning`` 类 runaway 错报位在父文件续行
    #: （``)`` 先于错误打印），``popped_files[-1]`` = 最近关闭的文件 =
    #: 肇事候选（#78）。无错误/无弹栈 → 空。
    popped_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # 命中的 warning id
    #: 系统源命中的输入侧警告 (``<warn_id>@<file>`` 形, loginfo
    #: ``warnings_sys`` 同形同义)——``_FILE_ATTRIBUTED_WARNS`` 按警告行
    #: 文件栈顶归因, 系统 texmf/bundle 件与 DOS 魔数 EPS 源 (``(dos-eps)``
    #: 尾标) 降此观察项, 不进 ``warnings`` 故不驱动 ``warn_*`` 伪类别。
    warnings_sys: list[str] = field(default_factory=list)
    raw: str = ""  # log 全文 (供 escalate_llm context / cases log_excerpt)
    #: 每条错误行 (strip 后 err_line, 其起 ≤CTX_LINES 行 ctx blob), 上限
    #: ``_ERRS_MAX``——次级错误派发 (twinhead) 的全错误面: 首错遮蔽可修
    #: 孪生时 ``classify_errs``/``err_candidates`` 在此表上逐条分类。
    #: 首条恒 = ``(first, ctx)``。
    errs: list[tuple[str, str]] = field(default_factory=list)


def parse_log(
    log_path: Path | None,
    warn_patterns: list[dict[str, Any]] | None = None,
    *,
    project_root: Path | None = None,
) -> ErrReport:
    """读 .log → ErrReport。log 不存在/不可读 → 全空 report (spike L50-55)。

    ``project_root`` 透传 ``parse_text``——``_FILE_ATTRIBUTED_WARNS`` 的
    警告归因根 (编译工作根 ``wdir``)。
    """
    if log_path is None or not Path(log_path).exists():
        return ErrReport()
    try:
        text = Path(log_path).read_text(errors="replace")
    except OSError:
        return ErrReport()
    return parse_text(text, warn_patterns, project_root=project_root)


def _attribute_warns(
    lines: list[str],
    attr_pats: dict[str, re.Pattern[str]],
    project_root: Path | None,
) -> tuple[set[str], dict[str, set[str]]]:
    """逐行扫归因型警告 → ``(工程源命中 id 集, {warn id: 系统源文件名集})``。

    文件栈顶最内具名帧即产生者候选——DOS 魔数 EPS (``(dos-eps)`` 尾标)
    与系统 texmf/bundle 件降 sys 观察项; 空栈/判不出归属保守归工程
    (``loginfo._scan_error_lines`` 同口径, 共用 texlog 归因原语)。
    """
    proj: set[str] = set()
    sys_hits: dict[str, set[str]] = {}
    dos_eps_cache: dict[str, bool] = {}
    stack: list[str | None] = []
    for ln in lines:
        update_file_stack(ln, stack)
        patch_graphic_top(ln, stack)
        for wid, rx in attr_pats.items():
            if not rx.search(ln):
                continue
            inner = next((s for s in reversed(stack) if s), None)
            if is_dos_eps(inner, project_root, dos_eps_cache):
                name = Path(inner).name if inner else "?"
                sys_hits.setdefault(wid, set()).add(f"{name}(dos-eps)")
            elif is_project_file(inner, project_root):
                proj.add(wid)
            else:
                sys_hits.setdefault(wid, set()).add(Path(inner).name if inner else "?")
    return proj, sys_hits


def parse_text(
    text: str,
    warn_patterns: list[dict[str, Any]] | None = None,
    *,
    project_root: Path | None = None,
) -> ErrReport:
    """Log 文本 → ErrReport (tectonic stdout_tail 兜底也走这里)。

    错误行双格式: `^!` (spike 原语义) + `file:line:` (-file-line-error,
    impl-compile xelatex 命令行旗标; Warning 行不计入)。

    ``project_root`` = 编译工作根 (``wdir``): ``_FILE_ATTRIBUTED_WARNS``
    的警告按警告行文件栈顶归因——工程源命中进 ``warnings`` (驱动
    ``warn_*`` 伪类别), 系统 texmf/bundle 件与 DOS 魔数 EPS 源降
    ``warnings_sys``。缺席时绝对路径按 texmf 标记启发式、裸名保守归
    工程 (``loginfo.parse_log`` 同口径——不可归因不掉红线)。
    """
    rep = ErrReport(raw=text)
    lines = text.splitlines()
    first_i: int | None = None
    for i, ln in enumerate(lines):
        if _is_err_line(ln):
            rep.n_bang += 1
            if len(rep.errs) < _ERRS_MAX:
                rep.errs.append((ln.strip(), "\n".join(lines[i : i + CTX_LINES])))
            if first_i is None:
                first_i = i
                rep.first = ln.strip()
                rep.ctx = "\n".join(lines[i : i + CTX_LINES])
                rep.pre = "\n".join(lines[max(0, i - _PRE_LINES) : i])
    rep.tail = "\n".join(lines[-TAIL_LINES:])
    if rep.ctx:
        m = _LINE_NO_RE.search(rep.ctx)
        if m:
            rep.line_no = int(m.group(1))
    if first_i is not None:
        popped: list[str | None] = []
        rep.file_stack = file_stack_at(lines, first_i, popped)
        rep.popped_files = [t for t in popped if t is not None]
    _collect_warnings(rep, text, lines, warn_patterns, project_root)
    return rep


def _collect_warnings(
    rep: ErrReport,
    text: str,
    lines: list[str],
    warn_patterns: list[dict[str, Any]] | None,
    project_root: Path | None,
) -> None:
    """warn_patterns → ``rep.warnings``/``rep.warnings_sys`` (序 = 表序)。

    ``_FILE_ATTRIBUTED_WARNS`` 成员只收工程源命中 (sys 件命中落
    ``warnings_sys`` 观察项, 不驱 ``warn_*``); 其余 id 走全文扫描原语义。
    """
    attr_pats = {
        w["id"]: re.compile(w["pattern"], re.IGNORECASE)
        for w in warn_patterns or []
        if w["id"] in _FILE_ATTRIBUTED_WARNS
    }
    attr_proj, attr_sys = (
        _attribute_warns(lines, attr_pats, project_root) if attr_pats else (set(), {})
    )
    for w in warn_patterns or []:
        wid = w["id"]
        if wid in attr_pats:
            if wid in attr_proj:
                rep.warnings.append(wid)
        elif re.search(w["pattern"], text, re.IGNORECASE | re.MULTILINE):
            rep.warnings.append(wid)
    rep.warnings_sys = [
        f"{wid}@{name}" for wid in sorted(attr_sys) for name in sorted(attr_sys[wid])
    ]


def _payload(entry: dict[str, Any], m: re.Match[str]) -> str | None:
    """Payload 取值: payload_group 指定组, 否则首个非空组 (spike L109)。"""
    if not m.re.groups:
        return None
    grp = entry.get("payload_group")
    if grp is not None:
        return m.group(grp) if grp <= len(m.groups()) else None
    if "payload_group" in entry:  # 显式 null → 无 payload
        return None
    return next((g for g in m.groups() if g), None)


def _ctx_tail_css(ctx: str | None) -> set[str]:
    r"""上下文中冒犯 cs 的三个候选位: ``<head>`` 行末位、展开栈区域末位、``l.N`` 行末。

    ctx 以错误行起 (parse_text L101)——顶层错误时冒犯 cs 落在 ``l.N``
    行内, 宏展开错误时 ``l.N`` 行末只剩表面宏, 真冒犯 cs 是错误行与
    ``l.N`` 行之间展开栈区域的末位 (loop1-2410.00012: ``\\pdfobj`` 藏
    ``\\AddSpotColor`` 体内, l.N 行末 ``\\SpotSpace`` 只是调用点)。
    ``<recently read>``/``<argument>`` 头行顶行止于该层冒犯 token——
    其续行 (该层剩余输入) 携带的 cs 会把区域末位带偏到 post-offending
    噪声 (1801.06287: 头行 ``<argument> \ifnum \pdfshellescape`` 续行
    ``>0 \edef \Gin@extensions`` → 区域末位 ``Gin@extensions`` 非冒犯)。
    """
    out: set[str] = set()
    if not ctx:
        return out
    lines = ctx.splitlines()
    ln_i = next((i for i, ln in enumerate(lines) if _LN_ROW_RE.match(ln)), len(lines))
    for ln in lines[1:ln_i]:
        if _CTX_HEAD_RE.match(ln) and (hits := _CS_NAME_RE.findall(ln)):
            out.add(hits[-1])
    if hits := _CS_NAME_RE.findall("\n".join(lines[1:ln_i])):
        out.add(hits[-1])
    if ln_i < len(lines) and (hits := _CS_NAME_RE.findall(lines[ln_i])):
        out.add(hits[-1])
    return out


def _cap_bracket_tag(raw: str) -> str:
    """Bracket 原名 → 短 tag (常见名查表, 未收名 snake 兜底保确定性)。"""
    name = " ".join(raw.split()).lower()
    if name in _CAP_BRACKET_TAG:
        return _CAP_BRACKET_TAG[name]
    return re.sub(r"[^a-z0-9]+", "_", name).strip("_")


def _capacity_pending(lines: list[str]) -> str | None:
    r"""Capacity ctx 首层 pending cs——TeX 上下文栈最深层印在最前。

    层头三形各取位: 宏展开层 ``\name<params>->`` 的 name 即在扩宏 (行首
    cs); ``<argument>``/``<recently read>`` 伪层头行止于冒犯 token (行
    末 cs); ``<to be read again>``/``<inserted text>`` 头行无 token,
    pending 在续行 (续行首 cs); ``l.N`` 顶层行末 cs 为冒犯 token, 行内
    无 cs 时续行 (源行后半 = 待读 token) 首 cs 兜底。非层头行 (包行
    折行残片/``#1<-`` 参绑行/空行) 跳过。
    """
    grab_next = False  # 上层头无 cs——token 在续行
    for ln in lines:
        hits = _CAP_CS_RX.findall(ln)
        if grab_next:
            if hits:
                return hits[0]
            grab_next = False
        if (m := _CAP_MACRO_RX.match(ln)) is not None:
            return m.group(1)
        if _CAP_HEAD_RX.match(ln) or _CAP_LN_ROW_RX.match(ln):
            if hits:
                return hits[-1]
            grab_next = True
    return None


def _capacity_payload(first: str | None, ctx: str | None) -> str | None:
    """``TeX capacity exceeded`` → ``<tag>``/``<tag>|<cs>``/``?|<cs>``/None。

    bracket 在错误行本体 (file-line 形态可折行到 ctx[1]) 故搜全 head;
    pending cs 取 ctx 首层 (``_capacity_pending``)。截断 log 无 bracket
    时 ``?`` 占位保两字段形。
    """
    blob = (first or "") + ("\n" + ctx if ctx else "")
    m = _CAP_BRACKET_RX.search(blob)
    tag = _cap_bracket_tag(m.group(1)) if m else None
    lines = ctx.splitlines() if ctx else []
    # parse_text 的 ctx 窗首行=错误行本身 (head 内重复两次) —— 跳过
    if lines and first and lines[0].strip() == first:
        lines = lines[1:]
    tok = _capacity_pending(lines)
    if tag is None:
        return f"?|{tok}" if tok else None
    return f"{tag}|{tok}" if tok else tag


#: ``input_stack|<cs>`` pending cs 显式名单 → ``input_stack`` 类别重路由:
#: 命中者全是上游 TeX-exec 宏递归帧 (内核 ``\@nomath`` 守卫帧 / expl3
#: quark 扫描哨兵族), 非 ``\input`` 循环——无任何源改写可修
#: (ifdiag-lane 2026-09-19: ``@nomath``@1404.0037 与
#: ``__quark_if_recursion_tail:w``@1706.00076 base 臂同炸, paper-authentic)。
#: verdict ``unfixable:{cat}`` 直挂 cat——独立 cat 让真递归帧不再混进
#: ``unfixable:capacity`` 的可修假簇; texlate 可修面 (``cref@resetstack``
#: restatable 族, restatdiag) 刻意不收, 留 ``capacity`` 走修复派发。
_CAP_UPSTREAM_RECURSION_CS = frozenset(
    {
        "@nomath",
        "q_recursion_tail",
        "__quark_if_recursion_tail:w",
        "__quark_if_recursion_tail_break:nN",
        "__quark_if_recursion_tail_stop:n",
        "__quark_if_recursion_tail_stop_do:nn",
    }
)


def _cap_verdict_cat(entry_id: str, pay: str | None) -> str:
    """Capacity ``input_stack|<cs>`` 且 cs 属上游递归帧 → ``input_stack`` 类。"""
    if entry_id == "capacity" and pay is not None:
        tag, _, cs = pay.partition("|")
        if tag == "input_stack" and cs in _CAP_UPSTREAM_RECURSION_CS:
            return "input_stack"
    return entry_id


#: taxonomy ``payload_scan:`` 键的 python 提取器注册表 (head-scope 专用,
#: 签名 ``(first, ctx) -> pay``)。未收名静默回退 regex payload_group 取值
#: —— taxonomy 段无键白名单校验, 与未知可选键同口径。
_PAYLOAD_SCANS: dict[str, Callable[[str | None, str | None], str | None]] = {
    "capacity": _capacity_payload,
}


class Taxonomy:
    """rules/ taxonomy 段的编译态: scope 三段评估序照 spike L67-125。"""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        """编译 taxonomy 条目 → head/tail/warnings 三个有序评估表。"""
        self.head: list[tuple[dict[str, Any], re.Pattern[str]]] = []
        self.tail: list[tuple[dict[str, Any], re.Pattern[str]]] = []
        self.warn: list[dict[str, Any]] = []
        for e in entries:
            scope = e.get("scope", "head")
            if scope == "head":
                self.head.append((e, re.compile(e["pattern"], re.IGNORECASE)))
            elif scope == "tail":
                self.tail.append((e, re.compile(e["pattern"], re.IGNORECASE)))
            elif scope == "warnings":
                self.warn.append(e)
        self.warn_cats = {e["id"] for e in self.warn}

    def classify(  # scope 三段+抢占评估序即分支
        self, rep: ErrReport, *, timed_out: bool = False
    ) -> tuple[str | None, str | None]:
        """→ (category, payload)。payload 供规则定位 (文件名/字体名/cs 名)。"""
        if timed_out:
            # 超时被杀编译细分：输出例程暴走（``\clearpage`` 死循环刷屏
            # Overfull \vbox）与「真大档超时」分流——前者重跑必再暴走，
            # 归因面挂 ``runaway_output`` 让 triage/排除臂与普通超时分开。
            if _is_runaway_output(rep.raw or rep.tail):
                return "runaway_output", None
            return "timeout", None
        head_hit = self.classify_head(rep.first, rep.ctx, pre=rep.pre)
        if head_hit is not None:
            return self._tail_preempt(head_hit, rep)
        # —— 无 '!' 行: tail 段回溯 (交互式缺文件/Emergency) ——
        blob = rep.tail
        for entry, pat in self.tail:
            m = pat.search(blob)
            if m and (not entry.get("guard") or re.search(entry["guard"], blob)):
                return entry["id"], _payload(entry, m)
        # —— 仍不中: warning 驱动的伪类别 (v1.1, docs/08 §5.2) ——
        for entry in self.warn:
            if entry.get("warn_id") in rep.warnings:
                return entry["id"], None
        return ("other" if rep.first else "clean"), None

    def classify_head(
        self, first: str | None, ctx: str | None, *, pre: str | None = None
    ) -> tuple[str | None, str | None] | None:
        """单条错误 (err 行 + ctx blob) 的 head-scope 分类 → (cat, pay); 无命中 → None。

        ``classify`` 首错分类块原样抽出 (评估序/subclassify 收窄不变)——
        ``classify_errs``/``err_candidates`` 对 ``rep.errs`` 每条错误行
        独立分类时无 tail/warn 回溯面, 调用方决定落空兜底。

        ``pre`` = 错误行之前的上下文 (``ErrReport.pre``): 仅 ``use_pre:
        true`` 的条目在 ``pre + head`` 拼接 blob 上检索——签名先于错误
        行落 log 的家族 (``No file X.fd.`` → NFSS 硬错) 由此可达; 其余
        条目保持 head-only, pre 行内宽词不扰既有评估序。
        """
        if not first:
            return None
        head = first + ("\n" + ctx if ctx else "")
        pre_head = (pre + "\n" + head) if pre else head
        for entry, pat in self.head:
            m = pat.search(pre_head if entry.get("use_pre") else head)
            if not m:
                continue
            scan = _PAYLOAD_SCANS.get(str(entry.get("payload_scan") or ""))
            pay = scan(first, ctx) if scan is not None else _payload(entry, m)
            sub = entry.get("subclassify")
            if sub:
                # 冒犯域收窄 (audit-2026-09-16): 细分命中须==主 payload
                # 或 l.N 行末 cs——ctx8 回显里混入的同名 token (如
                # \pdfoutput 环境引用) 不再把真 undefined_cs 抢路由成
                # pdftex_prim。
                allowed = {pay} if pay else set()
                allowed.update(_ctx_tail_css(ctx))
                grp = sub.get("payload_group")
                for sm in re.finditer(sub["pattern"], head):
                    spay = (
                        sm.group(grp)
                        if grp
                        else next((g for g in sm.groups() if g), None)
                    )
                    if spay is not None and spay in allowed:
                        return sub["into"], spay
            return _cap_verdict_cat(entry["id"], pay), pay
        return None

    def err_candidates(
        self, rep: ErrReport
    ) -> list[tuple[str | None, str | None, str, str]]:
        """``rep.errs`` 逐条 head 分类 → (cat, pay, err_line, ctx_blob) 去重保错误序。

        次级错误派发 (twinhead) 的候选面: 携源位供 ``ctx.round`` 重指与
        dispatch ErrReport 构造。无 head 命中的真实错误行归
        ``("other", None)``——它确实出现在编译 log, 只是 taxonomy 未收录。
        """
        out: list[tuple[str | None, str | None, str, str]] = []
        seen: set[tuple[str | None, str | None]] = set()
        for line, blob in rep.errs:
            cat, pay = self.classify_head(line, blob) or ("other", None)
            if (cat, pay) in seen:
                continue
            seen.add((cat, pay))
            out.append((cat, pay, line, blob))
        return out

    def classify_errs(self, rep: ErrReport) -> list[tuple[str | None, str | None]]:
        """``rep.errs`` 全错误面逐条 head 分类 → (cat, pay) 去重保错误序。

        ``err_candidates`` 的源位投影面——只关心类别构成的消费侧
        (次级派发决策/judge 型归因) 用这个就够。
        """
        return [(cat, pay) for cat, pay, _line, _blob in self.err_candidates(rep)]

    def _tail_preempt(
        self, head_hit: tuple[str | None, str | None], rep: ErrReport
    ) -> tuple[str | None, str | None]:
        """致命 tail 抢占: ``preempts`` 弱类别表内的 head 命中可被尾错夺路由。

        regress4-2410.00012——log 尾的 Emergency stop/File-not-found 是更
        可行动的真杀手, 不该被先报的非致命头错 (如上游包内
        undefined_cs) 抢走路由。
        """
        for entry, pat in self.tail:
            pre = entry.get("preempts")
            if not pre or head_hit[0] not in pre:
                continue
            tm = pat.search(rep.tail)
            if tm and (not entry.get("guard") or re.search(entry["guard"], rep.tail)):
                return entry["id"], _payload(entry, tm)
        return head_hit
