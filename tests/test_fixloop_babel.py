r"""babel 车道 (2026-09-19): babel 语言选项系修复钉。

格面: corpus 0707.1325/1003.2165 ([german] → ldf 装好后炸
``\iflanguage{ngerman}`` AtBeginDocument 钩, Arch 格式零非英 \l@*)、
1206.0213 ([english,francais] 弃名)、1306.0435 ([ukrainian,russian] 选项名
≠实档名)。机制三件: ``file_aliases`` 候选桥 (ini
``\BabelDefinitionFile{0}{X}`` 指名实档, try_exts 拼不出) /
``babel_opt_francais_rewrite`` 弃名全位改写 / ``babel_undef`` 类目 +
``babel_undeclared_option`` 选项表头补名 (主语言=末项, 头插不夺主位)。
babelinv 普查钉组 (2026-09-19): 51 枚 ``.ldf`` 显式钉入
``filemap.overrides`` (``.ldf`` 不入索引, 钉是唯一离线确定通路) +
``polytonicgreek`` 裸选项收进 ``babel_opt_polutoniko_rewrite`` 源面。
"""

from pathlib import Path

from _fixloopkit import EngInstall, EngStub, apply, classify, mk_ctx, rs, rule

from texlate.compile.fixloop import actions
from texlate.compile.fixloop.engine import _wire_filemap_overrides
from texlate.compile.logparse import ErrReport


def _apply(
    rid: str, tmp_path: Path, pay: str, eng: EngStub | None = None
) -> tuple[bool, str]:
    """kit ``apply`` 的 ``tmp_path`` 便捷壳——rid 直传、缺省 ``EngStub``。"""
    return apply(rid, mk_ctx(tmp_path), pay, eng=eng)


# ──────────────────────────── taxonomy: babel_undef ────────────────────────────
def test_taxonomy_babel_undef_signature() -> None:
    """'You haven't defined the language X' → babel_undef, payload=X。"""
    cat, pay = classify(
        "! Package babel Error: You haven't defined the language `ngerman' yet.\n"
        "l.740 \\iflanguage{ngerman}\n"
    )
    assert (cat, pay) == ("babel_undef", "ngerman")


def test_taxonomy_babel_opt_not_shadowed() -> None:
    """新增 babel_undef 签不抢 babel_opt 老签 (Unknown option/language)。"""
    cat, pay = classify(
        "! Package babel Error: Unknown option `francais'.\nl.5 \\ProcessOptions"
    )
    assert (cat, pay) == ("babel_opt", "francais")
    cat, pay = classify("! Package babel Error: Unknown language `german'.")
    assert (cat, pay) == ("babel_opt", "german")


# ───────────────────── babel_lang_ldf_install: file_aliases ────────────────────
def test_ldf_install_aliases_registered() -> None:
    """file_aliases 表装载: ukrainian→ukraineb + 抽查全表项。"""
    r = rule("babel_lang_ldf_install")
    assert r.order == 11  # noqa: PLR2004 - schema 断言值
    assert r.when["category"] == "babel_opt"
    aliases = r.action["params"]["file_aliases"]
    assert aliases["ukrainian"] == ["ukraineb.ldf"]
    assert aliases["hungarian"] == ["magyar.ldf"]
    assert aliases["ukenglish"] == ["UKenglish.ldf"]
    # greek 系不入表 —— XeTeX 下 ldf 硬拒, polutoniko 走 ini 改写
    assert "polutonikogreek" not in aliases
    assert "monotonicgreek" not in aliases


