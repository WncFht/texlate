r"""e-print 解包：逐成员路径安全 + mtree 清单（docs/spec/arxiv-source.md）。

逐成员检查（缺一不可）：

- 拒绝：``..``、绝对路径（``/`` 或盘符）、包外 symlink/hardlink、
  device/fifo/socket 等特殊文件、setuid/setgid 位、控制字符与非 UTF-8
  原名（tarfile surrogateescape 代理区——manifest/meta.json 无法编码）。
- 规范化：``./`` 前缀剥离、重复名去重（last-wins）、大小写折叠冲突
  改名（``~cN``）+ 告警。经 kept symlink 祖先写穿的别名成员共享同一
  物理落点——解包末尾按落点对账，先到条目的内容字段改记为盘上实况
  （last-wins 赢家），记录实际变化的记 ``dup_member_overwrite``。
- 成员级 IO 病态（超长名、dangling/自环链接父级等 errno 白名单）降级
  ``reject_io``；成员流中途坏头（tarfile 静默停枚举、尾部留非零块）
  整包 ``UnpackError``——mtree 不能谎报完整。
- 上限：解压总量 ≤512MB、成员 ≤20k、单文件 ≤100MB。
- stub：成员 <100B 或 ``%auto-ignore`` 前缀 → 标 stub（留盘但不进抽样）。

落盘：``extracted/`` 过滤后树 + 每成员 ``(path, size, sha256)`` 记入
``members``，由 :func:`write_manifest` 产出 ``files.txt``/``mtree.txt``。

实现说明：不用 ``tarfile.extractall(filter="data")``——``data`` 过滤器是
「消毒后放行」语义（剥高位权限、改写链接名），与本层「拒绝即拒绝」口径
不符，且不覆盖大小写折叠/重复名/容量上限/mtree，故逐成员自走。
"""

from __future__ import annotations

import errno
import hashlib
import io
import re
import tarfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final

from texlate.arxiv._texutil import TEX_EXT
from texlate.arxiv.sniff import BlobKind, SniffResult

#: 资源上限（docs/spec/arxiv-source.md）
MAX_MEMBERS: Final = 20_000
MAX_FILE_BYTES: Final = 100 * 1024 * 1024
MAX_TOTAL_BYTES: Final = 512 * 1024 * 1024
#: stub 成员阈值：<100B 或 %auto-ignore 前缀（实测 42B 占位混入案例）
STUB_SIZE: Final = 100
STUB_PREFIX: Final = b"%auto-ignore"

_DRIVE_RE: Final = re.compile(r"^[A-Za-z]:")
#: 成员名/链接名控制字符——POSIX 允许落盘但 TSV manifest（files.txt/mtree.txt）
#: 行/列结构会被 \t \n 破坏（phantom 行、列错位），按路径非法一并拒绝
_CTRL_RE: Final = re.compile(r"[\x00-\x1f\x7f]")
#: 代理区码点——tarfile surrogateescape 解码出的非 UTF-8 原名。POSIX 能落盘，
#: 但 mtree.txt/meta.json 写 utf-8 时炸 UnicodeEncodeError（审计实证），按非法拒
_SURROGATE_RE: Final = re.compile(r"[\ud800-\udfff]")
#: 成员级可拒的 IO 错：超长名、dangling/自环 symlink 父级、环链——纯输入构造
#: 可触发，降级为告警跳过；ENOSPC/EIO 等全局错仍上抛整包失败
_MEMBER_ERRNOS: Final = frozenset(
    {errno.ENAMETOOLONG, errno.ELOOP, errno.EEXIST, errno.ENOTDIR}
)


class UnpackError(Exception):
    """解包失败（容量超限 / tar 损坏等无法继续的硬错误）。"""


