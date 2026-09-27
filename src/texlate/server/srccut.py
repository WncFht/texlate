"""copy-latex 服务端纯件：选区 seqs → 原始 ``.tex`` 切片。

``POST /api/task/{id}/latex`` 的核（copy-latex 实现文档 §后端改动）：
请求闸 + 每块三级回落切片 + sent 档 anchor 裁剪 + 连续 run 原文回收 +
壳边扩展 + 界标拼接，全部同步纯逻辑——文件 IO 由路由叶
``asyncio.to_thread`` 卸载（``routers/reader.py`` 同款分工）。

坐标系钉死（cl-seq-map / cl-span-extract 实证）：

- ``byte_start``/``byte_end`` 列名谎称——实为 ``decode_tex`` 后 str 的
  **字符偏移**（``Mouth.i`` 语义）；对 raw bytes 切在非 ASCII 文件必错
  （实测 367/400 行分叉）。
- 权威坐标 = ``base/`` 归一化树；``src.tar`` 原件经 ``decode_tex`` 后仅当
  normalize 未改写该文件时同形——tar 臂切片必须过校验头闸（``main.tex``
  被注入 ~1.5KB 头时 span 全漂，不匹配即弃臂）。
- 三级皆败 → ``dual.json`` ``chunks[seq].en`` + ``ph`` 反掩码重构
  （``approx:true`` 透出——重构体缺注释/原始空白，前端 toast 须标）。
"""

from __future__ import annotations

import difflib
import json
import re
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from texlate.textutil import PH_RX, decode_tex
from texlate.xlat.batch import sentence_ends

#: 请求面硬帽（实现文档 §后端改动 + §风险 9）
SEQS_MAX = 300
ANCHOR_MAX = 400
#: 输出 UTF-8 字节帽——超界截尾 + ``truncated:true``
OUT_CAP = 256 << 10
#: tar 臂校验头最小归一化长——首个达标 literal 段做针
_TAR_HEAD_MIN = 8
#: anchor 定位置信闸：最长匹配块 < ``len(anchor_norm)`` × 0.6 → 该侧退 whole
_ANCHOR_MIN_CONF = 0.6
#: 归一化 anchor 最短有效长——过短定位全是噪声
_ANCHOR_MIN_LEN = 4
#: ph 反掩码递归轮帽（cl-span-extract 同款）
_UNMASK_ROUNDS = 100
#: 壳边回扫上限（字符）——``\section{…}\label{…}`` 恒在数百字符内
_EDGE_MAX = 512
#: 空白行=段落界——壳边扩展不跨界抓料
_EDGE_BLANK = re.compile(r"(?:\n[ \t]*){2,}")
#: env 开合 token——壳尾配平扫描用
_ENV_RX = re.compile(r"\\(begin|end)\{([^}]+)\}")
#: 壳头带入 env 时壳尾追 ``\end`` 的前探上限（字符）——大表/图体可至数十 K
_ENV_TAIL_MAX = 64 << 10


class SrcCutError(Exception):
    """HTTP 语义错误（status + detail + code）——路由叶映 ``_ApiError``。"""

    def __init__(self, status: int, detail: str, code: str) -> None:
        """三要素全收（body 形状与 ``_json_error`` 同）。"""
        self.status = status
        self.detail = detail
        self.code = code
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class LatexRequest:
    """``POST /latex`` 请求体决议结果（``parse_request`` 产物）。"""

    seqs: tuple[int, ...]
    head: str
    tail: str
    mode: str  # "sent"|"whole"
    gaps: bool


def _anchor_field(body: dict[str, Any], name: str) -> str:
    """``head``/``tail`` 入参闸：非 str → 400；超 ``ANCHOR_MAX`` 钳断不拒。"""
    val = body.get(name)
    if val is None:
        return ""
    if not isinstance(val, str):
        raise SrcCutError(400, f"{name}: str ≤{ANCHOR_MAX}", "bad_request")
    return val[:ANCHOR_MAX]


