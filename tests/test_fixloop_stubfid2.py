"""vendor-stub fidelity pins 批二（task #342-#347 impl 车道，clsfidcen 普查
58 条目，签名按随稿真件抄值核对）。

六组补丁：

- ``85-shim.yaml::aastex_bundle_shadow`` 体（~230 格）：emulateapj 全缺的
  aastex5 frontmatter 面——``\\email`` provide+renew 双写（aastex6x_body
  先例），``\\authoremail/\\received/\\revised/\\accepted/\\journalid/
  \\articleid/\\cpright/\\ccc`` + ``references`` env 守卫。
- ``aastex6x_body`` 共享锚 ×4 键（~109 格）：``\\altaffiliation``/
  track-changes 族（``\\added/\\deleted/\\replaced/\\listofchanges``）/
  ``\\AuthorCollaborationLimit``/``\\lesssim/\\gtrsim`` 画符 + widetext/
  ruledtabular/contribution envs。
- ``vendor/shims/svjour3.cls``（~59 格）：qed 族（画框 ``\\squareforqed``/
  ``\\smartqed`` 行尾式）、``\\makeheadbox/\\setitemindent``、theopargself
  对、``\\spnewtheorem`` 三式路由、*name 英文默认值族。
- ``vendor/stubs/aa.cls``（~88 格）：``\\tablefoot`` 族、Online Material
  族、``\\element`` 可选参链、``\\orcidlink``、aa 式 ``\\newtheorem``
  宽容路由（尾部 {capf}{bodyf} 两字体参吞）、预定义 theorem env 集、
  dataavailability 族、``endacknowledgements`` namedef、期刊缩写增补。
- bare-bridge aliases（~107 格）：eptcs/svmult/appolb/kapproc/cimento
  article 桥 + sig-alternate 族/acm_proc → acmart 桥 conference kit。
- tail singles：JHEP3/JHEP ``\\sissa@jrnl`` 缩写补员 + ``\\newjournal``/
  ``\\PrHEP``；svjour.cls ``\\makeheadbox/\\fnmsep/\\tens/\\spnewtheorem``；
  aipproc 第二宏面（``\\SetInternalRegister`` 功能形/``\\tablenote`` 就地印/
  varioref ``\\reftext*`` 族）；siamltex mathop 族 + romannum/remunerate/
  AM envs + ``\\Appendix``；svjour2 ``\\email/\\smartqed`` 族；osajnl
  ``\\bmsection``+backmatter；JINST ``\\preprint``+arxiv-abbrev 族；
  PoS ``\\href/\\pos``；revtex4 ``\\mathindent``。

有意不补（普查误报/回归面，pin 成不变量）：

- mn2e ``\\apspr``：6/6 格稿侧 ``\\newcommand`` 自定——stub 提供会撞
  already-def（真件注释态，vendored mnras 同位）。
- JINST ``\\href``：体已载 hyperref，普查项误报。
- siamart：保持纯桥，siamltex 专有面（mathop/list env/``\\Appendix``）
  不得渗入——真身走 amsthm + 稿自定义定理。
- revtex4-1/revtex4b4：普查零格，不补。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.fixloop import load_ruleset

SHIMS = (
    Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor/shims"
)
STUBS = (
    Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor/stubs"
)

_XELATEX = shutil.which("xelatex")
_COMPILE = pytest.mark.skipif(_XELATEX is None, reason="xelatex not installed")


def _rule_params(rule_id: str) -> dict:
    rules = {r.id: r for r in load_ruleset().rules}
    return rules[rule_id].action["params"]


def _shim_map() -> dict[str, dict]:
    return _rule_params("legacy_pkg_shim")["shim_map"]


def _shim_body(name: str) -> str:
    spec = _shim_map().get(name)
    assert spec is not None, f"{name} 不在 shim_map"
    assert "body" in spec, f"{name} 无 body 键"
    return spec["body"]


def _code_lines(body: str) -> str:
    """滤 % 注释行——pin 断言不得被注释文本夹带。"""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("%"))


def _run(wdir: Path, tex: str, extra: dict[str, str] | None = None) -> str:
    (wdir / "main.tex").write_text(tex, encoding="utf-8")
    for name, body in (extra or {}).items():
        (wdir / name).write_text(body, encoding="utf-8")
    subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [_XELATEX, "-interaction=nonstopmode", "main.tex"],
        cwd=wdir,
        capture_output=True,
        timeout=120,
        check=False,
    )
    return (wdir / "main.log").read_text(encoding="utf-8", errors="replace")


def _n_err(log: str) -> int:
    return len(re.findall(r"^! ", log, re.MULTILINE))


# ------------------------------------------------- aastex_bundle_shadow（85-shim）
def test_aastex_bundle_shadow_frontmatter() -> None:
    r"""aastex.cls bundle-shadow 体补 aastex5 frontmatter 面（emulateapj
    全缺；``\email`` provide+renew 双写）。"""
    code = _code_lines(_rule_params("aastex_bundle_shadow")["body"])
    for frag in (
        "\\providecommand{\\email}[1]{}",
        "\\renewcommand{\\email}[1]{}",
        "\\providecommand{\\authoremail}[1]{}",
        "\\providecommand{\\received}[1]{}",
        "\\providecommand{\\revised}[1]{}",
        "\\providecommand{\\accepted}[1]{}",
        "\\providecommand{\\journalid}[2]{}",
        "\\providecommand{\\articleid}[2]{}",
        "\\providecommand{\\cpright}[2]{}",
        "\\providecommand{\\ccc}[1]{}",
        "\\newenvironment{references}",
        "\\providecommand{\\rotate}{}",
    ):
        assert frag in code, f"aastex shadow 体缺 {frag}"


def test_email_provide_before_renew() -> None:
    r"""provide+renew 双写序不变量：``\renewcommand{\email}`` 必须晚于
    ``\providecommand``（emulateapj 变体自带/缺失两路均安全）。"""
    shadow = _code_lines(_rule_params("aastex_bundle_shadow")["body"])
    assert shadow.index("\\providecommand{\\email}") < shadow.index(
        "\\renewcommand{\\email}"
    )
    a6x = _code_lines(_shim_body("aastex61.cls"))
    assert a6x.index("\\providecommand{\\email}") < a6x.index("\\renewcommand{\\email}")


# ------------------------------------------------- aastex6x_body 共享锚 ×4
_AASTEX6X_FRAGS = (
    "\\providecommand{\\altaffiliation}",
    "\\providecommand{\\allauthors}",
    "\\providecommand{\\setwatermarkfontsize}",
    "\\providecommand{\\added}[2][]",
    "\\providecommand{\\deleted}[2][]",
    "\\providecommand{\\replaced}[3][]",
    "\\providecommand{\\listofchanges}",
    "\\newcount\\AuthorCollaborationLimit",
    "\\providecommand{\\lesssim}",
    "\\providecommand{\\gtrsim}",
    "\\newenvironment{widetext}",
    "\\newenvironment{ruledtabular}",
    "\\newenvironment{contribution}",
)


@pytest.mark.parametrize("key", ["aastex61.cls", "aastex63.cls", "aastex631.cls"])
def test_aastex6x_shared_body(key: str) -> None:
    """aastex6x 共享体三键同面：track-changes 族 + env 三件 + 画符不等号。"""
    code = _code_lines(_shim_body(key))
    for frag in _AASTEX6X_FRAGS:
        assert frag in code, f"{key} 缺 {frag}"


def test_aastex_barename_bridges() -> None:
    """aastex6/aastex3 裸名桥 → vendored 真件；AASTeX62.cls 死键已删。

    clsbridge 普查唯一真覆盖洞：1901.00051 \\documentclass{aastex6} →
    missing_file|aastex6.cls，TL/vendor 无本体；loads 桥让 stub
    \\LoadClassWithOptions{aastex62} 命中 vendored 真件。aastex3 桥是
    aux-declare 面保险（零活实证）。AASTeX62.cls 键大小写敏感不可达，
    删后不得复活。
    """
    sm = _shim_map()
    assert sm.get("aastex6.cls") == {"loads": "aastex62", "needs": ["aastex62.cls"]}
    assert sm.get("aastex3.cls") == {"loads": "aastex", "needs": ["aastex.cls"]}
    assert "AASTeX62.cls" not in sm


# ------------------------------------------------- svjour3.cls vendor 件
def test_svjour3_vendor_shim() -> None:
    r"""svjour3 stub：qed 族 + ``\makeheadbox/\setitemindent`` +
    theopargself 对 + ``\spnewtheorem`` 路由 + *name 默认族。"""
    code = _code_lines((SHIMS / "svjour3.cls").read_text(encoding="utf-8"))
    for frag in (
        "\\def\\squareforqed",
        "\\def\\qed",
        "\\def\\smartqed",
        "\\newcommand{\\makeheadbox}",
        "\\def\\setitemindent",
        "\\providecommand{\\spnewtheorem}",
        "\\newenvironment{theopargself}",
        "\\newenvironment{theopargself*}",
        "\\providecommand{\\theoremname}",
        "\\providecommand{\\lemmaname}",
        "\\providecommand{\\corollaryname}",
        "\\providecommand{\\propositionname}",
        "\\providecommand{\\definitionname}",
        "\\providecommand{\\examplename}",
        "\\providecommand{\\remarkname}",
        "\\providecommand{\\conjecturename}",
        "\\providecommand{\\claimname}",
        "\\providecommand{\\problemname}",
        "\\providecommand{\\proofname}",
        "\\providecommand{\\emailname}",
        "\\providecommand{\\mailname}",
        "\\providecommand{\\noteaddname}",
    ):
        assert frag in code, f"svjour3 缺 {frag}"


# ------------------------------------------------- aa.cls vendor 件
def test_aa_stub_second_surface() -> None:
    r"""aa stub 第二宏面：``\tablefoot``/Online Material 族 + ``\element``
    可选参链 + aa 式 ``\newtheorem`` 路由 + dataavailability + 缩写增补。"""
    code = _code_lines((STUBS / "aa.cls").read_text(encoding="utf-8"))
    for frag in (
        "\\providecommand{\\fnmsep}",
        "\\providecommand{\\tablebib}[1]",
        "\\providecommand{\\tablefoot}[1]",
        "\\providecommand{\\tablefootmark}[1]",
        "\\providecommand{\\tablefoottext}[2]",
        "\\providecommand{\\Online}",
        "\\providecommand{\\onlfloat}[2]",
        "\\providecommand{\\onlfig}",
        "\\providecommand{\\onltab}",
        "\\providecommand{\\onllongtab}",
        "\\providecommand{\\orcidlink}[1]",
        "\\providecommand{\\element}",
        "\\providecommand{\\corr}[1]",
        "\\providecommand{\\idline}",
        "\\providecommand{\\headnote}",
        "\\providecommand{\\listofobjects}",
        "\\providecommand{\\filedate}",
        "\\providecommand{\\fileversion}",
        "\\newenvironment{longtab}",
        "\\newenvironment{nodata}",
        "\\newenvironment{dataavailability}",
        "endacknowledgements",
        "\\RequirePackage{longtable}",
        "\\providecommand{\\actaa}",
        "\\providecommand{\\bac}",
        "\\providecommand{\\caa}",
        "\\providecommand{\\cjaa}",
        "\\providecommand{\\icarus}",
        "\\providecommand{\\jcap}",
        "\\providecommand{\\na}",
        "\\providecommand{\\nar}",
        "\\providecommand{\\pasa}",
        "\\providecommand{\\rmxaa}",
    ):
        assert frag in code, f"aa.cls 缺 {frag}"
    # aa 式 \newtheorem 宽容路由：内核签名尾部可再挂 {capf}{bodyf}
    assert "\\renewcommand{\\newtheorem}" in code
    assert "\\aa@thfonteat" in code


def test_aa_stub_pdfoutput_fallback() -> None:
    r"""``\pdfoutput`` xelatex 兜底——真件 verbatim ``\newcount`` 形。"""
    code = _code_lines((STUBS / "aa.cls").read_text(encoding="utf-8"))
    assert "\\ifx\\pdfoutput\\undefined" in code
    assert "\\newcount\\pdfoutput" in code


# ------------------------------------------------- bare-bridge aliases
def test_eptcs_body() -> None:
    """eptcs 值持面：0 参文本 holder + firstpage counter + 打印形。"""
    code = _code_lines(_shim_body("eptcs.cls"))
    for frag in (
        "\\providecommand{\\event}",
        "\\providecommand{\\volume}",
        "\\providecommand{\\anno}",
        "\\providecommand{\\eid}",
        "\\providecommand{\\titlerunning}",
        "\\providecommand{\\authorrunning}",
        "\\providecommand{\\publicationstatus}",
        "\\providecommand{\\copyrightholders}",
        "\\newcounter{firstpage}",
        "\\providecommand{\\institute}",
        "\\providecommand{\\email}",
    ):
        assert frag in code, f"eptcs 缺 {frag}"


def test_svmult_body() -> None:
    r"""svmult 面：toks 寄存器 verbatim + ``\svhline``/``\greeksym`` +
    ``\spnewtheorem`` 路由 + qed 族 + 版式指示 noop。"""
    code = _code_lines(_shim_body("svmult.cls"))
    for frag in (
        "\\newtoks\\titlerunning",
        "\\newtoks\\authorrunning",
        "\\newtoks\\toctitle",
        "\\newtoks\\tocauthor",
        "\\providecommand{\\inst}",
        "\\providecommand{\\orcidID}",
        "\\providecommand{\\fnmsep}",
        "\\providecommand{\\subtitle}",
        "\\providecommand{\\institute}",
        "\\providecommand{\\email}",
        "\\providecommand{\\svhline}",
        "\\providecommand{\\greeksym}",
        "\\providecommand{\\umu}",
        "\\providecommand{\\udelta}",
        "\\def\\squareforqed",
        "\\providecommand{\\smartqed}",
        "\\providecommand{\\spnewtheorem}",
        "\\providecommand{\\ackname}",
        "\\newenvironment{acknowledgement}",
        "\\providecommand{\\biblstarthook}",
        "\\providecommand{\\sidecaption}",
        "\\providecommand{\\frontmatter}",
        "\\providecommand{\\mainmatter}",
        "\\providecommand{\\backmatter}",
        "\\providecommand{\\cleardoublepage}",
    ):
        assert frag in code, f"svmult 缺 {frag}"


def test_appolb_body() -> None:
    """appolb（Acta Phys. Pol. B）版式面。"""
    code = _code_lines(_shim_body("appolb.cls"))
    for frag in (
        "\\providecommand{\\eqsec}",
        "\\providecommand{\\address}",
        "\\providecommand{\\PACS}",
        "\\providecommand{\\Tr}",
        "\\providecommand{\\preprint}",
        "\\providecommand{\\runhead}",
    ):
        assert frag in code, f"appolb 缺 {frag}"


def test_kapproc_body() -> None:
    r"""kapproc（Kluwer 老版式）面：``\savefootnote`` let 快照 +
    ``\articletitle`` section 桥 + ``\sphline`` verbatim。"""
    code = _code_lines(_shim_body("kapproc.cls"))
    for frag in (
        "\\let\\savefootnote\\footnote",
        "\\let\\savefootnotetext\\footnotetext",
        "\\providecommand{\\savefootnoterule}",
        "\\providecommand{\\articletitle}",
        "\\providecommand{\\articlesubtitle}",
        "\\providecommand{\\affil}",
        "\\providecommand{\\email}",
        "\\providecommand{\\affilemail}",
        "\\providecommand{\\upperandlowercase}",
        "\\providecommand{\\kluwerbib}",
        "\\providecommand{\\normallatexbib}",
        "\\providecommand{\\lcitebracket}",
        "\\providecommand{\\rcitebracket}",
        "\\providecommand{\\sphline}",
        "\\providecommand{\\chaptersection}",
        "\\providecommand{\\chapbblname}",
        "\\providecommand{\\chapbibliography}",
        "\\providecommand{\\chaptitlerunninghead}",
        "\\providecommand{\\notes}",
        "\\providecommand{\\draft}",
        "\\providecommand{\\altaffilmark}",
    ):
        assert frag in code, f"kapproc 缺 {frag}"


def test_cimento_body() -> None:
    r"""cimento（Nuovo Cimento）面：``\atque/\And/\etal/\idest/\jr`` 行内件 +
    单位-记号族 + bbl-struct 族 + eqnletter/mathletters/narrowtabular envs。"""
    code = _code_lines(_shim_body("cimento.cls"))
    for frag in (
        "\\providecommand{\\atque}",
        "\\def\\And{\\atque}",
        "\\providecommand{\\etal}",
        "\\providecommand{\\idest}",
        "\\providecommand{\\jr}",
        "\\providecommand{\\acknowledgments}",
        "\\let\\stars\\acknowledgments",
        "\\let\\solong\\acknowledgments",
        "\\providecommand{\\drm}",
        "\\providecommand{\\sy}",
        "\\providecommand{\\tx}",
        "\\providecommand{\\un}",
        "\\providecommand{\\chem}",
        "\\providecommand{\\mth}",
        "\\providecommand{\\acro}",
        "\\providecommand{\\NAME}",
        "\\providecommand{\\BY}",
        "\\providecommand{\\IN}[4]",
        "\\providecommand{\\SAME}",
        "\\providecommand{\\TITLE}",
        "\\providecommand{\\ETC}",
        "\\providecommand{\\issue}",
        "\\newenvironment{eqnletter}",
        "\\newenvironment{mathletters}",
        "\\newenvironment{narrowtabular}",
    ):
        assert frag in code, f"cimento 缺 {frag}"


_ACM_KIT_FRAGS = (
    "\\alignauthor",
    "\\numberofauthors",
    "\\category",
    "\\conferenceinfo",
    "\\CopyrightYear",
    "\\crdata",
    "\\permission",
    "\\isbn",
    "\\doi",
    "\\printccsdesc",
    "\\toappear",
    "\\toappearbox",
    "\\balancecolumns",
    "\\additionalauthors",
)


@pytest.mark.parametrize(
    "key",
    ["sig-alternate.cls", "sig-alternate-05-2015.cls", "acm_proc_article-sp.cls"],
)
def test_acm_conference_kit(key: str) -> None:
    r"""ACM 会议版式 kit（``\ifdefined`` 守卫防 acmart 原生同名）：
    sig-alt 双键共享锚 + acm_proc_article-sp 同款。"""
    code = _code_lines(_shim_body(key))
    for frag in _ACM_KIT_FRAGS:
        assert frag in code, f"{key} 缺 {frag}"


# ------------------------------------------------- tail singles
def test_jhep3_journal_abbrevs() -> None:
    r"""JHEP3 stub ``\sissa@jrnl`` 双态分派补员 + ``\newjournal``/``\PrHEP``
    （真件 @spires 表抄值）。"""
    code = _code_lines((SHIMS / "JHEP3.cls").read_text(encoding="utf-8"))
    for frag in (
        "\\providecommand{\\ap}{\\sissa@jrnl{Ann.~Phys.~(NY)}}",
        "\\providecommand{\\ptp}{\\sissa@jrnl{Prog.~Theor.~Phys.}}",
        "\\providecommand{\\ptps}{\\sissa@jrnl{Prog.~Theor.~Phys.~Suppl.}}",
        "\\providecommand{\\prep}{\\sissa@jrnl{Phys.~Rept.}}",
        "\\providecommand{\\atmp}{\\sissa@jrnl{Adv.~Theor.~Math.~Phys.}}",
        "\\providecommand{\\adnp}{\\sissa@jrnl{Adv.~Nucl.~Phys.}}",
        "\\providecommand{\\npps}{\\sissa@jrnl{Nucl.~Phys.~Proc.~Suppl.}}",
        "\\providecommand{\\ppnp}{\\sissa@jrnl{Prog.~Part.~Nucl.~Phys.}}",
        "\\providecommand{\\app}{\\sissa@jrnl{Astropart.~Phys.}}",
        "\\providecommand{\\apj}{\\sissa@jrnl{Astrophys.~J.}}",
        "\\providecommand{\\am}{\\sissa@jrnl{Ann.~Math.}}",
        "\\providecommand{\\nc}{\\sissa@jrnl{Nuovo~Cim.}}",
        "\\providecommand{\\newjournal}[5]",
        "\\providecommand{\\PrHEP}[1]",
    ):
        assert frag in code, f"JHEP3 缺 {frag}"


def test_jhep_journal_abbrevs() -> None:
    r"""JHEP stub 只补普查实证的 3 条（``\ap/\prep/\jgp``）——JHEP3 的
    12 条面不对称不抄。"""
    code = _code_lines((SHIMS / "JHEP.cls").read_text(encoding="utf-8"))
    for frag in (
        "\\providecommand{\\ap}{\\sissa@jrnl{Ann.~Phys.~(NY)}}",
        "\\providecommand{\\prep}{\\sissa@jrnl{Phys.~Rep.}}",
        "\\providecommand{\\jgp}{\\sissa@jrnl{J.~Geom.~Phys.}}",
    ):
        assert frag in code, f"JHEP 缺 {frag}"
    assert "\\providecommand{\\ptp}" not in code


def test_svjour_clsvendor_second_surface() -> None:
    r"""svjour stub：``\makeheadbox`` 0 参 verbatim（稿 ``\renewcommand``
    需前置存在）+ ``\fnmsep/\tens`` + ``\spnewtheorem`` 三式路由。"""
    code = _code_lines((SHIMS / "svjour.cls").read_text(encoding="utf-8"))
    for frag in (
        "\\def\\makeheadbox{{}}",
        "\\def\\fnmsep{\\unskip$^,$}",
        "\\def\\tens#1{\\ensuremath{\\mathsf{#1}}}",
        "\\providecommand{\\spnewtheorem}",
        "\\texlate@svj@uthm",
        "\\texlate@svj@thmA",
    ):
        assert frag in code, f"svjour 缺 {frag}"


def test_aipproc_second_surface() -> None:
    r"""aipproc 第二宏面：画符 ``\lesssim/\gtrsim/\sq`` + ``\tablenote``
    就地印 + ``\SetInternalRegister`` 功能形 + varioref ``\reftext*`` 族。"""
    code = _code_lines((SHIMS / "aipproc.cls").read_text(encoding="utf-8"))
    for frag in (
        "\\providecommand{\\lesssim}",
        "\\providecommand{\\gtrsim}",
        "\\providecommand{\\sq}",
        "\\providecommand{\\sun}",
        "\\providecommand{\\boldmath}",
        "\\providecommand{\\tablenote}[1]",
        "\\providecommand{\\SetInternalRegister}[2]{#1=#2\\relax}",
        "\\providecommand{\\AIPcitestyleselect}",
        "\\providecommand{\\reftextvario}[2]",
        "\\providecommand{\\reftextfacebefore}",
        "\\providecommand{\\reftextfaceafter}",
        "\\providecommand{\\reftextbefore}",
        "\\providecommand{\\reftextafter}",
        "\\providecommand{\\reftextcurrent}",
        "\\providecommand{\\reftextearlier}",
        "\\providecommand{\\reftextlater}",
        "\\providecommand{\\reftextfaraway}[1]",
        "\\providecommand{\\source}[1]",
        "\\providecommand{\\spaceforfigure}[2]",
    ):
        assert frag in code, f"aipproc 缺 {frag}"


def test_siamltex_mathop_and_lists() -> None:
    r"""siamltex mathop 族（``\operator@font`` 是 amsopn 私有 → ``\mathrm``
    降级）+ romannum/remunerate/AM envs + ``\Appendix`` secdef 机。"""
    code = _code_lines(_shim_body("siamltex.cls"))
    for frag in (
        "\\providecommand{\\const}",
        "\\providecommand{\\diag}",
        "\\providecommand{\\grad}",
        "\\providecommand{\\Range}",
        "\\providecommand{\\rank}",
        "\\providecommand{\\supp}",
        "\\providecommand{\\sameauthor}",
        "\\providecommand{\\URL}",
        "\\providecommand{\\AMname}",
        "\\newenvironment{AM}",
        "\\newcounter{rmnum}",
        "\\newenvironment{romannum}",
        "\\newcounter{muni}",
        "\\newenvironment{remunerate}",
        "\\providecommand{\\Append}",
        "\\providecommand{\\sAppend}",
        "\\providecommand{\\Appendix}",
        "\\secdef\\Append\\sAppend",
    ):
        assert frag in code, f"siamltex 缺 {frag}"
    assert "\\operator@font" not in code


def test_siamart_free_of_siamltex_surface() -> None:
    """siamltex 专有面不得渗入 siamart 纯桥（真身走 amsthm + 稿自定义）。"""
    code = _code_lines(_shim_body("siamart.cls"))
    for frag in ("\\diag", "\\Appendix", "\\sameauthor", "romannum", "remunerate"):
        assert frag not in code, f"siamart 渗入 {frag}"


def test_svjour2_body() -> None:
    r"""svjour2 补面：``\email`` 打印形 ``\emailname: #1`` + ``\subtitle/
    \tens`` + qed 族 + acknowledgement 双 env。"""
    code = _code_lines(_shim_body("svjour2.cls"))
    for frag in (
        "\\providecommand{\\emailname}{E-mail}",
        "\\providecommand{\\email}[1]{\\emailname: #1}",
        "\\providecommand{\\subtitle}",
        "\\providecommand{\\tens}[1]{\\ensuremath{\\mathsf{#1}}}",
        "\\def\\squareforqed",
        "\\providecommand{\\qed}",
        "\\providecommand{\\smartqed}",
        "\\providecommand{\\ackname}",
        "\\newenvironment{acknowledgement}",
        "\\newenvironment{acknowledgements}",
    ):
        assert frag in code, f"svjour2 缺 {frag}"


@pytest.mark.parametrize("key", ["osajnl.cls", "osajnl2.cls"])
def test_osa_body(key: str) -> None:
    """OSA 补面共享锚：存值 noop 件 + ``\bmsection`` + backmatter env。"""
    code = _code_lines(_shim_body(key))
    for frag in (
        "\\providecommand{\\bibliographyfullrefs}",
        "\\providecommand{\\dates}",
        "\\providecommand{\\journalref}",
        "\\providecommand{\\articletype}",
        "\\newenvironment{backmatter}",
        "\\providecommand{\\bmsection}",
    ):
        assert frag in code, f"{key} 缺 {frag}"


def test_jinst_body() -> None:
    r"""JINST 补面：``\preprint`` + arxiv-abbrev 族（体载 hyperref——
    ``\href`` 普查项误报不再补 provide）。"""
    code = _code_lines(_shim_body("JINST.cls"))
    for frag in (
        "\\providecommand{\\preprint}[1]",
        "\\providecommand{\\nuclex}",
        "\\providecommand{\\nuclth}",
        "\\providecommand{\\physics}",
        "\\providecommand{\\quantph}",
        "\\providecommand{\\jinst}",
        "\\providecommand{\\hepth}",
        "\\providecommand{\\hepph}",
        "\\providecommand{\\hepex}",
        "\\providecommand{\\heplat}",
        "\\providecommand{\\grqc}",
        "\\providecommand{\\astroph}",
        "\\providecommand{\\condmat}",
        "\\providecommand{\\mathph}",
        "\\providecommand{\\qalg}",
        "\\providecommand{\\chaodyn}",
        "\\providecommand{\\accphys}",
        "\\providecommand{\\alggeom}",
        "\\providecommand{\\dgga}",
        "\\providecommand{\\nlinsys}",
        "\\providecommand{\\solvint}",
        "\\providecommand{\\suprcon}",
    ):
        assert frag in code, f"JINST 缺 {frag}"
    assert "\\providecommand{\\href}" not in code


def test_pos_body() -> None:
    r"""PoS 补面：``\href`` 打印第二参降级 + ``\pos`` 缩写宏。"""
    code = _code_lines(_shim_body("PoS.cls"))
    assert "\\providecommand{\\href}[2]{#2}" in code
    assert (
        "\\providecommand{\\pos}[1]{\\href{https://pos.sissa.it/#1}{\\tt #1}}" in code
    )


def test_revtex4_mathindent() -> None:
    r"""revtex4 ``\mathindent``（真件 hep-ph/0111060 :306 verbatim =
    ``\@centering``）。"""
    code = _code_lines(_shim_body("revtex4.cls"))
    assert "\\providecommand{\\mathindent}{\\@centering}" in code


# ------------------------------------------------- 有意不补（不变量 pin）
def test_mn2e_no_apspr() -> None:
    r"""mn2e ``\apspr`` 有意不补：6/6 格稿侧 ``\newcommand`` 自定——
    stub 提供会撞 already-def（真件注释态）。"""
    code = _code_lines((SHIMS / "mn2e.cls").read_text(encoding="utf-8"))
    assert "\\apspr" not in code


def test_guarded_defs_idempotent() -> None:
    r"""本波全部新补面走 ``\providecommand``/``\@ifundefined``/``\ifdefined``
    守卫或 ``\def`` 幂等形——无裸 ``\newcommand`` 撞稿内同名。"""
    for key in (
        "aastex61.cls",
        "svjour2.cls",
        "osajnl.cls",
        "siamltex.cls",
        "eptcs.cls",
        "svmult.cls",
        "appolb.cls",
        "kapproc.cls",
        "cimento.cls",
        "PoS.cls",
        "JINST.cls",
        "revtex4.cls",
    ):
        code = _code_lines(_shim_body(key))
        assert "\\newcommand{" not in code, f"{key} 含裸 \\newcommand"


# ------------------------------------------------- xelatex 编译钉
@_COMPILE
@pytest.mark.integration
def test_compile_svjour3_spnewtheorem(tmp_path: Path) -> None:
    r"""svjour3 端到端：``\spnewtheorem`` 三式 + theopargself env + ``\smartqed``。"""
    log = _run(
        tmp_path,
        "\\documentclass{svjour3}\n"
        "\\spnewtheorem{myprop}{Proposition}{\\bfseries}{\\itshape}\n"
        "\\spnewtheorem{mydef}[myprop]{Definition}{\\bfseries}{\\itshape}\n"
        "\\spnewtheorem*{mynote}{Note}{\\itshape}{\\rmfamily}\n"
        "\\begin{document}\n"
        "\\begin{myprop}p\\end{myprop}\n\\begin{mydef}d\\end{mydef}\n"
        "\\begin{mynote}n\\end{mynote}\n"
        "\\begin{theorem}t\\smartqed\\end{theorem}\n"
        "\\begin{theopargself}x\\end{theopargself}\n"
        "\\end{document}\n",
        {"svjour3.cls": (SHIMS / "svjour3.cls").read_text(encoding="utf-8")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_aa_second_surface(tmp_path: Path) -> None:
    r"""aa 端到端：``\tablefoot/\fnmsep/\orcidlink/\element`` + theorem env +
    longtab/dataavailability/acknowledgements envs。[onecolumn] 实选项——
    longtable 内核限制 1-column mode，aa 默认 twocolumn 下 \\begin{longtab}
    必炸（稿侧 longtab 实证全在 referee/onecolumn 语境）。"""
    log = _run(
        tmp_path,
        "\\documentclass[onecolumn]{aa}\n"
        "\\begin{document}\n"
        "\\begin{theorem}t\\end{theorem}\n"
        "A\\fnmsep{a}B \\orcidlink{0000-0000} \\element[][15]{N} \\corr{c}\n"
        "\\begin{longtab}{cc}a&b\\end{longtab}\n"
        "\\tablefoot{note} \\tablefootmark{a}\\tablefoottext{a}{txt}\n"
        "\\begin{dataavailability}d\\end{dataavailability}\n"
        "\\begin{acknowledgements}ok\\end{acknowledgements}\n"
        "\\end{document}\n",
        {"aa.cls": (STUBS / "aa.cls").read_text(encoding="utf-8")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_svjour_makeheadbox_tens(tmp_path: Path) -> None:
    r"""svjour 端到端：稿 ``\renewcommand\makeheadbox``（需前置存在）+
    ``\tens/\fnmsep`` + ``\spnewtheorem`` 路由。"""
    log = _run(
        tmp_path,
        "\\documentclass{svjour}\n"
        "\\renewcommand{\\makeheadbox}{}\n"
        "\\spnewtheorem{thm2}{Thm}{\\bfseries}{\\itshape}\n"
        "\\begin{document}\n"
        "\\tens{x} A\\fnmsep{a}B\n\\begin{thm2}t\\end{thm2}\n"
        "\\end{document}\n",
        {"svjour.cls": (SHIMS / "svjour.cls").read_text(encoding="utf-8")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_aipproc_second_surface(tmp_path: Path) -> None:
    r"""aipproc 端到端：``\SetInternalRegister`` 真赋值 + 画符数学件 +
    ``\tablenote`` tabular 内 + ``\source/\spaceforfigure/\reftextfaraway``。"""
    log = _run(
        tmp_path,
        "\\documentclass{aipproc}\n"
        "\\SetInternalRegister\\hbadness{8000}\n"
        "\\begin{document}\n"
        "$\\sq\\;\\sun\\;x\\lesssim y\\gtrsim z$\n"
        "\\begin{tabular}{c}a\\tablenote{n}\\end{tabular}\n"
        "\\source{s} \\spaceforfigure{2cm}{cap} \\reftextfaraway{l}\n"
        "\\end{document}\n",
        {"aipproc.cls": (SHIMS / "aipproc.cls").read_text(encoding="utf-8")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_siamltex_mathop_lists(tmp_path: Path) -> None:
    r"""siamltex 端到端：mathop 族 + romannum/remunerate envs +
    ``\Appendix`` 换 ``\section`` + ``\URL/\sameauthor``。"""
    log = _run(
        tmp_path,
        "\\documentclass{siamltex}\n\\begin{document}\n"
        "$\\diag(A)\\;\\supp f\\;\\rank M\\;\\const\\;\\grad\\;\\Range$\n"
        "\\begin{romannum}\\item a\\end{romannum}\n"
        "\\begin{remunerate}\\item b\\end{remunerate}\n"
        "a\\sameauthor b\nx \\URL\n"
        "\\Appendix\n\\section{App}\n"
        "\\end{document}\n",
        {"siamltex.cls": _shim_body("siamltex.cls")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_svjour2_body(tmp_path: Path) -> None:
    r"""svjour2 端到端：``\email/\subtitle/\tens`` + ``\smartqed`` +
    acknowledgements env。``\email`` 真件是打印形 ``\emailname: #1``——
    稿内坐 ``\author/\institute`` 块由 ``\maketitle`` 排印，此处 body
    内直调同一路径。"""
    log = _run(
        tmp_path,
        "\\documentclass{svjour2}\n\\subtitle{s}\n"
        "\\begin{document}\n\\email{e@x}\n\\tens{T}\n"
        "\\begin{acknowledgements}thx\\end{acknowledgements}\n"
        "\\smartqed\n\\end{document}\n",
        {"svjour2.cls": _shim_body("svjour2.cls")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_osajnl_body(tmp_path: Path) -> None:
    r"""osajnl 端到端：存值件 + backmatter env + ``\bmsection``。"""
    log = _run(
        tmp_path,
        "\\documentclass{osajnl}\n"
        "\\bibliographyfullrefs{x}\\dates{d}\\journalref{j}\\articletype{t}\n"
        "\\begin{document}\nx\n"
        "\\begin{backmatter}\\bmsection{Supp}s\\end{backmatter}\n"
        "\\end{document}\n",
        {"osajnl.cls": _shim_body("osajnl.cls")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_pos_href(tmp_path: Path) -> None:
    r"""PoS 端到端：``\href`` 打印第二参 + ``\pos`` 缩写宏。"""
    log = _run(
        tmp_path,
        "\\documentclass{PoS}\n\\begin{document}\n"
        "\\href{http://x}{y} \\pos{PoS(ABC)123}\n\\end{document}\n",
        {"PoS.cls": _shim_body("PoS.cls")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_jinst_preprint_abbrevs(tmp_path: Path) -> None:
    r"""JINST 端到端：``\preprint`` + arxiv-abbrev 族（体载 hyperref）。"""
    log = _run(
        tmp_path,
        "\\documentclass{JINST}\n\\preprint{CERN-XX}\n"
        "\\title{T}\\author{A}\n"
        "\\begin{document}\n\\nuclex{0101001} \\quantph{0202002}\n"
        "\\end{document}\n",
        {"JINST.cls": _shim_body("JINST.cls")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_eptcs_frontmatter(tmp_path: Path) -> None:
    r"""eptcs 端到端：``\institute/\email`` 在 ``\author`` 块内（``\\``
    需 tabular 语境）+ firstpage counter + 0 参 holder 改名面。"""
    log = _run(
        tmp_path,
        "\\documentclass{eptcs}\n"
        "\\def\\titlerunning{RT}\\def\\authorrunning{AR}\n"
        "\\title{T}\\author{A \\institute{I} \\email{e@x}}\n"
        "\\begin{document}\n\\maketitle\n"
        "\\setcounter{firstpage}{5}\\event \\volume \\anno \\eid\n"
        "\\end{document}\n",
        {"eptcs.cls": _shim_body("eptcs.cls")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_svmult_toks_spnewtheorem(tmp_path: Path) -> None:
    r"""svmult 端到端：toks 寄存器赋值面 + ``\svhline`` + ``\spnewtheorem`` +
    acknowledgement env。"""
    log = _run(
        tmp_path,
        "\\documentclass{svmult}\n"
        "\\titlerunning{RT}\\authorrunning{AR}\n"
        "\\spnewtheorem{thm}{Thm}{\\bfseries}{\\itshape}\n"
        "\\begin{document}\n"
        "\\inst{1}\\orcidID{0}\\email{e}\n"
        "\\begin{tabular}{c}a\\\\ \\svhline b\\end{tabular}\n"
        "\\begin{thm}t\\end{thm}\n"
        "\\begin{acknowledgement}a\\end{acknowledgement}\n"
        "\\end{document}\n",
        {"svmult.cls": _shim_body("svmult.cls")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_jhep3_abbrevs_newjournal(tmp_path: Path) -> None:
    r"""JHEP3 端到端：``\sissa@jrnl`` 双态——带 brace 引文形 + 裸调缩写 +
    ``\newjournal/\PrHEP``。"""
    log = _run(
        tmp_path,
        "\\documentclass{JHEP3}\n\\title{T}\\author{A}\n\\begin{document}\n"
        "\\ap{1}{2000}{2} \\ptp{3}{2001}{4} \\ap \\nc\n"
        "\\newjournal{Name}{CODE}{v}{y}{p} \\PrHEP{x}\n"
        "\\end{document}\n",
        {"JHEP3.cls": (SHIMS / "JHEP3.cls").read_text(encoding="utf-8")},
    )
    assert _n_err(log) == 0


@_COMPILE
@pytest.mark.integration
def test_compile_sigalt_acmart_kit(tmp_path: Path) -> None:
    r"""sig-alternate 端到端：acmart 桥下 conference kit + ``\category``
    尾可选参吞。"""
    log = _run(
        tmp_path,
        "\\documentclass{sig-alternate}\n"
        "\\conferenceinfo{CONF}{2020}\\CopyrightYear{2020}\\crdata{X}\n"
        "\\category{A.1}{Cat}{Sub}[extra]\n"
        "\\title{T}\\author{A}\n"
        "\\begin{document}\n\\maketitle\nx\n\\end{document}\n",
        {"sig-alternate.cls": _shim_body("sig-alternate.cls")},
    )
    assert _n_err(log) == 0
