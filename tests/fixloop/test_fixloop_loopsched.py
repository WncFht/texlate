r"""loopsched (task #144): mid-loop 落件同步 —— 指纹 diff → ``_texts`` 失效 +
落件前 ``{rule}:{pay}`` dedup 键过期 (defcensus E-route 病族复现钉)。

E-route 机制: 站点臂烧键后, ``install_file``/vendored/run_tool 类动作把
新的撞名站点带进 fileset (``.def`` 间接装载天然在 ``static_precheck``
``tex_files`` 扫面之外), 同签下轮复报时旧烧键让 ``_match_apply`` 在
``key in applied`` 处静默跳过 —— 站点臂永不再火, 残签滞留至
unfixable/stuck。修复 = 每个规则应用点前后做 wdir 指纹 diff
(``_landing_sync``): 落件即失效 ``_texts`` 对应条目 + 过期基线前
烧键, 刚派发规则的自身键保留 (``applied - pre_applied``)。

钉三层:
  - 单元: ``_landing_sync`` 键面语义 (pre 过期 / post 保留 / 无落件
    零动作) + ``_texts`` 覆盖写与 miss→None 毒化失效;
  - e2e 正例 ×2: 新件落盘 + 覆盖写落盘两形, 站点臂重派 → clean;
  - e2e 反例: 无新落件 → 同签 dedup 依旧压重派 → miss 落兜底。
"""

from pathlib import Path

from _fixloopkit import MockEngine, MockRes

from texlate.compile.fixloop import fixloop, load_ruleset
from texlate.compile.fixloop._builtins_common import _wdir_fingerprint
from texlate.compile.fixloop.engine import LoopCtx, _landing_sync

_ALDEF_ZZ = (
    "! LaTeX cmd Error: Command '\\zz' already defined.\n"
    "l.2 \\NewDocumentCommand{\\zz}\n"
)
_ALDEF_WW = (
    "! LaTeX cmd Error: Command '\\ww' already defined.\n"
    "l.2 \\NewDocumentCommand{\\ww}\n"
)
_MISS_QUX = "! LaTeX Error: File `qux.sty' not found.\nl.3 \\input{baropts.def}\n"
_MISS_DEP2 = "! LaTeX Error: File `dep2.sty' not found.\nl.3 \\input{depopts.def}\n"
_CLEAN = "This is XeTeX\nOutput written on main.pdf (1 page).\n"

_MAIN_ZZ = (
    "\\documentclass{article}\n"
    "\\NewDocumentCommand{\\zz}{}{M}\n"
    "\\usepackage{bar}\n"
    "\\begin{document}\nx\n\\end{document}\n"
)
_BAR = (
    "\\ProvidesPackage{bar}\n\\NewDocumentCommand{\\zz}{}{BAR}\n\\input{baropts.def}\n"
)
# ``.def`` 不在 scan_install 的 ``tex_files`` 扫面 (.tex/.sty/.cls) —— qux
# 的装载需求对 static_precheck 隐形, 缺档只能 mid-loop 经 missing_file
# 派发补; ``bar.sty`` 自身 r1 在 NDC 撞名行炸停, ``\input{baropts.def}``
# 要等站点臂清位后才执行到 —— 剧本顺序与真 TeX 执行序一致。
_BAROPTS = "\\RequirePackage{qux}\n"
_QUX = "\\ProvidesPackage{qux}\n\\NewDocumentCommand{\\zz}{}{QUX}\n"

_MAIN_WW = (
    "\\documentclass{article}\n"
    "\\NewDocumentCommand{\\ww}{}{M}\n"
    "\\usepackage{dep}\n\\usepackage{foo}\n"
    "\\begin{document}\nx\n\\end{document}\n"
)
_DEP = (
    "\\ProvidesPackage{dep}\n\\NewDocumentCommand{\\ww}{}{DEP}\n\\input{depopts.def}\n"
)
_DEPOPTS = "\\RequirePackage{dep2}\n"
_DEP2 = "\\ProvidesPackage{dep2}\n"
_FOO_V1 = "\\ProvidesPackage{foo}\n"
# 覆盖写落盘: dep2 补装伴写的 foo.sty 新版带 \\ww 撞名站点 —— r1 站点图
# 已把 v1 无站态读进 ``_texts``, 指纹 diff 失效后才见 v2 站点。
_FOO_V2 = "\\ProvidesPackage{foo}\n\\NewDocumentCommand{\\ww}{}{FOO}\n"


