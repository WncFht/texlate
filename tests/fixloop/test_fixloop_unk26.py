r"""implunk26 钉 —— unk26spec 七捆落地 (2026-09-20, unk26spec 车道普查)。

B1 ``era_bundle_shadow_retire`` (40-install.yaml order 11.92, cond-mat/
0103307+0103262): era pst-* 包捆 ld<sd 确证遮蔽 → vendored_shadow_isolate
早位宽 when (timeout 在列) 宽 exts (.def/.cfg 配套核同道退役; 同干
.tex 核经 paired 道 —— spec 原案 .tex 入 exts 会与 paired 道 double-move
撞缺件, builtin 无 moved 卫, 权属外故走安全偏差)。
B2 ``psfig_vendor_bridge`` (vendor/files/psfig.sty 全文换, astro-ph/
0103205+0103349): 真身 psfig v1.10 是 dvips ``\special{psfile}`` 输出
xelatex 永不可渲 → epsfig 官方仿真桥 (vendored_fetch 11.5 投递零 yaml 改)。
B3 ``doc_ifx_errmessage_demote`` (40-install.yaml order 11.94, cond-mat/
9612213): doc 导言区 ``\ifx<cs>\undefined..\errmessage`` 引擎护栏 →
``\errmessage`` 降级 ``\typeout`` (注入 hyperref 踩 ``\href`` 护栏中止)。
B4 ``special_psfile_abspath_basename`` (95-targeted.yaml order 18.55,
hep-ex/9412001): ``\special{psfile=/abs/…/x.ps}`` 作者机绝对径 → basename
(wdir 已带档可 flip clean; 18.6 占位臂次轮兜缺席格)。
B5 ``atdef_cat_wrap`` (95-targeted.yaml order 198.6, 0712.0866):
spacefactor_atdef_wrap builtin 加 ``gate_terms`` param —— 默认
``("spacefactor",)`` 原臂不变, ``gate_terms:[]`` 无签名门姊妹臂收
@-token def 站 (\\newtheorem/\\newenvironment/\\def 族)。
B6 ``microtype_era_cfg_retire`` (40-install.yaml order 11.93, 0812.1138):
era microtype 包捆 (.cfg 无日期面 → shadow 臂够不到) → pstadd 形 sh 名单
退役, 系统现代套件递补。
B7 ``oldfont_cmd_polyfill`` (95-targeted.yaml cs_targeted_fix 扩,
0712.1692): when.any += oldfont_cmd + cs_table 七键 (rm/sf/tt/bf/it/sl/sc)
kernel-verbatim ``\ifdefined``-守卫 ``\DeclareOldFontCommand`` 全家族
polyfill。
"""

from pathlib import Path

import regex
from _fixloopkit import EngStub, apply, mk_ctx, rs, rule

from texlate.compile.fixloop import actions
from texlate.compile.fixloop._builtins_common import (
    _AT_LETTER_POST,
    _AT_LETTER_PRE,
)
from texlate.compile.fixloop.builtins import (
    spacefactor_atdef_wrap,
    vendored_shadow_isolate,
)

# 规则 rid 常量——经 ``rule()``/``rs()`` 惰性取件（收集期不 IO 约定）。
_ERA_ID = "era_bundle_shadow_retire"
_MICRO_ID = "microtype_era_cfg_retire"
_DEMOTE_ID = "doc_ifx_errmessage_demote"
_PSFILE_ID = "special_psfile_abspath_basename"
_ATDEF_ID = "atdef_cat_wrap"
_CS_ID = "cs_targeted_fix"

_VENDOR_PSFIG = (
    Path(__file__).resolve().parents[2]
    / "src/texlate/compile/fixloop/vendor/files/psfig.sty"
)


class _ShadowEng:
    """probe_file → ``texmf`` 目录直查 (模拟系统副本在场; kit 无对应件)。"""

    name = "xelatex"

    def __init__(self, texmf: Path) -> None:
        self.texmf = texmf

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del cwd
        p = self.texmf / fname
        return str(p) if p.is_file() else None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _era_params() -> dict:
    return dict(rule(_ERA_ID).action["params"])