def parse_request(body: dict[str, Any]) -> LatexRequest:
    """请求体 → ``LatexRequest``；非法输入 → ``SrcCutError(400)``。

    ``seqs`` 非空 ≤300、元素非负 int（bool 拒收）、去重保序；
    ``mode`` 严格 ``sent|whole``（缺省 sent）；``gaps`` 严格 bool（缺省 true）；
    ``head``/``tail`` 非 str 拒收、超帽钳断。
    """
    raw = body.get("seqs")
    if not isinstance(raw, list) or not raw or len(raw) > SEQS_MAX:
        raise SrcCutError(400, f"seqs: int 数组（1..{SEQS_MAX}）", "bad_request")
    seqs: list[int] = []
    seen: set[int] = set()
    for v in raw:
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise SrcCutError(400, "seqs: 元素须为非负 int", "bad_request")
        if v not in seen:
            seen.add(v)
            seqs.append(v)
    mode = body.get("mode", "sent")
    if mode not in ("sent", "whole"):
        raise SrcCutError(400, 'mode ∈ "sent"|"whole"', "bad_request")
    gaps = body.get("gaps", True)
    if not isinstance(gaps, bool):
        raise SrcCutError(400, "gaps: bool", "bad_request")
    return LatexRequest(
        seqs=tuple(seqs),
        head=_anchor_field(body, "head"),
        tail=_anchor_field(body, "tail"),
        mode=str(mode),
        gaps=gaps,
    )


# ------------------------------------------------------------------ 路径/成员


_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _norm_rel(name: str) -> str | None:
    """``src_file``/成员名 → posix 相对路径；``..``/绝对/控字/空 → ``None``。

    ``arxiv.unpack._norm_member`` 同口径本地件（私件不跨包引用）：剥 ``./``
    与空段、拒绝对路径/盘符/``..``/控制字符。
    """
    if not name or _CTRL_RE.search(name):
        return None
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


class _BlobSrc:
    """``src_tar`` 登记 blob 的成员读取面：tar(r:*) → zip → 裸文本 三形态。

    arxiv 链恒 ``src.tar``（tar.* 系）；upload_tex 链登记 ``upload/{name}``
    可能是 zip/tar/裸文本任一——探测按内容不按扩展名。成员名索引惰性
    （首个 ``member`` 调用才扫目录）。
    """

    def __init__(self, path: Path) -> None:
        """钉 blob 路径；开包推迟到首次查询。"""
        self._path = path
        self._tf: tarfile.TarFile | None = None
        self._zf: zipfile.ZipFile | None = None
        self._raw: bytes | None = None
        self._names: dict[str, Any] = {}
        self._indexed = False

    def _open(self) -> None:
        """三形态探测：tarfile 判魔数不吃扩展名；zip 次之；末位按裸文本。"""
        try:
            # TarFile 生命周期与 self 同寿（成员按需 extractfile 惰性读）——
            # 不开 context manager：with 会在函数返回时即关包
            self._tf = tarfile.open(self._path, mode="r:*")  # noqa: SIM115
        except (OSError, tarfile.TarError):
            self._tf = None
        else:
            return
        try:
            # 同上——ZipFile 持有供惰性 namelist 读
            self._zf = zipfile.ZipFile(self._path)
        except (OSError, zipfile.BadZipFile):
            self._zf = None
        else:
            return
        try:
            self._raw = self._path.read_bytes()
        except OSError:
            self._raw = None

    def member(self, want: str) -> bytes | None:
        """归一化成员名 ``want`` 命中 → 字节；未命中/坏包 → ``None``。"""
        if not self._indexed:
            self._open()
            self._indexed = True
        if self._tf is not None:
            return self._member_tar(want)
        if self._zf is not None:
            return self._member_zip(want)
        if self._raw is not None and PurePosixPath(want).name == self._path.name:
            # 裸文本 blob（upload_tex 单文件直存）——按 basename 对靶
            return self._raw
        return None

    def _member_tar(self, want: str) -> bytes | None:
        """Tar 臂成员读（名索引惰性建——``./`` 前缀与重复名 last-wins 不收）。"""
        tf = self._tf
        if tf is None:
            return None
        if not self._names:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                rel = _norm_rel(m.name)
                if rel:
                    self._names.setdefault(rel, m)
        m = self._names.get(want)
        if m is None:
            return None
        try:
            f = tf.extractfile(m)
        except (KeyError, OSError, tarfile.TarError):
            return None
        if f is None:
            return None
        try:
            return f.read()
        except OSError:
            return None

    def _member_zip(self, want: str) -> bytes | None:
        """Zip 臂成员读（名归一化同 tar 臂）。"""
        zf = self._zf
        if zf is None:
            return None
        if not self._names:
            for n in zf.namelist():
                rel = _norm_rel(n)
                if rel:
                    self._names.setdefault(rel, n)
        name = self._names.get(want)
        if name is None:
            return None
        try:
            return zf.read(name)
        except (KeyError, OSError, zipfile.BadZipFile):
            return None


