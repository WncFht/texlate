r"""``latex/segmenter.args_handlers`` — 各行 handler（``args`` god-file 机械拆分叶）。

``\href``/``\input`` 族漏网/protect-block/边界命令（``BOUNDARY_TAIL``/
dimen 尾参/``\item`` 置 ``force_chunk``）/``\textcolor`` 透明头/
``\\[dimen]``/盒规格尾参/accent 单参/``\endinput`` 截停/``\[\(``
定界数学/``\if`` 两档界标/opaque 宏 spec 读参/未知 cs 探针+S3 字面
别名闸。逐 handler 即主流分派目标的实现面。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import texlate.latex.tables as _tables
from texlate.latex.gullet import MacroDef
from texlate.latex.model import ArgSpec, PhType, ScanWarning, match_brace
from texlate.latex.tables import (
    BOUNDARY_TAIL,
    DIMEN_TAIL_KIND,
    FILENAME_CHARS,
    TRANSPARENT_HEAD_SPEC,
    strip_fname_quotes,
)

from ._common import (
    _BSBS_OPT_RX,
    _COND_GROUP_ARGS,
    _DEAD_ARG_NAMES,
    _DEAD_TAIL_NAMES,
    _MATH_TEXTARG,
    _PROTECT_TYP,
    _SWALLOW_ARG_NAMES,
    _TAIL_CAP,
    TokenSource,
    _cite_ref_type,
    _pend_call_slots,
    _verb_delim_tok,
)
from .args_chunk import _ArgsChunk
from .args_prose import _PROSE_BLOCK_NAMES
from .grpscan import _IMPORT2

if TYPE_CHECKING:
    from texlate.latex.model import ScanState, Span
    from texlate.latex.mouth import Tok

    from ._common import _Vtex


class _ArgsHandlers(_ArgsChunk):
    # ------------------------------------------------------------ 宿主契约（ty 静态面）
    # god-class 机械拆分的静态代价：``Segmenter``（``__init__.py``）经 mixin
    # 链注入的状态/方法在本文件孤检时对 ty 不可见——``TYPE_CHECKING`` 声明
    # 即契约，签名与宿主 mixin（``core.py``/``mainloop.py``/``pending.py``）
    # 定义保持一致；宿主签名改动时同步此处。
    if TYPE_CHECKING:
        # ``_Core.__init__`` 注入的状态
        state: ScanState
        in_arg: bool
        vt: _Vtex
        file_texts: list[str]
        force_chunk: bool
        _stop: bool

        # ``_Core``/``_MainLoop``/``_Pending`` 提供的方法
        def _cover_to(self, fid: int, end: int) -> Span: ...
        def _cover_text(self, fid: int, end: int) -> tuple[Span, str]: ...
        def _cover_gap(self, fid: int, tok_start: int) -> None: ...
        def _cover_ph(
            self, fid: int, end: int, typ: PhType, gap: Tok | None = None
        ) -> Span: ...
        def _ph(
            self, typ: PhType, body: str, cut: tuple[int, int] | None = None
        ) -> str: ...
        def _rappend(self, surface: str, ident: str, vspan: Span) -> None: ...
        def _rappend_tok(self, t: Tok) -> None: ...
        def _rappend_ph(self, ph: str, vspan: Span) -> None: ...
        def _flush_run(self, end_pos: int) -> None: ...
        def _emit(self, vstart: int, vend: int) -> None: ...
        def _emit_ph(self, typ: PhType, vstart: int, vend: int, body: str) -> None: ...
        def _skip_past(self, src: TokenSource, fid: int, end: int) -> None: ...
        def _tail_scan_end(self, fid: int, pos: int, kind: str) -> int | None: ...
        def _math_skip_textarg(self, src: TokenSource, body: list[Tok]) -> None: ...
        def _absorb_slots(
            self, src: TokenSource, fid: int, slots: list[str]
        ) -> list[Tok]: ...
        def _keyarg_tail(
            self, m: object, src: TokenSource | None = None, depth: int = 0
        ) -> str | None: ...

    # ------------------------------------------------------------ 各行 handler

    def _handle_href(self, t: Tok, src: TokenSource) -> None:
        r"""``\href{url}{text}``：url→``[[HREF]]``，``{text}`` 留主流续扫。

        url 参按逐字读（``%`` 不作注释，v1 ``match_brace(verbatim=True)``
        同）——token 收集会被 ``%`` 吃掉闭括号直排 EOF。
        """
        fid, _a, _b = t.pos
        pulled: list[Tok] = []
        x = self._peek_nonspace(src, pulled)
        if x is not None and x.kind == "lbrace":
            e = match_brace(self.file_texts[fid], x.pos[1], verbatim=True)
            if e is not None:
                self._cover_gap(fid, t.pos[1])  # \href 前间隙 → 字面项
                vpre = self._cover_to(fid, x.pos[1])  # \href + 间隙进 run
                self._rappend(
                    self.vt.slice(vpre.start, vpre.end),
                    self.vt.slice(vpre.start, vpre.end),
                    vpre,
                )
                self._cover_ph(fid, e, PhType.HREF)
                self._skip_past(src, fid, e)
                return
            self._unread_pulled(src, pulled, x)  # 未配对——全量回放重扫（v1 回 j）
            self._rappend_tok(t)
            return
        self._unread_pulled(src, pulled, x)
        self._rappend_tok(t)

    def _handle_input_cs(  # noqa: C901, PLR0912, PLR0915 — 四形平铺（{file}/import 双参/裸名/\cs 动态名）
        self, t: Tok, src: TokenSource, name: str
    ) -> None:
        r"""``\input`` 族漏网（gullet 未解析成功）：literal + ``inputs[]``。

        in_arg → ``[[CMD]]`` 进 run（v1 row10）。``{file}``/``import`` 双参/
        裸文件名三形；in_arg 裸名形文件名并入 CMD 保护段（不在则留 arg
        文本被译、splice 出 ``\input 译文`` 炸 missing_file）。
        """
        fid, _a, b = t.pos
        if self.in_arg:
            # 裸文件名形（``\input foo.tex``）：连吃 FILENAME_CHARS token 并入
            # 保护段——否则文件名留 arg 文本被翻译，splice 出 ``\input 译文``
            # 炸 missing_file（zhfile 普查 ``\caption{…\input f.tex…}`` 实漏）。
            # ``{file}``/``\cs``/其他形照旧 ``_protect_cs`` 逐参。
            pulled: list[Tok] = []
            x = self._peek_nonspace(src, pulled)
            if x is not None and x.kind in ("letter", "other") and x.text == '"':
                # 引号裸名 ``\input"a b.tex"``：收至闭引号并入保护段（同
                # 非 in_arg 臂）。子扫源界即 arg 界——无闭引号时「缺席」
                # 只说明本 arg 内无配对，不吞尾（否则引号后散文全进
                # CMD），全量回放退 ``_protect_cs`` 只护 ``\input``。
                qtoks, qend = self._eat_quoted_toks(src, x)
                if qend is None:
                    self._unread_pulled(src, pulled, *qtoks)
                    self._protect_cs(t, src, PhType.CMD)
                    return
                self._cover_ph(fid, qend, PhType.CMD, gap=t)
                return
            if (
                x is not None
                and x.kind in ("letter", "other")
                and all(c in FILENAME_CHARS for c in x.text)
            ):
                _, end = self._eat_fname_toks(src, x)
                self._cover_ph(fid, end, PhType.CMD, gap=t)
                return
            if x is not None and x.kind == "lbrace":
                # ``\input{...}`` in_arg：组内含 cs → 动态文件名信号
                # （input_dyn 供 main 闭包判 fail-open）；组消费后回放，
                # 保护仍交 ``_protect_cs`` 逐参。
                hit = self._collect_group(src, x, brace=True)
                if hit is not None:
                    inner, closer = hit
                    if any(tk.kind == "cs" for tk in inner):
                        self.state.input_dyn += 1
                    self._unread_pulled(src, pulled, x, *inner, closer)
                else:
                    self._unread_pulled(src, pulled, x)
                self._protect_cs(t, src, PhType.CMD)
                return
            if x is not None and x.kind == "cs":
                # ``\input \cs`` 动态文件名——非字面路径，input_dyn 信号
                self.state.input_dyn += 1
            self._unread_pulled(src, pulled, x)
            self._protect_cs(t, src, PhType.CMD)
            return
        end = b
        fname = ""
        pulled: list[Tok] = []
        x = self._peek_nonspace(src, pulled)
        if x is not None and x.kind == "lbrace":
            hit = self._collect_group(src, x, brace=True)
            if hit is not None:
                _inner, closer = hit
                end = closer.pos[2]
                if name in _IMPORT2:
                    # dir 参含 cs → 动态目录前缀——file 参纵为字面闭包
                    # 亦不可证，记 input_dyn 作 fail-open 信号
                    if "\\" in self.file_texts[fid][x.pos[2] : closer.pos[1]]:
                        self.state.input_dyn += 1
                    # v1 此处 ws_skip（全空白）非 ws_skip_arg——跨 \n\n
                    p2: list[Tok] = []
                    y = self._read_skipws(src, p2)
                    if y is not None and y.kind == "lbrace":
                        hit2 = self._collect_group(src, y, brace=True)
                        if hit2 is not None:
                            _inner2, closer2 = hit2
                            fname = self.file_texts[fid][
                                y.pos[2] : closer2.pos[1]
                            ].strip()
                            end = closer2.pos[2]
                        else:
                            self._unread_pulled(src, p2)  # 组 token 已回吐
                    else:
                        self._unread_pulled(src, p2, y)
                else:
                    fname = self.file_texts[fid][x.pos[2] : closer.pos[1]].strip()
            else:
                self._unread_pulled(src, pulled)  # 组已回吐；ws 回放（v1 end=j 重扫）
        elif x is not None and x.kind in ("letter", "other") and x.text == '"':
            # 引号裸名 ``\input"a b.tex"``（web2c 带空格名）——连同双引号
            # 收至闭引号 token，缺席收到流尾；span 须整吞否则文件名漏成散文
            fname_toks, _ = self._eat_quoted_toks(src, x)
            fname = "".join(t2.text for t2 in fname_toks)
            end = fname_toks[-1].pos[2]
        elif (
            x is not None
            and x.kind in ("letter", "other")
            and all(c in FILENAME_CHARS for c in x.text)
        ):
            # 裸文件名形（\input path/to）：连吃 FILENAME_CHARS token
            fname_toks, end = self._eat_fname_toks(src, x)
            fname = "".join(t2.text for t2 in fname_toks)
        elif x is not None and x.kind == "cs":
            # ``\input \cs`` 动态文件名：cs 吞进 literal 随命令走——否则
            # ``\myfile`` 被主流当未知命令展开/逐字，体文本漏进 chunk
            # （R4）。``fname`` 留空——动态名非字面路径，不记 inputs[]；
            # input_dyn 记 main 闭包 fail-open 信号。
            self.state.input_dyn += 1
            end = x.pos[2]
        else:
            self._unread_pulled(src, pulled, x)
        vspan = self._cover_to(fid, end)
        self._flush_run(vspan.start)
        self._emit(vspan.start, vspan.end)
        if fname and "\\" in fname:
            # 含 cs 的动态文件名（\@journal\substyle@ext）非字面路径，
            # 非输入尝试——不记 inputs[]（gullet 侧同款过滤），记
            # input_dyn 作 main 闭包 fail-open 信号
            self.state.input_dyn += 1
        elif fname:
            # 引号壳统一剥除——``"a b.tex"`` 与 ``a b.tex`` 同档记
            self.state.inputs.append((vspan.start, strip_fname_quotes(fname)))

    def _handle_protect_block(self, t: Tok, src: TokenSource) -> None:
        r"""``\author[opt]{..}`` 整块保护 → ``[[AUTHOR]]``（v1 row12）。

        ``{arg}`` 未跟随时 abort：``end`` 恒停在 ``b``（只护 ``\author``
        本体，v1 :885 同规）——``[opt]`` 段回放主流重扫。若把 ``[opt]``
        盖进 ph 体而 token 又回放，同段字节既受保护又进 run surface →
        译文双份（S2）。``_PROSE_BLOCK_NAMES`` 白名单名先走
        ``_mine_prose_block`` 散文挖掘——命中即返，无命中全参回放走
        本路径零行为变化。
        """
        fid, _a, b = t.pos
        if t.text in _PROSE_BLOCK_NAMES and self._mine_prose_block(t, src, fid, b):
            return
        end = b
        pulled: list[Tok] = []
        opt_toks: list[Tok] = []  # 已吃 ``[opt]``——``{`` 未中时随 abort 回放
        x = self._peek_nonspace(src, pulled)
        if x is not None and x.kind == "other" and x.text == "[":
            hit = self._collect_group(src, x, brace=False)
            if hit is not None:
                inner, closer = hit
                opt_toks = [*pulled, x, *inner, closer]
                pulled.clear()
                x = self._peek_nonspace(src, pulled)
            else:
                self._unread_pulled(src, pulled)  # 组已回吐
                x = None
        if x is not None and x.kind == "lbrace":
            hit = self._collect_group(src, x, brace=True)
            if hit is not None:
                end = hit[1].pos[2]
                opt_toks = []
            else:
                self._unread_pulled(src, pulled)  # `{` 组已回吐；opt 段随下方回放
            pulled.clear()
            x = None
        src.unread([*opt_toks, *pulled, *([x] if x is not None else [])])
        if end > b:
            end = self._keyval_tail_end(src, end)
        self._cover_gap(fid, t.pos[1])
        vspan, body = self._cover_text(fid, end)
        if self.in_arg:
            self._rappend_ph(self._ph(PhType.AUTHOR, body), vspan)
            return
        self._flush_run(vspan.start)
        self._emit_ph(PhType.AUTHOR, vspan.start, vspan.end, body)

    def _handle_boundary(  # tail/spec/in_arg 三路分派平铺即边界语义
        self, t: Tok, src: TokenSource, name: str
    ) -> None:
        r"""边界命令：flush + LITERAL（含 ``BOUNDARY_TAIL``/dimen 尾参）。

        ``\item`` 置 ``force_chunk``（label ``[o]`` 不收——可译文本留 run）。
        in_arg → ``[[CMD]]`` 进 run（v1 row14）。``\vskip 3pt`` 这类裸操作
        数尾参走 ``_tail_scan_end`` 字节扫随命令进 LITERAL/``[[CMD]]``——
        否则 ``pt``/``em`` 裸进 surface 被翻译（illegal_unit）。
        """
        fid, _a, b = t.pos
        kind = DIMEN_TAIL_KIND.get(name)
        tail_end = self._tail_scan_end(fid, b, kind) if kind is not None else None
        spec = BOUNDARY_TAIL.get(name)
        if self.in_arg:
            if tail_end is not None:
                self._cover_ph(fid, tail_end, PhType.CMD, gap=t)
                self._skip_past(src, fid, tail_end)
            elif spec is not None:
                # 参内边界命令同样按 spec 收参（``\setlength\parskip{4pt}``
                # 的 ``{4pt}`` 在参内照样漏 chunk）——token 已被
                # ``_args_tok`` 消费，无需 ``_skip_past``
                hit = self._try_args(src, fid, spec, b)
                if hit is not None:
                    self._cover_ph(fid, hit[1], PhType.CMD, gap=t)
                else:
                    self._protect_cs(t, src, PhType.CMD)
            else:
                self._protect_cs(t, src, PhType.CMD)
            return
        end = b
        if tail_end is not None:
            end = tail_end
        elif spec is not None:
            hit = self._try_args(src, fid, spec, b)
            if hit is not None:
                end = hit[1]
        vspan = self._cover_to(fid, end)
        self._flush_run(vspan.start)
        self._emit(vspan.start, vspan.end)
        if tail_end is not None:
            self._skip_past(src, fid, tail_end)
        if name == "item":
            self.force_chunk = True  # item 文本恒可译

    def _handle_transparent_head(self, t: Tok, src: TokenSource, name: str) -> None:
        r"""``\textcolor{red}{text}``/``\colorbox``：头参 ``[model]{name}`` → ``[[CMD]]``。

        ``{text}`` 留主流续扫（色名非文本槽位——裸落 surface 译成
        ``Undefined color``，loop1 slots③ 主错因）。argspec 同名条目
        是 chunk-arg 但只挂 xcolor 包——族表先行不吃门控。
        """
        fid, _a, b = t.pos
        hit = self._try_args(
            src, fid, TRANSPARENT_HEAD_SPEC[name], b, allow_single_token=False
        )
        if hit is None:
            self._rappend_tok(t)
            return
        self._cover_ph(fid, hit[1], PhType.CMD, gap=t)

    def _handle_bsbs(self, t: Tok, src: TokenSource) -> None:
        r"""``\\`` 的可选 dimen 参：``\\[5pt]``/``\\*[2em]`` 整调用 → ``[[CMD]]``。

        ``\\`` 本体是单字符字面 cs；``[atom]`` 命中 dimen 形才收（``\\[x]``
        非 dimen 照常逐字）。字节扫 + ``_skip_past``——``[5pt]`` 的 token
        不再主流重放。
        """
        fid, _a, b = t.pos
        m = _BSBS_OPT_RX.match(self.file_texts[fid], b, b + _TAIL_CAP)
        if m is None or m.end() <= b:
            self._rappend_tok(t)
            return
        end = m.end()
        self._cover_ph(fid, end, PhType.CMD, gap=t)
        self._skip_past(src, fid, end)

    def _handle_box_tail(self, t: Tok, src: TokenSource, name: str) -> None:
        r"""``\hbox to\hsize{..}``/``\vbox spread2pt`` 盒规格尾参。

        ``to|spread``+dimen 命中 → ``\cs<spec>`` 整段 ``[[CMD]]``，
        其后 ``{body}`` 组照主流续扫（``\hbox`` 透明体语义不变——体文
        进 chunk）；``to`` 关键字裸落 surface 被译是 hep-th/9703214:933
        实证。未命中回各名原路：``\hbox`` 透明字面、``\vbox`` 族回未知
        命令探针（``{body}`` 照常整调保护）。
        """
        fid, _a, b = t.pos
        end = self._tail_scan_end(fid, b, "boxspec")
        if end is None:
            if name == "hbox":
                self._rappend_tok(t)
            else:
                self._handle_unknown_cs(t, src, name)
            return
        self._cover_ph(fid, end, PhType.CMD, gap=t)
        self._skip_past(src, fid, end)

    def _handle_accent(self, t: Tok, src: TokenSource) -> None:
        r"""``\'e``/``\c{c}`` accent 单参保护：整调用 → ``[[CMD]]`` 进 run。

        参形：``{x}`` 组或单 token（``\~n``/``\~\i``——undelimited 参前导
        空格由 TeX 规则跳过，参判定同款；cs 参只收单字符名，``\begin``
        类多字符名不算参）。参缺席（``eol_par``/跨 fid/无参 token 种）
        → 裸名回吐按旧规内联字面。参在位则基字随 cs 进占位——``c``/``n``
        落 chunk 被译成 ``\c{这是译文}`` 是 0806.3144 的 misschar 根因
        （accent+CJK 语义上恒无意义）。
        """
        fid, _a, _b = t.pos
        pulled: list[Tok] = []
        end = -1
        hit_eof = False
        x = self._peek_nonspace(src, pulled, fid=fid)
        if x is None or x.kind == "lbrace":
            if x is not None:
                hit = self._collect_group(src, x, brace=True, fid=fid)
                if hit is not None:
                    end = hit[1].pos[2]
                x = None  # 组 token 由 ``_collect_group`` 结账（成败皆已回放/消费）
            if end < 0:
                # peek/组扫的 None 三分支（eol_par/异 fid/真 EOF）以重探分流：
                # 回吐过的 token 原样读出 → 回放走普通 bail；真 EOF → hit_eof
                x2 = src.read()
                if x2 is None:
                    hit_eof = True
                else:
                    src.unread([x2])
        elif x.kind in ("letter", "other") or (x.kind == "cs" and len(x.text) == 1):
            end = x.pos[2]
        if end < 0:
            if hit_eof and src.eof_pops:
                # _on_math 同款 EOF 守护：unread 只建 file_id<0 合成源——
                # cs 本体落 run，余下字节整盖 LITERAL 保真
                self._rappend_tok(t)
                self._flush_run(len(self.vt))
                tail = self._cover_to(fid, len(self.file_texts[fid]))
                self._emit(tail.start, tail.end)
                return
            self._unread_pulled(src, pulled, x)
            self._rappend_tok(t)
            return
        self._cover_ph(fid, end, PhType.CMD, gap=t)

    def _handle_endinput(self, t: Tok, src: TokenSource) -> None:
        r"""``\endinput`` 漏网档：顶层 flush + 本文件余下逐字 + 截停。"""
        fid, _a, _b = t.pos
        if self.in_arg:
            self._protect_cs(t, src, PhType.CMD)
            return
        vspan = self._cover_to(fid, len(self.file_texts[fid]))
        self._flush_run(vspan.start)
        self._emit(vspan.start, vspan.end)
        self._stop = True

    def _on_math_delim(self, t: Tok, src: TokenSource, closer: str) -> None:
        r"""``\[``/``\(`` 定界数学：token 拉取闭符 → ``[[MATH]]`` 进 run。"""
        fid, _a, _b = t.pos
        e = self._find_math_close_tok(src, closer)
        if e is not None:
            self._cover_ph(fid, e, PhType.MATH, gap=t)
            return
        self._rappend_tok(t)

    def _find_math_close_tok(self, src: TokenSource, closer: str) -> int | None:
        r"""``\]``/``\)`` 闭符 token 拉取：``eol_par``/EOF → 回吐放弃。

        字节版 ``_find_math_close`` 的 token 等价：注释已由 Mouth 吞掉；
        ``eol_par`` = 段界逃逸信号（假闭合不吃进 MATH）。``\text`` 族
        正文参整段跳扫——体内 ``\)``/``\]`` 属组内文本，不关外层数学
        （``_on_math`` 同款 ``_math_skip_textarg`` 口径）。
        """
        pulled: list[Tok] = []
        while True:
            x = src.read()
            if x is None or x.kind == "eol_par":
                self._unread_pulled(src, pulled, x)
                return None
            pulled.append(x)
            if x.kind == "cs" and x.text == closer:
                return x.pos[2]
            if x.kind == "cs" and x.text in _MATH_TEXTARG:
                self._math_skip_textarg(src, pulled)

    def _handle_cond(
        self, t: Tok, src: TokenSource, name: str, m: object | None
    ) -> None:
        r"""``\if`` 两档界标（v1 ``_handle_cond`` token 版，§8.6）。

        可求值 ``\if`` 已被 gullet ``process_if`` 消费成 ``if:``/``fi:``
        marker 夹心，不到此。到此者：

        - ``if*`` MacroDef（``\ifAnonymous{T}{F}`` 双参调用形）→ 整调用
          ``[[COND]]``（in_arg）/``[[CMD]]`` 保护（v1 ``_protect_call``——
          透明分流会把命令名放进 run surface → conditional 泄漏）；
        - 不可求值 ``\ifX``（``\ifx`` 宏比较/未知 if*/溢界 IfCond）→
          条件段已被 gullet 按语法吃掉（字节成 gap），界标 LITERAL 盖
          ``\ifX`` + 条件区（``read()`` 窥下一 raw token 取起点后回吐）；
          **双支自流**——``\else``/``\fi`` 各自再到此出 LITERAL 界标，
          与 v1 收集+回放的逐 piece 序列等价（嵌套免计深、verb 体假
          ``\fi`` 由 verb 处理器 ``skip_past`` 天然挡）；
        - 裸 ``\else/\or/\fi`` 散件 / ``\Xtrue``/``\Xfalse``（IfSetter，
          旗标 gullet 已写）→ flush + LITERAL 盖本体；
        - in_arg 一律 ``[[COND]]`` 进 run（``if*`` 同窥位盖条件区）。
        """
        if isinstance(m, MacroDef):
            self._protect_cs(t, src, PhType.COND if self.in_arg else PhType.CMD)
            return
        fid, _a, b = t.pos
        end = b
        if name.startswith("if"):
            nxt = src.read()
            if nxt is not None:
                src.unread([nxt])
                # 条件区 = [b, nxt.start)：gen>0/跨 fid 窥物不算（非本段字节）
                if nxt.gen == 0 and nxt.pos[0] == fid:
                    end = nxt.pos[1]
        for _ in range(_COND_GROUP_ARGS.get(name, 0)):
            # 名/表达式槽 ``{..}`` 并入界标覆盖（``\iftoggle{proofs}`` 名槽
            # 裸落 surface 会被译——1306.0026/1511.02547）；``{T}{F}`` 支
            # 不在吸收数内，留主流照常进 chunk。跨 fid/gen>0 组不收——字节
            # 异源判不了界，全量回放是保守等价物。
            pulled: list[Tok] = []
            x = self._peek_nonspace(src, pulled, fid=fid)
            if x is None or x.kind != "lbrace" or x.gen != 0:
                self._unread_pulled(src, pulled, x)
                break
            hit = self._collect_group(src, x, brace=True)
            if hit is None:
                self._unread_pulled(src, pulled)  # 组 token 已回吐；ws 回放
                break
            inner, closer = hit
            if closer.gen != 0 or closer.pos[0] != fid:
                self._unread_pulled(src, pulled, x, *inner, closer)
                break
            end = closer.pos[2]
        if self.in_arg:
            self._cover_ph(fid, end, PhType.COND, gap=t)
            return
        self._flush_run(len(self.vt))
        vspan = self._cover_to(fid, end)
        self._emit(vspan.start, vspan.end)

    def _handle_opaque_macro(self, t: Tok, src: TokenSource, m: object) -> None:
        r"""Opaque 宏（gullet 判定体无文本不展开）：按 spec 读参 → ``[[MACRO]]``。

        gullet ``Arg`` → ``ArgSpec`` 映射：``m``→m、``o``→o、``star``→s、
        ``e``→e（delim toks → 字符表）、``delim``→u（``delim_toks`` 原样携带
        目标序列——滑窗命中止、delim 消费）、``until_group``→g（读到
        ``lbrace`` 回吐不消费）；``brace_after`` 不传递——gullet 侧也只是
        读一枚随即回吐，净效应零。其余（literal_match/eq 等）→ 零宽占位。

        散文参挖掘（cat9 @-cs 面 + 全 opaque 散文面共享本点）：``{..}`` 组参
        命中散文判据时抠出 ``[[MACRO]]`` 覆盖、子扫渲进 run surface——
        「参留主流即同可见」，整调用不再把散文整块蒸发；宏名/非散文参/
        散文参花括号所在的结构段仍 opaque 原文（编译语义不破）。``m``/``o``
        交错与 ``\author{n}{prose}`` 类双参按逐参独立判定。
        """
        fid, _a, b = t.pos
        gspec = [
            ArgSpec("m")
            if a.kind == "m"
            else ArgSpec("o")
            if a.kind == "o"
            else ArgSpec("s")
            if a.kind == "star"
            else ArgSpec("e", delim="".join(x.text for x in a.delim))
            if a.kind == "e"
            else ArgSpec("u", delim_toks=tuple(a.delim))
            if a.kind == "delim" and a.delim
            else ArgSpec("g")
            if a.kind == "until_group"
            else ArgSpec("b")
            for a in getattr(m, "spec", [])
        ]
        args, end = self._args_tok(src, fid, gspec, b, allow_single_token=True)
        # 体尾 key-arg cs（``\def\r{\ref}`` 走 opaque 档不展开时）：spec 参
        # 读尽后调用点 ``{key}`` 仍是待绑尾参——吸进 [[MACRO]] 覆盖，
        # 否则裸落 chunk 被译（key-arg 泄漏 S1-opaque 面）。
        ka = self._keyarg_tail(m, src)
        if ka is not None:
            got = self._absorb_slots(src, fid, _pend_call_slots(ka))
            if got:
                end = max(end, got[-1].pos[2])
            if not any(x.kind == "lbrace" for x in got):
                self.state.warnings.append(
                    ScanWarning("keyarg_unbound", len(self.vt), f"\\{ka} 尾参缺席")
                )
        prose_args = self._prose_args_gated(t.text, t, fid, args, "opaque")
        self._cover_gap(fid, t.pos[1])
        # ``{`` 随前段结构进 [[MACRO]]，参内容子扫渲进 run surface——
        # 嵌套 cs/注释由 ``_subscan_render`` 照常保护。
        self._emit_prose_args(fid, prose_args, PhType.MACRO)
        end = self._keyval_tail_end(src, end)  # 尾随 ``[kv]`` 选参并入 [[MACRO]] 覆盖
        self._cover_ph(fid, end, PhType.MACRO)

    def _handle_unknown_cs(
        self, t: Tok, src: TokenSource, name: str = "", m: object | None = None
    ) -> None:
        r"""未知命令（v1 row19）：argspec 表兜底 + ``{``/``[`` 探针。

        宏表未命中（``m is None``）先查 ``argspec_lookup``——已加载包
        的签名驱动 policy 分派；表外维持探针：参数命中 → ``[[CMD]]``
        进 run（``{散文}`` 参抠出子扫渲 surface——``_opaque_arg_prose``
        判据同 opaque 宏臂），否则逐字。``allow_single_token=False``
        （泄漏机制 A：禁单 token 参——``\foo x`` 的 ``x`` 是正文）；
        参数搜索不跨 ``eol_par``。
        """
        fid, _a, b = t.pos
        # 裸操作数/赋值尾参先扫——literal-policy 名（``\hangindent``/``\kern``/
        # ``\vrule``/``\font``）在 argspec 分派早退逐字、探针不认 ``=``/裸
        # 操作数形，不盖则单位字母进 surface（illegal_unit）。表外名走通用
        # ``=ATOM`` 赋值扫（``\foo=2pt`` 的 ``=2pt`` 不可能是散文）。
        kind = DIMEN_TAIL_KIND.get(name or t.text)
        tail_end = self._tail_scan_end(fid, b, kind if kind is not None else "assign")
        if tail_end is not None:
            self._cover_ph(fid, tail_end, PhType.CMD, gap=t)
            self._skip_past(src, fid, tail_end)
            return
        if m is not None:
            # S3 字面别名闸：宏表命中但 cs 到分派仍未展开（xprotect/
            # gen-cap/bail——``\r`` 不能按字面进 chunk）。体尾解析到
            # key-arg 族名 → 按该族 protect 调用：参可绑整调用
            # ``[[REF]]``/``[[LABEL]]`` 等；参缺席（EOF/par/异 fid/
            # gen>0 紧邻）→ cs-only 保护 + ``keyarg_unbound`` 告警，
            # 不让 ``\r`` 字面进 surface。
            ka = self._keyarg_tail(m, src)
            if ka is not None:
                pulled: list[Tok] = []
                x = self._peek_nonspace(src, pulled, fid=fid)
                bound = (
                    x is not None
                    and x.gen == 0
                    and (
                        x.kind == "lbrace"
                        or (x.kind == "other" and x.text in "[*")
                        or (ka in ("url", "path") and _verb_delim_tok(x))
                    )
                )
                self._unread_pulled(src, pulled, x)
                typ = _cite_ref_type(ka) or _PROTECT_TYP.get(ka, PhType.CMD)
                if bound:
                    self._protect_cs(
                        t,
                        src,
                        typ,
                        mand=2 if ka == "inputminted" else 1,
                        verbatim=ka in ("url", "path"),
                    )
                    return
                self.state.warnings.append(
                    ScanWarning(
                        "keyarg_unbound",
                        len(self.vt),
                        f"\\{name or t.text}→\\{ka} 参缺席",
                    )
                )
                self._cover_ph(fid, b, typ, gap=t)
                return
        if m is None:
            e = _tables.argspec_lookup(
                name or t.text, cast("set[str]", self.state.pkgs)
            )
            if e is not None:
                self._handle_argspec_cs(t, src, e)
                return
        hit = self._try_args(src, fid, 6, b, has_opt=True, allow_single_token=False)
        if hit is None:
            self._rappend_tok(t)
            return
        args, end = hit
        # 块级体参（参内含空行/`\begin`/`\end`/`\item`/节题 cs）不是参数是
        # 排版体——standalone 段文件扫不到 main.tex 的 ``\newcommand`` 注册，
        # ``\arxiv{整段}`` 族整参糊 [[CMD]] 会连块结构带散文全吞（t_f748
        # 实证 EOF 吞 1.6K）。cs 名保 [[CMD]]、参 token 回放主流重分派，
        # 组内按块自然分段（等效 flatten 展开）。吞块/死文本/死尾参名闸
        # 不旁路——``\comment``/``\deleted``/``\replaced`` 语义仍罩。
        nm = name or t.text
        if (
            nm not in _SWALLOW_ARG_NAMES
            and nm not in _DEAD_ARG_NAMES
            and nm not in _DEAD_TAIL_NAMES
            and any(self._arg_body_shaped(a) for a in args)
        ):
            self.state.warnings.append(
                ScanWarning("body_arg_replay", len(self.vt), f"\\{nm}")
            )
            self._cover_ph(fid, b, PhType.CMD, gap=t)
            self._unread_args(src, args)
            return
        # 与 ``_handle_opaque_macro`` 同款散文参挖掘：投机参里的 ``{散文}``
        # 抠出 [[CMD]] 覆盖子扫渲进 run surface——``\@maketitle{…prose…}``
        # 类调用块不再整块蒸发（1803.00127 实测）。宏名/非散文参/散文参
        # 花括号所在结构段仍 [[CMD]] 原文。
        prose_args = self._prose_args_gated(name or t.text, t, fid, args, "probe")
        self._cover_gap(fid, t.pos[1])
        end = self._keyval_tail_end(src, end)  # 尾随 ``[kv]`` 选参并入覆盖
        self._emit_prose_args(fid, prose_args, PhType.CMD)
        self._cover_ph(fid, end, PhType.CMD)