@dataclass(frozen=True, slots=True)
class MemberEntry:
    """已落盘成员的 mtree 记录。"""

    path: str  # 相对 extracted/ 根的 posix 路径
    size: int
    sha256: str
    kind: str  # "file" | "dir" | "symlink" | "hardlink"
    link_target: str | None = None
    stub: bool = False


@dataclass(slots=True)
class UnpackResult:
    """解包结果：成员清单 + 告警 + 字节统计。"""

    dest: Path
    members: list[MemberEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extracted_bytes: int = 0
    #: ``members`` 路径索引——dup 覆写去重 O(1) 判存（20k 成员上限下
    #: 逐条 list 重建是 O(n²) 扫描）
    member_index: set[str] = field(default_factory=set, repr=False, compare=False)

    @property
    def files(self) -> list[str]:
        """常规文件相对路径（含 hardlink 物化产物），排序稳定。"""
        return sorted(m.path for m in self.members if m.kind in ("file", "hardlink"))

    @property
    def n_files(self) -> int:
        """落盘文件数。"""
        return len(self.files)

    @property
    def tex_files(self) -> int:
        """``.tex``/``.ltx``/``.latex`` 文件数。"""
        return sum(1 for f in self.files if f.lower().endswith(TEX_EXT))

    @property
    def stub_files(self) -> list[str]:
        """Stub 成员路径。"""
        return sorted(m.path for m in self.members if m.stub)


def _safe(s: str) -> str:
    """告警文本中的原始成员名/链接名：代理区转义防 meta.json 编码炸。"""
    return s.encode("utf-8", "backslashreplace").decode("utf-8")


def _norm_member(name: str) -> str | None:
    """成员名规范化 → 相对路径；非法返回 None。

    剥离 ``./`` 与空段；拒绝控制字符（含 NUL）、代理区（非 UTF-8 原名）、
    绝对路径（``/`` 或 ``C:`` 盘符）、``..``。
    """
    if _CTRL_RE.search(name) or _SURROGATE_RE.search(name):
        return None
    if name.startswith("/") or _DRIVE_RE.match(name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts:
        return ""
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _in_tree(rel: str) -> bool:
    """规范化后的相对路径仍在包内。"""
    return bool(rel) and not rel.startswith(("/", "..")) and ".." not in rel.split("/")


def _normpath_posix(p: str) -> str:
    """Posix 手工 normpath：折叠 ``.``/``..``；逃逸出根返回以 ``..`` 开头。"""
    parts: list[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            else:
                parts.append("..")
        else:
            parts.append(seg)
    return "/".join(parts)


def _link_rel(member: tarfile.TarInfo, rel: str) -> str:
    """链接目标的包内相对路径：symlink 相对自身目录，hardlink 相对包根。"""
    if member.issym():
        base = str(PurePosixPath(rel).parent)
        return _normpath_posix(f"{base}/{member.linkname}")
    return _normpath_posix(member.linkname)


def _unique_rename(rel: str, seen: dict[str, str]) -> str:
    """大小写折叠冲突改名：``foo.eps`` → ``foo~c2.eps``。"""
    stem, dot, ext = rel.rpartition(".")
    if not stem:
        stem, suffix = rel, ""
    else:
        suffix = dot + ext
    k = 2
    while f"{stem}~c{k}{suffix}".lower() in seen:
        k += 1
    return f"{stem}~c{k}{suffix}"


def _dir_clash(res: UnpackResult, rel: str, target: Path) -> bool:
    """落点与既有实体路径冲突（同名目录 / 父段是文件）→ 告警并跳过。"""
    if target.is_dir() and not target.is_symlink():
        # tar 里 dir 与同名 file 成员并存（或 casefold 冲突后的 FS 合并产物）
        # ——write_bytes 打目录会抛 IsADirectoryError，降级为告警跳过
        res.warnings.append(f"reject_dir_clash:{rel}")
        return True
    if target.parent.exists() and not target.parent.is_dir():
        # 父路径段是文件（foo 之后来 foo/bar）——mkdir 会抛 FileExistsError
        # 整包流产，按成员级拒绝降级
        res.warnings.append(f"reject_dir_clash:{rel}")
        return True
    return False


def _member_loc(dest_res: Path, rel: str) -> Path:
    """成员的物理落点：父级 resolve（可穿 kept symlink 祖先）+ 末段名。"""
    p = dest_res / rel
    try:
        parent = p.parent.resolve()
    except RuntimeError:
        # 自环/环链 symlink 祖先——无法解析时按未解析路径当独立落点
        parent = p.parent.absolute()
    return parent / p.name


def _reconcile_aliases(res: UnpackResult) -> None:
    """别名落点对账：经 kept symlink 祖先写穿的成员共享同一物理落点。

    mtree 按字面成员路径记账，但盘上别名路径指向同一实体——后到写穿先到
    （last-wins），先到条目的 size/sha256（乃至 kind/link_target）仍是声明时
    旧值，与盘上实况不符。把各落点最末成员的内容字段回填到先到条目；涉入
    symlink 时 kind/link_target 同样以赢家为准（lstat 类型已变）。内容字段
    实际变化的条目记 ``dup_member_overwrite``（声明载荷被后到别名覆盖，
    与字面重名同语义）；dir/dir 等记录本就一致的别名不告警。
    """
    if not res.members:
        return
    if not any(m.kind == "symlink" for m in res.members):
        # 别名只能经 kept symlink 祖先写穿产生（新鲜 dest 契约：调用方总是
        # 解进新建 extracted/）——零 symlink 包跳过整轮 resolve 对账。
        # dirty dest 理论上可借预存 symlink 别名，非契约场景不盖。
        return
    dest_res = res.dest.resolve()
    locs = [_member_loc(dest_res, m.path) for m in res.members]
    winner = {loc: i for i, loc in enumerate(locs)}  # 后写序覆盖——最末为赢家
    for i, (m, loc) in enumerate(zip(res.members, locs, strict=True)):
        if i == winner[loc]:
            continue
        w = res.members[winner[loc]]  # 赢家条目不会被改写，读到的是原始记录
        kind, link = m.kind, m.link_target
        if m.kind == "symlink" or w.kind == "symlink":
            kind, link = w.kind, w.link_target
        new = MemberEntry(
            path=m.path,
            size=w.size,
            sha256=w.sha256,
            kind=kind,
            link_target=link,
            stub=m.stub,
        )
        if new == m:
            continue
        res.members[i] = new
        res.warnings.append(f"dup_member_overwrite:{m.path}")


def _drop_member(res: UnpackResult, rel: str) -> None:
    """覆盖同名成员时摘掉旧 mtree 条目（``members`` 与 ``member_index`` 同步）。"""
    if rel in res.member_index:
        res.members = [mm for mm in res.members if mm.path != rel]
        res.member_index.discard(rel)


def _write_entry(
    res: UnpackResult, rel: str, data: bytes, kind: str, link: str | None = None
) -> bool:
    """写文件 + 记 mtree 成员 + stub 标记；路径与既有实体冲突 → 告警跳过。"""
    target = res.dest / rel
    if _dir_clash(res, rel, target):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        # 后到 file 覆盖同名 symlink：先摘链再写，否则 write_bytes 穿链改目标
        target.unlink()
    target.write_bytes(data)
    _drop_member(res, rel)
    stub = len(data) < STUB_SIZE or data.startswith(STUB_PREFIX)
    res.members.append(
        MemberEntry(
            path=rel,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            kind=kind,
            link_target=link,
            stub=stub,
        )
    )
    res.member_index.add(rel)
    res.extracted_bytes += len(data)
    if stub:
        res.warnings.append(f"stub_member:{rel}")
    return True


class _TarWalker:
    """单 tar 的逐成员解包状态机（seen/告警/统计/hardlink 延迟物化）。"""

    def __init__(self, dest: Path) -> None:
        """初始化状态。"""
        self.res = UnpackResult(dest=dest)
        self.seen: dict[str, str] = {}
        self.hardlinks: list[tuple[str, str]] = []
        self.total = 0

    def run(self, payload: bytes) -> UnpackResult:
        """解整个 tar 流。"""
        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as tf:
                members = tf.getmembers()
                if len(members) > MAX_MEMBERS:
                    msg = f"too_many_members:{len(members)}"
                    raise UnpackError(msg)
                # getmembers 遇坏头静默停枚举（errorlevel=2 也不抛）——
                # offset 停在终止扫描的那一块：全零 = 正常 EOF 标记（其后
                # 残留旧数据尾巴属真实包形态，9702009 实证）；非零 = 无法
                # 解析的头块、其后成员全丢——mtree 不能谎报完整，硬拒
                if payload[tf.offset : tf.offset + 512].strip(b"\x00"):
                    msg = f"corrupt member stream at offset {tf.offset}"
                    raise UnpackError(msg)
                for m in members:
                    self._member(m, tf)
        except tarfile.TarError as e:
            msg = f"not a tar stream: {e}"
            raise UnpackError(msg) from e
        self._finish_links()
        _reconcile_aliases(self.res)
        return self.res

    def _claim(self, rel: str) -> str:
        """大小写折叠/重名检查，返回落盘名（可能改名）。"""
        low = rel.lower()
        if low in self.seen and self.seen[low] != rel:
            new_rel = _unique_rename(rel, self.seen)
            self.res.warnings.append(f"casefold_rename:{rel}->{new_rel}")
            rel = new_rel
            low = rel.lower()
        elif low in self.seen:
            self.res.warnings.append(f"dup_member_overwrite:{rel}")
        self.seen[low] = rel
        return rel

    def _reject_reason(self, m: tarfile.TarInfo, rel: str) -> str | None:
        """常规文件的容量/类型拒绝理由；None = 放行。"""
        if m.size > MAX_FILE_BYTES:
            return f"reject_filesize:{rel}:{m.size}"
        if self.total + m.size > MAX_TOTAL_BYTES:
            return f"reject_totalcap:{rel}"
        return None

    def _member(self, m: tarfile.TarInfo, tf: tarfile.TarFile) -> None:
        """处理单成员：七项安全检查 → 落盘 / 告警。"""
        rel = _norm_member(m.name)
        if rel is None or rel == "":
            if rel is None:
                self.res.warnings.append(f"reject_path:{_safe(m.name)}")
            return
        if m.mode and m.mode & 0o6000:
            self.res.warnings.append(f"reject_setuid:{rel}")
            return
        if m.isdir():
            self._dir_member(rel)
            return
        if m.issym() or m.islnk():
            self._link(m, rel)
            return
        if not m.isreg():
            self.res.warnings.append(f"reject_special:{rel}")
            return
        self._file_member(m, tf, rel)

    def _file_member(self, m: tarfile.TarInfo, tf: tarfile.TarFile, rel: str) -> None:
        """常规文件：容量闸 → 认领名 → 读流落盘。"""
        reject = self._reject_reason(m, rel)
        if reject is not None:
            self.res.warnings.append(reject)
            return
        rel = self._claim(rel)
        self._drop_pending(rel)
        fobj = tf.extractfile(m)
        data = fobj.read() if fobj else b""
        try:
            ok = _write_entry(self.res, rel, data, "file")
        except OSError as e:
            if e.errno not in _MEMBER_ERRNOS:
                raise
            self.res.warnings.append(f"reject_io:{rel}:{e.errno}")
            return
        if ok:
            self.total += len(data)

    def _drop_pending(self, rel: str) -> None:
        """同名后到的非 hardlink 声明压掉未物化的 hardlink 元组（保成员序 last-wins）。"""
        if self.hardlinks:
            self.hardlinks = [h for h in self.hardlinks if h[0] != rel]

    def _dir_member(self, rel: str) -> None:
        """目录成员：注册 seen + mkdir + mtree；重复幂等、casefold 冲突告警跳过。"""
        low = rel.lower()
        prev = self.seen.get(low)
        if prev is not None and prev != rel:
            # 大小写折叠冲突（foo/ 对已见 Foo 成员）——大小写不敏感 FS
            # 上会静默合并目录；子成员路径在 tar 里固定无法 rename，
            # 告警留痕后跳过（audit-2026-09-16 codehealth 补漏）
            self.res.warnings.append(f"casefold_dir:{prev}~{rel}")
            return
        self._drop_pending(rel)
        target = self.res.dest / rel
        if target.is_dir() and not target.is_symlink():
            # 同名目录重复成员幂等；隐式目录（成员父级 mkdir 产生、未登记）
            # 补登记 + mtree
            if prev is None:
                self.seen[low] = rel
                self.res.members.append(
                    MemberEntry(path=rel, size=0, sha256="", kind="dir")
                )
                self.res.member_index.add(rel)
            return
        if target.parent.exists() and not target.parent.is_dir():
            self.res.warnings.append(f"reject_dir_clash:{rel}")
            return
        if target.exists() or target.is_symlink():
            # 同名 file/symlink 已落盘——dir 成员迟到按 clash 拒
            # （与 file-over-dir 对称：先到者保，后到同类冲突告警跳过）
            self.res.warnings.append(f"reject_dir_clash:{rel}")
            return
        self.seen[low] = rel
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            if e.errno not in _MEMBER_ERRNOS:
                raise
            self.seen.pop(low, None)
            self.res.warnings.append(f"reject_io:{rel}:{e.errno}")
            return
        self.res.members.append(MemberEntry(path=rel, size=0, sha256="", kind="dir"))
        self.res.member_index.add(rel)

    def _link(self, m: tarfile.TarInfo, rel: str) -> None:
        ln = m.linkname
        # linkname 先查本体：绝对路径/盘符经 _link_rel 归一化会被折成 in-tree，
        # 只查解析结果会漏掉真实逃逸（symlink_to 用的是原始 linkname）。
        if (
            not ln
            or _CTRL_RE.search(ln)
            or _SURROGATE_RE.search(ln)
            or ln.startswith("/")
            or _DRIVE_RE.match(ln)
        ):
            self.res.warnings.append(f"reject_link:{rel}->{_safe(ln)}")
            return
        target_rel = _link_rel(m, rel)
        if not _in_tree(target_rel):
            self.res.warnings.append(f"reject_link:{rel}->{_safe(m.linkname)}")
            return
        # 与 file 同套 _claim：精确重名 → dup_member_overwrite（last-wins），
        # 大小写折叠 → 改名。此前无条件 _unique_rename 会把精确重名也改成
        # ~cN 幽灵成员并让旧链接残留（审计实证）。
        rel = self._claim(rel)
        self._drop_pending(rel)
        if m.issym():
            target = self.res.dest / rel
            if _dir_clash(self.res, rel, target):
                return
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    target.unlink()
                target.symlink_to(m.linkname)
            except OSError as e:
                if e.errno not in _MEMBER_ERRNOS:
                    raise
                self.res.warnings.append(f"reject_io:{rel}:{e.errno}")
                return
            # 覆盖同名 file 成员时摘掉旧 mtree 条目，
            # 否则 files/mtree 把盘上 symlink 记成 file
            _drop_member(self.res, rel)
            self.res.members.append(
                MemberEntry(
                    path=rel, size=0, sha256="", kind="symlink", link_target=m.linkname
                )
            )
            self.res.member_index.add(rel)
            self.res.warnings.append(f"link_kept:{rel}->{m.linkname}")
        else:
            # hardlink：目标可能靠后出现，延迟物化
            self.hardlinks.append((rel, target_rel))

    def _finish_links(self) -> None:
        """Hardlink 二遍物化：目标已在树上 → 复制实体；缺失 → 记 dangling。"""
        for rel, target_rel in self.hardlinks:
            src = self.res.dest / target_rel
            if not src.is_file() or src.is_symlink():
                self.res.warnings.append(f"hardlink_dangling:{rel}->{target_rel}")
                continue
            try:
                data = src.read_bytes()
            except OSError as e:
                if e.errno not in _MEMBER_ERRNOS:
                    raise
                self.res.warnings.append(f"reject_io:{rel}:{e.errno}")
                continue
            if self.total + len(data) > MAX_TOTAL_BYTES:
                self.res.warnings.append(f"reject_totalcap:{rel}")
                continue
            try:
                ok = _write_entry(self.res, rel, data, "hardlink", target_rel)
            except OSError as e:
                if e.errno not in _MEMBER_ERRNOS:
                    raise
                self.res.warnings.append(f"reject_io:{rel}:{e.errno}")
                continue
            if not ok:
                continue
            self.res.warnings.append(f"hardlink_materialized:{rel}->{target_rel}")
            self.total += len(data)


def unpack_tar(payload: bytes, dest: Path) -> UnpackResult:
    """解已解压的 tar 字节流到 ``dest``（逐成员安全过滤）。"""
    return _TarWalker(dest).run(payload)


def _single_tex_name(stem_hint: str) -> str:
    """单文件 .gz 落盘名：cd 文件名去 ``arXiv-`` 前缀与 ``.gz`` 后缀 + ``.tex``。"""
    name = PurePosixPath(stem_hint).name  # 只取末段，防路径注入
    name = re.sub(r"^arXiv-", "", name)
    name = re.sub(r"\.gz$", "", name)
    name = re.sub(r"\.tex$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^A-Za-z0-9_.+-]", "_", name)
    return (name or "main") + ".tex"


def unpack_single(payload: bytes, dest: Path, *, stem_hint: str) -> UnpackResult:
    """单文件 .gz 流：gunzip 后本体即 .tex，写一个文件。"""
    res = UnpackResult(dest=dest)
    rel = _single_tex_name(stem_hint)
    if len(payload) > MAX_FILE_BYTES:
        msg = f"single_file_too_large:{len(payload)}"
        raise UnpackError(msg)
    dest.mkdir(parents=True, exist_ok=True)
    _write_entry(res, rel, payload, "file")
    return res


def unpack_sniffed(s: SniffResult, dest: Path, *, stem_hint: str) -> UnpackResult:
    """按 :func:`sniff` 结果分流解包。"""
    if s.oversized:
        msg = f"inflated_too_large:{s.inflated_size}"
        raise UnpackError(msg)
    if s.kind is BlobKind.TAR or s.kind is BlobKind.SINGLE:
        if s.payload is None:
            msg = f"missing payload for kind={s.kind}"
            raise UnpackError(msg)
        if s.kind is BlobKind.TAR:
            return unpack_tar(s.payload, dest)
        return unpack_single(s.payload, dest, stem_hint=stem_hint)
    msg = f"cannot unpack kind={s.kind}"
    raise UnpackError(msg)


def write_manifest(res: UnpackResult, out_dir: Path) -> None:
    """写 ``files.txt`` 与 ``mtree.txt``（TSV：path size sha256 kind [-> target][stub]）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "files.txt").write_text(
        "\n".join(res.files) + ("\n" if res.files else ""), encoding="utf-8"
    )
    lines = []
    for m in sorted(res.members, key=lambda m: m.path):
        line = f"{m.path}\t{m.size}\t{m.sha256}\t{m.kind}"
        if m.link_target:
            line += f"\t-> {m.link_target}"
        if m.stub:
            line += "\tstub"
        lines.append(line)
    (out_dir / "mtree.txt").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
    )