def _cstable() -> dict:
    return rule(_CS_ID).action["params"]["cs_table"]


def _subs(rid: str) -> list:
    return actions._compile_rewrites(  # noqa: SLF001
        rule(rid).action["params"]["rewrites"]
    )


def _sub(rid: str, text: str) -> str | None:
    """经 _compile_rewrites/_masked_sub 真管线跑全部 rewrite (_patch_files 序)。"""
    for pat, repl, masked in _subs(rid):
        nxt = (
            actions._masked_sub(pat, repl, text)  # noqa: SLF001
            if masked
            else actions._bounded_sub(pat, repl, text)  # noqa: SLF001
        )
        if nxt is None:
            return None
        text = nxt
    return text


# ------------------------------------------------------- 注册钉


def test_ruleset_registers_unk26_rules() -> None:
    """五新臂在册且位次钉死 (共仓兄弟车道并发加规则, 只钉下界)。"""
    assert len(rs().rules) >= 200  # noqa: PLR2004 - 落地时 200+5
    assert rule(_ERA_ID).order == 11.92  # noqa: PLR2004
    assert rule(_MICRO_ID).order == 11.93  # noqa: PLR2004
    assert rule(_DEMOTE_ID).order == 11.94  # noqa: PLR2004
    assert rule(_PSFILE_ID).order == 18.55  # noqa: PLR2004 - 18.5 后 18.6 占位臂前
    assert rule(_ATDEF_ID).order == 198.6  # noqa: PLR2004 - spacefactor_atdef_wrap(198.5) 后


def test_era_rule_shape() -> None:
    """B1: builtin_transform vendored_shadow_isolate + 宽 exts + timeout 在 when。"""
    era = rule(_ERA_ID)
    assert era.action["kind"] == "builtin_transform"
    assert era.action["function"] == "vendored_shadow_isolate"
    # spec 原案 exts 含 .tex —— 与 _retire_paired_tex_core 道 double-move
    # 撞缺件 (builtin 无 moved 卫); .tex 留 paired 道独担 (同干核仍退役)
    assert era.action["params"]["exts"] == [".sty", ".cls", ".def", ".cfg"]
    assert era.condition["vendored_shadow"] is True
    cats = {w["category"] for w in era.when["any"]}
    assert "timeout" in cats  # 0103262 超时装载格
    assert {"undefined_cs", "syntax", "other"} <= cats


def test_micro_rule_shape() -> None:
    """B6: run_tool sh 名单退役, ctx+glob+tool 三闸。"""
    micro = rule(_MICRO_ID)
    assert micro.action["kind"] == "run_tool"
    assert micro.condition["cache_dir_glob"] == "microtype.cfg"
    assert micro.condition["tool_available"] == "sh"
    assert "DeclareMicrotypeSet" in micro.condition["ctx_suggests"]
    argv = micro.action["params"]["argv"]
    body = argv[argv.index("-c") + 1]
    for name in ("microtype.sty", "microtype.cfg", "letterspace.sty", "mt-*.cfg"):
        assert name in body
    assert "texlate-fixloop-injected" in body  # 指纹跳


def test_demote_rule_shape() -> None:
    """B3: regex_rewrite 双条 (else 支 + 真支), exts .tex。"""
    demote = rule(_DEMOTE_ID)
    assert demote.action["kind"] == "regex_rewrite"
    assert demote.action["params"]["exts"] == [".tex"]
    assert len(demote.action["params"]["rewrites"]) == 2  # noqa: PLR2004
    assert "errmessage" in demote.condition["source_contains"]


