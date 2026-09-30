r"""``_OPERAND_SCAN_STOP`` 扫描终止符表 + arith 裸 ``=`` 臂（operandfix 车道）。

inputtail（0697124）只排 ``INPUT_SCAN_CMDS``∪``{endinput}``——operandcensus
普查把同形孤儿面量出：TeX 数/胶扫遇**不可展开命令**即止，被
``_OPERAND_FACTOR``/``_OPERAND_BASE`` 吃进的命令 cs 只把其后随参孤儿化：
``\setbox0=\hbox{`` 盒体（corpus 493 命中/216 篇）、``\message{`` 日志
载荷、``\end{env}`` 环境名、``\vskip3pt plus1pt`` 的 ``plus1pt``、
``\setlength\parskip{3pt}`` 的 ``{3pt}``。修复双臂：

- ``_OPERAND_SCAN_STOP``（_common.py）：名表并集 + 内联原语集 + ``if*``
  前瞻模式——终止符 cs 永不作操作数，回本族分派（boundary/protect/
  cond/透明/探针）自收其参。寄存器/内部量/盒引用/数产生子（``\count``/
  ``\baselineskip``/``\fontdimen``/``\box``/``\the``/``\numexpr``）不排。
- ``_TAIL_RX["arith"]`` ``(by|=)`` 臂增裸 ``=`` 备选——rval 是终止符
  （或非操作数）时 ``=`` 仍随赋值收，不裸落 surface（``\toks0={`` 的
  ``=`` 泄漏同源收编）。

镜像面无复制：group.py ``_grp_tail_end``/pending.py/args.py/mainloop.py
全部复用同一编译 ``_TAIL_RX``——新表自动贯通字节/token 两路。

每条过公共不变式（``reconstruct == tex`` + 校验零告警 + 无缝平铺）。
"""

import re

from _segkit import ph_bodies, scan_prose
from _segkit import (
    scan_art as scan,
)
from conftest import blob

from texlate.latex.segmenter._common import _OPERAND_CS

_OPERAND_CS_RX = re.compile(_OPERAND_CS)


# ----------------------------------------------------------- 终止符集成员钉版


def test_scan_stop_membership() -> None:
    r"""排除侧/保留侧双向钉版——终止符不收操作数，寄存器/盒引用/数产生子
    照吃。"""
    for name in (
        "hbox",
        "vbox",
        "vtop",
        "vcenter",
        "setbox",
        "message",
        "write",
        "end",
        "begin",
        "par",
        "item",
        "fi",
        "setlength",
        "vskip",
        "hrule",
        "includegraphics",
        "cite",
        "section",
        "newcommand",
        "openout",
        "special",
        "csname",
        "penalty",
        "kern",
        "relax",
    ):
        assert not _OPERAND_CS_RX.match("\\" + name), name
    for name in (
        "count",
        "dimen",
        "skip",
        "muskip",
        "toks",
        "font",
        "fontdimen",
        "skewchar",
        "baselineskip",
        "parskip",
        "box",
        "copy",
        "lastbox",
        "vsplit",
        "the",
        "number",
        "romannumeral",
        "numexpr",
        "pdfoutput",
        "everypar",
        "foo",
    ):
        assert _OPERAND_CS_RX.match("\\" + name), name


def test_if_family_pattern_excluded() -> None:
    r"""``if*`` 前瞻模式——``\ifnum``/``\ifx``/``\iftoggle`` 全族不收，
    ``\if`` 光杆同排；``\newif`` 造的自定义条件子（``\iffoo``/``\iff``）
    全带 ``if`` 前缀故同排。"""
    for name in ("if", "ifnum", "ifx", "ifodd", "ifcase", "iftoggle", "iffoo"):
        assert not _OPERAND_CS_RX.match("\\" + name), name
    # 名界守护：``if`` 模式只锚名首——``if`` 出现在名中的普通 cs 不误伤
    assert _OPERAND_CS_RX.match("\\myifhandler")


# ----------------------------------------------------------- setbox 族孤儿修复


def test_setbox_hbox_body_transparent() -> None:
    r"""``\setbox0=\hbox{..}``——``\setbox0=`` 收，``\hbox`` 回透明档连名
    带体原文进 surface（盒结构保留），体文照译；``=`` 不裸落。"""
    res = scan_prose("\\setbox0=\\hbox{hello world box body}")
    assert "\\hbox{hello world box body}" in blob(res)
    assert "=" not in blob(res)
    assert any(b.rstrip().endswith("\\setbox0=") for b in ph_bodies(res))


def test_setbox_vbox_body_clean() -> None:
    r"""``\setbox0=\vbox{..}``——``\vbox`` 走未知/盒规格路，体文不带花括号
    进 chunk（孤儿 ``{..}`` 字面花括号不再漏 surface）。"""
    res = scan_prose("\\setbox0=\\vbox{hello world box body}")
    assert "hello world box body" in blob(res)
    assert "{hello" not in blob(res)
    assert "=" not in blob(res)


def test_setbox_hbox_spec_tail() -> None:
    r"""``\setbox0=\hbox to3cm{..}``——``\setbox0=`` 收后 ``\hbox`` 回
    boxspec 路收 ``to3cm`` 规格尾，``to`` 关键字不进 surface。"""
    res = scan_prose("\\setbox0=\\hbox to3cm{hello world box body}")
    assert "to3cm" not in blob(res)
    assert "hello world box body" in blob(res)
    assert "=" not in blob(res)


def test_setbox_box_ref_operand_kept() -> None:
    r"""回归闸：盒引用仍是合法 rval——``\setbox0=\box1`` 全链照吃。"""
    res = scan_prose("\\setbox0=\\box1")
    assert "box1" not in blob(res)
    assert "\\setbox0=\\box1" in ph_bodies(res)


