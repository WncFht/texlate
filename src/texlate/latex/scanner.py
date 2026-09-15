r"""Scanner 主循环 + dispatch_cmd + env/macro/arg handlers + math-debt repair。

规格：docs/07 §3（状态机）/§4（对象模型）/§8（展开层语义落地）。

五条铁律（docs/07 §0）：

1. 单遍逐字符扫描，绝不回退、绝不抛异常；
2. 分支顺序即语义（§3.1/§3.2 分派表 19 行顺序原样）；
3. 凡内容可含 ``%`` 的构造在 ``%`` 分支判定前被整段消费；
4. splice 永远用调用点/原文字节区间；
5. 一切降级 splice-safe（失败输出永远是原文某连续区间）。

展开层 v1（docs/07 §8 在 char-scanner 上的语义等价落地）：

- ``\if`` 两档：可求值族 → ``_process_if`` 字节级收集 case（任何 ``if*``
  计嵌套、``\newif`` 整对保留、``\or/\else`` 分案例），选中段 spawn 子扫
  （pieces 经 base 并入主流，平铺不破），未选段/界标全部 LITERAL；
  不可求值 → 界标 LITERAL，双分支都进分段器（召回优先）。
- ``\def`` 定界参 → opaque 降级（macro_table 不登记 + def_parse_fail）。
- 回压：``state.steps`` > BUDGET → 宏不再分流（按 OPAQUE 处理）；
  ``gen`` > MAX_GEN → 子扫描不再递归挖 chunk。
"""

from __future__ import annotations

import re

from texlate.latex.macro_table import (
    parse_argspec,
    register_macros_in,
    register_newif,
    scan_macro_def,
)
from texlate.latex.model import (
    ArgSpan,
    ArgSpec,
    Chunk,
    EnvEntry,
    MacroEntry,
    MacroKind,
    PhType,
    Piece,
    PieceKind,
    ScanMode,
    ScanResult,
    ScanState,
    ScanWarning,
    Span,
    env_name_at,
    match_brace,
    match_bracket,
    read_cmd_name,
    unescaped_dollar_odd,
    ws_skip,
)
from texlate.latex.placeholder import PH_RX
from texlate.latex.tables import (
    ACCENT_CHARS,
    ARG_TRANSPARENT_ENVS,
    BOUNDARY_NAMES,
    BUDGET,
    CHUNK_ARG_NAMES,
    CHUNK_ARG_SPEC,
    CHUNK_MAX,
    CHUNK_MIN,
    CITE_NAMES,
    COND_RX,
    DEF_NAMES,
    ENV_MANDATORY_ARG,
    FONT_SWITCHES,
    IF_CONST,
    IF_CONST_FALSE,
    INLINE_LITERAL_CMDS,
    MATH_ENVS,
    MAX_GEN,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    PROTECTED_ENVS,
    REF_NAMES,
    TRANSPARENT_NAMES,
    VERBATIM_ENVS,
)

_PROTECT_TYP = {
    "includegraphics": PhType.GRAPHICS,
    "url": PhType.URL,
    "path": PhType.URL,
    "label": PhType.LABEL,
    "bibliography": PhType.BIB,
    "bibliographystyle": PhType.BIB,
    "bibitem": PhType.BIB,
}

# scan 层登记的 \input 触发面（flatten 已展开的不再出现，未解析的记 inputs[]）
_INPUT_SCAN_CMDS = {
    "input",
    "include",
    "InputIfFileExists",
    "subfile",
    "includestandalone",
    "import",
    "subimport",
}

_FILENAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
)

_LETTER_TAIL_RX = re.compile(
    r"\\[a-zA-Z@]+\Z"
)  # \Z 严格串尾：体尾 \n 已阻断 token 合并
_CUT_PROBE = 16  # 硬切点半径：探测横跨切点的 [[X_n]]（最长占位符 ~12 字符）
_CLEAN_CMD_RX = re.compile(r"\\[a-zA-Z@]+\*?|\\[^a-zA-Z]")
_CLEAN_NONALPHA_RX = re.compile(r"[^a-zA-Z]")
_LEAD_WS_RX = re.compile(r"\s*")
_TRAIL_WS_RX = re.compile(r"\s*$")


