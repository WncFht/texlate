"""ph_in_cs 升格拦截：zh 把占位符嵌进 cs 名中段 → fault + 回退原文。

scout-spliceguard 归因：LLM 挪位把 ``[[PH]]`` 嵌进命令名
（``\\te[[MATH_1]]xtbf``/``\\noind[[REF_2]]ent``），splice ``expand`` 逐字节
替换后断 cs 成未定义命令、载荷不可复原——不进 fixloop。validator 主层
（l0 ``_check_ph_in_cs``）之外，本层拦续跑 state/段级缓存旁路的 stale
脏译。判定 = ``textutil.ph_in_cs_net`` 双侧夹持净差：``\\cs[[PH]]`` 尾邻
合法高频形（``\\protect[[REF_n]]`` 系）不误伤、src 自带同形按多重集差
豁免、注释区屏蔽。
"""

import asyncio
import re
from pathlib import Path

from conftest import mk_chunk, pass_validate, run_pipeline

from texlate.latex import parse_tex, reconstruct
from texlate.xlat import pipeline as pl
from texlate.xlat.state import ChunkRecord, StateStore

_FUSE_RX = re.compile(r"\\textbf\{?(\[\[[A-Z]+_\d+\]\])\}?")
_FUSE_TO = r"\\te\1xtbf"


class _Fuser(pl.MockTranslator):
    r"""``\textbf[[PH]]``/``\textbf{[[PH]]}`` 融成 ``\te[[PH]]xtbf``——挪位缺陷签名复现。

    ``marker`` 给了就只污染含该字样的输入（净块对照用）。
    """

    def __init__(self, marker: str | None = None) -> None:
        """``marker``：只污染 ``user`` 含此字样的调用；None = 全污染。"""
        super().__init__()
        self.marker = marker

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """mock 译文 + cs 名中段融合（批量形态逐成员行内替换）。"""
        raw = await super().translate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        if self.marker is not None and self.marker not in user:
            return raw
        return _FUSE_RX.sub(_FUSE_TO, raw)


class TestIntercept:
    """命中即 fault + skipped + 回退原文——断名 cs 绝不进 splice。"""

    def test_fused_chunk_faults_and_falls_back(self) -> None:
        """单翻路径：``\\te[[MATH_1]]xtbf`` → fault，translation=源文。"""
        src = "Long prose \\textbf[[MATH_1]] " + "x" * 400
        out = run_pipeline(
            [mk_chunk(src, "c1")], translator=_Fuser(), validator=pass_validate
        )
        r = out[0]
        assert r.status == "fault"
        assert r.skipped
        assert r.translation == src
        assert r.error_kind == "validate"
        assert "ph_in_cs:1" in r.warnings
        assert "fused into cs name" in r.skip_reason

    def test_mixed_run_only_dirty_chunk_faults(self) -> None:
        """论文级降格粒度：脏块 fault、净块 ok——不拖全篇。"""
        chunks = [
            mk_chunk("dirty-marker prose \\textbf[[MATH_1]] " + "x" * 400, "dirty"),
            mk_chunk("clean prose " + "y" * 400, "clean"),
        ]
        out = run_pipeline(
            chunks, translator=_Fuser(marker="dirty-marker"), validator=pass_validate
        )
        by_id = {r.chunk_id: r for r in out}
        assert by_id["dirty"].status == "fault"
        assert by_id["clean"].status == "ok"


class TestNoFalsePositive:
    """双侧夹持外的合法形态不误伤。"""

    def test_tail_adjacent_cs_ph_ok(self) -> None:
        """``\\protect[[REF_1]]`` 尾邻合法形（corpus 高频）——不拦。"""
        src = "Long prose \\protect[[REF_1]] " + "x" * 400
        out = run_pipeline(
            [mk_chunk(src, "c1")],
            translator=pl.MockTranslator(),
            validator=pass_validate,
        )
        assert out[0].status == "ok"
        assert not any(w.startswith("ph_in_cs") for w in out[0].warnings)

    def test_src_same_shape_net_diff_exempt(self) -> None:
        """src 自带 ``\\lq[[CMD_1]]angular`` 同形，zh 忠实回显——净差零不拦。"""

        class Echo(pl.MockTranslator):
            async def translate(self, *, user: str, **_kw: object) -> str:
                return user

        src = "Long prose \\lq[[CMD_1]]angular-momentum " + "x" * 400
        out = run_pipeline(
            [mk_chunk(src, "c1")], translator=Echo(), validator=pass_validate
        )
        assert out[0].status == "ok"

    def test_zh_comment_fused_exempt(self) -> None:
        """zh 注释内的融合形被 ``mask_comments`` 屏蔽——不拦。"""
        src = "Long prose \\textbf[[MATH_1]] " + "x" * 400

        class CommentFuser(pl.MockTranslator):
            async def translate(self, *, user: str, **kw: object) -> str:
                raw = await super().translate(user=user, **kw)
                return f"{raw}\n% 备注 \\te[[MATH_1]]xtbf"

        out = run_pipeline(
            [mk_chunk(src, "c1")], translator=CommentFuser(), validator=pass_validate
        )
        assert out[0].status == "ok"


