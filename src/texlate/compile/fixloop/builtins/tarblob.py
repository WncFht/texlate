r"""builtins.tarblob — tar 伪装件解包 (builtins.misc C3 再拆叶)。

arXiv e-print 偶发把整包源码以嵌套 tar 随投稿, 外层解包后 tar 以
``.sty``/``.cls`` 名落进工作树 → TeX ``\input`` 读 tar 头成排版文本。
本叶收检测 (``_tar_header_start`` 前 64KB ``ustar`` 窗 + 头校验)、
regular-file 成员补缺 (no-clobber) 与 blob 改名 ``*.tarblob`` 退役的
全族, 单入口 ``extract_tar_blobs``。
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import _safe_rel
from texlate.textutil import _TAR_HEADER_LEN, _tar_header_ok

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


# ════════════════════════════════════════════════════════════════
# tar 伪装件解包：e-print 内嵌 tar 以 .sty/.cls 名落盘 → 抽成员补缺
# ════════════════════════════════════════════════════════════════

#: POSIX ustar 魔数 ``ustar`` 驻留偏移 257 (tar header magic field)。
_TAR_MAGIC_OFF = 257
_TAR_MAGIC = b"ustar"

#: 魔数探测窗——我方 splice/zh 对 ``.sty`` 一律前置 prologue 注入
#: (``\PassOptionsToPackage``/``\providecommand`` 块), tar 魔数被推离 257
#: (0707.0382 实案：注入 ~600B 后 ``ustar`` 落 ~偏移 870, 定点探测漏检);
#: 前 64KB 扫描兼容原生与变异 blob。
_TAR_SCAN_WINDOW = 65536

#: 伪装判定扩展名集——tar blob 只在文本类名下才有害 (二进制件 .eps/.pdf
#: 不查；``.tarblob`` 是本方改名件，重扫须免再命中)。
_TARBLOB_EXTS = frozenset(
    {
        ".tex",
        ".sty",
        ".cls",
        ".clo",
        ".def",
        ".fd",
        ".cfg",
        ".bst",
        ".bib",
        ".ins",
        ".dtx",
        ".ltx",
        ".stytxt",
    }
)


def _tar_header_start(f: Path) -> int | None:
    r"""Tar 头起点探测——前 ``_TAR_SCAN_WINDOW`` 内找 ``ustar``, 回推 257 得头起点。

    None = 非 tar; 0 = 原生 tar; >0 = 被前置注入推位的变异 tar
    (注入件仍以 tar 为主体, 同须退役)。逐候选过 textutil
    ``_tar_header_ok`` 双校验 (name 非 NUL + 魔数+版本域 + 512B 校验和)
    ——免 ``\mustar``/``\mustarh`` 类宏名内 ``ustar`` 字样误中真 .tex
    (2410.17904 ``paper.tex``→missing_file 实案)。多读
    ``_TAR_HEADER_LEN`` 让窗尾命中仍见全头。
    """
    try:
        with f.open("rb") as fh:
            head = fh.read(_TAR_SCAN_WINDOW + _TAR_HEADER_LEN)
    except OSError:
        return None
    p = head.find(_TAR_MAGIC)
    while p != -1:
        hdr = p - _TAR_MAGIC_OFF
        if hdr >= 0 and _tar_header_ok(head, hdr):
            return hdr
        p = head.find(_TAR_MAGIC, p + 1)
    return None


def _safe_member_name(name: str) -> PurePosixPath | None:
    """成员名卫：剥 ``./`` 前缀后拒绝对路径/``..``/空名/含 NUL。"""
    n = name
    while n.startswith("./"):
        n = n[2:]
    return _safe_rel(n)


def _slot_hit(rel: PurePosixPath, expected: Path) -> int:
    r"""成员对期待槽位 ``expected`` 的命中级: 0 无 / 1 stem 兄弟 / 2 basename 精确。

    stem 兄弟限 ``.cls`` 槽位 ← ``.sty`` 成员——2.09 时代 class 本体就以
    .sty 发行, ``\\documentstyle``/compat ``\\documentclass`` 读本名槽位
    (astro-ph/0104007 ``aipproc.cls`` tar 内含 ``aipproc.sty`` 实案);
    反向 (.cls 成员冒写 .sty 槽位) 不开——class 件不是 package 实现。
    """
    if rel.name.lower() == expected.name.lower():
        return 2
    sib = (
        expected.suffix.lower() == ".cls"
        and rel.suffix.lower() == ".sty"
        and rel.stem.lower() == expected.stem.lower()
    )
    return int(sib)


def _slot_payload(f: Path, hdr_start: int, expected: Path) -> bytes | None:
    """二扫 tar 成员找期待槽位 ``expected`` 的补写字节 (basename 精确 > stem 兄弟)。

    独立 BytesIO 重扫——成员字节已在盘内 tar 里，扫序同一遍损坏边界，
    确定性等价。``hit > best_rank`` 让后到的精确件盖过先到的兄弟件。
    """
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415

    best_rank = 0
    payload: bytes | None = None
    try:
        stream = io.BytesIO(f.read_bytes()[hdr_start:])
        with tarfile.open(fileobj=stream) as tf:
            for m in tf:
                if not m.isreg():
                    continue
                rel = _safe_member_name(m.name)
                if rel is None:
                    continue
                hit = _slot_hit(rel, expected)
                if hit <= best_rank:
                    continue
                src = tf.extractfile(m)
                if src is not None:
                    best_rank, payload = hit, src.read()
    except (tarfile.TarError, OSError):
        pass
    return payload


def _extract_members(
    ctx: LoopCtx, f: Path, hdr_start: int, expected: Path | None = None
) -> int:
    r"""抽 tar ``f`` (头起点 ``hdr_start``) 的 regular-file 成员补缺 → 落地数。

    顺序迭代 (非 getmembers 全扫)——变异 tar 内层被 recode 改写可能中段
    损坏, 顺序读让头部完好成员先落地, 遇坏头即收。

    ``expected`` = 伪装件原名槽位 (blob 已先改名让出): 与槽位同名成员
    (任意深度 basename) 自然落地即占槽位; 槽位仍缺则由 ``_slot_payload``
    二扫补写——basename 命中或同 stem ``.sty`` 兄弟件, 让 class/``\\input``
    解析拿到 tar 内真实实现而非落入 missing_file→stub。
    """
    import io  # noqa: PLC0415 — 冷路径：命中伪装件才用，不污染常规启动
    import tarfile  # noqa: PLC0415

    extracted = 0
    try:
        stream = io.BytesIO(f.read_bytes()[hdr_start:])
        with tarfile.open(fileobj=stream) as tf:
            for m in tf:
                if not m.isreg():
                    continue
                rel = _safe_member_name(m.name)
                if rel is None:
                    continue
                dest = f.parent / Path(*rel.parts)
                if dest.exists():
                    continue
                src = tf.extractfile(m)
                if src is None:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read())
                ctx.invalidate(dest)
                extracted += 1
    except (tarfile.TarError, OSError):
        pass
    if expected is not None and not expected.exists():
        payload = _slot_payload(f, hdr_start, expected)
        if payload is not None:
            expected.write_bytes(payload)
            ctx.invalidate(expected)
            extracted += 1
    return extracted


def extract_tar_blobs(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""工作树内 tar 伪装件 → 成员补缺解包 + blob 改名 ``*.tarblob`` 退役。

    arXiv e-print 偶发把整包源码以嵌套 tar 随投稿——外层解包后 tar 以
    ``.sty``/``.cls`` 名落进工作树 (0707.0382 ``AMSbsy.sty``=全 bundle tar、
    astro-ph/0104007 ``aipproc.cls``=aipproc.sty+figs+symposium.tex tar,
    loop2 fixloop 实证): TeX ``\input`` 读 tar 头成排版文本 →
    ``Missing \begin{document}`` 于伪装件第 N 行 (``l.30 AMSfonts.sty^^@``)。

    解包纪律: 仅 regular file 成员 (tarfile.extractfile 逐件读字节自写,
    不依赖平台 filter 语义); 名卫拒 ``..``/绝对/``./`` 残件/NUL;
    **no-clobber**——目标已存在跳过 (真件优先, tar 只补缺); blob 本体
    命中 tar 魔数即改名 ``{name}.tarblob`` 退役 (移出 TeX 解析路径、
    留现场可审计)——tar 归档在 ``.sty``/``.cls`` 名下绝不是合法 TeX,
    0 新成员 (=语料已带全部成员, 0707.0382 实案) 或魔数被前置注入推位
    的变异件也必须退役。**先改名再抽**——blob 让出原名槽位后, 与槽位
    同名或同 stem 的 ``.sty`` 兄弟成员才能补写回 ``{name}`` 本身
    (旧序先抽后改: 槽位被 tar 本体占着, 同名成员永远被 no-clobber
    跳过, 改名后期待文件名彻底缺席 → missing_file)。抽取按头起点切片
    喂 tarfile, 顺序迭代容忍变异件中段损坏 (头段完好成员照补)。
    """
    del eng, payload
    exts = {str(e).lower() for e in (params.get("exts") or _TARBLOB_EXTS)}
    done: list[str] = []
    for f in sorted(ctx.wdir.rglob("*"), key=lambda p: p.as_posix()):
        if not f.is_file() or f.suffix.lower() not in exts:
            continue
        hdr = _tar_header_start(f)
        if hdr is None:
            continue
        blob = f.with_name(f.name + ".tarblob")
        f.replace(blob)
        ctx.invalidate(f)
        extracted = _extract_members(ctx, blob, hdr, expected=f)
        done.append(f"{f.name}({extracted} members)")
    return (bool(done)), f"tar blobs extracted: {', '.join(done)}"
