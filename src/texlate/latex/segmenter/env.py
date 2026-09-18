r"""``latex/segmenter`` 子模块——god-class 机械拆分（行为零变）。"""

from __future__ import annotations

import re
from bisect import (
    bisect_left,
)
from typing import TYPE_CHECKING

from texlate.latex.gullet import (
    ArgMismatch,
    Gullet,
    MacroDef,
)
from texlate.latex.model import (
    PhType,
    ScanWarning,
    Span,
    env_opt_is_format,
)
from texlate.latex.tables import (
    ARG_TRANSPARENT_ENVS,
    ENV_MANDATORY_ARG,
    INPUT_CMDS,
    MAX_GEN,
    PAIR_BLOCK_CMDS,
    VERBATIM_ENVS,
    looks_like_colspec,
)
from texlate.textutil import (
    DEAD_ENVS,
    dead_end_anchored,
    dead_env_end,
)

from ._common import (
    TokenSource,
    _chunk_spec_cached,
    _env_ph_type,
    _EnvDeadTok,
    _ListSource,
)

if TYPE_CHECKING:
    from texlate.latex.model import ArgspecEntry
    from texlate.latex.mouth import (
        Tok,
    )

r"""``Segmenter`` 环境机制（begin/end 分类、参数尾、端点查找）。"""