class TestCacheAndResume:
    """缓存/续跑两路存量污染的拦截与自愈。"""

    def test_poisoned_cache_hit_evicted_and_retranslated(self) -> None:
        """脏缓存命中 → 命中即清 + 落回重翻自愈（曾永远 fault 冻结：命中→拦截→fault 每轮循环）。"""
        c = mk_chunk("Long prose \\textbf[[MATH_1]] " + "x" * 400, "c1")
        cache: dict[str, str] = {}
        t = pl.MockTranslator()
        pipe = pl.XlatPipeline(t, cache=cache)
        key = pipe._seg_key(c)  # noqa: SLF001 -- 造毒须触键
        cache[key] = "这是译文 \\te[[MATH_1]]xtbf"
        out = asyncio.run(pipe.run([c]))
        r = out[0]
        assert r.status == "ok"  # 毒条目被清 → 真重翻 → 痊愈
        assert t.calls
        assert "\\te[[MATH_1]]xtbf" not in cache[key]  # 同键已被干净译文改写

    def test_resume_stale_ok_record_retranslates(self, tmp_path: Path) -> None:
        """warning 时代落盘的 ok 融合记录 → 续跑降 fault 重翻。"""
        outdir = tmp_path / "out"
        src = "Long prose \\textbf[[MATH_1]] " + "x" * 400
        store = StateStore(outdir)
        store.start(1)
        store.record(
            ChunkRecord(
                chunk_id="c1",
                source=src,
                translation="这是译文 \\te[[MATH_1]]xtbf",
                status="ok",
            )
        )
        store.finish()

        t = pl.MockTranslator()
        out = run_pipeline(
            [mk_chunk(src, "c1")], translator=t, state=StateStore(outdir)
        )
        assert t.calls  # 旧记录被拦截踢出 completed——真重翻发生
        assert out[0].status == "ok"


class TestDownstreamContract:
    """拦截结果与 splice / L2 回灌 / auth 闸的契约面。"""

    def test_splice_never_sees_fused_zh(self) -> None:
        """真 splice 验证：fault 块不进 trans → reconstruct 回原文、零断名。"""
        doc = (
            "\\documentclass{article}\n\\begin{document}\n"
            "First \\textbf{$x$} with some english text for translation.\n\n"
            "Second paragraph also has english prose content here.\n"
            "\\end{document}\n"
        )
        res = parse_tex(doc)
        assert len(res.chunks) >= 2  # noqa: PLR2004 -- 合成文档至少两块
        chunks = [
            pl.chunk_to_in(c, chunk_id=str(c.id), ph_map=res.ph_map) for c in res.chunks
        ]
        out = run_pipeline(chunks, translator=_Fuser(), validator=pass_validate)
        assert any(r.status == "fault" for r in out)

        # e2e 口径：仅 status==ok 进 trans dict，其余 reconstruct 回源文
        trans = {int(r.chunk_id): r.translation for r in out if r.status == "ok"}
        spliced = reconstruct(res, trans)
        assert "\\textbf{$x$}" in spliced  # fault 块回退原文——融合译文未进 splice
        assert "xtbf" not in spliced.replace("\\textbf", "")

    def test_retranslate_fused_falls_back(self) -> None:
        """L2 回灌同受拦截——重译产物带融合 → fault，调用方回落原文。"""
        pipe = pl.XlatPipeline(translator=_Fuser(), validator=pass_validate)
        c = mk_chunk("Long prose \\textbf[[MATH_1]] " + "x" * 400, "c1")
        r = asyncio.run(pipe.retranslate_chunk(c, "compile error here"))
        assert r is not None
        assert r.status == "fault"
        assert r.skipped
        assert r.translation == c.content
        assert r.error_kind == "validate"

    def test_intercepted_chunk_is_non_auth_outcome(self) -> None:
        """真发过请求的拦截块计 non_auth——与正常非-auth 结果同口径。"""
        pipe = pl.XlatPipeline(translator=_Fuser(), validator=pass_validate)
        out = asyncio.run(
            pipe.run([mk_chunk("Long prose \\textbf[[MATH_1]] " + "x" * 400, "c1")])
        )
        assert out[0].error_kind == "validate"
        assert pipe.auth_gate.non_auth == 1
        assert not pipe.auth_gate.tripped
