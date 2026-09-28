"""xelatex 引擎 —— TeX Live 系全工具链通路（``engine.py`` 拆分叶）。

``run_process``/``find_tool`` 走 ``_eng.`` 运行期回查——测试 patch
缝钉在 ``texlate.compile.engine.X`` 模块名上（worker ``_w.`` 同款）。
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from typing import Final

    from texlate.compile.loginfo import LogInfo
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

from texlate.compile.deps import compiled_dependencies
from texlate.compile.loginfo import parse_log
from texlate.compile.sandbox import (
    _apply_sandbox,
    _rc_to_signal,
    _texmfdist,
    child_env,
)
from texlate.texlog import log_text_of
from texlate.textutil import env_raw, safe_is_file
from texlate.textutil.osutil import ENV_TLNET

from ._base import (
    DEFAULT_TIMEOUT,
    CompRes,
    _checked_main,
    _collect_compile_outputs,
    _salvage_driver_fatal,
)
from ._cache import load_search_cache, save_search_cache, tlmgr_search_cache_path

log = logging.getLogger(__name__)

MAX_PASSES = 2

#: 续趟判据（B14 fix#7 rerun-gate）：逐趟 stdout 匹配——命中即 LaTeX 自报
#: 还要一遍。不收裸 ``rerun``（rerunfilecheck 包名行是常态噪音）。
#: qc-impl 扩臂 (fp resolve-pass): ``(citation|reference)...undefined``
#: 与 ``Please (re)run Biber/BibTeX`` 入面——0806.3788 型 bib 内 brace
#: 错吞掉 Rerun 尾标时 citation undefined 是唯一存活签名; biber/bibtex
#: 请求行同理要续趟吸收 (bib 趟由 ``_bib_pass`` 文件态承, 本行只管
#: "再给一趟 tex" 的自适应信号)。
_RERUN_HINT_RX: Final = re.compile(
    r"rerun to get|label\(s\) may have changed|there were undefined references"
    r"|table widths have changed"
    r"|(?:citation|reference)s?\b[^\n]*?undefined"
    r"|please \(re\)run\s+(?:biber|bibtex)",
    re.IGNORECASE,
)

#: ``probe_file`` texmf 树探测 memo 条数上限（B14 fix#3）：fixloop 格均
#: ~10–40 名、跨 cell 名集高重叠，容量远超格均即全覆盖；撞顶整表清——
#: 树态随 install 漂移，老条目残值低。
_PROBE_MEMO_MAX: Final = 4096

#: ``compile(flags=…)`` 拒放面：重键输出落点的 flag 会毁掉 ``{stem}.pdf/.log``
#: 按 outdir 回收的约定——这类请求进 ``CompRes.flags_dropped`` 而非 argv。
_OUTPUT_REKEY_PREFIXES: Final = ("-output-directory", "-aux-directory", "-jobname")

#: xelatex 开 ``\write18`` 的 flag 拼写集——``env`` 降级（OS 容器缺席）时
#: 须从 argv 摘除降入 ``flags_dropped``：无沙箱兜底的 shell-escape 即裸
#: 命令执行面。``sandbox=off`` 是调用方明示退出，不动。
_SHELL_ESCAPE_FLAGS: Final = frozenset(
    {"-shell-escape", "--shell-escape", "-enable-write18", "--enable-write18"}
)

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
_BBL_KEY_RX: Final = re.compile(
    r"\\(?:bibitem(?:\[[^\]]*\])?|entry)\{([^}]*)\}"
)
#: ``\bibdata{name[,name2]}``——bibdata 可解性判 (无 .bib → bibtex 必败,
#: 让位异名收编臂)。
_BIBDATA_RX: Final = re.compile(r"\\bibdata\{([^}]*)\}")


def _has_bbl(bbl: Path) -> bool:
    """同侪 ``.bbl`` 在席判据——空文件视同缺席（无物可失），查不了态按在席。

    在席即永不 clobber：bundled .bbl 是上游跑好的成品（cargo bbl 如
    ``foxtrot-full.bbl`` 无 .bib 可重生），且 biber 败北会自删同侪 bbl
    （``_builtins_bib.bbl_regen`` 实证）——在场即整臂跳过才安全。
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


def _bcf_intact(bcf: Path) -> bool:
    """``.bcf`` 完整性判: 尺寸下限 + 尾窗 ``</bcf:controlfile>`` 尾标。"""
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


