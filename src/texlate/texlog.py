r"""TeX ``.log`` 词法原语 —— engine/l2/fixloop 三处文件栈收敛的单源实现。

错误行 regex（``_ERR_FNAME``/``_ERR_FILELINE_RE``/``_NONERR_FILELINE_RE``
等）亦居此层——``compile/loginfo`` 与 ``fixloop/logparse`` 的共同单源，
叶子层定位使 fixloop→compile 模块级环边不再存在。

``(``/``)`` 开闭配对追踪：TeX log 用圆括号标记打开/关闭文件，行内可能混
非文件括号（``.log`` 折行、参数转储），非文件 ``(`` 入栈 ``None`` 占位以
保持配对正确——这是文件栈算法的核心不变量（早期"只压不弹"实现把栈
越滚越大的教训）。具名帧不限 tex 系扩展名——graphic/``.lbx``/pgf 内部
件等真实输入文件按 ``looks_like_input_file`` 形状判定入栈。

79 列折行可能把文件名劈到下一行——本模块逐字符扫，劈断的 token 因扩展名
校验失败自然落入 ``None`` 占位，栈配对仍正确（近似即可，文件栈只用于
缩小 rewrite 作用域与 escalate 上下文，不是精确解析器）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

__all__ = [
    "DOS_EPS_MAGIC",
    "TEX_FILE_EXTS",
    "file_stack_at",
    "is_dos_eps",
    "is_project_file",
    "looks_like_input_file",
    "patch_graphic_top",
    "update_file_stack",
]

#: tex 系扩展名（三版并集：engine 编译面 + l2 观测面 + logparse 判定面）。
TEX_FILE_EXTS: Final = frozenset(
    {
        "tex",
        "sty",
        "cls",
        "def",
        "cfg",
        "clo",
        "fd",
        "ldf",
        "dtx",
        "ins",
        "ltx",
        "bib",
        "bst",
        "bbl",
        "bbx",
        "cbx",
        "map",
        "enc",
        "aux",
        "out",
        "toc",
        "mf",
        "tfm",
        "vf",
        "ofm",
        "ovp",
    }
)

#: ``(`` 后的候选文件 token（排除 ``()``/``{}`` 内字符——后者是字体/参数转储）。
_OPEN_TOKEN_RX: Final = re.compile(r"[^\s(){}]+")

#: 非白名单扩展名形状：字母开头 + ``[a-z0-9_]`` ≤10 字符。字母开头一条
#: 即挡住 ``(52.00102pt`` 尺寸转储（overfull 行海量）、``(v2.0)``/
#: ``(4.2d--4.2f)`` 版本号、``(Fig.11a)`` 引文号这类数字开头假扩展名
#: （loop1 语料 8418 log 全扫实证：误纳率 ~0.3%）。
_FILE_EXT_RX: Final = re.compile(r"[a-z][a-z0-9_]{0,9}")

#: ``Missing character: There is no X in font`` —— X 是**字面字形**，可为
#: ``(``/``)``（nullfont 缺字符实测）：不配对的 ``)`` 会误弹真文件帧，
#: ``(`` 留幻影帧吃掉后续真闭括弧。字形后必跟空格（单字符形态）或行尾；
#: ``(U+0029)``/``("0029)`` 码位形态括号自带配对，不在此列。
_MISS_CHAR_RX: Final = re.compile(r"Missing character: There is no ([()])(?=[ (]|$)")


def looks_like_input_file(token: str) -> bool:
    r"""``(`` 后 token 是否文件名形——不限 tex 系扩展名。

    白名单 ``TEX_FILE_EXTS`` 先行（零回归 fast-path）；其余按扩展名形状
    判：末段 ``.<ext>`` 且 ext 字母开头 ``[a-z0-9_]`` ——TeX 实际打开的
    输入文件扩展名是无限长尾（``.eps``/``.tikz``/``.lbx``/``.pygtex``/
    pgf ``.code``/``.c``/``.cod``、revtex ``.rtx``、mdframed ``.mdf``…），
    白名单注定追不全。含 ``@``/``://``/``,`` 的 token 拒收（邮件/URL/
    坐标列表括号——loop1 语料 8418 log 实证该组合误纳率 ~0.3%）。
    """
    base = token.rsplit("/", 1)[-1]
    if "." not in base:
        return False
    ext = base.rsplit(".", 1)[-1].lower()
    if ext in TEX_FILE_EXTS:
        return True
    if "@" in token or "://" in token or "," in base:
        return False
    return _FILE_EXT_RX.fullmatch(ext) is not None


def update_file_stack(
    ln: str,
    stack: list[str | None],
    popped: list[str | None] | None = None,
) -> None:
    """单行扫 ``(``/``)`` 增量维护文件栈；非文件 ``(`` 入栈 ``None`` 保持配对。

    入栈的是字面 token（保留 ``./`` 前缀——log 原样，消费端按 endswith 用）。
    具名帧判定走 ``looks_like_input_file``——graphic/``.lbx``/pgf 内部件
    等非 tex 扩展名同样具名入栈（栈内容与 ``popped`` 不限 tex 系，消费端
    不得假设扩展名族）。``popped`` 非 None 时把本行弹出的栈顶按序追加——
    ``File ended while scanning`` 类 runaway 错报在父文件续行位（``)``
    先于错误打印），消费端靠"刚弹出的文件"找回真肇事文件（#78）。
    """
    if "(" not in ln and ")" not in ln:
        return
    skip: frozenset[int] = (
        frozenset(m.start(1) for m in _MISS_CHAR_RX.finditer(ln))
        if "Missing character" in ln
        else frozenset()
    )
    j = 0
    while j < len(ln):
        c = ln[j]
        if j in skip:
            j += 1
        elif c == "(":
            m = _OPEN_TOKEN_RX.match(ln, j + 1)
            if m and looks_like_input_file(m.group(0)):
                stack.append(m.group(0))
                j = m.end()
                continue
            stack.append(None)
            j += 1
        elif c == ")":
            if stack:
                top = stack.pop()
                if popped is not None:
                    popped.append(top)
            j += 1
        else:
            j += 1


#: ``(x.eps`` 类 graphic 打开帧的 PS 族扩展名面——与 fixloop builtins 的
#: 全图形族 ``_GRAPHIC_EXTS``（含 pdf/png/jpg）**同名不同物**，故名加
#: ``_PS_`` 前缀区分。形状判定拒收的 graphic token（逗号/截断形，如
#: ``fig,1.eps``）入 ``None`` 配对帧；engine/l2/fixloop 三处栈消费都把
#: 行尾未配对 ``(`` 的 graphic token 补回栈顶真名。
_PS_GRAPHIC_EXTS: Final = frozenset({".eps", ".epsf", ".epsi", ".ps", ".mps"})


def patch_graphic_top(ln: str, stack: list[str | None]) -> None:
    """栈顶 ``None`` 配对帧是 graphic 打开时补真名（engine/l2 同款补丁）。

    只补行尾最后一个未配对 ``(`` 后的 graphic token——已被 ``)`` 闭合或
    栈顶为具名帧时不动作；``None`` 占位语义其余位置不受影响。
    """
    if not stack or stack[-1] is not None:
        return
    lp = ln.rfind("(")
    if lp < 0 or lp < ln.rfind(")"):
        return
    m = _OPEN_TOKEN_RX.match(ln, lp + 1)
    if m and Path(m.group(0)).suffix.lower() in _PS_GRAPHIC_EXTS:
        stack[-1] = m.group(0)


def file_stack_at(
    lines: list[str], stop: int, popped: list[str | None] | None = None
) -> list[str]:
    """重放 ``lines[:stop]`` 的文件栈，取 stop 行处仍打开的文件名序列。

    ``popped`` 非 None 时把重放全程弹出的栈顶按序追加——与
    ``update_file_stack`` 同口径含 ``None`` 配对帧（原样透传，滤除是
    消费端职责）；``popped[-1]`` 即 stop 行前最近关闭的文件，
    ``File ended while scanning`` 类 runaway 错报位在父文件续行时
    找回真肇事文件用（#78）。重放逐行套用 ``patch_graphic_top``——
    形状拒收的 ``(fig,1.eps`` 类帧与 engine/l2 同口径补真名。
    """
    stack: list[str | None] = []
    for ln in lines[:stop]:
        update_file_stack(ln, stack, popped)
        patch_graphic_top(ln, stack)
    return [s for s in stack if s]


#: 系统 texmf/bundle 树路径标记——``root`` 缺席时绝对路径的归因兜底。
#: 段内含 ``texmf``（``texmf-dist``/``_texmf`` usertree/``~/texmf``）或
#: Tectonic bundle 缓存均判系统侧——注意 fixloop usertree 落在
#: ``wdir/_texmf``（root 之内仍是系统语义），故本标记先于 root 前缀判。
#: 大小写敏感：``Tectonic`` 只认 canonical 大写缓存目录名——小写
#: ``tectonic/`` 恰是 fixloop 编译工作段名（``wdir/tectonic``），误吃会把
#: 工程件错判系统。
_SYS_TREE_RX: Final = re.compile(r"[^/]*texmf[^/]*/|/Tectonic/")


def is_project_file(token: str | None, root: Path | None = None) -> bool:
    """文件栈 token → 工程文件判定（invalid_utf8 类红线按产生者归因用）。

    相对 token（``./x``/``sec/y``）= cwd 相对即工程内；绝对路径先看 texmf
    标记再按 ``root`` 前缀判（root 给定时界外即系统——沙箱 root=wdir，
    工程件不可能在其外）。裸名是 tectonic bundle 日志形态：``root`` 给定
    按 ``root/token`` 存在性分（bundle 件不在工程树），缺席时保守归工程
    ——不可归因不掉红线。含 NUL 的 token 与 ``resolve`` 失败的路径同理
    归工程——真实文件路径不含 NUL，判不出归属时红线照留。
    """
    if token is None or "\x00" in token:
        return True
    if "/" not in token:
        try:
            probed = root is not None and (root / token).is_file()
        except (OSError, ValueError):
            probed = True  # ENAMETOOLONG 等——不可归因，保守归工程
        return probed or root is None
    if not token.startswith("/"):
        return True
    if _SYS_TREE_RX.search(token):
        return False
    if root is not None:
        try:
            return Path(token).resolve().is_relative_to(Path(root).resolve())
        except (OSError, ValueError):
            pass  # symlink 环/非法路径——不可归因，保守归工程
    return True


#: DOS 二进制 EPS 魔数：带绝对偏移头的 legacy 格式，normalize 只能字节原样
#: 保留进 ``dos_eps_skipped`` 台账——其 invalid_utf8 警告是必然残余而非可
#: 修复缺陷，消费端（engine/l2）按栈顶文件 token 判定后降级 ``sys_hits``。
DOS_EPS_MAGIC: Final = b"\xc5\xd0\xd3\xc6"


def is_dos_eps(token: str | None, root: Path | None, cache: dict[str, bool]) -> bool:
    """文件栈 token → DOS 二进制 EPS 判定（按 token 缓存；相对路径以 ``root`` 解析）。

    读文件头 4 字节比对 ``DOS_EPS_MAGIC``；``root`` 缺席或读不到（None
    token/相对路径无根/文件不存在）一律 False——判不出时不降级。
    """
    if not token or root is None:
        return False
    if token in cache:
        return cache[token]
    p = Path(token)
    if not p.is_absolute():
        p = root / p
    try:
        if p.is_file():  # 正规文件闸——fifo 开口阻塞与 NUL ValueError 同消
            with p.open("rb") as fh:
                ok = fh.read(4) == DOS_EPS_MAGIC
        else:
            ok = False
    except (OSError, ValueError):
        ok = False
    cache[token] = ok
    return ok


# ================================================================ 错误行原语
#: ``file:line:`` 文件名面（``compile/loginfo`` 与 ``fixloop/logparse`` 的
#: 单源；l2 ``_FILE_LINE_RX`` 同口径副本）：``name.ext`` 必带扩展名、禁
#: ``()``/空白/``:`` 内嵌——``Makefile:5:``/``C:\foo.tex:5:``/``(x.tex:5:``
#: 畸形形齐拒；扩展名不限 tex 系（``.eps``/``.pdf_t``/``.end`` 等皆真错，
#: l2 侧 7814 log 实证）。
_ERR_FNAME = r"[^()\s:]+\.[A-Za-z0-9_-]{1,10}"
_ERR_FILELINE_RE = re.compile(
    r"^" + _ERR_FNAME + r":\d+: \S"
)  # -file-line-error 引擎级错误
#: ``file:line:`` 形态的非错误行（loginfo/logparse 同口径）：Warning 行
#: （警告也带 file:line: 前缀时不能计入错误）与 ``==> Fatal error occurred``
#: 汇总尾行（同一失败的复述，多计一次）。
_NONERR_FILELINE_RE = re.compile(
    r"^" + _ERR_FNAME + r":\d+:\s*(?:(?:LaTeX|Package|Class)\b[^\n]*?\bWarning\b|==>)"
)
_ERR_BANG_RE = re.compile(r"^!")
_L_NUM_RE = re.compile(r"^l\.(\d+)")