def test_psfile_rule_shape() -> None:
    """B4: 双闸 AND (驱动签名 ∧ 绝对径 psfile), exts .tex。"""
    psfile = rule(_PSFILE_ID)
    assert psfile.action["kind"] == "regex_rewrite"
    assert "Image inclusion failed" in psfile.condition["ctx_suggests"]
    assert "psfile" in psfile.condition["source_contains"]
    cats = {w["category"] for w in psfile.when["any"]}
    assert {"driver_fatal", "other"} == cats


def test_atdef_rule_shape() -> None:
    """B5: 同 builtin 无签名门版; 原臂默认参数不变。"""
    atdef = rule(_ATDEF_ID)
    assert atdef.action["kind"] == "builtin_transform"
    assert atdef.action["function"] == "spacefactor_atdef_wrap"
    assert atdef.action["params"]["gate_terms"] == []
    cats = {w["category"] for w in atdef.when["any"]}
    assert "cs_mismatch" in cats


# ------------------------------------------------------- B1 vendored_shadow_isolate 宽 exts

_OLD_STY = "\\ProvidesPackage{pstricks}[1997/03/25 era wrapper]\n"
_NEW_STY = "\\ProvidesPackage{pstricks}[2024/02/02 v0.75 new wrapper]\n"
_OLD_CORE = "\\def\\filedate{1999/03/24}\n\\input pst-key\n"
_NEW_CORE = "\\def\\filedate{2025/12/13}\n"
_OLD_NODE = "\\ProvidesPackage{pst-node}[1999/11/24 era]\n"
_NEW_NODE = "\\ProvidesPackage{pst-node}[2024/01/01 v1.45]\n"


def test_era_isolate_wide_exts(tmp_path: Path) -> None:
    """0103307/0103262 形: era .sty 直退 + 同干 .tex 核 paired 道同道退。"""
    wdir = tmp_path / "proj"
    wdir.mkdir()
    texmf = tmp_path / "texmf"
    texmf.mkdir()
    (texmf / "pstricks.sty").write_text(_NEW_STY, encoding="utf-8")
    (texmf / "pstricks.tex").write_text(_NEW_CORE, encoding="utf-8")
    (texmf / "pst-node.sty").write_text(_NEW_NODE, encoding="utf-8")
    (wdir / "pstricks.sty").write_text(_OLD_STY, encoding="utf-8")
    (wdir / "pstricks.tex").write_text(_OLD_CORE, encoding="utf-8")
    (wdir / "pst-node.sty").write_text(_OLD_NODE, encoding="utf-8")
    (wdir / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{pstricks,pst-node}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = vendored_shadow_isolate(
        mk_ctx(wdir), _ShadowEng(texmf), None, _era_params()
    )
    assert ok, note
    for name in ("pstricks.sty", "pstricks.tex", "pst-node.sty"):
        assert not (wdir / name).exists(), name
        assert (wdir / f"{name}.fixloop-iso").is_file(), name
    assert (wdir / "main.tex").is_file()  # doc 本体不动 (无系统同名)


def test_era_isolate_negatives(tmp_path: Path) -> None:
    """阴性: 无日期面件不退役 / 干净 wdir decline; 指纹不护直接候选。"""
    wdir = tmp_path / "proj"
    wdir.mkdir()
    texmf = tmp_path / "texmf"
    texmf.mkdir()
    (texmf / "pstricks.sty").write_text(_NEW_STY, encoding="utf-8")
    (texmf / "pstricks.tex").write_text(_NEW_CORE, encoding="utf-8")
    (texmf / "pst-node.sty").write_text(_NEW_NODE, encoding="utf-8")
    # 无日期面 .sty/.tex → ld 无证 → 保留 (probe 中系统副本也不动)
    (wdir / "pstricks.sty").write_text("% hand-rolled wrapper\n", encoding="utf-8")
    (wdir / "pstricks.tex").write_text("% hand-rolled, no date\n", encoding="utf-8")
    # 指纹标记不护直接候选: ld<sd 确证仍退役 (指纹闸只在 paired-core/
    # revtex 专道) —— 旧注入 stub 让位系统新副本是预期语义
    (wdir / "pst-node.sty").write_text(
        "% texlate-fixloop-injected: a1b2c3d4e5f6\n" + _OLD_NODE,
        encoding="utf-8",
    )
    ok, _note = vendored_shadow_isolate(
        mk_ctx(wdir), _ShadowEng(texmf), None, _era_params()
    )
    assert ok  # pst-node.sty 退役 → applied
    assert (wdir / "pstricks.sty").is_file()
    assert (wdir / "pstricks.tex").is_file()
    assert not (wdir / "pst-node.sty").exists()
    assert (wdir / "pst-node.sty.fixloop-iso").is_file()
    # 干净 wdir → 零候选 → decline
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "main.tex").write_text("\\documentclass{article}\nx\n", encoding="utf-8")
    ok2, _note2 = vendored_shadow_isolate(
        mk_ctx(clean), _ShadowEng(texmf), None, _era_params()
    )
    assert not ok2


