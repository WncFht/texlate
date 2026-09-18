"""mnras texmf 遮蔽退役 + vendor 补丁件平铺修复链单测。

实证背景 (corpus_v3 1206.0291, geomreverify #57 stagerun 残格):
mn2e stub ``needs:["mnras.cls"]`` → ``eng.install_file`` → ``tlmgr
--usermode install mnras`` → 上游 v3.2 病件落 usertree
``_texmf/home/tex/latex/mnras/`` —— ``\\def\\ds@usegraphicx{\\@usegraphicxtrue
\\usepackage{graphicx}}`` 把 ``\\usepackage`` 写进 ``\\ds@`` 选项声明体,
``\\ProcessOptions`` 执行 usegraphicx 选项 → ``mnras.cls:114: LaTeX Error:
\\RequirePackage or \\LoadClass in Options Section`` 硬错 (cat=other)。
宿主 ``~/texmf`` 常驻副本同病 (TEXMFHOME 链尾保持可见 → 同样可达, 只遮蔽不退役)。
退役→missing→vendored_fetch(11.5) 名义链不可达: ``install_file`` (order 10)
先截 missing_file (宿主探得 already-present / tlmgr 重装同病上游件) ——
规则脚本自给: ``find . ../_texmf/home`` 双根扫 (生产内嵌 + stagerun 兄弟
式两布局), 指纹闸 (剥注释后 ``\\ds@usegraphicx`` 行内联
``\\usepackage|\\RequirePackage``) 确证才 mv ``.fixloop-iso``;
``texlate patch`` / ``texlate-fixloop-injected`` 双标跳过防自拆; python
桥 ``_vendor_root`` 钉件平铺 ``./mnras.cls`` —— kpathsea cwd 序压过一切
texmf 树件。
"""

from pathlib import Path

from texlate.compile.fixloop import Ruleset, actions, fixloop, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.fixloop.logparse import ErrReport, parse_text

_VENDOR_DIR = (
    Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor/files"
)
_RULE_ID = "mnras_texmf_shadow_retire"

# 1206.0291 geomreverify 实证首错 (file-line-error 形态, cat=other pay=null)
_ERR_OPTIONS = (
    "/work/1206.0291/_texmf/home/tex/latex/mnras/mnras.cls:114: "
    "LaTeX Error: \\RequirePackage or \\LoadClass in Options Section."
)
_ERR_OPTIONS_CTX = (
    "See the LaTeX manual or LaTeX Companion for explanation.\n"
    "Type  H <return>  for immediate help.\n"
    "l.114 \\ProcessOptions"
)
# '!' 形态同款: rep.first 无文件名, "Options Section" 字面同闸收
_BANG_ERR = "! LaTeX Error: \\RequirePackage or \\LoadClass in Options Section.\n"
# 签名散格变体: 同文件其他错 (syntax / undefined_cs) —— mnras.cls 点名在
_ERR_MISSINGNUM = (
    "/work/1206.0291/_texmf/home/tex/latex/mnras/mnras.cls:114: "
    "Missing number, treated as zero."
)
_ERR_UNDEF = (
    "/work/1206.0291/_texmf/home/tex/latex/mnras/mnras.cls:200: "
    "Undefined control sequence.\nl.200 \\mn@foo"
)

CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"

# 上游 v3.2 病件指纹形: \ds@usegraphicx 行内联 \usepackage
_BUGGY_CLS = (
    "% mnras.cls v3.2 (upstream)\n"
    "\\newif\\if@usegraphicx\n"
    "\\def\\ds@usegraphicx{\\@usegraphicxtrue\\usepackage{graphicx}}\n"
    "\\ProcessOptions\\relax\n"
)
# vendor 补丁形 (无标外来件): ds@usegraphicx 行净 + usepackage 推迟到他行 → 指纹阴性
_SAFE_CLS = (
    "% foreign safe copy\n"
    "\\def\\ds@usegraphicx{\\@usegraphicxtrue}\n"
    "\\if@usegraphicx\n  \\usepackage{graphicx}\n\\fi\n"
)
# 补丁标件: marker 在 → 首闸跳过 (即便行面像病件)
_PATCHED_CLS = (
    "% texlate patch: \\usepackage deferred past \\ProcessOptions\n"
    "\\def\\ds@usegraphicx{\\@usegraphicxtrue}\n"
)
# 本引擎注入件: 指纹标在 → 首闸跳过
_INJECTED_CLS = (
    "% texlate-fixloop-injected: 0123456789ab\n"
    "\\def\\ds@usegraphicx{\\@usegraphicxtrue\\usepackage{graphicx}}\n"
)
# 注释载件: 病形只在注释行 → 剥注释后指纹阴性 → 不动
_COMMENTED_CLS = (
    "% \\def\\ds@usegraphicx{\\@usegraphicxtrue\\usepackage{graphicx}}\n"
    "\\def\\ds@usegraphicx{\\@usegraphicxtrue}\n"
)


