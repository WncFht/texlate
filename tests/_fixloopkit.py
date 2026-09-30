"""fixloop 规则钉测试公共骨架——``EngStub``/``mk_ctx``/``rs``/``rule``/``classify``/``apply`` + 真 xelatex 臂。

``test_fixloop_*`` 簇逐文件复刻的同构脚手架归此一处（沿用
``_workerkit``/``_fuzzkit`` 抽取先例——首批只抽不写回，此后各车道
陆续回嫁 import；新批次规则钉文件只需 payloads + assertions）：

- ``EngStub``：builtin_transform/condition 直驱路径的最小引擎替身
  （``probe_file``→None / ``filemap``→[] / ``install_file``→False），
  ~70 文件同体；``EngInstall`` = 可装件子类（installable 集合内名落
  fake texmf，probe 复核命中，``install_calls`` 记账）。
- ``EngHit``/``EngProbe``/``EngMissing``：``EngStub`` 两反相替身——
  恒中（probe→``/texmf/<fname>`` + install→True）与双侧恒缺
  （probe→``""`` + install→False）。csfix 族 ~9 文件局部 ``_EngStub``
  实为恒中形——同名反语义是真实 swap-trap，故子类新名而非 flag。
- ``ShadowEng``：``EngStub`` + ``texmf`` 目录直查 probe（``extra``
  逐名覆盖命中位），遮蔽道 7 文件 ``_ShadowEng`` 同体归此
  （vendorcwd 的 revtex4-2.cls 硬编码 probe 形不同，不收）。
- ``mk_ctx``：``LoopCtx(wdir=tmp_path, engine_name="xelatex",
  main_rel=..., err_head=..., runner=...)`` 工厂——89 文件同体；
  ``runner`` kwarg 透传取代 post-ctor ``ctx.runner =`` workaround。
- ``rs``/``rule``/``params``/``classify``：ruleset 装载（``lru_cache``
  单发——load_ruleset 每调深拷重校验的回归面归此）/ rid 查规则 /
  ``action["params"]`` 直取 / log 文本分类（``warn`` kwarg 控
  ``warn_patterns`` 透传，与生产 ``_report_of`` 同口径，
  ``warn_*`` 伪类行可达）。
- ``apply``/``cond_ok``/``cond``/``when_cond_ok``/``match_apply``/
  ``match``：``actions._apply/_cond_ok/_when_ok/_match_apply`` 直驱
  集中点——``# noqa: SLF001`` 豁免一处收口（47+ 文件各自豁免归此）。
- 真 xelatex 臂：``XELATEX`` 路径常量 + ``requires_xelatex`` skipif 钉
  （32 处同名散钉）+ ``run_xelatex``（写 main.tex → nonstopmode 编译 →
  回读 main.log；``extra`` 落侧车件、``passes`` 多轮）+
  ``run_xelatex_proc``（``-halt-on-error`` CompletedProcess 形，
  institutesig/paralong 的 ``_xelatex`` 双胞胎归此）+ ``n_err``
  （``^! `` 计数）。
- ``DOC``/``MAIN_DOC``：最小 article 壳 / ``\\usepackage{somepkg}`` 壳
  （primarg/primguard/primofw 逐字节同体）；``MNRAS_BUGGY_CLS`` +
  ``mnras_buggy_cls`` 病件指纹厂（mnrasretire 全形 / sitehoist 两行形）。
- ``VENDOR``/``VENDOR_ROOT``/``STUBS``/``SHIMS``/``VENDOR_FILES``：包内
  ``vendor/`` 根与三层路径常量——逐文件 ``__file__`` 推导归此一处；
  ``shim_map``/``vendor_file``/``shim_body``/``write_shim`` shim-pin 族
  （``vendor_file`` 按真实 emit 序 files→stubs→shims 扫层，
  与 ``_vendored_source`` 同口径）。
- 杂项替身/工厂：``ISOLATE_PARAMS`` + ``proj_texmf``/``proj_pair``
  （遮蔽道 proj/texmf 双目录厂）、``write_file``/``write_files``/
  ``read_rel``（mkdir-parents 落件惯用法）、``mk_ctx_files``
  （files-dict ctx 厂）、``code_lines``（% 注释行剥离）、
  ``which_only``（shutil.which 假件厂）、``sh_runner``（subprocess
  直通 RunFn）、``biber_ok``（biber 假件 runner）、``mk_vendor``/
  ``vendored_fetch``（wdir 内 vendor 树 + TRANSFORM_FNS 直驱）。
- 脚本化 e2e 臂：``CLEAN_LOG``/``XETEX_CLEAN_LOG``/``MAIN_TEX`` 语料 +
  ``MockRes``/``MockEngine``（逐轮吐 spec 的脚本引擎；``caps``/
  ``available``/``installable``/``probe_cwd`` kwarg 折各车道变体）+
  ``make_proj``/``mini_rs`` 工厂 + ``BOOM_LOG``/``BOOM_TAXONOMY``/
  ``run_tool_rules``（合成 ruleset 机械钉语料）+ ``MockTectonic``/
  ``SalvageMockEngine``（tectonic/best_effort 引擎变体）——原
  ``test_fixloop_loop`` hub 共享件全数迁此，含 loop 文件自身的
  30+ 兄弟文件一律从这里取件，不 import 测试模块。
  ``ScriptEng``/``ScriptedEng``/``ScriptedRes``/``SpecRes``/
  ``ScriptedEngine``/``ScriptEngine``/``LoopEngine`` 为历代命名别名
  （``ScriptedEngine`` 与 test_e2e_wiring.py:84 的 callable-script 类
  同名不同形——同名阱已记，新车道请用 ``ScriptEngine``/
  ``MockEngine``）。``mini_rs`` 增 ``warnings`` kwarg 供 warn 域
  合成 ruleset（缺省与原形等价）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.logparse import ErrReport, parse_text

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from texlate.compile.fixloop.engine import Engine, RunFn
    from texlate.compile.fixloop.ruleset import Rule


#: 最小 article 文档壳——``\\documentclass{article}`` + ``x`` 正文。
DOC = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"

#: ``\\usepackage{somepkg}`` 文档壳 (primarg/primguard/primofw 逐字节同体)。
MAIN_DOC = (
    "\\documentclass{article}\n\\usepackage{somepkg}\n"
    "\\begin{document}\nx\n\\end{document}\n"
)

#: 宿主机 xelatex 绝对路径（缺席 → ``requires_xelatex`` 臂整体跳过）。
XELATEX = shutil.which("xelatex")

#: 包内 vendor 根 + 三层路径常量——逐文件 ``__file__`` 推导归此一处。
VENDOR = Path(actions.__file__).resolve().parent / "vendor"
#: ``VENDOR`` 别名：部分车道 (stubaudit 等 ~20 件) 按 root 名义引用。
VENDOR_ROOT = VENDOR
STUBS = VENDOR / "stubs"
#: ``.cls`` 替身 stub 归位层 (F2)。
SHIMS = VENDOR / "shims"
#: ``vendored_fetch`` 真件层。
VENDOR_FILES = VENDOR / "files"

#: 真编译臂 skipif 钉——原 ``_COMPILE``/``_HAS_XELATEX``/内联 mark 归此一名。
requires_xelatex = pytest.mark.skipif(XELATEX is None, reason="xelatex not installed")


class EngStub:
    """builtin_transform/condition 直驱路径的最小引擎替身（不触真 texmf）。"""

    name = "xelatex"
    caps: frozenset[str] = frozenset()

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False

    def rebuild_fontmaps(self) -> None:
        """updmap noop."""


class EngInstall(EngStub):
    """``EngStub`` + install_file：installable 集合内名落 fake texmf，probe 复核命中。"""

    def __init__(self, texmf: Path, installable: set[str]) -> None:
        self.texmf = texmf
        self.texmf.mkdir(parents=True, exist_ok=True)
        self.installable = set(installable)
        self.install_calls: list[str] = []

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if cwd is not None and (Path(cwd) / fname).is_file():
            return str(Path(cwd) / fname)
        hit = self.texmf / fname
        return str(hit) if hit.is_file() else None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del font_related
        self.install_calls.append(fname)
        if fname not in self.installable:
            return False
        (self.texmf / fname).write_text("", encoding="utf-8")
        return True


class EngHit(EngStub):
    """``EngStub`` 的恒中反相：``probe_file`` → ``/texmf/<fname>``, ``install_file`` → True。

    csfix 族 ~9 文件局部 ``_EngStub`` 实为恒中形——同名反语义是真实
    swap-trap，故子类化新名（而非 ``hit=True`` flag）保 ``EngStub``
    恒缺签名稳定；``EngProbe`` 为同体别名。
    """

    def probe_file(self, fname: str, cwd: Path | None = None) -> str:
        del cwd
        return f"/texmf/{fname}"

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return True


#: ``EngHit`` 同体别名（csfix2._EngStub 等恒中形命名面）。
EngProbe = EngHit


class EngMissing(EngStub):
    """双侧均缺替身：``probe_file`` → ``""``, ``install_file`` → False (WARNING 支路)。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> str:
        del fname, cwd
        return ""