# ------------------------------------------------------------------ 归一化面


def _norm_cmp(s: str) -> str:
    """校验头用粗归一：全空白折叠成单空格 + strip。"""
    return re.sub(r"\s+", " ", s).strip()


def _head_ok(frag: str, src_text: str) -> bool:
    r"""Tar 臂校验头闸：``src_text`` 首个达标 literal 段须是切片归一化前缀。

    ``src_text``（surface 渲染形）按 ``[[TYPE_n]]`` token 切段，取首个归一化
    ≥``_TAR_HEAD_MIN`` 字符的 literal 段做针——normalize 注入头/改写
    ``\input`` 会让 tar 原件坐标漂移，漂到别处的 ``text[s:e]`` 切片头对不上
    ``src_text`` 头即弃臂（approx 兜底近乎精确）。找不到达标段视为不可验证，
    同样弃臂（保守方向——错切片比近似重构更糟）。
    """
    hay = _norm_cmp(frag)
    for piece in PH_RX.split(src_text):
        needle = _norm_cmp(piece)
        if len(needle) >= _TAR_HEAD_MIN:
            return hay.startswith(needle)
    return False


def _unmask(text: str, ph: dict[str, str]) -> str:
    """``[[TYPE_n]]`` → ph 体递归展开 ≤``_UNMASK_ROUNDS`` 轮（体内可再嵌 token）。"""
    for _ in range(_UNMASK_ROUNDS):
        new = PH_RX.sub(lambda m: ph.get(m.group(0), m.group(0)), text)
        if new == text:
            return new
        text = new
    return text


def _dual_map(dual_path: Path) -> dict[int, dict[str, Any]]:
    """``dual.json`` → ``{seq: chunk 行}``；缺席/坏 JSON/非表 → ``{}``。"""
    try:
        data: Any = json.loads(dual_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    chunks = data.get("chunks") if isinstance(data, dict) else None
    out: dict[int, dict[str, Any]] = {}
    if isinstance(chunks, list):
        for c in chunks:
            if isinstance(c, dict) and isinstance(c.get("seq"), int):
                out[int(c["seq"])] = c
    return out


# ------------------------------------------------------------------ anchor 臂

#: 渲染文本 → LaTeX 对照面的字符归一（智能引号/撇号/破折号/NBSP）
_ANCHOR_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        " ": " ",
    }
)


def _norm_anchor(s: str) -> str:
    """Anchor 归一：引号归一 + 空白折叠 + strip（spec §后端 4 对照面）。"""
    return re.sub(r"\s+", " ", s.translate(_ANCHOR_MAP)).strip()


def _norm_mapped(s: str) -> tuple[str, list[int]]:
    """归一化串 + ``pos[i]`` = 归一化第 i 字符的原文偏移（末位追加 ``len(s)``）。

    与 ``_norm_anchor`` 同规则（引号归一 + ws 折叠 + 去前导空白），逐字符
    记原文坐标供 difflib 命中映回 raw 偏移。
    """
    out: list[str] = []
    pos: list[int] = []
    prev_ws = False
    for i, c in enumerate(s.translate(_ANCHOR_MAP)):
        if c.isspace():
            if prev_ws:
                continue
            prev_ws = True
            out.append(" ")
            pos.append(i)
            continue
        prev_ws = False
        out.append(c)
        pos.append(i)
    if out and out[0] == " ":
        out.pop(0)
        pos.pop(0)
    pos.append(len(s))
    return "".join(out), pos