# ----------------------------------------------------------- 机器参/日志载荷


def test_message_log_payload_protected() -> None:
    r"""``\count0=5\message{..}``——``\message`` 回探针路整参进
    ``[[CMD]]``，日志载荷不再孤儿化裸译进正文。"""
    res = scan_prose("\\count0=5\\message{oops log text}")
    assert "oops log text" not in blob(res)
    assert "message" not in blob(res)


def test_write_file_payload_not_orphaned() -> None:
    r"""``\count0=5\write16{..}``——``\write`` 不收操作数，cs 连流号连参
    整段原文驻留 surface（raw-preserve）：无孤儿 ``{``、无裸 ``16``，
    cs 语境保住参界——载荷语义仍随段译出（已知取舍，结构不破）。"""
    res = scan_prose("\\count0=5\\write16{write payload text}")
    assert "\\write16{write payload text}" in blob(res)


def test_vskip_plus_minus_tail_intact() -> None:
    r"""``\count0=5\vskip3pt plus1pt``——``\vskip`` 回 boundary 自带 dimen
    扫，``plus``/``minus`` 胶续与单位不再断链漏出。"""
    res = scan_prose("\\count0=5\\vskip3pt plus1pt")
    assert "plus" not in blob(res)
    assert "3pt" not in blob(res)
    assert "vskip" not in blob(res)


def test_setlength_spec_bound() -> None:
    r"""``\count0=5\setlength\parskip{3pt}``——``\setlength`` 回 boundary
    参扫，``{3pt}`` 组随 spec 收不裸译。"""
    res = scan_prose("\\count0=5\\setlength\\parskip{3pt}")
    assert "3pt" not in blob(res)
    assert "parskip" not in blob(res)


# ----------------------------------------------------------- 结构子


def test_par_boundary_survives() -> None:
    r"""``\count0=5\par``——``\par`` 回 boundary，段界语义不再被操作数
    吞进 ``[[CMD]]`` 内部。"""
    res = scan(
        "Prose before keeps the run alive and gives context here.\n"
        "\\count0=5\\par\n"
        "New paragraph prose after the break keeps going here."
    )
    assert "New paragraph prose" in blob(res)
    assert "\\par" not in blob(res)
    contents = [c.content for c in res.chunks]
    assert not any("Prose before" in c and "New paragraph" in c for c in contents)


def test_end_env_not_orphaned() -> None:
    r"""``\count0=5\end{env}``——``\end`` 回 env 分派，``{env}`` 名组不
    孤儿化（环境名裸译会破坏 ``\end`` 配对）。"""
    res = scan_prose("\\begin{sloppypar}inner words \\count0=5\\end{sloppypar}")
    assert "{sloppypar}" not in blob(res)


# ----------------------------------------------------------- arith 裸 ``=`` 臂


def test_toks_eq_sign_covered() -> None:
    r"""``\toks0={..}``——裸 ``=`` 臂收赋值关键子：``=`` 不再漏 surface
    （orphan 组形不变，``=`` 单字泄漏收编）。"""
    res = scan_prose("\\toks0={tok body text}")
    assert "=" not in blob(res)


def test_count_eq_before_stop_cs() -> None:
    r"""``\count0=\message{..}``——rval 是终止符时 ``=`` 随 ``\count0=``
    收编；``\message`` 探针路护住载荷。"""
    res = scan_prose("\\count0=\\message{oops log text}")
    assert "oops log text" not in blob(res)
    assert "=" not in blob(res)


# ----------------------------------------------------------- KEEP 侧回归闸


def test_register_chain_still_eaten() -> None:
    r"""``\multiply\count0 by -4\count1``——``by`` 间隔关键子与 cs 因子
    链照收（``\count`` 是合法操作数不排）。"""
    res = scan_prose("\\multiply\\count0 by -4\\count1")
    assert "count1" not in blob(res)
    assert "by" not in blob(res)


def test_dimen_register_factor_kept() -> None:
    r"""``\hskip0.5\baselineskip``——寄存器因子链照收。"""
    res = scan_prose("\\hskip0.5\\baselineskip plus 1pt")
    assert "baselineskip" not in blob(res)
    assert "hskip" not in blob(res)
    assert "plus" not in blob(res)


def test_fontdimen_operand_kept() -> None:
    r"""``\fontdimen3\font=5pt``——``\font`` 字体标识符仍作操作数。"""
    res = scan_prose("\\fontdimen3\\font=5pt")
    assert "5pt" not in blob(res)
    assert "\\fontdimen3\\font=5pt" in ph_bodies(res)


def test_vsplit_operand_kept() -> None:
    r"""``\setbox0=\vsplit1 to3cm``——盒引用 + ``to`` 规格尾全链照吃。"""
    res = scan_prose("\\setbox0=\\vsplit1 to3cm")
    assert "vsplit" not in blob(res)
    assert "\\setbox0=\\vsplit1 to3cm" in ph_bodies(res)


# ----------------------------------------------------------- 组面镜像（token 路）


def test_group_tail_same_exclusion() -> None:
    r"""宏体内 ``\setbox0=\hbox{..}``——展开组内 ``_grp_tail_end`` 复用
    同一 ``_TAIL_RX``，终止符排除自动贯通 token 路。"""
    res = scan(
        "\\newcommand{\\vv}{\\setbox0=\\hbox{inner box text}}\n"
        "This is a longer paragraph of English prose that certainly should be "
        "segmented into a chunk for translation purposes here \\vv and the "
        "sentence continues with more English words afterwards for sure."
    )
    assert "=" not in blob(res)
    assert "inner box text" in blob(res)
