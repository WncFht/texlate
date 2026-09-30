r"""``latex/segmenter.args_protect`` — 保护调用（``args`` god-file 机械拆分叶）。

``_protect_cs``：命令 + ``*?`` + ``[opt]*`` + ``{args}*`` 整段 →
``[[typ_n]]`` 进 run（``mand`` = ``{...}`` 组上限，verbatim 走字节级
配对）；``_protect_key_warns`` 尾哨兵（``\bibitem(n)``/``\cite{n-m}``
键形态告警）；``_keyval_tail_end`` 实参后续吃键值形 ``{..}``/``[..]``
组（aipproc/ceurart/biblatex/tikzstyle 实证）。组内对价：``_grp_call_end``。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.latex.model import PhType, ScanWarning, match_brace

from ._common import _kv_list_shaped, _verb_delim_tok
from .args_read import _ArgsRead

if TYPE_CHECKING:
    from texlate.latex.model import ScanState, Span
    from texlate.latex.mouth import Tok

    from ._common import TokenSource, _Vtex

# ``\cite{15-20}`` 把区间当键写（W90）——逗号项中纯数字 - 数字形即误植，
# ``smith-2020``/``key-a`` 合法键不中。
_CITE_RANGE_KEY_RX = re.compile(r"\s*\d+\s*-+\s*\d+\s*")


class _ArgsProtect(_ArgsRead):
    # ------------------------------------------------------------ 宿主契约（ty 静态面）
    # god-class 机械拆分的静态代价：``Segmenter``（``__init__.py``）经 mixin
    # 链注入的状态/方法在本文件孤检时对 ty 不可见——``TYPE_CHECKING`` 声明
    # 即契约，签名与宿主 mixin（``core.py``/``mainloop.py``/``pending.py``）
    # 定义保持一致；宿主签名改动时同步此处。
    if TYPE_CHECKING:
        # ``_Core.__init__`` 注入的状态
        state: ScanState
        vt: _Vtex
        file_texts: list[str]

        # ``_Core``/``_MainLoop``/``_Pending`` 提供的方法
        def _cover_ph(
            self, fid: int, end: int, typ: PhType, gap: Tok | None = None
        ) -> Span: ...
        def _skip_past(self, src: TokenSource, fid: int, end: int) -> None: ...

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