class _LandEngine(MockEngine):
    """MockEngine + 落件表: ``install_file`` 把 ``drops[fname]`` 写进 wdir,
    ``side_writes`` 为 dep-fanout/vendor 伴写替身; ``probe_file`` 先查
    cwd 内实件再查 ``texmf`` 表 (kpathsea 替身)。"""

    caps = frozenset({"kpsewhich", "tlmgr"})
    halt_on_error = False  # 无次级探针——单错 log miss 直落裁决, 剧本确定性

    def __init__(
        self,
        script: list,
        *,
        drops: dict[str, str] | None = None,
        side_writes: dict[str, str] | None = None,
        texmf: dict[str, str] | None = None,
    ) -> None:
        super().__init__(script)
        self.drops = dict(drops or {})
        self.side_writes = dict(side_writes or {})
        self.texmf = dict(texmf or {})
        self.installed: list[str] = []
        self._wdir: Path | None = None

    def compile(self, wdir: Path, main: str, **kw: object) -> MockRes:
        self._wdir = Path(wdir)
        return super().compile(wdir, main, **kw)

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if cwd is not None:
            self._wdir = Path(cwd)
            hit = Path(cwd) / fname
            if hit.is_file():
                return str(hit)
        return self.texmf.get(fname)

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del font_related
        rel = fname.lstrip("/")
        if rel not in self.drops or self._wdir is None:
            return False
        for name, text in {rel: self.drops[rel], **self.side_writes}.items():
            p = self._wdir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        self.installed.append(rel)
        return True