def test_filemap_pins_cover_alias_targets() -> None:
    """别名目标档全数钉进 filemap overrides (.ldf 不入索引 → 钉才确定)。"""
    overrides = rs().filemap_cfg["overrides"]
    for fname, pkg in {
        "ukraineb.ldf": "babel-ukrainian",
        "magyar.ldf": "babel-hungarian",
        "slovenian.ldf": "babel-slovenian",
        "UKenglish.ldf": "babel-english",
        "indonesian.ldf": "babel-indonesian",
        "malay.ldf": "babel-malay",
        "brazilian.ldf": "babel-portuges",
        "classicallatin.ldf": "babel-latin",
        "german-at.ldf": "babel-german",
        "nswissgerman.ldf": "babel-german",
        "friulan.ldf": "babel-friulan",
        "lsorbian.ldf": "babel-sorbian",
        "usorbian.ldf": "babel-sorbian",
    }.items():
        assert overrides.get(fname) == pkg, fname


def test_ldf_install_ukrainian_alias_first(tmp_path: Path) -> None:
    """ukrainian payload: 别名 ukraineb.ldf 为首个试装候选 (1306.0435 实档名)。"""
    eng = EngInstall(tmp_path / "texmf", {"ukraineb.ldf"})
    ok, note = _apply("babel_lang_ldf_install", tmp_path, "ukrainian", eng)
    assert ok, note
    assert eng.install_calls == ["ukraineb.ldf"]
    assert "ukraineb.ldf" in note


def test_ldf_install_alias_falls_through_to_exts(tmp_path: Path) -> None:
    """别名装不上 → 续试本名 try_exts 扩展 (别名失败不吞后续候选)。"""
    eng = EngInstall(tmp_path / "texmf", {"ukrainian.ldf"})
    ok, _note = _apply("babel_lang_ldf_install", tmp_path, "ukrainian", eng)
    assert ok
    assert eng.install_calls == ["ukraineb.ldf", "ukrainian.ldf"]


def test_ldf_install_russian_b_ext(tmp_path: Path) -> None:
    """russian 无别名 → try_exts 双候选 [russian.ldf, russianb.ldf] 顺试。"""
    eng = EngInstall(tmp_path / "texmf", {"russianb.ldf"})
    ok, _note = _apply("babel_lang_ldf_install", tmp_path, "russian", eng)
    assert ok
    assert eng.install_calls == ["russian.ldf", "russianb.ldf"]


def test_ldf_install_no_alias_no_match_declines(tmp_path: Path) -> None:
    """francais (弃名, TL 无档): 全候选失败 → applied=False 落改写规则。"""
    eng = EngInstall(tmp_path / "texmf", set())
    ok, _note = _apply("babel_lang_ldf_install", tmp_path, "francais", eng)
    assert not ok
    assert eng.install_calls == ["francais.ldf", "francaisb.ldf"]


# ─────────────────────── babel_opt_francais_rewrite ────────────────────────────
def test_francais_rule_registered() -> None:
    r = rule("babel_opt_francais_rewrite")
    assert r.order == 13.5  # noqa: PLR2004 - schema 断言值
    assert r.when["category"] == "babel_opt"
    assert r.action["kind"] == "regex_rewrite"
    assert "francais" in r.condition["source_contains"]


def test_francais_option_brackets_renamed(tmp_path: Path) -> None:
    """1206.0213 形: usepackage + docclass 选项表内 francais→french。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[a4paper,francais]{article}\n"
        "\\usepackage[english,francais]{babel}\n",
        encoding="utf-8",
    )
    ok, note = _apply("babel_opt_francais_rewrite", tmp_path, "francais")
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\documentclass[a4paper,french]{article}" in t
    assert "\\usepackage[english,french]{babel}" in t
    assert "francais" not in t


def test_francais_body_selectors_renamed(tmp_path: Path) -> None:
    """正文语言引用同改净 —— 漏改会留 'francais' 未声明残错喂 babel_undef。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[english,francais]{babel}\n"
        "\\selectlanguage{francais}\n"
        "\\foreignlanguage{francais}{salut}\n"
        "\\iflanguage{francais}{oui}{non}\n"
        "\\begin{otherlanguage}{francais}x\\end{otherlanguage}\n",
        encoding="utf-8",
    )
    ok, _ = _apply("babel_opt_francais_rewrite", tmp_path, "francais")
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "francais" not in t
    assert "\\selectlanguage{french}" in t
    assert "\\begin{otherlanguage}{french}" in t


