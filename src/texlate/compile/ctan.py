"""ctan — ``ctan_fetch`` 原语: tlpdb 离线索引 → tlnet 拉包 → cwd 平铺遮蔽 (compile 层共享件, F2 归位)。

原 ``fixloop/ctan.py``——CTAN 拉包/索引是 compile 层共享件
(``probe``/``engine._xelatex``/``pipecore``/``worker`` 同层消费), 上提后
fixloop 向下消费 (旧 ``fixloop.ctan`` 路径 2026-09-20 退场,
全仓直引本模块)。

实证基础 ``docs/research/latex/ctanfetch-probe.md``:
  - tlpdb 正确路径 ``tlpkg/texlive.tlpdb.xz`` (~2.8MB xz → 20.7MB),
    解析出 8148 包 / 138K basename 索引, 构建 0.14s, filemap.json ~5.5MB
  - ``archive/<pkg>.tar.xz`` 单包 2-136KB 秒级; tar 顶层前缀不统一
    (``texmf-dist/`` 或裸 ``tex/``), 落地两策略: 平铺 basename /
    保留 ``tex/`` 树配 ``-Z search-path``
  - cwd 平铺遮蔽 bundle 实测成立 (ctex 2.5.10 遮蔽 2.5.8 → 0 错)
  - **仅限 TeX 输入层文件** (.sty/.cls/.tfm/…); 物理字体 (.pfb/.pk/.vf)
    与 xdvipdfmx 层不在射程 —— 走改写规则兜底
  - tlnet 只发最新版 → version_guard 比对 expl3/LaTeX2e 要求,
    新版过新则跳过 (ctex 2.6.5 vs bundle expl3 2022/07/14 实证)

缓存约定: ``$TEXLATE_CACHE`` > ``data_root()/cache`` (``TEXLATE_DATA_DIR``
> ``~/.texlate``) 下 ``texlive.tlpdb`` 原件 + ``filemap.json`` 索引
(远端仓库知识, 与环境冷热无关)。
"""

from __future__ import annotations

import contextlib
import io
import json
import lzma
import re
import tarfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from texlate.textutil import data_root, env_raw
from texlate.textutil.osutil import ENV_CACHE

__all__ = [
    "CtanFetchError",
    "CtanFetcher",
    "FetchCaps",
    "FetchResult",
    "TlpdbIndex",
    "check_version_compat",
    "ctan_fetch",
    "default_cache_dir",
    "fetch_package",
    "fetch_tlpdb",
]

MIRROR = "https://mirror.ctan.org/systems/texlive/tlnet"
TLPDB_RELPATH = "tlpkg/texlive.tlpdb.xz"  # 探针纠错: 非 tlnet/texlive.tlpdb.gz (404)

