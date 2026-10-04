r"""fontfb (2026-09-20): fontspec_missing 克隆替换 + enc.def 摘除两臂 (task #293)。

- ``fontspec_clone_sub`` (fontfb-A): ``fontspec_missing|X`` 中介于
  install_sysfont (家族名/无 filemap 档装不上) 与 font_name_substitute
  (无差别换 Latin Modern) 之间的精确臂 —— 度量克隆表逐茎文件形替换:
  Nimbus 系 → TeX Gyre 同源克隆 (2609.19582), Tinos/NotoSerif → texmf
  truetype 同件 + ``Path``/``Extension``/``*Font`` 捆绑键剥除
  (2609.20064 anthology-ch.cls 实证根因)。家族名在 fixloop 面不可探测
  (run_tool 无 FONTCONFIG_FILE → fc-list 对 texmf 字族恒盲), 文件形经
  ``eng.probe_file`` kpathsea 与 fontspec 文件查找同通路; fontspec 对
  文件形名自动同目录补全字重 (实测 verbatim)。Amiri 不收表 —— TL 内外
  无度量克隆 → decline = 车道裁决 unfixable, 不发错字体声明。
- ``fontenc_enc_relax`` (fontfb-B): ``missing_file|<enc>enc.def`` 全真件
  臂 (install filemap / vendored_fetch) 后的末位改写臂 —— 全文无
  ``\fontencoding{ENC}``/``\DeclareText*{..}{ENC}`` 使用时 fontenc 选项
  表摘 ENC + 裸 ``\DeclareFontEncoding`` 行注释 (2211.13021/2609.19346
  T2A 只载不用); 在用 enc → decline (1312.0514 LGR 由 vendored 真件先行)。
"""

from pathlib import Path

from _fixloopkit import EngStub, mk_ctx, rule

from texlate.compile.fixloop.builtins import (
    fontenc_enc_relax,
    fontspec_clone_sub,
)
from texlate.compile.fixloop.builtins.misschar import (
    _CLONE_TABLE,
    _font_stem,
)


class _FontEng(EngStub):
    """probe_file → ``avail`` 白名单在档 (模拟 texmf 文件形名可达)。"""

    def __init__(self, avail: set[str]) -> None:
        self.avail = avail

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del cwd
        return f"/texmf/{fname}" if fname in self.avail else None


def _params() -> dict:
    return {"exts": (".tex", ".sty", ".cls")}


_NIMBUS_SRC = (
    "\\documentclass{article}\n"
    "\\usepackage{fontspec}\n"
    "\\setmainfont{Nimbus Roman}\n"
    "\\setsansfont{Nimbus Sans}\n"
    "\\setmonofont{Nimbus Mono PS}\n"
    "\\begin{document}\nx\n\\end{document}\n"
)
_GRE_CLONES = {
    "texgyretermes-regular.otf",
    "texgyreheros-regular.otf",
    "texgyrecursor-regular.otf",
}


# ------------------------------------------------------- _font_stem / clone table


def test_font_stem_normalization() -> None:
    """payload 与站点名归一到同茎：文件扩展名 + ``-<weight>`` 尾 + 空白。"""
    assert _font_stem("Tinos-Regular") == "tinos"
    assert _font_stem("Nimbus Roman") == "nimbus roman"
    assert _font_stem("Nimbus Mono PS") == "nimbus mono ps"
    assert _font_stem("Amiri-Regular.ttf") == "amiri"
    assert _font_stem("NotoSerif-Bold") == "notoserif"


def test_clone_table_pins() -> None:
    """克隆表条目钉死 —— Nimbus 系 TeX Gyre 克隆 + Tinos/NotoSerif 同件。"""
    assert _CLONE_TABLE["nimbus roman"] == "texgyretermes-regular.otf"
    assert _CLONE_TABLE["nimbus sans"] == "texgyreheros-regular.otf"
    assert _CLONE_TABLE["nimbus mono ps"] == "texgyrecursor-regular.otf"
    assert _CLONE_TABLE["tinos"] == "Tinos-Regular.ttf"
    assert _CLONE_TABLE["notoserif"] == "NotoSerif-Regular.ttf"
    # Amiri 不收 —— TL 内外皆无度量克隆，强替发错字体声明 (unfixable 裁决)
    assert "amiri" not in _CLONE_TABLE
    # 全表值皆文件形 (kpathsea 可探测); 家族名不可写入站点
    for v in _CLONE_TABLE.values():
        assert v.lower().endswith((".otf", ".ttf"))


# ------------------------------------------------------- fontspec_clone_sub


