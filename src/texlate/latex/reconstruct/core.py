r"""``latex.reconstruct.core`` — pieces splice + 占位符 DAG 递归展开（``reconstruct`` god-file 机械拆分叶）。

``_Expander``：``trans_map → ph_map → chunks[idx].content → 字面``
优先级展开器，memo + ``active`` 环检内建；注锚开启时停用 memo
（``_ctx_chain`` 站点语境随引用点变）。``reconstruct``：pieces 遍历
+ ``mark_seq0`` 注锚总闸 + 译文侧 post-fix 链（``cjk_glue_fix`` →
``cjk_punct_close_guard`` → ``dblbrace_arg_fix``）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from texlate.latex.placeholder import CHUNK_RX, PH_RX
from texlate.latex.reconstruct.fix import (
    PAR_RUN_RX,
    cjk_glue_fix,
    cjk_punct_close_guard,
    dblbrace_arg_fix,
    seg_join,
    translation_tokens,
)
from texlate.latex.reconstruct.mark import (
    _MARK_ALIGN_ENVS,
    _MARK_MOVING_CTX,
    _MARK_NONTEXT_CS,
    _MARK_ROW_HEAD_RX,
    _MARK_ROW_TAIL_RX,
    _MARK_RULE_HEAD_RX,
    _MARK_RULE_TAIL_RX,
    _MARK_SKIP_CTX,
    _MARK_SOUL_CS,
    _PH_EDGE_HEAD_RX,
    _PH_EDGE_TAIL_RX,
    _in_align_preamble,
    _open_cs,
    _piece_site_map,
    _wrap_seq_mark,
    in_env_args,
)

if TYPE_CHECKING:
    from texlate.latex.model import ScanResult

log = logging.getLogger(__name__)


class _Expander:
    r"""``[[X_n]]`` 占位符 DAG 递归展开器（``reconstruct``/``chunk_spans`` 单源）。

    ``trans_map`` = ``translation_tokens`` 产物；``glue_latin`` 开接缝
    守卫（译文落盘侧恒真，identity 路径恒假）。``expand`` 解析优先级
    ``trans_map → ph_map → CHUNK_RX.fullmatch → chunks[idx].content →
    字面``；memo + ``active`` 环检内建（译文侧自指/互指环留字面），
    查无实体的 token 记 ``dangling``（``ph_reserved`` 豁免）。
    """

    def __init__(
        self,
        res: ScanResult,
        trans_map: dict[str, str],
        *,
        glue_latin: bool,
        mark_seq0: int | None = None,
        mark_moving: bool = False,
    ) -> None:
        self.res = res
        self.trans = trans_map
        self.glue_latin = glue_latin
        self.memo: dict[str, str] = {}
        self.active: set[str] = set()
        # seq 注锚表：{chunk_idx: seq}；None → 不注锚（identity/chunk_spans 同径）
        self.mark = (
            {c.id: mark_seq0 + c.id for c in res.chunks}
            if mark_seq0 is not None
            else None
        )
        self.mark_moving = mark_moving
        # piece 级 site 上下文（顶层 expand_body 前由 reconstruct 逐 piece 写入）
        self._site_cs: frozenset[str] = frozenset()
        self._site_prev = ""
        self._site_next = ""
        # 引用点上下文栈：expand 递归下钻时逐层压入「本层已解析的
        # (site_cs, tail, head)」——嵌套体空缘回落外层邻居文本判闸，
        # 而非一律弃注（嵌套 [[CHUNK_n]] 覆盖 ~16% chunk 的引用面）。
        self._ctx_chain: list[tuple[frozenset[str], str, str]] = []
        # 查无实体的 ph token——留字面并记名（原静默残留）
        self.dangling: set[str] = set()
        # 短参 chunk 集：context 非 para/item 的已译 [[CHUNK_n]]——展开后
        # ``\n\n`` 压单 ``\n``（见 PAR_RUN_RX 注）。
        self.short_arg: set[str] = {
            f"[[CHUNK_{c.id}]]"
            for c in res.chunks
            if c.context not in ("para", "item") and f"[[CHUNK_{c.id}]]" in trans_map
        }

    def expand(self, token: str) -> str:  # token 形如 [[X_n]]
        """单 token → 展开体（memo 命中直返）。

        注锚开启时停用 memo：嵌套 ``[[CHUNK_n]]`` 的注锚判定吃
        ``_ctx_chain`` 站点语境——memo 会把首站判定冻结进缓存体，
        同 token 第二引用点不再重估（锚随首站语境错放/丢失）。
        ``active`` 环检不受影响；ph 图引用低重展开实测廉价。
        """
        memoize = self.mark is None
        memo = self.memo
        if memoize and token in memo:
            return memo[token]
        if token in self.active:
            return token  # 译文侧自指/互指环（ph_map 构造上无环）→ 留字面
        self.active.add(token)
        body = self.trans.get(token)
        if body is None:
            body = self.res.ph_map.get(token)
        if body is None:
            m = CHUNK_RX.fullmatch(token)
            idx = int(m.group(1)) if m else -1
            if 0 <= idx < len(self.res.chunks):
                body = self.res.chunks[idx].content
            else:
                if token not in self.res.ph_reserved:
                    self.dangling.add(token)
                body = token
        expanded = self.expand_body(body, fold_par=token in self.short_arg)
        if memoize:
            memo[token] = expanded
        self.active.discard(token)
        return expanded

    def set_site(self, cs: frozenset[str], prev: str, nxt: str) -> None:
        """Piece 级 site 上下文写入——``reconstruct`` 逐顶层 piece 调用。"""
        self._site_cs = cs
        self._site_prev = prev
        self._site_next = nxt

    def _mark_seq(  # noqa: C901, PLR0911, PLR0912 -- 闸阶梯逐条早返即谓词本体，分支数=规则数
        self, tok: str, site_cs: frozenset[str], tail: str, head: str
    ) -> tuple[int, bool] | None:
        r"""引用点注锚判定——(seq, arg_zone) 或 None（保守方向：判不出=不注，丢锚不丢编译）。

        谓词全貌见 docs/dev/projects/pdf-seq-anchors-impl-2026-09-23.md §2.2：
        soul 栈/对齐 env/skip context/moving-arg/行间界五闸。
        ``site_cs``/``tail``/``head`` 由 ``push_ph`` 逐层解析——嵌套体
        空缘已回落 ``_ctx_chain`` 外层邻居文本，嵌套引用点同样可判。
        ``arg_zone=True`` 时 ``push_ph`` 把 BDC 挪到展开体前导读参串尾
        （未知 env 强制参进了 chunk 头——锚钉参前会破 ``\begin`` 参扫描）。
        """
        if self.mark is None:
            return None
        m = CHUNK_RX.fullmatch(tok)
        if not m:
            return None
        idx = int(m.group(1))
        if not (0 <= idx < len(self.res.chunks)):
            return None
        chunk = self.res.chunks[idx]
        ctx = (chunk.context or "").lower()
        if ctx in _MARK_SKIP_CTX:
            return None
        env = (chunk.env or "").lower().rstrip("*")
        if env.endswith("matrix") or env.startswith("nice"):
            return None
        in_align = env in _MARK_ALIGN_ENVS
        if in_align and _in_align_preamble(tail):
            return None
        if site_cs & _MARK_SOUL_CS:
            return None
        if site_cs & _MARK_NONTEXT_CS:
            return None  # 结构参括号内——whatsit 腐蚀 key/url/文件名言义
        if not self.mark_moving and (
            ctx in _MARK_MOVING_CTX or site_cs & _MARK_MOVING_CTX
        ):
            return None
        # ``\\`` 前贴闸仅非对齐面用——对齐内 ``\\ x`` 的 whatsit 进下一
        # 行首单元格（cell 起点隐式成立），合法不落 noalign 区。
        if _MARK_ROW_TAIL_RX.search(tail) and not in_align:
            return None
        if in_align:
            if _MARK_RULE_HEAD_RX.match(head):
                return None
            # 展开体缘同样拦：whatsit 贴 ``\multicolumn``/``\omit`` 破
            # omit 前瞻；尾贴 ``\\``/行规则 EMC 落下一行首（后续不可见
            # 行规即成 misplaced）——ph 边 token 解一层再判。
            exp = self._unroll_edge(
                self.trans.get(tok) or chunk.content or "", head=True
            )
            if _MARK_RULE_HEAD_RX.match(exp):
                return None
            exp = self._unroll_edge(
                self.trans.get(tok) or chunk.content or "", head=False
            )
            if _MARK_RULE_TAIL_RX.search(exp):
                return None
        elif _MARK_ROW_HEAD_RX.match(head):
            return None
        seq = self.mark.get(idx)
        if seq is None:
            return None
        return seq, (not in_align) and in_env_args(tail)

    def _unroll_edge(self, body: str, *, head: bool) -> str:
        r"""展开体头/尾的 ph token 原地代一层。

        ``[[CMD_n]]`` 边下的 ``\\multicolumn``/``\\\\`` 对齐缘判定须看字面。
        """
        for _ in range(2):
            m = _PH_EDGE_HEAD_RX.match(body) if head else _PH_EDGE_TAIL_RX.search(body)
            if not m:
                break
            sub = self.res.ph_map.get(m.group(1))
            if sub is None:
                break
            body = (sub + body[m.end() :]) if head else (body[: m.start()] + sub)
        return body

    def expand_body(self, body: str, *, fold_par: bool = False) -> str:
        r"""字面+ph 交错体展开——token 递归展开后过接缝守卫。

        ``fold_par`` 折叠域 = 本层字面段 + 字面↔ph 接缝；嵌套 ph 展开体
        **内部**的 ``\\n\\n`` 不动——受保环境体的真段落界不属短参 arg 上
        下文（S3）。接缝处理一律剥字面侧（foldable 面），ph 体只读：
        字面尾 ``\\n`` + ph 头 ``\\n`` → 字面退一格；ph 尾 ``\\n`` +
        字面头 ``\\n`` → 字面退一格。ph↔ph 直邻接缝不处理（双侧皆不可
        折叠面，存残留记档）。
        """
        segs: list[str] = []
        prev_ph = False  # segs[-1] 是否 ph 展开体（ph↔ph 接缝无字面侧可剥）

        def push_literal(seg: str) -> None:
            nonlocal prev_ph
            if fold_par:
                seg = PAR_RUN_RX.sub("\n", seg)
                if seg.startswith("\n") and segs and segs[-1].endswith("\n"):
                    seg = seg[1:]
            segs.append(seg)
            prev_ph = False

        def push_ph(tok: str, mstart: int, mend: int) -> None:
            nonlocal prev_ph
            # 本引用点上下文：本层字面邻居优先，空缘回落外层已解析邻居
            # （顶层空链 → piece site 三元组）
            pre, post = body[:mstart], body[mend:]
            outer = (
                self._ctx_chain[-1]
                if self._ctx_chain
                else (self._site_cs, self._site_prev, self._site_next)
            )
            site_cs = outer[0] | _open_cs(pre)
            tail = pre if pre.strip() else outer[1]
            head = post if post.strip() else outer[2]
            self._ctx_chain.append((site_cs, tail, head))
            try:
                exp = self.expand(tok)
            finally:
                self._ctx_chain.pop()
            if (
                fold_par
                and not prev_ph
                and exp.startswith("\n")
                and segs
                and segs[-1].endswith("\n")
            ):
                segs[-1] = segs[-1][:-1]
            mark_hit = self._mark_seq(tok, site_cs, tail, head)
            if mark_hit is not None and exp != tok:
                seq, arg_zone = mark_hit
                # 前缘判据取已发出字面尾——倒扫 segs 首个非空段 (相邻 token
                # 间空字面段/纯空白会占末位); 空缘回落 piece site 源文近似。
                # ``pre`` 是源侧 ph-token 注释体不可用。
                prev_out = next((s for s in reversed(segs) if s.strip()), tail)
                exp = _wrap_seq_mark(exp, seq, prev_out, arg_zone=arg_zone)
            segs.append(exp)
            prev_ph = True

        pos = 0
        for mm in PH_RX.finditer(body):
            push_literal(body[pos : mm.start()])
            push_ph(mm.group(0), mm.start(), mm.end())
            pos = mm.end()
        push_literal(body[pos:])
        return seg_join(segs) if self.glue_latin else "".join(segs)


def reconstruct(
    res: ScanResult,
    translations: dict[int, str] | None = None,
    *,
    mark_seq0: int | None = None,
    mark_moving: bool = False,
) -> str:
    r"""按 pieces splice + 占位符 DAG 递归展开（docs/spec/latex-pipeline.md 伪码原样）。

    ``translations``：``{chunk_id: 译文}``；None → identity 重建（回落
    ``chunks[idx].content`` 原文，字节等价）。``mark_seq0`` 给本文件 seq
    基址——非 None 即注锚：``[[CHUNK_n]]`` 引用点按安全谓词包
    ``/TLXC <</MCID 50000+seq>> BDC`` marked-content 锚（seq = mark_seq0
    + chunk 下标）；identity 面同样可注（en.pdf 源侧锚——glue/cjk 修正
    仍随译文缺席而关，产物 = 原文 + 纯锚）。``mark_moving`` 由调用方
    证明无 ``\\tableofcontents``/``\\listof*``/hyperref 后放行
    moving-arg chunk。
    """
    glue_latin = translations is not None
    marking = mark_seq0 is not None
    ex = _Expander(
        res,
        translation_tokens(res, translations),
        glue_latin=glue_latin,
        mark_seq0=mark_seq0 if marking else None,
        mark_moving=mark_moving,
    )
    # LITERAL 段也可能内嵌 ph（短 run / MINED_ONLY run 发渲染文本）——全段展开。
    if marking:
        sites = _piece_site_map(res)
        out = []
        for i, p in enumerate(res.pieces):
            ex.set_site(
                sites.get(p.span.start, frozenset()),
                res.pieces[i - 1].text[-64:] if i else "",
                res.pieces[i + 1].text[:64] if i + 1 < len(res.pieces) else "",
            )
            out.append(ex.expand_body(p.text))
    else:
        out = [ex.expand_body(p.text) for p in res.pieces]
    result = seg_join(out) if glue_latin else "".join(out)
    if ex.dangling:
        log.warning(
            "splice unresolved placeholders left literal: %d kinds (e.g. %s)",
            len(ex.dangling),
            ", ".join(sorted(ex.dangling)[:8]),
        )
    if translations:
        result = cjk_glue_fix(result)
        result = cjk_punct_close_guard(result)
        result = dblbrace_arg_fix(result)
    return result