def test_francais_word_boundary_respected(tmp_path: Path) -> None:
    """\\b 词界: francais2/xfrancais 非弃名不命中; 无 francais → applied=False。"""
    src = "\\usepackage[franc]{babel}\n\\selectlanguage{xfrancais}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply("babel_opt_francais_rewrite", tmp_path, "francais")
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_francais_condition_gate(tmp_path: Path) -> None:
    """source_contains 闸: 工程无 francais 字样 → condition 拒, 不空转。"""
    r = rule("babel_opt_francais_rewrite")
    (tmp_path / "main.tex").write_text("\\usepackage[french]{babel}\n")
    ok, why = actions._cond_ok(  # noqa: SLF001
        r.condition, r, mk_ctx(tmp_path), EngStub(), "francais"
    )
    assert not ok, why


def test_francais_match_apply_fallthrough(tmp_path: Path) -> None:
    """整链: babel_opt/francais → install 候选全败 decline → 同轮改写规则接住。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[english,francais]{babel}\n", encoding="utf-8"
    )
    eng = EngInstall(tmp_path / "texmf", set())  # francais.ldf 类全装不上
    ctx = mk_ctx(tmp_path, err_head="! Package babel Error: Unknown option `francais'.")
    r, note = actions._match_apply(  # noqa: SLF001
        rs(), ctx, eng, "babel_opt", "francais", ErrReport()
    )
    assert r is not None, note
    assert r.id == "babel_opt_francais_rewrite"
    assert "\\usepackage[english,french]{babel}" in (tmp_path / "main.tex").read_text()


# ─────────────────────── babel_undeclared_option ───────────────────────────────
def test_undeclared_rule_registered() -> None:
    r = rule("babel_undeclared_option")
    assert r.order == 14  # noqa: PLR2004 - schema 断言值
    assert r.when["category"] == "babel_undef"
    assert r.when["payload_required"] is True


def test_undeclared_usepackage_head_insert(tmp_path: Path) -> None:
    """[german]{babel} + payload ngerman → [ngerman,german] (末项主位不动)。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[german]{babel}\n", encoding="utf-8"
    )
    ok, note = _apply("babel_undeclared_option", tmp_path, "ngerman")
    assert ok, note
    assert "\\usepackage[ngerman,german]{babel}" in (tmp_path / "main.tex").read_text()


def test_undeclared_main_position_preserved(tmp_path: Path) -> None:
    """多语言表头插不夺主位: [english,german] → [ngerman,english,german]。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[english,german]{babel}\n", encoding="utf-8"
    )
    ok, _ = _apply("babel_undeclared_option", tmp_path, "ngerman")
    assert ok
    assert (
        "\\usepackage[ngerman,english,german]{babel}"
        in (tmp_path / "main.tex").read_text()
    )


def test_undeclared_bare_and_group_usepackage(tmp_path: Path) -> None:
    """无表形 \\usepackage{babel} → [X]{babel}; 组载 {graphicx,babel} 同盖。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage{babel}\n\\usepackage{graphicx,babel}\n", encoding="utf-8"
    )
    ok, _ = _apply("babel_undeclared_option", tmp_path, "french")
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage[french]{babel}" in t
    assert "\\usepackage[french]{graphicx,babel}" in t