def test_clone_sub_nimbus_trio(tmp_path: Path) -> None:
    """2609.19582 形：Nimbus 三站点同轮收敛 → TeX Gyre 文件形克隆。"""
    (tmp_path / "main.tex").write_text(_NIMBUS_SRC, encoding="utf-8")
    ok, note = fontspec_clone_sub(
        mk_ctx(tmp_path), _FontEng(_GRE_CLONES), "Nimbus Roman", _params()
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\setmainfont{texgyretermes-regular.otf}" in t
    assert "\\setsansfont{texgyreheros-regular.otf}" in t
    assert "\\setmonofont{texgyrecursor-regular.otf}" in t


def test_clone_sub_tinos_path_bind_strip(tmp_path: Path) -> None:
    """2609.20064 anthology-ch.cls 形：post-opts 全 filebind 组剥净。"""
    src = (
        "\\setmainfont{Tinos}[\n"
        "  Path=fonts/Tinos/,Extension=.ttf,UprightFont=*-Regular,\n"
        "  BoldFont=*-Bold,ItalicFont=*-Italic,BoldItalicFont=*-BoldItalic]\n"
    )
    (tmp_path / "anthology-ch.cls").write_text(src, encoding="utf-8")
    ok, note = fontspec_clone_sub(
        mk_ctx(tmp_path), _FontEng({"Tinos-Regular.ttf"}), "Tinos-Regular", _params()
    )
    assert ok, note
    t = (tmp_path / "anthology-ch.cls").read_text()
    assert "\\setmainfont{Tinos-Regular.ttf}" in t
    assert "Path" not in t


def test_clone_sub_fam_form_mid_opts(tmp_path: Path) -> None:
    """2609.20064 \\newfontfamily 族名形：mid 选项组同剥。"""
    src = (
        "\\newfontfamily\\scfallbackfont{NotoSerif}[\n"
        "  Path=fonts/Noto_Serif/static/,Extension=.ttf,\n"
        "  UprightFont=*-Regular,BoldFont=*-Bold]\n"
    )
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = fontspec_clone_sub(
        mk_ctx(tmp_path), _FontEng({"NotoSerif-Regular.ttf"}), "NotoSerif", _params()
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\newfontfamily\\scfallbackfont{NotoSerif-Regular.ttf}" in t
    assert "Path" not in t


def test_clone_sub_preopts_and_keeps_render_opts(tmp_path: Path) -> None:
    """pre-opts 形 + 非 filebind 渲染键 (Scale/Ligatures) 保留。"""
    src = (
        "\\setmainfont[Path=fonts/Tinos/,Scale=0.95,Ligatures=TeX]{Tinos}\n"
        "\\setsansfont[Path=fonts/X/,BoldFont=*-Bold]{Nimbus Sans}\n"
    )
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    eng = _FontEng({"Tinos-Regular.ttf", "texgyreheros-regular.otf"})
    ok, note = fontspec_clone_sub(mk_ctx(tmp_path), eng, "Tinos", _params())
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\setmainfont[Scale=0.95, Ligatures=TeX]{Tinos-Regular.ttf}" in t
    assert "\\setsansfont{texgyreheros-regular.otf}" in t


def test_clone_sub_amiri_declines_unfixable(tmp_path: Path) -> None:
    """2609.20684 形：Amiri 无克隆表项 → 不动站点，诚实 unfixable。"""
    src = "\\babelfont[arabic]{rm}{Amiri-Regular.ttf}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = fontspec_clone_sub(
        mk_ctx(tmp_path), _FontEng(set()), "Amiri-Regular", _params()
    )
    assert not ok
    assert "no clone-table entry" in note
    assert (tmp_path / "main.tex").read_text() == src


def test_clone_sub_clone_unresolvable_declines(tmp_path: Path) -> None:
    """表项在而克隆件 kpathsea 不可达 → decline 落回 LM 兜底臂。"""
    (tmp_path / "main.tex").write_text(_NIMBUS_SRC, encoding="utf-8")
    ok, note = fontspec_clone_sub(
        mk_ctx(tmp_path), _FontEng(set()), "Nimbus Roman", _params()
    )
    assert not ok
    assert "not resolvable" in note


def test_clone_sub_masked_comment_untouched(tmp_path: Path) -> None:
    """注释内假站点不改写; 全文零活站点 → decline。"""
    src = "% \\setmainfont{Nimbus Roman}\nx\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = fontspec_clone_sub(
        mk_ctx(tmp_path), _FontEng(_GRE_CLONES), "Nimbus Roman", _params()
    )
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_clone_sub_no_matching_site_declines(tmp_path: Path) -> None:
    """payload 在表且克隆可达，但 fileset 无该名字体站点 → decline。"""
    (tmp_path / "main.tex").write_text(
        "\\setmainfont{Latin Modern Roman}\n", encoding="utf-8"
    )
    ok, note = fontspec_clone_sub(
        mk_ctx(tmp_path), _FontEng(_GRE_CLONES), "Nimbus Roman", _params()
    )
    assert not ok
    assert "no fontspec sites" in note


# ------------------------------------------------------- fontenc_enc_relax


def test_enc_strip_unused_t2a_whole_optlist(tmp_path: Path) -> None:
    """2211.13021 形：``[T2A]`` 只载不用 → 方括号连摘 → 裸 fontenc 装载。"""
    src = "\\documentclass{article}\n\\usepackage[T2A]{fontenc}\n\\begin{document}\nx\\end{document}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = fontenc_enc_relax(
        mk_ctx(tmp_path), _FontEng(set()), "t2aenc.def", _params()
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{fontenc}" in t
    assert "T2A" not in t