def _anchor_span(piece: str, anchor: str) -> tuple[int, int] | None:
    """Anchor 归一化 → 切片内 difflib 定位 ``(raw_lo, raw_hi)``；不足 → ``None``。

    最长匹配块外推 anchor 起/终点到归一化坐标，再经 ``_norm_mapped``
    位置表映回原文偏移（cl-arb-sel anchor 臂同款外推）。最长块 <
    ``len(anchor_norm) × _ANCHOR_MIN_CONF`` 判失配——**退 whole 不报错**
    （spec §后端 4：置信不足即降级档，是正确行为非失败）。
    """
    na = _norm_anchor(anchor)
    if len(na) < _ANCHOR_MIN_LEN:
        return None
    np_, pos = _norm_mapped(piece)
    if not np_:
        return None
    sm = difflib.SequenceMatcher(None, np_, na, autojunk=False)
    best = max(sm.get_matching_blocks(), key=lambda b: b.size)
    if best.size < _ANCHOR_MIN_CONF * len(na):
        return None
    lo_n = max(0, min(best.a - best.b, len(np_)))
    hi_n = max(0, min(best.a - best.b + len(na), len(np_)))
    return pos[lo_n], pos[hi_n]


def _snap_lo(piece: str, cut: int) -> int:
    """``cut`` 所在句的句首：``sentence_ends`` 界 ≤cut 最右者 + 后随空白跳过。"""
    lo = 0
    for b in sentence_ends(piece):
        if b <= cut:
            lo = b
        else:
            break
    while lo < len(piece) and piece[lo] in " \t\n":
        lo += 1
    return lo


def _snap_hi(piece: str, cut: int) -> int:
    """``cut`` 所在句的句终：``sentence_ends`` 界 ≥cut 最左者（无界 → 文末）。"""
    for b in sentence_ends(piece):
        if b >= cut:
            return b
    return len(piece)


# ------------------------------------------------------------------ 切片主链


@dataclass(slots=True)
class _Piece:
    """单块切片产物 + run 合并/壳边扩展所需的同源坐标。"""

    seq: int
    src_file: str
    text: str
    approx: bool
    #: 同源文本标识（``base:file``/``tar:file``/``""``=approx）——同 key 且
    #: seq 相邻才并 run（跨 arm 坐标不互通、approx 无文件坐标）
    src_key: str = ""
    span_start: int = 0
    span_end: int = 0
    #: sent 档实裁侧——置位端拼接期跳过壳边扩展（裁掉的料不能被捞回）
    clip_lo: bool = False
    clip_hi: bool = False


def _decode_file(path: Path) -> str | None:
    """``path.read_bytes`` → ``decode_tex``；IO 败 → ``None``。"""
    try:
        return decode_tex(path.read_bytes())
    except OSError:
        return None