def _prepare_main(
    wdir: Path,
    main: str,
    outdir: Path | None,
    *,
    default_subdir: str = "",
    extra_stale: Iterable[str] = (),
) -> tuple[Path, Path, str, Path, Path, Path]:
    """compile() 头段共享件：main 校验 + out 落点解析/mkdir + 陈旧产物清理。

    ``default_subdir`` = ``outdir`` 缺席时 ``cwd`` 下的引擎默认子目录
    （tectonic ``_tect_out``；xelatex 产物落 main 旁、留空）。``extra_stale``
    收相对 ``out`` 的追加清档名，``{stem}`` 占位按 main 词干展开（xelatex
    ``"{stem}.fls"``、tectonic ``"dependencies.mk"``）。返回
    ``(main_path, cwd, stem, out, pdf, log)``——源树目录镜像等引擎私有
    步骤留在调用方。
    """
    main_path = _checked_main(wdir, main)
    cwd = main_path.parent
    stem = main_path.stem
    out = (outdir or (cwd / default_subdir if default_subdir else cwd)).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pdf, log = out / f"{stem}.pdf", out / f"{stem}.log"
    for stale in (pdf, log, *(out / name.format(stem=stem) for name in extra_stale)):
        stale.unlink(missing_ok=True)
    return main_path, cwd, stem, out, pdf, log


def _harvest(  # noqa: PLR0913, PLR0917 — compile() 尾段共享件，参数面即两引擎差异缝
    res: CompRes,
    wdir: Path,
    main: str,
    out: Path,
    pdf: Path,
    log: Path,
    log_text: str,
) -> None:
    """compile() 尾段共享件：log_text/log_path/pdf/ok/workdir/deps 归位。

    ``log_text`` 由调用方早读——各引擎 ``.log``→``LogInfo`` 解析段发散
    （xelatex ``parse_log(log_text or stdout_tail)`` + driver-fatal 打捞 +
    ``log_truncated``；tectonic 空 .log 退 stdout_tail + ``error:`` 签名
    兜底），读盘随解析段留在原地。本函数只归位字段，且须在
    ``_salvage_driver_fatal`` 之后调用：``_driver_fatal`` 的 ``has_pdf``
    门按归位前字段评估（编译时序上恒 False——``res.pdf`` 此刻未落位即
    「呈失败相」，fatal 行打捞不因已出 pdf 被闸掉）。
    """
    res.log_text = log_text
    res.log_path = log if log.exists() else None
    res.pdf = pdf if pdf.exists() else None
    res.pdf_bytes = pdf.stat().st_size if pdf.exists() else 0
    res.ok = not res.timed_out and res.rc is not None and res.rc >= 0
    res.workdir = wdir
    res.deps = compiled_dependencies(wdir, main, out, res.engine)