class ShadowEng(EngStub):
    """``EngStub`` + ``texmf`` 目录直查 probe（模拟系统副本在场）；``extra`` 逐名覆盖命中位。

    pstshadow/citekey_shadow/revtexretire/amsretire/pathqual/providesdate/
    unk26 七文件 ``_ShadowEng`` 同体归此——``filemap``/``install_file``/
    ``caps``/``rebuild_fontmaps`` 承 ``EngStub``。vendorcwd 的
    revtex4-2.cls 硬编码 probe 形不同，不收。
    """

    def __init__(self, texmf: Path, extra: dict[str, Path] | None = None) -> None:
        self.texmf = texmf
        self.extra = extra or {}

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del cwd
        if fname in self.extra:
            return str(self.extra[fname])
        p = self.texmf / fname
        return str(p) if p.is_file() else None


def mk_ctx(
    tmp_path: Path,
    main_rel: str | None = "main.tex",
    err_head: str = "",
    *,
    runner: RunFn | None = None,
) -> LoopCtx:
    """直驱面 ``LoopCtx`` 工厂——xelatex 名钉死；``err_head``/``runner`` 透传。

    ``runner`` 直通 ``LoopCtx`` 构造参（外部工具调用注入点）——取代
    orphan_rules/tarmember 的 post-ctor ``ctx.runner =`` workaround。
    """
    return LoopCtx(
        wdir=tmp_path,
        engine_name="xelatex",
        main_rel=main_rel,
        err_head=err_head,
        runner=runner,
    )