class _Cutter:
    """单次 ``cut_latex`` 调用的解析上下文：源文本缓存 + 切片/拼接件。"""

    def __init__(self, task_dir: Path, src_tar: Path | None, dual_path: Path) -> None:
        """钉产物路径；dual 表与 blob 索引惰性。"""
        self._base_root = (task_dir / "base").resolve()
        self._blob = _BlobSrc(src_tar) if src_tar is not None else None
        self._dual = _dual_map(dual_path)
        self._texts: dict[str, tuple[str | None, str]] = {}

    def resolve(self, src_file: str) -> tuple[str | None, str]:
        """``src_file`` → ``(decode_tex 文本, arm)``；``arm ∈ {base,tar,""}``。"""
        if src_file in self._texts:
            return self._texts[src_file]
        out: tuple[str | None, str] = (None, "")
        rel = _norm_rel(src_file)
        if rel is not None:
            cand = (self._base_root / rel).resolve()
            if cand.is_relative_to(self._base_root) and cand.is_file():
                # base/ 是权威坐标系——切片不校验（spans 本就按它产出）
                text = _decode_file(cand)
                if text is not None:
                    out = (text, "base")
            elif self._blob is not None:
                raw = self._blob.member(rel)
                if raw is not None:
                    out = (decode_tex(raw), "tar")
        self._texts[src_file] = out
        return out

    def slice(self, row: dict[str, Any]) -> _Piece | None:
        """单块三级回落：base 直切 → tar+校验头 → dual approx → ``None``。"""
        seq = int(row["seq"])
        src_file = str(row["src_file"])
        s, e = int(row["byte_start"]), int(row["byte_end"])
        text, arm = self.resolve(src_file)
        if text is not None and 0 <= s <= e <= len(text):
            frag = text[s:e]
            if arm == "base" or _head_ok(frag, str(row["src_text"])):
                return _Piece(
                    seq=seq,
                    src_file=src_file,
                    text=frag,
                    approx=False,
                    src_key=f"{arm}:{src_file}",
                    span_start=s,
                    span_end=e,
                )
        d = self._dual.get(seq)
        if d is None:
            return None
        en = d.get("en")
        if not isinstance(en, str) or not en:
            return None
        ph = d.get("ph")
        ph_map = {str(k): str(v) for k, v in ph.items()} if isinstance(ph, dict) else {}
        return _Piece(
            seq=seq,
            src_file=src_file,
            text=_unmask(en, ph_map),
            approx=True,
        )

    def edge_lo(self, src_file: str, start: int) -> int:
        r"""``start`` 前最后一个空白行界的右端（壳头界）；无界 → ``start``。

        span 只圈可译正文——``\section{`` 壳头与随行注释/``\label`` 落在
        span 前，回扫 ``_EDGE_MAX`` 内最近空白行界之后即壳起点。
        """
        text, _arm = self.resolve(src_file)
        if text is None:
            return start
        ms = list(_EDGE_BLANK.finditer(text, max(0, start - _EDGE_MAX), start))
        return ms[-1].end() if ms else start

    def edge_hi(self, src_file: str, end: int, opened: list[str] | None = None) -> int:
        r"""``end`` 后第一个空白行界的左端（壳尾界）；无界 → ``end``。

        ``}\label{…}`` 壳尾在 span 后、空白行前——第一个空白行界之左即壳终点。
        ``opened`` 非空 = 壳头/正文已含未闭合 ``\begin{env}``——尾继续吃到
        配对 ``\end``（``_ENV_TAIL_MAX`` 内）；吃不到按原界交付。
        空 opened 时区域出现无配对 ``\end`` 的孤儿 ``\begin{env}`` → 截在
        其前（不带半张表/图进切片）。
        """
        text, _arm = self.resolve(src_file)
        if text is None:
            return end
        m = _EDGE_BLANK.search(text, end, min(len(text), end + _EDGE_MAX))
        hi = m.start() if m else end
        if opened:
            need = list(opened)
            far = min(len(text), end + _ENV_TAIL_MAX)
            for mm in _ENV_RX.finditer(text, end, far):
                if mm.group(1) == "begin":
                    need.append(mm.group(2))
                elif need and mm.group(2) == need[-1]:
                    need.pop()
                    if not need:
                        hi = max(hi, mm.end())
                        break
            return hi
        stack: list[tuple[str, int]] = []
        for mm in _ENV_RX.finditer(text, end, hi):
            if mm.group(1) == "begin":
                stack.append((mm.group(2), mm.start()))
            elif stack and stack[-1][0] == mm.group(2):
                stack.pop()
        return stack[0][1] if stack else hi


