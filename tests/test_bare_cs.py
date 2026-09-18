r"""bare_cs 升格拦截：zh 文本域新增裸 cs → fault + 回退原文。

realpostfix2 归因：LLM 译文把数学 cs 写在 ``$`` 域外（0905.4907
``\alpha 发射体`` → ``Missing $`` 炸弹）或把 cs 与后随词粘合
（``\itemOC``/``\csnamebibitemNoStop`` → 未定义 cs）。validator 主层
（l0 ``_check_bare_cs``）之外，本层拦续跑 state/段级缓存旁路的 stale
脏译。判定 = ``textutil.bare_cs_net`` 双侧夹持净差：zh 自带 ``$..$``
内的数学 cs（合法修正方向）、src 自带同形、注释区、全小写延申
（``\citep`` 类真 cs）均不误伤。
"""

import asyncio
import re
from pathlib import Path

from conftest import mk_chunk, pass_validate, run_pipeline

from texlate.latex import parse_tex, reconstruct
from texlate.xlat import pipeline as pl
from texlate.xlat.state import ChunkRecord, StateStore

_NUM_RX = re.compile(r"^\s*\[(\d+)\]", re.MULTILINE)


def _member_of(user: str, marker: str) -> int | None:
    """批编码输入里含 ``marker`` 的成员号；单发/非编号输入 → ``None``。"""
    for ln in user.split("\n"):
        m = _NUM_RX.match(ln)
        if m is not None and marker in ln:
            return int(m.group(1))
    return None


def _splice_member(raw: str, k: int, payload: str) -> str:
    """``payload`` 拼进编号响应第 ``k`` 段段尾（成员缺失退化整响应尾注）。"""
    ms = list(_NUM_RX.finditer(raw))
    for i, m in enumerate(ms):
        if int(m.group(1)) == k:
            end = ms[i + 1].start() if i + 1 < len(ms) else len(raw)
            return f"{raw[:end]}{payload}\n{raw[end:]}"
    return f"{raw}{payload}"


class _Injector(pl.MockTranslator):
    r"""mock 译文尾部追加 ``payload``——``\alpha 发射体``/``$\alpha$``/注释形按需注入。

    ``marker`` 给了就只污染含该字样的输入（净块对照用）。批协议下注入点
    定位到 marker 所在成员段内——整响应尾注会落进最后成员段（73ffa4c
    全量入批后 marker 与尾注脱钩，曾把污染错配到净块成员上）。
    """

    def __init__(self, payload: str, marker: str | None = None) -> None:
        """``payload``：追加串；``marker``：只污染 ``user`` 含此字样的调用/成员。"""
        super().__init__()
        self.payload = payload
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
        """mock 译文 + 注入（批输入定位 marker 成员，单发尾注）。"""
        raw = await super().translate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        if self.marker is not None:
            if self.marker not in user:
                return raw
            k = _member_of(user, self.marker)
            if k is not None:
                return _splice_member(raw, k, self.payload)
        return f"{raw}{self.payload}"


_FUSE_RX = re.compile(r"\\textbf")
_FUSE_TO = r"\\textbfXY"  # \textbf → \textbfXY: 前缀 textbf(≥3) + 大写后缀 XY


class _Fuser(pl.MockTranslator):
    r"""``\textbf`` 粘合成 ``\textbfXY``——cs 吞间隔/后随词首字母粘连签名复现。"""

    async def translate(self, *, user: str, **kw: object) -> str:
        """mock 译文 + cs 名后缀粘连。"""
        raw = await super().translate(user=user, **kw)
        return _FUSE_RX.sub(_FUSE_TO, raw)


class TestIntercept:
    """命中即 fault + skipped + 回退原文——裸 cs 绝不进 splice。"""

    def test_math_cs_out_of_math_faults(self) -> None:
        """0905.4907 签名：``\\alpha 发射体`` 文本域裸写 → fault。"""
        src = "Long prose [[MATH_1]] " + "x" * 400
        out = run_pipeline(
            [mk_chunk(src, "c1")],
            translator=_Injector("\\alpha 发射体"),
            validator=pass_validate,
        )
        r = out[0]
        assert r.status == "fault"
        assert r.fell_back
        assert r.translation == src
        assert r.error_kind == "validate"
        assert "bare_cs:1" in r.warnings
        assert "bare cs injected" in r.skip_reason

    def test_fused_cs_faults(self) -> None:
        """``\\textbfXY`` 粘合形 → fault。"""
        src = "Long prose \\textbf[[MATH_1]] " + "x" * 400
        out = run_pipeline(
            [mk_chunk(src, "c1")], translator=_Fuser(), validator=pass_validate
        )
        r = out[0]
        assert r.status == "fault"
        assert r.fell_back
        assert r.translation == src
        assert any(w.startswith("bare_cs:") for w in r.warnings)

    def test_mixed_run_only_dirty_chunk_faults(self) -> None:
        """论文级降格粒度：脏块 fault、净块 ok——不拖全篇。"""
        chunks = [
            mk_chunk("dirty-marker prose [[MATH_1]] " + "x" * 400, "dirty"),
            mk_chunk("clean prose " + "y" * 400, "clean"),
        ]
        out = run_pipeline(
            chunks,
            translator=_Injector("\\alpha 发射体", marker="dirty-marker"),
            validator=pass_validate,
        )
        by_id = {r.chunk_id: r for r in out}
        assert by_id["dirty"].status == "fault"
        assert by_id["clean"].status == "ok"


