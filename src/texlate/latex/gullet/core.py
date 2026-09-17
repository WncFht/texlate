r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：源栈 + 主循环 + 原语分派。"""

from __future__ import annotations

from pathlib import (
    Path,
)
from typing import (
    TYPE_CHECKING,
)

import texlate.latex.gullet as _g
from texlate.latex.model import (
    ScanWarning,
)
from texlate.latex.mouth import (
    CC_LETTER,
    CC_OTHER,
    CatTable,
    Mouth,
    Tok,
)
from texlate.latex.tables import (
    INPUT_CMDS,
    MAX_GEN,
)

from .entries import (
    ArgMismatch,
    IfCond,
    IfSetter,
    MacroDef,
    ScopeMacroTable,
)
from .tables import (
    _EXPAND_KINDS,
    _PRIMS,
)

if TYPE_CHECKING:
    from texlate.latex.gullet import (
        Gullet,
    )


class _Core:
    def __init__(
        self,
        text: str = "",
        *,
        root_dir: str = "",
        top_dir: str = "",
        cats: CatTable | None = None,
        macros: ScopeMacroTable | None = None,
    ) -> None:
        r"""``text`` 顶层源（可空）；``cats``/``macros`` 可注入共享。

        ``top_dir``：``\input`` 解析第三级兜底（论文顶层目录，
        缺省回落 ``root_dir``，与 flatten ``_resolve`` 同序）。
        """
        self.cats = cats if cats is not None else CatTable()
        self.macros = macros if macros is not None else ScopeMacroTable()
        self.inputs: list[Mouth] = []  # 输入栈 = TeX.inputs (TeX.py:72)
        self.file_texts: list[str] = []  # file_id → 源文本
        self.file_paths: list[str] = []  # file_id → 路径（'' = 内存源）
        self.ifflags: dict[str, bool] = {}  # \newif 旗标
        # read() 最近产出（\if 条件段 marker 取端点 / _consumed 端点扩展）
        self._last_read: Tok | None = None
        self.steps = 0
        self.overflow = False  # 是否已记 expansion_overflow
        self.warnings: list[ScanWarning] = []
        self.root_dir = root_dir
        self.top_dir = top_dir or root_dir
        self._seen: set[str] = set()  # \input 绝对路径祖先栈（W12：进栈压、弹栈撤）
        self._seen_fid: dict[int, str] = {}  # file_id → 已登记绝对路径
        self._trace: list[Tok] = []  # 当前 invoke 已消费 token（回吐用）
        # 栈成员变更事件钟：read() 弹栈 / push_source / unread 合成源——
        # 分段器尾字节补盖的 live 快照按此重建（免每 token 全量 diff）。
        self._pop_seq = 0
        self._push_seq = 0
        if text:
            self.push_source(text, "")

    # ------------------------------------------------------------ 源栈

    def push_source(self, text: str, path: str = "") -> int:
        """压新输入源，返回其 ``file_id``；有路径即入 ``_seen`` 祖先栈。"""
        fid = len(self.file_texts)
        self.file_texts.append(text)
        self.file_paths.append(path)
        self.inputs.append(Mouth(text, fid, self.cats))
        self._push_seq += 1
        if path:
            r = str(Path(path).resolve())
            self._seen.add(r)
            self._seen_fid[fid] = r
        return fid

    def read(self) -> Tok | None:
        """拉原始 token（``itertokens`` TeX.py:249-279）：栈顶耗尽即弹。"""
        while self.inputs:
            t = self.inputs[-1].next()
            if t is not None:
                self._last_read = t
                return t
            m = self.inputs.pop()
            self._pop_seq += 1
            r = self._seen_fid.pop(m.file_id, None)
            if r is not None:
                self._seen.discard(r)  # 祖先栈回撤：兄弟位合法重包含不断
        return None

    def unread(self, toks: list[Tok] | tuple[Tok, ...]) -> None:
        """推回前端（``pushTokens`` TeX.py:455-467）：栈空 → 新建 token 源。"""
        if not toks:
            return
        if not self.inputs:
            self.inputs.append(Mouth.from_tokens(list(toks), self.cats))
            self._push_seq += 1
        else:
            self.inputs[-1].push_tokens(list(toks))

    def skip_past(self, fid: int, pos: int) -> bool:  # noqa: C901 — 栈序/tokbuf 回压/跨界守门平铺即 resync 规则表
        r"""逐字区 resync（分段器 ``\begin{verbatim}``/``\verb`` 用）。

        分段器在**文件字节**上找到闭合符后调此：把 ``fid`` 源的消费指针
        推到 ``pos``（=闭合区间末）。坑位：

        - 目标源通常即栈顶；栈顶为 ``from_tokens`` 合成源（file_id<0，
          case 回放/参读回吐所建）时向栈深找 fid——其上方滞留源保持
          先排，流序不乱。
        - ``tokbuf`` 回压 token：``end<=pos`` → 逐字区残骸丢弃；
          ``start>=pos`` → 保留（闭合符后真内容）；跨界 straddle 实际
          不可能（pos 恒落 ``}`` token 末），仍守门拒。
        - ``i`` 只前进（分段器已拉过闭合点的防御路径不重绕）。
        - ``_seen``/``_seen_fid`` 不动（resync 不弹源）。

        fid 不在栈 / 缓冲跨界 → ``verb_resync_failed`` warning + False，
        分段器退化逐字流（与今日无 verb 处理等价）。

        残余 fid token 可能躺在**合成回放源**（``file_id<0``——``\\if``
        选支回放/组收集回吐所建）的 ``tokbuf``——fid 源在栈时同样要清
        （回放源压在 fid 源上方，token 已搬走不在 fid tokbuf）；
        fid 源已弹栈（EOF 前排空被 ``read()`` 弹）时 tokbuf 剔除即
        resync 等价物。
        """
        hit = False
        for m in self.inputs:
            if m.file_id == fid:
                hit = True  # 字节游标 resync 由下方 target 分支统一做
                continue
            if m.file_id >= 0 or not any(t.pos[0] == fid for t in m.tokbuf):
                continue
            keep2: list[Tok] = []
            for t in m.tokbuf:
                if t.pos[0] != fid or t.pos[1] >= pos:
                    keep2.append(t)
                    continue
                if t.pos[2] > pos:
                    self._warn("verb_resync_failed", None, "buffered token straddles")
                    return False
            m.tokbuf.clear()
            m.tokbuf.extend(keep2)
            hit = True
        target = next((m for m in reversed(self.inputs) if m.file_id == fid), None)
        if target is not None:
            keep: list[Tok] = []
            for t in target.tokbuf:
                if t.pos[0] != fid or t.pos[1] >= pos:
                    keep.append(t)  # 异 fid 产物/闭合符后真内容——照常先排
                    continue
                if t.pos[2] > pos:
                    self._warn("verb_resync_failed", None, "buffered token straddles")
                    return False
                # pos[2] <= pos：逐字区残骸，丢
            target.resync(pos, keep)
        if not hit:
            self._warn("verb_resync_failed", None, f"fid {fid} not on inputs")
        return hit

    # ------------------------------------------------------------ 主循环

    def next_expanded(self) -> Tok | None:  # noqa: C901, PLR0911, PLR0912 — 分派顺序即 §8.2/§8.6（宏表先行）
        r"""展开主循环（``TeX.__iter__`` TeX.py:281-340）。

        拉原始 token → 非 cs 直交 → cs 查宏表（先行：``\ifb`` 单位宏 /
        ``\ifAnonymous{T}{F}`` 双参宏不落入 if 族）→ 命中且可展开则读参代入
        推回（不 return，不动点）；否则查原语；都不中 → 直交分段器。
        """
        while True:
            t = self.read()
            if t is None:
                return None
            if t.kind != "cs":
                return t
            if t.xprotect:
                t.xprotect = False  # \noexpand 打标：见标跳过一次展开
                return t
            name = t.text
            entry = self.macros.lookup(name)
            if entry is not None:
                r = self.macros.resolve(entry)
                if isinstance(r, MacroDef):
                    if r.kind in _EXPAND_KINDS and self._can_expand(t):
                        self.steps += 1
                        self._trace = []
                        try:
                            out = self._invoke(t, r)
                        except ArgMismatch:
                            self.unread(self._trace)
                            return t  # §3.5：回吐已读 + \name 本体交出
                        self.unread(out)
                        continue
                    return t  # opaque/math/inline/literal → 调用点保护
                if isinstance(r, IfCond):
                    if not self._can_expand(t):
                        return t
                    self.steps += 1
                    # 界标夹心：lead marker 盖 [trig, 选支首)（\ifX + 前置死支
                    # + 分案符），fi: 尾 marker 随选支 unread 盖 [选支末, \fi 末)
                    end = self.process_if(
                        self.ifflags.get(r.flag, False),
                        trig=t,
                        tail_tag=f"fi:{name}",
                    )
                    return self._consumed(
                        f"if:{name}", t, None, end=end if end is not None else t.pos[2]
                    )
                if isinstance(r, IfSetter):
                    self.ifflags[r.flag] = r.value
                    return t
                if isinstance(r, Tok):  # \let 字面别名 → 以触发位交出
                    return Tok(r.kind, r.text, t.pos, t.gen, t.origin)
                if isinstance(r, str):  # \let 到原语名 → 换名走原语分派
                    t = Tok("cs", r, t.pos, t.gen, t.origin)
                    name = r
                else:
                    return t  # Alias(None)：定义时未解析 → 未知命令
            if name in _PRIMS or name.startswith("if"):
                if not self._can_expand(t):
                    return t
                self.steps += 1
                self._trace = []
                try:
                    out = self._exec_prim(t)
                except ArgMismatch:
                    self.unread(self._trace)
                    return t  # §3.5：回吐已读 + 本体交出（如 \input{ 流尽）
                if out is None:
                    continue
                return out
            return t  # LaTeX 内建/未知 cs → 分段器按 argspec 表处理

    def _can_expand(self, t: Tok) -> bool:
        """三级限制：``gen>MAX_GEN``/``steps>BUDGET`` → 不再展开（§3.4）。"""
        if t.gen >= MAX_GEN:
            if not self.overflow:
                self.overflow = True
                self._warn("gen_overflow", t, f"gen>={MAX_GEN} unexpanded")
            return False
        if self.steps >= _g.BUDGET:
            if not self.overflow:
                self.overflow = True
                self._warn("expansion_overflow", t, f"steps>{_g.BUDGET}")
            return False
        return True

    def __iter__(self) -> Gullet:
        """迭代协议：``next_expanded() → None`` 耗尽。"""
        return self

    def __next__(self) -> Tok:
        """``next_expanded() → None`` 时 ``StopIteration``。"""
        t = self.next_expanded()
        if t is None:
            raise StopIteration
        return t

    def expand_all(self) -> list[Tok]:
        """抽干展开流（测试/分段器喂流便利）。"""
        out: list[Tok] = []
        while True:
            t = self.next_expanded()
            if t is None:
                return out
            out.append(t)

    def _warn(self, kind: str, t: Tok | None, detail: str) -> None:
        """登记 ``ScanWarning``；pos 取 token 起点（无 token → 0）。

        ``ScanWarning.pos`` 是 int 装不下 fid——多文件时 detail 前挂
        ``f{fid} `` 前缀（fid=0 主文件不挂，单文件 detail 保持原样）。
        """
        if t is not None and t.pos[0] > 0:
            detail = f"f{t.pos[0]} {detail}"
        pos = t.pos[1] if t is not None else 0
        self.warnings.append(ScanWarning(kind, pos, detail))

    def _consumed(
        self,
        tag: str,
        trig: Tok,
        trace: list[Tok] | None,
        head: Tok | None = None,
        end: int = -1,
    ) -> Tok:
        r"""静默消费段 → ``consumed`` marker token（分段器接线 §4）。

        ``pos = (fid, head.start, 末消费 token end)``：分段器 flush +
        LITERAL 盖面（``\def`` 串不落 chunk——译文会删 def）。``head``
        供 ``\long\global`` 前缀链从首个前缀起算；``end`` 显式端点供
        ``\if`` 条件段（其消费不走 ``trace``）。``gen>0`` 的 marker
        只作组内边界——pos 是定义体位（母体字节，多已被同组 token 覆盖），
        分段器侧零宽 piece 即正确、不驱覆盖；``input:`` 型仍须按 text 记
        ``inputs[]``。
        """
        h = head or trig
        if end < 0:
            end = trace[-1].pos[2] if trace else h.pos[2]
            lr = self._last_read
            if (
                lr is not None
                and lr.gen == 0
                and lr.pos[0] == h.pos[0]
                and lr.pos[2] > end
            ):
                end = lr.pos[2]  # _read_number 等非 trace 消费补端；gen>0 产物不延
        return Tok("consumed", tag, (h.pos[0], h.pos[1], end), h.gen, h.origin)

    # ------------------------------------------------------------ 原语分派

    def _exec_prim(self, t: Tok) -> Tok | None:  # noqa: C901, PLR0911, PLR0912 — 原语表平铺即 §8.2 expandables 集
        """原语执行：``Tok`` → 直交分段器；``None`` → 已处理继续循环。"""
        name = t.text
        if name in ("def", "edef", "gdef", "xdef"):
            return self._do_def(
                t,
                global_=name in ("gdef", "xdef"),
                eager=name in ("edef", "xdef"),
            )
        if name in ("long", "outer", "global", "protected"):
            return self._do_prefix(t, name)
        if name in (
            "newcommand",
            "renewcommand",
            "providecommand",
            "DeclareRobustCommand",
        ):
            return self._do_newcmd(t, name)
        if name in ("newenvironment", "renewenvironment"):
            return self._do_newenv(t)
        if name == "newtheorem":
            return self._do_newtheorem(t)
        if name == "DeclareMathOperator":
            return self._do_mathop(t)
        if name in (
            "NewDocumentCommand",
            "RenewDocumentCommand",
            "ProvideDocumentCommand",
            "DeclareDocumentCommand",
        ):
            return self._do_xparse(t, name)
        if name == "let":
            return self._do_let(t)
        if name == "newif":
            return self._do_newif(t)
        if name == "makeatletter":
            self.cats.set("@", CC_LETTER)
            return t
        if name == "makeatother":
            self.cats.set("@", CC_OTHER)
            return t
        if name == "catcode":
            return self._do_catcode(t)
        if name in ("begingroup", "bgroup"):
            # 原语组开：宏表+cats 同推。scope 事件唯一属主在此（分段器只
            # 回报 lbrace/\begin——cs 形不另报，免双推）；token 本体照交
            # 分段器（vtex 覆盖 = reconstruct identity 的硬理由）。
            self.macros.push_scope()
            self.cats.push()
            return t
        if name in ("endgroup", "egroup"):
            self.macros.pop_scope()
            self.cats.pop()
            return t
        if name == "endinput":
            if self.inputs:
                m = self.inputs.pop()  # 当前文件余下字节丢弃（flatten 同语义）
                self._pop_seq += 1
                r = self._seen_fid.pop(m.file_id, None)
                if r is not None:
                    self._seen.discard(r)  # 祖先栈回撤——同 read() 弹栈账
            return self._consumed("endinput", t, None)
        if name in INPUT_CMDS:
            return self._do_input(t, name)
        if name == "expandafter":
            return self._do_expandafter(t)
        if name == "csname":
            return self._do_csname(t)
        if name == "noexpand":
            t2 = self.read()
            if t2 is not None:
                t2.xprotect = True
                self.unread([t2])
            return None
        if name in ("ifundefined", "@ifundefined"):
            return self._do_ifundefined(t)
        if name == "par":
            return Tok("eol_par", "par", t.pos, t.gen, t.origin)
        if name.startswith("if"):
            return self._do_if(t)
        return t  # else/or/fi/endcsname 散件 → 界标 literal