def _sent_clips(
    rows: list[dict[str, Any]], pieces: list[_Piece | None], req: LatexRequest
) -> tuple[dict[int, tuple[int, int]], set[int], set[int]]:
    """Sent 档边界块裁剪位 ``{row_i: (lo, hi)}`` + 实裁侧集 ``(lo_cut, hi_cut)``。

    anchor 属「请求 seq 边界块」：行缺失（seqs 含无行 seq）时错块裁剪
    比不裁更糟，故按 ``rows[0].seq == min(seqs)`` / ``rows[-1] == max``
    对齐后才裁。定位失配/置信不足 → 不进表（该侧自然退 whole）。
    ``lo_cut``/``hi_cut`` 记哪侧真裁过——拼接期对应侧跳过壳边扩展
    （否则裁掉的头/尾会被 ``edge_lo``/``edge_hi`` 重新捞回）。
    """
    clips: dict[int, tuple[int, int]] = {}
    lo_cut: set[int] = set()
    hi_cut: set[int] = set()
    first = pieces[0]
    if req.head and first is not None and int(rows[0]["seq"]) == min(req.seqs):
        span = _anchor_span(first.text, req.head)
        if span is not None:
            clips[0] = (_snap_lo(first.text, span[0]), len(first.text))
            lo_cut.add(0)
    li = len(rows) - 1
    last = pieces[li]
    if req.tail and last is not None and int(rows[li]["seq"]) == max(req.seqs):
        span = _anchor_span(last.text, req.tail)
        if span is not None:
            clips[li] = (clips.get(li, (0, 0))[0], _snap_hi(last.text, span[1]))
            hi_cut.add(li)
    return clips, lo_cut, hi_cut


def _apply_sent_clips(
    rows: list[dict[str, Any]], pieces: list[_Piece | None], req: LatexRequest
) -> bool:
    """Sent 档裁剪应用：回写 ``piece.text`` + span 坐标 + 实裁侧旗标 → 是否裁过。

    span 同步保 ``text == text[span_start:span_end]`` 不变量——拼接期 verbatim
    run 切片依赖该坐标；``clip_lo``/``clip_hi`` 旗标供 ``_join_pieces`` 跳过
    对应侧壳边扩展。
    """
    if req.mode != "sent":
        return False
    clipped = False
    clips, lo_cut, hi_cut = _sent_clips(rows, pieces, req)
    for i, (lo, hi) in clips.items():
        p = pieces[i]
        if p is not None and lo < hi:
            s = p.span_start + lo
            p.span_end = p.span_start + hi
            p.span_start = s
            p.text = p.text[lo:hi]
            clipped = True
            p.clip_lo = i in lo_cut
            p.clip_hi = i in hi_cut
    return clipped


def _open_envs(text: str, lo: int, hi: int) -> list[str]:
    r"""``text[lo:hi]`` 内未闭合的 ``\begin{env}`` 名栈（顶在尾）。

    同名顶匹才 pop——``\begin{a}\begin{b}\end{a}`` 保守视为全未闭。
    """
    stack: list[str] = []
    for mm in _ENV_RX.finditer(text, lo, hi):
        if mm.group(1) == "begin":
            stack.append(mm.group(2))
        elif stack and stack[-1] == mm.group(2):
            stack.pop()
    return stack


def _run_hi(cutter: _Cutter, text: str, src_file: str, lo: int, piece: _Piece) -> int:
    r"""Run 尾界：sent 实裁侧取 span；否则空白行界 + env 配平。

    ``document`` 帧 env 不追 ``\end``——壳头偶带 ``\begin{document}``
    会把全文件尾段拉进小选区切片。
    """
    if piece.clip_hi:
        return piece.span_end
    opened = _open_envs(text, lo, piece.span_end)
    if "document" in opened:
        opened = []
    return cutter.edge_hi(src_file, piece.span_end, opened)