def _rs() -> Ruleset:
    return load_ruleset()


def _rule() -> Rule:
    return next(r for r in _rs().rules if r.id == _RULE_ID)


def _classify(head_text: str) -> tuple[str | None, str | None]:
    rep = parse_text(head_text + "\n")
    return _rs().taxonomy.classify(rep)


def _plant_cls(wdir: Path, body: str = _BUGGY_CLS) -> Path:
    """usertree 生产内嵌布局落件: ``wdir/_texmf/home/tex/latex/mnras/mnras.cls``。"""
    f = wdir / "_texmf/home/tex/latex/mnras/mnras.cls"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    return f


# ---------------------------------------------------------------- taxonomy
def test_taxonomy_options_section_is_other() -> None:
    """实证签名: Options Section LaTeX Error → other (兜底格)。"""
    cat, _ = _classify(_ERR_OPTIONS + "\n" + _ERR_OPTIONS_CTX)
    assert cat == "other"


def test_taxonomy_missing_number_is_syntax() -> None:
    """同文件 Missing number 变体 → syntax (签名散格同闸收)。"""
    cat, _ = _classify(_ERR_MISSINGNUM)
    assert cat == "syntax"


def test_taxonomy_undef_is_undefined_cs() -> None:
    """同文件 Undefined cs 变体 → undefined_cs。"""
    cat, _ = _classify(_ERR_UNDEF)
    assert cat == "undefined_cs"


# ---------------------------------------------------------------- 钉版面
def test_vendored_mnras_pinned_patch() -> None:
    """vendor/files/mnras.cls 钉版: 补丁标 + ds@usegraphicx 行净 + 推迟载入块。"""
    text = (_VENDOR_DIR / "mnras.cls").read_text(encoding="utf-8")
    assert "% texlate patch" in text
    assert "\\def\\ds@usegraphicx{\\@usegraphicxtrue}" in text
    assert "\\if@usegraphicx" in text
    assert "\\ProcessOptions\\relax" in text
    # 指纹阴性自洽: 剥注释后无 ds@usegraphicx 行载 \usepackage/\RequirePackage
    for line in text.splitlines():
        if line.lstrip().startswith("%") or "ds@usegraphicx" not in line:
            continue
        assert "\\usepackage" not in line
        assert "\\RequirePackage" not in line


# ---------------------------------------------------------------- 规则接线
def test_rule_wired_loop_phase() -> None:
    """规则挂 loop 相 order 11.91 → run_tool sh -c 指纹退役 + vendor 平铺。"""
    rule = _rule()
    assert rule.order == 11.91  # noqa: PLR2004 - schema 断言值
    cats = {c.get("category") for c in rule.when["any"]}
    assert cats == {"syntax", "undefined_cs", "other"}
    assert "Options Section" in rule.condition["ctx_suggests"]
    assert "mnras" in rule.condition["ctx_suggests"]
    globs = {c.get("cache_dir_glob") for c in rule.condition["any"]}
    assert globs == {"**/mnras.cls", "../_texmf/home/**/mnras.cls"}
    assert rule.condition["tool_available"] == "sh"
    assert rule.action["kind"] == "run_tool"
    argv = rule.action["params"]["argv"]
    assert argv[:2] == ["sh", "-c"]
    assert "mnras.cls" in argv[2]
    assert "fixloop-iso" in argv[2]
    assert "ds@usegraphicx" in argv[2]
    assert "texlate patch" in argv[2]  # 补丁标闸: 不退役 vendor 件
    assert "texlate-fixloop-injected" in argv[2]  # 指纹闸: 不退役本引擎注入件
    assert "_vendor_root" in argv[2]  # 平铺臂: 补丁件自给 (vendored_fetch 链不可达)


def test_rule_order_neighbors() -> None:
    """order 排序自洽: pstricks(11.9) < 本规则 < abstract_edef(11.95) < legacy_pkg_shim(12)。"""
    orders = {r.id: r.order for r in _rs().phase("loop")}
    assert orders["pstricks_add_pair_retire"] < orders[_RULE_ID]
    assert orders[_RULE_ID] < orders["abstract_edef_capture_neutralize"]
    assert orders[_RULE_ID] < orders["legacy_pkg_shim"]


