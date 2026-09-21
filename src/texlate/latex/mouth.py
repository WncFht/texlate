r"""Mouth：字符 → token（plasTeX ``Tokenizer.py:333-483`` 的移植）。

逐条对应关系见 ``docs/research/latex/expansion-design.md`` §3（Token 与
Mouth，原对照表已改散文）。
与规格的刻意分歧（已留档）：

- ``Tok.pos`` 是 ``(file_id, start, end)`` 三元组而非规格的
  ``(file_id, offset)``：splice 覆盖校验需要 end——注释、被吞的定义区段、
  被丢弃的 ``\if`` 分支**不产 token**，它们的字节是 gap；已产 token 的
  ``[start, end)`` + gap = 原文逐字节。
- 展开产物新增 ``origin`` 字段 = 最外层调用点 pos（沿嵌套展开传播）。
  spec §2 同时要求"产物 pos=定义体区间"与"splice 用调用点 pos"，
  ``origin`` 字段让两者同真：``src`` 属性 = ``origin or pos``。
- ``^^X`` 序列不实现（语料 ≈0）；``\let`` 不在 Mouth 层解（gullet 建
  别名表项，宏表查找时解引用——等价且少一条 Mouth→Context 依赖）。
- ``eol_par`` 归一 ``\n\n`` 与 ``\par``（gullet 把 ``\par`` 原语也归一到
  这个 kind）。
"""

from __future__ import annotations

import re
import string
import weakref
from collections import deque
from dataclasses import dataclass

__all__ = [
    "CC_LETTER",
    "CC_OTHER",
    "CatTable",
    "Mouth",
    "Tok",
]

# ------------------------------------------------------- catcode（TeX 16 类）
# 序号同 plasTeX Tokenizer.py:37-52；默认表同 DEFAULT_CATEGORIES（Tokenizer.py:7-26）
CC_ESCAPE = 0
CC_BGROUP = 1
CC_EGROUP = 2
CC_MATHSHIFT = 3
CC_ALIGNMENT = 4
CC_EOL = 5
CC_PARAMETER = 6
CC_SUPER = 7
CC_SUB = 8
CC_IGNORED = 9
CC_SPACE = 10
CC_LETTER = 11
CC_OTHER = 12
CC_ACTIVE = 13
CC_COMMENT = 14
CC_INVALID = 15

# catcode → Tok.kind（ESCAPE/COMMENT/EOL/SPACE 走专门路径不进此表；
# SUPER/SUB/ALIGNMENT/IGNORED/INVALID 归并为 'other'）
_CODE_TO_KIND = {
    CC_BGROUP: "lbrace",
    CC_EGROUP: "rbrace",
    CC_MATHSHIFT: "mathshift",
    CC_PARAMETER: "param",
    CC_LETTER: "letter",
    CC_ACTIVE: "active",
    CC_OTHER: "other",
    CC_SUPER: "other",
    CC_SUB: "other",
    CC_ALIGNMENT: "other",
}

# Mouth 三态：N=行首 M=行中 S=吸空白（plasTeX STATE_*，Tokenizer.py:172 附近）
_S = 1
_M = 2
_N = 4

_LETTERS = string.ascii_letters  # TeX 语义：LETTER 只含 ASCII（非 ASCII → OTHER）


@dataclass(slots=True)
class Tok:
    r"""token。``kind`` ∈ cs|lbrace|rbrace|mathshift|param|space|eol_par|letter|other|active|consumed。

    ``pos`` = ``(file_id, start, end)`` 半开区间；展开产物的 pos = 定义体区间
    且 ``gen>0``、``origin`` = 最外层调用点 pos（spec §2）。
    ``xprotect`` = ``\noexpand`` 打标（gullet 见标跳过一次展开）。
    ``consumed`` = gullet 静默消费段 marker（``\def``/``\if``/``\input`` 等），
    ``text`` = ``family:payload``，``pos`` 盖整个被消费区间——分段器
    flush + LITERAL 用。``gen>0`` 时 pos 是**定义体位**（母体字节，多已被
    同组 token 覆盖）→ 分段器侧零宽 piece 即正确、不驱覆盖，仅作组内
    边界；``input:`` 型仍须按 text 记 ``inputs[]``（文件源确实压栈了）。
    """

    kind: str
    text: str  # cs→名字（不含 \）；其余→字符本体
    pos: tuple[int, int, int]
    gen: int = 0
    origin: tuple[int, int, int] | None = None
    xprotect: bool = False

    @property
    def src(self) -> tuple[int, int, int]:
        """Splice 语义位：展开产物取调用点，源 token 取自身 pos。"""
        return self.origin or self.pos

    def __str__(self) -> str:
        r"""``\foo`` → ``\\foo``；其余 → text 本体（调试/表面文本用）。"""
        return "\\" + self.text if self.kind == "cs" else self.text