def test_enc_strip_keeps_sibling_opts(tmp_path: Path) -> None:
    """``[T2A,T1]`` 摘 T2A 留 T1 —— 其余 enc 装载面不动。"""
    src = "\\usepackage[T2A,T1]{fontenc}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = fontenc_enc_relax(
        mk_ctx(tmp_path), _FontEng(set()), "t2aenc.def", _params()
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "T1" in t
    assert "T2A" not in t


def test_enc_decl_commented_with_opt(tmp_path: Path) -> None:
    """裸 ``\\DeclareFontEncoding{ENC}`` 装载点行注释 (decl=def 装载点)。"""
    src = "\\usepackage[T2A]{fontenc}\n\\DeclareFontEncoding{T2A}{}{}\nx\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = fontenc_enc_relax(
        mk_ctx(tmp_path), _FontEng(set()), "t2aenc.def", _params()
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "%\\DeclareFontEncoding{T2A}" in t
    assert "\\usepackage{fontenc}" in t


def test_enc_in_use_declines(tmp_path: Path) -> None:
    """1312.0514 形：``\\fontencoding{LGR}``/``\\DeclareText*`` 在用 → decline。"""
    src = "\\usepackage[LGR,T1]{fontenc}\n{\\fontencoding{LGR}\\selectfont α}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = fontenc_enc_relax(
        mk_ctx(tmp_path), _FontEng(set()), "lgrenc.def", _params()
    )
    assert not ok
    assert "selected in source" in note
    assert (tmp_path / "main.tex").read_text() == src


def test_enc_declaretext_use_declines(tmp_path: Path) -> None:
    """``\\DeclareTextSymbol{cs}{ENC}`` 声明面在用同 decline。"""
    src = "\\usepackage[T2A]{fontenc}\n\\DeclareTextSymbol{\\cyrA}{T2A}{192}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = fontenc_enc_relax(
        mk_ctx(tmp_path), _FontEng(set()), "t2aenc.def", _params()
    )
    assert not ok
    assert "selected in source" in note


def test_enc_use_in_comment_not_use(tmp_path: Path) -> None:
    """注释内 ``\\fontencoding`` 遮盖面不计使用 —— 仍摘除。"""
    src = "% {\\fontencoding{T2A}\\selectfont x}\n\\usepackage[T2A]{fontenc}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = fontenc_enc_relax(
        mk_ctx(tmp_path), _FontEng(set()), "t2aenc.def", _params()
    )
    assert ok
    assert "\\usepackage{fontenc}" in (tmp_path / "main.tex").read_text()


def test_enc_non_encdef_payload_declines(tmp_path: Path) -> None:
    """非 ``<enc>enc.def`` payload (foo.sty) → decline。"""
    ok, note = fontenc_enc_relax(
        mk_ctx(tmp_path), _FontEng(set()), "foo.sty", _params()
    )
    assert not ok
    assert "not an <enc>enc.def" in note


def test_enc_transitive_no_load_site_declines(tmp_path: Path) -> None:
    """装载点不在 fileset (babel ldf 内传递请求) → decline。"""
    (tmp_path / "main.tex").write_text("\\usepackage{inputenc}\nx\n", encoding="utf-8")
    ok, note = fontenc_enc_relax(
        mk_ctx(tmp_path), _FontEng(set()), "t2aenc.def", _params()
    )
    assert not ok
    assert "transitive" in note


# ------------------------------------------------------- 规则注册钉


def test_clone_sub_rule_registered() -> None:
    """order 30.5 —— install(30) 后 LM 兜底 (31) 前; 仅 fontspec_missing 点火。"""
    r = rule("fontspec_clone_sub")
    assert r.order == 30.5  # noqa: PLR2004 - schema 断言值
    assert r.when["category"] == "fontspec_missing"
    assert r.when["payload_required"] is True
    assert r.action["kind"] == "builtin_transform"
    assert r.action["function"] == "fontspec_clone_sub"
    assert "amiri" not in r.action["params"]["clone_table"]
    # yaml clone_table 是 builtin ``_CLONE_TABLE`` 的显式重述 (60-misschar.yaml
    # 注明「同表」) —— ``params.get(...) or _CLONE_TABLE`` 让 yaml 整表顶替
    # builtin, 全表等值钉防两份拷贝静默漂移。
    assert {
        _font_stem(str(k)): str(v) for k, v in r.action["params"]["clone_table"].items()
    } == _CLONE_TABLE


def test_enc_relax_rule_registered() -> None:
    """order 11.995 —— 全真件臂后 shim 前; enc.def 标记限定点火。"""
    r = rule("fontenc_enc_relax")
    assert r.order == 11.995  # noqa: PLR2004 - schema 断言值
    assert r.when["category"] == "missing_file"
    assert "enc" in r.condition["ctx_suggests"]
    assert r.action["kind"] == "builtin_transform"
    assert r.action["function"] == "fontenc_enc_relax"