# ------------------------------------------------------- B2 psfig vendor 桥件


def test_psfig_vendor_is_epsfig_bridge() -> None:
    """vendor/files/psfig.sty = epsfig 仿真桥, 非真身 v1.10。"""
    t = _VENDOR_PSFIG.read_text(encoding="utf-8")
    assert "\\ProvidesPackage{psfig}" in t
    assert "\\RequirePackage{epsfig}" in t
    assert "\\define@key{Gin}{rheight}" in t
    assert "\\define@key{Gin}{rwidth}" in t
    assert "\\PsfigVersion" not in t  # 真身标记缺席
    # dvips 输出面缺席 —— \special 仅可出现在注释行
    assert all(
        line.lstrip().startswith("%") for line in t.splitlines() if "\\special" in line
    )
    assert t.endswith("\\endinput\n")


# ------------------------------------------------------- B3 doc_ifx_errmessage_demote


def test_demote_else_branch() -> None:
    """9612213 verbatim 形: \\ifx\\href\\undefined \\else\\errmessage \\fi → typeout。"""
    src = "\\ifx\\href\\undefined\n\\else\\errmessage{Don't use hypertex}\n\\fi"
    out = _sub(_DEMOTE_ID, src)
    assert "\\errmessage" not in out
    assert "\\typeout{Don't use hypertex}" in out
    assert "\\ifx\\href\\undefined" in out
    assert "texlate-fixloop-injected" in out
    assert _sub(_DEMOTE_ID, out) == out  # errmessage 消失天然幂等


def test_demote_true_branch() -> None:
    """真支变体 (无 \\else): \\ifx\\foo\\undefined\\errmessage{..}\\fi → typeout。"""
    src = "\\ifx\\foo\\undefined \\errmessage{no pdftex}\\fi"
    out = _sub(_DEMOTE_ID, src)
    assert "\\typeout{no pdftex}" in out
    assert "\\errmessage" not in out


def test_demote_negatives() -> None:
    """阴性: 裸 \\errmessage / 无 \\undefined 护栏形不动。"""
    assert _sub(_DEMOTE_ID, "\\errmessage{fatal}\n") == "\\errmessage{fatal}\n"
    assert (
        _sub(_DEMOTE_ID, "\\ifx\\foo\\bar \\errmessage{x}\\fi")
        == "\\ifx\\foo\\bar \\errmessage{x}\\fi"
    )


def test_demote_apply_tex_only(tmp_path: Path) -> None:
    """exts .tex: 同名护栏在 .sty 内不动。"""
    guard = "\\ifx\\href\\undefined \\else\\errmessage{Don't use hypertex}\\fi\n"
    (tmp_path / "main.tex").write_text(guard, encoding="utf-8")
    (tmp_path / "pkg.sty").write_text(guard, encoding="utf-8")
    ok, _note = apply(_DEMOTE_ID, mk_ctx(tmp_path), None)
    assert ok
    assert "\\typeout" in (tmp_path / "main.tex").read_text()
    assert "\\errmessage" in (tmp_path / "pkg.sty").read_text()