# 索引收录扩展名 (探针 §2: 在任务白名单上加 .clo/.vf/.ofm/.ovp ——
# ctex 有 .clo 字号文件, 不索引则无法从缺 .clo 反查包)。
# .tex/.rtx 仅索引不平铺: binhex.tex/epsf.tex/tikzlibrary*.code.tex
# 类缺名可反查真包, 但修复须走 usertree/tlmgr 安装 —— basename 平铺
# 会撞名遮蔽工程自身 .tex。
INDEX_EXTS = {
    ".sty",
    ".cls",
    ".def",
    ".fd",
    ".tfm",
    ".pfb",
    ".enc",
    ".map",
    ".cfg",
    ".clo",
    ".vf",
    ".ofm",
    ".ovp",
    ".tex",
    ".rtx",
}
#: 只从 tlpdb ``runfiles`` 段收录的扩展名: docfiles/srcfiles 的同名
#: .tex 量大 (示例/文档源) 且 kpsewhich 本就跑不到, 收录只喂噪声候选。
_RUNFILES_ONLY_EXTS = {".tex", ".rtx"}
# 允许平铺进 cwd 的扩展名 = TeX 输入层; .pfb/.pk 物理字体对
# tectonic xdvipdfmx 是死路 (探针 §3.4) 不投; .tex/.rtx 只索引不平铺
# (basename 平铺即撞名遮蔽工程源文件)。
OVERLAY_EXTS = INDEX_EXTS - {".pfb", ".tex", ".rtx"}
# tar 内已知顶层前缀 (探针 §2 踩坑: 前缀不统一)
_TAR_PREFIXES = ("texmf-dist/", "texmf/", "tex/")
_TLPDB_FILE_SECTIONS = {"runfiles", "docfiles", "srcfiles"}
#: 单参 date 族 —— 日期即紧跟实参 (``{date}``/``[date]``):
#: ``\NeedsTeXFormat{LaTeX2e}[date]``; ``\IfFormatAtLeastTF|T|F{date}``
#: (nicematrix v7.11c ``\IfFormatAtLeastTF{2026-06-01}`` abort 实证,
#: v7.11a 写 ``{ 2025-06-01 }`` 带空白 —— 允许内部空白);
#: ``\IfExplAtLeastTF|T|F{date}`` (expl3 loader 日期闸, latex.ltx:1177);
#: ``\@ifl@t@r\<cs>{date}`` 原语直用 (texmf 实证 \fmtversion 66 件/
#: \ExplLoaderFileDate 11 件/``\csname ver@<file>\endcsname`` 形)。
_NEEDFMT_RE = re.compile(
    r"(?:\\NeedsTeXFormat\s*\{LaTeX2e\s*\}"
    r"|\\IfFormatAtLeast(?:TF|T|F)"
    r"|\\IfExplAtLeast(?:TF|T|F)"
    r"|\\@ifl@t@r\s*\\csname\s*[^\\\s{}]*\\endcsname"
    r"|\\@ifl@t@r\s*\\[A-Za-z@]+)"
    r"\s*[\{\[]\s*(\d{4})\s*[/.-]\s*(\d{2})\s*[/.-]\s*(\d{2})"
)
#: 双参 date 族 —— 具名包/类/文件闸 ``{name}{date}`` 与
#: loader 日期实参 ``{name}[date]``:
#: ``\@ifpackagelater``/``\@ifclasslater``/``\IfPackageAtLeastTF|T|F``/
#: ``\IfClassAtLeastTF|T|F``/``\IfFileAtLeastTF|T|F{name}{date}`` ——
#: texmf 实证 gate 目标非 expl3 系占多数 (hyperref/csquotes/graphics…),
#: 名槽开 ``[^}]*``; ``\@ifl@ter\@pkgextension|\@clsextension`` 原语形;
#: ``\RequirePackage``/``\usepackage``/``\LoadClass``/``\documentclass``
#: /``*WithOptions`` ``[opts]{names}[date]`` (texmf 实证 408 件,
#: bracket 须日期开头 —— ``[=v2]``/``[\KOMAScriptVersion]`` 兼容钉不命中)。
#: 注意 ``\ProvidesX{name}[date]``/``\ProvidesExplX{name}{date}`` 是包自署
#: 日期非 floor 声明 (expl3 件多走 ``{\ExplFileDate}``/``\GetIdInfo`` 间址),
#: 不入本族 —— 自署件抽取归 builtins.vendored._provides_date 的遮蔽语义。
_PKGLATER_RE = re.compile(
    r"(?:\\@ifpackagelater|\\@ifclasslater"
    r"|\\IfPackageAtLeast(?:TF|T|F)"
    r"|\\IfClassAtLeast(?:TF|T|F)"
    r"|\\IfFileAtLeast(?:TF|T|F)"
    r"|\\@ifl@ter\s*\\@(?:pkg|cls)extension"
    r"|\\RequirePackage|\\RequirePackageWithOptions|\\usepackage"
    r"|\\LoadClass|\\LoadClassWithOptions|\\documentclass)"
    r"\s*(?:\[[^\]]*\]\s*)?\{[^}]*\}\s*[\{\[]"
    r"\s*(\d{4})\s*[/.-]\s*(\d{2})\s*[/.-]\s*(\d{2})"
)

Fetcher = Callable[[str], bytes]  # url → body (测试注入点)


class CtanFetchError(Exception):
    """远端包校验失败（路径穿越成员 / 超限 / 流损坏）——整包拒收。"""


