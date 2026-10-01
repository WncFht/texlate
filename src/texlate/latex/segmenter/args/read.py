r"""``latex/segmenter.args.read`` — 参数读取（``args`` god-file 机械拆分叶）。

``_args`` 的 token 版拉取/回放契约：``pulled``/``committed``/
``all_toks`` 账本 + 逐参 ``_ArgTok`` 记录。``_peek_nonspace``/
``_read_skipws``/``_collect_group``/``_unread_pulled`` 探针四件套 +
``_eat_quoted_toks``/``_eat_fname_toks`` 裸文件名连吃 + ``_args_tok``
argspec 逐参位 + ``_try_args``/``_unread_args`` 三连惯用式。组内列扫
对价 = ``_walk_spec_toks``；零宿主依赖。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.latex.gullet import _tok_eq
from texlate.latex.model import ArgSpec
from texlate.latex.segmenter._common import TokenSource, _ArgTok
from texlate.latex.tables import FILENAME_CHARS

if TYPE_CHECKING:
    from texlate.latex.mouth import Tok


class _ArgsRead:
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

    @staticmethod
    def _unread_args(src: TokenSource, args: list[_ArgTok]) -> None:
        """``_args_tok`` 放弃路径：全部 ``all_toks`` 按拉取序回放。"""
        toks = [x for a in args for x in a.all_toks]
        if toks:
            src.unread(toks)
