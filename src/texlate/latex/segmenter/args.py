r"""``latex/segmenter`` 子模块——god-class 机械拆分（行为零变）。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import texlate.latex.tables as _tables
from texlate.latex.gullet import (
    MacroDef,
    _tok_eq,
)
from texlate.latex.model import (
    ArgSpec,
    PhType,
    Piece,
    PieceKind,
    ScanWarning,
    Span,
    match_brace,
)
from texlate.latex.tables import (
    BOUNDARY_TAIL,
    CHUNK_ARG_SPEC,
    CHUNK_MAX,
    DIMEN_TAIL_KIND,
    FILENAME_CHARS,
    MAX_GEN,
    TRANSPARENT_HEAD_SPEC,
    strip_fname_quotes,
)

from ._common import (
    _ARG_COMMENT_RX,
    _BSBS_OPT_RX,
    _COND_GROUP_ARGS,
    _DEAD_ARG_NAMES,
    _DEAD_TAIL_NAMES,
    _MATH_TEXTARG,
    _PROTECT_TYP,
    _SWALLOW_ARG_NAMES,
    _TAIL_CAP,
    TokenSource,
    _ArgTok,
    _chunk_spec_cached,
    _cite_ref_type,
    _kv_list_shaped,
    _ListSource,
    _pend_call_slots,
    _pick_cut,
    _prose_text_hit,
    _verb_delim_tok,
)
from .grpscan import (
    _IMPORT2,
)

if TYPE_CHECKING:
    from texlate.latex.model import ArgspecEntry
    from texlate.latex.mouth import (
        Tok,
    )

r"""``Segmenter`` 参数读取/保护调用/各 handler/argspec 发射。"""

# ``\cite{15-20}`` 把区间当键写（W90）——逗号项中纯数字-数字形即误植，
# ``smith-2020``/``key-a`` 合法键不中。
_CITE_RANGE_KEY_RX = re.compile(r"\s*\d+\s*-+\s*\d+\s*")

#: protect-block 散文白名单：``\markright``/``\markboth`` 运行头与
#: ``\address``/``\institute``/``\affiliation`` 机构隶属段装的是真散文
#: （界外项「protect-block 第三臂同型蒸发」核销）。``\author`` 不入——
#: ``\and`` 连名过 4 词门会把人名抬进译文面（专名翻译有害 + W56 内嵌
#: 图面）；``\date``/``\email``/``\orcid``/``\recdate``/``\publishedin``
#: 等是日期/标识元数据非散文槽位，词链门天然不中也无需挖。
_PROSE_BLOCK_NAMES = frozenset(
    {"markright", "markboth", "address", "institute", "affiliation"}
)

#: 白名单名的实参位上限——``\markboth{l}{r}`` 双参，其余单参；超限的
#: ``{..}`` 组不是实参，不收（防 ``\markright{h} {散文段落}`` 误吞正文组）。
_PROSE_BLOCK_ARITY = {
    "markright": 1,
    "markboth": 2,
    "address": 1,
    "institute": 1,
    "affiliation": 1,
}

#: 参内块级信号 cs 名——任一出现即判该参为排版体而非数据槽（探针臂
#: ``_arg_body_shaped`` 用）。env 界标/``\item``/节题皆不可能当真参数值。
_BODY_CS_NAMES = frozenset(
    {
        "begin",
        "end",
        "item",
        "section",
        "subsection",
        "subsubsection",
        "paragraph",
        "subparagraph",
        "chapter",
        "part",
    }
)

class _Args:
    # ------------------------------------------------------------ 参数读取（token 版 _args）

    @staticmethod
    def _peek_nonspace(
        src: TokenSource, pulled: list[Tok], *, fid: int | None = None
    ) -> Tok | None:
        r"""拉下一非 space token；跳过的 space token 追加进 ``pulled``。

        ``eol_par``/EOF → None（eol_par 立即回吐——``\\par`` 是不定界参数
        边界，同 ``ws_skip_arg`` 的 par 停语义）。``fid`` 非空时异 fid
        token 同样回吐返 None（``_handle_accent`` 的 fid-only 判据——
        与 ``_pull_cursor.peek`` 的 gen>0 额外闸不同步）。``pulled``
        约定：space token 拉出即失主流——参数命中时其字节在覆盖区间内
        （``pulled`` 并进 ``all_toks`` 或随调用点覆盖），放弃路径必须
        ``src.unread([*pulled, x])`` 全量回放（字节版「pos 停在不匹配
        位、空白由主流重扫」的等价物，否则 ``\\cite{a} more`` 的空格
        从 surface 消失）。
        """
        while True:
            x = src.read()
            if x is None:
                return None
            if x.kind == "space":
                pulled.append(x)
                continue
            if x.kind == "eol_par" or (fid is not None and x.pos[0] != fid):
                src.unread([x])
                return None
            return x

    @staticmethod
    def _read_skipws(src: TokenSource, pulled: list[Tok]) -> Tok | None:
        r"""``ws_skip``（全空白含 ``\n\n``）的 token 版。

        ``\lstinline``/``\import`` 第二参等 v1 用 ``ws_skip`` 而非
        ``ws_skip_arg`` 的位点。读过的 ws token 进 ``pulled``，
        返回首个非空白 token（不 append）。
        """
        while True:
            x = src.read()
            if x is None:
                return None
            if x.kind in ("space", "eol_par"):
                pulled.append(x)
                continue
            return x

    @staticmethod
    def _collect_group(
        src: TokenSource, open_t: Tok, *, brace: bool, fid: int | None = None
    ) -> tuple[list[Tok], Tok] | None:
        r"""``open_t``（lbrace/``[``）之后拉配对组 → ``(inner_toks, closer)``。

        EOF 截断 → 已拉 token（含 open_t）全部回吐、返 None——调用方按
        参数不匹配处理（字节版 ``match_brace`` 返 None 且 ``pos`` 不动
        的等价物）。``eol_par`` 在组内是普通内容 token（``match_brace``
        不判段界），继续收集。组内对价：``_grp_bal``（展开组 token 列
        版——``eol_par`` 即停返 None，规则不同步过对端须双查）。

        ``fid`` 非空时组内逐 token 查 fid——异 fid token 即止：已拉
        token（含异 fid 者）全部回吐、返 None（``_handle_accent`` 的
        fid-only 判据同款；注意是**逐枚**判据非 closer-only——调用方
        只查 closer fid 的门不能换用本参）。

        ``unmatched_open``（``TokenSource`` 契约成员——``_ListSource`` 持
        真集，Gullet 恒 None）：扫到流尽仍未归零时，深度栈上残留的 open
        全是「整流无配对」——配对关系按栈唯一，记入 memo；同 open 再探
        直返（回吐 open_t 与实扫失败同态）。
        """
        dead = src.unmatched_open
        if dead is not None and (open_t.pos, open_t.gen) in dead:
            src.unread([open_t])
            return None
        pulled = [open_t]
        inner: list[Tok] = []
        opens: list[tuple[tuple[int, int, int], int]] = [(open_t.pos, open_t.gen)]
        depth = 1
        while True:
            x = src.read()
            if x is None:
                if dead is not None:
                    dead.update(opens)
                src.unread(pulled)
                return None
            pulled.append(x)
            if fid is not None and x.pos[0] != fid:
                src.unread(pulled)
                return None
            if brace:
                is_open = x.kind == "lbrace"
                is_close = x.kind == "rbrace"
            else:
                is_open = x.kind == "other" and x.text == "["
                is_close = x.kind == "other" and x.text == "]"
            if is_open:
                depth += 1
                opens.append((x.pos, x.gen))
            if is_close:
                depth -= 1
                if depth == 0:
                    return inner, x
                opens.pop()
            inner.append(x)

    @staticmethod
    def _unread_pulled(src: TokenSource, pulled: list[Tok], *tail: Tok | None) -> None:
        r"""回放 ``pulled`` + 可选尾 token 并清账——bail 惯用式单源。

        ``src.unread([*pulled, *tail])`` 的兜底形：放弃路径把跳读 ws 与
        探得 token 一并回吐主流重扫（字节版「pos 停原位」等价物）；尾参
        逐个收、``None`` 滤除（peek-bail 的 maybe-None 位直接传）。
        ``pulled`` 回放后即死账——顺手 ``clear()`` 供循环位复用同名
        列表（``_protect_cs`` opt/mand 轮探臂）。
        """
        src.unread([*pulled, *(t for t in tail if t is not None)])
        pulled.clear()

    @staticmethod
    def _eat_quoted_toks(src: TokenSource, first: Tok) -> tuple[list[Tok], int | None]:
        r"""引号裸名 ``"a b.tex"`` 收集：``first``（开引号 token）起收至闭引号。

        返回 ``(toks, qend)``——``toks`` 含 ``first``；``qend`` = 闭引号
        token 后界，缺席（EOF/源界先至）为 ``None``：in_arg 臂按此中止
        回放（无配对不吞尾），literal 臂忽略之整收到流尾。
        """
        toks = [first]
        while True:
            y = src.read()
            if y is None:
                return toks, None
            toks.append(y)
            if y.kind in ("letter", "other") and y.text == '"':
                return toks, y.pos[2]

    @staticmethod
    def _eat_fname_toks(src: TokenSource, first: Tok) -> tuple[list[Tok], int]:
        r"""裸文件名连吃：``first`` 起连吃 FILENAME_CHARS token → ``(toks, end)``。

        首个失配 token 回吐不消费；``end`` = 末枚文件名 token 后界。
        """
        toks = [first]
        while True:
            y = src.read()
            if (
                y is not None
                and y.kind in ("letter", "other")
                and all(c in FILENAME_CHARS for c in y.text)
            ):
                toks.append(y)
            else:
                if y is not None:
                    src.unread([y])
                break
        return toks, toks[-1].pos[2]

    def _args_tok(  # noqa: C901, PLR0912, PLR0913, PLR0915 — argspec 字母各一分支，平铺即 §5.3 表
        self,
        src: TokenSource,
        fid: int,
        spec: list[ArgSpec] | int,
        pos0: int,
        *,
        has_opt: bool = False,
        allow_single_token: bool = True,
    ) -> tuple[list[_ArgTok], int]:
        r"""v1 ``_args`` 的 token 版：按 argspec 从 ``read()`` 流读参。

        ``pos0`` = cs 名后文件位（零消费时零宽锚点）。返回 ``(args, end)``，
        ``end`` = 最后消费位。每参前置 ws token 记进 ``pulled``——命中并入
        ``all_toks``（放弃路径 ``_unread_args`` 一并回放，与 v1「pos 不动
        全量重扫」等价）；未中连同目标 token 一起 ``unread``。

        组内列扫对价 = ``_walk_spec_toks``（``_aspec_elem`` 归一）——本
        面是拉取/回放契约（``pulled``/``committed``/``all_toks`` 账本 +
        逐参 ``_ArgTok`` 记录），TokenSource 无索引游标、ws 计入消费位，
        不同构不入归一。判据差留意：``t``/``d`` 位本面有 cs 禁配，列扫
        ``_grp_spec_args_end`` 无（原判保留在 ``_WSpec.no_cs``）。
        """
        items = [ArgSpec("m")] * spec if isinstance(spec, int) else list(spec)
        if has_opt:
            items = [ArgSpec("o"), *items]
        out: list[_ArgTok] = []
        end = pos0
        for s in items:
            pulled: list[Tok] = []
            x = self._peek_nonspace(src, pulled)
            if x is None:
                # par/EOF 停：ws 回放主流重扫（v1 主循环从 end 续读）
                self._unread_pulled(src, pulled)
                out.append(_ArgTok.empty(fid, end, s))
                continue
            if s.kind in ("m", "v"):
                if x.kind == "lbrace" or (x.kind == "other" and x.text == "["):
                    hit = self._collect_group(src, x, brace=x.kind == "lbrace")
                    if hit is None:
                        # 组 token 已回吐；ws 回放（v1 pos 停原位的等价物）
                        self._unread_pulled(src, pulled)
                        break
                    inner, closer = hit
                    out.append(_ArgTok.group(fid, x, closer, inner, pulled, s))
                    end = closer.pos[2]
                elif x.kind == "cs" or not allow_single_token:
                    # 单 token 参数不跨 '\'（BUG1）；禁用即停
                    self._unread_pulled(src, pulled, x)
                    break
                else:
                    out.append(_ArgTok.single(fid, x, pulled, s))
                    end = x.pos[2]
            elif s.kind == "n":
                # 裸 cs 名参（``\setlength\parskip{4pt}``）：cs token 直收、
                # 或 {..}/[..] 组——其余形失配即终止（强制参同 m）
                if x.kind == "cs":
                    out.append(_ArgTok.single(fid, x, pulled, s))
                    end = x.pos[2]
                elif x.kind == "lbrace" or (x.kind == "other" and x.text == "["):
                    hit = self._collect_group(src, x, brace=x.kind == "lbrace")
                    if hit is None:
                        self._unread_pulled(src, pulled)
                        break
                    inner, closer = hit
                    out.append(_ArgTok.group(fid, x, closer, inner, pulled, s))
                    end = closer.pos[2]
                else:
                    self._unread_pulled(src, pulled, x)
                    break
            elif s.kind in ("o", "O"):
                if x.kind == "other" and x.text == "[":
                    hit = self._collect_group(src, x, brace=False)
                    if hit is None:
                        self._unread_pulled(src, pulled)
                        break
                    inner, closer = hit
                    out.append(_ArgTok.group(fid, x, closer, inner, pulled, s))
                    end = closer.pos[2]
                else:
                    self._unread_pulled(src, pulled, x)
                    out.append(_ArgTok.empty(fid, end, s))
            elif s.kind == "s":
                if x.kind == "other" and x.text == "*":
                    out.append(_ArgTok.single(fid, x, pulled, s))
                    end = x.pos[2]
                else:
                    self._unread_pulled(src, pulled, x)
                    out.append(_ArgTok.empty(fid, end, s))
            elif s.kind == "t" and s.delim:
                if x.kind != "cs" and x.text == s.delim[0]:
                    out.append(_ArgTok.single(fid, x, pulled, s))
                    end = x.pos[2]
                else:
                    self._unread_pulled(src, pulled, x)
                    out.append(_ArgTok.empty(fid, end, s))
            elif s.kind in ("d", "D", "r", "R") and s.delim:
                op, cl = s.delim[0], s.delim[-1]
                if x.kind == "cs" or x.text != op:
                    self._unread_pulled(src, pulled, x)
                    if s.kind in ("r", "R"):
                        break  # 定界强制缺失 → 参数不匹配，停读
                    out.append(_ArgTok.empty(fid, end, s))
                    continue
                dtoks = [x]
                inner = []
                closer = None
                while True:
                    y = src.read()
                    if y is None:
                        break
                    dtoks.append(y)
                    if y.kind != "cs" and y.text == cl:
                        closer = y
                        break
                    inner.append(y)
                if closer is None:
                    self._unread_pulled(src, pulled, *dtoks)
                    break
                out.append(_ArgTok.group(fid, x, closer, inner, pulled, s))
                end = closer.pos[2]
            elif s.kind == "e":
                # 修饰参 ``e{^_}``：逐个 token 试吃 ``X{arg}``/``X<tok>``，
                # 整段并作一个 ArgTok（F10 位序修复的 token 版；
                # gullet ``_invoke`` 'e' 分支同规——cs 不作参、缺席只留符）
                es = end
                self._unread_pulled(src, pulled, x)  # 归一：候选判读在循环内逐轮做
                etoks: list[Tok] = []
                inner = []
                if s.delim:
                    rest = list(dict.fromkeys(s.delim))
                    while rest:
                        ip: list[Tok] = []
                        y = self._peek_nonspace(src, ip)
                        if y is None or y.kind == "cs" or y.text not in rest:
                            self._unread_pulled(src, ip, y)
                            break
                        etoks.extend(ip)
                        etoks.append(y)
                        inner.append(y)
                        rest.remove(y.text)
                        end = y.pos[2]
                        jp: list[Tok] = []
                        z = self._peek_nonspace(src, jp)
                        if z is not None and z.kind == "lbrace":
                            hit = self._collect_group(src, z, brace=True)
                            if hit is not None:
                                g_inner, g_close = hit
                                etoks.extend([*jp, z, *g_inner, g_close])
                                inner.extend([z, *g_inner, g_close])
                                end = g_close.pos[2]
                            else:
                                self._unread_pulled(src, jp)  # 组 token 已回吐
                        elif z is not None and z.kind != "cs":
                            etoks.extend(jp)
                            etoks.append(z)
                            inner.append(z)
                            end = z.pos[2]
                        else:
                            self._unread_pulled(src, jp, z)
                out.append(_ArgTok(fid, es, end, es, end, inner, etoks, s))
            elif s.kind == "u" and s.delim_toks:
                # ``#1<seq>`` 定界参：滑窗 ``_tok_eq`` 逐枚比对 delim 序列——
                # delim 消费、不计入 inner；``lbrace`` 起平衡组整收（组内
                # 定界符不参与滑窗，gullet ``_read_delimited`` 同款屏蔽）。
                # ``eol_par``/EOF 先至 → 全回吐 ``break``——不跨段界追 delim
                # （``_find_math_close_tok`` 与 ``d/r`` closer-miss 同款
                # runaway 防护）。
                k = len(s.delim_toks)
                dtoks: list[Tok] = []
                runaway = False
                if x.kind == "lbrace":
                    grp = self._collect_group(src, x, brace=True)
                    if grp is None:
                        runaway = True  # 组 token 已由 _collect_group 回吐
                    else:
                        g_inner, g_close = grp
                        dtoks.extend([x, *g_inner, g_close])
                else:
                    dtoks.append(x)
                while not runaway:
                    if len(dtoks) >= k and all(
                        _tok_eq(dtoks[-k + j], s.delim_toks[j]) for j in range(k)
                    ):
                        break
                    y = src.read()
                    if y is None or y.kind == "eol_par":
                        if y is not None:
                            dtoks.append(y)
                        runaway = True
                        break
                    if y.kind == "lbrace":
                        grp = self._collect_group(src, y, brace=True)
                        if grp is None:
                            runaway = True  # 同上——已拉 token 全回吐
                            break
                        g_inner, g_close = grp
                        dtoks.extend([y, *g_inner, g_close])
                        continue
                    dtoks.append(y)
                if runaway:
                    self._unread_pulled(src, pulled, *dtoks)
                    break
                inner = dtoks[:-k]
                closer = dtoks[-1]
                out.append(
                    _ArgTok(
                        fid,
                        inner[0].pos[1] if inner else closer.pos[1],
                        inner[-1].pos[2] if inner else closer.pos[1],
                        dtoks[0].pos[1],
                        closer.pos[2],
                        inner,
                        [*pulled, *dtoks],
                        s,
                    )
                )
                end = closer.pos[2]
            elif s.kind == "g":
                # ``#1{`` 形：读到 ``lbrace`` 回吐——``{`` 不消费、不计入
                # inner（TeX ``#{`` 语义：组留主流自行分流）。``eol_par``/
                # EOF 先至 → 全回吐 ``break``（runaway 防护同 'u'）。
                gtoks: list[Tok] = []
                hit = x.kind == "lbrace"
                if hit:
                    src.unread([x])
                else:
                    gtoks.append(x)
                while not hit:
                    y = src.read()
                    if y is None or y.kind == "eol_par":
                        if y is not None:
                            gtoks.append(y)
                        break
                    if y.kind == "lbrace":
                        src.unread([y])
                        hit = True
                        break
                    gtoks.append(y)
                if not hit:
                    self._unread_pulled(src, pulled, *gtoks)
                    break
                out.append(
                    _ArgTok(
                        fid,
                        gtoks[0].pos[1] if gtoks else x.pos[1],
                        gtoks[-1].pos[2] if gtoks else x.pos[1],
                        gtoks[0].pos[1] if gtoks else x.pos[1],
                        gtoks[-1].pos[2] if gtoks else x.pos[1],
                        gtoks,
                        [*pulled, *gtoks],
                        s,
                    )
                )
                if gtoks:
                    end = gtoks[-1].pos[2]
            else:
                # 'b'/无 delim 的 dDrRt/未知：不消费但占零宽位
                self._unread_pulled(src, pulled, x)
                out.append(_ArgTok.empty(fid, end, s))
        return out, end

    def _try_args(  # noqa: PLR0913 — 三连惯用式参面（源/fid/spec/pos0/双开关）原位
        self,
        src: TokenSource,
        fid: int,
        spec: list[ArgSpec] | int,
        pos0: int,
        *,
        has_opt: bool = False,
        allow_single_token: bool = True,
    ) -> tuple[list[_ArgTok], int] | None:
        r"""``_args_tok`` + 全占位判据 + ``_unread_args`` 回放的三连惯用式。

        任一实消费参 → ``(args, end)``；全零宽占位 → 回放后返 ``None``
        （调用方走各自 bail：protect 回落/逐字/字面档）。
        """
        args, end = self._args_tok(
            src,
            fid,
            spec,
            pos0,
            has_opt=has_opt,
            allow_single_token=allow_single_token,
        )
        if not any(a.fe > a.fs for a in args):
            self._unread_args(src, args)
            return None
        return args, end

    # ------------------------------------------------------------ 保护调用

    def _protect_cs(  # noqa: C901, PLR0915 — *?/定界/[opt]×3/{arg}×mand 平铺即 _protect_call
        self,
        t: Tok,
        src: TokenSource,
        typ: PhType,
        *,
        mand: int = 3,
        verbatim: bool = False,
    ) -> None:
        r"""命令 + ``*?`` + ``[opt]*`` + ``{args}*`` 整段 → ``[[typ_n]]`` 进 run。

        ``mand`` = ``{...}`` 组上限（v1 ``_protect_call`` 同参）：cite/ref/
        protect 族全是单 key 签名传 1——``\cite{a}{b}`` 的 ``{b}`` 是正文
        不是参数，吞进去就永不进 chunk（audit 次要 2）。组内对价：
        ``_grp_call_end``（展开组 surface 侧的同款尾参扫描）。
        """
        fid, _a, b = t.pos
        end = b
        # v1 ``_protect_call``：``*``/定界符都查 ``tex[pos]`` 裸位——不 ws_skip
        x = src.read()
        if x is not None and x.kind == "other" and x.text == "*":
            end = x.pos[2]
            x = src.read()
        if verbatim and x is not None:
            # ``\url<delim>…<delim>`` 定界形（url.sty 同 \verb 规则，
            # EOL 上限——scanner-audit F11）。cs token 的定界字符 = `\`。
            d = "\\" if x.kind == "cs" else x.text
            if _verb_delim_tok(x):
                ftext = self.file_texts[fid]
                e = ftext.find(d, x.pos[1] + 1)
                eol = ftext.find("\n", x.pos[1] + 1)
                lim = eol if eol >= 0 else len(ftext)
                end = e + 1 if 0 <= e < lim else lim
                self._cover_ph(fid, end, typ, gap=t)
                self._skip_past(src, fid, end)
                return
        if x is not None:
            src.unread([x])  # 未消费位回吐——opt/mand 走 ws_skip peek
        pulled: list[Tok] = []
        for _ in range(3):
            x = self._peek_nonspace(src, pulled)
            if x is not None and x.kind == "other" and x.text == "[":
                hit = self._collect_group(src, x, brace=False)
                if hit is not None:
                    end = hit[1].pos[2]
                    pulled.clear()
                    continue
                self._unread_pulled(src, pulled)  # 组 token 已回吐；ws 回放
                break
            self._unread_pulled(src, pulled, x)
            break
        key_span: tuple[int, int] | None = None  # 末个 ``{..}`` 内容位（告警判形）
        for _ in range(mand):
            x = self._peek_nonspace(src, pulled)
            if x is not None and x.kind == "lbrace":
                if verbatim:
                    # url/path 逐字参：``%`` 不作注释——字节级配对 +
                    # resync；token 收集会被 ``%`` 吃掉闭括号直排 EOF
                    e = match_brace(self.file_texts[fid], x.pos[1], verbatim=True)
                    if e is None:
                        self._unread_pulled(src, pulled, x)
                        break
                    end = e
                    pulled.clear()  # ws/lbrace 已在覆盖区间内——不回放
                    self._skip_past(src, fid, e)
                    continue
                hit = self._collect_group(src, x, brace=True)
                if hit is None:
                    self._unread_pulled(src, pulled)  # 组 token 已回吐
                    break
                key_span = (x.pos[2], hit[1].pos[1])
                end = hit[1].pos[2]
                pulled.clear()
                continue
            self._unread_pulled(src, pulled, x)
            break
        self._protect_key_warns(t, fid, end, typ, key_span)
        self._cover_ph(fid, end, typ, gap=t)

    def _protect_key_warns(
        self,
        t: Tok,
        fid: int,
        end: int,
        typ: PhType,
        key_span: tuple[int, int] | None,
    ) -> None:
        r"""``_protect_cs`` 尾哨兵：``\bibitem(n)``/``\cite{n-m}`` 键形态告警。

        ``\bibitem(13)`` 圆括号标号形（W89）——``(`` 直贴消费尾即签名，
        标号漏进 chunk 面但整调用仍原样保真；``\cite{15-20}`` 把区间当
        键写（W90）——逗号项中纯数字-数字形即误植（``smith-2020``/
        ``key-a`` 合法键不中），保护照旧记哨兵供归因。v1 同款判形在
        ``scanner._protect_warns``。
        """
        if t.text == "bibitem" and self.file_texts[fid][end : end + 1] == "(":
            self.state.warnings.append(
                ScanWarning("bibitem_paren", len(self.vt), "\\bibitem(n) 形")
            )
        if (
            typ is PhType.CITE
            and key_span is not None
            and any(
                _CITE_RANGE_KEY_RX.fullmatch(item)
                for item in self.file_texts[fid][key_span[0] : key_span[1]].split(",")
            )
        ):
            self.state.warnings.append(
                ScanWarning("cite_range_key", len(self.vt), "\\cite{n-m} 区间键")
            )

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
            # 嵌套 chunk-arg 内联化：前缀+渲染+闭括号并入父 run
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
        # 覆盖 gap+命令头一步 cover：`_cover_gap` 的 run 项在 preamble 档
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
    def _unread_args(src: TokenSource, args: list[_ArgTok]) -> None:
        """``_args_tok`` 放弃路径：全部 ``all_toks`` 按拉取序回放。"""
        toks = [x for a in args for x in a.all_toks]
        if toks:
            src.unread(toks)

    @staticmethod
    def _arg_body_shaped(a: _ArgTok) -> bool:
        r"""参 token 流是否块级排版体（而非参数槽）。

        ``eol_par`` 空行（TeX ``\long`` 语义多段参）或
        ``\begin``/``\end``/``\item``/节题 cs 任一即体。
        """
        for x in a.all_toks:
            if x.kind == "eol_par":
                return True
            if x.kind == "cs" and x.text in _BODY_CS_NAMES:
                return True
        return False

    @staticmethod
    def _split_rendered(core: str) -> list[str]:
        """渲染串二次切分——v1 ``_split_core`` 原样（``[[X_n]]`` 边界优先）。

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

    def _mine_prose_block(self, t: Tok, src: TokenSource, fid: int, b: int) -> bool:
        r"""``_PROSE_BLOCK_NAMES`` 白名单名的散文参挖掘（第三臂，界外项核销）。

        ``\markright``/``\markboth`` 运行头与 ``\address``/``\institute``/
        ``\affiliation`` 隶属段的实参装的是真散文——整调用折 ``[[AUTHOR]]``
        会蒸发译文面（``_handle_protect_block`` 与 opaque 蒸发同型）。
        实参逐参过共享判据（``_prose_args_of`` → ``_opaque_arg_prose``，
        位上限 ``_PROSE_BLOCK_ARITY`` 防尾随正文组误吞）：命中即探针臂同款
        发射——``[[CMD]]`` 分段护结构 + 子扫渲进 run surface；无命中 /
        ``gen`` 触底 → 全参回放返 False，调用方走 ``[[AUTHOR]]`` 原路径。
        ``\author`` 不入白名单：``\and`` 连名过词链门会把人名抬进译文面。
        """
        args, end = self._args_tok(
            src, fid, _PROSE_BLOCK_ARITY[t.text], b, allow_single_token=False
        )
        prose_args = self._prose_args_gated(t.text, t, fid, args, "block")
        if not prose_args:
            self._unread_args(src, args)
            return False
        self._cover_gap(fid, t.pos[1])
        self._emit_prose_args(fid, prose_args, PhType.CMD)
        self._cover_ph(fid, end, PhType.CMD)
        return True

    def _keyval_tail_end(self, src: TokenSource, end: int) -> int:
        r"""Protect 调用实参之后续吃键值形 ``{..}``/``[..]`` 组 → 新 end。

        aipproc ``\author{name}{address=..,email=..}`` 第二参是 keyval 签名
        ——只护首组会让 keyval 组裸进 chunk，``key=`` 键位被译成
        ``这是译文=``，splice 后 ``\setkeys`` 炸 ``Package keyval Error``
        （0905.0330/0905.2183/1012.1143/astro-ph/0408494/0605512 五格）。
        同型 ``[kv]`` 尾参同收：ceurart/elsarticle ``\author[..]{n}[orcid=..,
        email=..]``（2410.17963/2403.01255）、biblatex ``\printbibliography
        [title={..},segment=1]``（2403.09125）、``\tikzstyle{n}=[rectangle,
        draw,text width=8em,..]``/``\tikzstyle{n} = [draw, -latex]``
        （2009.03715/2403.14735——``=`` 起头可选，并入试探列随败退回放）。
        形状门（``_kv_list_shaped``——任一项 ``key=`` 或全项裸键 token）把
        ``{散文}``/``[see Fig. 1]`` 误吞面压掉——非键值组全量回放由主流
        重扫，与今日行为同。``eol_par`` 段界不跨（``_peek_nonspace`` 内建）；
        跨 fid 组不收——字节异源没法切片判形，回放是保守等价物。
        """
        while True:
            pulled: list[Tok] = []
            x = self._peek_nonspace(src, pulled)
            if x is not None and x.kind == "other" and x.text == "=":
                pulled.append(x)  # ``=`` 并入试探列——后非键值组随败退回放
                x = self._peek_nonspace(src, pulled)
            is_brace = x is not None and x.kind == "lbrace"
            is_bracket = x is not None and x.kind == "other" and x.text == "["
            if x is None or not (is_brace or is_bracket):
                self._unread_pulled(src, pulled, x)
                return end
            hit = self._collect_group(src, x, brace=is_brace)
            if hit is None:
                self._unread_pulled(src, pulled)  # 组 token 已回吐；ws/``=`` 回放
                return end
            inner, closer = hit
            if closer.pos[0] != x.pos[0] or not _kv_list_shaped(
                self.file_texts[x.pos[0]], x.pos[2], closer.pos[1]
            ):
                self._unread_pulled(src, pulled, x, *inner, closer)
                return end
            end = closer.pos[2]

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

    def _opaque_arg_prose(self, fid: int, a: _ArgTok) -> bool:
        r"""Opaque 宏 ``{..}``/``[..]`` 组参的调用点散文门（gullet-at scout 口径）。

        只认本 fid 实消费的 ``{``/``[``-open 组参：跨 fid 组字节切片判不了形
        （``_keyval_tail_end`` 同款守门）、``d<>``/``e``/``r()``/``t``/单 token
        参不是散文槽位。``[``-open 可选参同挖——``\subfigure[长 caption]{..}``
        的 opt 散文是真翻译料，``[width=2cm]``/``[see]`` 由形状门/词链挡住。
        ``key=`` 起头的 keyval 组不挖——``{pdftitle={长标题}}`` 值内散文会连
        ``key=`` 键位一起抬进译文面（``_keyval_tail_end`` 同款形状门，
        ``\setkeys`` 炸面）；逗号分隔机读名单同罩——``{arrows, automata,
        backgrounds, calendar}`` 类库/包/文件列抠出翻译即断链（1907.03868
        实遇）。``\index``/``\label`` 整调用判形前剥除——零宽标记不当隔墙
        （W85 参内嵌句面）。内容剔注释+cs 后 ≥4 连词即散文。
        """
        if a.fe <= a.fs or a.cs <= a.fs:
            return False  # 未消费占位 / 单 token 参
        if any(x.pos[0] != fid for x in a.all_toks):
            return False  # 跨 fid 组——``file_texts[fid]`` 切片错位，保持 opaque
        if self.file_texts[fid][a.fs] not in "{[":
            return False  # ``d<>``/``e``/``r()``/``t`` 定界参非散文槽位
        content = self.file_texts[fid][a.cs : a.ce]
        return _prose_text_hit(content)

    def _prose_args_of(self, name: str, fid: int, args: list[_ArgTok]) -> list[_ArgTok]:
        r"""调用点名闸 + 逐参散文门——三臂（opaque/探针/argspec）抠出判定单源。

        ``_SWALLOW_ARG_NAMES``（吞块）/``_DEAD_ARG_NAMES``（被删死文本）
        整调用不挖；``_DEAD_TAIL_NAMES`` 只放首个实参——``\replaced{新}{旧}``
        的 ``{旧}`` 是被替换死文本不译。序数按实消费参计（``[o]`` 占位
        不计位——``\replaced`` 无 ``[o]`` 签名，参序即实序）。
        """
        if name in _SWALLOW_ARG_NAMES or name in _DEAD_ARG_NAMES:
            return []
        tail_dead = name in _DEAD_TAIL_NAMES
        out: list[_ArgTok] = []
        nth = 0
        for a in args:
            if a.fe <= a.fs:
                continue  # 未消费占位不占实参序
            if (not tail_dead or nth == 0) and self._opaque_arg_prose(fid, a):
                out.append(a)
            nth += 1
        return out

    def _prose_args_gated(
        self, name: str, t: Tok, fid: int, args: list[_ArgTok], tag: str
    ) -> list[_ArgTok]:
        r"""``_prose_args_of`` + ``gen_overflow`` 闸二连——三臂共用判定面。

        子扫代数触底时散文参不挖、整调用维持 protect/opaque 原文
        （``_handle_chunk_arg`` 同款回压：宁可不译也不超代数）；``tag``
        即告警 detail 前缀（``block``/``opaque``/``probe``/``argspec``）。
        """
        prose_args = self._prose_args_of(name, fid, args)
        if prose_args and self.gen >= MAX_GEN:
            self.state.warnings.append(
                ScanWarning("gen_overflow", len(self.vt), f"{tag}:{t.text}")
            )
            prose_args = []
        return prose_args

    def _emit_prose_args(
        self, fid: int, prose_args: list[_ArgTok], typ: PhType
    ) -> None:
        r"""散文参逐枚「``{`` 前结构进 ``[[typ]]`` + 参内容子扫渲 surface」发射。

        ``_cover_to(a.cs)`` 不含前隙——调用方先 ``_cover_gap`` 剖命令前
        间隙字面项；``_rappend_subscan`` 的 vmark 不复用位（逐枚只渲不锚）。
        """
        for a in prose_args:
            self._cover_ph(fid, a.cs, typ)
            self._rappend_subscan(a, len(self.vt))

    def _rappend_subscan(self, a: _ArgTok, vmark: int) -> int:
        r"""子扫渲染串进 run（``[vmark, vt 末)`` 区间记账）→ 新 vmark。

        ``_emit_argspec_chunks`` 的 op 循环锚位推进同款——``vmark`` 是
        上一 op 落定后的 vt 位，返回 ``len(self.vt)`` 供下一 op 复用。
        """
        rendered = self._subscan_render(a)
        self._rappend(rendered, rendered, Span(vmark, len(self.vt)))
        return len(self.vt)

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
            e = _tables.argspec_lookup(name or t.text, self.state.pkgs)
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
                    vmark = self._cover_ph(fid, int(x), PhType.CMD).end
                    continue
                vmark = self._rappend_subscan(x, vmark)
            return
        self._cover_gap(fid, t.pos[1])  # 同上——字面 piece 不含前隙
        v0 = self._cover_to(fid, int(ops[0][1]))
        self._flush_run(v0.start)
        self._emit(v0.start, v0.end)
        cur_v = v0.end
        for op, x in ops[1:]:
            if op == "lit":
                v = self._cover_to(fid, int(x))
                self._emit(v.start, v.end)
                cur_v = v.end
                continue
            rendered = self._subscan_render(x)
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

    def _subscan_render(self, a: _ArgTok) -> str:
        r"""文本参内容 token → in_arg 子扫渲染串（含尾字节兜底 + 注释 ph）。

        ``_handle_chunk_arg`` 的子扫段抽出：覆盖经共享 vt/cons 直落父
        区间（``a.cs`` 前的字面段由调用方先盖），``a.ce`` 内残余字节
        补盖进渲染串（F-尾丢同款）。
        """
        fid = a.fid
        sub = self.spawn(in_arg=True)
        sub.scan(_ListSource(list(a.toks)), self.file_texts)
        sub_end = len(self.vt)
        self._cover_to(fid, a.ce)
        rendered = "".join(p.text for p in sub.pieces)
        if sub_end < len(self.vt):
            rendered += self.vt.slice(sub_end, len(self.vt))
        return self._arg_comment_ph(rendered)

    def _arg_comment_ph(self, rendered: str) -> str:
        r"""渲染串内裸 ``%`` 注释 → ``[[COMMENT]]``（机制 B 同款）。"""
        return _ARG_COMMENT_RX.sub(
            lambda m: (
                m.group(0)
                if m.group(0).startswith("\\")
                else self._ph(PhType.COMMENT, m.group(0))
            ),
            rendered,
        )