@lru_cache(maxsize=1)
def rs() -> Ruleset:
    """``load_ruleset()`` 直通——``lru_cache`` 单发。

    ``load_ruleset`` 每调深拷 + 重校验一份 Ruleset；~64 文件批量查件的
    回归面归此一发。返回共享实例——调用方不得就地改 rules/params，
    改前先 ``dict(...)``/深拷；需重载的车道用 ``rs.cache_clear()``。
    """
    return load_ruleset()


def rule(rid: str) -> Rule:
    """按 rid 取规则行。"""
    return next(r for r in rs().rules if r.id == rid)


def params(rid: str) -> dict:
    """按 rid 取规则 ``action["params"]``——cs_table/shim_map/直驱 params 单入口。"""
    return rule(rid).action["params"]


def classify(text: str, *, warn: bool = True) -> tuple[str | None, str | None]:
    """log 文本 → ``(category, payload)``——``parse_text`` + taxonomy 直通。

    ``warn_patterns`` 透传与生产 ``_report_of`` 同口径——不喂则
    ``rep.warnings`` 恒空、``warn_*`` 伪类行不可达；``warn=False``
    关 warn 域喂入。
    """
    ruleset = rs()
    return ruleset.taxonomy.classify(
        parse_text(text, ruleset.warn_patterns if warn else None)
    )


def apply(
    rule_or_rid: Rule | str,
    ctx: LoopCtx,
    pay: str | None,
    *,
    eng: Engine | None = None,
) -> tuple[bool, str]:
    """``actions._apply`` 直驱集中点——SLF001 豁免一处收口。

    ``rule_or_rid`` 收 ``Rule`` 或 rid 字符串；``eng`` 缺省 ``EngStub()``
    （需 ``EngInstall`` 记账的调用方传实例进来）。
    """
    r = rule(rule_or_rid) if isinstance(rule_or_rid, str) else rule_or_rid
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        r, ctx, eng or EngStub(), pay, ErrReport()
    )