# ------------------------------------------------------- B4 special_psfile_abspath_basename


def test_psfile_abspath_stripped() -> None:
    """9412001 verbatim 形: 作者机绝对径 → basename。"""
    src = "\\special{psfile=/home/enomoto/kekm.ps hscale=0.7 vscale=0.7 hoffset=-150 voffset=-220}"
    out = _sub(_PSFILE_ID, src)
    assert "psfile=kekm.ps" in out
    assert "/home/enomoto" not in out
    assert "hscale=0.7" in out  # 尾参原样


def test_psfile_quoted_abspath() -> None:
    """引号形绝对径同剥 (组1 保引号)。"""
    out = _sub(_PSFILE_ID, 'psfile="/abs/dir/x.ps"')
    assert out == 'psfile="x.ps"'


def test_psfile_relative_untouched() -> None:
    """阴性: 相对径与裸名不动 (前导 /|\\ 闸)。"""
    assert _sub(_PSFILE_ID, "psfile=figs/x.ps") == "psfile=figs/x.ps"
    assert _sub(_PSFILE_ID, "psfile=kekm.ps") == "psfile=kekm.ps"


def test_psfile_apply(tmp_path: Path) -> None:
    """全链: .tex 内绝对径剥 basename, 真档在场可解析。"""
    (tmp_path / "kekm.ps").write_text("%!PS-Adobe\n", encoding="utf-8")
    (tmp_path / "main.tex").write_text(
        "\\special{psfile=/home/enomoto/kekm.ps hscale=0.7}\n", encoding="utf-8"
    )
    ok, _note = apply(_PSFILE_ID, mk_ctx(tmp_path), None)
    assert ok
    assert "psfile=kekm.ps" in (tmp_path / "main.tex").read_text()


# ------------------------------------------------------- B5 atdef_cat_wrap + gate_terms


def test_atdef_wraps_newtheorem_env(tmp_path: Path) -> None:
    """0712.0866 形: 无 spacefactor 签名也裹 @-def 站 (gate_terms:[])。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\newtheorem{@#1}{#2}[section]\n"
        "\\newenvironment{clm}{\\begin{@clm}\\rm\\edef\\@currentlabel{\\arabic{@clm}}}{\\end{@clm}}\n"
        "\\def\\the@clm{\\arabic{@clm}}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = apply(
        _ATDEF_ID,
        mk_ctx(tmp_path, err_head="Use of \\@ doesn't match its definition"),
        None,
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert _AT_LETTER_PRE in t
    assert _AT_LETTER_POST in t
    assert "\\catcode 64=11" in t
    # 包裹内原文逐字节未动
    assert "\\newtheorem{@#1}{#2}[section]" in t
    assert "\\newenvironment{clm}" in t
    assert "\\def\\the@clm" in t


def test_atdef_idempotent(tmp_path: Path) -> None:
    """复跑不双重包裹 (自注 catcode 事件标 at_letter 跳过)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\def\\the@clm{x}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = apply(_ATDEF_ID, mk_ctx(tmp_path, err_head="syntax junk"), None)
    assert ok
    first = (tmp_path / "main.tex").read_text()
    apply(_ATDEF_ID, mk_ctx(tmp_path, err_head="syntax junk"), None)
    assert (tmp_path / "main.tex").read_text() == first
    assert first.count("\\catcode 64=11") == 1


