r"""xelatex bib 文件态件 + ``_XelatexBib`` 趟间补跑 mixin（``engine/_xelatex`` 二级缝叶）。

``.bbl``/``.bcf``/``aux`` 文件态判件（完整性尾标/版本 skew/覆盖度/异名
收编资格）与 ``XelatexEngine._bib_pass`` 的宿主臂。``find_tool``/
``run_process`` 走 ``_eng.`` 运行期回查——测试 patch 缝钉在
``texlate.compile.engine.X`` 模块名上。
"""

from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Final

    from texlate.compile.proc import run_process
    from texlate.compile.toolchain import find_tool

    class _EngNS:
        """``_eng`` 静态面——锚位真签名经 staticmethod 别名钉入。

        ``engine/__init__`` 经 seams ``__getattr__`` 惰性回指锚位模块，ty
        仅见 ``object``；借 TYPE_CHECKING 命名空间把 ``_eng.X`` 回查收窄到
        真签名。仅类型面视图——运行期 ``else`` 分支绑定原样，patch 缝
        （``monkeypatch.setattr(engine.X, …)`` → 叶侧 ``_eng.X`` 命中）零漂移。
        """

        find_tool = staticmethod(find_tool)
        run_process = staticmethod(run_process)

    _eng = _EngNS()
else:
    import texlate.compile.engine as _eng

from texlate.compile.sandbox import _apply_sandbox

log = logging.getLogger("texlate.compile.engine._xelatex")

#: ``_bib_pass`` 逐 aux 扫描上限（``out.rglob("*.aux")`` 排序截断）与
#: 单次工具子进程预算顶——bibtex 实测 33ms，顶只在病态 .bib 上兜底。
_BIB_AUX_SCAN_MAX: Final = 8
_BIB_TOOL_TIMEOUT_MAX: Final = 60.0

#: bbl 完整性尾标（尾窗字节内匹配）：classic bibtex 以
#: ``\end{thebibliography}`` 收，biblatex 两后端 datalist 以 ``\endinput``
#: 收（PoC 实测双形）——截断件两标皆缺。截断 bbl 下趟喂 "File ended while
#: scanning" poison，只留完整件（同 ``bbl_regen`` 防御姿态）。
_BBL_TAIL_RX: Final = re.compile(rb"\\end\{thebibliography\}|\\endinput")
_BBL_TAIL_BYTES: Final = 4096

#: ``.bcf`` 完整性门 (qc-impl fp bbl_backup): 尾标 ``</bcf:controlfile>``
#: 缺席即截断件——kill 撞档残留喂 biber 会触发其 "malformed → Deleted"
#: 自毁路径删掉在席好 .bbl (1706.00240 实证), 宁缺不跑。
_BCF_TAIL_RX: Final = re.compile(rb"</bcf:controlfile\s*>")
_BCF_TAIL_BYTES: Final = 8192
_BCF_MIN_BYTES: Final = 200

#: aux 引用记录键面——``\citation{keys}`` (classic) 与
#: ``\abx@aux@cite{<refsection>}{key}`` (biblatex, 首参为段号) 同收。
_AUX_CITE_RX: Final = re.compile(
    r"\\(?:citation|abx@aux@cite(?:\{[^}]*\})?)\{([^}]*)\}"
)
#: bbl 键面——``\bibitem[..]{key}`` (classic) 与 ``\entry{key}{..}``
#: (biblatex) 同收; 覆盖度复核的"已供键"面。
_BBL_KEY_RX: Final = re.compile(r"\\(?:bibitem(?:\[[^\]]*\])?|entry)\{([^}]*)\}")
#: ``\bibdata{name[,name2]}``——bibdata 可解性判 (无 .bib → bibtex 必败，
#: 让位异名收编臂)。
_BIBDATA_RX: Final = re.compile(r"\\bibdata\{([^}]*)\}")


