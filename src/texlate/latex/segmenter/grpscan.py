r"""``latex/segmenter`` 子模块——god-class 机械拆分（行为零变）：``_grp_*`` 组内 surface 扫描引擎。"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    NamedTuple,
    cast,
)

import texlate.latex.tables as _tables
from texlate.latex.gullet import (
    Arg,
)
from texlate.latex.model import (
    PhType,
    ScanWarning,
)
from texlate.latex.mouth import (
    Tok,
)
from texlate.latex.tables import (
    BOUNDARY_NAMES,
    BOUNDARY_TAIL,
    CHUNK_ARG_NAMES,
    CHUNK_ARG_SPEC,
    COND_RX,
    DIMEN_TAIL_KIND,
    FILENAME_CHARS,
    INPUT_SCAN_CMDS,
    MAX_GEN,
    PAIR_BLOCK_ALL,
    PAIR_BLOCK_CMDS,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    TRANSPARENT_HEAD_SPEC,
)

from ._common import (
    _ACCENT_SLOTS,
    _ENV_CS,
    _GRP_SCAN_CAP,
    _HYPERREF_SLOTS,
    _MATH_OPEN_CS,
    _PROTECT_TYP,
    _TAIL_RX,
    _VERB_LIKE,
    _accent_cs,
    _chunk_spec_cached,
    _cite_ref_type,
    _cond_slots,
    _env_ph_type,
    _gspec_elem,
    _inline_lit_cs,
    _pend_call_slots,
    _prose_arg_hit,
    _slot_elem,
    _verb_delim_tok,
    _WSpec,
)

if TYPE_CHECKING:
    from texlate.latex.segmenter import Segmenter

r"""``Segmenter`` 组内 surface 收拢引擎——``_close_group``/``_grp_pending`` 的
组内对价（``_grp_*`` 族）；流侧 pend/absorb 机械在 ``pending.py``。"""

_IMPORT2 = ("import", "subimport")


class _PendRem(NamedTuple):
    r"""``_grp_spec_walk`` 组末余量——跨界待绑位描述（``_absorb_spec`` 消费）。

    ``spec``/``cont`` = 未走 gullet ``Arg`` 尾段与首参续扫态
    （``("delim",滑窗尾列)``/``("e-arg",)``/``("grp",定界族,残深)``）；
    ``ka_slots``/``ka_cont``/``ka`` = 体尾 key-arg 剩余槽、首槽 ``[`` 组
    续收态与告警名（``""`` = 无）。
    """

    spec: list
    cont: tuple | None
    ka_slots: list[str]
    ka_cont: tuple | None
    ka: str


class _GrpScan:
    def _grp_delim_body_end(
        self: Segmenter, toks: list[Tok], i: int, j: int
    ) -> int | None:
        r"""``toks[j]`` = 定界 token 的逐字闭界扫描 → j_end；未闭 → None。

        ``_handle_verb``/``_protect_cs`` 定界支的组内镜像：cs 定界
        （``\\``）由下一 cs token 闭合，其余按 ``kind+text`` 同符配对；
        ``eol_par`` 与盖了源换行的 space token 是 EOL 上限（W9 同义——
        定界搜索不过行）。
        """
        d = toks[j]
        n = len(toks)
        k = j + 1
        while k < n and k - i < _GRP_SCAN_CAP:
            x = toks[k]
            if x.kind == "eol_par" or (
                x.kind == "space"
                and "\n" in self.file_texts[x.pos[0]][x.pos[1] : x.pos[2]]
            ):
                return None
            if d.kind == "cs":
                if x.kind == "cs":
                    return k + 1
            elif x.kind == d.kind and x.text == d.text:
                return k + 1
            k += 1
        return None

    def _grp_verb_end(self: Segmenter, toks: list[Tok], i: int) -> int | None:
        r"""组内 ``\verb|..|``/``\verb*``/``\lstinline[opt]|..|``/``{..}`` → j_end。

        ``_handle_verb`` 的组内镜像（组内无文件字节可扫——定界/配对全在
        token 列上）：``verb*`` 星与 ``lstinline`` 的 ws+``[opt]`` 前缀先吃；
        定界 token 为 space/eol_par/EOF → ``None``（逐字回落）。``{..}``
        配对形走 ``_grp_bal``——``\\}``/``\\{`` 是 cs token 不计深，
        ``%`` 不成 token，配对语义与字节版 verbatim 一致。
        """
        n = len(toks)
        name = toks[i].text
        j = i + 1
        if name.startswith("verb") and j < n and toks[j].text == "*":
            j += 1
        if name == "lstinline":
            j = self._grp_skip_ws(toks, j)
            if j < n and toks[j].kind == "other" and toks[j].text == "[":
                e = self._grp_bal(toks, j, brace=False)
                if e is not None:
                    j = self._grp_skip_ws(toks, e)
        if j >= n or toks[j].kind in ("space", "eol_par"):
            return None
        if toks[j].kind == "lbrace":
            return self._grp_bal(toks, j, brace=True)
        return self._grp_delim_body_end(toks, i, j)

    @staticmethod
    def _grp_open_tail(
        toks: list[Tok], i: int, *, brace: bool
    ) -> tuple[str, bool, int] | None:
        r"""``_grp_bal`` 否决的细分 → 跨界续扫态 / ``None``（失配终止）。

        同口径重数深度：``eol_par`` 穿组 → ``None``（参扫终界同规）；
        深度未归零走到列尾 = 组真跨界 → ``("grp", 定界族, 残深)`` 交
        ``_absorb_grp_tail`` 流侧续收（``[..]`` 版式组在 def 体内不需
        配平——``\vv{pre \foo[ww}`` 实形，``{`` 组同理备齐）。
        """
        depth = 0
        for x in toks[i:]:
            if x.kind == "eol_par":
                return None
            if brace:
                if x.kind == "lbrace":
                    depth += 1
                elif x.kind == "rbrace":
                    depth -= 1
            elif x.kind == "other":
                if x.text == "[":
                    depth += 1
                elif x.text == "]":
                    depth -= 1
            if depth == 0:
                return None
        return ("grp", brace, depth) if depth else None

    def _grp_spec_walk(
        self: Segmenter, toks: list[Tok], i: int, m: object
    ) -> tuple[int, list[tuple[int, int, int]], _PendRem | None]:
        r"""Opaque/math 宏 ``m.spec`` + 体尾 key-arg 槽的组内位序走参。

        → ``(参末位, 散文候选界列, 跨界余量)``。``_handle_opaque_macro``+
        ``_args_tok`` 的组内 toks 对价。走参本体 = ``_walk_spec_toks``
        （gullet ``Arg`` 经 ``_gspec_elem`` 归一）——``m``/``o`` 组未闭
        承 ``_grp_open_tail`` 跨界续扫态（``cont_ok``）。体尾 key-arg cs
        （``\def\r{\ref}`` 形）续按 ``_pend_call_slots`` 槽形吸调用点
        ``{key}``——同机第二段走参（ka-``o`` 未闭承续收态、``s``/``m``
        失配即终止不追）。

        余量 ``None`` = 调用在组内完结/失配终止；``_PendRem`` = toks 走尽
        而调用未竟（``_grp_pending`` 臂消费）：``spec`` 未走 ``Arg`` 尾段
        （``e`` 残件只剩未吃定界符）、``cont`` 首参续扫态、``ka_slots``/
        ``ka_cont``/``ka`` = key-arg 剩余槽、``[`` 组续收态与告警名——
        流侧对价 = ``_absorb_spec`` + ``_absorb_slots``。
        """
        ka = self._keyarg_tail(m)
        ka_slots = _pend_call_slots(ka) if ka is not None else []
        spec = list(getattr(m, "spec", []))
        res = self._walk_spec_toks(toks, i + 1, [_gspec_elem(a) for a in spec])
        end, cand = res.end, res.cand
        rem: _PendRem | None = None
        if res.rem is not None:
            if res.e_rest is not None:
                resid = Arg(
                    "e", delim=[Tok("other", c, (-1, -1, -1)) for c in res.e_rest]
                )
                rem = _PendRem(
                    [resid, *spec[res.rem + 1 :]],
                    res.cont,
                    ka_slots,
                    None,
                    ka or "",
                )
            else:
                rem = _PendRem(spec[res.rem :], res.cont, ka_slots, None, ka or "")
        elif ka is not None:
            kres = self._walk_spec_toks(
                toks,
                end,
                [_slot_elem(s, cont_ok=s == "o") for s in ka_slots],
            )
            end = kres.end
            if kres.rem is not None:
                rem = _PendRem([], None, ka_slots[kres.rem :], kres.cont, ka)
        return end, cand, rem

    def _grp_opaque_args(
        self: Segmenter, toks: list[Tok], i: int, name: str, m: object
    ) -> tuple[int, list[tuple[int, int]]]:
        r"""Opaque/math 宏 ``m.spec`` 的组内位序走参 → ``(参末位, 散文参界列)``。

        走参本体 = ``_grp_spec_walk``（跨界余量归 ``_grp_pending`` 臂，组内
        surface 只见完结调用——``_grp_scan`` 在收组后对完整 toks 重走）。
        散文参界 = 实消费 ``{``/``[``-open 组参过判据的 ``(开位, 闭后位)``
        列——``_prose_arg_hit`` 单源管线（``_opaque_arg_prose`` 的组内
        对价）：``_SWALLOW/_DEAD`` 名闸 + ``_DEAD_TAIL`` 首参限 +
        keyval/逗号名单/裸键列形状门 + 词链判据；``e``/``u``/单 token 参
        无散文槽位（主流 ``a.fs``/``a.cs`` 门同界）。
        """
        end, cand, _rem = self._grp_spec_walk(toks, i, m)
        return end, [
            (a0, a1)
            for nth2, a0, a1 in cand
            if _prose_arg_hit(name, nth2, self._grp_surfs(toks[a0 + 1 : a1 - 1]))
        ]

    def _group_surface(self: Segmenter) -> list[str] | None:
        r"""组成员 token → surface 段：结构命令再生保护段产 ph。

        展开表面里的 ``\\begin/\\end{env}``（math/verb/protected 整段、
        其余 tag）、``$…$``/``\\[…\\]``/``\\(…\\)``、cite/ref/PROTECT 族整
        调用、``\\if`` 族——ph 体 = 展开表面切片（vtex 无对应字节，
        identity 由本组 ``[[EXPAND]]``/``ph_map[CHUNK]`` 兜底）。
        ``eol_par`` = 虚拟分段符：切段边界、自身不产字节（§3）。
        返回 ``list[str]``——段界在 ``_close_group`` 重拼为同一 run 的
        ``\\n\\n`` 段内分隔（全或无发射：逐段冲刷会把空 ident 尾段交给
        literal 路径丢字节——``\\parbox`` 参内 ``\\par`` 切断的
        ``}``/``\\end{env}`` 蒸发，hep-ph/9910403 ``\\@iiiparbox``
        runaway 族）。

        返回 ``None`` = 整组 bail（``_close_group`` 转 literal 兜底）：
        组内 ``\\begin{保护族 env}``/env_begin 宏端点找不到配对
        ``\\end``——物质化一个永无配对的开 tag 会把后续主流
        ``\\end`` 变 stray、译文面留未闭环境（R7/J3，``\\bea``=
        ``\\begin{eqnarray}\\relax`` 形）。
        """
        return self._grp_scan(self._open_toks)

    def _grp_emit_carved(  # noqa: PLR0913, PLR0917 — carve 发射面（输出/区间/切列/深度/警标）七件原位
        self: Segmenter,
        out: list[str],
        toks: list[Tok],
        i: int,
        j2: int,
        spans: list[tuple[int, int]],
        depth: int,
        warn_tag: str,
    ) -> int:
        r"""散文参界列 carve 发射 → 新 ``i``（= ``j2``）。

        ``_grp_scan`` opaque/探针两臂的共享末段（``_walk_spec_toks`` 同款
        单源化）：``spans`` 非空而 ``depth`` 触底 ``MAX_GEN`` →
        ``gen_overflow`` 告警 + 参维持 opaque；否则逐散文参 ``_grp_scan``
        递归子扫（``None`` = 参内保护族 env 无配对——该参维持 opaque），
        参间结构段与调用尾段罩 ``[[CMD]]``。
        """
        if spans and depth >= MAX_GEN:
            self.state.warnings.append(
                ScanWarning("gen_overflow", len(self.vt), warn_tag)
            )
            spans = []
        cur = i
        for a0, a1 in spans:
            sub = self._grp_scan(toks[a0 + 1 : a1 - 1], depth + 1)
            if sub is None:
                continue  # 参内保护族 env 无配对——该参维持 opaque
            self._cat_surf(
                out,
                self._grp_ph(PhType.CMD, self._grp_surfs(toks[cur : a0 + 1])),
            )
            self._cat_surf(out, "\n\n".join(sub))
            cur = a1 - 1  # ``}``/``]`` 随下段结构进 CMD（主流同位）
        self._cat_surf(out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[cur:j2])))
        return j2

    def _grp_scan(  # noqa: C901, PLR0912, PLR0915 — 组内保护段分派平铺（§3 再生保护段）
        self: Segmenter, toks: list[Tok], depth: int = 0
    ) -> list[str] | None:
        r"""``_group_surface`` 的 toks 参数化引擎——探针散文参子扫复用。

        ``depth`` = 散文参递归代数：``MAX_GEN`` 触底即停挖、参维持
        ``[[CMD]]`` 并记 ``gen_overflow``（字节臂 ``self.gen`` 回压同义——
        宁可不译也不超代数）。
        """
        segs: list[str] = []
        out: list[str] = []
        i, n = 0, len(toks)
        while i < n:
            t = toks[i]
            if t.kind == "eol_par":
                segs.append("".join(out))
                out = []
                i += 1
                continue
            if t.kind == "mathshift":
                j = self._grp_math_end(toks, i)
                if j is None:
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                self._cat_surf(
                    out, self._grp_ph(PhType.MATH, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            if t.kind != "cs":
                self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            name = t.text
            # 分派行序镜像 _dispatch：verb 定界形（row1）→ env tag → 定界
            # 数学 → cite/ref（共享谓词）→ PROTECT → href/hyperref →
            # input 族 → \if 族 → env 宏端点 → 默认逐字
            if name in _VERB_LIKE:
                j = self._grp_verb_end(toks, i)
                if j is None:
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                self._cat_surf(
                    out, self._grp_ph(PhType.VERB, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            if name in _ENV_CS:
                hit = self._grp_envtag(toks, i)
                if hit is None:
                    self._cat_surf(
                        out, self._grp_ph(PhType.ENVTAG, self._tok_surface(t))
                    )
                    i += 1
                    continue
                env, j = hit
                if name == "begin":
                    reg = self.state.macros.lookup_env(env)
                    ae = self._argspec_env(env, reg)
                    typ = _env_ph_type(env, ae, reg)
                    if typ is not None:
                        e = self._grp_find_env_end(toks, j, env)
                        if e is not None:
                            self._cat_surf(
                                out, self._grp_ph(typ, self._grp_surfs(toks[i:e]))
                            )
                            i = e
                            continue
                        # 保护族 env 开 tag 无配对 \end——整组回 literal
                        # （R7/J3：\bea=\begin{eqnarray}\relax 形）
                        return None
                    # ENVTAG 界延到环境尾参（主流 _eat_env_args 同规）——
                    # preamble {lRLc}/版式 [opt] 不裸进 surface
                    j = self._grp_env_args_end(toks, j, env, reg, ae)
                self._cat_surf(
                    out, self._grp_ph(PhType.ENVTAG, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            if name in _MATH_OPEN_CS:
                j = self._grp_delim_end(toks, i, "]" if name == "[" else ")")
                if j is not None:
                    self._cat_surf(
                        out, self._grp_ph(PhType.MATH, self._grp_surfs(toks[i:j]))
                    )
                    i = j
                    continue
                self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            fam = _cite_ref_type(name)
            if fam is not None:
                j = self._grp_call_end(toks, i, self._cite_ref_mand(name))
                self._cat_surf(out, self._grp_ph(fam, self._grp_surfs(toks[i:j])))
                i = j
                continue
            if name in PROTECT_NAMES:
                j = self._grp_call_end(toks, i, 2 if name == "inputminted" else 1)
                if name in ("url", "path"):
                    # \url<delim>…<delim> 定界形兜底（主版 verbatim 支同判据）
                    k2 = i + 1
                    if k2 < n and toks[k2].kind == "other" and toks[k2].text == "*":
                        k2 += 1
                    if j == k2 and k2 < n and _verb_delim_tok(toks[k2]):
                        e2 = self._grp_delim_body_end(toks, i, k2)
                        if e2 is not None:
                            j = e2
                self._cat_surf(
                    out,
                    self._grp_ph(
                        _PROTECT_TYP.get(name, PhType.CMD),
                        self._grp_surfs(toks[i:j]),
                    ),
                )
                i = j
                continue
            if name == "href":
                # \href{url}{text}：命令名+间隙留 surface，{url} 组 →
                # [[HREF]]；{text} 组 token 留 surface 续扫（主版 _handle_href
                # 同形——花括号随文本进 surface）
                k = i + 1
                while k < n and toks[k].kind == "space":
                    k += 1
                e = (
                    self._grp_bal(toks, k, brace=True)
                    if k < n and toks[k].kind == "lbrace"
                    else None
                )
                if e is None:
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                self._cat_surf(out, self._grp_surfs(toks[i:k]))
                self._cat_surf(
                    out, self._grp_ph(PhType.HREF, self._grp_surfs(toks[k:e]))
                )
                i = e
                continue
            if name == "hyperref":
                # argspec m m（key,text）的组内对价：首个参组（{key} 或
                # [label]）随命令进 [[CMD]]，{text} 余参留 surface 续扫——
                # 走参 = ``["s","e"]`` 槽列（``_pend_spec_of`` hyperref 行同形）
                j = self._walk_spec_toks(
                    toks, i + 1, [_slot_elem(s) for s in _HYPERREF_SLOTS]
                ).end
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            if COND_RX.match(name):
                # 名/表达式槽 ``{..}`` 并入 [[COND]]（主流 ``_handle_cond``
                # 的 ``_COND_GROUP_ARGS`` 组内对价）——``\iftoggle{tag}`` 的
                # ``{tag}`` 机器槽留 surface 被译；``{T}{F}`` 支不在吸收数
                # 内，留 surface 续扫照译。表外名无槽形（``{`` 是分支散文）。
                # 走参 = ``["m"]×nslots`` 槽列（``_pend_spec_of`` COND 行同形）
                j = self._walk_spec_toks(
                    toks, i + 1, [_slot_elem(s) for s in _cond_slots(name)]
                ).end
                self._cat_surf(
                    out, self._grp_ph(PhType.COND, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            if name in INPUT_SCAN_CMDS:
                # \input 族漏网（主版 row10）：{file}/import 双参/裸名三形
                k = i + 1
                while k < n and toks[k].kind == "space":
                    k += 1
                if (
                    k < n
                    and toks[k].kind in ("letter", "other")
                    and all(c in FILENAME_CHARS for c in toks[k].text)
                ):
                    j = k + 1  # 裸文件名形：连吃 FILENAME_CHARS 文本 token
                    while (
                        j < n
                        and toks[j].kind in ("letter", "other")
                        and all(c in FILENAME_CHARS for c in toks[j].text)
                    ):
                        j += 1
                elif (
                    k < n
                    and toks[k].kind in ("letter", "other")
                    and toks[k].text == '"'
                ):
                    # 引号裸名 \input"a b.tex" —— 含闭引号整吞进 [[CMD]]，
                    # 缺席吞到流尾（否则文件名漏成散文）
                    j = k + 1
                    while j < n and not (
                        toks[j].kind in ("letter", "other") and toks[j].text == '"'
                    ):
                        j += 1
                    if j < n:
                        j += 1
                elif k < n and toks[k].kind == "cs":
                    # ``\input \cs`` 动态文件名——cs 随命令进 [[CMD]]
                    # （主流 else 臂同规，R4）；input_dyn 记闭包 fail-open 信号
                    self.state.input_dyn += 1
                    j = k + 1
                else:
                    j = self._grp_call_end(toks, i, 2 if name in _IMPORT2 else 1)
                    if any(tk.kind == "cs" for tk in toks[k:j]):
                        # ``\input{\cs}``/``\import{\csdir}{f}`` 组内动态名
                        self.state.input_dyn += 1
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            em = self._grp_env_macro(t)
            if em is not None:
                ek, eenv = em
                reg2 = self.state.macros.lookup_env(eenv)
                ae2 = self._argspec_env(eenv, reg2) if ek == "env_begin" else None
                typ = _env_ph_type(eenv, ae2, reg2) if ek == "env_begin" else None
                e = (
                    self._grp_find_env_end(toks, i + 1, eenv)
                    if typ is not None
                    else None
                )
                if e is not None:
                    # e 非 None ⟹ typ 非 None（e 仅在 typ 非 None 时求解）
                    self._cat_surf(
                        out,
                        self._grp_ph(cast("PhType", typ), self._grp_surfs(toks[i:e])),
                    )
                    i = e
                    continue
                if ek == "env_begin" and typ is not None:
                    # 同上：保护族 env 开端点无配对——整组回 literal（R7/J3）
                    return None
                j2 = i + 1
                if ek == "env_begin":
                    # 宏端点同吃环境尾参（\bea{c} 的 preamble 不裸进 surface）
                    j2 = self._grp_env_args_end(toks, j2, eenv, reg2, ae2)
                self._cat_surf(
                    out, self._grp_ph(PhType.ENVTAG, self._grp_surfs(toks[i:j2]))
                )
                i = j2
                continue
            if name in CHUNK_ARG_NAMES:
                # ``\section[opt]{arg}`` 组内对价（``_handle_chunk_arg`` 镜像）：
                # ``*``?+可译位前头参随名进 ``[[CMD]]``，``{arg}`` 组整体留
                # surface 续扫（B 臂无独立 chunk piece——参留主流即可见同义，
                # 名不再裸落译文面）。可译槽缺席/非 ``{..}`` 组 → 名逐字回落
                # （主流 bail→``_rappend_tok`` 同规）；空参 → 整调用逐字。
                spec_s, tidx = CHUNK_ARG_SPEC.get(name, ("om", 1))
                # ``*``? 前缀 = ``star`` 走参元（ws 前跳——组面 ``*`` 可隔空，
                # 与槽 ``s`` 的 ws=False 原位判不同，原判保留）
                k = self._walk_spec_toks(toks, i + 1, [_WSpec("star")]).end
                j2 = self._grp_spec_args_end(
                    toks, k, _chunk_spec_cached(spec_s)[:tidx], (), None
                )
                k = j2
                while k < n and toks[k].kind == "space":
                    k += 1
                e2 = (
                    self._grp_bal(toks, k, brace=True)
                    if k < n and toks[k].kind == "lbrace"
                    else None
                )
                if e2 is None:
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                if not self._grp_surfs(toks[k + 1 : e2 - 1]).strip():
                    self._cat_surf(out, self._grp_surfs(toks[i:e2]))
                    i = e2
                    continue
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:k]))
                )
                i = k
                continue
            if name in PROTECT_BLOCK_NAMES:
                # ``\author[opt]{..}`` 整块 → ``[[AUTHOR]]``——abort（``{`` 未
                # 随只护 cs 本体）与 keyval 续组语义在 ``_grp_protect_block_end``
                e = self._grp_protect_block_end(toks, i)
                self._cat_surf(
                    out, self._grp_ph(PhType.AUTHOR, self._grp_surfs(toks[i:e]))
                )
                i = e
                continue
            if name in BOUNDARY_NAMES:
                # 组内 BOUNDARY_TAIL/dimen 尾参（顶层 _handle_boundary 对价，
                # in_arg=COMMAND 整调用保护）：结构尾参 ``{2mm}``/``[o]``、裸
                # 操作数 ``\vskip 3pt`` 随命令进 [[CMD]]——裸落 surface 会被
                # 翻译 ``mm``/``pt``（illegal_unit，loop1 slots①）。
                # spec 缺席不预吃 ``[opt]``——``\item[label]`` 的 label 是
                # 可译文本须留 surface（主流同规）。
                spec = BOUNDARY_TAIL.get(name)
                j = i + 1
                kind = DIMEN_TAIL_KIND.get(name)
                if kind is not None:
                    e2 = self._grp_tail_end(toks, j, _TAIL_RX[kind])
                    if e2 is not None:
                        j = e2
                elif spec is not None:
                    # 位序走参——``n`` 槽认裸 cs token（``\setlength\parskip``
                    # 组内形）；旧 ``_grp_call_end`` 只数 ``{..}`` 组，裸名形
                    # 漏 ``{4pt}`` 进 surface（illegal_unit 波实证：
                    # 1608.02270 ``\setlength\arraycolsep{2pt}`` 34 处残留）
                    j = self._grp_spec_args_end(toks, i + 1, spec, (), None)
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            # —— 以下各行镜像 _dispatch 行 13–19 的组内对价（非文本槽位不
            #    裸进 surface——loop1 slots 修复的组内侧）——
            if name == "\\":
                j2 = self._grp_bsbs(toks, i)
                if j2 is not None:
                    self._cat_surf(
                        out,
                        self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j2])),
                    )
                    i = j2
                    continue
                self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            if name in TRANSPARENT_HEAD_SPEC:
                # \textcolor{red}{text}：头参进 [[CMD]]，{text} 留 surface
                j2 = self._grp_spec_args_end(
                    toks,
                    i + 1,
                    TRANSPARENT_HEAD_SPEC[name],
                    (),
                    None,
                    allow_single_token=False,
                )
                if j2 > i + 1:
                    self._cat_surf(
                        out,
                        self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j2])),
                    )
                    i = j2
                    continue
                self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            kind2 = DIMEN_TAIL_KIND.get(name)
            j2 = self._grp_tail_end(
                toks, i + 1, _TAIL_RX[kind2 if kind2 is not None else "assign"]
            )
            if j2 is not None:
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j2]))
                )
                i = j2
                continue
            if _accent_cs(name):
                # accent 单参保护（主流 _handle_accent 对价）：{x} 组或
                # 单 token 参随 cs 进 [[CMD]]——参字母裸落 surface 会被
                # 翻译（0806.3144 同族，花括号形前由探针兜底、裸参形是洞）。
                # 走参 = ``["a"]`` 槽列（``_pend_spec_of`` accent 行同形）
                j = self._walk_spec_toks(
                    toks, i + 1, [_slot_elem(s) for s in _ACCENT_SLOTS]
                ).end
                if j > i + 1:
                    self._cat_surf(
                        out,
                        self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j])),
                    )
                    i = j
                    continue
                self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            if _inline_lit_cs(name):
                # 行内字面（主流 row19 对价）：符号/品牌/字体开关/单字符
                # 非字母命令零参逐字——``\5``/``\_`` 不得被下游 argspec
                # 假条目/探针吃参（参留 surface = 主流可见同义）
                if name == "$":
                    # ``\$`` 组内同规：surface ph 化防裸 ``$`` 漏进可译面
                    self._cat_surf(out, self._grp_ph(PhType.CMD, self._tok_surface(t)))
                else:
                    self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            # 宏表登记名决议（env-macro 行只截 env_begin/env_end 后此处
            # 再查同表）：opaque/math 宏行走参、其余登记名落探针——
            # ``m is None`` 才进 argspec（主流闸同规）
            m2 = self.state.macros.resolve(self.state.macros.lookup(name))
            if getattr(m2, "kind", "") in ("opaque", "math"):
                # opaque/math 宏（主流 row18 ``_handle_opaque_macro`` 对价）：
                # ``m.spec`` 位序走参整调用罩 ``[[CMD]]``——探针 ``[o]+{m}×6``
                # 形把 spec 外 ``{..}`` 组误吸进保护面（登记宏 nargs 越界
                # 过吸）。``{``/``[``-open 组参过散文门抠出子扫渲 surface
                # （主流散文挖掘同型）；体尾 key-arg 调用点 ``{key}`` 同罩。
                # 宏行在 pair-block 行之前与主流行序同位。
                j2, spans = self._grp_opaque_args(toks, i, name, m2)
                i = self._grp_emit_carved(
                    out, toks, i, j2, spans, depth, f"grp-opaque:{name}"
                )
                continue
            if name in PAIR_BLOCK_ALL:
                # cs 对界块（主流 row18b 对价）：组内有配对闭 cs → 整段
                # [[ENV]]（B 臂无独立 chunk piece——体表面随 ph 保护即同
                # 义）；孤闭 cs → [[CMD]]；开 cs 组内无配对 → 不落本行、
                # 续走 argspec/探针（未闭合按未知 cs 保守处理，主流
                # unclosed→unknown 同规）
                if name not in PAIR_BLOCK_CMDS:
                    self._cat_surf(out, self._grp_ph(PhType.CMD, self._tok_surface(t)))
                    i += 1
                    continue
                e3 = self._grp_pair_end(toks, i + 1, name, PAIR_BLOCK_CMDS[name])
                if e3 is not None:
                    self._cat_surf(
                        out,
                        self._grp_ph(PhType.ENV, self._grp_surfs(toks[i:e3])),
                    )
                    i = e3
                    continue
            # 宏表登记名不吃 argspec（主流 ``m is None`` 闸的组内对价——
            # env-macro 行只截 env_begin/env_end，opaque/math 宏上行已兜，
            # 其余登记名落探针同规）
            e2 = (
                _tables.argspec_lookup(name, cast("set[str]", self.state.pkgs))
                if m2 is None
                else None
            )
            if e2 is not None:
                policy = e2.policy
                if policy in ("literal", "transparent"):
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                spec2 = _chunk_spec_cached(e2.signature)
                if policy == "chunk-arg":
                    j2 = self._grp_spec_args_end(toks, i + 1, spec2, e2.arg_roles, None)
                    if j2 > i + 1:
                        self._cat_surf(
                            out,
                            self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j2])),
                        )
                        i = j2
                        continue
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                # protect/key/verbatim/boundary → 整调用 [[CMD]]
                if name == "tikz" and policy in ("protect", "key"):
                    # 裸 ``\tikz <path>;`` 的组内对价（R8）——签名
                    # ``o o m`` 同主流一样够不着路径形
                    j3 = self._grp_tikz_end(toks, i)
                    if j3 is not None:
                        self._cat_surf(
                            out,
                            self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j3])),
                        )
                        i = j3
                        continue
                mand = sum(1 for s in spec2 if s.kind in ("m", "v", "n"))
                j2 = self._grp_call_end(toks, i, mand)
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j2]))
                )
                i = j2
                continue
            # 未知探针（主流 row19 对价）：``[opt]``? + ``{m}``×6 → [[CMD]]；
            # 散文 ``{..}`` 参抠出 CMD 覆盖、``_grp_scan`` 递归子扫渲进
            # surface（``_handle_unknown_cs`` 散文挖掘的组内同型——宏名/
            # 非散文参/散文参两侧花括号所在结构段仍 CMD 原文，嵌套 cs 经
            # 子扫分派照常保护）。
            res = self._grp_probe_end(toks, i)
            if res is not None:
                spans = self._grp_probe_prose_args(toks, res, name)
                i = self._grp_emit_carved(
                    out, toks, i, res.end, spans, depth, f"grp-probe:{name}"
                )
                continue
            self._cat_surf(out, self._tok_surface(t))
            i += 1
        segs.append("".join(out))
        return segs
