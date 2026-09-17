r"""``latex/segmenter`` 子模块——god-class 机械拆分（行为零变）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.latex.gullet import (
    Gullet,
    IfSetter,
)
from texlate.latex.model import (
    PhType,
    ScanWarning,
    match_brace,
)
from texlate.latex.placeholder import (
    PH_RX,
)
from texlate.latex.tables import (
    ACCENT_CHARS,
    BOUNDARY_NAMES,
    CHUNK_ARG_NAMES,
    COND_RX,
    FONT_SWITCHES,
    INLINE_LITERAL_CMDS,
    INPUT_SCAN_CMDS,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    TRANSPARENT_HEAD_SPEC,
    TRANSPARENT_NAMES,
)

from ._common import (
    _GRP_FLOW_TAGS,
    _MATH_TEXTARG,
    _MATH_TEXTARG_OPT_CAP,
    _PKG_ARG_SPEC,
    _PKG_CMDS,
    _PROTECT_TYP,
    _TAIL_RX,
    TokenSource,
    _ArgTok,
    _cite_ref_type,
)

if TYPE_CHECKING:
    from texlate.latex.mouth import (
        Tok,
    )

r"""``Segmenter`` 主循环/preamble/分派/math/verb。"""


class _MainLoop:
    # ------------------------------------------------------------ 主循环

    def scan(self, src: TokenSource, files: list[str], doc_begin: int = -1) -> None:  # noqa: C901, PLR0912, PLR0915 — preamble/consumed/组界/dispatch 四态平铺即主循环
        r"""消费 ``src`` 至耗尽。``files`` = fid→源文本表（gullet.file_texts）。

        ``doc_begin`` = fid-0 上 ``\\begin{document}`` 的 ``\\begin`` 起点
        （api mask 视图判定，<0 = 无 preamble）：>0 时进 preamble 档——
        token 照常过 gullet（``\\def`` 登记/``\\if`` 求值/``\\input`` 内联
        全生效），分段侧一律 LITERAL 到该边界（v1 整段 ``_emit`` 对价）。
        """
        self.file_texts = files
        self._doc_begin = doc_begin
        self._preamble = doc_begin >= 0 and not self.in_arg
        v0 = len(self.vt)  # 扫描起点——子扫全命中已盖区时不回补前缀
        gullet_inputs = getattr(src, "inputs", None)
        live_srcs = (
            {id(m): m for m in gullet_inputs} if gullet_inputs is not None else None
        )
        # 栈成员变更事件门：``_pop_seq``/``_push_seq`` 不变即 live 快照不失真
        # （fid 进出栈唯一通道是 read() 弹栈 / push_source / unread 合成源，
        # 均计数）——免每 token 重建 dict diff（pdotaph2 986K 次重建省掉）。
        stack_ck = (
            (src._pop_seq, src._push_seq)  # noqa: SLF001 — §4 契约面：同模块事件钟
            if live_srcs is not None
            else (0, 0)
        )
        while not self._stop:
            t = src.next_expanded()
            if isinstance(src, Gullet) and len(self.file_texts) > self._ph_scan_n:
                # \input 懒加载：新压栈文件的字面 [[X_n]] 采进保留集——签发
                # 避让只护「之后」签发；先签发后加载的同号碰撞只能
                # ph_collision 告警留痕（占位符保留集覆盖洞 F2/S1）
                for ftext in self.file_texts[self._ph_scan_n :]:
                    hits = PH_RX.findall(ftext)
                    if hits:
                        self.state.ph_reserved.update(hits)
                        self.state.warnings.append(
                            ScanWarning(
                                "ph_collision",
                                len(self.vt),
                                f"{len(hits)} 处 [[X_n]] 形字面",
                            )
                        )
                self._ph_scan_n = len(self.file_texts)
            if (
                live_srcs is not None
                and (
                    src._pop_seq,  # noqa: SLF001
                    src._push_seq,  # noqa: SLF001
                )
                != stack_ck
            ):
                stack_ck = (src._pop_seq, src._push_seq)  # noqa: SLF001
                # 子文件源耗尽被 read() 弹栈：尾部不成 token 的字节（注释/
                # 空白尾）补盖 + 零宽 run 项（surface="" 不落译文面，ident
                # 随归属 piece 进 identity）——v1 flatten 保留这些字节。
                # \endinput 主动截停的尾巴不盖（flatten 同语义丢弃）。
                # 快照持 Mouth 引用：弹栈对象续命一拍，防 id() 地址复用把
                # 真弹栈遮蔽成"仍在栈"。
                cur = {id(m): m for m in gullet_inputs}
                endinput = (
                    t.pos[0]
                    if t is not None
                    and t.kind == "consumed"
                    and t.text.partition(":")[0] == "endinput"
                    else -1
                )
                for k, m in reversed(list(live_srcs.items())):
                    fid = m.file_id
                    if k in cur or fid < 0 or fid == endinput:
                        continue
                    if any(
                        t2.pos[0] == fid for mm in gullet_inputs for t2 in mm.tokbuf
                    ):
                        # 源弹栈 ≠ fid 枯竭：拉参/回放可把 fid 源提前排空，
                        # 残余 token 躺合成回放源 tokbuf——尾盖抢在回放分派
                        # 前吃字节 → 后续 cover 全零宽 → ph 空体整段 literal。
                        continue
                    vspan = self._cover_to(fid, len(files[fid]))
                    # preamble 档只盖不入队——emit 推迟整段兜底，run 项
                    # 会冲刷出与 preamble piece 重叠的 piece
                    if vspan.end > vspan.start and not self._preamble:
                        self._rappend("", self.vt.slice(vspan.start, vspan.end), vspan)
                live_srcs = cur
            if t is None:
                break
            if self._preamble:
                if self._doc_begin >= 0 and self._cons(0) > self._doc_begin:
                    # 覆盖已越过 \begin 起点——命中落在 def 体/if 死支等
                    # 整体消费区内（token 永不到主流）→ preamble literal 收尾。
                    # _doc_begin<0 = 起点不在 fid-0（\input 子文件内）——
                    # 只能等 \begin{document} token 流经 _preamble_tok 翻档
                    self._emit(
                        self.pieces[-1].span.end if self.pieces else 0,
                        len(self.vt),
                    )
                    self._preamble = False
                    self._doc_opened = True
                else:
                    self._preamble_tok(t, src)
                    continue
            if t.kind == "consumed":
                if self._in_group(t):
                    # 组内 marker（gen>0）：消费的是定义体区段（早已覆盖），
                    # 不是流边界——组界不破；input 型仍记 inputs[]。
                    # input/if/fi 是纯控制流；其余（def 族/let/catcode…）
                    # 已改宏表副作用 → 记标，收组时整组回 literal。
                    self._note_input(t)
                    if not t.text.startswith(_GRP_FLOW_TAGS):
                        self._open_side_effect = True
                    continue
                self._close_group()
                self._on_consumed(t)
                continue
            if self._in_group(t):
                self._open_toks.append(t)
                continue
            if t.gen > 0:
                self._close_group()
                self._open_group(t)
                self._open_toks.append(t)
                continue
            o = self._open_origin
            if (
                o is not None
                and t.pos[0] == o[0]
                and t.pos[1] >= o[2]
                and self._absorb_pending(t, src)
            ):
                continue
            self._close_group()
            if (
                t.kind == "cs"
                and t.gen == 0
                and t.text in ("documentclass", "documentstyle")
                and not self._doc_opened
                and not self.in_arg
                and not self.mined
                and not self.env_stack
            ):
                # preamble 起点不必在 fid-0：``\begin{document}`` 住
                # ``\input`` 子文件时主流先见 ``\documentclass``——现场翻
                # preamble 档（F7），收尾交给 _preamble_tok 的 begin 检出
                self._preamble = True
                self._preamble_tok(t, src)
                continue
            self._dispatch(t, src)
        self._close_group()
        # 流耗尽 ≠ 覆盖完备：主文件尾部（尾随注释/空白不产 token）补盖进
        # vtex——单文件 identity 的收口。\\endinput 截停的子文件尾巴不盖
        # （flatten 语义：\\endinput 后字节不进输出）。
        if files and not self.in_arg and not self.mined:
            self._cover_to(0, len(files[0]))
        self._flush_run(len(self.vt))
        # flush 后仍可能有 vtex 尾巴无 piece 承接（纯注释/空白尾不产 run
        # 项）——补 LITERAL 保 pieces 平铺不变式。
        tail_from = self.pieces[-1].span.end if self.pieces else v0
        if tail_from < len(self.vt):
            self._emit(max(tail_from, v0), len(self.vt))

    def _preamble_tok(self, t: Tok, src: TokenSource) -> None:
        r"""Preamble 档单 token：覆盖进 vtex 不 emit。

        emit 推迟到 ``\\begin{document}`` 检出或 EOF 的 tail emit——整段
        一条 LITERAL piece。``input:``/``input_tag:`` marker 保持调用点
        排除 + ``inputs[]`` 登记；gen>0 token 只盖调用点（origin），本体
        字节属已盖定义区。
        """
        fid, a, b = t.pos
        if t.kind == "consumed":
            if self._note_input(t):
                self._cover_to(fid, a)  # 调用点前间隙（注释/空白）照常进 vtex
                self._cons_bump(fid, b)
            else:
                self._cover_to(fid, b)
            return
        if self._preamble_doc_end(t, src, fid, b):
            return
        if t.kind == "cs" and t.text in _PKG_CMDS and t.gen == 0:
            # preamble 包声明：抽出 ``{pkg}`` 名单登记 argspec 门控；
            # 参数 token 回放照走 preamble 覆盖（含 \input 进来的声明）。
            args, _e = self._args_tok(src, fid, _PKG_ARG_SPEC, b)
            self._note_pkgs(args)
            self._unread_args(src, args)
            self._cover_to(fid, b)
            return
        if t.gen > 0:
            if t.origin is not None:
                self._cover_to(t.origin[0], t.origin[2])
            return
        # gen==0 组界在 preamble 同样开闭作用域——``{\catcode…}``/``{\makeatletter…}``
        #  preamble 包（\input 进的 .sty）不写到底帧泄漏（body 档 _dispatch 同型）。
        if t.kind == "lbrace":
            self._scope_push(src)
        elif t.kind == "rbrace":
            self._scope_pop(src)
        self._cover_to(fid, b)

    def _preamble_doc_end(self, t: Tok, src: TokenSource, fid: int, b: int) -> bool:
        r"""``\begin{document}`` 检出（字面或 env_begin 宏端点）→ 翻档。

        字面 ``\begin{document}`` 盖到 ``{document}`` 闭花括号；``\startdoc``
        形 env_begin 宏端点（gullet 不展开端点宏，主流收到的是 gen=0 调用
        token 而非 ``\begin`` 字面）盖到该 token 尾——宏包装拼法在
        ``\input`` 子文件里同样认（F7）。非 document 的 ``\begin{env}``
        回放名字 token 后只盖 ``\begin`` 本体。返回是否已处理（调用方即返）。
        """
        if t.kind != "cs" or t.gen != 0:
            return False
        end = -1
        if t.text == "begin":
            env, close_t, consumed = self._env_name(src)
            if env == "document":
                end = close_t.pos[2]
            else:
                src.unread(consumed)
                self._cover_to(fid, b)
                return True
        else:
            m = self._resolve_macro(src, t.text)
            if (
                getattr(m, "kind", "") == "env_begin"
                and getattr(m, "target_env", "").rstrip("*") == "document"
            ):
                end = b
        if end < 0:
            return False
        self._cover_to(fid, end)
        start = self.pieces[-1].span.end if self.pieces else 0
        self._emit(start, len(self.vt))
        self._preamble = False
        self._doc_opened = True
        return True

    @staticmethod
    def _tok_surface(t: Tok) -> str:
        """Token → surface 文本（展开组内渲染规则）。"""
        if t.kind == "cs":
            return "\\" + t.text
        if t.kind == "eol_par":
            return "\n\n"
        return t.text

    def _note_input(self, t: Tok) -> bool:
        r"""``input:``/``input_tag:`` consumed marker → ``inputs[]`` 登记。

        ``input_tag`` 的 payload 带 ``:tag`` 尾——rpartition 剥掉。返回是否
        命中（调用方据此走 input 分支：调用点字节不进 vtex）。
        """
        tag, _, name = t.text.partition(":")
        if tag not in ("input", "input_tag"):
            return False
        path = name.rpartition(":")[0] if tag == "input_tag" else name
        self.state.inputs.append((len(self.vt), path))
        return True

    def _on_consumed(self, t: Tok) -> None:
        r"""``consumed`` marker：gullet 静默消费区间的显形（契约 §4）。

        ``text`` = ``tag:name``——``input:path`` 记 ``inputs[]`` 且调用点
        字节不进 vtex（输出物不含 ``\\input`` 行）；其余 flush+LITERAL
        盖区间（def 串不落 chunk，否则译文会删 def）。
        """
        fid, a, b = t.pos
        self._flush_run(len(self.vt))
        if self._note_input(t):
            # 调用点前间隙（注释/空白）照常进 vtex——_cons_bump 只跳调用本体
            vspan = self._cover_to(fid, a)
            self._emit(vspan.start, vspan.end)
            self._cons_bump(fid, b)
        else:
            vspan = self._cover_to(fid, b)
            self._emit(vspan.start, vspan.end)

    def _cons_bump(self, fid: int, end: int) -> None:
        r"""``\\input`` 调用点字节只推进 cons 不进 vtex（输出不含该行）。"""
        if end > self._cons(fid):
            self.cons[fid] = end

    def _note_pkgs(self, args: list[_ArgTok]) -> None:
        r"""包加载命令已消费的 ``m`` 参 → 包名集入 ``state.pkgs``。

        ``\\usepackage{a,b}`` 逗号名单拆分；参未实消费（零宽占位）跳过。
        """
        for a in args:
            if a.spec is not None and a.spec.kind == "m" and a.fe > a.fs:
                for raw in "".join(x.text for x in a.toks).split(","):
                    nm = raw.strip()
                    if nm:
                        self.state.pkgs.add(nm)

    # ------------------------------------------------------------ 分派

    def _dispatch(self, t: Tok, src: TokenSource) -> None:  # noqa: C901, PLR0911, PLR0912, PLR0915 — §3.2 分派表 19 行平铺，顺序即语义
        r"""cs/结构 token 主分派——v1 ``_dispatch_cmd`` 的 token 版逐行移植。"""
        fid, _a, b = t.pos
        if t.kind == "cs":
            name = t.text
            # 1. \verb|..|/\lstinline 定界形（EOL 上限，W9/W10）
            if name in ("verb", "verb*", "lstinline"):
                self._handle_verb(t, src)
                return
            # 2/3. \def/\newif 族：gullet 消费发 consumed marker（主流首段
            #   处理）——漏网到此 = _ListSource 子扫内定义命令 → 落未知路径
            # 4. \begin{env}
            if name == "begin":
                self._handle_env_begin(t, src)
                return
            # 5. \end{env}
            if name == "end":
                self._handle_env_end(t, src)
                return
            # 6/7. cite/ref 词族 → [[CITE]]/[[REF]] 进 run（href/hyperref
            #    带可译 text 参除外——交 href 行 / row19 argspec chunk-arg）
            fam = _cite_ref_type(name)
            if fam is not None:
                self._protect_cs(t, src, fam, mand=self._cite_ref_mand(name))
                return
            # 8. PROTECT_NAMES → 类型映射；url/path 认逐字定界形
            if name in PROTECT_NAMES:
                self._protect_cs(
                    t,
                    src,
                    _PROTECT_TYP.get(name, PhType.CMD),
                    mand=2 if name == "inputminted" else 1,
                    verbatim=name in ("url", "path"),
                )
                return
            # 9. \href{url}{text}：url→[[HREF]]，text 继续扫
            if name == "href":
                self._handle_href(t, src)
                return
            # 10. \input 族漏网（gullet 未解析成功）：LITERAL + inputs[]
            if name in INPUT_SCAN_CMDS:
                self._handle_input_cs(t, src, name)
                return
            # 11. chunk 参数命令
            if name in CHUNK_ARG_NAMES:
                self._handle_chunk_arg(t, src, name)
                return
            # 12. 整块保护（\author{..} → [[AUTHOR]]）
            if name in PROTECT_BLOCK_NAMES:
                self._handle_protect_block(t, src)
                return
            # 12b. 头参非文本的透明命令（\textcolor{red}{text} 的 {red} 保护、
            #      {text} 留主流——argspec chunk-arg 的族表确定性版，不吃
            #      xcolor 包门控；色名裸落 → Undefined color 腐蚀）
            if name in TRANSPARENT_HEAD_SPEC:
                self._handle_transparent_head(t, src, name)
                return
            # 13. 透明命令：命令名进 run，参数随主流
            if name in TRANSPARENT_NAMES:
                self._rappend_tok(t)
                return
            # 14. 边界命令：文本 run 硬边界 + BOUNDARY_TAIL 结构尾参
            if name in BOUNDARY_NAMES:
                self._handle_boundary(t, src, name)
                return
            # 14b. \endinput 漏网（子扫内/未消费）：顶层截停
            if name == "endinput":
                self._handle_endinput(t, src)
                return
            # 15. 条件命令 \if*/\else/\fi/\or + \Xtrue/\Xfalse（IfSetter）
            #     + if* 宏调用——可求值支已被 gullet 消费成 if:/fi: marker
            #     夹心；到此者全走 _handle_cond 界标档（§8.6）
            m = self._resolve_macro(src, name)
            if isinstance(m, IfSetter) or COND_RX.match(name):
                self._handle_cond(t, src, name, m)
                return
            # 16. 数学定界 \[ \(；孤 \] \) 字面
            if name == "[":
                self._on_math_delim(t, src, "]")
                return
            if name == "(":
                self._on_math_delim(t, src, ")")
                return
            if name in ("]", ")"):
                self._rappend_tok(t)
                return
            # 16b. ``\\`` 的可选 dimen 参：``\\[5pt]``/``\\*[2em]`` 整调用
            #      → [[CMD]]（``[5pt]`` 裸进 surface → illegal_unit）
            if name == "\\":
                self._handle_bsbs(t, src)
                return
            # 16c. accent 族单参保护：``\c{c}``/``\~n`` 参字母+CJK 恒无意义
            #      （0806.3144 参被译 ``\c{这是译文}``→组合符无字槽）
            if len(name) == 1 and name in ACCENT_CHARS:
                self._handle_accent(t, src)
                return
            # 17. 行内字面（符号/品牌/旧式字体开关/无参单字符命令）
            if (
                name in INLINE_LITERAL_CMDS
                or name in FONT_SWITCHES
                or (len(name) == 1 and not name.isalpha())
            ):
                self._rappend_tok(t)
                return
            # 18. gullet 宏表命中：env_begin/env_end 宏端点走 \begin/\end
            #     同路（target_env 已知免读 {env} 组；_find_env_end 认宏
            #     端点事件）；opaque/math（体无文本不展开——math 即 v1
            #     OPAQUE 含数学特征的那半）→ 整调用 [[MACRO]]
            kind = getattr(m, "kind", "")
            if kind == "env_begin":
                self._handle_env_begin(t, src, m)
                return
            if kind == "env_end":
                self._handle_env_end(t, src, m)
                return
            if kind in ("opaque", "math"):
                self._handle_opaque_macro(t, src, m)
                return
            # 19. 未知命令：宏表未命中先查 argspec 表（包签名驱动分派），
            #     表外再走 {/[ 探针 → [[CMD]]；否则逐字进 run
            self._handle_unknown_cs(t, src, name, m)
            return
        if t.kind == "mathshift":
            self._on_math(t, src)
            return
        if t.kind == "eol_par":
            cons0 = self._cons(fid)
            vspan, ident = self._cover_text(fid, b)
            self._rappend(
                self._gap_surface(fid, cons0, t.pos[1]) + "\n\n",
                ident,
                vspan,
            )
            self._flush_run(vspan.end)
            return
        if t.kind == "lbrace":
            self._scope_push(src)
            self._run_brace += 1
            self._rappend_tok(t)
            return
        if t.kind == "rbrace":
            if self._run_brace > 0:
                self._run_brace -= 1
                self._rappend_tok(t)
            elif not any(it.surface.strip() for it in self._run):
                # 孤立 } 落在 run 头——配对 { 已被冲刷成字面/消费
                # （{\let\gl\relax}Body 族）：盖字面不进 run。否则 chunk
                # 头孤 } 被 LLM 丢改 → 下游花括失衡（L0 只管 [[ph]]
                # 不管裸括号，F11）。run 中段孤 }（配对 { 在先前
                # piece/chunk，eol_par 跨组切分等）留 run 保分段——
                # 两侧不平衡是跨 piece 配对的既有面
                self._cover_gap(fid, t.pos[1])
                vspan = self._cover_to(fid, b)
                self._flush_run(vspan.start)
                self._emit(vspan.start, vspan.end)
            else:
                self._rappend_tok(t)
            self._scope_pop(src)
            return
        # letter/other/space/active/param/杂项 → run
        self._rappend_tok(t)

    def _scope_push(self, src: TokenSource) -> None:
        """组开 → ``gullet.macros.push_scope`` + ``cats.push``（契约 §4 回报）。"""
        if isinstance(src, Gullet):
            src.macros.push_scope()
            src.cats.push()

    def _scope_pop(self, src: TokenSource) -> None:
        """组闭 → 宏表/cats 对称弹（底帧不弹由两侧各自兜底）。"""
        if isinstance(src, Gullet):
            src.macros.pop_scope()
            src.cats.pop()

    # ------------------------------------------------------------ math

    def _on_math(self, t: Tok, src: TokenSource) -> None:  # noqa: C901, PLR0912, PLR0915 — $$ 邻接/闭符分支平铺即 §3.3
        r"""``$``/``$$`` 配对：拉 token 到同窗 mathshift 止（``$$``=紧邻双 token）。

        混排闭符 ``\)/\]`` 同收——LaTeX 数学态内 ``\)=`` ``$``、``\]=``
        ``$$``，不收则越过真闭符吞散文、``$`` 奇偶翻转（0806.1984）。
        """
        fid, _a, b = t.pos
        disp = False
        nxt = src.read()
        if (
            nxt is not None
            and nxt.kind == "mathshift"
            and nxt.pos[0] == fid
            and nxt.pos[1] == b
        ):
            disp = True
        elif nxt is not None:
            src.unread([nxt])
        body: list[Tok] = []
        end_tok: Tok | None = None
        while True:
            x = src.read()
            if x is None:
                break
            if x.kind == "eol_par":
                src.unread([x])  # 段落边界不吞——回吐由主流断段
                break
            if x.kind == "mathshift":
                if not disp:
                    end_tok = x
                    break
                n2 = src.read()
                if (
                    n2 is not None
                    and n2.kind == "mathshift"
                    and n2.pos[0] == fid
                    and n2.pos[1] == x.pos[2]
                ):
                    end_tok = n2
                    break
                if n2 is not None:
                    src.unread([n2])
                body.append(x)
                continue
            if x.kind == "cs" and x.text in (")", "]"):
                # 混排闭符：``\)/\]`` 在 LaTeX 数学态语义即 ``$/$$``——
                # ``$...\)``/``$$...\]`` 收作闭符，否则越过真闭符续吞散文、
                # 奇偶翻转（0806.1984 ``$\alpha(x)\), for all $p \in S$``
                # ", for all " 落数学、"\p" 裸进散文被译，miss×12）。
                end_tok = x
                break
            if x.kind == "cs" and x.text in _MATH_TEXTARG:
                # \text 族正文参重进文本态——体内（含嵌套组）$ 属组内配
                # 对，不跳扫会在内层 $ 处截断外层数学（0806.3472 残留）。
                body.append(x)
                self._math_skip_textarg(src, body)
                continue
            body.append(x)
        if end_tok is None:
            cons0 = self._cons(fid)
            # disp 时 ``nxt``（``$$`` 第二枚 ``$``）已 read 出流——一并盖掉，
            # 否则丢 token：surface 剩单 ``$``、源字节成孤儿（0806.3472 的
            # ``Missing $``/``Display math should end with $$`` 错因）。
            vspan = self._cover_to(fid, nxt.pos[2] if disp else b)
            self._rappend(
                self._gap_surface(fid, cons0, t.pos[1])
                + t.text
                + (nxt.text if disp else ""),
                self.vt.slice(vspan.start, vspan.end),
                vspan,
            )
            self.state.warnings.append(ScanWarning("unpaired_dollar", vspan.start, "$"))
            if body:
                if x is None and isinstance(src, Gullet):
                    # Gullet EOF 中止：栈顶 Mouth 已被 read() 弹栈，unread 只
                    # 会建 file_id<0 合成源——主循环尾扫抢先整盖 [cons, EOF)
                    # → 回放 token 全零宽 → $\omega$ 类 ph 体空串静默丢。
                    # 余下字节直接 LITERAL 保真（字节全保，\end{document} 安全）。
                    self._flush_run(len(self.vt))
                    tail = self._cover_to(fid, len(self.file_texts[fid]))
                    self._emit(tail.start, tail.end)
                else:
                    # eol_par 中止，或 _ListSource 子扫耗尽——后者 unread
                    # 同队回插保序、无弹栈合成源问题，恒走回放（否则子扫
                    # 的 EOF 会把 [cons,文件尾) 整段 LITERAL 抢走主扫字节）。
                    src.unread(body)
            return
        eb = end_tok.pos[2]
        self._cover_gap(fid, t.pos[1])
        vspan = self._cover_to(fid, eb)
        ph = self._ph(PhType.MATH, self.vt.slice(vspan.start, vspan.end))
        self._rappend_ph(ph, vspan)

    @staticmethod
    def _skip_balanced(src: TokenSource, body: list[Tok], pair: str) -> None:
        r"""开符已进 ``body`` → 读到配对闭符止（嵌套计深；流尽自然终）。

        ``pair`` ∈ ``"{}"``/``"[]"``——brace 按 kind 判（``\{`` 转义是 cs
        不误算），bracket 按 ``other``+text 判。
        """
        open_kind, open_ch = ("lbrace", "{") if pair == "{}" else ("other", "[")
        close_kind, close_ch = ("rbrace", "}") if pair == "{}" else ("other", "]")
        depth = 1
        while depth:
            z = src.read()
            if z is None:
                return
            body.append(z)
            if z.kind == open_kind and z.text == open_ch:
                depth += 1
            elif z.kind == close_kind and z.text == close_ch:
                depth -= 1

    def _math_skip_textarg(self, src: TokenSource, body: list[Tok]) -> None:
        r"""``\text`` 族正文参整段收进 ``body``：``*``?+``[opt]``≤2+``{..}`` 定序跳扫。

        读到的 token 全进 ``body`` 两路均安全：paired 路只凭 vspan 盖字节、
        body 不参与；unpaired 路 ``unread(body)`` 原序回放。参非 ``{..}``
        打头（病态写法）则前缀按原样并入、跳扫提前返回。
        """
        opts = 0
        star_ok = True
        while True:
            y = src.read()
            if y is None:
                return
            body.append(y)
            if y.kind == "space":
                continue
            if star_ok and y.kind == "other" and y.text == "*":
                star_ok = False
                continue
            star_ok = False
            if y.kind == "lbrace":
                self._skip_balanced(src, body, "{}")
                return
            if y.kind == "other" and y.text == "[" and opts < _MATH_TEXTARG_OPT_CAP:
                self._skip_balanced(src, body, "[]")
                opts += 1
                continue
            return

    # ------------------------------------------------------------ verb

    def _handle_verb(self, t: Tok, src: TokenSource) -> None:  # noqa: C901, PLR0912, PLR0915 — verb 三形各一支，平铺即 W9/W10
        r"""``\\verb|..|``/``\\verb*``/``\\lstinline[opt]|..|``/``{...}`` 配对形。

        定界符 = 命令后首个非空白 token；``{..}`` 配对形按平衡组收；
        文件字节搜闭合（EOL 上限）+ ``skip_past`` resync（W9）。
        """
        fid, _a, b = t.pos
        name = t.text
        pulled: list[Tok] = []  # 命令后拉出的全部 token（abort 整体回放）
        d = src.read()
        if d is not None:
            pulled.append(d)
        if d is not None and name.startswith("verb") and d.text == "*":
            d = src.read()  # \verb* 星号吃掉（v1 裸位判定，无 ws_skip）
            if d is not None:
                pulled.append(d)
        if name == "lstinline":
            # v1 此处 ws_skip（全空白含 \n\n）非 ws_skip_arg
            while d is not None and d.kind in ("space", "eol_par"):
                d = src.read()
                if d is not None:
                    pulled.append(d)
            if d is not None and d.kind == "other" and d.text == "[":
                hit = self._collect_group(src, d, brace=False)
                if hit is not None:
                    inner, closer = hit
                    pulled.extend(inner)
                    pulled.append(closer)
                    d = self._read_skipws(src, pulled)
                    if d is not None:
                        pulled.append(d)
                # hit None：组 token 已回吐且仍在 pulled——``[`` 落定界符路径
        if d is None or d.kind in ("space", "eol_par"):
            src.unread(pulled)
            self._rappend_tok(t)
            return
        if d.kind == "lbrace":
            # \verb{...} 配对形：字节级逐字配对（``%`` 不作注释，v1
            # match_brace(verbatim=True) 同）——token 收集会被 ``%``
            # 吃掉闭括号直排 EOF
            e = match_brace(self.file_texts[fid], d.pos[1], verbatim=True)
            if e is None:
                src.unread(pulled)  # 未消费任何组 token——全量回放（含 d）
                self._rappend_tok(t)
                return
            self._cover_gap(fid, t.pos[1])
            vspan = self._cover_to(fid, e)
            self._rappend_ph(
                self._ph(PhType.VERB, self.vt.slice(vspan.start, vspan.end)),
                vspan,
            )
            self._skip_past(src, fid, e)
            return
        # 定界符 = token 的文件首字符（cs → ``\``；多字符 token 取首字符，
        # 与 v1 单字符 ``d = tex[k]`` 语义一致）
        delim = self.file_texts[fid][d.pos[1]]
        ftext = self.file_texts[fid]
        close = ftext.find(delim, d.pos[1] + 1)
        eol = ftext.find("\n", d.pos[1] + 1)
        if close < 0 or (0 <= eol < close):
            cons0 = self._cons(fid)
            vspan = self._cover_to(fid, b)
            self._rappend(
                self._gap_surface(fid, cons0, t.pos[1]) + "\\" + name,
                self.vt.slice(vspan.start, vspan.end),
                vspan,
            )
            src.unread(pulled)
            return
        end = close + 1
        self._cover_gap(fid, t.pos[1])
        vspan = self._cover_to(fid, end)
        self._rappend_ph(
            self._ph(PhType.VERB, self.vt.slice(vspan.start, vspan.end)),
            vspan,
        )
        self._skip_past(src, fid, end)

    def _skip_past(self, src: TokenSource, fid: int, end: int) -> None:
        """Resync ``fid`` 源到 ``end``——raw 区段不经 token 流（契约 §4）。

        调 ``gullet.skip_past`` 真 API（tokbuf 残骸剔除 + 栈深找 fid +
        i 只前进）；``_ListSource`` 丢队首已覆盖 token（子扫同源语义）。
        失败时 gullet 已记 ``verb_resync_failed``，分段器不退化——位置
        已对齐，后续 token 照常（与今日无 verb 处理等价）。
        """
        src.skip_past(fid, end)

    def _tail_scan_end(self, fid: int, pos: int, kind: str) -> int | None:
        r"""``pos`` 起的非文本尾参字节扫 → end；形不合 → None。

        ``kind`` ∈ ``_TAIL_RX``：``dimen``/``rule``/``font``/``assign``
        （通用 ``=ATOM``——``\foo=2pt`` 的赋值形对一切未知名生效）。
        只认 ``[ \\t]`` 间隙——换行分隔的操作数不进覆盖（语料未见，
        par 边界语义不跨）。
        """
        m = _TAIL_RX[kind].match(self.file_texts[fid], pos)
        return m.end() if m is not None and m.end() > pos else None

    def _tikz_tail_end(  # noqa: C901, PLR0911, PLR0912 — 字节级 ; 定界扫：深度/注释/终止判定逐字符平铺
        self, fid: int, pos: int
    ) -> int | None:
        r"""裸 ``\tikz <path>;`` 语句的 ``;`` 定界尾扫 → end；非路径形 → None。

        ``\tikz`` 的 argspec ``o o m`` 认不出无 ``[``/``{`` 起头的裸
        路径形（``\tikz \draw (0,0) -- (1,1);``）——整句 path 裸进
        chunk 被当正文翻译（R8）。首非空字符须是 ``\\``/``(``/``[``
        （path 起点族；``{`` 起头是 ``\tikz{...}`` 短形归 argspec
        ``m`` 参，散文里 ``\tikz``+文字的误伤面也压掉）；之后 ``{..}``/
        ``[..]`` 组内、``\\X`` 转义、``%`` 注释内的 ``;`` 都不算界；
        ``\\end{``/``\n\n``（par 界）/EOF 即中止回落旧路。
        """
        tex = self.file_texts[fid]
        n = len(tex)
        i = pos
        while i < n and tex[i] in " \t":
            i += 1
        if i >= n or tex[i] not in "\\([":
            return None
        depth = 0
        while i < n:
            c = tex[i]
            if c == "\\":
                if tex.startswith("\\end{", i):
                    return None
                i += 2
                continue
            if c == "%":
                k = tex.find("\n", i)
                if k < 0:
                    return None
                i = k + 1
                continue
            if c == "\n":
                k = i + 1
                while k < n and tex[k] in " \t\r":
                    k += 1
                if k >= n or tex[k] == "\n":
                    return None
                i += 1
                continue
            if c in "{[":
                depth += 1
            elif c in "}]":
                if depth == 0:
                    return None  # 深度外闭括 = 越过所在参数界（in_arg 调用）
                depth -= 1
            elif c == ";" and depth == 0:
                return i + 1
            i += 1
        return None