def test_atdef_no_at_def_declines(tmp_path: Path) -> None:
    """阴性: 无 @-token def 站 → decline 不改文。"""
    src = "\\documentclass{article}\n\\def\\ok{1}\n\\begin{document}\nx\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _note = apply(_ATDEF_ID, mk_ctx(tmp_path, err_head="syntax junk"), None)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_gate_terms_default_preserves_spacefactor(tmp_path: Path) -> None:
    """B5 builtin 兼容: 默认 gate 仍要 spacefactor 签名 (原臂语义不变)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\def\\a@b{x}\n", encoding="utf-8"
    )
    # 无参 (默认 gate) + 无签名 → decline
    ok, note = spacefactor_atdef_wrap(
        mk_ctx(tmp_path, err_head="Undefined control sequence \\foo"),
        EngStub(),
        None,
        {},
    )
    assert not ok
    assert "gate" in note
    # gate_terms:[] + 无签名 → 裹
    ok2, _ = spacefactor_atdef_wrap(
        mk_ctx(tmp_path, err_head="Undefined control sequence \\foo"),
        EngStub(),
        None,
        {"gate_terms": []},
    )
    assert ok2
    assert "\\catcode 64=11" in (tmp_path / "main.tex").read_text()


# ------------------------------------------------------- B6 microtype_era_cfg_retire


def test_micro_retire_listed_files(tmp_path: Path) -> None:
    """0812.1138 形: 名单四件 mv .fixloop-iso; 指纹件与名单外件留盘。"""
    for name in ("microtype.sty", "microtype.cfg", "letterspace.sty", "mt-cmr.cfg"):
        (tmp_path / name).write_text(f"% era {name}\n", encoding="utf-8")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{microtype}\nx\n", encoding="utf-8"
    )
    (tmp_path / "microtype-fix.cfg").write_text(
        "% texlate-fixloop-injected: a1b2c3d4e5f6\n", encoding="utf-8"
    )
    ok, note = apply(
        _MICRO_ID,
        mk_ctx(tmp_path, err_head="Package microtype Error \\DeclareMicrotypeSet"),
        None,
    )
    assert ok, note
    for name in ("microtype.sty", "microtype.cfg", "letterspace.sty", "mt-cmr.cfg"):
        assert not (tmp_path / name).exists(), name
        assert (tmp_path / f"{name}.fixloop-iso").is_file(), name
    assert (tmp_path / "main.tex").is_file()
    # 名单外 glob 不收 (microtype-fix.cfg 不在名单 —— 名字不匹配 mt-*)
    assert (tmp_path / "microtype-fix.cfg").is_file()


def test_micro_fingerprint_skipped(tmp_path: Path) -> None:
    """阴性: 名单内指纹件跳过 —— ``texlate-fixloop-injected`` 认亲不退役。"""
    (tmp_path / "microtype.cfg").write_text(
        "% texlate-fixloop-injected: a1b2c3d4e5f6\n\\ProvidesFile{microtype.cfg}\n",
        encoding="utf-8",
    )
    (tmp_path / "microtype.sty").write_text("% era\n", encoding="utf-8")
    ok, _note = apply(_MICRO_ID, mk_ctx(tmp_path), None)
    assert ok  # run_tool 臂恒 applied (跑了即算)
    assert (tmp_path / "microtype.cfg").is_file()
    assert not (tmp_path / "microtype.sty").exists()
    assert (tmp_path / "microtype.sty.fixloop-iso").is_file()


# ------------------------------------------------------- B7 oldfont_cmd_polyfill


def test_oldfont_when_widened() -> None:
    """B7: when.any 收 oldfont_cmd (payload_required)。"""
    entries = [
        w for w in rule(_CS_ID).when["any"] if w.get("category") == "oldfont_cmd"
    ]
    assert entries
    assert all(w.get("payload_required") for w in entries)


def test_oldfont_table_keys() -> None:
    """七键同体: kernel-verbatim 全家族 \\ifdefined-守卫 DeclareOldFontCommand。"""
    cstable = _cstable()
    for key in ("rm", "sf", "tt", "bf", "it", "sl", "sc"):
        body = cstable[key]["polyfill"]
        assert body.startswith("\n")  # eol-注释缝约
        for cs in ("rm", "sf", "tt", "bf", "it", "sl", "sc"):
            assert f"\\ifdefined\\{cs}\\else\\DeclareOldFontCommand{{\\{cs}}}" in body
        assert "\\normalfont\\bfseries}{\\mathbf}" in body  # kernel 逐字样
        assert "\\mathsl" in body
        assert "\\mathsc" in body


def test_oldfont_polyfill_injected(tmp_path: Path) -> None:
    """0712.1692 形: scrartcl 稿 oldfont_cmd|\\bf → docclass 后全家族注入。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{scrartcl}\n\\begin{document}\n{\\bf X}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = apply(_CS_ID, mk_ctx(tmp_path), "\\bf")
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    pos = t.index("\\documentclass{scrartcl}")
    for cs in ("rm", "sf", "tt", "bf", "it", "sl", "sc"):
        inj = t.index(f"\\DeclareOldFontCommand{{\\{cs}}}")
        assert inj > pos
    assert "\\ifdefined\\bf\\else" in t  # 守卫形 —— 已定义类上 no-op