class CatTable:
    r"""catcode 表（``dict[char, int]``）+ 组作用域 undo 栈。

    Mouth/Gullet 共享可变——``\makeatletter`` 翻 ``@`` 即查即生效
    （拉取式 tokenize 的硬理由）。

    ``\catcode`` 赋值是组局部的（TeX 同）：``push``/``pop`` 与
    ``ScopeMacroTable`` 同型，``set`` 在每帧首写某 ch 时记旧值，
    ``pop`` 回放恢复。底帧不存 undo——顶层写 = 全局写，永不回滚。
    """

    _MISSING = -1  # undo 帧里"写入前未登记"哨兵（catcode 域 0-15 外）

    def __init__(self) -> None:
        """建默认 TeX catcode 表（plasTeX DEFAULT_CATEGORIES 同值）。"""
        m: dict[str, int] = {}
        m["\\"] = CC_ESCAPE
        m["{"] = CC_BGROUP
        m["}"] = CC_EGROUP
        m["$"] = CC_MATHSHIFT
        m["&"] = CC_ALIGNMENT
        m["\n"] = CC_EOL
        m["#"] = CC_PARAMETER
        m["^"] = CC_SUPER
        m["_"] = CC_SUB
        m["\x00"] = CC_IGNORED
        for c in " \t\r\f":
            m[c] = CC_SPACE
        for c in _LETTERS:
            m[c] = CC_LETTER
        m["~"] = CC_ACTIVE
        m["%"] = CC_COMMENT
        self._m = m
        self._undo: list[dict[str, int]] = []
        # 内容版本钟：set/pop 改表递增——派生缓存（segmenter 文本 run 正则）
        # 的失效键；不改表的 push/空帧 pop 不递增，免每 ``}`` 重建缓存。
        self._v = 0

    def code(self, ch: str) -> int:
        """查 catcode；未登记字符 → ``CC_OTHER``（plasTeX whichCode 同义）。"""
        return self._m.get(ch, CC_OTHER)

    def set(self, ch: str, code: int) -> None:
        r"""``\catcode`/``\makeatletter`` 写入口；组内首写记 undo。

        ``\global`` 前缀在 gullet ``_do_prefix`` 不续 catcode 而回吐——
        带 ``\global`` 的写仍落本帧 undo、组闭照滚（保守方向，比泄漏
        安全；真 write-through 需前缀链透传，未实现）。
        """
        if self._undo:
            frame = self._undo[-1]
            if ch not in frame:
                frame[ch] = self._m.get(ch, self._MISSING)
        self._m[ch] = code
        self._v += 1

    def push(self) -> None:
        r"""组开（``{``/``\begingroup``/``\begin``/``$``族回报）→ 开 undo 帧。"""
        self._undo.append({})

    def pop(self) -> None:
        """组闭 → 回放本帧写入；无帧（顶层）不弹——底帧写即全局写。"""
        if not self._undo:
            return
        frame = self._undo.pop()
        if frame:
            self._v += 1  # 本帧有写入回放——_m 内容可能变
        for ch, old in frame.items():
            if old == self._MISSING:
                self._m.pop(ch, None)
            else:
                self._m[ch] = old


# ---- 文本 run 批量化（fix#9 cut-2） ------------------------------------------
# 可批 catcode 集：这些猫码逐字符产「surface=原字符」文本 token——排除
# ESCAPE/BGROUP/EGROUP/MATHSHIFT/EOL/SPACE/COMMENT/IGNORED/INVALID（折叠
# 空白/注释/结构字节无法字节再生），``CC_ACTIVE``（``~``）亦剔出买保险
# （未来可展开化风险）。未登记字符恒 ``CC_OTHER`` → 天然在 run 集。
_RUN_CATCODES = frozenset(
    {CC_LETTER, CC_OTHER, CC_SUPER, CC_SUB, CC_ALIGNMENT, CC_PARAMETER}
)
# 猫码表 → 派生 run 正则缓存：``CatTable._v`` 版本钟在 set/pop 改表时递增。
_RUN_RX_CACHE: weakref.WeakKeyDictionary[CatTable, tuple[int, re.Pattern[str]]] = (
    weakref.WeakKeyDictionary()
)