class TestNoFalsePositive:
    """双侧夹持外的合法形态不误伤。"""

    def test_math_cs_inside_math_ok(self) -> None:
        """zh 自加 ``$\\alpha$``——数学域内是合法修正方向, 不拦。"""
        src = "Long prose [[MATH_1]] " + "x" * 400
        out = run_pipeline(
            [mk_chunk(src, "c1")],
            translator=_Injector(" $\\alpha$"),
            validator=pass_validate,
        )
        assert out[0].status == "ok"
        assert not any(w.startswith("bare_cs") for w in out[0].warnings)

    def test_src_same_shape_net_diff_exempt(self) -> None:
        """src 自带文本域 ``\\alpha``, zh 忠实回显——净差零不拦。"""

        class Echo(pl.MockTranslator):
            async def translate(self, *, user: str, **_kw: object) -> str:
                return user

        src = "Long prose \\alpha particle " + "x" * 400
        out = run_pipeline(
            [mk_chunk(src, "c1")], translator=Echo(), validator=pass_validate
        )
        assert out[0].status == "ok"

    def test_zh_comment_bare_exempt(self) -> None:
        """zh 注释内的 ``\\alpha`` 被 ``mask_comments`` 屏蔽——不拦。"""
        src = "Long prose [[MATH_1]] " + "x" * 400
        out = run_pipeline(
            [mk_chunk(src, "c1")],
            translator=_Injector("\n% 备注 \\alpha"),
            validator=pass_validate,
        )
        assert out[0].status == "ok"

    def test_lowercase_extension_real_cs_ok(self) -> None:
        """``\\cite``→``\\citep`` 全小写延申是真 cs 面——粘合判定要求大写后缀, 不拦。"""
        src = "Long prose \\cite ref " + "x" * 400

        class Citep(pl.MockTranslator):
            async def translate(self, *, user: str, **kw: object) -> str:
                raw = await super().translate(user=user, **kw)
                return raw.replace("\\cite", "\\citep")

        out = run_pipeline(
            [mk_chunk(src, "c1")], translator=Citep(), validator=pass_validate
        )
        assert out[0].status == "ok"

    def test_new_legit_text_cs_ok(self) -> None:
        """zh 新增 ``\\footnote{注}``——定义内文本 cs 非炸弹, 不拦。"""
        src = "Long prose " + "x" * 400
        out = run_pipeline(
            [mk_chunk(src, "c1")],
            translator=_Injector("\\footnote{这是译文}"),
            validator=pass_validate,
        )
        assert out[0].status == "ok"


class TestCacheAndResume:
    """缓存/续跑两路存量污染的拦截与自愈。"""

    def test_poisoned_cache_hit_evicted_and_retranslated(self) -> None:
        """脏缓存命中 → 命中即清 + 落回重翻自愈（曾永远 fault 冻结：命中→拦截→fault 每轮循环）。"""
        c = mk_chunk("Long prose [[MATH_1]] " + "x" * 400, "c1")
        cache: dict[str, str] = {}
        t = pl.MockTranslator()
        pipe = pl.XlatPipeline(t, cache=cache)
        key = pipe._seg_key(c)  # noqa: SLF001 -- 造毒须触键
        cache[key] = "这是译文 \\alpha 发射体"
        out = asyncio.run(pipe.run([c]))
        r = out[0]
        assert r.status == "ok"  # 毒条目被清 → 真重翻 → 痊愈
        assert t.calls
        assert "\\alpha" not in cache[key]  # 同键已被干净译文改写

    def test_resume_stale_ok_record_retranslates(self, tmp_path: Path) -> None:
        """warning 时代落盘的 ok 裸 cs 记录 → 续跑降 fault 重翻。"""
        outdir = tmp_path / "out"
        src = "Long prose [[MATH_1]] " + "x" * 400
        store = StateStore(outdir)
        store.start(1)
        store.record(
            ChunkRecord(
                chunk_id="c1",
                source=src,
                translation="这是译文 \\alpha 发射体",
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
        """真 splice 验证：fault 块不进 trans → reconstruct 回原文、零粘名。"""
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
        assert "\\textbf{$x$}" in spliced  # fault 块回退原文——粘合译文未进 splice
        assert "textbfXY" not in spliced

    def test_retranslate_bare_falls_back(self) -> None:
        """L2 回灌同受拦截——重译产物带裸 cs → fault，调用方回落原文。"""
        pipe = pl.XlatPipeline(
            translator=_Injector("\\alpha 发射体"), validator=pass_validate
        )
        c = mk_chunk("Long prose [[MATH_1]] " + "x" * 400, "c1")
        r = asyncio.run(pipe.retranslate_chunk(c, "compile error here"))
        assert r is not None
        assert r.status == "fault"
        assert r.fell_back
        assert r.translation == c.content
        assert r.error_kind == "validate"

    def test_intercepted_chunk_is_non_auth_outcome(self) -> None:
        """真发过请求的拦截块计 non_auth——与正常非-auth 结果同口径。"""
        pipe = pl.XlatPipeline(
            translator=_Injector("\\alpha 发射体"), validator=pass_validate
        )
        out = asyncio.run(
            pipe.run([mk_chunk("Long prose [[MATH_1]] " + "x" * 400, "c1")])
        )
        assert out[0].error_kind == "validate"
        assert pipe.auth_gate.non_auth == 1
        assert not pipe.auth_gate.tripped