#: 远端拉取/解压安全上限（audit-2026-09-16 H3: tlnet 包按不可信输入处理）。
#: 实证基线: tlpdb.xz ~2.8MB→20.7MB, 单包 tar.xz 2-136KB —— 下列默认值
#: 对合法负载有数量级富余, 只拦失陷镜像的炸弹/穿越。
DEFAULT_DOWNLOAD_CAP: Final = 128 * 1024 * 1024
DEFAULT_INFLATED_CAP: Final = 512 * 1024 * 1024
DEFAULT_MEMBER_CAP: Final = 64 * 1024 * 1024
DEFAULT_TOTAL_CAP: Final = 512 * 1024 * 1024
DEFAULT_MEMBERS_CAP: Final = 20_000


@dataclass(frozen=True, slots=True)
class FetchCaps:
    """远端包下载/解压/落盘上限；默认值对 tlnet 合法负载数量级富余。"""

    max_download: int = DEFAULT_DOWNLOAD_CAP  # 单响应体字节
    max_inflated: int = DEFAULT_INFLATED_CAP  # xz 解压产物字节
    max_members: int = DEFAULT_MEMBERS_CAP  # tar 成员数
    max_member_bytes: int = DEFAULT_MEMBER_CAP  # 单成员解压后字节
    max_total_bytes: int = DEFAULT_TOTAL_CAP  # 单包落盘总量


#: 缺省上限单例（frozen+slots 不可变，跨调用共享安全）。
DEFAULT_CAPS: Final = FetchCaps()


def default_cache_dir() -> Path:
    """``$TEXLATE_CACHE`` > ``data_root()/cache`` (``TEXLATE_DATA_DIR`` > ``~/.texlate``)。"""
    raw = env_raw(ENV_CACHE)
    return Path(raw).expanduser() if raw else data_root() / "cache"


def _http_get(url: str, *, cap: int = DEFAULT_DOWNLOAD_CAP) -> bytes:
    """流式 GET + 下载体上限；超 cap 抛 CtanFetchError（防失陷镜像炸弹）。"""
    import httpx  # noqa: PLC0415  # 延迟加载: 纯索引路径不依赖网络栈

    from texlate.compile.toolchain import _read_capped  # noqa: PLC0415  # 同上网段惰载

    with httpx.stream("GET", url, timeout=60.0, follow_redirects=True) as resp:
        resp.raise_for_status()
        return _read_capped(
            resp,
            cap,
            on_over=lambda cap: CtanFetchError(f"download exceeds {cap} bytes: {url}"),
        )


def _fetch_capped(url: str, fetcher: Fetcher | None, cap: int) -> bytes:
    """拉取并对注入 fetcher 的返回值同样套下载上限。"""
    raw = fetcher(url) if fetcher else _http_get(url, cap=cap)
    if len(raw) > cap:
        msg = f"download exceeds {cap} bytes: {url}"
        raise CtanFetchError(msg)
    return raw


def _decompress_xz(raw: bytes, cap: int) -> bytes:
    """有上限的 xz 解压；超 cap / 截断 / 损坏 → CtanFetchError。"""
    dec = lzma.LZMADecompressor()
    try:
        out = dec.decompress(raw, max_length=cap + 1)
    except lzma.LZMAError as e:
        msg = f"corrupt xz stream: {e}"
        raise CtanFetchError(msg) from e
    if len(out) > cap:
        msg = f"xz inflated exceeds {cap} bytes"
        raise CtanFetchError(msg)
    if not dec.eof:
        msg = "truncated xz stream"
        raise CtanFetchError(msg)
    return out