# ================================================================ xelatex
class XelatexEngine:
    """TeX Live xelatex：M0 开发默认（tlmgr 可修性实测最高，engine-matrix §5）。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr", "updmap", "recorder"})

    def __init__(
        self,
        binary: str | None = None,
        *,
        halt_on_error: bool = True,
        texmfhome: Path | None = None,
        repository: str | None = None,
    ) -> None:
        """binary=None → PATH/常见落点探测；texmfhome=沙箱 usermode 树（冷启动）。

        repository=tlnet 镜像 pin：`tlmgr --usermode install` 与 tlpdb 索引
        拉取共用（env ``TEXLATE_TLNET`` 同效）；None = tlmgr 既有配置
        （mirror.ctan.org round-robin 在部分网络下不稳，bench 侧钉 TUNA）。
        """
        self.binary = binary
        # docs/spec/compile.md 命令行含 -halt-on-error（fixloop 首错语义）；bench 基线跑
        # best-effort（halt_on_error=False，对齐 compile_bench 方法论）。
        self.halt_on_error = halt_on_error
        self.texmfhome = texmfhome
        self.repository = repository or env_raw(ENV_TLNET) or None
        self._search_cache: dict[str, list[str]] | None = None
        self._usertree_inited = False
        #: ``_fontconfig_conf`` memo——``(texmfhome, conf 路径)``。conf 内容
        #: 只吃 texmfhome（``_texmfdist`` 进程级 lru_cache 恒定）；texmfhome
        #: 经 fixloop ``_wire_engine``/worker 接线漂移（None → 实树）即自动
        #: 失效重写，conf 文件被外删（usertree 整清）时 ``is_file`` 复核回写
        #: ——同键每实例只写一回，不再逐次 ``_env`` 重写。
        self._fontconfig_memo: tuple[Path | None, str] | None = None
        #: ``probe_file`` 树探测 memo——键 ``(fname, texmfhome, 宿主
        #: TEXMFHOME)``，值 None=阴性也缓存（缺件重探是真成本）；树态变动
        #: 只经本实例 install/updmap 通路，各落件点统一 ``clear()``。
        self._probe_cache: dict[tuple[str, str, str], str | None] = {}

    def detect(self) -> str | None:
        """Xelatex 二进制探测（ctor 指定优先，否则 PATH/常见落点）。"""
        return self.binary or _eng.find_tool("xelatex")

    def _env(self, extra: dict[str, str] | None) -> dict[str, str]:
        add = dict(extra or {})
        # 单行超长的 legacy 宏转储 (TCI tcilcomm.tex 实测 3MB/行) 会顶穿
        # web2c 默认 buf_size=200000 → `Unable to read an entire line` 硬死。
        # kpathsea cnf 变量可经 env 覆盖, 放宽输入行缓冲即解 (loop1-1706.02464)。
        add.setdefault("buf_size", "8000000")
        # fontspec 裸名查找走 fontconfig——texmf 自带 otf (FontAwesome.otf
        # 等) 未注册必炸 "font X cannot be found"。注入一份把
        # texmf-dist/opentype + usertree 字体注册的 conf（2211.12985 实证：
        # ambient/sandbox 同缺, OSFONTDIR 不吃, FONTCONFIG_FILE 一注即解）。
        fc = self._fontconfig_conf()
        if fc:
            add.setdefault("FONTCONFIG_FILE", fc)
        if self.texmfhome:
            # TEXMFHOME 写冒号链：usertree 居首（可写/优先），ambient
            # TEXMFHOME（缺席时取 kpathsea 默认 ~/texmf）尾随保持可见——
            # 否则宿主 ~/texmf 里的 shim/老包在 fixloop 冷树视角下凭空消失
            # （regress4 假退化根因）。tlmgr/updmap 不认链，走 _usertree_env。
            home_tree = str(self.texmfhome / "home")
            tail = env_raw("TEXMFHOME") or str(Path.home() / "texmf")
            homes = [home_tree] + [e for e in tail.split(":") if e and e != home_tree]
            add.update(
                {
                    "TEXMFHOME": ":".join(homes),
                    "TEXMFVAR": str(self.texmfhome / "var"),
                    "TEXMFCONFIG": str(self.texmfhome / "config"),
                }
            )
        return child_env(add)

    def _fontconfig_conf(self) -> str | None:
        """写一份 fontconfig conf 并返回路径（texmf opentype + usertree 字体注册）。

        ``FONTCONFIG_FILE`` 是整份替换语义——必须 ``<include>`` 系统 conf
        保住宿主机字体面。conf 落 ``usertree/home`` 之下（该目录经
        ``TEXMFHOME`` 链入 ``_bwrap_env_paths`` 挂进沙箱；usertree 根本身
        不在挂载面）；texmfhome 缺席时落 ``~/.cache/texlate/fontconfig/``
        （已列入 ``_bwrap_mounts`` rw）。重写幂等——实例内 memo
        （``_fontconfig_memo``）同 texmfhome 键只写一回：``_env`` 每次
        kpsewhich/tlmgr/updmap spawn 都经本方法，幂等重写此前逐次摊销。
        """
        if (
            self._fontconfig_memo is not None
            and self._fontconfig_memo[0] == self.texmfhome
            and Path(self._fontconfig_memo[1]).is_file()
        ):
            return self._fontconfig_memo[1]
        dist = _texmfdist()
        dirs = []
        if dist:
            dirs.append(str(Path(dist) / "fonts" / "opentype"))
            # truetype 树同注册 (tinos/noto 等 google ttf 家族)——名查找字体
            # 在 truetype 的格此前必炸 fontspec_missing (2609.20064 实证)。
            dirs.append(str(Path(dist) / "fonts" / "truetype"))
        home_ot = (
            self.texmfhome / "home" / "fonts" / "opentype"
            if self.texmfhome
            else Path.home() / "texmf" / "fonts" / "opentype"
        )
        dirs.append(str(home_ot))
        try:
            cdir = (
                self.texmfhome / "home" / "fontconfig"
                if self.texmfhome
                else Path.home() / ".cache" / "texlate" / "fontconfig"
            )
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / "cache").mkdir(parents=True, exist_ok=True)
            conf = cdir / "fonts.conf"
            body = [
                "<?xml version='1.0'?>",
                "<!DOCTYPE fontconfig SYSTEM 'fonts.dtd'>",
                "<fontconfig>",
                '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>',
                *(f"  <dir>{d}</dir>" for d in dirs),
                # texmf opentype 数千枚，首扫几秒级——cachedir 落 usertree 内
                # 随格多次重编译摊销（沙箱 HOME 是 tmpfs，不落此即每次重扫）。
                f"  <cachedir>{cdir / 'cache'}</cachedir>",
                "</fontconfig>",
            ]
            conf.write_text("\n".join(body) + "\n", encoding="utf-8")
        except OSError:
            return None  # 写失败不 memo——下回重试（同旧逐次重写语义）
        self._fontconfig_memo = (self.texmfhome, str(conf))
        return str(conf)

    def _usertree_env(self) -> dict[str, str]:
        """tlmgr/updmap 系 env：TEXMFHOME 退链取首元素。

        tlmgr 把 env 值当字面路径——冒号链会被建成名为 ``texA:`` 的目录
        且 tlpdb 判定全炸（实测）。kpathsea 读侧（compile/probe）才吃链。
        """
        env = self._env(None)
        home = env.get("TEXMFHOME")
        if home and ":" in home:
            env["TEXMFHOME"] = home.split(":", 1)[0]
        return env

    @staticmethod
    def _split_flags(flags: Iterable[str] | None) -> tuple[list[str], list[str]]:
        """engine_flags → (进 argv, 丢弃)。

        ``_OUTPUT_REKEY_PREFIXES`` 系 flag 会重键 pdf/log 落点、毁掉按
        outdir 回收产物的约定 → 拒放进 dropped（kpathsea 单双横线等价，
        ``--output-directory=/x`` 同拒）；两 token 形态
        （``-output-directory /x``）把值 token 一并丢——留在 argv 会被
        xelatex 当第二输入文件处理。其余原样直通。
        """
        applied, dropped = [], []
        flist = list(flags or ())
        i = 0
        while i < len(flist):
            fl = flist[i]
            # kpathsea 长选项单双横线等价——归一成单横线再查重键表，
            # 否则 ``--output-directory=/x`` 绕过拒放面把 pdf/log 落点重键。
            norm = "-" + fl.lstrip("-")
            if norm.startswith(_OUTPUT_REKEY_PREFIXES):
                dropped.append(fl)
                if (
                    "=" not in fl
                    and i + 1 < len(flist)
                    and not flist[i + 1].startswith("-")
                ):
                    dropped.append(flist[i + 1])
                    i += 1
            elif fl not in applied:
                applied.append(fl)
            i += 1
        return applied, dropped

    def _cmd(
        self,
        binary: str,
        out: Path,
        main_name: str,
        *,
        best_effort: bool = False,
        flag_toks: Iterable[str] | None = None,
    ) -> list[str]:
        """构造 xelatex 命令行（docs/spec/compile.md 旗标集 + 预切 engine_flags）。

        ``flag_toks`` 是 ``_split_flags`` 已放行的 token——compile() 喂
        ``res.flags_applied``（过滤记账单点在 compile 头段，此处不复切；
        预切也免了同一 ``flags`` 迭代器被二次消费的空放形）。追加在基线
        旗标之后、``main_name`` 之前——kpathsea 选项 last-wins，规则请求
        （如 minted 的 ``-shell-escape``）可压过 ``-no-shell-escape``。
        """
        cmd = [
            binary,
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-file-line-error",
            "-recorder",
            f"-output-directory={out}",
        ]
        if self.halt_on_error and not best_effort:
            cmd.insert(3, "-halt-on-error")
        for fl in flag_toks or ():
            if fl not in cmd:
                cmd.append(fl)
        cmd.append(main_name)
        return cmd

    def compile(  # noqa: PLR0913 — 签名即 docs/spec/compile.md 规格面；pass 环停趟判据单点平铺
        self,
        wdir: Path,
        main: str,
        *,
        passes: int | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        outdir: Path | None = None,
        sandbox: bool = True,
        env_extra: dict[str, str] | None = None,
        best_effort: bool = False,
        flags: Iterable[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> CompRes:
        """执行 xelatex ≤`passes` 遍；-recorder 产 .fls 供 compiled_dependencies。

        ``passes=None``（缺省）= 自适应门：趟输出出现 rerun 提示族
        （``_RERUN_HINT_RX``）即续跑，上限 ``MAX_PASSES``；显式 int =
        无条件 ≤N 遍。停趟判据：超时/exec 失败（rc=None）/无 pdf 即停
        ——同输入重跑必同炸；错误退出（rc>0 非信号）仅自适应档被 rerun
        提示压过（提示即 LaTeX 自报 .aux 状态已变、pass-2 非同一输入），
        钉死档与提示缺席照旧即停；信号死（负 rc）是外部截杀非确定性败，
        留续趟重试通道。
        """
        res = CompRes(engine=self.name)
        res.flags_applied, res.flags_dropped = self._split_flags(flags)
        binary = self.detect()
        if binary is None:
            res.stdout_tail = "xelatex not found"
            return res
        main_path, cwd, stem, out, pdf, log = _prepare_main(
            wdir, main, outdir, extra_stale=("{stem}.fls",)
        )
        env = self._env(env_extra)
        cmd = self._cmd(
            binary,
            out,
            main_path.name,
            best_effort=best_effort,
            flag_toks=res.flags_applied,
        )
        cmd, res.sandbox_mode = _apply_sandbox(
            cmd,
            root=wdir,
            out=out,
            env=env,
            enabled=sandbox,
            # xelatex 工具链（kpsewhich/mktex*/xdvipdfmx）全本地——断网兜底
            # ``-shell-escape`` flag 穿透场景（fixloop minted 规则可压过
            # -no-shell-escape）的 curl 外联面。
            allow_net=False,
            extra_rw=[self.texmfhome] if self.texmfhome else [],
        )
        if res.sandbox_mode == "env":
            # env 降级 = OS 容器缺席——shell-escape 系 flag 没人兜底，压过
            # -no-shell-escape 即裸 \write18 → 从 argv 摘除降入 dropped。
            esc = [f for f in res.flags_applied if f in _SHELL_ESCAPE_FLAGS]
            if esc:
                res.flags_applied = [
                    f for f in res.flags_applied if f not in _SHELL_ESCAPE_FLAGS
                ]
                res.flags_dropped += esc
                cmd = [t for t in cmd if t not in _SHELL_ESCAPE_FLAGS]
        outputs = []
        eff_passes = MAX_PASSES if passes is None else passes
        per_pass = max(10.0, timeout / max(1, eff_passes))
        # while 非 for-range：bib 采纳后 eff_passes+1 要真吃进一趟
        # （range 界在入环时定死，中途改量不延趟——bibcite→aux→[n] 需 3 趟）。
        p = 0
        while p < eff_passes:
            p += 1
            rc, out_s, sec, to = _eng.run_process(
                cmd, cwd=cwd, env=env, timeout=per_pass, should_cancel=should_cancel
            )
            res.rc = rc
            if (sig := _rc_to_signal(rc, res.sandbox_mode)) is not None:
                res.killed_signal = sig
            res.seconds += sec
            # ``to`` 可携活哨原因 str（``vbox_flood``/``page_flood``）——槽位
            # 短暂带 str 经 ``_collect_compile_outputs`` 归位 sentry_reason。
            res.timed_out = res.timed_out or to  # ty: ignore[invalid-assignment]
            res.passes = p
            outputs.append(out_s)
            # 停趟判据：超时 / exec 失败 / 无 pdf 恒收。确定性错误退出
            # （rc>0 非信号）仅被自适应档（passes=None）的 rerun 提示压过——
            # 提示即 LaTeX 自报还要一趟：.aux 首趟陈态错（footmisc perpage
            # 首趟 \@ctrerr Counter too large 一族）pass-2 自愈，不算同输入
            # 重跑；提示缺席照旧即收。钉死档（passes=N）rc!=0 恒停、不吃提示。
            # 信号死（负 rc / 包裹层 128+N）是外部截杀非定败，留续趟通道。
            hint = _RERUN_HINT_RX.search(out_s) is not None
            # bib 中间趟（lane-bibpass）：趟间产物（.bcf/.aux）此刻最新。
            # qc-impl 扩闸 (fp bibtex_pass_coverage/bbl_backup): 旧 ``p <
            # eff_passes`` 闸把末趟封死——passes=1 的 sealed 格 (fixloop
            # 分类趟/salvage) 永远轮不到 bib; 现放宽为任何趟后都评, 若在
            # 末趟补成则 ``eff_passes = p+1`` 自延一趟让 tex 吸收新 .bbl
            # (钉死档 caller 钉了 N 也在 bib 采纳时破例延一趟——不延则
            # 新 bbl 无人消费)。本趟恒收的死相（超时/exec 败/无 pdf）与
            # 钉死档 rc!=0 不补（补了也吃不到下趟）。采纳即续趟信号；
            # pass2 载 .bbl 把 \bibcite 落 aux，pass3 才渲文内 [n]
            # （PoC 实证 2 趟仍 [?]）。
            if (
                not res.bib_ran
                and not (to or rc is None or not pdf.exists())
                and (rc == 0 or sig is not None or passes is None)
            ):
                res.bib_ran = self._bib_pass(
                    wdir,
                    out,
                    env,
                    stem=stem,
                    sandbox=sandbox,
                    per_pass=per_pass,
                    should_cancel=should_cancel,
                )
                if res.bib_ran and p >= eff_passes:
                    # 末趟才补成 → 自延一趟吸收; 延趟后按剩余预算重劈
                    # per_pass——``timeout/eff_passes`` 本就是总墙钟约束:
                    # 不劈则 timeout=240 的 2 趟起跑 (per_pass=120) 延成
                    # 3 趟可烧 360s，静默超预算。
                    eff_passes = p + 1
                    per_pass = max(
                        10.0, (timeout - res.seconds) / max(1, eff_passes - p)
                    )
            hint = hint or bool(res.bib_ran)
            if (
                to
                or rc is None
                or (rc != 0 and sig is None and not (passes is None and hint))
                or not pdf.exists()
                or (passes is None and not hint)
            ):
                break
        _collect_compile_outputs(res, outputs)
        try:
            log_text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = ""
        res.log = parse_log(log_text or res.stdout_tail, project_root=wdir)
        _salvage_driver_fatal(res.log, res)
        # Guard A (adjudication #10): halt_on_error 下 n_errors>0 ⇒ 编译截在
        # 首错——计数是下界非测量值, log 证不了 errors≤阈值; best_effort
        # (nonstopmode) 跑全程不截。消费端 getattr 容错——tectonic/测试替身
        # 无此字段按不截断处理。
        res.log_truncated = (
            self.halt_on_error and not best_effort and res.log.n_errors > 0
        )
        _harvest(res, wdir, main, out, pdf, log, log_text)
        return res

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
        r"""文件态触发的 bibtex/biber 趟间补跑（lane-bibpass 设计）。

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
            """新产不完整且旧件还在备份 → 回滚 (删本趟残件, 还原旧件)。"""
            if bak is None or not bak.is_file():
                return False
            try:
                bbl.unlink(missing_ok=True)
                bak.rename(bbl)
            except OSError:
                return False
            return True

        def _rollback(bak: Path | None, bbl: Path) -> None:
            """Adopt 失败清算: 有备份回滚, 无备份删本趟残件免毒下趟。"""
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
                # 覆盖度复核: 缺键 → 备份重跑 (fp bibtex_pass_coverage 臂2)
                missing = cite_keys - _bbl_keys(bbl)
                if not missing or not cite_keys:
                    continue
                if not _bibdata_resolvable(text, wdir, out):
                    continue  # 无 .bib 可再生——缺键是空跑, 在席件不碰
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
                        rel, rc, to, out_s,
                    )
                continue
            # bbl 缺席: \bibdata 可解 → bibtex; 不可解 → 异名收编兜底
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
                # 完整产物照采纳, 缺口键数落 note 供账本。
                ran.append(f"bibtex:{rel}" + (f"(missing:{missed})" if missed else ""))
            else:
                bbl.unlink(missing_ok=True)  # 截断/空 bbl——删除免毒下趟
                log.debug(
                    "bibtex %s not adopted rc=%s to=%s: %.200s", rel, rc, to, out_s
                )
        return ran

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> str | None:
        """用 kpsewhich 探测文件可解析路径（texmf 树侧结果进程内 memo）。

        ``cwd`` 对应的 ``.`` 搜索元素拆成 ``Path.is_file`` 直查、不进 memo
        ——wdir 内文件随 fixloop 落件动态出现（vendored 平铺/stub 写件），
        直查让阴性缓存永不遮蔽新件。texmf 树探测按 ``(fname, texmfhome,
        宿主 TEXMFHOME)`` 键进 ``_probe_cache``——树内容变动只发生在本实例
        install/updmap 通路（各落件点统一清缓存）；跨进程同伴装件的陈旧
        阴性顶多让 tlmgr 空转一趟，``_post_install_verify`` 复核链自清。
        """
        if "\x00" in fname:
            return None  # NUL 进 argv 炸 Popen ValueError（log 可控面）
        base = cwd if cwd is not None else Path.cwd()
        if safe_is_file(cand := base / fname):
            return str(cand)
        key = (fname, str(self.texmfhome), env_raw("TEXMFHOME"))
        if key in self._probe_cache:
            return self._probe_cache[key]
        hit = self._probe_tree(fname, base)
        if len(self._probe_cache) >= _PROBE_MEMO_MAX:
            self._probe_cache.clear()
        self._probe_cache[key] = hit
        return hit

    def _probe_tree(self, fname: str, base: Path) -> str | None:
        """``kpsewhich`` 纯树探测（``.`` 元素已由 ``probe_file`` cwd 直查覆盖）。

        子进程 cwd 取 ``base`` 而非进程 cwd——``safe_is_file`` 已直查过
        ``base/fname``, ``.`` 元素在该基上永不另产命中; 进程 cwd 落 wdir
        内时旧写法会让 kpsewhich ``.`` 命中 vendored 自件并毒化 memo
        (seki 15 era 件全 self-hit → vendored_shadow 条件死面实证)。
        ``base`` 不在档（wdir 中途被清）时回落**文件系统根**而非进程
        cwd——进程 cwd 的 ``.`` 命中是 cwd 相关结果，却会按 cwd 无关键
        ``(fname, texmfhome, TEXMFHOME)`` 进 ``_probe_cache`` 毒化后续
        一切 workdir 的探测；根目录下相对 ``fname`` 必 miss，结果天然
        cwd 无关、缓存安全。
        """
        tool = _eng.find_tool("kpsewhich")
        if tool is None:
            return None
        rc, out, _, to = _eng.run_process(
            [tool, fname],
            cwd=base if base.is_dir() else Path(base.anchor or os.sep),
            env=self._env(None),
            timeout=15,
        )
        if to or rc != 0 or not out.strip():
            return None
        return out.strip().splitlines()[0]

    def _search_cache_map(self) -> dict[str, list[str]]:
        """file→pkg 进程内缓存，首次访问时并入落盘缓存（远端仓库知识）。"""
        if self._search_cache is None:
            self._search_cache = load_search_cache()
        return self._search_cache

    def _filemap_index(self, fname: str) -> list[str] | None:
        """texlive.tlpdb 离线索引查询；索引不可用 → None（回退 tlmgr）。

        `tlmgr search --global` 逐查询远端 tlpdb，镜像 round-robin 实测挂出
        假 "no package provides"（fixloop-bench 口径）——同一份仓库知识走
        本地索引既稳又快（~/.texlate/cache/filemap.json 常驻）。
        """
        from texlate.compile.ctan import (  # noqa: PLC0415  # 冷路径惰载
            MIRROR,
            TlpdbIndex,
        )

        try:
            idx = TlpdbIndex.ensure(mirror=self.repository or MIRROR)
        except Exception:  # noqa: BLE001  # 索引拉取失败不阻塞在线通路
            return None
        return idx.query(fname)

    def filemap(self, fname: str) -> list[str]:
        """file→TL 包名索引：tlpdb 离线索引优先，`tlmgr search --file` 兜底。"""
        if "\x00" in fname:
            return []  # NUL 进 tlmgr argv 炸 Popen ValueError（log 可控面）
        cache = self._search_cache_map()
        key = "/" + fname
        if key in cache:
            return cache[key]
        pkgs = self._filemap_index(fname)
        if pkgs is not None:
            cache[key] = pkgs
            return pkgs
        pkgs = self._filemap_tlmgr(fname)
        cache[key] = pkgs  # 进程内 memo 保留阴性（同文件重查不打爆 tlmgr）
        if pkgs:
            save_search_cache(cache)
        return pkgs

    def _filemap_tlmgr(self, fname: str) -> list[str]:
        """`tlmgr search --global --file /fname` 在线通路（索引缺席时兜底）。"""
        tool = _eng.find_tool("tlmgr")
        if tool is None:
            return []
        rc, out, _, to = _eng.run_process(
            [tool, "search", "--global", "--file", "/" + fname],
            cwd=Path.cwd(),
            env=self._usertree_env(),
            timeout=60,
        )
        pkgs: list[str] = []
        if not to and rc == 0:
            for ln in out.splitlines():
                m = re.match(r"^([\w.-]+):$", ln.strip())
                if not m:
                    continue
                pkg = m.group(1)
                # 滤平台特定条目与 tlmgr 自身输出
                if "." in pkg and pkg.split(".")[-1] in (
                    "windows",
                    "win32",
                    "macosx",
                    "linux",
                    "x86_64",
                    "aarch64",
                    "amd64",
                    "i386",
                    "universal",
                ):
                    continue
                if pkg.startswith(("tlmgr", "tlgs")):
                    continue
                pkgs.append(pkg)
        return sorted(set(pkgs))

    @contextlib.contextmanager
    def _install_lock(self) -> Iterator[None]:
        """同 usertree 的 tlmgr install 串行化（跨进程 flock；无 fcntl 则退化为直通）。"""
        base = (
            Path(self.texmfhome) if self.texmfhome else tlmgr_search_cache_path().parent
        )
        try:
            base.mkdir(parents=True, exist_ok=True)
            import fcntl  # noqa: PLC0415  # 平台门: 无 fcntl 则退化为直通
        except (OSError, ImportError):
            yield
            return
        with (base / ".texlate-install.lock").open("a+b") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        """经 kpsewhich 验证 → filemap 查包 → `tlmgr --usermode install` → 复核。"""
        if self.probe_file(fname):
            return True
        pkgs = self.filemap(fname)
        if not pkgs:
            return False
        tool = _eng.find_tool("tlmgr")
        if tool is None:
            return False
        env = self._usertree_env()
        home = env.get("TEXMFHOME")
        with self._install_lock():
            if self.probe_file(fname):
                return True  # 并发同伴已装好
            if (
                home
                and not self._usertree_inited
                and not (Path(home) / "tlpkg" / "texlive.tlpdb").exists()
            ):
                # 冷 TEXMFHOME：先建 usertree tlpdb，否则 --usermode 报
                # "Cannot determine type of tlpdb"（fixloop.py 实测坑）。
                rc_i, _, _, to_i = _eng.run_process(
                    [tool, "--usermode", "init-usertree"],
                    cwd=Path.cwd(),
                    env=env,
                    timeout=60,
                )
                # 失败/超时不钉 True——下次 install 按 tlpdb 缺席重试。
                self._usertree_inited = rc_i == 0 and not to_i
            argv = [tool, "--usermode"]
            if self.repository:
                argv += ["--repository", self.repository]
            argv += ["install", *pkgs]
            rc, _, _, to = _eng.run_process(argv, cwd=Path.cwd(), env=env, timeout=300)
        # tlmgr/init-usertree 动过树态——probe memo 清一遍再进复核链
        self._probe_cache.clear()
        if to or rc != 0:
            return False
        if font_related:
            self.rebuild_fontmaps()
        return self._post_install_verify(fname, pkgs, home)

    def _post_install_verify(
        self, fname: str, pkgs: list[str], home: str | None
    ) -> bool:
        """装后复核: tlmgr rc=0 未落盘走 CTAN overlay → doc-only 搬迁两兜底。

        postaction 类包在 usermode 整体拒装 ("package X is not relocatable",
        axodraw2 实证) —— 文件本身可直放, 走 CTAN archive 按 tlpdb relpath
        铺进 usertree home。mn2e.cls 类连 overlay 都落在 TEXINPUTS 外的
        doc/ 树 (mnras → doc/latex/mnras/LEGACY/) —— basename 恰一命中才
        搬进 tex/latex/。
        """
        if self.probe_file(fname) is not None:
            return True
        if not home:
            return False
        dest = Path(home)
        if self._fetch_into_usertree(fname, pkgs, dest):
            return True
        return self._relocate_doc_only(fname, dest)

    def _relocate_doc_only(self, fname: str, home: Path) -> bool:
        """把 doc/ 树落位的缺件搬进 tex/latex/ + kpsewhich 复核。"""
        base = Path(fname.replace("\\", "/")).name
        if not base or "\x00" in fname:
            return False
        try:
            root = home.resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        doc = root / "doc"
        if not doc.is_dir():
            return False
        hits = [p for p in doc.rglob(base) if p.is_file()]
        if len(hits) != 1:  # 0=没装进来; >1=多副本歧义不猜
            return False
        dest = root / "tex" / "latex" / base
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(hits[0], dest)
        except OSError:
            return False
        if (root / "ls-R").is_file() and (tool := _eng.find_tool("mktexlsr")):
            # 存量 bug（已上报）：缺 ``env`` 必填实参——经真 proc.run_process
            # 路由时到达即 TypeError；测试替身签名宽松未兜住。待修前压诊断。
            _eng.run_process(  # ty: ignore[missing-argument]
                [tool, str(root)], cwd=Path.cwd(), timeout=60
            )
        self._probe_cache.clear()  # 刚把缺件搬进了树——复核前清 memo
        return self.probe_file(fname) is not None

    def _fetch_into_usertree(self, fname: str, pkgs: list[str], dest: Path) -> bool:
        """CTAN ``archive/<pkg>.tar.xz`` → overlay=tree 落 usertree home → 复核。"""
        from texlate.compile.ctan import (  # noqa: PLC0415  # 冷路径惰载
            MIRROR,
            fetch_package,
        )

        for pkg in pkgs:
            # 网络/解包失败 → 试下一候选包 (复核探针是真值), 但不静默——
            # debug 留名供排障 (suppress 吞错曾让装包层故障零线索)
            try:
                fetch_package(
                    pkg,
                    dest,
                    mirror=self.repository or MIRROR,
                    overlay="tree",
                )
            except Exception as e:  # noqa: BLE001  # 候选包逐个试, 单包失败不致命
                log.debug("usertree fetch %s skipped: %r", pkg, e)
            # fetch 可能已部分落件——树态变了，复核前清 memo
            self._probe_cache.clear()
            if self.probe_file(fname) is not None:
                return True
        return False

    def rebuild_fontmaps(self) -> bool:
        """updmap-user 重建字体 map。"""
        tool = _eng.find_tool("updmap-user") or _eng.find_tool("updmap")
        if tool is None:
            return False
        args = [tool] if tool.endswith("updmap-user") else [tool, "--user"]
        rc, _, _, to = _eng.run_process(
            args, cwd=Path.cwd(), env=self._usertree_env(), timeout=120
        )
        self._probe_cache.clear()  # map 重建后字体类探测结果可能变
        return rc == 0 and not to

    def parse_log(self, res: CompRes) -> LogInfo:
        """``texlog.log_text_of`` 同口径：log_text 优先、``.log`` 兜底、stdout_tail 收尾。"""
        info = parse_log(log_text_of(res), project_root=res.workdir)
        _salvage_driver_fatal(info, res)
        return info
