r"""``latex/segmenter.args.chunk`` — chunk-arg 族 + argspec 表分派（``args`` god-file 机械拆分叶）。

``_chunk_target_args``（``\section`` 族公共头：``*`` + spec 读参 +
可译位挑取）→ ``_handle_chunk_arg``/``_preamble_chunk_arg`` 双档
（顶层 run/preamble 档 bail 各异）；``_handle_argspec_cs`` policy
分派（literal/transparent/boundary/protect/key/verbatim/chunk-arg）
→ ``_emit_argspec_chunks`` 参序 literal/chunk 交替发射；
``_split_rendered`` 渲染串二次切分（``_pick_cut`` 切点链）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from texlate.latex.model import PhType, Piece, PieceKind, ScanWarning, Span
from texlate.latex.segmenter._common import _chunk_spec_cached, _pick_cut
from texlate.latex.segmenter.args.prose import _ArgsProse
from texlate.latex.segmenter.args.protect import _ArgsProtect
from texlate.latex.tables import CHUNK_ARG_SPEC, CHUNK_MAX, MAX_GEN

if TYPE_CHECKING:
    from texlate.latex.model import ArgspecEntry, ScanState
    from texlate.latex.mouth import Tok
    from texlate.latex.segmenter._common import TokenSource, _ArgTok, _Vtex


class _ArgsChunk(_ArgsProse, _ArgsProtect):
    # ------------------------------------------------------------ 宿主契约（ty 静态面）
    # god-class 机械拆分的静态代价：``Segmenter``（``__init__.py``）经 mixin
    # 链注入的状态/方法在本文件孤检时对 ty 不可见——``TYPE_CHECKING`` 声明
    # 即契约，签名与宿主 mixin（``core.py``/``mainloop.py``/``pending.py``）
    # 定义保持一致；宿主签名改动时同步此处。
    if TYPE_CHECKING:
        # ``_Core.__init__`` 注入的状态
        state: ScanState
        in_arg: bool
        gen: int
        vt: _Vtex
        file_texts: list[str]
        pieces: list[Piece]
        env_stack: list[str]

        # ``_Core``/``_MainLoop``/``_Pending`` 提供的方法
        def _cover_to(self, fid: int, end: int) -> Span: ...
        def _cover_gap(self, fid: int, tok_start: int) -> None: ...
        def _cover_ph(
            self, fid: int, end: int, typ: PhType, gap: Tok | None = None
        ) -> Span: ...
        def _rappend(self, surface: str, ident: str, vspan: Span) -> None: ...
        def _rappend_tok(self, t: Tok) -> None: ...
        def _flush_run(self, end_pos: int) -> None: ...
        def _emit(self, vstart: int, vend: int) -> None: ...
        def _new_chunk(
            self, content: str, context: str, gspan: Span, ident: str
        ) -> str: ...
        def _skip_past(self, src: TokenSource, fid: int, end: int) -> None: ...
        def _tikz_tail_end(self, fid: int, pos: int) -> int | None: ...

    # ------------------------------------------------------------ chunk-arg 族

    def _chunk_target_args(
        self, t: Tok, src: TokenSource, name: str
    ) -> tuple[int, list[_ArgTok], _ArgTok | None]:
        r"""``\section`` 族 chunk-arg 公共头：``*`` 修饰 + spec 读参 + 可译位挑取。

        返回 ``(b, args, target)``——``b`` = ``*`` 后参数扫描起点；
        ``target`` = spec 位序 ``tidx`` 实参（位空/未消费 → ``None``，
        调用方按各自 bail 处理）。``_handle_chunk_arg``/
        ``_preamble_chunk_arg`` 共用（bail/发射尾各异，留在调用方）。
        """
        fid, _a, b = t.pos
        # v1：``pos = ws_skip_arg(j)`` 后先吃 ``*``（``\section*{T}``），
        # 未中回吐走 ``_args_tok`` 的 peek 重拉
        pulled: list[Tok] = []
        x = self._peek_nonspace(src, pulled)
        if x is not None and x.kind == "other" and x.text == "*":
            b = x.pos[2]
        else:
            self._unread_pulled(src, pulled, x)
        spec_str, tidx = CHUNK_ARG_SPEC.get(name, ("om", 1))
        spec = _chunk_spec_cached(spec_str)
        args, _end = self._args_tok(src, fid, spec, b, allow_single_token=True)
        # 可译参数 = spec 位序 tidx 实参；位空即 bail——不退 ``real[-1]``：
        # ``\captionof{figure}`` 的末实参是类型名（slot0）不是可译槽，
        # ``\section[opt]`` 缺 ``{arg}`` 时末实参是可选参——两者翻译成
        # ``\captionof{译文}``/``\section{译文}`` 都是错体（S4）
        target: _ArgTok | None = None
        if tidx < len(args) and args[tidx].fe > args[tidx].fs:
            target = args[tidx]
        return b, args, target

    def _handle_chunk_arg(self, t: Tok, src: TokenSource, name: str) -> None:
        r"""``\section[opt]{arg}`` token 版：前缀 LITERAL，arg → 独立 chunk。

        v1 ``_handle_chunk_arg`` 逐行移植：arg token 经 ``_args_tok`` 拉出
        （消费位入覆盖账），内容 token 喂 ``_ListSource`` 子扫——渲染串含
        ``[[X_n]]`` 自解析（ident=part 直传 ``_new_chunk``）。
        """
        fid, _a, _b = t.pos
        _b, args, target = self._chunk_target_args(t, src, name)
        if target is not None and self.gen >= MAX_GEN:
            self.state.warnings.append(
                ScanWarning("gen_overflow", len(self.vt), f"chunk:{name}")
            )
        if (
            target is None
            or (target.cs, target.ce) == (target.fs, target.fe)
            or self.gen >= MAX_GEN
        ):
            # 无 {..} 参数 / 单 token 参数 / 超代数 → 命令名逐字；
            # 已拉参数 token 回放主流（字节版返回 j 的等价物）
            self._unread_args(src, args)
            self._rappend_tok(t)
            return
        self._cover_gap(fid, t.pos[1])  # 命令前间隙 → 字面项（不进下述覆盖段）
        if not self.file_texts[fid][target.cs : target.ce].strip():
            # 空参数 → 整调用（含括号）逐字进 run
            vspan = self._cover_to(fid, target.fe)
            self._rappend(
                self.vt.slice(vspan.start, vspan.end),
                self.vt.slice(vspan.start, vspan.end),
                vspan,
            )
            return
        # 前缀覆盖到 content 起（\section[opt]{ 一段）；内文子扫共享覆盖账
        vpre = self._cover_to(fid, target.cs)
        rendered = self._subscan_render(target)
        vce = len(self.vt)
        vclose = self._cover_to(fid, target.fe)
        if self.in_arg:
            # 嵌套 chunk-arg 内联化：前缀 + 渲染 + 闭括号并入父 run
            text = (
                self.vt.slice(vpre.start, vpre.end)
                + rendered
                + self.vt.slice(vclose.start, vclose.end)
            )
            self._rappend(
                text,
                text,
                Span(vpre.start, vclose.end),
            )
            return
        self._flush_run(vpre.start)
        self._emit(vpre.start, vpre.end)  # \section{ 前缀
        gspan = Span(vpre.end, vce)
        refs = "".join(
            self._new_chunk(part, name, gspan, part)
            for part in self._split_rendered(rendered)
        )
        self.pieces.append(
            Piece(
                PieceKind.CHUNK_REF,
                gspan,
                refs,
                self.env_stack[-1] if self.env_stack else None,
            )
        )
        self._emit(vclose.start, vclose.end)  # } 闭括号

    def _preamble_chunk_arg(self, t: Tok, src: TokenSource, name: str) -> bool:
        r"""``_handle_chunk_arg`` 的 preamble 档版：bail 一律 ``_cover_to``。

        run 在 preamble 档永不中途冲刷——``_handle_chunk_arg`` 的 ``_rappend``
        bail 会把 ``\title`` 挂进 run，EOF flush 时在已盖字面区里再发 piece
        → 平铺破。此路径参数缺失/空参数全部回放+整调用字面盖过。
        """
        fid, _a, _b = t.pos
        b, args, target = self._chunk_target_args(t, src, name)
        if (
            target is None
            or (target.cs, target.ce) == (target.fs, target.fe)
            or self.gen >= MAX_GEN
            or not self.file_texts[fid][target.cs : target.ce].strip()
        ):
            self._unread_args(src, args)
            self._cover_to(fid, b)
            return True
        # 覆盖 gap+ 命令头一步 cover：`_cover_gap` 的 run 项在 preamble 档
        # 永不中途冲刷（EOF flush 会在已盖字面区乱序发 piece）——preamble
        # 内 emit 一律随覆盖即时发 literal 保持平铺。
        vpre = self._cover_to(fid, target.cs)
        self._emit(
            self.pieces[-1].span.end if self.pieces else 0, vpre.end
        )  # 前缀+``\title{`` literal
        rendered = self._subscan_render(target)
        vce = len(self.vt)
        vclose = self._cover_to(fid, target.fe)
        gspan = Span(vpre.end, vce)
        refs = "".join(
            self._new_chunk(part, name, gspan, part)
            for part in self._split_rendered(rendered)
        )
        self.pieces.append(Piece(PieceKind.CHUNK_REF, gspan, refs, None))
        self._emit(vce, vclose.end)  # } 闭括号
        return True

    @staticmethod
    def _split_rendered(core: str) -> list[str]:
        """渲染串二次切分——旧 ``_split_core`` 原样（``[[X_n]]`` 边界优先）。

        切点优先级链本体在 ``_pick_cut``（与 ``_split_bounds`` 共用）。
        """
        if len(core) <= CHUNK_MAX:
            return [core]
        parts: list[str] = []
        i, n = 0, len(core)
        while i < n:
            hard = min(i + CHUNK_MAX, n)
            if hard >= n:
                parts.append(core[i:])
                break
            cut = _pick_cut(core, i, hard)
            parts.append(core[i : i + cut])
            i += cut
        return parts

    # ------------------------------------------------------------ argspec 表分派

    def _handle_argspec_cs(  # noqa: C901, PLR0911 — policy 分派早退平铺，顺序即语义
        self, t: Tok, src: TokenSource, e: ArgspecEntry
    ) -> None:
        r"""Argspec 表命中分派：policy → literal/boundary/protect/chunk-arg。

        签名即权威（与探针不同：参数读 ``e.signature`` 位序，角色表
        ``e.arg_roles`` 对齐）。``literal``/``transparent`` 名进 run
        参数随主流；``boundary`` flush+LITERAL；``protect``/``key``/
        ``verbatim``（+in_arg 的 boundary）整调用 ``[[CMD]]``；
        ``chunk-arg`` 走 :meth:`_emit_argspec_chunks`。

        ``transparent``/``boundary`` 当前全条目被同名族表先截获——此路
        不可达；到达即表/族漂移，记 ``argspec_shadowed`` 告警但语义照旧。
        """
        fid, _a, b = t.pos
        if e.policy == "verbatim":
            # verbatim policy：逐字读参（ctan-argspec 定界式约定）——``%``/``#``
            # 等在参数里是字面（``\hyperbaseurl{..%20..}``），走 ``\url``/``\path``
            # 同款字节级配对；token 流会被 ``%`` 吃掉闭括号直排 EOF。
            spec = _chunk_spec_cached(e.signature)
            mand = sum(s.kind in ("m", "v", "n") for s in spec)
            self._protect_cs(t, src, PhType.CMD, mand=mand, verbatim=True)
            return
        if e.policy == "literal":
            self._rappend_tok(t)
            return
        if e.policy in ("transparent", "boundary"):
            self.state.warnings.append(
                ScanWarning("argspec_shadowed", len(self.vt), e.name)
            )
            if e.policy == "transparent":
                self._rappend_tok(t)
                return
        spec = _chunk_spec_cached(e.signature)
        if e.name == "tikz" and e.policy in ("protect", "key"):
            # 裸 ``\tikz <path>;``：签名 ``o o m`` 够不着无 ``[``/``{``
            # 起头的路径形（``[opts]`` 前导形同漏——先扫再让 argspec 走
            # 参）——``;`` 定界整句进 [[CMD]]（R8）；非路径形 → None 回落。
            tail_end = self._tikz_tail_end(fid, b)
            if tail_end is not None:
                self._cover_ph(fid, tail_end, PhType.CMD, gap=t)
                self._skip_past(src, fid, tail_end)
                return
        hit = self._try_args(src, fid, spec, b, allow_single_token=True)
        args, end = hit or ([], b)
        if e.policy == "chunk-arg":
            self._emit_argspec_chunks(t, src, e, args, end, b)
            return
        if not any(a.fe > a.fs for a in args):
            if e.policy == "boundary" and not self.in_arg:
                vspan = self._cover_to(fid, self._keyval_tail_end(src, b))
                self._flush_run(vspan.start)
                self._emit(vspan.start, vspan.end)
                return
            if e.policy in ("protect", "key"):
                # 签名零参/参数缺席但本体仍要保护（\printindex 类）——
                # 裸名进 run 会被译文面当真词处理；尾随 ``[kv]`` 选参同收
                # （``\printbibliography[title={..},segment=1]`` 2403.09125）
                self._cover_ph(fid, self._keyval_tail_end(src, b), PhType.CMD, gap=t)
                return
            self._rappend_tok(t)
            return
        self._cover_gap(fid, t.pos[1])
        end = self._keyval_tail_end(src, end)
        if e.policy == "boundary" and not self.in_arg:
            vspan = self._cover_to(fid, end)
            self._flush_run(vspan.start)
            self._emit(vspan.start, vspan.end)
            return
        # 与 ``_handle_unknown_cs`` 探针臂同款散文参挖掘：protect/key
        # （+in_arg boundary）签名参消费后整调用 ``[[CMD]]`` 塌缩同型蒸发
        # ——``\marginpar{prose}``/``\only<1>{prose}``/``\frame{prose}`` 面。
        # 逐参 ``_opaque_arg_prose`` 调用点判定（key/良性参天然不命中，
        # keyval 组由判据内形状门挡住），花括号所在结构段仍 ``[[CMD]]`` 原文。
        prose_args = self._prose_args_gated(e.name, t, fid, args, "argspec")
        self._emit_prose_args(fid, prose_args, PhType.CMD)
        self._cover_ph(fid, end, PhType.CMD)

    def _emit_argspec_chunks(  # noqa: C901, PLR0912, PLR0913, PLR0915, PLR0917 — 参序 literal/chunk 交替平铺即 _handle_chunk_arg 多参推广
        self,
        t: Tok,
        src: TokenSource,
        e: ArgspecEntry,
        args: list[_ArgTok],
        end: int,
        b: int,
    ) -> None:
        r"""chunk-arg policy：``text``/``opt-text`` 角色参 → 独立 chunk。

        ``_handle_chunk_arg`` 的推广：consumed 参按位序「字面段（含
        括号与非文本参）→ 子扫渲染 → CHUNK_REF」交替发射；单 token
        文本参起截停回吐主流（泄漏机制 A 同判）。无文本参但有消费
        → 整调用 ``[[CMD]]``；零消费 → 名进 run。
        """
        fid = t.pos[0]
        consumed = [a for a in args if a.fe > a.fs]
        cut = len(args)
        for k, a in enumerate(args):
            if a.fe <= a.fs:
                continue
            role = e.arg_roles[k] if k < len(e.arg_roles) else "skip"
            if role in ("text", "opt-text") and (a.cs, a.ce) == (a.fs, a.fe):
                cut = k
                break
        if cut < len(args):
            self._unread_args(src, args[cut:])
            consumed = [a for a in args[:cut] if a.fe > a.fs]
            end = consumed[-1].fe if consumed else b
        if not consumed:
            self._rappend_tok(t)
            return
        end = self._keyval_tail_end(src, end)  # 尾随 ``[kv]`` 选参并入末段字面
        text_k = {
            k
            for k, a in enumerate(args[:cut])
            if a.fe > a.fs
            and (e.arg_roles[k] if k < len(e.arg_roles) else "skip")
            in ("text", "opt-text")
        }
        if text_k and self.gen >= MAX_GEN:
            self.state.warnings.append(
                ScanWarning("gen_overflow", len(self.vt), f"chunk:{e.name}")
            )
            text_k = set()
        if not text_k:
            self._cover_ph(fid, end, PhType.CMD, gap=t)
            return
        # 参序 op 列：("lit", end) 覆盖到 end；("arg", _ArgTok) 子扫文本参。
        # 非文本参/括号字节随相邻 lit 段覆盖——首 op 恒为 lit（text_k 非空）。
        ops: list[tuple[str, int | _ArgTok]] = []
        for k, a in enumerate(args[:cut]):
            if a.fe <= a.fs:
                continue
            if k in text_k and self.file_texts[fid][a.cs : a.ce].strip():
                ops.append(("lit", a.cs))
                ops.append(("arg", a))
            # else：参数字节并入下一段 lit 覆盖
        ops.append(("lit", end))
        if self.in_arg:
            self._cover_gap(fid, t.pos[1])  # 命令前间隙 → 字面项（不入 texts）
            vmark = len(self.vt)  # 已覆盖到 vtex 位——下一 op 的 vstart
            for op, x in ops:
                if op == "lit":
                    # 非文本参/括号字面段不进 run surface——``[[CMD]]`` 代位
                    # （2310.16788 ``[origin=c]``→``[这是译文]`` 机理：凡
                    # argspec chunk-arg 名 in_arg 皆漏）
                    vmark = self._cover_ph(fid, cast("int", x), PhType.CMD).end
                    continue
                vmark = self._rappend_subscan(cast("_ArgTok", x), vmark)
            return
        self._cover_gap(fid, t.pos[1])  # 同上——字面 piece 不含前隙
        v0 = self._cover_to(fid, cast("int", ops[0][1]))
        self._flush_run(v0.start)
        self._emit(v0.start, v0.end)
        cur_v = v0.end
        for op, x in ops[1:]:
            if op == "lit":
                v = self._cover_to(fid, cast("int", x))
                self._emit(v.start, v.end)
                cur_v = v.end
                continue
            rendered = self._subscan_render(cast("_ArgTok", x))
            gspan = Span(cur_v, len(self.vt))
            refs = "".join(
                self._new_chunk(part, e.name, gspan, part)
                for part in self._split_rendered(rendered)
            )
            self.pieces.append(
                Piece(
                    PieceKind.CHUNK_REF,
                    gspan,
                    refs,
                    self.env_stack[-1] if self.env_stack else None,
                )
            )
            cur_v = gspan.end