def cond_ok(  # noqa: PLR0913 - 与 _cond_ok 同签名面
    rule_or_rid: Rule | str,
    ctx: LoopCtx,
    pay: str | None = None,
    *,
    eng: Engine | None = None,
    cond: dict | None = None,
    rep: ErrReport | None = None,
) -> tuple[bool, str]:
    """``actions._cond_ok`` 直驱集中点——SLF001 豁免一处收口。

    ``rule_or_rid`` 收 ``Rule`` 或 rid；``eng`` 原样透传（``None`` 合法——
    不触 eng 面的条件闸惯用形）；``cond`` 可覆盖评估用 condition dict；
    ``rep`` 喂 ``err_outside_fileset`` 等消费 ``ErrReport`` 的条件键。
    """
    r = rule(rule_or_rid) if isinstance(rule_or_rid, str) else rule_or_rid
    return actions._cond_ok(  # noqa: SLF001 - 钉规则条件直驱
        r.condition if cond is None else cond,
        r,
        ctx,
        eng,
        pay,
        rep,
    )


def cond(
    rule_or_rid: Rule | str,
    ctx: LoopCtx,
    eng: Engine | None = None,
    pay: str | None = None,
) -> tuple[bool, str]:
    """``cond_ok`` 的 positional-eng 形（driverdef._lane 同签名面）。"""
    return cond_ok(rule_or_rid, ctx, pay, eng=eng)


def when_cond_ok(  # noqa: PLR0913, PLR0917 - 派发钉签名面 (rid/cat/pay/err_head/wdir 位序钉死)
    rid: str,
    cat: str | None,
    pay: str | None,
    err_head: str,
    wdir: Path,
    eng: Engine | None = None,
) -> bool:
    """``when + condition`` 联合判定——``pick_and_apply`` 同口径派发钉。

    ctx 经 ``mk_ctx(wdir, err_head=err_head)``；``eng`` 缺省 ``EngStub()``
    （与 ``apply`` 同例）——singbun/aux_eof 的 ``_dispatch`` 双胞胎归此。
    """
    r = rule(rid)
    ctx = mk_ctx(wdir, err_head=err_head)
    w_ok = actions._when_ok(r.when, cat, pay, ctx)  # noqa: SLF001
    c_ok = actions._cond_ok(  # noqa: SLF001
        r.condition, r, ctx, eng or EngStub(), pay
    )[0]
    return w_ok and c_ok


def match_apply(  # noqa: PLR0913 - 与 _match_apply 同签名面
    ctx: LoopCtx,
    cat: str | None,
    pay: str | None,
    rep: ErrReport | None = None,
    *,
    eng: Engine | None = None,
    only: Callable[[Rule], bool] | None = None,
) -> tuple[Rule | None, str]:
    """``actions._match_apply`` 直驱集中点——ruleset 取 ``rs()``，SLF001 一处收口。

    ``eng`` 原样透传（``None`` 合法——但触 eng 面的条件会裸炸，需引擎
    替身语义的调用方传 ``EngStub()``）；``rep`` 缺省空 ``ErrReport``；
    ``only`` 族过滤器透传。
    """
    return actions._match_apply(  # noqa: SLF001 - 路由行为直驱
        rs(),
        ctx,
        eng,
        cat,
        pay,
        rep if rep is not None else ErrReport(),
        only,
    )


def match(
    ctx: LoopCtx,
    pay: str | None,
    cat: str,
    rep: ErrReport,
    *,
    eng: Engine | None = None,
) -> Rule | None:
    """``match_apply`` 便捷形——``eng`` 缺省 ``EngStub()``，回 ``hit`` 规则。

    primofw._match 口径：``_cond_ok`` 在 ``_match_apply`` 的 try/except
    之外跑，条件原语触 eng 面不能裸炸 → eng 给 ``EngStub()`` 而非 None。
    需 ``(hit, note)`` 对或 verbatim ``eng=None`` 的调用方用
    ``match_apply``。
    """
    hit, _note = match_apply(ctx, cat, pay, rep, eng=eng or EngStub())
    return hit


def run_xelatex(
    wdir: Path,
    tex: str,
    *,
    extra: dict[str, str] | None = None,
    passes: int = 1,
) -> str:
    """写 ``main.tex``（+ ``extra`` 侧车件）→ nonstopmode 编译 ``passes`` 轮 → 回读 ``main.log``。"""
    (wdir / "main.tex").write_text(tex, encoding="utf-8")
    for name, body in (extra or {}).items():
        (wdir / name).write_text(body, encoding="utf-8")
    for _ in range(passes):
        subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
            [XELATEX, "-interaction=nonstopmode", "main.tex"],
            cwd=wdir,
            capture_output=True,
            timeout=120,
            check=False,
        )
    return (wdir / "main.log").read_text(encoding="utf-8", errors="replace")