class Scanner:
    """单次正向扫描器。pos 单调递增，永不回退，绝不抛异常。

    一切可变状态收敛在 ``state``（ScanState）——spawn 只共享这一个引用。
    """

    def __init__(  # noqa: PLR0913 — 五开关全是关键字参数，spawn 逐字段透传
        self,
        state: ScanState,
        *,
        mode: ScanMode = ScanMode.NORMAL,
        in_arg: bool = False,
        force_chunk: bool = False,
        base: int = 0,
        gen: int = 0,
    ) -> None:
        """绑定共享 ``state``；五个开关见 docs/07 §2 ScanState/子扫描语义。"""
        self.state = state  # issuer/ph_map/chunks/macros/inputs/warnings/ifflags
        self.mode = mode
        self.in_arg = in_arg  # 渲染结果将落入 chunk → 字面必须占位符化
        self.force_chunk = force_chunk
        self.base = base  # 子扫描切片的全局偏移（span 换算）
        self.gen = gen  # 子扫描代数（MAX_GEN 回压）
        self.pieces: list[Piece] = []
        self.env_stack: list[str] = []
        self.math_debt: list[int] = []  # run 下标栈
        self._tex = ""
        self._run: list[str] = []
        self._run_start: int | None = None  # run 覆盖字节区间起点（局部坐标）

    def spawn(
        self,
        *,
        mode: ScanMode | None = None,
        in_arg: bool | None = None,
        base: int = 0,
    ) -> Scanner:
        """子扫描器：共享 ``state``，env_stack 拷贝，gen+1。"""
        sub = Scanner(
            self.state,
            mode=self.mode if mode is None else mode,
            in_arg=self.in_arg if in_arg is None else in_arg,
            base=base,
            gen=self.gen + 1,
        )
        sub.env_stack = list(self.env_stack)
        return sub

    # ------------------------------------------------------------ 占位符/piece 发射

    def _ph(self, typ: PhType, body: str, cut_end: int | None = None) -> str:
        r"""签发占位符（body → ph_map）。``cut_end`` = 构造在源串的后一位。

        BUG1 回归断言（docs/07 §11）：ph 体以 ``\\letters`` 结尾且源串后继
        仍是字母 → 单 token 参数切断命令名，记 ``letters_cut`` warning。
        """
        if (
            cut_end is not None
            and cut_end < len(self._tex)
            and self._tex[cut_end].isalpha()
            and _LETTER_TAIL_RX.search(body)
        ):
            self.state.warnings.append(
                ScanWarning("letters_cut", self.base + cut_end, body[-40:])
            )
        return self.state.issuer.new(typ, body, self.state.ph_map)

    def _ph_into_run(
        self,
        typ: PhType,
        body: str,
        byte_start: int,
        cut_end: int | None = None,
    ) -> None:
        """一切占位符进 run 的唯一入口（math-debt 记账，§3.3）。

        body 内未转义 ``$`` 为奇 → ``math_debt`` 压 run 下标栈。
        """
        if self._run_start is None:
            self._run_start = byte_start
        ph = self._ph(typ, body, cut_end)
        self._run.append(ph)
        if unescaped_dollar_odd(body):
            self.math_debt.append(len(self._run) - 1)

    def _rappend(self, s: str, byte_start: int) -> None:
        """Run 追加（run 覆盖区间必连续 → 记首 append 的字节起点）。"""
        if s:
            if self._run_start is None:
                self._run_start = byte_start
            self._run.append(s)

    def _emit(self, lstart: int, lend: int) -> None:
        """LITERAL piece：覆盖局部区间 ``[lstart, lend)``。"""
        if lend > lstart:
            self._emit_text(lstart, lend, self._tex[lstart:lend])

    def _emit_text(self, lstart: int, lend: int, text: str) -> None:
        """LITERAL piece（显式文本）：run 内含 ``[[X_n]]`` 时 text≠原切片。"""
        if lend > lstart:
            self.pieces.append(
                Piece(
                    PieceKind.LITERAL,
                    Span(self.base + lstart, self.base + lend),
                    text,
                    self.env_stack[-1] if self.env_stack else None,
                )
            )

    def _emit_ph(self, typ: PhType, lstart: int, lend: int, body: str) -> None:
        """独立 PROTECTED piece（body 可与 ``tex[lstart:lend]`` 不同）。"""
        ph = self._ph(typ, body, lend)
        self.pieces.append(
            Piece(
                PieceKind.PROTECTED,
                Span(self.base + lstart, self.base + lend),
                ph,
                self.env_stack[-1] if self.env_stack else None,
            )
        )

    # ------------------------------------------------------------ chunk / run

    def _new_chunk(self, content: str, context: str, gspan: Span) -> str:
        """登记 chunk，返回 ``[[CHUNK_id]]``。"""
        cid = len(self.state.chunks)
        self.state.chunks.append(
            Chunk(
                id=cid,
                content=content,
                context=context,
                span=gspan,
                env=self.env_stack[-1] if self.env_stack else None,
                placeholders=PH_RX.findall(content),
            )
        )
        return f"[[CHUNK_{cid}]]"

    def _split_core(self, core: str) -> list[str]:  # noqa: C901 — 切点优先级链，平铺即 §3.8 规则序
        """超大 chunk 二次切分（§3.8 原子上限）：``[[X_n]]`` 边界优先。"""
        if len(core) <= CHUNK_MAX:
            return [core]
        parts: list[str] = []
        i, n = 0, len(core)
        while i < n:
            hard = min(i + CHUNK_MAX, n)
            if hard >= n:
                parts.append(core[i:])
                break
            window = core[i:hard]
            cut = -1
            for m in PH_RX.finditer(window):  # 占位符尾是最安全切点
                cut = m.end()
            if cut <= 0:
                ws = window.rfind("\n\n")
                if ws > 0:
                    cut = ws + 2
            if cut <= 0:
                for ch in (". ", "} ", " "):
                    ws = window.rfind(ch)
                    if ws > CHUNK_MAX // 2:
                        cut = ws + len(ch)
                        break
            if cut <= 0:  # 硬切，但不许切在 [[X_n]] 中间
                tail = core[hard - _CUT_PROBE : hard + _CUT_PROBE]
                lead = PH_RX.search(tail)
                cut = (
                    hard
                    - i
                    + (
                        lead.end() - _CUT_PROBE
                        if lead and lead.start() < _CUT_PROBE < lead.end()
                        else 0
                    )
                )
            parts.append(core[i : i + cut])
            i += cut
        return parts

    def _flush_run(self, end_pos: int) -> None:
        """分块规则（§3.8 原样 + 原子上限切分）。``end_pos`` = run 末字节后一位。"""
        s = "".join(self._run)
        self._run.clear()
        rs = self._run_start
        self._run_start = None
        self.math_debt.clear()  # 跨段不追 math debt
        if rs is None:
            return
        re_ = end_pos
        if not s.strip() or self.mode is ScanMode.MINED_ONLY:
            # run 渲染文本可能含 [[X_n]]（占位符已在 run 内）——发 s 而非原切片，
            # 否则占位符从 protected_tex 消失成死 ph（泄漏：caption 内裸 $/\cite）。
            self._emit_text(rs, re_, s)
            return
        lead = _LEAD_WS_RX.match(s).group(0) if s else ""
        trail_m = _TRAIL_WS_RX.search(s)
        trail = trail_m.group(0) if trail_m else ""
        core = s[len(lead) : len(s) - len(trail) if trail else len(s)]
        clean = PH_RX.sub(" ", core)
        clean = _CLEAN_CMD_RX.sub(" ", clean)
        clean = _CLEAN_NONALPHA_RX.sub(" ", clean).strip()
        force = self.force_chunk
        self.force_chunk = False
        if len(clean) < CHUNK_MIN and not (force and clean):
            self._emit_text(rs, re_, s)
            return
        # 首尾空白作字面保留 → chunk 为纯文本核，identity 无损
        self._emit(rs, rs + len(lead))
        core_start, core_end = rs + len(lead), re_ - len(trail)
        gspan = Span(self.base + core_start, self.base + core_end)
        refs = "".join(
            self._new_chunk(part, "item" if force else "paragraph", gspan)
            for part in self._split_core(core)
        )
        self.pieces.append(
            Piece(
                PieceKind.CHUNK_REF,
                gspan,
                refs,
                self.env_stack[-1] if self.env_stack else None,
            )
        )
        self._emit(core_end, re_)

    # ------------------------------------------------------------ 主循环

    def scan(self, tex: str, preamble_end: int = 0) -> ScanResult:
        r"""扫 tex → pieces。``preamble_end``：``\begin{document}`` 的后一位。"""
        self._tex = tex
        self._run = []
        self._run_start = None
        n = len(tex)
        i = preamble_end
        if preamble_end:
            register_macros_in(tex[:preamble_end], self.state)
            self._emit(0, preamble_end)
        while i < n:
            c = tex[i]

            # 1. 命令先吃（\verb/\url/verbatim env 的 % 永远到不了分支 2）
            if c == "\\":
                name, j = read_cmd_name(tex, i)
                i = self._dispatch_cmd(i, name, j)
                continue

            # 2. 注释（能到这里必是真注释）
            if c == "%":
                k = tex.find("\n", i)
                kend = n if k < 0 else k
                if self.in_arg:
                    self._ph_into_run(PhType.COMMENT, tex[i:kend], i)
                else:
                    self._flush_run(i)
                    self._emit(i, kend)
                i = kend
                continue

            # 3. 数学 $..$ / $$..$$（含 math-debt repair）
            if c == "$":
                i = self._on_dollar(i)
                continue

            # 4. 空行分段：\n + 空白* + \n → 段落边界
            if c == "\n":
                k = i + 1
                while k < n and tex[k] in " \t":
                    k += 1
                if k < n and tex[k] == "\n":
                    self._rappend(tex[i:k], i)
                    self._flush_run(k)
                    i = k
                    continue
                self._rappend(c, i)
                i += 1
                continue

            # 5. 普通字符（含 { } ~ 等，逐字入 run）
            self._rappend(c, i)
            i += 1

        self._flush_run(n)
        return ScanResult(
            protected_tex="".join(p.text for p in self.pieces),
            chunks=self.state.chunks,
            ph_map=self.state.ph_map,
            macros=self.state.macros,
            pieces=self.pieces,
            inputs=self.state.inputs,
            warnings=self.state.warnings,
        )

    # ------------------------------------------------------------ 数学配对 + debt

    def _on_dollar(self, i: int) -> int:
        """``$`` 分支：debt 修复 → ``$$`` → ``$``；失败逐字 + warning。"""
        tex, n = self._tex, len(self._tex)
        # debt repair：占位符体内开出数学的闭合符（§3.3 正确性论证）
        if self.math_debt:
            idx = self.math_debt.pop()
            tail = "".join(self._run[idx:]) + "$"
            del self._run[idx:]
            self._run.append(self._ph(PhType.MATH, tail))
            self.state.warnings.append(
                ScanWarning("debt_repair", self.base + i, tail[:60])
            )
            return i + 1
        if tex.startswith("$$", i):
            e = tex.find("$$", i + 2)
            if e >= 0 and "\n\n" not in tex[i:e]:
                self._ph_into_run(PhType.MATH, tex[i : e + 2], i, e + 2)
                return e + 2
            self._rappend("$", i)
            return i + 1
        j = i + 1
        ok = False
        while j < n:
            if tex[j] == "\\":
                j += 2
                continue
            if tex[j] == "$":
                ok = True
                break
            if tex[j] == "\n" and j + 1 < n and tex[j + 1] == "\n":
                break
            j += 1
        if ok and "\n\n" not in tex[i : j + 1]:
            self._ph_into_run(PhType.MATH, tex[i : j + 1], i, j + 1)
            return j + 1
        self._rappend("$", i)
        self.state.warnings.append(
            ScanWarning("unpaired_dollar", self.base + i, tex[i : i + 20])
        )
        return i + 1

    # ------------------------------------------------------------ 参数读取

    def _args(  # noqa: C901, PLR0912, PLR0915 — argspec 字母各一分支，平铺即 §5.3 表
        self,
        i: int,
        spec: list[ArgSpec] | int,
        *,
        has_opt: bool = False,
        allow_single_token: bool = True,
    ) -> tuple[list[ArgSpan], int]:
        r"""从 i 起按 argspec 读参（§5.3）。

        ``spec`` 为 int 等价 ``[m]*n``（classic 宏路径）。
        ``allow_single_token=False`` 唯一调用点 = 未知命令保护（分派 19）——
        修泄漏机制 A 第一层。单 token 兜底读到 ``\\`` 必须停止（BUG1 补丁）。
        缺省可选参数发零宽 ArgSpan 占位（protect_args 位序对齐）。
        """
        tex = self._tex
        n = len(tex)
        items = [ArgSpec("m")] * spec if isinstance(spec, int) else list(spec)
        if has_opt:
            items = [ArgSpec("o"), *items]
        pos = (
            ws_skip(tex, i) if items else i
        )  # 空 spec 不吃命令后空白（\CX\ngate 误吞 \n 教训）
        out: list[ArgSpan] = []
        for s in items:
            pos = ws_skip(tex, pos)
            if pos >= n:
                out.append(ArgSpan(Span(pos, pos), Span(pos, pos), s))
                continue
            c = tex[pos]
            if s.kind in ("m", "v"):
                if c == "{":
                    e = match_brace(tex, pos, verbatim=s.kind == "v")
                    if e is None:
                        break
                    out.append(ArgSpan(Span(pos + 1, e - 1), Span(pos, e), s))
                    pos = e
                elif c == "[":
                    e = match_bracket(tex, pos)
                    if e is None:
                        break
                    out.append(ArgSpan(Span(pos + 1, e - 1), Span(pos, e), s))
                    pos = e
                elif c == "\\" or not allow_single_token:
                    # 单 token 参数不跨 '\'（BUG1）；禁用即停
                    break
                else:
                    out.append(ArgSpan(Span(pos, pos + 1), Span(pos, pos + 1), s))
                    pos += 1
            elif s.kind in ("o", "O"):
                if c == "[":
                    e = match_bracket(tex, pos)
                    if e is None:
                        break
                    out.append(ArgSpan(Span(pos + 1, e - 1), Span(pos, e), s))
                    pos = e
                else:
                    out.append(ArgSpan(Span(pos, pos), Span(pos, pos), s))
            elif s.kind == "s":
                if c == "*":
                    out.append(ArgSpan(Span(pos, pos + 1), Span(pos, pos + 1), s))
                    pos += 1
                else:
                    out.append(ArgSpan(Span(pos, pos), Span(pos, pos), s))
            elif s.kind == "t" and s.delim:
                # 测试单字符存在性（t* 等）：在则消费该字符
                if c == s.delim[0]:
                    out.append(ArgSpan(Span(pos, pos + 1), Span(pos, pos + 1), s))
                    pos += 1
                else:
                    out.append(ArgSpan(Span(pos, pos), Span(pos, pos), s))
            elif s.kind in ("d", "D", "r", "R") and s.delim:
                op, cl = s.delim[0], s.delim[-1]
                if c == op:
                    e = tex.find(cl, pos + 1)
                    if e < 0:
                        break
                    out.append(ArgSpan(Span(pos + 1, e), Span(pos, e + 1), s))
                    pos = e + 1
                elif s.kind in ("r", "R"):
                    break  # 定界强制缺失 → 参数不匹配，停读
                else:
                    out.append(ArgSpan(Span(pos, pos), Span(pos, pos), s))
            # 'e'/'b'/未知：不消费（修饰/环境体语义不在调用点）
        return out, pos

    def _find_env_end(self, i: int, env: str) -> tuple[int, int] | None:  # noqa: C901 — begin/end/宏端点三分支单遍查找，平铺即 §3.5
        r"""找 env 的匹配 ``\end``（含宏端点），注释安全 + ``*`` 归一。

        两侧 ``rstrip('*')`` 归一比较（``\begin{multline*}…\end{multline}``
        笔误场景，泄漏 C1 修复）。命中返回 (end 后一位, tag 起点)；未命中 None。
        """
        tex, n = self._tex, len(self._tex)
        target = env.rstrip("*")
        depth = 1
        while i < n:
            c = tex[i]
            if c == "%":
                k = tex.find("\n", i)
                i = n if k < 0 else k + 1
                continue
            if c == "\\":
                name, j = read_cmd_name(tex, i)
                if name == "begin":
                    sub, e2 = env_name_at(tex, j)
                    if sub is not None and sub.rstrip("*") == target:
                        depth += 1
                    i = e2 or j
                    continue
                if name == "end":
                    sub, e2 = env_name_at(tex, j)
                    if sub is not None and sub.rstrip("*") == target:
                        depth -= 1
                        if depth == 0:
                            return e2, i
                    i = e2 or j
                    continue
                m = self.state.macros.cmds.get(name)
                if (
                    m is not None
                    and m.kind is MacroKind.ENV_BEGIN
                    and m.target_env.rstrip("*") == target
                ):
                    depth += 1
                elif (
                    m is not None
                    and m.kind is MacroKind.ENV_END
                    and m.target_env.rstrip("*") == target
                ):
                    depth -= 1
                    if depth == 0:
                        return j, i
                i = j
                continue
            i += 1
        return None

    # ------------------------------------------------------------ 命令分派（19 行）

    def _dispatch_cmd(self, i: int, name: str, j: int) -> int:  # noqa: C901, PLR0911, PLR0912, PLR0915 — §3.2 分派表 19 行平铺，顺序即语义
        r"""分派表 §3.2——顺序即语义，不得调换。``i``=``\`` 位，``j``=名后位。"""
        tex, n = self._tex, len(self._tex)

        # 1. \verb|..| / \verb* / \lstinline 定界形（EOL 上限，W9/W10）
        if name in ("verb", "lstinline"):
            return self._handle_verb(i, j, name)

        # 2. 定义命令：flush + 整段 LITERAL + 登记宏表
        if name in DEF_NAMES:
            self._flush_run(i)
            end = scan_macro_def(tex, i, name, self.state)
            self._emit(i, end)
            return end

        # 3. \newif：flush + LITERAL + 注册 \Xtrue/\Xfalse + ifflags
        if name == "newif":
            self._flush_run(i)
            p = ws_skip(tex, j)
            if p < n and tex[p] == "\\":
                cond, e2 = read_cmd_name(tex, p)
                register_newif(self.state, cond, self.base + i)
                self._emit(i, e2)
                return e2
            self._emit(i, j)
            return j

        # 4. \begin{env}
        if name == "begin":
            env, e2 = env_name_at(tex, j)
            if env is None:
                self._rappend(tex[i:j], i)
                return j
            return self._handle_env(i, env, e2)

        # 5. \end{env}
        if name == "end":
            env, e2 = env_name_at(tex, j)
            end = e2 or j
            if self.in_arg:
                self._ph_into_run(PhType.ENVTAG, tex[i:end], i, end)
                if env is not None:
                    self._env_pop(env)
                return end
            self._flush_run(i)
            if env == "document" and e2:
                self._emit(i, e2)  # \end{document} 本体
                self._emit(e2, n)  # 之后全逐字（顶层才截停）
                return n
            self._emit(i, end)
            if env is not None:
                self._env_pop(env)
            return end

        # 6. cite 族 → [[CITE]] 进 run
        if name in CITE_NAMES or name.startswith("cite"):
            return self._protect_call(i, j, PhType.CITE)

        # 7. ref 族 → [[REF]]（排除 href 与 TRANSPARENT）
        if name in REF_NAMES or (
            name.endswith("ref") and name not in TRANSPARENT_NAMES and name != "href"
        ):
            return self._protect_call(i, j, PhType.REF)

        # 8. PROTECT_NAMES → 类型映射；url/path verbatim 括号
        if name in PROTECT_NAMES:
            typ = _PROTECT_TYP.get(name, PhType.CMD)
            vb = name in ("url", "path")
            return self._protect_call(i, j, typ, verbatim=vb)

        # 9. \href{url}{text}：url→[[HREF]]，text 继续扫
        if name == "href":
            pos = ws_skip(tex, j)
            if pos < n and tex[pos] == "{":
                e = match_brace(tex, pos, verbatim=True)
                if e:
                    self._rappend(tex[i:pos], i)
                    self._ph_into_run(PhType.HREF, tex[pos:e], pos, e)
                    return e
            self._rappend(tex[i:j], i)
            return j

        # 10. \input/\include 族：flush + LITERAL + 记 inputs[]；in_arg → [[CMD]]
        if name in _INPUT_SCAN_CMDS:
            if self.in_arg:
                return self._protect_call(i, j, PhType.CMD)
            pos = ws_skip(tex, j)
            end = j
            if pos < n and tex[pos] == "{":
                e = match_brace(tex, pos)
                if e:
                    end = e
                    if name in ("import", "subimport"):
                        p2 = ws_skip(tex, e)
                        if p2 < n and tex[p2] == "{":
                            e3 = match_brace(tex, p2)
                            if e3:
                                fname = tex[p2 + 1 : e3 - 1].strip()
                                self.state.inputs.append((self.base + i, fname))
                                end = e3
                    else:
                        fname = tex[pos + 1 : e - 1].strip()
                        self.state.inputs.append((self.base + i, fname))
            elif pos < n and tex[pos] in _FILENAME_CHARS:
                k = pos
                while k < n and tex[k] in _FILENAME_CHARS:
                    k += 1
                self.state.inputs.append((self.base + i, tex[pos:k]))
                end = k
            self._flush_run(i)
            self._emit(i, end)
            return end

        # 11. chunk 参数命令
        if name in CHUNK_ARG_NAMES:
            return self._handle_chunk_arg(i, j, name)

        # 12. 整块保护（\author{..} 等）；in_arg → [[AUTHOR]] 进 run 不 flush
        if name in PROTECT_BLOCK_NAMES:
            pos = ws_skip(tex, j)
            if pos < n and tex[pos] == "[":
                e2 = match_bracket(tex, pos)
                if e2:
                    pos = ws_skip(tex, e2)
            if pos < n and tex[pos] == "{":
                e = match_brace(tex, pos)
                if e:
                    if self.in_arg:
                        self._ph_into_run(PhType.AUTHOR, tex[i:e], i, e)
                    else:
                        self._flush_run(i)
                        self._emit_ph(PhType.AUTHOR, i, e, tex[i:e])
                    return e
            if self.in_arg:
                self._ph_into_run(PhType.AUTHOR, tex[i:j], i, j)
            else:
                self._flush_run(i)
                self._emit_ph(PhType.AUTHOR, i, j, tex[i:j])
            return j

        # 13. 透明命令：命令名逐字进 run，参数随主流
        if name in TRANSPARENT_NAMES:
            self._rappend(tex[i:j], i)
            return j

        # 14. 边界命令：文本 run 硬边界；in_arg → _protect_call → [[CMD]]
        if name in BOUNDARY_NAMES:
            if self.in_arg:
                return self._protect_call(i, j, PhType.CMD)
            self._flush_run(i)
            self._emit(i, j)
            if name == "item":
                self.force_chunk = True  # item 文本恒可译
            return j

        # 15. 条件命令 / LITERAL 类宏（\if 两档，§8.6）
        if COND_RX.match(name) or self._is_literal_macro(name):
            return self._handle_cond(i, j, name)

        # 16. 数学定界 \[ \( \] \)
        if name == "[":
            e = tex.find("\\]", j)
            if e > 0 and "\n\n" not in tex[i:e]:
                self._ph_into_run(PhType.MATH, tex[i : e + 2], i, e + 2)
                return e + 2
            self._rappend(tex[i:j], i)
            return j
        if name == "(":
            e = tex.find("\\)", j)
            if e > 0 and "\n\n" not in tex[i:e]:
                self._ph_into_run(PhType.MATH, tex[i : e + 2], i, e + 2)
                return e + 2
            self._rappend(tex[i:j], i)
            return j
        if name in ("]", ")"):
            self._rappend(tex[i:j], i)
            return j

        # 17. 行内字面（重音/符号/品牌/旧式字体开关/单字符命令）
        if (
            name in INLINE_LITERAL_CMDS
            or name in FONT_SWITCHES
            or (len(name) == 1 and (name in ACCENT_CHARS or not name.isalpha()))
        ):
            self._rappend(tex[i:j], i)
            return j

        # 18. 宏表命中
        m = self.state.macros.cmds.get(name)
        if m is not None:
            return self._handle_macro(i, j, m)

        # 19. 未知命令：有 {/[ 参数 → [[CMD]]（禁单 token，修泄漏 A）；
        #     否则逐字进 run
        pos = ws_skip(tex, j)
        if pos < n and tex[pos] in "{[":
            args, end = self._args(j, 6, has_opt=True, allow_single_token=False)
            if any(a.full.end > a.full.start for a in args):
                self._ph_into_run(PhType.CMD, tex[i:end], i, end)
                return end
        self._rappend(tex[i:j], i)
        return j

    # ------------------------------------------------------------ verb

    def _handle_verb(self, i: int, j: int, name: str) -> int:
        r"""``\verb|x|`` / ``\verb*x`` / ``\lstinline[opt]|x|`` → ``[[VERB]]``。

        定界符搜索上限 = 下一 ``\n``（W9：TeX 里 verb 不跨行）。
        ``\lstinline`` 支持 ``[opts]`` 前缀与 ``{...}`` 配对形（W10）。
        """
        tex, n = self._tex, len(self._tex)
        k = j
        if name == "verb" and k < n and tex[k] == "*":
            k += 1
        if name == "lstinline":
            k = ws_skip(tex, k)
            if k < n and tex[k] == "[":
                e2 = match_bracket(tex, k)
                if e2:
                    k = ws_skip(tex, e2)
        if k < n:
            d = tex[k]
            if d == "{":
                e = match_brace(tex, k, verbatim=True)
                if e:
                    self._ph_into_run(PhType.VERB, tex[i:e], i, e)
                    return e
            elif d not in " \t\n":
                eol = tex.find("\n", k + 1)
                limit = n if eol < 0 else eol
                e = tex.find(d, k + 1, limit)
                if e > 0:
                    self._ph_into_run(PhType.VERB, tex[i : e + 1], i, e + 1)
                    return e + 1
        self._rappend(tex[i:j], i)
        return j

    # ------------------------------------------------------------ env

    def _handle_env(self, i: int, env: str, j: int) -> int:  # noqa: C901, PLR0911, PLR0915 — §3.5 环境四分类各一段，平铺即规则表
        r"""``\begin{env}`` 已读到 j（env 名 ``}`` 后）。§3.5 全规则。"""
        tex = self._tex
        reg = self.state.macros.envs.get(env)
        if env in VERBATIM_ENVS:
            self._flush_run(i)
            pat = "\\end{" + env + "}"
            k = tex.find(pat, j)
            if k < 0:
                self._emit(i, j)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", self.base + i, env)
                )
                return j
            self._emit_ph(PhType.VERB, i, k + len(pat), tex[i : k + len(pat)])
            return k + len(pat)
        if env in MATH_ENVS:
            hit = self._find_env_end(j, env)
            if hit is None:
                self._flush_run(i)
                self._emit(i, j)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", self.base + i, env)
                )
                return j
            end, _tag = hit
            self._ph_into_run(PhType.MATH, tex[i:end], i, end)
            return end
        if env in PROTECTED_ENVS or (reg is not None and reg.kind == "protected"):
            hit = self._find_env_end(j, env)
            if hit is None:
                self._flush_run(i)
                self._emit(i, j)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", self.base + i, env)
                )
                return j
            end, tag_start = hit
            self._flush_run(i)
            body = self._env_with_mined(i, j, env, end, tag_start)
            self._emit_ph(PhType.ENV, i, end, body)
            return end
        # 其余（透明容器/未知/注册 transparent env）
        if self.in_arg:
            transparent = env in ARG_TRANSPARENT_ENVS or (
                reg is not None and reg.kind == "transparent"
            )
            if transparent:
                pos = self._eat_env_args(j, env, reg)
                self._ph_into_run(PhType.ENVTAG, tex[i:pos], i, pos)
                self.env_stack.append(env)
                return pos
            # 未知/结构环境 in_arg → 整段 [[ENV]] 进 run（不 flush，修泄漏 C2）
            hit = self._find_env_end(j, env)
            if hit is None:
                self._ph_into_run(PhType.ENVTAG, tex[i:j], i, j)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", self.base + i, env)
                )
                return j
            end, tag_start = hit
            body = self._env_with_mined(i, j, env, end, tag_start)
            if self._run_start is None:
                self._run_start = i
            ph = self._ph(PhType.ENV, body, end)
            self._run.append(ph)
            if unescaped_dollar_odd(body):
                self.math_debt.append(len(self._run) - 1)
            return end
        self._flush_run(i)
        pos = self._eat_env_args(j, env, reg)
        self._emit(i, pos)
        self.env_stack.append(env)
        return pos

    def _eat_env_args(self, j: int, env: str, reg: EnvEntry | None) -> int:
        r"""``\begin`` 行尾部：``[opt]`` + ``ENV_MANDATORY_ARG``/登记 nargs 的 ``{arg}``。"""
        tex, n = self._tex, len(self._tex)
        pos = ws_skip(tex, j)
        if pos < n and tex[pos] == "[":
            e2 = match_bracket(tex, pos)
            if e2:
                pos = ws_skip(tex, e2)
        mand = 1 if env in ENV_MANDATORY_ARG else 0
        if reg is not None:
            mand = max(mand, reg.nargs)
        for _ in range(mand):
            if pos < n and tex[pos] == "{":
                e2 = match_brace(tex, pos)
                if e2:
                    pos = ws_skip(tex, e2)
                    continue
            break
        return pos

    def _env_pop(self, env: str) -> None:
        r"""``\end{env}`` → env_stack 弹（rstrip 归一；stray → warning）。"""
        target = env.rstrip("*")
        if self.env_stack and self.env_stack[-1].rstrip("*") == target:
            self.env_stack.pop()
            return
        if target in {e.rstrip("*") for e in self.env_stack}:
            while self.env_stack and self.env_stack[-1].rstrip("*") != target:
                self.env_stack.pop()
            if self.env_stack:
                self.env_stack.pop()
            return
        if self.env_stack:
            self.state.warnings.append(
                ScanWarning("stray_end", self.base, f"\\end{{{env}}}")
            )

    def _env_with_mined(
        self, i: int, j: int, env: str, end: int, tag_start: int
    ) -> str:
        r"""保护环境体 → mined_only 子扫挖 caption/footnote → 渲染体。

        返回 ``[[ENV]]`` 的 body 文本（begin 行 + mined 渲染 + end tag）。
        """
        inner = self._tex[j:tag_start]
        if self.gen >= MAX_GEN:
            return self._tex[i:end]  # 超代数不再内挖，原样保护
        sub = self.spawn(mode=ScanMode.MINED_ONLY, in_arg=False, base=self.base + j)
        sub.env_stack.append(env)
        rendered = sub.scan(inner).protected_tex
        return self._tex[i:j] + rendered + self._tex[tag_start:end]

    # ------------------------------------------------------------ chunk-arg

    def _handle_chunk_arg(self, i: int, j: int, name: str) -> int:
        r"""``\section[opt]{arg}``：前缀逐字，arg → 独立 chunk（§3.6）。"""
        tex = self._tex
        pos = ws_skip(tex, j)
        if pos < len(tex) and tex[pos] == "*":
            pos += 1
        spec_str, tidx = CHUNK_ARG_SPEC.get(name, ("om", 1))
        spec = _chunk_spec_cached(spec_str)
        args, _end = self._args(pos, spec, allow_single_token=True)
        # 可译参数：spec 位序取 tidx，越界退最后实参（零宽缺省参不算）
        real = [a for a in args if a.full.end > a.full.start]
        target = None
        if tidx < len(args) and args[tidx].full.end > args[tidx].full.start:
            target = args[tidx]
        elif real:
            target = real[-1]
        if target is None or target.full == target.content or self.gen >= MAX_GEN:
            # 无 {..} 参数 / 单 token 参数 / 超代数 → 命令名逐字
            self._rappend(tex[i:j], i)
            return j
        cs, ce = target.content.start, target.content.end
        fe = target.full.end
        inner = tex[cs:ce]
        if not inner.strip():
            self._rappend(tex[i:fe], i)
            return fe
        sub = self.spawn(mode=ScanMode.MINED_ONLY, in_arg=True, base=self.base + cs)
        rendered = sub.scan(inner).protected_tex
        if self.in_arg:
            # 嵌套 chunk-arg 内联化：文本并入父 chunk
            self._rappend(tex[i:cs] + rendered + tex[ce:fe], i)
            return fe
        self._flush_run(i)
        self._emit(i, cs)  # \caption{ 前缀
        gspan = Span(self.base + cs, self.base + ce)
        refs = "".join(
            self._new_chunk(part, name, gspan) for part in self._split_core(rendered)
        )
        self.pieces.append(
            Piece(
                PieceKind.CHUNK_REF,
                gspan,
                refs,
                self.env_stack[-1] if self.env_stack else None,
            )
        )
        self._emit(ce, fe)  # }
        return fe

    # ------------------------------------------------------------ 宏处理

    def _handle_macro(self, i: int, j: int, m: MacroEntry) -> int:  # noqa: C901, PLR0911, PLR0912, PLR0915 — §3.7 五分类各一段，平铺即表
        """宏表命中（§3.7）。"""
        tex = self._tex
        self.state.steps += 1
        if self.state.steps > BUDGET:
            self._ph_into_run(PhType.MACRO, tex[i:j], i, j)
            if self.state.steps == BUDGET + 1:
                self.state.warnings.append(
                    ScanWarning("expansion_overflow", self.base + i, m.name)
                )
            return j
        if m.kind is MacroKind.ENV_BEGIN:
            env = m.target_env
            hit = self._find_env_end(j, env)
            if hit is None:
                self._rappend(tex[i:j], i)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", self.base + i, env)
                )
                return j
            end, tag_start = hit
            if env in MATH_ENVS or env.rstrip("*") in MATH_ENVS:
                self._ph_into_run(PhType.MATH, tex[i:end], i, end)
            elif env in VERBATIM_ENVS:
                self._flush_run(i)
                self._emit_ph(PhType.VERB, i, end, tex[i:end])
            elif env in PROTECTED_ENVS:
                self._flush_run(i)
                body = self._env_with_mined(i, j, env, end, tag_start)
                self._emit_ph(PhType.ENV, i, end, body)
            else:
                self._ph_into_run(PhType.ENV, tex[i:end], i, end)
            return end
        if m.kind is MacroKind.ENV_END:
            self._rappend(tex[i:j], i)  # 裸 \ee 容错
            return j
        if m.kind is MacroKind.OPAQUE:
            _args, end = self._args(j, m.spec, allow_single_token=True)
            self._ph_into_run(PhType.MACRO, tex[i:end], i, end)
            return end
        if m.kind is MacroKind.LITERAL:
            self._rappend(tex[i:j], i)
            return j
        # TRANSPARENT：保护位参数 → [[KEY]]；文本位 → in_arg 子扫渲染
        args, end = self._args(j, m.spec, allow_single_token=True)
        if not args:
            self._rappend(tex[i:end], i)
            return end
        self._rappend(tex[i:j], i)
        prev = j
        for k, arg in enumerate(args):
            self._rappend(tex[prev : arg.full.start], prev)  # 参数间空白逐字
            self._rappend(
                tex[arg.full.start : arg.content.start], arg.full.start
            )  # 开括号
            if arg.spec is not None and arg.spec.kind == "s":
                self._rappend(tex[arg.full.start : arg.full.end], arg.full.start)
            elif k < len(m.protect_args) and m.protect_args[k]:
                body = tex[arg.content.start : arg.content.end]
                self._ph_into_run(PhType.KEY, body, arg.content.start, arg.content.end)
            elif arg.content.end > arg.content.start and self.gen < MAX_GEN:
                sub = self.spawn(in_arg=True, base=self.base + arg.content.start)
                rendered = sub.scan(
                    tex[arg.content.start : arg.content.end]
                ).protected_tex
                self._rappend(rendered, arg.content.start)
            else:
                self._rappend(
                    tex[arg.content.start : arg.content.end], arg.content.start
                )
            self._rappend(
                tex[arg.content.end : arg.full.end], arg.content.end
            )  # 闭括号
            prev = arg.full.end
        self._rappend(tex[prev:end], prev)
        return end

    # ------------------------------------------------------------ \if 两档

    def _is_literal_macro(self, name: str) -> bool:
        m = self.state.macros.cmds.get(name)
        return m is not None and m.kind is MacroKind.LITERAL

    def _handle_cond(self, i: int, j: int, name: str) -> int:  # noqa: C901, PLR0911 — 两档+宏前置各早退一支
        r"""``\if`` 两档（§8.6）：可求值 → ``_process_if``；不可求值 → 界标。

        判定前置：先查宏表（``\ifb`` 单位宏 / ``\ifAnonymous{T}{F}`` 双参宏），
        ``if*`` 紧跟 ``{`` 即宏调用。in_arg 一律 ``[[COND]]`` 进 run。
        """
        tex, n = self._tex, len(self._tex)
        m = self.state.macros.cmds.get(name)
        if m is not None and m.kind is not MacroKind.LITERAL:
            if name.startswith("if"):
                # 非原语 if* = 宏调用（\ifAnonymous/\ifAppendicesIncluded）：
                # 整段保护，不走透明分流（名字进 run 会触发 conditional 泄漏）
                return self._protect_call(
                    i, j, PhType.COND if self.in_arg else PhType.CMD
                )
            return self._handle_macro(i, j, m)
        if name.startswith("if"):
            if self.in_arg:
                # in_arg：if* 紧跟 { 即双参宏调用 → 整调用 [[COND]]
                p = ws_skip(tex, j)
                if m is None and p < n and tex[p] == "{":
                    return self._protect_call(i, j, PhType.COND)
                _w, end = self._eval_if(j, name)
                end = max(end, j)
                self._ph_into_run(PhType.COND, tex[i:end], i, end)
                return end
            if m is None:
                # 顶层：先 \newif 旗标，再可求值族，再 { 宏调用形，最后结构界标
                flag = name[2:]
                if flag in self.state.ifflags:
                    return self._process_if(i, j, which=self.state.ifflags[flag])
                which, cond_end = self._eval_if(j, name)
                if which is not None:
                    return self._process_if(i, cond_end, which=which)
                p = ws_skip(tex, j)
                if p < n and tex[p] == "{":
                    return self._protect_call(i, j, PhType.CMD)
                # 结构界标：\if/\else/\fi literal，双分支都进
                self._flush_run(i)
                self._emit(i, j)
                return j
        # else/fi/or 或 LITERAL 宏（含 \newif 旗标写入副作用）
        if self.in_arg:
            self._ph_into_run(PhType.COND, tex[i:j], i, j)
        else:
            self._flush_run(i)
            self._emit(i, j)
        self._set_ifflag(name)
        return j

    def _set_ifflag(self, name: str) -> None:
        r"""``\Xtrue/\Xfalse``（\newif 注册的 LITERAL 宏）→ 旗标副作用。"""
        if name.endswith("true") and name[:-4] in self.state.ifflags:
            self.state.ifflags[name[:-4]] = True
        elif name.endswith("false") and name[:-5] in self.state.ifflags:
            self.state.ifflags[name[:-5]] = False

    def _eval_if(self, j: int, name: str) -> tuple[bool | int | None, int]:  # noqa: C901, PLR0911, PLR0912 — 可求值族十一种各一分支，平铺即 §8.6 表
        r"""``\if`` 条件求值。``(which, cond_end)``；which=None → 结构界标。

        条件部分按语法读掉（``\ifnum`` 数-关系-数、``\ifx`` 两 token 等）；
        读不出的按 None 返回但条件串仍消费——界标 literal 覆盖 ``\if+cond``。
        """
        tex, n = self._tex, len(self._tex)
        if name == "iftrue":
            return True, j
        if name == "iffalse":
            return False, j
        if name == "ifmmode":
            return False, j  # 数学区已被 [[MATH]] 保护，到这里的恒非数学
        if name in IF_CONST:
            return IF_CONST[name], j
        if name in ("ifnum", "ifdim"):
            v1, p1 = self._read_number(j)
            p2 = ws_skip(tex, p1)
            rel = tex[p2] if p2 < n and tex[p2] in "<>=" else None
            p3 = p2 + 1 if rel else p2
            v2, p4 = self._read_number(p3)
            if v1 is not None and v2 is not None and rel:
                if rel == "<":
                    return v1 < v2, p4
                if rel == ">":
                    return v1 > v2, p4
                return v1 == v2, p4
            return None, max(p4, j)
        if name == "ifodd":
            v, p = self._read_number(j)
            return (v % 2 == 1) if v is not None else None, max(p, j)
        if name == "ifcase":
            v, p = self._read_number(j)
            return (v if v is not None and v >= 0 else None), max(p, j)
        if name in ("if", "ifcat"):
            t1, p1 = self._read_if_token(j)
            t2, p2 = self._read_if_token(p1)
            if t1 is not None and t2 is not None and "\\" not in (t1 + t2):
                if name == "if":
                    return t1 == t2, p2
                # \ifcat：字母类 vs 其他类的粗粒度 catcode 比较
                return t1.isalpha() == t2.isalpha(), p2
            return None, max(p2, j)
        if name == "ifx":
            t1, p1 = self._read_if_token(j)
            t2, p2 = self._read_if_token(p1)
            if t1 is not None and t2 is not None:
                if t1.startswith("\\") and t2.startswith("\\"):
                    if t1 == t2:
                        return True, p2
                    return None, p2  # \ifx 对宏 → 不可求值（结构界标）
                if "\\" not in (t1 + t2):
                    return t1 == t2, p2
            return None, max(p2, j)
        if name == "ifdefined":
            p = ws_skip(tex, j)
            if p < n and tex[p] == "\\":
                cname, e2 = read_cmd_name(tex, p)
                if cname in self.state.macros.cmds:
                    return True, e2
                return None, e2  # 未知 → 结构界标（召回优先，刻意分歧）
            return None, j
        if name == "ifcsname":
            e = tex.find("\\endcsname", j)
            if e > 0:
                cname = tex[j:e].strip()
                if cname in self.state.macros.cmds:
                    return True, e + len("\\endcsname")
                return None, e + len("\\endcsname")
            return None, j
        if name in IF_CONST_FALSE:
            return False, j
        if name in ("ifhbox", "ifvbox", "ifvoid"):
            _v, p = self._read_number(j)
            return False, max(p, j)
        return None, j

    def _read_number(self, i: int) -> tuple[int | None, int]:
        r"""读 TeX 数：可选符号 + 数字串 / ``'x`` / ```x`` 字符码 / ``\cs``。"""
        tex, n = self._tex, len(self._tex)
        pos = ws_skip(tex, i)
        sign = 1
        while pos < n and tex[pos] in "+-":
            if tex[pos] == "-":
                sign = -sign
            pos += 1
        pos = ws_skip(tex, pos)
        if pos >= n:
            return None, pos
        c = tex[pos]
        if c.isdigit():
            k = pos
            while k < n and tex[k].isdigit():
                k += 1
            return sign * int(tex[pos:k]), k
        if c in "'`" and pos + 1 < n:
            return sign * ord(tex[pos + 1]), pos + 2
        if c == "\\":
            _name, e2 = read_cmd_name(tex, pos)
            return None, e2  # 寄存器/内部量 → 消费但不求值
        if c == "{":
            e = match_brace(tex, pos)
            if e:
                return None, e  # 组 → 不求值但消费
        return None, pos

    def _read_if_token(self, i: int) -> tuple[str | None, int]:
        r"""``\if/\ifx`` 的一个 token：``\cs`` 带 ``\`` 前缀返回，字符原样。"""
        tex, n = self._tex, len(self._tex)
        pos = ws_skip(tex, i)
        if pos >= n:
            return None, pos
        if tex[pos] == "\\":
            name, e2 = read_cmd_name(tex, pos)
            return "\\" + name, e2
        return tex[pos], pos + 1

    def _process_if(  # noqa: C901, PLR0912, PLR0915 — case 收集字节级状态机，平铺即 §8.6/plasTeX processIfContent
        self, i: int, cond_end: int, *, which: bool | int
    ) -> int:
        r"""可求值 ``\if``：收集 case 到 ``\fi``，只推回选中支（§8.6）。

        字节级实现：``\if+cond`` → LITERAL；未选 case + ``\else/\or/\fi``
        → LITERAL；选中 case → spawn 子扫（pieces 经 base 并入主流）。
        ``\newif`` 整对保留（其后 ``\ifX`` 不计嵌套）；任何 ``if*`` 计嵌套。
        """
        tex, n = self._tex, len(self._tex)
        depth = 0
        seps: list[tuple[int, int]] = []
        pos = cond_end
        fi_start = fi_end = -1
        while pos < n:
            c = tex[pos]
            if c == "%":
                k = tex.find("\n", pos)
                pos = n if k < 0 else k + 1
                continue
            if c == "\\":
                nm, j2 = read_cmd_name(tex, pos)
                if nm == "newif":
                    p3 = ws_skip(tex, j2)
                    if p3 < n and tex[p3] == "\\":
                        _cn, j3 = read_cmd_name(tex, p3)
                        pos = j3
                    else:
                        pos = p3
                    continue
                if nm.startswith("if"):
                    depth += 1
                    pos = j2
                    continue
                if nm == "fi":
                    if depth == 0:
                        fi_start, fi_end = pos, j2
                        break
                    depth -= 1
                    pos = j2
                    continue
                if depth == 0 and nm in ("else", "or"):
                    seps.append((pos, j2))
                    pos = j2
                    continue
                pos = j2
                continue
            pos += 1
        self._flush_run(i)
        if fi_start < 0:
            self.state.warnings.append(
                ScanWarning("if_unterminated", self.base + i, tex[i : i + 30])
            )
            self._emit(i, n)
            return n
        idx = (0 if which else 1) if isinstance(which, bool) else which
        # case 区间：cond_end..sep0 | sep..sep | sepN..fi_start
        cases: list[tuple[int, int]] = []
        prev = cond_end
        for s, e in seps:
            cases.append((prev, s))
            prev = e
        cases.append((prev, fi_start))
        # 发射：LITERAL(\if+cond) → 逐 case（选中 spawn / 未选 LITERAL）+ sep LITERAL
        self._emit(i, cond_end)
        for k, (cs, ce) in enumerate(cases):
            if k == idx and ce > cs and self.gen < MAX_GEN:
                sub = self.spawn(in_arg=False, base=self.base + cs)
                sub.scan(tex[cs:ce])
                self.pieces.extend(sub.pieces)
            else:
                self._emit(cs, ce)
            if k < len(seps):
                self._emit(seps[k][0], seps[k][1])
        self._emit(fi_start, fi_end)
        return fi_end

    # ------------------------------------------------------------ 保护调用

    def _protect_call(
        self, i: int, j: int, typ: PhType, *, verbatim: bool = False
    ) -> int:
        r"""命令 + ``*?`` + ``[opt]*`` + ``{args}*`` 整段 → ``[[typ_n]]`` 进 run。"""
        tex, n = self._tex, len(self._tex)
        pos = j
        if pos < n and tex[pos] == "*":
            pos += 1
        for _ in range(3):
            p2 = ws_skip(tex, pos)
            if p2 < n and tex[p2] == "[":
                e = match_bracket(tex, p2)
                if e:
                    pos = e
                    continue
            break
        end = pos
        for _ in range(3):
            p2 = ws_skip(tex, end)
            if p2 < n and tex[p2] == "{":
                e = match_brace(tex, p2, verbatim=verbatim)
                if e is None:
                    break
                end = e
            else:
                break
        self._ph_into_run(typ, tex[i:end], i, end)
        return end


_CHUNK_SPEC_CACHE: dict[str, list[ArgSpec]] = {}


def _chunk_spec_cached(spec_str: str) -> list[ArgSpec]:
    """``CHUNK_ARG_SPEC`` 签名串 → ``list[ArgSpec]``（解析一次缓存）。"""
    if spec_str not in _CHUNK_SPEC_CACHE:
        _CHUNK_SPEC_CACHE[spec_str] = parse_argspec(spec_str)
    return _CHUNK_SPEC_CACHE[spec_str]