def _has_bbl(bbl: Path) -> bool:
    """同侪 ``.bbl`` 在席判据——空文件视同缺席（无物可失），查不了态按在席。

    在席即永不 clobber：bundled .bbl 是上游跑好的成品（cargo bbl 如
    ``foxtrot-full.bbl`` 无 .bib 可重生），且 biber 败北会自删同侪 bbl
    （``builtins.bib.bbl_regen`` 实证）——在场即整臂跳过才安全。
    """
    try:
        return bbl.is_file() and bbl.stat().st_size > 0
    except OSError:
        return True


def _bbl_complete(bbl: Path) -> bool:
    """``_bib_pass`` 采纳闸：产物尾窗须带完整尾标，缺即截断件。"""
    try:
        size = bbl.stat().st_size
        with bbl.open("rb") as fh:
            fh.seek(max(0, size - _BBL_TAIL_BYTES))
            tail = fh.read()
    except OSError:
        return False
    return _BBL_TAIL_RX.search(tail) is not None


#: ``.bbl`` 头窗 ``% $ biblatex bbl format version X.Y $`` 声明组。
_BBL_VER_RX: Final = re.compile(rb"biblatex bbl format version\s+([\d.]+)")
_BBL_HEAD_BYTES: Final = 2048
#: biblatex.sty 内期待值 ``\def\blx@bblversion{X.Y}``。
_BLX_VER_RX: Final = re.compile(r"\\def\\blx@bblversion\{([\d.]+)\}")
#: ``\blx@bblversion`` 进程内 memo (texmf 路径键)——每格 kpsewhich 已
#: memo, 本层只省 sty 重复读; texmf 树 install 通路在册期间不换版。
_BLX_VER_MEMO: dict[str, str | None] = {}


def _bbl_decl_version(bbl: Path) -> str | None:
    """``.bbl`` 头窗声明的 bbl format 版本; 无声明 (classic bibtex 件) → None。"""
    try:
        head = bbl.read_bytes()[:_BBL_HEAD_BYTES]
    except OSError:
        return None
    m = _BBL_VER_RX.search(head)
    return m.group(1).decode("ascii", "replace") if m else None


def _bbl_version_skewed(bbl: Path, probe: Callable[[str], str | None]) -> bool:
    r"""在席 bbl 声明版 ≠ 装机 biblatex 期待版 (``\blx@bblversion``)。

    随稿 ``.bbl`` 由作者旧 biber 产 (format 3.2), 装机 biblatex 3.21 要
    3.3——版本不符 biblatex 只警告不拒读, 但 ``\\datalist`` 结构失配
    解不成书目 → 原始 name-hash 数据直排成页 (2312.00752 ``un=0,
    uniquepart=base,hash=…`` 全文 dump + 524 overfull 实证, vault 25 格
    同纹)。任一侧读不出 (无 bbl/无 biblatex) → False 保守放行。
    """
    decl = _bbl_decl_version(bbl)
    if decl is None:
        return False
    sty = probe("biblatex.sty")
    if sty is None:
        return False
    if sty not in _BLX_VER_MEMO:
        try:
            text = Path(sty).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        m = _BLX_VER_RX.search(text)
        _BLX_VER_MEMO[sty] = m.group(1) if m else None
    want = _BLX_VER_MEMO[sty]
    return want is not None and decl != want


def _bcf_intact(bcf: Path) -> bool:
    """``.bcf`` 完整性判：尺寸下限 + 尾窗 ``</bcf:controlfile>`` 尾标。"""
    try:
        data = bcf.read_bytes()
    except OSError:
        return False
    if len(data) < _BCF_MIN_BYTES:
        return False
    return _BCF_TAIL_RX.search(data[-_BCF_TAIL_BYTES:]) is not None


def _aux_cite_keys(text: str) -> set[str]:
    r"""Aux 文本 → 引用键集 (``\\citation``/``\\abx@aux@cite`` 双签名)。"""
    keys: set[str] = set()
    for m in _AUX_CITE_RX.finditer(text):
        keys.update(k.strip() for k in m.group(1).split(",") if k.strip())
    return keys