def run_xelatex_proc(wdir: Path) -> subprocess.CompletedProcess[str]:
    """``xelatex -interaction=nonstopmode -halt-on-error main.tex`` → CompletedProcess。

    ``run_xelatex`` 的进程形变体（institutesig/paralong 的 ``_xelatex``
    双胞胎归此）——不写 main.tex（调用方自理），返回 CompletedProcess
    供 rc/stdout 断言。
    """
    return subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [XELATEX, "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
        cwd=wdir,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def n_err(log: str) -> int:
    """``^! `` 行计数——硬错数。"""
    return len(re.findall(r"^! ", log, re.MULTILINE))


# ---------------------------------------------------------------- 杂项替身/工厂

#: ``vendored_shadow_isolate`` 系 transform params 公共底 (exts+suffix)——
#: 调用方须 ``dict(ISOLATE_PARAMS)`` 拷贝 (部分车道就地改 params)。
ISOLATE_PARAMS = {"exts": (".sty", ".cls"), "suffix": ".fixloop-iso"}

#: 上游 mnras.cls v3.2 病件指纹全形 (mnrasretire canonical): 头注 +
#: ``\\newif`` + ``\\ds@usegraphicx`` 行内联 ``\\usepackage`` +
#: ``\\ProcessOptions`` 收尾。只要头注 + 病行两行的车道用
#: ``mnras_buggy_cls()`` (sitehoist 形)。
MNRAS_BUGGY_CLS = (
    "% mnras.cls v3.2 (upstream)\n"
    "\\newif\\if@usegraphicx\n"
    "\\def\\ds@usegraphicx{\\@usegraphicxtrue\\usepackage{graphicx}}\n"
    "\\ProcessOptions\\relax\n"
)


def mnras_buggy_cls(*, before: Iterable[str] = (), after: Iterable[str] = ()) -> str:
    """mnras v3.2 病件指纹骨架：头注行 + ``before`` 行 + ``\\ds@usegraphicx`` 病行 + ``after`` 行。

    指纹不变量是头注 + 病行（行内联 ``\\usepackage``）；``before``/``after``
    槽插周件行（``\\newif`` 前置 / ``\\ProcessOptions`` 收尾）。零参 =
    sitehoist 两行形；``MNRAS_BUGGY_CLS`` 即 ``before=["\\\\newif..."]``
    + ``after=["\\\\ProcessOptions..."]`` 的全形展开。
    """
    lines = [
        "% mnras.cls v3.2 (upstream)",
        *before,
        "\\def\\ds@usegraphicx{\\@usegraphicxtrue\\usepackage{graphicx}}",
        *after,
    ]
    return "\n".join(lines) + "\n"


def write_file(wdir: Path, name: str, text: str) -> Path:
    """``<wdir>/<name>`` mkdir-parents + utf-8 写入 → 落件 Path。

    institutesig/paralong/burnfix 的 ``_write`` 逐字节同体归此；与
    singbun/runaway/mathbd 的 ``_write(tmp, body, name="main.tex")``
    异签名形不兼容——那些车道不迁。
    """
    p = wdir / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def write_files(wdir: Path, files: dict[str, str]) -> None:
    """``{rel: text}`` 批量落 ``wdir`` 下 (csfix2._proj 同体; mkdir-parents + utf-8)。"""
    for rel, text in files.items():
        write_file(wdir, rel, text)


def read_rel(wdir: Path, rel: str) -> str:
    """``<wdir>/<rel>`` utf-8 回读 (csfix2._read 同体)。"""
    return (wdir / rel).read_text(encoding="utf-8")


def code_lines(body: str) -> str:
    """滤 % 注释行后拼接——pin 断言不得被注释文本夹带。"""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("%"))


def which_only(*names: str) -> Callable[[str], str | None]:
    """``shutil.which`` 假件工厂：名单内名 → ``/usr/bin/<name>``, 否则 ``None``。"""
    return lambda n: f"/usr/bin/{n}" if n in names else None