def test_undeclared_docclass_global_options(tmp_path: Path) -> None:
    """docclass 全局选项表头插 (cls 内载 babel 也吃得到); 裸 docclass 新生表。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[12pt]{article}\n\\usepackage[english]{babel}\n",
        encoding="utf-8",
    )
    ok, _ = _apply("babel_undeclared_option", tmp_path, "ngerman")
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\documentclass[ngerman,12pt]{article}" in t
    assert "\\usepackage[ngerman,english]{babel}" in t


def test_undeclared_passoptions_babel_only(tmp_path: Path) -> None:
    """PassOptionsTo{..}{babel} 首参补名; 非 babel 目标不动。"""
    (tmp_path / "main.tex").write_text(
        "\\PassOptionsToPackage{english}{babel}\n"
        "\\PassOptionsToPackage{dvips}{graphicx}\n"
        "\\usepackage{babel}\n",
        encoding="utf-8",
    )
    ok, _ = _apply("babel_undeclared_option", tmp_path, "french")
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\PassOptionsToPackage{french,english}{babel}" in t
    assert "\\PassOptionsToPackage{dvips}{graphicx}" in t


def test_undeclared_no_surface_declines(tmp_path: Path) -> None:
    """无 babel 载点且无 docclass 选项面 → applied=False (不硬改无关文件)。"""
    src = "\\usepackage[dvips]{graphicx}\nhello\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply("babel_undeclared_option", tmp_path, "ngerman")
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_undeclared_payload_substituted(tmp_path: Path) -> None:
    """{payload} 占位替换实证: pay=french 注入 french 而非字面串。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[english]{babel}\n", encoding="utf-8"
    )
    ok, _ = _apply("babel_undeclared_option", tmp_path, "french")
    assert ok
    assert "\\usepackage[french,english]{babel}" in (tmp_path / "main.tex").read_text()