def _bbl_keys(bbl: Path) -> set[str]:
    r"""``.bbl`` 已供键集 (``\\bibitem``/``\\entry`` 双签名); 读败 → 空集。"""
    try:
        text = bbl.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {
        k.strip()
        for m in _BBL_KEY_RX.finditer(text)
        for k in m.group(1).split(",")
        if k.strip()
    }


def _bbl_stray_candidate(bbl: Path) -> bool:
    r"""异名收编闸: ``thebibliography`` env 完整 + ``\\bibitem`` ≥1 (全文扫)。

    与 ``_bbl_complete`` 的尾窗判不同源——BMC 式 bbl 在
    ``\\end{thebibliography}`` 后还拖 ``\\BMCxmlcomment`` XML 注块
    (0812.0841 ``dimer.bbl`` 实证: 尾标在全文 23% 处, 尾窗判假阴),
    收编臂按"书目 env 完整"全文判, 截断件看的是新产尾标不是存量文件。
    """
    try:
        text = bbl.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return (
        "\\begin{thebibliography}" in text
        and "\\end{thebibliography}" in text
        and "\\bibitem" in text
    )


def _bibdata_resolvable(aux_text: str, wdir: Path, out: Path) -> bool:
    r"""``\\bibdata{name,...}`` 指名的 ``<name>.bib`` 是否至少一件可解。

    BIBINPUTS 面 = ``wdir:out`` 前缀 + 全树 rglob 宽档 (嵌套稿 ``dir/x.bib``
    亦算可解——bibtex argv 同效); 全不可解 → False 让位异名收编臂。
    """
    for m in _BIBDATA_RX.finditer(aux_text):
        for name in (n.strip() for n in m.group(1).split(",")):
            if not name:
                continue
            base = name if name.endswith(".bib") else f"{name}.bib"
            if (wdir / base).is_file() or (out / base).is_file():
                return True
            if any(wdir.rglob(Path(base).name)):
                return True
    return False