def _join_pieces(
    cutter: _Cutter,
    rows: list[dict[str, Any]],
    pieces: list[_Piece | None],
    req: LatexRequest,
) -> tuple[str, list[str]]:
    r"""切片行集 → ``(latex, files)``：连续同源 run 发 verbatim 源区间 + 壳边扩展。

    ``gaps`` 开时同 ``src_key`` + seq 相邻的连续块并作一个 run，整段发
    ``text[lo:hi]`` 原文——间区恒为非 chunk 料（表格/公式/图体/注释），
    一体回收不设大小帽（``OUT_CAP`` 为总闸）；``lo``/``hi`` 各外扩到
    最近空白行界（``edge_lo``/``edge_hi``），``\section{`` 壳头与
    ``}\label`` 壳尾随之入切；壳头带入的 env 未闭合时 ``edge_hi``
    追配对 ``\end`` 配平。被 sent clip 裁过的端不扩，直接取裁剪后
    span 坐标。run 长 1（``gaps`` 关或邻块断裂）等价「逐块 + 壳边
    扩展」。approx 块无文件坐标发 ``piece.text``，未解析块按 ``%``
    占位注释落位；跨 ``src_file`` 恒插 ``% ── file: {src_file} ──``
    注释界标（LaTeX 安全，防异文件切片静默串接）。
    """
    out: list[str] = []
    files_seen: list[str] = []
    i = 0
    while i < len(rows):
        piece = pieces[i]
        src_file = str(rows[i]["src_file"])
        if i > 0 and src_file != str(rows[i - 1]["src_file"]):
            # 跨文件界标（LaTeX 注释形——不粘进语义，防异文件静默串接）
            out.append(f"% ── file: {src_file} ──")
        if piece is None:
            out.append(f"% [seq {rows[i]['seq']}: source unavailable]")
            i += 1
            continue
        if src_file not in files_seen:
            files_seen.append(src_file)
        if not piece.src_key:
            # approx 重构体无文件坐标——不能进 run 也不能壳边扩展
            out.append(piece.text)
            i += 1
            continue
        j = i
        if req.gaps:
            while (
                j + 1 < len(rows)
                and pieces[j + 1] is not None
                and pieces[j + 1].src_key == piece.src_key
                and str(rows[j + 1]["src_file"]) == src_file
                and int(rows[j + 1]["seq"]) == int(rows[j]["seq"]) + 1
                and pieces[j].span_end <= int(rows[j + 1]["byte_start"])
            ):
                j += 1
        text, _arm = cutter.resolve(src_file)
        if text is None:
            out.append(piece.text)
        else:
            lo = (
                pieces[i].span_start
                if pieces[i].clip_lo
                else cutter.edge_lo(src_file, pieces[i].span_start)
            )
            hi = _run_hi(cutter, text, src_file, lo, pieces[j])
            out.append(text[lo:hi])
        i = j + 1
    return "\n\n".join(out), files_seen


def cut_latex(
    *,
    task_dir: Path,
    src_tar: Path | None,
    dual_path: Path,
    rows: list[dict[str, Any]],
    req: LatexRequest,
) -> dict[str, Any]:
    r"""行集 → ``{latex,chunks,files,mode_used,approx?,truncated?}``。

    每块三级回落：``base/{src_file}`` 字符切片 → ``src.tar`` 成员切片 +
    校验头 → ``dual.json`` ``en+ph`` 反掩码（``approx``）。全块皆败 →
    ``SrcCutError(422)``；单块失败按 ``%`` 注释占位（不拖垮其余切片）。
    """
    if not rows:
        raise SrcCutError(422, "源全不可得：seqs 无命中 chunk", "no_source")
    cutter = _Cutter(task_dir, src_tar, dual_path)
    pieces = [cutter.slice(row) for row in rows]
    resolved = sum(1 for p in pieces if p is not None)
    if resolved == 0:
        raise SrcCutError(422, "源全不可得", "no_source")

    # ---------------- sent 档：边界块 anchor 定位 → 句界外扩 ----------------
    clipped = _apply_sent_clips(rows, pieces, req)

    # ---------------- 拼接：连续 run verbatim + 壳边扩展 + 跨文件界标 -------
    latex, files_seen = _join_pieces(cutter, rows, pieces, req)

    # ---------------- 输出帽 + 响应面 ----------------
    data = latex.encode("utf-8")
    truncated = len(data) > OUT_CAP
    if truncated:
        latex = data[:OUT_CAP].decode("utf-8", errors="ignore")
    resp: dict[str, Any] = {
        "latex": latex,
        "chunks": resolved,
        "files": files_seen,
        "mode_used": "sent" if clipped else "whole",
    }
    if any(p is not None and p.approx for p in pieces):
        resp["approx"] = True
    if truncated:
        resp["truncated"] = True
    return resp