def _proj(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------- 单元钉
def test_landing_sync_key_semantics(tmp_path: Path) -> None:
    """外部落件 → 基线前烧键过期 / 基线后保留 / ``_texts`` 失效;
    ``ctx.write`` 自改与无落件两形 → 键面零动作。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    a, later = tmp_path / "a.sty", tmp_path / "later.sty"
    a.write_text("v1", encoding="utf-8")
    ctx.io.written.clear()  # 派发窗开始: 自产写从零计账 (与三处 wrap 点同约)
    before = _wdir_fingerprint(tmp_path)
    ctx.ledger.applied.update({"ruleA:x", "ruleB:y"})
    pre = set(ctx.ledger.applied)
    assert ctx.read(a) == "v1"  # 旧文入缓存 (覆盖写毒化对象)
    assert ctx.read(later) is None  # miss→None 毒化入缓存
    # —— 外部落件: 裸写覆盖 + 新件 (install/vendor/run_tool 同形) ——
    a.write_text("v2 — longer", encoding="utf-8")
    later.write_text("new", encoding="utf-8")
    ctx.ledger.applied.add("ruleC:z")  # 基线后烧键 (刚派发规则自身)
    assert _landing_sync(ctx, before, pre) == 2  # noqa: PLR2004
    assert ctx.ledger.applied == {"ruleC:z"}
    assert ctx.read(a) == "v2 — longer"  # 覆盖写失效 → 读新文
    assert ctx.read(later) == "new"  # None 毒化失效 → 读实件
    # —— ctx.write 规则自改: accounted 写不过期键 (stucksem 实证:
    # 自产编辑稀释 dedup → 先火规则非幂等重派抢后位凭据门窗口);
    # 重写既有件同形——``written`` 按窗清零, 集差分看不出的重写
    # 仍记为自产 (loopsched 实证: run 级积累会让改写既有件误判外部) ——
    ctx.io.written.clear()
    ctx.ledger.applied.update({"ruleA:x", "ruleD:w"})
    before2 = _wdir_fingerprint(tmp_path)
    pre2 = set(ctx.ledger.applied)
    ctx.write(a, "v3 authored")  # regex_rewrite/站点前置同形
    assert _landing_sync(ctx, before2, pre2) == 0
    assert {"ruleA:x", "ruleD:w"} <= ctx.ledger.applied
    assert ctx.read(a) == "v3 authored"
    # —— 无落件: 键面与缓存零动作 ——
    ctx.io.written.clear()
    before3 = _wdir_fingerprint(tmp_path)
    assert _landing_sync(ctx, before3, set(ctx.ledger.applied)) == 0
    assert "ruleA:x" in ctx.ledger.applied


# ------------------------------------------------------------- e2e 正例
def test_install_landing_refires_site_arm(tmp_path: Path) -> None:
    """E-route 正例 (新件落盘): install 落件后同签轮站点臂重派。

    r1 already_def:\\zz → 站点前置清位 (烧 ``already_def_undefine:zz``);
    r2 missing_file:qux.sty (baropts.def 间接装载, precheck 扫面外) →
    install_file 落件; r3 同签复报 —— 修复前站点臂按旧烧键静默跳过
    (残签滞留 → unfixable), 修复后烧键过期重派 → qux.sty 吃到
    ``\\let`` 前置 → r4 clean。
    """
    _proj(
        tmp_path,
        {"main.tex": _MAIN_ZZ, "bar.sty": _BAR, "baropts.def": _BAROPTS},
    )
    eng = _LandEngine(
        [
            {"log": _ALDEF_ZZ},
            {"log": _MISS_QUX},
            {"log": _ALDEF_ZZ},
            {"log": _CLEAN, "pdf": True},
        ],
        drops={"qux.sty": _QUX},
        texmf={"article.cls": "/texmf/article.cls"},
    )
    cell = fixloop(tmp_path, eng, ruleset=load_ruleset())
    assert cell["verdict"] == "clean"
    qux = (tmp_path / "qux.sty").read_text(encoding="utf-8")
    assert "\\csname zz\\endcsname\\TeXlateUndefCs" in qux  # 落件吃到站点前置
    acts = [a["rule"] for a in cell["actions"]]
    # 烧键过期 → 同规则两轮各应用一次 (r1 清位 + r3 落件站点)
    assert acts.count("already_def_undefine") == 2  # noqa: PLR2004
    assert any("landing sync" in e for e in cell["log"])


def test_overwrite_landing_invalidates_site_cache(tmp_path: Path) -> None:
    """E-route 正例 (覆盖写落盘): 伴写改写既有件 → ``_texts`` 失效见新站点。

    r1 站点图把 foo.sty v1 无站态读进缓存; r2 install 落 dep2.sty 并伴写
    foo.sty v2 (带 \\ww 站点); r3 同签复报 —— 覆盖写不失效则站点图照供
    v1 残影, guilty 集缺 foo → 站点臂无活可干照烧键辞; 失效后见 v2 站
    → 前置 → clean。
    """
    _proj(
        tmp_path,
        {
            "main.tex": _MAIN_WW,
            "dep.sty": _DEP,
            "depopts.def": _DEPOPTS,
            "foo.sty": _FOO_V1,
        },
    )
    eng = _LandEngine(
        [
            {"log": _ALDEF_WW},
            {"log": _MISS_DEP2},
            {"log": _ALDEF_WW},
            {"log": _CLEAN, "pdf": True},
        ],
        drops={"dep2.sty": _DEP2},
        side_writes={"foo.sty": _FOO_V2},
        texmf={"article.cls": "/texmf/article.cls"},
    )
    cell = fixloop(tmp_path, eng, ruleset=load_ruleset())
    assert cell["verdict"] == "clean"
    foo = (tmp_path / "foo.sty").read_text(encoding="utf-8")
    assert "\\csname ww\\endcsname\\TeXlateUndefCs" in foo
    acts = [a["rule"] for a in cell["actions"]]
    assert acts.count("already_def_undefine") == 2  # noqa: PLR2004


# ------------------------------------------------------------- e2e 反例
def test_no_landing_keeps_dedup(tmp_path: Path) -> None:
    """E-route 反例: 无新落件 → 同签 dedup 依旧压重派。

    r2 同签复报但轮内零落件 → ``applied`` 键面不动 → 站点臂在
    ``key in applied`` 处静默跳过 (无拒绝事件) → miss →
    unfixable:already_def → 兜底 best_effort_pdf。dedup 语义不被
    落件同步稀释成每轮重估。"""
    _proj(
        tmp_path,
        {
            "main.tex": _MAIN_ZZ,
            "bar.sty": "\\ProvidesPackage{bar}\n\\NewDocumentCommand{\\zz}{}{BAR}\n",
        },
    )
    eng = _LandEngine(
        [{"log": _ALDEF_ZZ}, {"log": _ALDEF_ZZ}, {"log": _CLEAN, "pdf": True}],
        texmf={"article.cls": "/texmf/article.cls"},
    )
    cell = fixloop(tmp_path, eng, ruleset=load_ruleset())
    assert cell["verdict"] == "best_effort_pdf"
    acts = [a["rule"] for a in cell["actions"]]
    assert acts.count("already_def_undefine") == 1
    # 站点臂烧键静默跳过 —— 事件面唯见 r1 的 "apply ..." 行; 重派评估
    # 才会多出 "rule ...: skip (all offenders already cleared)" 类行。
    assert sum("already_def_undefine" in e for e in cell["log"]) == 1
    assert cell["rounds"][1]["category"] == "already_def"