_MEMBER_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _norm_member_name(name: str) -> str | None:
    """Tar 成员名 → 包内相对 posix 路径；非法形态返回 None。

    拒绝：NUL、反斜杠（Windows 语义下是分隔符）、绝对路径、盘符、
    任意位置的 ``..`` 段（中段 ``a/../x`` 与前缀 ``../x`` 同罪）。
    """
    if "\x00" in name or "\\" in name:
        return None
    if name.startswith("/") or _MEMBER_DRIVE_RE.match(name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


class TlpdbIndex:
    """file basename → [TL 包] 离线索引 (texlive.tlpdb 解析产物)。"""

    def __init__(
        self, table: dict[str, list[str]], overrides: dict[str, Any] | None = None
    ) -> None:
        """table=basename→[pkg]; overrides 手工映射 (null=已知噪声)。"""
        self.table = table
        self.overrides = overrides or {}

    @classmethod
    def from_tlpdb(cls, path: Path) -> TlpdbIndex:
        """解析 texlive.tlpdb 文本建索引 (tlpdb_index.py 探针移植)。

        块格式: ``name <pkg>`` + ``runfiles/docfiles/srcfiles`` 缩进清单,
        剥 ``RELOC/`` 前缀取 basename。
        """
        table: dict[str, list[str]] = {}
        pkg: str | None = None
        section: str | None = None
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("name "):
                    pkg = line.split(None, 1)[1].strip()
                    section = None
                    continue
                if pkg is None:
                    continue
                if line.startswith(" "):
                    if section is None:
                        continue
                    relpath = line.strip().split(" ", 1)[0]
                    relpath = relpath.removeprefix("RELOC/")
                    base = relpath.rsplit("/", 1)[-1]
                    stem, dot, ext = base.rpartition(".")
                    if not (stem and dot):
                        continue
                    lext = f".{ext.lower()}"
                    if lext not in INDEX_EXTS or (
                        lext in _RUNFILES_ONLY_EXTS and section != "runfiles"
                    ):
                        continue
                    lst = table.setdefault(base, [])
                    if pkg not in lst:
                        lst.append(pkg)
                    continue
                if not line.strip():
                    continue
                key = line.split(None, 1)[0]
                section = key if key in _TLPDB_FILE_SECTIONS else None
        return cls(table)

    @classmethod
    def load(cls, cache_dir: Path | None = None) -> TlpdbIndex:
        """读缓存 ``filemap.json``; 不存在 → FileNotFoundError (走 ensure)。"""
        p = (cache_dir or default_cache_dir()) / "filemap.json"
        return cls(json.loads(p.read_text(encoding="utf-8")))

    def save(self, cache_dir: Path | None = None) -> Path:
        """写 ``filemap.json`` (sort_keys 稳定 + tmp→rename 原子落盘); 返回路径。"""
        d = cache_dir or default_cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        p = d / "filemap.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.table, ensure_ascii=False, sort_keys=True))
        tmp.replace(p)  # 原子换名: 并发读只能见到完整的一代
        return p

    @classmethod
    def ensure(
        cls,
        cache_dir: Path | None = None,
        *,
        mirror: str = MIRROR,
        fetcher: Fetcher | None = None,
        caps: FetchCaps = DEFAULT_CAPS,
    ) -> TlpdbIndex:
        """有缓存读缓存; 否则拉 tlpdb.xz → 解析 → 存 filemap.json。"""
        try:
            return cls.load(cache_dir)
        except (OSError, json.JSONDecodeError):
            pass
        d = cache_dir or default_cache_dir()
        tlpdb_path = fetch_tlpdb(mirror, d, fetcher=fetcher, caps=caps)
        idx = cls.from_tlpdb(tlpdb_path)
        idx.save(d)
        return idx

    def query(self, basename: str) -> list[str]:
        """Basename → 候选包名; overrides 显式 null = 已知噪声 → []。"""
        if basename in self.overrides:
            v = self.overrides[basename]
            return [v] if isinstance(v, str) else []
        hits = self.table.get(basename, [])
        stem = basename.rsplit(".", 1)[0]
        # 消歧启发: 包名==stem 的排最前 (hyperxmp.sty→hyperxmp);
        # 406 个多包 basename (探针 §2) 其余保持 tlpdb 序
        return sorted(hits, key=lambda p: (p != stem, p))

    def suggest(self, stem: str, limit: int = 5) -> list[str]:
        """索引查不到时的 advisory 候选: 包名前缀匹配。"""
        all_pkgs = {x for pkgs in self.table.values() for x in pkgs}
        return sorted(p for p in all_pkgs if p.startswith(stem))[:limit]


@dataclass(slots=True)
class FetchResult:
    """ctan_fetch 返回: ok / 落盘文件 / advisory (索引未命中或版本过新)。"""

    ok: bool
    fname: str
    pkg: str | None = None
    files: list[str] = field(default_factory=list)
    note: str = ""
    advisory: str | None = None


def fetch_tlpdb(
    mirror: str,
    dest_dir: Path,
    *,
    fetcher: Fetcher | None = None,
    caps: FetchCaps = DEFAULT_CAPS,
) -> Path:
    """``tlpkg/texlive.tlpdb.xz`` → 解压 ``texlive.tlpdb`` 落 dest_dir。

    tmp→os.replace 原子落盘: 并发 ``ensure`` 的 ``from_tlpdb`` 流式读
    只能见到完整的一代 (fixloop-bench 冷启动实测撞过半写文件 →
    索引缺条目 → 假 "no package provides")。
    """
    raw = _fetch_capped(f"{mirror}/{TLPDB_RELPATH}", fetcher, caps.max_download)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "texlive.tlpdb"
    tmp = out.with_suffix(".tlpdb.tmp")
    tmp.write_bytes(_decompress_xz(raw, caps.max_inflated))
    tmp.replace(out)
    return out


def _overlay_members(
    tf: tarfile.TarFile, dest: Path, *, overlay: str, caps: FetchCaps
) -> list[str]:
    """解包 tar 成员到 dest; 返回落盘相对路径表。

    overlay="flat": 只取 OVERLAY_EXTS 的 basename 平铺 (cwd 遮蔽 bundle)
    overlay="tree": 剥 texmf-dist/tex 前缀后按 relpath 落 (配 -Z search-path)

    不用 ``extractall(filter="data")``——「消毒后放行」与本层「拒绝即拒收」
    口径不符，且成员数/单成员/总量上限需逐成员自走（同 unpack.py 取舍）。
    任何成员名过不了 :func:`_norm_member_name`（穿越/abs/盘符/反斜杠/NUL）
    或触碰上限 → CtanFetchError 整包拒收 + 撤回本轮已落盘文件。
    """
    members = tf.getmembers()
    if len(members) > caps.max_members:
        msg = f"too_many_members:{len(members)}"
        raise CtanFetchError(msg)
    landed: list[str] = []
    total = 0
    try:
        for m in members:
            if not m.isfile():
                continue
            rel = _member_relpath(m.name, overlay)
            if rel is None:
                continue
            _check_member_caps(m, total, caps)
            src = tf.extractfile(m)
            if src is None:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            data = src.read()
            target.write_bytes(data)
            total += len(data)
            landed.append(rel)
    except CtanFetchError:
        # 拒收即零残留：撤回本轮已落盘文件（空目录壳无妨）
        for rel in landed:
            with contextlib.suppress(OSError):
                (dest / rel).unlink()
        raise
    return landed


def _member_relpath(raw_name: str, overlay: str) -> str | None:
    """成员名 → 落地相对路径；非法名抛 CtanFetchError，非目标成员返回 None。"""
    name = _norm_member_name(raw_name)
    if name is None:
        msg = f"unsafe member name: {raw_name!r}"
        raise CtanFetchError(msg)
    for pre in _TAR_PREFIXES:
        if name.startswith(pre):
            name = name[len(pre) :]
            break
    if overlay == "flat":
        if Path(name).suffix.lower() not in OVERLAY_EXTS:
            return None
        return Path(name).name  # basename 平铺
    return name or None


def _check_member_caps(m: tarfile.TarInfo, total: int, caps: FetchCaps) -> None:
    """单成员/总量上限检查；超限抛 CtanFetchError。"""
    if m.size > caps.max_member_bytes:
        msg = f"member too large: {m.name!r}:{m.size}"
        raise CtanFetchError(msg)
    if total + m.size > caps.max_total_bytes:
        msg = f"extract total exceeds {caps.max_total_bytes} bytes"
        raise CtanFetchError(msg)


def fetch_package(  # noqa: PLR0913  # mirror/overlay/fetcher/caps 注入面即签名
    pkg: str,
    dest_dir: Path,
    *,
    mirror: str = MIRROR,
    overlay: str = "flat",
    fetcher: Fetcher | None = None,
    caps: FetchCaps = DEFAULT_CAPS,
) -> list[str]:
    """``archive/<pkg>.tar.xz`` → 解包投放; 返回落盘文件相对路径表。"""
    raw = _fetch_capped(f"{mirror}/archive/{pkg}.tar.xz", fetcher, caps.max_download)
    payload = _decompress_xz(raw, caps.max_inflated)
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as tf:
            return _overlay_members(tf, dest_dir, overlay=overlay, caps=caps)
    except tarfile.TarError as e:
        msg = f"not a tar stream: {e}"
        raise CtanFetchError(msg) from e


def check_version_compat(files: list[Path], epoch: str) -> tuple[bool, str | None]:
    r"""Tlnet 最新版对 bundle 快照的 expl3/LaTeX2e 要求是否过新 (docs/spec/compile.md §6.5)。

    epoch 形如 ``"2022-07-14"`` (tectonic bundle 快照年代)。
    任一落盘文件声明的 format/包版本 floor —— ``\NeedsTeXFormat`` /
    ``\IfFormatAtLeastT|F|TF`` / ``\IfExplAtLeastT|F|TF`` / ``\@ifl@t@r`` /
    ``\@ifpackagelater`` / ``\@ifclasslater`` / ``\If{Package,Class,File}AtLeastT|F|TF`` /
    ``\@ifl@ter`` / loader 日期实参 (``\RequirePackage{x}[date]`` 系) ——
    取 max 晚于 epoch → (False, 说明)。
    """
    ey, em, ed = (int(x) for x in epoch.split("-"))
    req: tuple[int, int, int] | None = None
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat in (_NEEDFMT_RE, _PKGLATER_RE):
            for m in pat.finditer(text):
                d = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if req is None or d > req:
                    req = d
    if req is not None and req > (ey, em, ed):
        return (
            False,
            f"requires LaTeX2e/expl3 >= {'-'.join(f'{x:02d}' for x in req)} > bundle epoch {epoch}",
        )
    return True, None


def _overlay_gate(fname: str) -> str | None:
    """后缀不在平铺层 → advisory 文本; 可平铺 → None。

    .tex/.rtx 已在索引 (可反查真包) 但平铺即撞名遮蔽工程源;
    物理字体 (.pfb/.pk) 对 xdvipdfmx 是死路 —— 两类分述。
    """
    ext = Path(fname).suffix.lower()
    if ext in OVERLAY_EXTS:
        return None
    if ext in _RUNFILES_ONLY_EXTS:
        return f"{ext} 只索引不平铺 (撞名遮蔽风险); 修复走 usertree/tlmgr 通路"
    return f"{ext} 不在 TeX 输入层 (物理字体/xdvipdfmx 域须改写规则)"


def ctan_fetch(  # noqa: PLR0913  # mirror/overlay/epoch/fetcher/caps 注入面即签名
    fname: str,
    wdir: Path,
    index: TlpdbIndex,
    *,
    mirror: str = MIRROR,
    overlay: str = "flat",
    epoch: str | None = None,
    fetcher: Fetcher | None = None,
    caps: FetchCaps = DEFAULT_CAPS,
) -> FetchResult:
    """``file→包索引→tlnet 拉取→cwd 平铺遮蔽`` 全链 (docs/spec/compile.md §6.5)。

    - 索引查不到 → advisory 附候选包名 (suggest)
    - epoch 给定且新版要求过新 → 撤回已投文件, 试下一候选包
    - 仅限平铺层: 后缀不在 OVERLAY_EXTS 的文件不会落盘
      (.tex/.rtx 可索引反查但不可平铺 —— basename 撞名遮蔽工程源)
    """
    stem = fname.rsplit(".", 1)[0]
    if note := _overlay_gate(fname):
        return FetchResult(ok=False, fname=fname, advisory=note)
    pkgs = index.query(fname)
    if not pkgs:
        sug = index.suggest(stem)
        hint = f"; 候选: {', '.join(sug)}" if sug else ""
        return FetchResult(
            ok=False, fname=fname, advisory=f"no TL package ships {fname}{hint}"
        )
    last_note = ""
    for pkg in pkgs:
        try:
            landed = fetch_package(
                pkg, wdir, mirror=mirror, overlay=overlay, fetcher=fetcher, caps=caps
            )
        except Exception as e:  # noqa: BLE001  # 网络/解包失败 → 试下一候选包
            last_note = f"fetch {pkg}: {type(e).__name__}: {e}"
            continue
        if overlay == "flat" and fname not in landed:
            # 包里没有目标文件 (索引按 basename 命中但整包未含?) —— 撤回
            for rel in landed:
                with contextlib.suppress(OSError):
                    (wdir / rel).unlink()
            last_note = f"{pkg} fetched but {fname} not inside"
            continue
        if epoch:
            ok_ver, why = check_version_compat([wdir / rel for rel in landed], epoch)
            if not ok_ver:
                for rel in landed:
                    with contextlib.suppress(OSError):
                        (wdir / rel).unlink()
                last_note = f"{pkg} {why}"
                continue
        return FetchResult(
            ok=True,
            fname=fname,
            pkg=pkg,
            files=landed,
            note=f"{pkg} -> {len(landed)} files",
        )
    return FetchResult(
        ok=False, fname=fname, advisory=f"all candidates failed: {last_note}"
    )


class CtanFetcher:
    """``TectonicEngine(ctan_fetch=...)`` 注入适配器: ``(fname) -> 落点路径 | None``。

    tlpdb 索引惰性构建 —— 首个真缺文件的 ctan_fetch 调用才拉 ~2.8MB
    texlive.tlpdb (clean 工程零网络开销)。``overrides``/``epoch`` 来自
    rules/ ``filemap:`` 段, 由 fixloop 启动时接线。
    """

    def __init__(  # noqa: PLR0913  # 注入面即签名 (index/cache/overrides/epoch/mirror/fetcher/caps)
        self,
        wdir: Path,
        *,
        index: TlpdbIndex | None = None,
        cache_dir: Path | None = None,
        overrides: dict[str, Any] | None = None,
        epoch: str | None = None,
        mirror: str = MIRROR,
        fetcher: Fetcher | None = None,
        caps: FetchCaps | None = None,
    ) -> None:
        """接线配置入存 (零 IO; 索引在 index/__call__ 首访时惰性建)。"""
        self.wdir = Path(wdir)
        self.cache_dir = cache_dir
        self.overrides = dict(overrides or {})
        self.epoch = epoch
        self.mirror = mirror
        self.fetcher = fetcher
        self.caps = caps or FetchCaps()
        # overrides 合并收敛到注入时点一次: 注入索引可能是跨 fetcher 共享
        # 对象 (fixloop_bench 单例), 原地 update 会让后写污染前写。
        self._index = self._merged(index) if index is not None else None
        self.last_note: str = ""

    def _merged(self, idx: TlpdbIndex) -> TlpdbIndex:
        """``idx`` + self.overrides 的合成视图 —— table 共享, overrides 并入新对象。"""
        if not self.overrides:
            return idx
        return TlpdbIndex(idx.table, {**idx.overrides, **self.overrides})

    @property
    def index(self) -> TlpdbIndex:
        """首访构建/装载索引 (潜在网络 IO); 之后进程内缓存。

        注入的 ``index=`` 同样套 ``overrides`` —— 调用方 (fixloop_bench)
        常注入共享索引, overrides 只走惰性建分支会被静默丢掉。合并发生
        在注入/ensure 时点一次, 本属性与 peek_index 只读不改。
        """
        if self._index is None:
            self._index = self._merged(
                TlpdbIndex.ensure(
                    self.cache_dir,
                    mirror=self.mirror,
                    fetcher=self.fetcher,
                    caps=self.caps,
                )
            )
        return self._index

    def peek_index(self) -> TlpdbIndex | None:
        """已构建才返回索引, 不触发拉取 (advisory 提示用, 见 actions._apply_install_file)。"""
        return self._index

    def __call__(self, fname: str) -> str | None:
        """``(fname) -> 落点 | None`` —— TectonicEngine.ctan_fetch 契约。"""
        res = ctan_fetch(
            fname,
            self.wdir,
            self.index,
            mirror=self.mirror,
            epoch=self.epoch,
            fetcher=self.fetcher,
            caps=self.caps,
        )
        self.last_note = res.advisory or res.note
        return str(self.wdir / fname) if res.ok else None