# ---------------------------------------------------------------- condition 闸
def test_cond_skip_when_file_absent(tmp_path: Path) -> None:
    """wdir 无 mnras.cls → cache_dir_glob 闸拒 (不动别格错)。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _ERR_OPTIONS + "\n" + _ERR_OPTIONS_CTX
    ok, why = actions._cond_ok(  # noqa: SLF001 - 闸行为直驱
        _rule().condition, _rule(), ctx, None, None
    )
    assert not ok
    assert "any" in why  # ctx_suggests 已过 → 是 glob any 臂拒


def test_cond_skip_when_error_elsewhere(tmp_path: Path) -> None:
    """错误不点名 mnras.cls/Options Section (别包错) → ctx_suggests 闸拒。"""
    _plant_cls(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = "./main.tex:10: Undefined control sequence.\nl.10 \\foo\n"
    ok, _ = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert not ok


def test_cond_pass_wdir_cls(tmp_path: Path) -> None:
    """生产内嵌布局: wdir/_texmf/home 下病件在场 + 实证签名 → 闸过。"""
    _plant_cls(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _ERR_OPTIONS + "\n" + _ERR_OPTIONS_CTX
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert ok, why


def test_cond_pass_sibling_usertree(tmp_path: Path) -> None:
    """stagerun 兄弟式: wdir=splice, 病件在 ../_texmf/home → ../ 闸过。"""
    splice = tmp_path / "splice"
    splice.mkdir()
    cls = tmp_path / "_texmf/home/tex/latex/mnras/mnras.cls"
    cls.parent.mkdir(parents=True)
    cls.write_text(_BUGGY_CLS, encoding="utf-8")
    ctx = LoopCtx(wdir=splice, engine_name="xelatex")
    ctx.err_head = _ERR_OPTIONS + "\n" + _ERR_OPTIONS_CTX
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert ok, why


def test_cond_pass_bang_form(tmp_path: Path) -> None:
    """'!' 形态: 文件名缺席但 "Options Section" 字面在 rep.first → 同闸收。"""
    _plant_cls(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _BANG_ERR + _ERR_OPTIONS_CTX
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert ok, why


# ---------------------------------------------------------------- 动作直驱 (真 sh)
def test_apply_retires_usertree_cls_and_plants(tmp_path: Path) -> None:
    """_apply 真跑 sh: usertree 病件 → .fixloop-iso + vendor 补丁件平铺 ./mnras.cls。"""
    cls = _plant_cls(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert not cls.exists()
    assert (cls.parent / "mnras.cls.fixloop-iso").read_text() == _BUGGY_CLS
    planted = (tmp_path / "mnras.cls").read_text(encoding="utf-8")
    assert planted == (_VENDOR_DIR / "mnras.cls").read_text(encoding="utf-8")
    assert "% texlate patch" in planted


def test_apply_retires_sibling_usertree(tmp_path: Path) -> None:
    """stagerun 兄弟式: ../_texmf/home 病件退役 + 平铺落 wdir (splice)。"""
    splice = tmp_path / "splice"
    splice.mkdir()
    cls = tmp_path / "_texmf/home/tex/latex/mnras/mnras.cls"
    cls.parent.mkdir(parents=True)
    cls.write_text(_BUGGY_CLS, encoding="utf-8")
    ctx = LoopCtx(wdir=splice, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert not cls.exists()
    assert (cls.parent / "mnras.cls.fixloop-iso").exists()
    planted = splice / "mnras.cls"
    assert planted.read_text(encoding="utf-8") == (_VENDOR_DIR / "mnras.cls").read_text(
        encoding="utf-8"
    )


def test_apply_retires_wdir_root_cls(tmp_path: Path) -> None:
    """稿自带 ./mnras.cls 病件 → 退役后原位递补 vendor 补丁件。"""
    (tmp_path / "mnras.cls").write_text(_BUGGY_CLS, encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert (tmp_path / "mnras.cls.fixloop-iso").read_text() == _BUGGY_CLS
    planted = (tmp_path / "mnras.cls").read_text(encoding="utf-8")
    assert planted == (_VENDOR_DIR / "mnras.cls").read_text(encoding="utf-8")


def test_apply_skips_patched_marker(tmp_path: Path) -> None:
    """texlate patch 标件不退役 —— vendor 件重扫防自拆。"""
    cls = _plant_cls(tmp_path, _PATCHED_CLS)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert cls.read_text(encoding="utf-8") == _PATCHED_CLS
    assert not (cls.parent / "mnras.cls.fixloop-iso").exists()


def test_apply_skips_fingerprint_clean_foreign(tmp_path: Path) -> None:
    """指纹阴性外来件 (ds@ 行净, 无标) 不退役 —— 已修副本不冤。"""
    cls = _plant_cls(tmp_path, _SAFE_CLS)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert cls.read_text(encoding="utf-8") == _SAFE_CLS


def test_apply_skips_commented_buggy_line(tmp_path: Path) -> None:
    """病形只在注释行 → 剥注释指纹阴性 → 不动 (纯注释载件不冤)。"""
    cls = _plant_cls(tmp_path, _COMMENTED_CLS)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert cls.read_text(encoding="utf-8") == _COMMENTED_CLS


def test_apply_skips_injected_marker(tmp_path: Path) -> None:
    """texlate-fixloop-injected 指纹件不退役 —— 防退役→重投死循环。"""
    cls = _plant_cls(tmp_path, _INJECTED_CLS)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert cls.read_text(encoding="utf-8") == _INJECTED_CLS


def test_apply_does_not_clobber_root_cls(tmp_path: Path) -> None:
    """./mnras.cls 已占 (稿自带/先投件) → 平铺臂不覆写, 仅退役树内病件。"""
    _plant_cls(tmp_path)
    (tmp_path / "mnras.cls").write_text(_SAFE_CLS, encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert (tmp_path / "mnras.cls").read_text(encoding="utf-8") == _SAFE_CLS


def test_apply_idempotent_second_run(tmp_path: Path) -> None:
    """二跑幂等: 平铺件带 patch 标 → find 跳过, [ -f ] 闸拒再平铺。"""
    cls = _plant_cls(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok1, _ = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    ok2, _ = actions._apply(_rule(), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok1
    assert ok2
    planted = (tmp_path / "mnras.cls").read_text(encoding="utf-8")
    assert planted == (_VENDOR_DIR / "mnras.cls").read_text(encoding="utf-8")
    assert not (tmp_path / "mnras.cls.fixloop-iso").exists()  # vendor 件不被退役
    assert (cls.parent / "mnras.cls.fixloop-iso").read_text() == _BUGGY_CLS


# ---------------------------------------------------------------- e2e
class _MockRes:
    """impl CompRes duck-type 替身 (test_fixloop_pstadd 同款微缩)。"""

    def __init__(self, wdir: Path, spec: dict) -> None:
        self.log_path = wdir / "main.log"
        self.log_path.write_text(spec.get("log", ""), encoding="utf-8")
        self.pdf = wdir / "main.pdf" if spec.get("pdf") else None
        if self.pdf is not None:
            self.pdf.write_bytes(b"%PDF-1.4 fake")
        self.pdf_bytes = self.pdf.stat().st_size if self.pdf else 0
        self.timed_out = False
        self.killed_signal = None
        self.seconds = 0.05
        self.stdout_tail = ""
        self.log_text = ""

    @property
    def has_pdf(self) -> bool:
        return self.pdf is not None and self.pdf_bytes > 0


class _MockEngine:
    """逐轮吐 spec; probe_file 只认 available 集 (模拟系统 texmf)。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr", "updmap"})

    def __init__(self, script: list, *, available: set[str] | None = None) -> None:
        self.script = list(script)
        self.available = available or set()
        self.rounds = 0

    def compile(self, wdir: Path, main: str, **_kw: object) -> _MockRes:
        del main  # mock 按轮吐 spec, 不编译真文件
        i = min(self.rounds, len(self.script) - 1)
        self.rounds += 1
        return _MockRes(Path(wdir), self.script[i])

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if cwd is not None and (Path(cwd) / fname).is_file():
            return str(Path(cwd) / fname)
        return f"/texmf/{fname}" if fname in self.available else None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False  # 装不上 → 反证平铺臂独立收敛 (不靠 install_file 链)

    def rebuild_fontmaps(self) -> bool:
        return True

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _proj(tmp_path: Path) -> Path:
    """生产内嵌布局: wdir 根 + wdir/_texmf/home usertree 病件。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{mn2e}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    _plant_cls(tmp_path)
    return tmp_path


def _proj_sibling(tmp_path: Path) -> Path:
    """stagerun 兄弟式: proj=splice, usertree 在 ../_texmf/home。"""
    splice = tmp_path / "splice"
    splice.mkdir()
    (splice / "main.tex").write_text(
        "\\documentclass{mn2e}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    cls = tmp_path / "_texmf/home/tex/latex/mnras/mnras.cls"
    cls.parent.mkdir(parents=True)
    cls.write_text(_BUGGY_CLS, encoding="utf-8")
    return splice


def _sh_runner(
    argv: list[str], timeout: int, wdir: Path
) -> tuple[int, str, float, bool]:
    """真跑 sh -c 的 runner (argv, timeout, wdir → rc,out,sec,to)。

    不仿真脚本语义 —— subprocess 原样执行, find/指纹闸/平铺臂都走真件。
    """
    import subprocess  # noqa: PLC0415 - 测试替身局部用

    p = subprocess.run(  # noqa: S603 - argv 列表无 shell 拼接; sh -c 是规则自身的原语
        argv,
        cwd=wdir,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or ""), 0.0, False


def test_e2e_retire_then_plant_shadows(tmp_path: Path) -> None:
    """整链 (内嵌布局): Options Section → 树内病件退役 + vendor 平铺 → clean。"""
    eng = _MockEngine(
        [
            {"log": _ERR_OPTIONS + "\n" + _ERR_OPTIONS_CTX + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path), eng, runner=_sh_runner)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == _RULE_ID for a in cell["actions"])
    iso = tmp_path / "_texmf/home/tex/latex/mnras/mnras.cls.fixloop-iso"
    assert iso.exists()
    assert not (tmp_path / "_texmf/home/tex/latex/mnras/mnras.cls").exists()
    planted = (tmp_path / "mnras.cls").read_text(encoding="utf-8")
    assert planted == (_VENDOR_DIR / "mnras.cls").read_text(encoding="utf-8")


def test_e2e_retire_sibling_layout(tmp_path: Path) -> None:
    """整链 (stagerun 兄弟式): ../_texmf/home 病件退役 + splice/mnras.cls 平铺。"""
    eng = _MockEngine(
        [
            {"log": _ERR_OPTIONS + "\n" + _ERR_OPTIONS_CTX + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    splice = _proj_sibling(tmp_path)
    cell = fixloop(splice, eng, runner=_sh_runner)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == _RULE_ID for a in cell["actions"])
    cls = tmp_path / "_texmf/home/tex/latex/mnras/mnras.cls"
    assert not cls.exists()
    assert cls.with_name("mnras.cls.fixloop-iso").exists()
    planted = splice / "mnras.cls"
    assert planted.read_text(encoding="utf-8") == (_VENDOR_DIR / "mnras.cls").read_text(
        encoding="utf-8"
    )


def test_e2e_no_fire_on_other_error(tmp_path: Path) -> None:
    """非 mnras 签名: 别包错 → 本规则不动树内病件。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\foo\n\\end{document}\n",
        encoding="utf-8",
    )
    cls = _plant_cls(tmp_path)
    eng = _MockEngine(
        [
            {"log": "./main.tex:3: Undefined control sequence.\nl.3 \\foo\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(tmp_path, eng, runner=_sh_runner)
    assert not any(a["rule"] == _RULE_ID for a in cell["actions"])
    assert cls.read_text(encoding="utf-8") == _BUGGY_CLS
    assert not (tmp_path / "mnras.cls").exists()


def test_e2e_planted_not_retired_breaks_loop(tmp_path: Path) -> None:
    """vendor 件已平铺仍报同名错: patch 标闸保件不退役 —— 无退役→重投环。"""
    eng = _MockEngine(
        [
            {"log": _ERR_OPTIONS + "\n" + _ERR_OPTIONS_CTX + "\n"},
            # 平铺的 vendor 件仍报 Options Section (假想签名变体重投场景):
            # dedup 外再跑脚本也必须跳过 patch 标件, 不得退役→平铺循环
            {
                "log": "./mnras.cls:120: LaTeX Error: \\RequirePackage or "
                "\\LoadClass in Options Section.\nl.120 \\fi\n"
            },
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path), eng, runner=_sh_runner)
    # r2 同签名错被 dedup 拦 (rule:None 已 applied) → stuck → salvage 兜底出 pdf
    assert cell["verdict"] == "best_effort_pdf"
    planted = (tmp_path / "mnras.cls").read_text(encoding="utf-8")
    assert planted == (_VENDOR_DIR / "mnras.cls").read_text(encoding="utf-8")
    assert not (tmp_path / "mnras.cls.fixloop-iso").exists()