def sh_runner(
    argv: list[str], timeout: int, wdir: Path
) -> tuple[int, str, float, bool]:
    """真跑 argv 的 ``RunFn`` 直通 runner → (rc, out, sec, timed_out)。

    不仿真脚本语义——subprocess 原样执行 (env 继承 → monkeypatch
    TEXMFHOME/PATH 可注假件), 指纹闸/find/kpsewhich 都走真件
    (mnrasretire/sitehoist/pstadd 逐字节同体)。
    """
    p = subprocess.run(  # noqa: S603 - argv 列表无 shell 拼接; sh -c 是规则自身的原语
        argv,
        cwd=wdir,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or ""), 0.0, False


def biber_ok(argv: list[str], _timeout: int, wdir: Path) -> tuple:
    """模拟 biber: 落 ``<stem>.bbl`` (argv[1] stem, 可带子目录), rc=0。"""
    (wdir / f"{argv[1]}.bbl").write_text("% regen", encoding="utf-8")
    return 0, "INFO - This is Biber 2.22", 0.5, False


def proj_texmf(tmp_path: Path) -> tuple[Path, Path]:
    """``proj/`` + ``texmf/`` 兄弟目录对——遮蔽道 wdir/系统面分居。

    probe 命中 wdir 内件会被判工程自件，故系统副本必须落 wdir 外的
    ``texmf/`` 兄弟目录 (pstshadow._proj_texmf 同体)。
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    texmf = tmp_path / "texmf"
    texmf.mkdir()
    return proj, texmf


def proj_pair(tmp_path: Path, name: str, local: str, sys: str) -> Path:
    """``proj_texmf`` + 落件形：``local`` 进 ``proj/<name>``, ``sys`` 进 ``texmf/<name>``, 返回 proj。"""
    proj, texmf = proj_texmf(tmp_path)
    (proj / name).write_text(local, encoding="utf-8")
    (texmf / name).write_text(sys, encoding="utf-8")
    return proj


def mk_ctx_files(
    tmp_path: Path,
    files: dict[str, str],
    *,
    main: str | None = None,
    engine: str = "xelatex",
) -> LoopCtx:
    """files-dict ctx 厂：各 ``{rel: text}`` 落 ``tmp_path`` 下 → ``LoopCtx``。

    ``main`` 缺省取 ``files`` 首键 (``next(iter(files))``——l1_verify 口径);
    epsplaceholder/haltsweep/gfxinclude 的 ``_ctx`` 双胞胎归此。
    """
    write_files(tmp_path, files)
    return LoopCtx(
        wdir=tmp_path,
        engine_name=engine,
        main_rel=main or next(iter(files)),
    )


def mk_vendor(tmp_path: Path) -> Path:
    """wdir 内 ``vendor/{files,stubs}`` 树 → 返 vendor 根 (vendored_fetch 的 dir 源)。"""
    root = tmp_path / "vendor"
    (root / "files").mkdir(parents=True)
    (root / "stubs").mkdir(parents=True)
    return root


def vendored_fetch(ctx: LoopCtx, payload: str, root: Path) -> tuple[bool, str]:
    """``TRANSFORM_FNS["vendored_fetch"]`` 直驱壳——``{"dir": str(root)}`` params 内置。"""
    return TRANSFORM_FNS["vendored_fetch"](ctx, None, payload, {"dir": str(root)})


# ------------------------------------------------------------ shim-pin 族


def shim_map() -> dict[str, dict]:
    """``legacy_pkg_shim`` 规则的 ``action.params.shim_map`` 直取。"""
    return rule("legacy_pkg_shim").action["params"]["shim_map"]


def vendor_file(name: str) -> Path | None:
    """vendor 三层查件：``files`` → ``stubs`` → ``shims`` 真实 emit 序。

    序与 ``_vendored_source`` (``builtins.vendored``) 同口径——stubaudit
    的就地版曾按 (SHIMS, STUBS, VENDOR_FILES) 反序扫，归此一处正之。
    """
    for layer in (VENDOR_FILES, STUBS, SHIMS):
        vend = layer / name
        if vend.is_file():
            return vend
    return None


def shim_body(name: str) -> str:
    """shim_map body 直取; 槽已删名 (routeclean) 回退 vendored_fetch 实件。"""
    spec = shim_map().get(name)
    if spec is None:
        vend = vendor_file(name)
        if vend is not None:
            return vend.read_text(encoding="utf-8")
        raise KeyError(name)
    assert "body" in spec, f"{name} 无 body 键"
    return spec["body"]


def write_shim(wdir: Path, name: str) -> None:
    r"""把 shim_map body (或 ``loads`` 模板 / vendored 实件) 物化成 ``<wdir>/<name>``。

    复刻 ``builtins.shim`` 的 emit 面——编译钉直打真实生成物; 槽已删名
    改物化 vendored_fetch 实件 (同服务物)。
    """
    spec = shim_map().get(name)
    if spec is None:
        vend = vendor_file(name)
        if vend is None:
            raise KeyError(name)
        (wdir / name).write_text(vend.read_text(encoding="utf-8"), encoding="utf-8")
        return
    body = spec.get("body")
    if body is None:
        loads = spec["loads"]
        stem = name.rsplit(".", 1)[0]
        body = (
            "\\NeedsTeXFormat{LaTeX2e}\n"
            f"\\ProvidesClass{{{stem}}}[2026/09/19 fixloop legacy shim -> {loads}]\n"
            f"\\LoadClassWithOptions{{{loads}}}\n"
            "\\endinput\n"
        )
    (wdir / name).write_text(body, encoding="utf-8")


# ---------------------------------------------------------------- 脚本化 e2e 臂
#
# 原 ``test_fixloop_loop`` hub 的 canonical 本营（共享件逐字节迁此——
# loop 文件自身也改为从这里 import，任何文件不再 import 测试模块）。

CLEAN_LOG = "This is pdfTeX\nOutput written on main.pdf (1 page).\n"
#: XeTeX banner 变体 (aux_eof/csvsimple/mnrasretire/enguard 等 ~10 文件同体)。
XETEX_CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"
MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n"


class MockRes:
    """impl CompRes 的 duck-type 替身 (compile/engine.py:56)。"""

    def __init__(self, wdir: Path, main: str, spec: dict | str) -> None:
        if isinstance(spec, str):
            spec = {"log": spec}
        stem = Path(main).stem
        self.log_path = wdir / f"{stem}.log"
        self.log_path.write_text(spec.get("log", ""), encoding="utf-8")
        if spec.get("wipe_pdf"):  # 镜像真引擎 stale-unlink (compile/engine.py:948)
            (wdir / f"{stem}.pdf").unlink(missing_ok=True)
        self.pdf = wdir / f"{stem}.pdf" if spec.get("pdf") else None
        if self.pdf is not None:
            self.pdf.write_bytes(b"%PDF-1.4 fake")
        if spec.get("aux") is not None:  # 模拟被杀编译驻留的 aux
            (wdir / f"{stem}.aux").write_text(spec["aux"], encoding="utf-8")
        self.pdf_bytes = self.pdf.stat().st_size if self.pdf else 0
        self.timed_out = bool(spec.get("timed_out"))
        #: 镜像 CompRes.killed_signal (任一 pass 被信号杀死记信号号)。
        self.killed_signal = spec.get("killed_signal")
        #: 镜像 CompRes.rc (末 pass 退出码; 驱动 fatal 形 = rc>0 非信号)。
        self.rc = spec.get("rc")
        self.seconds = 0.05
        self.stdout_tail = spec.get("tail", "")
        #: 镜像 CompRes.log_text (编译期已读 .log 原文)——缺省 "" 走文件读。
        self.log_text = spec.get("log_text", "")

    @property
    def has_pdf(self) -> bool:
        return self.pdf is not None and self.pdf_bytes > 0


class MockEngine:
    """script 逐轮吐 spec; 耗尽后重放末条。

    构造 kwarg 折各车道变体：``installable``/``available`` 集合、
    ``caps`` 实例覆盖 (缺省承类面 ``{kpsewhich,tlmgr,updmap}``——传
    ``None`` 不冲掉子类类属性钉版，如 draftsty)、``probe_cwd=False``
    关 cwd 先查 (nataux 形 probe→None 保真)。
    """

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr", "updmap"})

    def __init__(
        self,
        script: list,
        *,
        installable: Iterable[str] = (),
        available: Iterable[str] = (),
        caps: Iterable[str] | None = None,
        probe_cwd: bool = True,
    ) -> None:
        self.script = list(script)
        self.installable = set(installable)
        self.available = set(available)
        if caps is not None:
            self.caps = frozenset(caps)
        self.probe_cwd = probe_cwd
        self.filemap_tbl: dict[str, list[str]] = {}
        self.rounds = 0
        self.fontmaps = 0
        self.install_calls: list[str] = []

    def compile(
        self, wdir: Path, main: str, *, passes: int = 2, **_kw: object
    ) -> MockRes:
        del passes, _kw  # mock 不需要
        i = min(self.rounds, len(self.script) - 1)
        self.rounds += 1
        return MockRes(Path(wdir), main, self.script[i])

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if self.probe_cwd and cwd is not None and (Path(cwd) / fname).is_file():
            return str(Path(cwd) / fname)
        if fname in self.available:
            return f"/texmf/{fname}"
        return None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del font_related
        self.install_calls.append(fname)
        if fname in self.installable:
            self.available.add(fname)
            return True
        return False

    def rebuild_fontmaps(self) -> bool:
        self.fontmaps += 1
        return True

    def filemap(self, fname: str) -> list[str]:
        return self.filemap_tbl.get(fname, [])


def make_proj(tmp_path: Path, main: str = MAIN_TEX) -> Path:
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    return tmp_path


def mini_rs(
    rules: list[dict],
    taxonomy: list[dict],
    loop_cfg: dict | None = None,
    warnings: list[dict] | None = None,
) -> Ruleset:
    """合成 ruleset: 机械性 verdict 测试用 (stuck/max_rounds 等)。

    ``warnings`` 供 warn 域合成（``warn_*`` 伪类行须配
    ``scope=warnings`` taxon + 同名 ``warnings`` pattern 行）。
    """
    return Ruleset(
        {
            "version": 1,
            "meta": {
                "loop": {
                    "max_rounds": 4,
                    "stuck_sig_repeat": 3,
                    "clean_err_max": 3,
                    "compile_passes": 2,
                    **(loop_cfg or {}),
                }
            },
            "taxonomy": taxonomy,
            "warnings": warnings or [],
            "rules": rules,
        }
    )


# ---- test_fixloop_loop 迁出件：合成 ruleset 语料 + 引擎变体 ----

#: 恒炸 taxonomy——``boom`` taxon 每轮命中 (stuck/dedup/max_rounds 机械钉)。
BOOM_TAXONOMY = [{"id": "boom", "scope": "head", "pattern": "BOOM"}]
BOOM_LOG = "! BOOM every time\n"


def run_tool_rules(n: int) -> list[dict]:
    """boom 类 run_tool 规则 ×n —— 跨轮 apply/dedup 占位派发件。"""
    return [
        {
            "id": f"fix{i}",
            "phase": "loop",
            "order": i,
            "when": {"category": "boom"},
            "action": {"kind": "run_tool", "params": {"argv": ["true"]}},
        }
        for i in range(1, n + 1)
    ]


class MockTectonic(MockEngine):
    name = "tectonic"
    caps = frozenset({"bundle"})

    def __init__(self, script: list, **kw: object) -> None:
        super().__init__(script, **kw)
        self.ctan_fetch = None  # fixloop 应注入 CtanFetcher
        self.filemap_index: dict[str, list[str]] = {}


class SalvageMockEngine(MockEngine):
    """best_effort 感知：兜底轮 (best_effort=True) 放残页 pdf 出来。"""

    def compile(
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 2,
        best_effort: bool = False,
        **_kw: object,
    ) -> MockRes:
        del passes
        if best_effort:
            self.rounds += 1
            return MockRes(
                Path(wdir),
                main,
                {"log": "! Undefined control sequence.\n", "pdf": True},
            )
        return super().compile(wdir, main, passes=1, **_kw)


# ---- 同体别名：各 finding 的历代命名全归 MockRes/MockEngine canonical 对 ----
# ``ScriptedEngine`` 与 tests/xlat/test_e2e_wiring.py:84 的 callable-script 类
# 同名不同形 (swap-trap, idx-176 已记)——新车道请用 ``ScriptEngine``/
# ``MockEngine``；此别名仅为 idx-131 adopters 的名字解析兜底。
ScriptedRes = MockRes
SpecRes = MockRes
ScriptEng = MockEngine
ScriptedEng = MockEngine
ScriptedEngine = MockEngine
ScriptEngine = MockEngine
LoopEngine = MockEngine