def test_undeclared_match_apply_routes(tmp_path: Path) -> None:
    """整链: babel_undef/ngerman → 规则点火注入 (0707.1325 残签的消费路径)。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[german]{babel}\n", encoding="utf-8"
    )
    ctx = mk_ctx(
        tmp_path,
        err_head="! Package babel Error: You haven't defined the language `ngerman' yet.",
    )
    r, note = actions._match_apply(  # noqa: SLF001
        rs(),
        ctx,
        EngInstall(tmp_path / "texmf", set()),
        "babel_undef",
        "ngerman",
        ErrReport(),
    )
    assert r is not None, note
    assert r.id == "babel_undeclared_option"
    assert "\\usepackage[ngerman,german]{babel}" in (tmp_path / "main.tex").read_text()


# ─────────────── babelinv 普查钉组 (babelinv 车道 ldf_pins 台账) ───────────
def test_census_pins_registered() -> None:
    """51 钉全量入 overrides —— 抽查代表项 + 包名异形格 (samin/turkmen)。"""
    overrides = rs().filemap_cfg["overrides"]
    for fname, pkg in {
        "bulgarian.ldf": "babel-bulgarian",
        "catalan.ldf": "babel-catalan",
        "danish.ldf": "babel-danish",
        "finnish.ldf": "babel-finnish",
        "swedish.ldf": "babel-swedish",
        "japanese.ldf": "babel-japanese",
        "norsk.ldf": "babel-norsk",
        "northernsami.ldf": "babel-samin",  # TL 包名 samin 无 babel- 前缀
        "turkmen.ldf": "turkmen",  # TL 包名即 turkmen
        "afrikaans.ldf": "babel-dutch",  # 实档在 babel-dutch 包
    }.items():
        assert overrides.get(fname) == pkg, fname
    # tlpdb 无档 → 显式 null 已知噪声, 不落 install 往返
    assert overrides["german-traditional.ldf"] is None


def test_census_pins_wire_filemap(tmp_path: Path) -> None:
    """overrides 接线后 eng.filemap 先答钉表: 钉中 → [pkg], null → []。"""
    eng = EngStub()
    _wire_filemap_overrides(eng, rs().filemap_cfg["overrides"], mk_ctx(tmp_path))
    assert eng.filemap("bulgarian.ldf") == ["babel-bulgarian"]
    assert eng.filemap("catalan.ldf") == ["babel-catalan"]
    assert eng.filemap("german-traditional.ldf") == []
    assert eng.filemap("unpinned.ldf") == []  # 未钉 → 委派原查询 (空表)


def test_ldf_install_census_pins(tmp_path: Path) -> None:
    """bulgarian/catalan 直名 .ldf 经 try_exts 首候选装上收口 (live repro 形)。"""
    eng = EngInstall(tmp_path / "texmf", {"bulgarian.ldf", "catalan.ldf"})
    ok, note = _apply("babel_lang_ldf_install", tmp_path, "bulgarian", eng)
    assert ok, note
    ok, note = _apply("babel_lang_ldf_install", tmp_path, "catalan", eng)
    assert ok, note
    assert eng.install_calls == ["bulgarian.ldf", "catalan.ldf"]


def test_ldf_install_unpinned_declines(tmp_path: Path) -> None:
    """无钉无档语言 (klingon): try_exts 双候选全败 → applied=False。"""
    eng = EngInstall(tmp_path / "texmf", set())
    ok, _note = _apply("babel_lang_ldf_install", tmp_path, "klingon", eng)
    assert not ok
    assert eng.install_calls == ["klingon.ldf", "klingonb.ldf"]


# ─────────────── babel_opt_polutoniko_rewrite: polytonicgreek 源 ───────────────
def test_taxonomy_polytonicgreek_payload() -> None:
    """Unknown option 'polytonicgreek' → babel_opt, payload=polytonicgreek。"""
    cat, pay = classify(
        "! Package babel Error: Unknown option 'polytonicgreek'.\nl.3 \\ProcessOptions"
    )
    assert (cat, pay) == ("babel_opt", "polytonicgreek")


def test_polytonicgreek_condition_gate(tmp_path: Path) -> None:
    """condition any 第三 disjunct: 源含裸 polytonicgreek → 放行。"""
    r = rule("babel_opt_polutoniko_rewrite")
    (tmp_path / "main.tex").write_text("\\usepackage[polytonicgreek]{babel}\n")
    ok, why = actions._cond_ok(  # noqa: SLF001
        r.condition, r, mk_ctx(tmp_path), EngStub(), "polytonicgreek"
    )
    assert ok, why


def test_polytonicgreek_option_brackets_rewritten(tmp_path: Path) -> None:
    """babelinv live repro 形: 选项表内 polytonicgreek → greek.polytonic。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[polytonicgreek]{article}\n"
        "\\usepackage[english,polytonicgreek]{babel}\n",
        encoding="utf-8",
    )
    ok, note = _apply("babel_opt_polutoniko_rewrite", tmp_path, "polytonicgreek")
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\documentclass[greek.polytonic]{article}" in t
    assert "\\usepackage[english,greek.polytonic]{babel}" in t
    assert "polytonicgreek" not in t


def test_polytonicgreek_passoptions_rewritten(tmp_path: Path) -> None:
    """PassOptionsTo{Package,Class} 首参 polytonicgreek → greek.polytonic。"""
    (tmp_path / "main.tex").write_text(
        "\\PassOptionsToPackage{polytonicgreek}{babel}\n"
        "\\PassOptionsToClass{polytonicgreek}{article}\n",
        encoding="utf-8",
    )
    ok, note = _apply("babel_opt_polutoniko_rewrite", tmp_path, "polytonicgreek")
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\PassOptionsToPackage{greek.polytonic}{babel}" in t
    assert "\\PassOptionsToClass{greek.polytonic}{article}" in t
    assert "polytonicgreek" not in t


def test_polytonicgreek_no_surface_declines(tmp_path: Path) -> None:
    """无选项位命中 (polytonicgreek 仅在正文) → applied=False, 源不动。"""
    src = "\\usepackage[english]{babel}\n% polytonicgreek mentioned\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply("babel_opt_polutoniko_rewrite", tmp_path, "polytonicgreek")
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src
