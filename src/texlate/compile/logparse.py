"""logparse — .log 解析 + taxonomy 分类 (compile 层共享地基, C3 归位)。

原 ``fixloop/logparse.py``——log 解析/taxonomy 是 compile 层共享件
(``loginfo``/``judge``/``proc`` 同层消费), 上提后 fixloop 向下消费
(旧路径 ``texlate.compile.fixloop.logparse`` 经 re-export shim 守恒,
名面全量含私名; 仅 ``_WARN_FILELINE_RE``/``_FATAL_TRAILER_RE``/
``_attribute_warns`` 三死件随事件流重构退场)。

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

C8 单遍事件流 (architecture-review-2026-09-19 §8): 文件栈走查/错误行
判定单源 = ``texlog.iter_log_events``——``parse_text`` 一遍事件流上同
时做错误面投影 (``first``/``ctx``/``errs``/``file_stack``/``popped_files``)
与归因警告投影 (``_AttrWarns.feed``), 不再自维护栈、不再 ``file_stack_at``
回放、不再私有错误行判定 (三消费面同词素三写已并)。
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
    L_NUM_ROW_SRC,
    L_NUM_SRC,
    TAIL_LINES,
    LogEvent,
    is_dos_eps,
    is_project_file,
    iter_log_events,
    match_error_line,
)

__all__ = ["ErrReport", "Taxonomy", "parse_log", "parse_text"]

#: ``Overfull \vbox ... while \output is active`` —— ``\clearpage`` 输出例程
#: 死循环签名（gr-qc/0104075 实证：``\end{document}`` 期暴走 73,595 页烧满
#: 240s SIGKILL）。健康编译也偶发少量同形告警，成串才判 runaway——
#: 阈值内正常档过量告警永远够不着，病态档轻松过线几个量级。
_RUNAWAY_VBOX_RX = re.compile(r"Overfull \\vbox[^\n]*while \\output is active")
_RUNAWAY_VBOX_MIN = 30
#: ``[N]`` shipout 页标候选——输出例程页产率签名（str 形供事后判据；
#: 活哨侧 bytes 编译形 ``compile.proc._PAGE_MARK_RX`` 同词素两介质）。
#: 匹配只找候选；是否计为 shipout 由消费侧的单调包络判定（见下）。
_RUNAWAY_PAGE_RX = re.compile(r"\[\d+\]")
#: 页产率硬顶——健康论文页数百级以下，病态输出例程 ~400 页/秒
#: （gr-qc/0104075 ~97K 页/240s 实证）。计数走**单调包络**：真 shipout
#: 序号只增不减（2609.19748 实测 9623 标记全序、2608.09867 19084 全
#: 序），仅 ``n >= 已计最大值`` 的页标入计——收敛文档打印万级非序
#: 方括数字（索引/引用/``\typeout`` 阵列）至多贡献 ~ln(n) 个左向右
#: 极大值，不再假触（killsem2 census 开放缺口）。
_RUNAWAY_PAGE_MAX = 10_000
#: vbox 密度闸——签名数须 > DENSITY × 页标数才判暴走：「逐页一条」的
#: 慢性告警是良性排版溢出（1003.2165 实证：46 签名/46 页、36s 干净编译，
#: 旧累计≥30 闸在 ~15.6s 误杀）；签名远超页产才是无进展空转。K=4 容忍
#: 单页多次 ``\output`` 调用（插页/footnote 冲刷、告警先于 ``[N]`` 落行）。
_RUNAWAY_VBOX_DENSITY = 4


def _is_runaway_output(text: str) -> bool:
    r"""Log 输出例程暴走判据——与 ``proc._RunawaySentry`` 活哨同语义双臂。

    - ``[N]`` 页标**单调包络计数** ≥ ``_RUNAWAY_PAGE_MAX``：病态页产率。
      仅 ``n >= 已计最大值`` 的页标入计（真 shipout 序号只增不减，冻结
      计数器暴走 ``[1][1]…`` 同页号仍计）——非序方括噪声只贡献左向右
      极大值 ~ln(n) 个；越阈即返，不等全扫；
    - vbox 签名 ≥ ``_RUNAWAY_VBOX_MIN`` ∧ 签名数 > ``_RUNAWAY_VBOX_DENSITY``
      × 页标**原始总数**：无 shipout 空转签名。分母不走包络——噪声撑
      大分母是豁免方向（保守），pagenumbering 复位档真 shipout 不漏计。
      密度按**全文终值**评估——中途的高密度前奏（告警先于页标落行）
      不抢判，逐页慢性告警文档永不误伤。
    """
    page_marks = 0
    env = 0
    last = -1
    for m in _RUNAWAY_PAGE_RX.finditer(text):
        page_marks += 1
        n = int(m.group(0)[1:-1])
        if n >= last:
            env += 1
            last = n
            if env >= _RUNAWAY_PAGE_MAX:
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
# 否则 `n_bang==0 → clean` 门永远不通。
#: 判定单源 = ``texlog.match_error_line``——本侧原 ``_WARN_FILELINE_RE``/
#: ``_FATAL_TRAILER_RE`` 双腿 (``: `` 单空格严形态) 与 texlog 消息面锚定
#: 形在 ``file:line:`` 闸内等价 (ROW 捕获组已钉 ``: \S`` 界, 闸内两形同
#: 集)——1504 log 语料零分歧, 词素并单源。


def _is_err_line(ln: str) -> bool:
    """`!` 行或 `-file-line-error` 行 (排除 Warning 伪命中与 ==> 汇总尾行)。

    判定单源 = ``texlog.match_error_line``——rules/ yaml 注释面与本层旧
    钉点经此名消费, 薄 delegate 保旧面。
    """
    return match_error_line(ln) is not None


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

#: 首错 ctx8 窗**之后**纳入 ``ErrReport.post`` 的行数——错误块的滞后
#: 落盘签名: graphicx ``File `X' not found`` 的 ``I could not locate the
#: file with any of these extensions:`` errhelp 恒居错误行 +8, 恰出 ctx8
#: 右缘 (extless lane failmine4 9-cell 实录); ``l.N`` 回显行折行时 errhelp
#: 可再后移 1-2 行, 6 行余量覆盖。仅 ``use_post: true`` 的 taxonomy
#: 条目在 ``head + post`` 拼接 blob 上检索 (``classify_head`` 实现)——
#: per-err ctx blob 不带 post (``err_candidates`` 面同 ``use_pre`` 先例:
#: 扩展窗特征仅首错 ``classify()`` 可达)。
_POST_LINES = 6

#: 输入侧 byte-level 警告 id——警告行文件栈顶即肇事文件, 按产生者归因
#: (``invalid_utf8`` 是读入字节告警; ``loginfo._scan_error_lines`` 同口径,
#: 两侧共用 texlog 归因原语)。输出侧警告 (``missing_char`` 缺字形——栈顶
#: 是排版执行位而非字源, 且缺字照样落 PDF) 与其余 warn id 刻意不归因,
#: 走全文扫描原语义。归因按**行**进行: 收进本集的 id 其 pattern 须是行内
#: 匹配形 (跨行 pattern 在本面不命中, 与全文 ``re.search`` 有语义差)。
_FILE_ATTRIBUTED_WARNS = frozenset({"invalid_utf8"})


@dataclass(slots=True)
class _AttrWarns:
    """归因型警告 (``_FILE_ATTRIBUTED_WARNS``) 的逐行投影状态——C8 事件流件。

    ``parse_text`` 事件遍内逐行喂 ``feed``: 事件 ``inner`` (栈顶最内具名
    帧) 即产生者候选——DOS 魔数 EPS (``(dos-eps)`` 尾标) 与系统
    texmf/bundle 件降 ``sys`` 观察项; 空栈/判不出归属保守归工程
    (``loginfo`` 同口径, 共用 texlog 归因原语)。原 ``_attribute_warns``
    第二遍栈走查已并进 ``parse_text`` 主遍。
    """

    pats: dict[str, re.Pattern[str]] = field(default_factory=dict)
    proj: set[str] = field(default_factory=set)
    sys: dict[str, set[str]] = field(default_factory=dict)
    dos_eps_cache: dict[str, bool] = field(default_factory=dict)

    def feed(self, ev: LogEvent, project_root: Path | None) -> None:
        """单行警告归因——命中 id pattern 时按 ``ev.inner`` 归因 proj/sys。"""
        for wid, rx in self.pats.items():
            if not rx.search(ev.line):
                continue
            inner = ev.inner
            if is_dos_eps(inner, project_root, self.dos_eps_cache):
                name = Path(inner).name if inner else "?"
                self.sys.setdefault(wid, set()).add(f"{name}(dos-eps)")
            elif is_project_file(inner, project_root):
                self.proj.add(wid)
            else:
                self.sys.setdefault(wid, set()).add(Path(inner).name if inner else "?")


@dataclass(slots=True)
class ErrReport:
    """一次编译的 log 摘要 (首个错误 + 计数 + tail + 结构定位 + warnings)。"""

    first: str | None = None  # 首个 '!' 行 (strip 后)
    ctx: str | None = None  # 首错行起 ≤8 行
    #: 首错行**之前** ≤``_PRE_LINES`` 行 (log 原序)——``No file X.fd.`` 型
    #: 签名先于错误行落盘, 前向 ctx 窗够不着; taxonomy ``use_pre: true``
    #: 条目在 ``pre + head`` blob 上检索 (``classify_head(pre=...)``)。
    pre: str = ""
    #: 首错 ctx8 窗**之后** ≤``_POST_LINES`` 行 (log 原序)——错误块滞后
    #: 落盘签名 (graphicx ``I could not locate ... extensions:`` errhelp
    #: 恒居错误行 +8, 恰出 ctx8 右缘) 由此可达; taxonomy ``use_post:
    #: true`` 条目在 ``head + post`` blob 上检索
    #: (``classify_head(post=...)``)。
    post: str = ""
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


def parse_text(
    text: str,
    warn_patterns: list[dict[str, Any]] | None = None,
    *,
    project_root: Path | None = None,
) -> ErrReport:
    """Log 文本 → ErrReport (tectonic stdout_tail 兜底也走这里)。

    错误行双格式: `^!` (spike 原语义) + `file:line:` (-file-line-error,
    impl-compile xelatex 命令行旗标; Warning 行不计入)。

    C8 单遍事件流: ``iter_log_events`` 一遍内同做错误面投影与
    ``_FILE_ATTRIBUTED_WARNS`` 归因投影——``file_stack``/``popped_files``
    沿用旧 ``file_stack_at`` **排他**口径 (首错行自身不入栈/不计弹栈,
    事件遍里以 ``prev_stack``/``popped_hist`` 前置快照守恒, 与
    l2/loginfo 含行快照是有意分歧, 不并)。

    ``project_root`` = 编译工作根 (``wdir``): ``_FILE_ATTRIBUTED_WARNS``
    的警告按警告行文件栈顶归因——工程源命中进 ``warnings`` (驱动
    ``warn_*`` 伪类别), 系统 texmf/bundle 件与 DOS 魔数 EPS 源降
    ``warnings_sys``。缺席时绝对路径按 texmf 标记启发式、裸名保守归
    工程 (``loginfo.parse_log`` 同口径——不可归因不掉红线)。
    """
    rep = ErrReport(raw=text)
    lines = text.splitlines()
    attr = _AttrWarns(
        pats={
            w["id"]: re.compile(w["pattern"], re.IGNORECASE)
            for w in warn_patterns or []
            if w["id"] in _FILE_ATTRIBUTED_WARNS
        }
    )
    first_i: int | None = None
    #: 排他口径前置快照——``prev_stack`` = 上一事件的后栈 (即旧
    #: ``file_stack_at(lines, first_i)`` 回放终态), ``popped_hist`` =
    #: 首错行之前的弹栈史 (``)`` 先于错误行打印, runaway 报位在父文件
    #: 续行, 真肇事件靠它找回 #78); 首错捕获点即冻结。
    prev_stack: tuple[str | None, ...] = ()
    popped_hist: list[str | None] = []
    for ev in iter_log_events(lines):
        if ev.err is not None:
            rep.n_bang += 1
            if len(rep.errs) < _ERRS_MAX:
                rep.errs.append(
                    (ev.err.head, "\n".join(lines[ev.i : ev.i + CTX_LINES]))
                )
            if first_i is None:
                first_i = ev.i
                rep.first = ev.err.head
                rep.ctx = "\n".join(lines[ev.i : ev.i + CTX_LINES])
                rep.pre = "\n".join(lines[max(0, ev.i - _PRE_LINES) : ev.i])
                rep.post = "\n".join(
                    lines[ev.i + CTX_LINES : ev.i + CTX_LINES + _POST_LINES]
                )
                rep.file_stack = [s for s in prev_stack if s]
                rep.popped_files = [t for t in popped_hist if t is not None]
        if first_i is None:
            popped_hist.extend(ev.popped)
            prev_stack = ev.stack
        attr.feed(ev, project_root)
    rep.tail = "\n".join(lines[-TAIL_LINES:])
    if rep.ctx:
        m = _LINE_NO_RE.search(rep.ctx)
        if m:
            rep.line_no = int(m.group(1))
    _collect_warnings(rep, text, warn_patterns, attr)
    return rep


def _collect_warnings(
    rep: ErrReport,
    text: str,
    warn_patterns: list[dict[str, Any]] | None,
    attr: _AttrWarns,
) -> None:
    """warn_patterns → ``rep.warnings``/``rep.warnings_sys`` (序 = 表序)。

    ``_FILE_ATTRIBUTED_WARNS`` 成员只收工程源命中 (sys 件命中落
    ``warnings_sys`` 观察项, 不驱 ``warn_*``)——归因投影由 ``parse_text``
    事件遍产出的 ``attr`` 给出; 其余 id 走全文扫描原语义。
    """
    for w in warn_patterns or []:
        wid = w["id"]
        if wid in attr.pats:
            if wid in attr.proj:
                rep.warnings.append(wid)
        elif re.search(w["pattern"], text, re.IGNORECASE | re.MULTILINE):
            rep.warnings.append(wid)
    rep.warnings_sys = [
        f"{wid}@{name}" for wid in sorted(attr.sys) for name in sorted(attr.sys[wid])
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


# ── undefined_cs payload 提取 (taxonomy ``payload_scan: undefined_cs``) ──
_UNDEF_MARK = "Undefined control sequence"
#: 顶行末位 cs 的字母串|单字符 nonletter 两支——与 taxonomy 条目 regex
#: 同词素 (``[a-zA-Z@]+`` | ``[^\s\\{}]``)。
_UNDEF_ANY_CS_RX = re.compile(r"\\([a-zA-Z@]+|[^\s\\{}])")
#: ``\GenericError``-led 语境的内核错误渲染宏族: 真冒犯 cs 被吞进 ``#N``
#: 参槽, ctx 顶行末位只印渲染机 token——抓来即 ``undefined_cs|GenericError``
#: 死 payload (0712.1016 ``\diagchar`` / 2105.03751 ``\footnote`` 实证)。
#: 处方集 {GenericError errhelp err@ MessageBreak @err@ @empty @ehc @ehd}
#: + 同族渲染层头 (PackageError/ClassError/latexerr 系 \@latex@error 链
#: 各层头名) 与 \errmessage 本体——同失败模同排除。
_UNDEF_KERNEL_CS = frozenset(
    {
        "GenericError",
        "PackageError",
        "ClassError",
        "latexerr",
        "latex@error",
        "errmessage",
        "errhelp",
        "err@",
        "MessageBreak",
        "@err@",
        "@empty",
        "@ehc",
        "@ehd",
    }
)


def _undefined_cs_payload(first: str | None, ctx: str | None) -> str | None:
    r"""``Undefined control sequence`` → 冒犯 cs 名; 内核渲染宏占位时向 ``l.N`` 行回退。

    主抓取与条目 regex 同语义: marker 行的下一行 (ctx 顶行) 末位 cs。
    ``\GenericError``-led ctx 的顶行末位是内核错误渲染宏 (真冒犯 cs 藏
    ``#N`` 参内)——落入 ``_UNDEF_KERNEL_CS`` 时改取 ``l.N`` 行末位非内核
    **字母** cs (顶层源行回显, ``\(``/``\)`` 类 nonletter 噪声滤除;
    0712.1016 ``l.625 函数 \(\diagchar{'00}\)`` 行末 ``\)`` 非冒犯);
    ``l.N`` 行无获再扫中间展开层各行末位 cs (pending 位), 仍无 → None。
    ``l.N`` 先于中间层评估: 中间层末位可为 ``\endgroup`` 等渲染机残片,
    ``l.N`` 行字母 cs 是更稳的冒犯指征。

    ctx 缺席或无 marker 时退回 ``first`` 同构扫描——head 内嵌整段
    (``! ...`` + ``l.N`` 同块, 调用方不拆 ctx) 的直调面由此可达。
    """
    lines = (ctx or "").splitlines()
    i = next((k for k, ln in enumerate(lines) if _UNDEF_MARK in ln), -1)
    if i < 0:
        lines = (first or "").splitlines()
        i = next((k for k, ln in enumerate(lines) if _UNDEF_MARK in ln), 0)
    rest = lines[i + 1 :]
    if not rest:
        return None
    hits = _UNDEF_ANY_CS_RX.findall(rest[0])
    if hits and hits[-1] not in _UNDEF_KERNEL_CS:
        return hits[-1]
    ln_i = next((k for k, ln in enumerate(rest) if _LN_ROW_RE.match(ln)), len(rest))
    if ln_i < len(rest):
        for cs in reversed(_CS_NAME_RE.findall(rest[ln_i])):
            if cs not in _UNDEF_KERNEL_CS:
                return cs
    for ln in rest[1:ln_i]:
        hits = _UNDEF_ANY_CS_RX.findall(ln)
        if hits and hits[-1] not in _UNDEF_KERNEL_CS:
            return hits[-1]
    return None


#: taxonomy ``payload_scan:`` 键的 python 提取器注册表 (head-scope 专用,
#: 签名 ``(first, ctx) -> pay``)。未收名静默回退 regex payload_group 取值
#: —— taxonomy 段无键白名单校验, 与未知可选键同口径。
_PAYLOAD_SCANS: dict[str, Callable[[str | None, str | None], str | None]] = {
    "capacity": _capacity_payload,
    "undefined_cs": _undefined_cs_payload,
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
        head_hit = self.classify_head(rep.first, rep.ctx, pre=rep.pre, post=rep.post)
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
        self,
        first: str | None,
        ctx: str | None,
        *,
        pre: str | None = None,
        post: str | None = None,
    ) -> tuple[str | None, str | None] | None:
        """单条错误 (err 行 + ctx blob) 的 head-scope 分类 → (cat, pay); 无命中 → None。

        ``classify`` 首错分类块原样抽出 (评估序/subclassify 收窄不变)——
        ``classify_errs``/``err_candidates`` 对 ``rep.errs`` 每条错误行
        独立分类时无 tail/warn 回溯面, 调用方决定落空兜底。

        ``pre`` = 错误行之前的上下文 (``ErrReport.pre``): 仅 ``use_pre:
        true`` 的条目在 ``pre + head`` 拼接 blob 上检索——签名先于错误
        行落 log 的家族 (``No file X.fd.`` → NFSS 硬错) 由此可达; 其余
        条目保持 head-only, pre 行内宽词不扰既有评估序。

        ``post`` = ctx8 窗之后的上下文 (``ErrReport.post``): 仅 ``use_post:
        true`` 的条目在 ``head + post`` 拼接 blob 上检索——错误块的滞后
        落盘签名 (graphicx ``File `X' not found`` 的 ``I could not locate
        the file with any of these extensions:`` errhelp 恒居错误行 +8,
        恰出 ctx8 右缘) 由此可达; 与 ``use_pre`` 同例, per-err 分类面
        (``err_candidates``) 不带 post, 扩展窗特征仅首错 ``classify()``
        可达。
        """
        if not first:
            return None
        head = first + ("\n" + ctx if ctx else "")
        for entry, pat in self.head:
            blob = head
            if pre and entry.get("use_pre"):
                blob = pre + "\n" + blob
            if post and entry.get("use_post"):
                blob = blob + "\n" + post
            m = pat.search(blob)
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