class _XelatexBib:
    """bibtex/biber 趟间补跑 mixin（实例状态由 ``XelatexEngine.__init__`` 初始化）。"""

    if TYPE_CHECKING:
        # ------------------------------------------------------------ 宿主契约（ty 静态面）
        # ``XelatexEngine.__init__`` 注入的状态；``_XelatexProbe`` 提供的方法。
        texmfhome: Path | None

        def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None: ...

    def _bib_pass(  # noqa: C901, PLR0912, PLR0913, PLR0915 -- compile 上下文面集中透传；两臂各一段顺序闸
        self,
        wdir: Path,
        out: Path,
        env: dict[str, str],
        *,
        stem: str,
        sandbox: bool,
        per_pass: float,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[str]:
        r"""文件态触发的 bibtex/biber 趟间补跑（bibpass 车道设计）。

        上游 arXiv latexmk 在 latex 趟间跑 bib 工具再生 ``.bbl``——本引擎
        此前从不跑，~30% clean 格因此出 ``[?]`` 引用缺。两路择一（互斥由
        biblatex 自身保证：``backend=biber`` 才产 ``.bcf``；
        ``backend=bibtex`` 不产 bcf，走 aux ``\citation``+``\bibdata``）：

        1. ``<stem>.bcf`` 在 out 且完整 (``_bcf_intact`` 尾标+尺寸门——
           截断 .bcf 喂 biber 触发其 malformed→Deleted 自毁路径删在席
           bbl, 1706.00240 实证, 宁缺不跑):
           - ``<stem>.bbl`` 缺席 → ``biber <stem>``;
           - 在席但 aux 引用键未全覆盖 (覆盖度复核) → 备份
             ``.fixloop-bak`` 后重跑, 完整采纳/回滚 (biber 败北自删时
             旧件照还——fp bbl_backup);
        2. 否则逐 aux（``out.rglob`` 排序截 ``_BIB_AUX_SCAN_MAX``）：含
           ``\citation``+``\bibdata``:
           - 同侪 ``.bbl`` 缺席: ``\bibdata`` 可解 → ``bibtex
             <aux-rel-stem>``（latexmk 逐 aux 算法——``\include`` 子件与
             multibib 同吃，PoC 实证 ``bibtex sub/ch1`` 可用）; 不可解
             且全树恰一份完整异名 ``*.bbl`` → 收编为所需 stem (jobname
             错配稿, 0812.0841 ``dimer.bbl``→``BMC_qbio.bbl`` 实证);
           - 在席但覆盖度缺键 → 同备份重跑臂 ("I didn't find a database
             entry" = 覆盖度缺口非错误, out_s 检测落 note)。

        工具 argv 走 ``_apply_sandbox`` 同款包裹（bwrap 下 bibtex/biber
        实测可跑）；``BIBINPUTS``/``BSTINPUTS`` 补 ``wdir``/``out`` 前缀
        覆盖 out≠cwd 场景（env 键本在透传/挂载白名单内）。采纳闸：
        产物须尾标完整（``_bbl_complete``；biber 另须 rc==0——败北会自删
        poison），不完整件是本趟新产出，删除免毒下一趟（备份回滚优先）。
        返回采纳记录 ``["bibtex:<rel-stem>", ...]``——空表即未跑/未采纳，
        调用方不计续趟信号。失败仅记 debug，永不中断 pass 环。
        """
        ran: list[str] = []
        bib_env = dict(env)
        for key in ("BIBINPUTS", "BSTINPUTS"):
            # 末端空位保 kpathsea 默认树；调用方原值居尾不被吃掉。
            bib_env[key] = f"{wdir}:{out}:{bib_env.get(key, '')}"
        budget = min(_BIB_TOOL_TIMEOUT_MAX, per_pass)
        extra_rw = [self.texmfhome] if self.texmfhome else []

        def _run(argv: list[str]) -> tuple[int | None, str, float, bool | str]:
            wrapped, _mode = _apply_sandbox(
                argv,
                root=wdir,
                out=out,
                env=bib_env,
                enabled=sandbox,
                allow_net=False,
                extra_rw=extra_rw,
            )
            return _eng.run_process(
                wrapped,
                cwd=out,
                env=bib_env,
                timeout=budget,
                should_cancel=should_cancel,
            )

        def _backup(bbl: Path) -> Path | None:
            """在席 bbl 快照 ``.fixloop-bak``——重跑败北/自删的回滚件。"""
            try:
                bak = bbl.with_name(bbl.name + ".fixloop-bak")
                bak.write_bytes(bbl.read_bytes())
            except OSError:
                return None
            return bak

        def _restore(bak: Path | None, bbl: Path) -> bool:
            """新产不完整且旧件还在备份 → 回滚 (删本趟残件，还原旧件)。"""
            if bak is None or not bak.is_file():
                return False
            try:
                bbl.unlink(missing_ok=True)
                bak.rename(bbl)
            except OSError:
                return False
            return True

        def _rollback(bak: Path | None, bbl: Path) -> None:
            """Adopt 失败清算：有备份回滚，无备份删本趟残件免毒下趟。"""
            if _restore(bak, bbl):
                return
            if bak is not None:
                bak.unlink(missing_ok=True)
            if not _bbl_complete(bbl):
                bbl.unlink(missing_ok=True)

        bbl_main = out / f"{stem}.bbl"
        bcf_main = out / f"{stem}.bcf"
        if bcf_main.is_file():
            if not _bcf_intact(bcf_main):
                log.debug("biber skipped: %s.bcf truncated/incomplete", stem)
                return ran
            cite_keys: set[str] = set()
            aux_main = out / f"{stem}.aux"
            if aux_main.is_file():
                with contextlib.suppress(OSError):
                    cite_keys = _aux_cite_keys(
                        aux_main.read_text(encoding="utf-8", errors="replace")
                    )
            need = not _has_bbl(bbl_main)
            bak: Path | None = None
            if not need and cite_keys:
                # 在席 bbl 覆盖度复核 (fp bibtex_pass_coverage): aux 键
                # 未全覆盖 → 在席件陈旧/异源——备份后仍跑 biber。
                missing = cite_keys - _bbl_keys(bbl_main)
                if missing:
                    need = True
                    bak = _backup(bbl_main)
                    log.debug(
                        "bbl coverage gap for %s: %d cite key(s) missing",
                        stem,
                        len(missing),
                    )
            if not need and _bbl_version_skewed(bbl_main, self.probe_file):
                # 在席 bbl 版本复核：随稿件由旧 biber 产 → biblatex 期待版
                # 不符 → \datalist 失配原文直排 (name-hash 满页 dump,
                # 2312.00752 实证)。同陈旧件处理：备份后重跑 biber。
                need = True
                bak = _backup(bbl_main)
                log.debug("bbl format skew for %s — rerunning biber", stem)
            if not need:
                return ran  # bundled/覆盖完整 .bbl 在席——不跑 biber
            if (tool := _eng.find_tool("biber")) is None:
                return ran
            rc, out_s, _sec, to = _run([tool, stem])
            if rc == 0 and not to and _bbl_complete(bbl_main):
                ran.append(f"biber:{stem}")
                if bak is not None:
                    bak.unlink(missing_ok=True)
            else:
                _rollback(bak, bbl_main)
                log.debug(
                    "biber %s not adopted rc=%s to=%s: %.200s", stem, rc, to, out_s
                )
            return ran

        if (tool := _eng.find_tool("bibtex")) is None:
            return ran
        for aux in sorted(out.rglob("*.aux"))[:_BIB_AUX_SCAN_MAX]:
            try:
                text = aux.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "\\citation" not in text or "\\bibdata" not in text:
                continue
            bbl = aux.with_suffix(".bbl")
            cite_keys = _aux_cite_keys(text)
            if _has_bbl(bbl):
                # 覆盖度复核：缺键 → 备份重跑 (fp bibtex_pass_coverage 臂 2)
                missing = cite_keys - _bbl_keys(bbl)
                if not missing or not cite_keys:
                    continue
                if not _bibdata_resolvable(text, wdir, out):
                    continue  # 无 .bib 可再生——缺键是空跑，在席件不碰
                bak = _backup(bbl)
                rel = str(aux.relative_to(out).with_suffix(""))
                rc, out_s, _sec, to = _run([tool, rel])
                if _bbl_complete(bbl):
                    ran.append(f"bibtex:{rel}(coverage)")
                    if bak is not None:
                        bak.unlink(missing_ok=True)
                else:
                    _rollback(bak, bbl)
                    log.debug(
                        "bibtex %s coverage-rerun not adopted rc=%s to=%s: %.200s",
                        rel,
                        rc,
                        to,
                        out_s,
                    )
                continue
            # bbl 缺席：\bibdata 可解 → bibtex; 不可解 → 异名收编兜底
            if not _bibdata_resolvable(text, wdir, out):
                strays = [
                    p
                    for p in sorted(set(wdir.rglob("*.bbl")) | set(out.rglob("*.bbl")))
                    if p.resolve() != bbl.resolve()
                    and p.suffix == ".bbl"
                    and _bbl_stray_candidate(p)
                ]
                if len(strays) != 1:
                    continue  # 恰一份才收编——多份无从归因
                stray = strays[0]
                try:
                    bbl.write_bytes(stray.read_bytes())
                except OSError:
                    continue
                ran.append(f"adopt:{stray.name}->{bbl.name}")
                log.debug("adopted stray bbl %s -> %s", stray, bbl)
                continue
            rel = str(aux.relative_to(out).with_suffix(""))
            rc, out_s, _sec, to = _run([tool, rel])
            if _bbl_complete(bbl):
                missed = len(cite_keys - _bbl_keys(bbl)) if cite_keys else 0
                # "I didn't find a database entry" = 覆盖度缺口非错误——
                # 完整产物照采纳，缺口键数落 note 供账本。
                ran.append(f"bibtex:{rel}" + (f"(missing:{missed})" if missed else ""))
            else:
                bbl.unlink(missing_ok=True)  # 截断/空 bbl——删除免毒下趟
                log.debug(
                    "bibtex %s not adopted rc=%s to=%s: %.200s", rel, rc, to, out_s
                )
        return ran