def _text_run_rx(cats: CatTable) -> re.Pattern[str]:
    r"""当前猫码表的 run 正则：``T+(␣T+)*``——内部只许字面 ``" "`` 夹心。

    ``T`` = run 集字符类的补（``SPACE``/``EOL`` 猫码字符本就不在 run 集，
    无须另排）；夹心空格取字面 ``" "``——space token surface 恒 ``" "``，
    仅当原字节就是它时合并才不偏 surface。``cats._v`` 失配即重建——
    ``\catcode``/``\makeatletter`` 改表后沿用旧正则会静默错切（proto 实证）。
    """
    ent = _RUN_RX_CACHE.get(cats)
    if ent is not None and ent[0] == cats._v:  # noqa: SLF001 — 版本钟即缓存契约面
        return ent[1]
    dead = "".join(
        sorted(
            ch
            for ch, c in cats._m.items()  # noqa: SLF001 — 同库内部表
            if c not in _RUN_CATCODES
        )
    )
    rx = re.compile("[^" + re.escape(dead) + "]+(?: [^" + re.escape(dead) + "]+)*")
    _RUN_RX_CACHE[cats] = (cats._v, rx)  # noqa: SLF001
    return rx


class Mouth:
    r"""单输入源的字符→token 机（plasTeX ``Tokenizer.__iter__``）。

    ``tokbuf`` 回压缓冲**先空先出**（``push_tokens`` 逆序塞左端，
    Tokenizer.py:319-331）；缓冲 token 不更新 ``_prev``/state（plasTeX
    同——缓冲 pop 在 ``prev = token`` 之前）。
    """

    def __init__(
        self, text: str, file_id: int = 0, cats: CatTable | None = None
    ) -> None:
        """``text`` 源串；``cats`` 共享 catcode 表（None → 新建默认表）。"""
        self.buf = text
        self.i = 0  # 已消费字符位（分段器 splice 用）
        self.file_id = file_id
        self.cats = cats if cats is not None else CatTable()
        self.state = _N
        self.tokbuf: deque[Tok] = deque()
        self._prev_kind = ""  # 上一枚**流产出** token 的 kind（eol_par 相邻去重）

    @classmethod
    def from_tokens(
        cls, toks: list[Tok], cats: CatTable | None = None, file_id: int = -1
    ) -> Mouth:
        """纯 token 输入源（plasTeX ``input([tokens])`` 同构，TeX.py:451）。"""
        m = cls("", file_id=file_id, cats=cats)
        m.tokbuf.extend(toks)
        return m

    def push_tokens(self, toks: list[Tok]) -> None:
        """逆序塞左端——``unread``/展开推回的落点（Tokenizer.py:319-331）。"""
        if toks:
            self.tokbuf.extendleft(reversed(toks))

    def resync(self, pos: int, keep: list[Tok]) -> None:
        r"""逐字区跳读复位（gullet ``skip_past`` 的唯一入口）。

        ``i`` 只前进；``state`` 归 M（``\end{V}`` 后接 ``\n\n`` 仍产
        ``eol_par``）；``_prev_kind`` 清空（同上，eol_par 去重不误伤）；
        ``tokbuf`` 重置为 ``keep``（调用方已剔除逐字区残骸）。
        """
        self.i = max(self.i, pos)  # i 只前进
        self.state = _M
        self._prev_kind = ""
        self.tokbuf.clear()
        self.tokbuf.extend(keep)

    def skip_text(self, end: int) -> None:
        r"""纯文本 run 快进：``i`` 只前进、``state`` 归 ``_M``。

        ``resync`` 的批量化轻量形（segmenter 文本 run 直推游标）——不清
        ``tokbuf``/``_prev_kind``：调用方保证 ``tokbuf`` 空；run 尾恒为
        文本字符，``_prev_kind`` 留头 token 的文本 kind 即正确值。
        """
        self.i = max(self.i, end)
        self.state = _M

    def __iter__(self) -> Mouth:
        """迭代协议：``next()`` 耗尽即停。"""
        return self

    def __next__(self) -> Tok:
        """``next() → None`` 时 ``StopIteration``。"""
        t = self.next()
        if t is None:
            raise StopIteration
        return t

    def next(self) -> Tok | None:  # noqa: C901, PLR0911, PLR0912 — 三态机分支平铺即 Tokenizer.py:364-483
        r"""产下一枚 token；源尽 → ``None``。

        三态折叠（逐条对 plasTeX）：

        - LETTER/OTHER → state M，直产；
        - SPACE：S/N 态跳过；M 态 → 产 Space + 转 S；
        - EOL(``\\n``)：S → 转 N 跳过；M → 产 Space + 转 N；N → 产
          ``eol_par``（相邻去重——``\\n\\n`` 折叠为一个段落边界）；
        - COMMENT：吞到 ``\\n`` 含本字符，转 N，不产 token；
        - ESCAPE：``\\``+字母串 → cs（后随空白吸收 = 转 S）；
          ``\\``+EOL → Space + S；``\\``+其他 → 单字符 cs（仅当该字符是
          ASCII 字母才转 S——即 catcode 被改写的边角，常态不转）；
          ``\\``+EOF → 空名 cs；
        - IGNORED/INVALID → 静默跳过。
        """
        buf, n = self.buf, len(self.buf)
        while True:
            if self.tokbuf:
                return self.tokbuf.popleft()
            if self.i >= n:
                return None
            c = buf[self.i]
            self.i += 1
            code = self.cats.code(c)
            pos = (self.file_id, self.i - 1, self.i)

            if code in (CC_IGNORED, CC_INVALID):
                continue

            if code in (CC_LETTER, CC_OTHER, CC_SUPER, CC_SUB, CC_ALIGNMENT):
                self.state = _M
                t = Tok(_CODE_TO_KIND.get(code, "other"), c, pos)
                self._prev_kind = t.kind
                return t

            if code == CC_SPACE:
                if self.state in (_S, _N):
                    continue
                self.state = _S
                t = Tok("space", " ", pos)
                self._prev_kind = t.kind
                return t

            if code == CC_EOL:
                if self.state == _S:
                    self.state = _N
                    continue
                if self.state == _M:
                    self.state = _N
                    t = Tok("space", " ", pos)
                    self._prev_kind = t.kind
                    return t
                # state N：段落边界（相邻去重）
                if self._prev_kind == "eol_par":
                    continue
                t = Tok("eol_par", c, pos)
                self._prev_kind = t.kind
                return t

            if code == CC_COMMENT:
                # 吞到 \n 含本字符（readline 语义）；\n 本身也被吃掉、转 N
                k = buf.find("\n", self.i)
                self.i = n if k < 0 else k + 1
                self.state = _N
                continue

            if code == CC_ESCAPE:
                t = self._read_escape()
                if t is None:  # tokbuf 有货时不可能到这；纯保险
                    continue
                self._prev_kind = t.kind
                return t

            if code == CC_ACTIVE:
                self.state = _M
                t = Tok("active", c, pos)
                self._prev_kind = t.kind
                return t

            # BGROUP/EGROUP/MATHSHIFT/PARAMETER：直产
            self.state = _M
            t = Tok(_CODE_TO_KIND.get(code, "other"), c, pos)
            self._prev_kind = t.kind
            return t

    def _read_escape(self) -> Tok | None:
        r"""``\`` 已消费 → 读转义序列（Tokenizer.py:411-453）。"""
        buf, n = self.buf, len(self.buf)
        start = self.i - 1
        self.state = _M
        # 下一字符：IGNORED/INVALID 跳过（iterchars 语义），EOF → 空名 cs
        while self.i < n:
            c = buf[self.i]
            self.i += 1
            code = self.cats.code(c)
            if code in (CC_IGNORED, CC_INVALID):
                continue
            break
        else:
            return Tok("cs", "", (self.file_id, start, self.i))
        if code == CC_LETTER:
            # 字母串 → word cs；首个非字母回吐（i -= 1 即 pushChar）
            j = self.i
            while j < n and self.cats.code(buf[j]) == CC_LETTER:
                j += 1
            name = buf[self.i - 1 : j]
            self.i = j  # j 停在首个非字母——等价 pushChar（下次重读）
            self.state = _S  # cs 后随空白吸收
            return Tok("cs", name, (self.file_id, start, j))
        if code == CC_EOL:
            # \<EOL> → Space token
            self.state = _S
            return Tok("space", " ", (self.file_id, start, self.i))
        # 单字符 cs（\<非字母>）；token[-1] ∈ ascii_letters → 转 S
        # （常态不可能——字母走的是上面分支；保留 plasTeX 同款判定）
        if c in _LETTERS:
            self.state = _S
        return Tok("cs", c, (self.file_id, start, self.i))
