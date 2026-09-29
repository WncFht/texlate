"""refs.bib 导出组装（M4）：Lane A .bib verbatim + Lane B 远端 bibtex + Lane C 合成兜底。

三臂顺序（misc-pack 实现文档 §M4，spike: tmp/ux-research-20260922/exp/ms-bib-export/）：

- **Lane A**：key 命中 src.tar/upload blob 内 ``*.bib`` → 原 entry verbatim
  直出 + 被引 ``@STRING`` defs 闭包置顶（33 条实证依赖宏，不带 defs 导出
  即断链）；hyperref 把 ``cite.*`` dest 小写化——大小写折叠键表兜底。
- **Lane B**：无 verbatim 但有 arxiv/doi 线索 → 远端 crosscite
  （``Accept: application/x-bibtex``）：DOI → ``doi.org/<unquoted>``，
  arXiv → ``doi.org/10.48550/arXiv.<id>``（DataCite）；无 id 有文本 →
  Crossref ``query.bibliographic`` 末臂，``title-overlap>=0.5`` 门控
  （不门控=毒导出，实测 5/12 通过率）。回包 bibtex key 改写成文档 key。
  **S2 永不进链**（429 常态实证）。并发闸 4、单请求 15s（client 持有）、
  总 deadline ~20s。
- **Lane C**：kept payload RefMeta 快照 → ``@misc`` 字段合成；meta 空 →
  ``note={text}``；text 也空 → ``@misc{key}`` 壳。

远端臂失败/超时/低重叠一律自动降级 Lane C——绝不 502；降级 key 由
``build_bib`` 回报给端点写 ``X-Refs-Degraded`` 头与文件头注释。
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import tarfile
import zipfile
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from texlate.arxiv.fetch import ARXIV_ID_FIND_RX, normalize_arxiv_id
from texlate.server._common import norm_doi

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import httpx

log = logging.getLogger(__name__)

#: 远端臂总 deadline（实测 p50 2.2s / max 20.3s——总闸+并发+兜底是硬需求）
REMOTE_DEADLINE_S = 20.0
REMOTE_CONCURRENCY = 4
#: Crossref bibliographic 末臂的 title token 重叠门（实测拐点，钉死防毒）
CROSSREF_MIN_OVERLAP = 0.5
_CROSSREF_API = "https://api.crossref.org/works"
_BIBTEX_ACCEPT = {"Accept": "application/x-bibtex"}
_SRC_SUFFIXES = (".bib", ".bbl", ".tex")

_BIB_ENTRY_RX = re.compile(r"@([A-Za-z]+)\s*[({]")
_BIBITEM_RX = re.compile(
    r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}(.*?)"
    r"(?=\\bibitem|\\end\{thebibliography\}|\Z)",
    re.DOTALL,
)
#: 上下文前缀臂（``extract_ids`` 优先臂）——裸 id 形状单源在
#: ``arxiv.fetch.ARXIV_ID_FIND_RX``，本件只补 arxiv.org/arXiv: 前缀闸
_ARXIV_CTX_RX = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arXiv[:\s])" + ARXIV_ID_FIND_RX.pattern,
    re.IGNORECASE,
)


# ------------------------------------------------------------ .bib 解析原语


def parse_bib(src: str) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """粗 .bib 解析：``{key: (type, 原文段)}`` + ``{@string 名(lower): 原文}``。

    brace-balanced 扫描 ``@type{key, …}``——entry 自身的开分隔符定计数
    （``{`` 开只数 ``{}``，``(`` 开只数 ``()``）；同 key 首现胜
    （``setdefault``），``@preamble``/``@comment`` 跳过。
    """
    entries: dict[str, tuple[str, str]] = {}
    strings: dict[str, str] = {}
    for m in _BIB_ENTRY_RX.finditer(src):
        typ = m.group(1).lower()
        i = m.end()
        if typ == "string":
            km = re.match(r"\s*([A-Za-z][\w-]*)\s*=", src[i:])
        else:
            km = re.match(r"\s*([^,\s}]+)\s*,", src[i:])
        if not km:
            continue
        key = km.group(1)
        body_start = i + km.end()
        open_ch = src[m.end() - 1]
        close_ch = "}" if open_ch == "{" else ")"
        depth = 1
        j = body_start
        while j < len(src) and depth:
            ch = src[j]
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
            j += 1
        raw = src[m.start() : j]
        if typ == "string":
            strings[key.lower()] = raw
            continue
        if typ in ("preamble", "comment"):
            continue
        entries.setdefault(key, (typ, raw))
    return entries, strings


def entry_uses_strings(raw: str, string_names: set[str]) -> set[str]:
    """Entry 文本引用的 ``@string`` 名集（裸 token 值：``= name`` 不带括号/引号）。"""
    hits: set[str] = set()
    for m in re.finditer(r"=\s*([A-Za-z][\w-]*)\s*[,}]", raw):
        tok = m.group(1).lower()
        if tok in string_names:
            hits.add(tok)
    return hits


def _iter_member_texts(blob: bytes, hint: str) -> Iterator[tuple[str, str]]:
    """Src blob → ``(member名, utf-8 文本)``：tar 各族 → zip → 裸文本回退。

    ``hint`` = blob 原文件名（裸 ``.tex``/``.bib`` 上传时决定回退臂的
    解析口径）；成员 decode 失败逐件跳过，整包不炸。
    """
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tf:
            for m in tf.getmembers():
                if not m.isfile() or not m.name.lower().endswith(_SRC_SUFFIXES):
                    continue
                f = tf.extractfile(m)
                if f is None:
                    continue
                try:
                    yield m.name, f.read().decode("utf-8", "replace")
                except Exception as e:  # noqa: BLE001 -- 坏成员跳过
                    log.debug("bibexport: member decode skip %s: %s", m.name, e)
            return
    except tarfile.TarError:
        pass
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for n in zf.namelist():
                if not n.lower().endswith(_SRC_SUFFIXES):
                    continue
                try:
                    yield n, zf.read(n).decode("utf-8", "replace")
                except Exception as e:  # noqa: BLE001 -- 坏成员跳过
                    log.debug("bibexport: zip member skip %s: %s", n, e)
            return
    except zipfile.BadZipFile:
        pass
    yield hint, blob.decode("utf-8", "replace")


def _bibitem_texts(src: str) -> Iterator[tuple[str, str]]:
    r"""``.bbl``/inline ``.tex`` 的 ``\bibitem{key}`` → 到下一 bibitem/尾 的 body。"""
    for m in _BIBITEM_RX.finditer(src):
        yield m.group(1).strip(), m.group(2)


def clean_bib_text(t: str) -> str:
    """排版残件最小清理（citations.cleanBibText 粗对应物）。"""
    t = re.sub(r"\\newblock\b", " ", t)
    t = re.sub(r"\\(?:em|emph|textit|textbf|url|doi|href)\b", " ", t)
    t = re.sub(r"\\[A-Za-z]+\s*", " ", t)
    t = re.sub(r"[{}]", "", t)
    t = re.sub(r"~", " ", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def extract_ids(text: str) -> tuple[str | None, str | None]:
    """``citations.ts extractRefIds`` 的 python 移植：排版文本 → (arxiv, doi)。"""
    arxiv = None
    m = _ARXIV_CTX_RX.search(text) or ARXIV_ID_FIND_RX.search(text)
    if m:
        arxiv = m.group(1)
    m2 = re.search(r"(?:doi\.org/|doi[:\s]+)(10\.\d{4,9}/\S+)", text, re.IGNORECASE)
    doi = m2.group(1).rstrip(".,;)]}") if m2 else None
    return arxiv, doi


# ------------------------------------------------------------ 物料装配


@dataclass(slots=True)
class SrcIndex:
    """src blob 扫出的引用物料面。"""

    bib: dict[str, tuple[str, str]] = field(default_factory=dict)
    bib_ci: dict[str, str] = field(default_factory=dict)  # lower -> 原 key
    strings: dict[str, str] = field(default_factory=dict)
    bibitems: dict[str, str] = field(default_factory=dict)  # key -> 清理后文本

    def universe(self, kept: dict[str, Any]) -> list[str]:
        """全可解 key：.bib ∪ bibitem ∪ kept（序稳定：src 序后 kept 补）。"""
        seen: list[str] = []
        known: set[str] = set()
        for k in [*self.bib, *self.bibitems, *kept]:
            if k not in known:
                known.add(k)
                seen.append(k)
        return seen


def load_src_index(src_path: Path | None) -> SrcIndex:
    """Src blob → ``SrcIndex``（纯同步 I/O——调用方 ``to_thread`` 卸载）。"""
    idx = SrcIndex()
    if src_path is None:
        return idx
    try:
        blob = src_path.read_bytes()
    except OSError:
        return idx
    for name, src in _iter_member_texts(blob, src_path.name):
        low = name.lower()
        if low.endswith(".bib"):
            entries, strings = parse_bib(src)
            for k, v in entries.items():
                idx.bib.setdefault(k, v)
            idx.strings.update(strings)
        if low.endswith((".bbl", ".tex")):
            for key, body in _bibitem_texts(src):
                idx.bibitems.setdefault(key, clean_bib_text(body))
    idx.bib_ci = {k.lower(): k for k in idx.bib}
    return idx


@dataclass(slots=True)
class RefItem:
    """一 key 的导出物料：verbatim 优先，ids/text 驱远端臂，meta 供合成。"""

    key: str
    verbatim: str | None = None
    text: str = ""
    arxiv: str | None = None
    doi: str | None = None
    meta: dict[str, Any] | None = None

    @property
    def remote_worthy(self) -> bool:
        """远端臂有得解（id 线索或可检索文本）。"""
        return bool(self.arxiv or self.doi or self.text)


def _norm_arxiv(raw: object) -> str | None:
    """kept/抽取面 arXiv id 归一 → canon base（剥版本——DataCite DOI 按 base 解）。"""
    if not isinstance(raw, str):
        return None
    base, _ver = normalize_arxiv_id(raw)
    return base or None


def plan_items(
    keys: list[str], idx: SrcIndex, kept: dict[str, dict[str, Any]]
) -> list[RefItem]:
    """Key 清单 → 物料表。

    verbatim 命中、ids（kept 快照优先 → 文本抽取）、bibitem 清理文本、
    kept RefMeta 快照一次归并。
    """
    items: list[RefItem] = []
    for key in keys:
        kp = kept.get(key) or {}
        ent = idx.bib.get(key)
        if ent is None:
            ci = idx.bib_ci.get(key.lower())
            ent = idx.bib.get(ci) if ci else None
        text = idx.bibitems.get(key, "")
        if not text and isinstance(kp.get("text"), str):
            text = clean_bib_text(kp["text"])
        arxiv = _norm_arxiv(kp.get("arxivId"))
        doi = norm_doi(kp.get("doi"))
        if (not arxiv and not doi) and text:
            ax, d = extract_ids(text)
            arxiv, doi = _norm_arxiv(ax), norm_doi(d)
        meta = kp.get("meta") if isinstance(kp.get("meta"), dict) else None
        items.append(
            RefItem(
                key=key,
                verbatim=ent[1].strip() if ent else None,
                text=text,
                arxiv=arxiv,
                doi=doi,
                meta=meta,
            )
        )
    return items


# ------------------------------------------------------------ Lane B 远端臂


def rewrite_key(bib: str, key: str) -> str:
    """远端 bibtex 的首个 ``{key,`` 换成文档自己的 bibkey。"""
    return re.sub(r"(@[A-Za-z]+\s*[({])\s*[^,\s]+", r"\1" + key, bib, count=1)


def bibtex_title(bib: str) -> str:
    """回包 bibtex 的 title 字段值（门控比较用）。"""
    m = re.search(r'title\s*=\s*[{"](.+?)[}"]\s*,', bib, re.DOTALL | re.IGNORECASE)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def token_overlap(a: str, b: str) -> float:
    """Token 集交叠 ``|∩|/min(|a|,|b|)``——Crossref 末臂质检门。"""
    ta = set(re.findall(r"[a-z]{3,}", a.lower()))
    tb = set(re.findall(r"[a-z]{3,}", b.lower()))
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


async def _crosscite(
    client: httpx.AsyncClient, doi: str, key: str, *, tries: int = 2
) -> str | None:
    """``GET doi.org/{doi}`` Accept x-bibtex → 改写 key 的 bibtex 原文。

    瞬时失败（SSL 抖动/5xx/429）重试 ``tries`` 次；404/410 硬 miss 不重试；
    回包非 ``@`` 开头（上游格式漂移）按 miss 降级不炸。
    """
    url = f"https://doi.org/{quote(doi)}"
    for attempt in range(tries):
        try:
            resp = await client.get(url, headers=_BIBTEX_ACCEPT)
        except Exception:  # noqa: BLE001 -- 网络抖动/关 client 皆按瞬时
            if attempt + 1 < tries:
                await asyncio.sleep(0.4)
            continue
        if resp.status_code == HTTPStatus.OK:
            body = resp.text
            if body.lstrip().startswith("@"):
                return rewrite_key(body.strip(), key)
            return None  # 200 但非 bibtex——格式漂移不重试不炸
        if resp.status_code in (HTTPStatus.NOT_FOUND, HTTPStatus.GONE):
            return None
        if attempt + 1 < tries:
            await asyncio.sleep(0.4)
    return None


async def _crossref_top_doi(client: httpx.AsyncClient, text: str) -> str | None:
    """Crossref ``query.bibliographic`` rows=1 → 首条命中 DOI（无则 None）。"""
    try:
        resp = await client.get(
            _CROSSREF_API,
            params={
                "query.bibliographic": text[:300],
                "rows": "1",
                "mailto": "texlate@localhost",
            },
        )
    except Exception:  # noqa: BLE001 -- 上游挂按 miss
        return None
    if resp.status_code != HTTPStatus.OK:
        return None
    try:
        items = resp.json().get("message", {}).get("items") or []
    except Exception:  # noqa: BLE001 -- 坏 JSON 按 miss
        return None
    doi = items[0].get("DOI") if items and isinstance(items[0], dict) else None
    return doi if isinstance(doi, str) and doi else None


async def _crossref_bib(client: httpx.AsyncClient, text: str, key: str) -> str | None:
    """Crossref 末臂：检索命中 DOI → crosscite → overlap≥0.5 门控。

    ``title_overlap`` 实测拐点 0.5（12 探 5 过）——不门控即毒导出，门控
    拒收宁降级。
    """
    doi = await _crossref_top_doi(client, text)
    if doi is None:
        return None
    bib = await _crosscite(client, doi, key, tries=1)
    if bib and token_overlap(text, bibtex_title(bib)) >= CROSSREF_MIN_OVERLAP:
        return bib
    return None


async def _resolve_one(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, item: RefItem
) -> tuple[str, str | None]:
    """单 key 远端链：DOI crosscite → arXiv DataCite → Crossref 末臂。"""
    async with sem:
        try:
            if item.doi:
                bib = await _crosscite(client, item.doi, item.key)
                if bib:
                    return item.key, bib
            if item.arxiv:
                bib = await _crosscite(client, f"10.48550/arXiv.{item.arxiv}", item.key)
                if bib:
                    return item.key, bib
            if item.text:
                bib = await _crossref_bib(client, item.text, item.key)
                if bib:
                    return item.key, bib
        except Exception as e:  # noqa: BLE001 -- 单 key 炸不拖全批
            log.debug("bibexport resolve %s failed: %s", item.key, e)
        return item.key, None


async def resolve_remote(
    client: httpx.AsyncClient,
    items: list[RefItem],
    *,
    deadline: float = REMOTE_DEADLINE_S,
) -> dict[str, str]:
    """并发闸 4 + 总 deadline 批量远端解 → ``{key: bibtex}``。

    deadline 到点未完成项按失败计（外层 wait_for 撤 gather，子任务随
    cancellation 收）——降级由 ``build_bib`` 统一兜底，本函数绝不抛。
    """
    sem = asyncio.Semaphore(REMOTE_CONCURRENCY)
    tasks = [asyncio.ensure_future(_resolve_one(client, sem, it)) for it in items]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), deadline)
    except TimeoutError:
        log.info("bibexport remote deadline %.0fs hit", deadline)
    out: dict[str, str] = {}
    for t in tasks:
        if not t.done() or t.cancelled():
            continue
        res = t.result()
        if isinstance(res, tuple) and res[1]:
            out[res[0]] = res[1]
    return out


# ------------------------------------------------------------ Lane C 合成


def _esc(s: str) -> str:
    """Bibtex 字段值最小转义：剥花括号、转义裸 ``%&#$``（编译炸点）。"""
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"(?<!\\)([%&#$])", r"\\\1", s)


def norm_key(raw: str) -> str:
    """Bibkey 白名单化（bibtex 保留字符→``_``）。"""
    return re.sub(r"[^\w:.-]", "_", raw)


def meta_to_bib(key: str, meta: dict[str, Any] | None, text: str = "") -> str:
    """RefMeta 快照 → ``@misc`` 段；meta 全空 → ``note={text}``；双无 → 空壳。"""
    k = norm_key(key)
    m = meta or {}
    fields: list[tuple[str, str]] = []
    if isinstance(m.get("title"), str) and m["title"]:
        fields.append(("title", m["title"]))
    authors = m.get("authors")
    if isinstance(authors, list):
        names = [a for a in authors if isinstance(a, str) and a]
        if names:
            fields.append(("author", " and ".join(names)))
    if m.get("year"):
        fields.append(("year", str(m["year"])))
    if isinstance(m.get("venue"), str) and m["venue"]:
        fields.append(("journaltitle", m["venue"]))
    if isinstance(m.get("doi"), str) and m["doi"]:
        fields.append(("doi", m["doi"]))
    if isinstance(m.get("arxivId"), str) and m["arxivId"]:
        fields.append(("eprint", m["arxivId"]))
        fields.append(("archivePrefix", "arXiv"))
    if not fields:
        note = re.sub(r"\s{2,}", " ", text).strip()
        if not note:
            return f"@misc{{{k}}}"  # 空壳（kept-refs-design 风险 2 已知退化）
        return f"@misc{{{k},\n  note = {{{_esc(note)}}}\n}}"
    body = ",\n".join(f"  {f} = {{{_esc(v)}}}" for f, v in fields)
    return f"@misc{{{k},\n{body}\n}}"


# ------------------------------------------------------------ 总装


def build_bib(
    items: list[RefItem],
    remote: dict[str, str],
    strings: dict[str, str],
    *,
    truncated: bool = False,
) -> tuple[str, list[str]]:
    """物料 + 远端结果 → refs.bib 全文 + 降级 key 表。

    Lane A verbatim 优先；Lane B 远端命中次之；其余落 Lane C 合成——
    ``remote_worthy`` 而没解到 bibtex 的计入 degraded（头部注释 + 响应头
    双层报告）。``@STRING`` defs 闭包随 verbatim 条目置顶注释块。
    """
    header = ["% texlate refs.bib export"]
    if truncated:
        header.append("% WARNING: key list truncated to export cap")
    need_strings: set[str] = set()
    blocks: list[str] = []
    degraded: list[str] = []
    for it in items:
        if it.verbatim is not None:
            need_strings |= entry_uses_strings(it.verbatim, set(strings))
            blocks.append(it.verbatim)
            continue
        bib = remote.get(it.key)
        if bib is not None:
            blocks.append(bib)
            continue
        if it.remote_worthy:
            degraded.append(it.key)
        blocks.append(meta_to_bib(it.key, it.meta, it.text))
    defs = [strings[n] for n in sorted(need_strings) if n in strings]
    if degraded:
        header.append(
            "% degraded (remote bibtex unavailable, fell back to @misc): "
            + ", ".join(degraded)
        )
    if defs:
        header.append("% ---- @STRING defs required by entries below ----")
    parts = ["\n".join(header)]
    parts += [d.strip() for d in defs]
    parts += blocks
    return "\n\n".join(parts) + "\n", degraded