def test_oldfont_unknown_cs_declines(tmp_path: Path) -> None:
    """阴性: 表外 payload → decline。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{scrartcl}\n\\begin{document}\nx\n", encoding="utf-8"
    )
    ok, _note = apply(_CS_ID, mk_ctx(tmp_path), "\\zznope")
    assert not ok


def test_oldfont_csname_payload_stripped(tmp_path: Path) -> None:
    """payload 剥反斜杠查表：裸 ``bf``（无 ``\\`` 前缀）经 lstrip 同命中 cs_table 键。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{scrartcl}\n\\begin{document}\n{\\bf X}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = apply(_CS_ID, mk_ctx(tmp_path), "bf")
    assert ok, note
    assert "\\DeclareOldFontCommand{\\bf}" in (tmp_path / "main.tex").read_text()


# ------------------------------------------------------- 条件 pattern 直钉 (regex 面)


def test_demote_condition_pattern() -> None:
    """source_contains 闸: \\ifx..\\undefined..\\errmessage 形才收。"""
    pat = rule(_DEMOTE_ID).condition["source_contains"]
    assert regex.search(pat, "\\ifx\\href\\undefined\\else\\errmessage{x}")
    assert regex.search(pat, "\\ifx\\@foo\\undefined x\n\\errmessage{y}")
    assert regex.search(pat, "\\errmessage{x}") is None
    assert regex.search(pat, "\\ifx\\foo\\undefined") is None


def test_psfile_condition_pattern() -> None:
    """source_contains 闸: \\special{..psfile=<绝对径>} 形才收。"""
    pat = rule(_PSFILE_ID).condition["source_contains"]
    assert regex.search(pat, "\\special{psfile=/home/x/y.ps}")
    assert regex.search(pat, '\\special{psfile="\\srv\\x.ps"')  # UNC 径
    assert regex.search(pat, "\\special{psfile=x.ps}") is None
    assert regex.search(pat, "\\special{psfile=figs/x.ps}") is None
    # 引号内盘符形不收 (``"?`` 后需立即 /|\\ —— 作者机 unix 绝对径口径)
    assert regex.search(pat, '\\special{psfile="C:\\dir\\x.ps"') is None


def test_atdef_condition_pattern() -> None:
    """source_contains 闸: def 命令行带 @ 才收。"""
    pat = rule(_ATDEF_ID).condition["source_contains"]
    assert regex.search(pat, "\\newtheorem{@#1}{#2}[section]")
    assert regex.search(pat, "\\newenvironment{clm}{\\begin{@clm}}")
    assert regex.search(pat, "\\def\\the@clm{x}")
    assert regex.search(pat, "\\newcommand\\foo{bar}") is None
    assert regex.search(pat, "see \\@ x") is None


def test_micro_ctx_pattern() -> None:
    """ctx_suggests 闸: microtype 签名族。"""
    pat = rule(_MICRO_ID).condition["ctx_suggests"]
    for sig in (
        "Package microtype Error",
        "\\DeclareMicrotypeSet",
        "\\MT@foo",
        "letterspace",
    ):
        assert regex.search(pat, sig), sig
    assert regex.search(pat, "Undefined control sequence") is None