class _Env:
    # ------------------------------------------------------------ env

    def _env_name(self, src: TokenSource) -> tuple[str | None, Tok | None, list[Tok]]:
        r"""``{env}`` 组收集：返回 (env 名, rbrace token, 全消费 token 列)。

        前扫跨 space 与 ``eol_par``——``\end`` 换段 ``{name}`` 形（断行
        env tag）不把 ``{name}`` 裸落主流（R6）；名内 ``eol_par``
        即失败（par 不可能是 env 名的合法成分——docstring 旧稿只写了
        半句，名内判据补上）。名内花括号按 ``match_brace`` 深度配对。
        失败返回 ``(None, None, consumed)``——调用方负责
        ``unread(consumed)``（v1 返回 ``i`` 原位重扫的等价物）。

        不变式：``env is None`` ⟺ ``close_t is None``——调用方只判
        ``env`` 即可。组内对价：``_grp_envtag``（展开组 surface 侧）。
        """
        consumed: list[Tok] = []
        open_t = src.read()
        while open_t is not None and open_t.kind in ("space", "eol_par"):
            consumed.append(open_t)
            open_t = src.read()
        if open_t is not None:
            consumed.append(open_t)
        if open_t is None or open_t.kind != "lbrace":
            return None, None, consumed
        name_toks: list[Tok] = []
        depth = 1
        while True:
            x = src.read()
            if x is None:
                return None, None, consumed
            consumed.append(x)
            if x.kind == "eol_par":
                return None, None, consumed
            if x.kind == "lbrace":
                depth += 1
            elif x.kind == "rbrace":
                depth -= 1
                if depth == 0:
                    name = "".join(t2.text for t2 in name_toks).strip()
                    return name, x, consumed
            name_toks.append(x)

    def _handle_env_begin(  # noqa: C901, PLR0911, PLR0912, PLR0915 — §3.5 环境四分类各一段，平铺即规则表
        self, t: Tok, src: TokenSource, m: MacroDef | None = None
    ) -> None:
        r"""``\begin{env}`` token 版：verbatim/math/protected/transparent。

        ``m`` 非空 = env_begin 宏端点（``\beq`` 形）：env 取
        ``m.target_env``、tag 区间 = cs 本体（无 ``{env}`` 组可读）。
        """
        fid, _a, _b = t.pos
        if m is None:
            env, close_t, consumed = self._env_name(src)
            if env is None:
                src.unread(consumed)
                self._rappend_tok(t)
                return
        else:
            env, close_t = m.target_env, t
        if env == "document":
            self._doc_opened = True  # 防中段 \documentclass 重入 preamble 档
        reg = self.state.macros.lookup_env(env)
        # 环境表未命中且族表全不知 → argspec env 条目：body_role 决定体路由
        # （verbatim/math/protect 走同名路径；text 落下方透明尾）。族表已
        # 知的 env（含 ARG_TRANSPARENT/ENV_MANDATORY_ARG）不交给 argspec——
        # 既有语义钉死（如 thebibliography 透明体 @X1 trap），数据侧
        # body_role 不覆盖族表分类。
        ae = self._argspec_env(env, reg)
        # \begin/\end 宏端点前间隙先剖字面项——不进 v_begin，否则 ENV/
        # ENVTAG/VERB 体头部夹带前隙（in_arg ident 渲染丢空格）
        self._cover_gap(fid, t.pos[1])
        v_begin = self._cover_to(fid, close_t.pos[2])
        pht = _env_ph_type(env, ae, reg)
        if pht is PhType.VERB:
            self._flush_run(v_begin.start)
            if m is not None:
                # 宏端点的 \end 面是 \eev 形宏事件——无 \end{env} 字面可
                # find，走 token 级配对（体照常按 raw token 扫描收集，
                # 渲染直切 vt 字节 = 字面）
                hit = self._find_env_end(src, env, t.pos)
                if hit is None:
                    # 未闭合也先吃环境尾参——{cc} preamble/版式 [opt]
                    # 不裸进 chunk（R2，全臂同规）
                    end = self._eat_env_args(src, fid, close_t.pos[2], env, reg, ae)
                    vspan = self._cover_to(fid, end)
                    self._emit(v_begin.start, vspan.end)
                    self.state.warnings.append(
                        ScanWarning("unclosed_env", v_begin.start, env)
                    )
                    return
                _tag, last, _body = hit
                vspan = self._cover_to(last.pos[0], last.pos[2])
                self._emit_ph(
                    PhType.VERB,
                    v_begin.start,
                    vspan.end,
                    self.vt.slice(v_begin.start, vspan.end),
                )
                return
            pat = "\\end{" + env + "}"
            if env in DEAD_ENVS:
                # comment 族行锚整行终结（_env_stop dead 臂同式）——行中
                # \end{comment} 是体字面，不闭合
                k = dead_env_end(self.file_texts[fid], env, close_t.pos[2])
            elif env.startswith("filecontents"):
                # filecontents 逐行读体、end 行首独占才算闭合（kernel 语义）——
                # 裸 find 会被体内 PostScript/注释里的行中 \end decoy 截短（W26）
                rx = re.compile(rf"(?m)^[ \t]*{re.escape(pat)}")
                fm = rx.search(self.file_texts[fid], close_t.pos[2])
                k = -1 if fm is None else fm.end() - len(pat)
            else:
                k = self.file_texts[fid].find(pat, close_t.pos[2])
            if k < 0:
                end = self._eat_env_args(src, fid, close_t.pos[2], env, reg, ae)
                vspan = self._cover_to(fid, end)
                self._emit(v_begin.start, vspan.end)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", v_begin.start, env)
                )
                return
            end = k + len(pat)
            vspan = self._cover_to(fid, end)
            self._emit_ph(
                PhType.VERB,
                v_begin.start,
                vspan.end,
                self.vt.slice(v_begin.start, vspan.end),
            )
            self._skip_past(src, fid, end)
            return
        if pht is PhType.MATH:
            hit = self._find_env_end(src, env, t.pos)
            if hit is None:
                self._flush_run(v_begin.start)
                end = self._eat_env_args(src, fid, close_t.pos[2], env, reg, ae)
                vspan = self._cover_to(fid, end)
                self._emit(v_begin.start, vspan.end)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", v_begin.start, env)
                )
                return
            _tag, last, _body = hit
            vspan = self._cover_to(last.pos[0], last.pos[2])
            # v1：math env ph 进 run（行内数学嵌段语义），非独立 piece
            self._rappend_ph(
                self._ph(PhType.MATH, self.vt.slice(v_begin.start, vspan.end)),
                Span(v_begin.start, vspan.end),
            )
            return
        if pht is PhType.ENV or (reg is not None and reg.kind == "protected"):
            hit = self._find_env_end(src, env, t.pos)
            if hit is None:
                self._flush_run(v_begin.start)
                end = self._eat_env_args(src, fid, close_t.pos[2], env, reg, ae)
                vspan = self._cover_to(fid, end)
                self._emit(v_begin.start, vspan.end)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", v_begin.start, env)
                )
                return
            tag, last, body_toks = hit
            self._flush_run(v_begin.start)
            body, vend = self._env_with_mined(
                env=env, vbegin=v_begin, tag=tag, last=last, body_toks=body_toks
            )
            self._emit_ph(PhType.ENV, v_begin.start, vend, body)
            return
        # transparent/未知/注册透明 env
        if self.in_arg:
            transparent = (
                env in ARG_TRANSPARENT_ENVS
                or (reg is not None and reg.kind in ("transparent", "theorem"))
                or ae is not None  # 到尾段即 body_role=text 的 argspec env
            )
            if transparent:
                end = self._eat_env_args(src, fid, close_t.pos[2], env, reg, ae)
                vspan = self._cover_to(fid, end)
                self._rappend_ph(
                    self._ph(PhType.ENVTAG, self.vt.slice(v_begin.start, vspan.end)),
                    Span(v_begin.start, vspan.end),
                )
                self.env_stack.append(env)
                self._scope_push(src)
                return
            # in_arg 未知/结构环境 → 整段 [[ENV]] 进 run（v1 泄漏 C2 修复）
            hit = self._find_env_end(src, env, t.pos)
            if hit is None:
                # 未闭合也吃环境尾参——ENVTAG 界延到 preamble 后（R2 同规）
                end = self._eat_env_args(src, fid, close_t.pos[2], env, reg, ae)
                vspan = self._cover_to(fid, end)
                self._rappend_ph(
                    self._ph(PhType.ENVTAG, self.vt.slice(v_begin.start, vspan.end)),
                    Span(v_begin.start, vspan.end),
                )
                self.state.warnings.append(
                    ScanWarning("unclosed_env", v_begin.start, env)
                )
                return
            tag, last, body_toks = hit
            body, vend = self._env_with_mined(
                env=env, vbegin=v_begin, tag=tag, last=last, body_toks=body_toks
            )
            self._rappend_ph(self._ph(PhType.ENV, body), Span(v_begin.start, vend))
            return
        self._flush_run(v_begin.start)
        end = self._eat_env_args(src, fid, close_t.pos[2], env, reg, ae)
        vrow = self._cover_to(fid, end)
        self._emit(v_begin.start, vrow.end)  # \begin 行（含吃掉的环境参）literal
        self.env_stack.append(env)
        self._scope_push(src)

    def _handle_env_end(
        self, t: Tok, src: TokenSource, m: MacroDef | None = None
    ) -> None:
        r"""``\end{env}``：in_arg→ENVTAG；``\end{document}``→顶层截停。

        ``m`` 非空 = env_end 宏端点（``\eeq`` 形）：env 取
        ``m.target_env``、tag 区间 = cs 本体。
        """
        fid, _a, _b = t.pos
        if m is None:
            env, close_t, consumed = self._env_name(src)
            if env is None:
                src.unread(consumed)
                self._rappend_tok(t)
                return
        else:
            env, close_t = m.target_env, t
        self._cover_gap(fid, t.pos[1])  # \end 前间隙 → 字面项（不进 ENVTAG 体）
        vspan = self._cover_to(fid, close_t.pos[2])
        if self.in_arg:
            self._rappend_ph(
                self._ph(PhType.ENVTAG, self.vt.slice(vspan.start, vspan.end)),
                vspan,
            )
            for _ in range(self._env_pop(env, vspan.start)):
                self._scope_pop(src)
            return
        self._flush_run(vspan.start)
        self._emit(vspan.start, vspan.end)
        if env == "document" and not self.in_arg:
            # \end{document} 之后全逐字（顶层截停，v1 row5）
            tail = self._cover_to(fid, len(self.file_texts[fid]))
            self._emit(vspan.end, tail.end)
            self._stop = True
            return
        for _ in range(self._env_pop(env, vspan.start)):
            self._scope_pop(src)

    def _env_pop(self, env: str, vpos: int) -> int:
        r"""v1 ``_env_pop`` 移植：弹 env 栈，返回弹出数（= scope_pop 次数）。

        栈顶即 target → 1；深匹配 → 隐式弹中间层 + ``env_mismatch``；
        栈空/无匹配 → ``stray_end`` + 0。
        """
        target = env.rstrip("*")
        if self.env_stack and self.env_stack[-1].rstrip("*") == target:
            self.env_stack.pop()
            return 1
        if target in {e.rstrip("*") for e in self.env_stack}:
            popped: list[str] = []
            while self.env_stack and self.env_stack[-1].rstrip("*") != target:
                popped.append(self.env_stack.pop())
            if self.env_stack:
                self.env_stack.pop()
            self.state.warnings.append(
                ScanWarning("env_mismatch", vpos, f"\\end{{{env}}} 隐式关闭 {popped}")
            )
            return len(popped) + 1
        self.state.warnings.append(ScanWarning("stray_end", vpos, f"\\end{{{env}}}"))
        return 0

    def _handle_pair_block(
        self, t: Tok, src: TokenSource, name: str, m: object | None
    ) -> None:
        r"""``cs`` 对界 DSL 块（``\labellist…\endlabellist`` pinlabel 形，W29）。

        体走 ``_env_with_mined`` 同款 mined 子扫：``\pinlabel {tex}``
        等 CHUNK_ARG 体命令照产 chunk，``at x y`` 坐标脚手架随 ENV 体
        保护不裸进可译面。闭名 cs 孤现 → ``[[CMD]]`` 进 run；开 cs 无
        配对 → ``unclosed_env`` 告警后落 ``_handle_unknown_cs``（探针
        吃 ``{arg}`` 进 CMD——保守不译也不裸漏）。
        """
        fid = t.pos[0]
        close = PAIR_BLOCK_CMDS.get(name)
        if close is None:
            # 孤 \end<block> 闭合 cs——CMD 保护（不吞参）
            self._cover_gap(fid, t.pos[1])
            vspan = self._cover_to(fid, t.pos[2])
            self._rappend_ph(
                self._ph(PhType.CMD, self.vt.slice(vspan.start, vspan.end)),
                vspan,
            )
            return
        # 先扫后盖——``_find_pair_end`` 未命中时 cs 字节须未盖，否则落
        # unknown-cs 的 CMD 体缺名（覆盖账单调，已盖区间不回卷）
        hit = self._find_pair_end(src, name, close)
        if hit is None:
            self.state.warnings.append(ScanWarning("unclosed_env", t.pos[1], name))
            self._handle_unknown_cs(t, src, name, m)
            return
        self._cover_gap(fid, t.pos[1])
        v_begin = self._cover_to(fid, t.pos[2])
        tag, last, body_toks = hit
        body, vend = self._env_with_mined(
            env=name, vbegin=v_begin, tag=tag, last=last, body_toks=body_toks
        )
        if self.in_arg:
            self._rappend_ph(self._ph(PhType.ENV, body), Span(v_begin.start, vend))
            return
        self._flush_run(v_begin.start)
        self._emit_ph(PhType.ENV, v_begin.start, vend, body)

    def _find_pair_end(  # noqa: C901 — ``_find_env_end`` 配对 cs 版同款单遍扫描
        self, src: TokenSource, open_: str, close: str
    ) -> tuple[Tok, Tok, list[Tok]] | None:
        r"""``cs`` 对界块收尾扫描（``_find_env_end`` 的配对 cs 版）。

        ``read()`` 原始流前瞻找闭名 cs 或 ``\end{open}`` env 闭形——
        块不嵌套、首命中即闭合（``\end{labellist}`` 混搭形是 TeX 合法
        ``\end{X}``→``\endX`` 展开的对价）。``\verb`` 定界体/``\input``
        前瞻展开两分支与 ``_find_env_end`` 同规。未命中回吐全部已收
        token 返回 ``None``（调用方落 unknown-cs 保守路径）。
        """
        collected: list[Tok] = []
        while True:
            x = src.read()
            if x is None:
                src.unread(collected)
                return None
            collected.append(x)
            if x.kind != "cs":
                continue
            if x.text == close:
                return x, x, collected[:-1]
            if x.text in ("verb", "verb*", "lstinline"):
                self._skip_verb_toks(src, collected)
                continue
            if x.text == "end":
                n2, c2, grp = self._env_name(src)
                if n2 is None:
                    src.unread(grp)
                    continue
                collected.extend(grp)
                if n2 == open_:
                    return x, c2, collected[: -(1 + len(grp))]
                continue
            if isinstance(src, Gullet) and x.text in INPUT_CMDS:
                # 前瞻不触发展开——\input 族交回 gullet 正常内联（
                # _find_env_end 同臂；否则子文件 token 随 _ListSource
                # 重放漏网成 literal）
                try:
                    hit = src._do_input(x, x.text)  # noqa: SLF001 — §4 契约面：前瞻展开经 gullet 内部入口
                except ArgMismatch:
                    src.unread(src._trace)  # noqa: SLF001 — ArgMismatch 回吐协议（§3.5）
                    hit = None
                if hit is not None and hit is not x:
                    collected[-1] = hit
                continue

    def _eat_env_args(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915, PLR0917 — opt/mand/colspec 三段判定平铺即 v1 行序
        self,
        src: TokenSource,
        fid: int,
        pos: int,
        env: str,
        reg: object | None,
        ae: ArgspecEntry | None = None,
    ) -> int:
        r"""``\begin`` 行尾 token 版：版式 ``[opt]`` + 强制 ``{arg}`` 数。

        ``[opt]`` 内容过 ``env_opt_is_format``——版式参吃掉进 LITERAL，
        定理类标题正文回吐随主流进 chunk（F6 修复语义）。mand =
        ``ENV_MANDATORY_ARG`` ∪ 登记 ``spec`` 的 ``m`` 槽数。v1
        ``ws_skip_arg`` 结果恒入 ``pos``——ws token 拉出即消费（字节
        随 ``_cover_to`` 进 begin 行），只参数 token 未中才 ``unread``。
        ``ae`` 非空且带签名 → :meth:`_eat_env_args_spec` 签名驱动版。
        """
        if ae is not None and ae.signature:
            return self._eat_env_args_spec(src, fid, pos, env, ae)
        pulled: list[Tok] = []
        x = self._peek_nonspace(src, pulled)
        if x is None:
            if pulled:
                pos = pulled[-1].pos[2]  # par/EOF 前 ws 已消费（v1 pos 过 ws）
        elif x.kind == "other" and x.text == "[":
            hit = self._collect_group(src, x, brace=False)
            if hit is None:
                return x.pos[1]  # `[` 未闭——组已回吐主流重扫；ws 在 pos 内
            inner, closer = hit
            content = self.file_texts[fid][x.pos[2] : closer.pos[1]]
            if env_opt_is_format(env, content):
                pos = closer.pos[2]
            else:
                src.unread([x, *inner, closer])  # 标题正文回吐进 chunk
                return x.pos[1]
        else:
            src.unread([x])
            pos = x.pos[1]
        mand = 1 if env in ENV_MANDATORY_ARG else 0
        if reg is not None:
            mand = max(
                mand,
                sum(1 for a in getattr(reg, "spec", ()) if a.kind == "m"),
            )
        for _ in range(mand):
            p2: list[Tok] = []
            x = self._peek_nonspace(src, p2)
            if x is None:
                if p2:
                    pos = p2[-1].pos[2]
                break
            if x.kind != "lbrace":
                src.unread([x])
                pos = x.pos[1]
                break
            hit = self._collect_group(src, x, brace=True)
            if hit is None:
                pos = x.pos[1]  # `{` 未闭已回吐；ws 消费进 pos
                break
            pos = hit[1].pos[2]
        if mand == 0:
            # 未注册环境的列型前导参（``\begin{mytable}{>{\raggedright}
            # p{4cm}}`` 形）——无 ``ENV_MANDATORY_ARG``/签名可据，首 ``{..}``
            # 形似列参即吃进 begin 行字面段（R3；``{Title}`` 形文本参
            # 回吐主流——判据/误伤面见 ``looks_like_colspec``）
            p3: list[Tok] = []
            x = self._peek_nonspace(src, p3)
            if x is not None and x.kind == "lbrace":
                hit = self._collect_group(src, x, brace=True)
                if hit is None:
                    return x.pos[1]  # `{` 未闭——组已回吐；ws 在 pos 内
                inner, closer = hit
                if looks_like_colspec(self.file_texts[fid][x.pos[2] : closer.pos[1]]):
                    return closer.pos[2]
                src.unread([x, *inner, closer])
                return x.pos[1]
            if x is None:
                if p3:
                    pos = p3[-1].pos[2]
            else:
                src.unread([x])
                pos = x.pos[1]
        return pos

    def _eat_env_args_spec(
        self, src: TokenSource, fid: int, pos: int, env: str, e: ArgspecEntry
    ) -> int:
        r"""Argspec 签名驱动的 ``\begin`` 尾参：非文本参吃掉进 LITERAL。

        ``text``/``opt-text`` 角色参回吐主流——beamer
        ``\\begin{frame}{Title}`` 的 ``d{}`` 标题吃进字面段就永不进
        chunk（今日 ``{title}`` 组随正文流的召回面不能回退）。可选位
        （``o``/``O``/``d``/``D``）仍过 ``env_opt_is_format``——数据里
        ``skip`` 角色对 ``[opt]`` 只是「非文本」缺省标注，定理标题
        ``[Name]`` 不归其管（F6 语义保持）。
        """
        spec = _chunk_spec_cached(e.signature)
        args, _end = self._args_tok(src, fid, spec, pos, allow_single_token=True)
        eat_end = pos
        for k, a in enumerate(args):
            if a.fe <= a.fs:
                continue  # 零宽占位（all_toks 空）
            kind = a.spec.kind if a.spec is not None else ""
            role = e.arg_roles[k] if k < len(e.arg_roles) else "skip"
            if kind in ("o", "O", "d", "D"):
                # 可选位：role=text 的定界参是标题（frame ``{Title}``）
                # 直接回吐——``env_opt_is_format`` 会把单字符标题误判
                # 成位置字母；``d<>`` 叠层 spec 恒版式（``+-`` 内容不在
                # 版式字符表）；其余角色过版式判定（``skip`` 对 ``[opt]``
                # 只是缺省标注，定理 ``[Name]`` 不归其管——F6 语义保持）。
                content = self.file_texts[fid][a.cs : a.ce]
                if role == "text" or (
                    a.spec.delim != "<>" and not env_opt_is_format(env, content)
                ):
                    self._unread_args(src, args[k:])
                    return eat_end
                eat_end = a.fe
                continue
            if role in ("text", "opt-text"):
                self._unread_args(src, args[k:])
                return eat_end
            eat_end = a.fe
        return eat_end

    def _env_with_mined(
        self,
        *,
        env: str,
        vbegin: Span,
        tag: Tok,
        last: Tok,
        body_toks: list[Tok],
    ) -> tuple[str, int]:
        r"""保护环境体 → in_arg 子扫挖 caption/footnote → 渲染体。

        返回 ``(body, vend)``：body = begin 行切片 + mined 渲染 + end tag
        切片（``_env_with_mined`` token 版）；vend = ``\end{env}`` 后 vtex 位。
        体 token 已被 ``_find_env_end`` 消费——子扫 ``_ListSource`` 重放
        只负责渲染，覆盖经共享 vt/cons 直落父区间。
        """
        if self.gen >= MAX_GEN:
            self.state.warnings.append(
                ScanWarning("gen_overflow", vbegin.start, f"env:{env}")
            )
            vend = self._cover_to(last.pos[0], last.pos[2])
            return self.vt.slice(vbegin.start, vend.end), vend.end
        # v1 ``MINED_ONLY + in_arg=False``：run 全 literal 但分派照常——
        # \caption 照产 chunk（in_arg=True 会内联化不产，T12 回归）
        sub = self.spawn(in_arg=False, mined=True)
        sub.env_stack.append(env)
        sub.scan(_ListSource(body_toks), self.file_texts)
        sub_end = len(self.vt)  # 子扫 pieces 平铺到此（scan 尾部兜底保证）
        self._cover_to(tag.pos[0], tag.pos[1])  # 子扫丢 token 的体尾字节兜底
        vend = self._cover_to(last.pos[0], last.pos[2])
        rendered = "".join(p.text for p in sub.pieces)
        if sub_end < vend.start:
            # 已盖未挂 piece 的残余字节（peek 吞掉的尾空白/杂项 token）——
            # 不进 rendered 则 ENV 体丢字节，identity 破（F-尾丢）
            rendered += self.vt.slice(sub_end, vend.start)
        return (
            self.vt.slice(vbegin.start, vbegin.end)
            + rendered
            + self.vt.slice(vend.start, vend.end)
        ), vend.end

    def _resolve_macro(self, src: TokenSource, name: str) -> object | None:
        r"""宏表查名（``Alias`` 解一层）。

        Gullet 源查 ``src.macros``；``_ListSource`` 子扫查共享的
        ``state.macros``——同一张表，v1 平表在子扫内可查的对应物
        （in_arg/env 体里的 ``\\beq`` 端点宏也命中）。时点近似：表
        反映的是子扫启动位的 scope 态，体内迟定义不回看。
        """
        tab = src.macros if isinstance(src, Gullet) else self.state.macros
        return tab.resolve(tab.lookup(name))

    @staticmethod
    def _env_sig_tok(src: TokenSource, target: str) -> frozenset:
        r"""Target env 端点宏签名（v1 ``_env_sig`` token 版）。

        gullet scope 链全量快照 ``(name, kind, scope_depth)``——迟到
        ``\def`` 登记/改义/scope 弹出使墓标事件面失真即作废。
        ``_ListSource`` → 空集：子扫 token 列固定、宏表在重放内不突变，
        单次扫描内墓标自洽（墓标本体也不跨子扫共享）。
        """
        if not isinstance(src, Gullet):
            return frozenset()
        out = set()
        for depth_i, scope in enumerate(src.macros.scopes):
            for name, entry in scope.items():
                m = src.macros.resolve(entry)
                kind = getattr(m, "kind", "")
                if (
                    kind in ("env_begin", "env_end")
                    and getattr(m, "target_env", "").rstrip("*") == target
                ):
                    out.add((name, kind, depth_i))
        return frozenset(out)

    def _replay_dead(
        self, src: TokenSource, tag_span: tuple[int, int, int]
    ) -> tuple[Tok, Tok, list[Tok]] | None:
        r"""墓标命中回放：拉到 end tag 末 token，tag 前 token 归 body。

        ``tag_span`` = ``(fid, tag_start, tag_end)``——回放期事件 token 与
        录制期同一批（raw 流子集保序）。失效检测：同 fid raw token 越过
        ``tag_end``（end tag 已被中间展开/消费吃掉）、tag 区被外来 token
        打断、tag 首 token 缺失、流尽——一律回吐已拉 token 返回 None，
        由 ``_find_env_end`` 正常续扫（事件重录，墓标保持完备）。
        """
        tfid, ts, te = tag_span
        pulled: list[Tok] = []
        body: list[Tok] = []
        tag: list[Tok] = []
        ok = False
        while True:
            x = src.read()
            if x is None:
                break
            pulled.append(x)
            raw_here = x.kind != "consumed" and x.gen == 0 and x.pos[0] == tfid
            if raw_here and x.pos[1] >= te:
                break  # 越过 tag 末——end tag 已被消费，墓标失效
            if raw_here and x.pos[1] >= ts:
                tag.append(x)
                if x.pos[2] == te:
                    ok = tag[0].pos[1] == ts
                    break
                continue
            if tag:
                break  # tag 区间被外来 token（展开注入等）打断——失效
            body.append(x)
        if ok:
            return tag[0], tag[-1], body
        src.unread(pulled)
        return None

    def _find_env_end(  # noqa: C901, PLR0911, PLR0912, PLR0915 — begin/end/csname-end/verb/宏端点五分支单遍查找
        self, src: TokenSource, env: str, qpos: tuple[int, int, int]
    ) -> tuple[Tok, Tok, list[Tok]] | None:
        r"""Token 版 env 配对（``read()`` 原始流——前瞻不触发展开副作用）。

        命中返回 ``(end_cs_or_macro_tok, 末位 token, body_toks)``——tag
        起点 = 首元 ``pos[1]``、体 token 列供 ``_env_with_mined`` 重放；
        未命中回吐全部已收 token 返回 None。
        ``*`` 两侧归一（泄漏 C1）；verb 定界体/嵌套 verbatim env 体内
        假 ``\end`` 不计（v1 ``skip_verb_at``/VERBATIM 跳的 token 版）。

        F12：未闭合扫描把端点事件存 ``_env_dead`` 墓标（``_EnvDeadTok``
        ——seq+pos 锚，详见类 docstring）；同 target、签名未变的后续查询
        按盈余相等直答 + 文件区间回放，不再 O(n) 重扫到 EOF。
        ``qpos`` = 本次 ``\begin`` tag 首 token 的 pos。
        """
        target = env.rstrip("*")
        sig = self._env_sig_tok(src, target)
        # comment 族终结是纯字面行锚——墓标键用未剥 * 的 env 本名
        # （comment/comment* 终结子串不同，共享 target 键会交叉误命中）
        dkey = env if env in DEAD_ENVS else target
        dead = self._env_dead.get(dkey)
        if dead is not None and dead.sig == sig:
            if env in DEAD_ENVS:
                return None  # dead 墓标 = 该 env 行锚 \end 全图不存在
            k_q = dead.bidx.get(qpos, -1)
            if k_q >= 0:
                qs = dead.begins[k_q]
                sj = (k_q + 1) - bisect_left(dead.ends, qs)
                for k in range(bisect_left(dead.ends, qs), len(dead.ends)):
                    if dead.s_end[k] == sj:
                        hit = self._replay_dead(src, dead.end_tag[k])
                        if hit is not None:
                            return hit
                        break  # 失效已回吐 → 落正常扫描（事件重录）
                else:
                    return None  # 事件流完备——无配对即真未闭合
        collected: list[Tok] = []
        begins: list[int] = []
        begin_pos: list[tuple[int, int, int]] = []
        ends: list[int] = []
        end_tag: list[tuple[int, int, int]] = []
        depth = 1
        while True:
            x = src.read()
            if x is None:
                src.unread(collected)
                self._env_dead[dkey] = _EnvDeadTok(
                    sig,
                    begins,
                    begin_pos,
                    {p: i for i, p in enumerate(begin_pos)},
                    ends,
                    end_tag,
                    [bisect_left(begins, e) - k for k, e in enumerate(ends)],
                )
                return None
            collected.append(x)
            if x.kind != "cs":
                continue
            seq = len(collected) - 1  # 事件位 = tag 首 token 的拉取序号
            if x.text in ("verb", "verb*", "lstinline"):
                self._skip_verb_toks(src, collected)
                continue
            if isinstance(src, Gullet) and x.text in INPUT_CMDS:
                # 前瞻 read() 不触发展开——\input 族收进 body_toks 会随
                # _ListSource 子扫漏网成 literal（v1 flatten 先内联）。
                # 交回 gullet 正常展开：marker 顶替已入列的 cs（pos 覆盖
                # 整调用）、新源 token 由后续 read() 照常进 collected。
                try:
                    hit = src._do_input(x, x.text)  # noqa: SLF001 — §4 契约面：前瞻展开经 gullet 内部入口
                except ArgMismatch:
                    # 流尽（\input{ 未闭合）——残参回放走漏网路，cs 留 literal
                    src.unread(src._trace)  # noqa: SLF001 — ArgMismatch 回吐协议（§3.5）
                    hit = None
                if hit is not None and hit is not x:
                    collected[-1] = hit
                continue
            if x.text in ("begin", "end"):
                n, c, grp = self._env_name(src)
                if n is None:
                    # 失败 token 回吐重分派——grp 里可能藏着真 \end{target}
                    # （``\begin \end{figure}`` 形），v1 pos 不动等价
                    src.unread(grp)
                    continue
                collected.extend(grp)
                if env in DEAD_ENVS:
                    # comment 族行锚整行终结、体不嵌套（_env_stop dead 臂
                    # 同式）——行中/断序列 \end{env}、异名交叉 \end、体内
                    # \begin{env} 与 verb/verbatim 跳读资格全不落，纯体字面
                    if (
                        x.text == "end"
                        and n == env
                        and x.pos[0] == c.pos[0]
                        and dead_end_anchored(
                            self.file_texts[x.pos[0]], env, x.pos[1], c.pos[2]
                        )
                    ):
                        return x, c, collected[: -(1 + len(grp))]
                    continue
                if n.rstrip("*") != target:
                    if n in VERBATIM_ENVS and x.text == "begin":
                        self._skip_verbatim_env_toks(src, n, collected)
                    continue
                if x.text == "begin":
                    depth += 1
                    begins.append(seq)
                    begin_pos.append(x.pos)
                else:
                    depth -= 1
                    if depth == 0:
                        body = collected[: -(1 + len(grp))]
                        return x, c, body
                    ends.append(seq)
                    end_tag.append((x.pos[0], x.pos[1], c.pos[2]))
                continue
            # ``\end<env>`` 字面端点：csname 合成（``\csname endtabular
            # \endcsname`` 产 gen=0 cs token，宏表无登记）与旧式写法
            # （``\begin{tabular}…\endtabular``——LaTeX 内核 ``\end{X}``
            # 即 ``\csname endX\endcsname``）都按 env_end 计对（R1）。
            # 先于宏解析——重定义 ``\endfoo`` 为别体的边缘形也按端点配对。
            # dead 族不算：comment.sty 只认行锚 ``\end{env}`` 字面行。
            if env not in DEAD_ENVS and x.text == "end" + target:
                depth -= 1
                if depth == 0:
                    return x, x, collected[:-1]
                ends.append(seq)
                end_tag.append((x.pos[0], x.pos[1], x.pos[2]))
                continue
            if env not in DEAD_ENVS and x.text == "csname":
                # 直用 ``\csname end<env>\endcsname``：raw 前瞻不触发
                # csname 合成（``_read_csname`` 的 token 版镜像）——收名
                # 到 ``\endcsname`` 止，命中 ``end+target`` 按 env_end
                # 计对；收不到（流尽）交给外层 EOF 墓标路径
                ctoks: list[Tok] = []
                while True:
                    y = src.read()
                    if y is None:
                        break
                    collected.append(y)
                    if y.kind == "cs" and y.text == "endcsname":
                        if "".join(str(z) for z in ctoks) == "end" + target:
                            depth -= 1
                            if depth == 0:
                                return x, y, collected[: -(len(ctoks) + 2)]
                            ends.append(seq)
                            end_tag.append((x.pos[0], x.pos[1], y.pos[2]))
                        break
                    ctoks.append(y)
                continue
            m = self._resolve_macro(src, x.text)
            kind = getattr(m, "kind", "")
            tgt = getattr(m, "target_env", "")
            if (
                env not in DEAD_ENVS
                and kind in ("env_begin", "env_end")
                and tgt.rstrip("*") == target
            ):
                if kind == "env_begin":
                    depth += 1
                    begins.append(seq)
                    begin_pos.append(x.pos)
                else:
                    depth -= 1
                    if depth == 0:
                        return x, x, collected[:-1]
                    ends.append(seq)
                    end_tag.append((x.pos[0], x.pos[1], x.pos[2]))

    def _skip_verb_toks(  # noqa: C901 — 定界三形平铺
        self, src: TokenSource, collected: list[Tok]
    ) -> None:
        r"""``\verb``/``\lstinline`` 定界体 token 跳读（假 ``\end`` 不计）。

        定界符 = 下一 token 文本；同符再现或 ``eol_par``/EOF 止——字节版
        ``skip_verb_at`` 的 token 近似（配对 ``{..}`` 形按单 token 近似，
        组内 ``\end`` 误计风险与字节版同阶、可接受）。
        """
        d = src.read()
        if d is not None:
            collected.append(d)
        if d is None:
            return
        if d.kind == "other" and d.text == "*":
            d = src.read()
            if d is not None:
                collected.append(d)
            if d is None:
                return
        if d.kind == "lbrace":
            hit = self._collect_group(src, d, brace=True)
            if hit is not None:
                inner, closer = hit
                collected.extend(inner)
                collected.append(closer)
            return
        delim = d.text
        while True:
            x = src.read()
            if x is None:
                return
            collected.append(x)
            if x.kind == "eol_par" or x.text == delim:
                return

    def _skip_verbatim_env_toks(
        self, src: TokenSource, env: str, collected: list[Tok]
    ) -> None:
        r"""嵌套 verbatim env 体整段跳读（体内 ``\end{target}`` 是字面）。

        comment 族体不嵌套、仅行锚 ``\\end{env}`` 终结（``_env_stop`` dead
        臂同式）——行中 ``\\end{comment}`` 与体内 ``\\begin{comment}``
        全是体字面。
        """
        dead = env in DEAD_ENVS
        depth = 1
        while True:
            x = src.read()
            if x is None:
                return
            collected.append(x)
            if x.kind != "cs" or x.text not in ("begin", "end"):
                continue
            n, c, grp = self._env_name(src)
            if n is None:
                src.unread(grp)  # 回吐重分派（同 _find_env_end）
                continue
            collected.extend(grp)
            if dead:
                if (
                    x.text == "end"
                    and n == env
                    and x.pos[0] == c.pos[0]
                    and dead_end_anchored(
                        self.file_texts[x.pos[0]], env, x.pos[1], c.pos[2]
                    )
                ):
                    return
                continue
            if n != env:
                continue
            depth += 1 if x.text == "begin" else -1
            if depth == 0:
                return
