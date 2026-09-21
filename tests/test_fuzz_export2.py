r"""``export/`` 第二波 fuzz——rights/load_epub/save_epub/drive_pipeline 边界。

与 ``test_fuzz_export.py`` 分工：那边盖 L1 纯函数/L2 单元/L3 e2e 正常面；
本文件专补其未触面——``check_epub`` DRM 判定全表、``load_epub`` 敌意
容器层、``save_epub`` 敌意成员名、``drive_pipeline`` 失败路径、
``coerce_glossary``/``marker_report`` 契约边角、``insert_after`` 敌意
language。

不变量清单：

- ``check_epub`` 对任意 zip/路径返回恰 ``"ok"``/``"drm"`` 之一、绝不抛；
  白名单纪律：只有所有 EncryptedData 直属 EncryptionMethod 全在
  ``FONT_OBFUSCATION`` 才 ``"ok"``；解析失败/无条目/无方法/藏深处的
  方法一律 ``"drm"``（判反的代价是帮助规避——宽侧宁错杀）。
- ``load_epub`` 只让 ``ExportError`` 族逃逸（含 Malformed/FixedLayout/
  Drm）；返回即 ``EpubBook`` 自洽（members/order/doc_paths 一致）。
- ``save_epub`` OCF 硬约束：``mimetype`` 首条 ZIP_STORED、内容恰为
  ``application/epub+zip``，其余 DEFLATED；成员名门禁（E1/E2 修复后
  契约）——空名/控制字符（含 NUL）/``..`` 段/``/`` 绝对/``\\`` 分隔/
  ``X:`` 驱动器形 → ``MalformedEpubError``，先于建包拒绝不留半截包；
  ``zipfile.ZipInfo`` 读写两侧都在首个 NUL 截断，「逐字节保留 NUL 名」
  在 stdlib 层不可实现，拒绝是唯一诚实契约。
- ``drive_pipeline``：apply_fn/save_fn 异常原样传播（半成品回放路径
  ``except Exception`` 兜底不再抛）；translator 永抛 → 管线内部降级
  完成；store 脏态 ``load()`` 优雅空集。
- ``coerce_glossary``：非文件路径族 → ``ExportError``；``Mapping`` 值
  ``str()`` 归一；类型外入参 → ``TypeError``（调用方契约钉）。

缺陷台账（``tmp/export-fuzz/`` 实证，2026-09-17，xfail-strict 钉——
修复后 XPASS 即拆钉信号）：

- CONFIRMED E0：``check_epub`` 对含 ``\x00`` 路径抛 ``ValueError``
  逃逸——``rights.py:81`` 只兜 ``OSError``/``BadZipFile``，而
  ``io.open`` 的 ``embedded null byte`` 是 ``ValueError``（非 OSError
  子类）。docstring「不存在的文件返回 ``"ok"``」契约破，
  ``load_epub`` 首步即被穿透（NUL 路径 → ``ValueError`` 而非
  ``MalformedEpubError``）。
- CONFIRMED E1：``save_epub`` 成员名含 ``\x00`` → zipfile 静默截断
  （``a\x00evil`` 写成 ``a``）→ 与真 ``a`` 成员撞名 → 出包出现重名
  条目且先写者内容被顶替（``read("a")`` 拿到后写者）。可达性：敌意
  EPUB 的 zip 中央目录可携 NUL 名成员（``load_epub`` 原样收入
  ``members``）→ 出包静默腐蚀。
- CONFIRMED E2（minor）：``save_epub`` 原样透传敌意成员名——
  ``../evil``/绝对名/控制字符进出包（OCF 成员名应受限相对路径；
  zip-slip 形态随出包流向任何按名落盘的下游提取器）。``load_epub``
  侧 ``members`` 同样不拒，进出全链零过滤。
- FIXED E3（跨界，根在 ``xlat/pipeline.py``）：translator 内抛
  ``KeyboardInterrupt``/``SystemExit``/``GeneratorExit``——sentinel
  与 worker 一一对应，带 BaseException 死掉的 worker 令其 sentinel
  无人消费 → ``queue.join()`` 死锁（KI/SE 另经 ``Task.__step``
  重抛沿事件循环层逃逸，gather 自始至终够不到）。修法：worker 把
  非 ``Exception`` 收进 ``fatal`` 账、只吃不做排空到 sentinel 保
  join 会计（fatal 后退场过早同样死锁——剩余项多于存活 worker 时
  残余 task_done 无人发），``_drain`` 在 join 收敛后重抛。回归钉
  走 single 工作项布阵让异常落在 worker 路径（warmup 臂本就直传，
  钉不到 worker）；形态钉 conc=2 + 6 项直钉 ``XlatPipeline``。

观察钉（pin observed——当前行为即取舍，定性留裁决）：

- ``save_epub`` order/members 失同步 → 裸 ``KeyError``（非 ExportError
  ——内部不变量面，腐态才可达）。
- ``load_epub`` ``member_path`` percent-decode 优先：``a%20b.xhtml``
  href 命中成员 ``a b.xhtml``，即便存在字面 ``a%20b.xhtml`` 成员
  （unquote 先行、原样兜底——spec 正确序已钉）。
- ``Pre-Paginated``（大小写变体）不触发 ``FixedLayoutError``——
  ``strip() == "pre-paginated"`` 精确匹配，非规格值放行照翻。
- ``spine`` 引用缺席 idref → 该条跳过，manifest 尾部 xhtml 兜底进
  ``doc_paths``（文档面不因 spine 脏而空）。
- zip 重名成员首个胜出（``infolist`` 序 + ``not in members`` 判定）。
- ``coerce_glossary(42)`` → ``TypeError``（非 ExportError）；
  ``{1: 2, None: None}`` → 键值 ``str()`` 归一（``"None"`` 入表）。
- ``marker_report`` 非-str sent/reply → ``TypeError`` 裸逃；
  issued 传 dict → 迭代键当 token（鸭子型）。
- ``insert_after`` 敌意 ``language``（控制字符/NUL）→ ``ValueError``
  （lxml XML 合法门禁）；敌意 ``zh_text`` 由 ``sanitize_xml_text``
  剥除控制字符/NUL/surrogate 后安静插入。
- ``drive_pipeline`` 重复 ``chunk_id`` 后写胜（dict 推导）——
  apply 只见去重表（chunk_id 唯一性是调用方契约）。
"""

from __future__ import annotations

import asyncio
import zipfile
from typing import TYPE_CHECKING

import pytest
from _fuzzkit import (
    assert_deterministic,
    fuzz_rng,
    short,
    soup_join,
    soup_pick,
)
from _zipkit import ed, encdoc, wzip

from texlate.export import sniff_format
from texlate.export.common import (
    ApplyCounts,
    ExportError,
    coerce_glossary,
    drive_pipeline,
)
from texlate.export.docx import insert_after
from texlate.export.epub import EpubBook, load_epub, save_epub
from texlate.export.markers import marker_report
from texlate.export.rights import FONT_OBFUSCATION, PROTECTION_FILES, check_epub
from texlate.xlat.pipeline import (
    ChunkIn,
    MockTranslator,
    PipelineConfig,
    XlatPipeline,
)
from texlate.xlat.state import StateStore

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------- 常量

_SEED_RIGHTS = 2026091709
_SEED_LOAD = 2026091710
_SEED_MEMBER = 2026091711
_SEED_DRIVE = 2026091712

_ENC = "META-INF/encryption.xml"
_FONT_OBF = "http://www.idpf.org/2008/embedding"
_AES = "http://www.w3.org/2001/04/xmlenc#aes128-cbc"
_CONTAINER = "META-INF/container.xml"
_XHTML = (
    b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml">'
    b"<body><p>x</p></body></html>"
)


# ---------------------------------------------------------------- zip 构造件


def _wzip(path: Path, members: dict[str, bytes]) -> Path:
    """写 zip（成员序 = dict 序）；目录条目与重名走调用方手写。"""
    return wzip(path, members, compress=zipfile.ZIP_STORED)


def _container(opf_path: str | None) -> bytes:
    if opf_path is None:
        return (
            b'<?xml version="1.0"?>'
            b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            b"<rootfiles/></container>"
        )
    return (
        b'<?xml version="1.0"?>'
        b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        b'<rootfiles><rootfile full-path="'
        + opf_path.encode()
        + b'" media-type="application/oebps-package+xml"/></rootfiles></container>'
    )


def _opf(
    items: list[tuple[str, str, str]],
    spine: list[str],
    extra: bytes = b"",
) -> bytes:
    its = b"".join(
        f'<item id="{i}" href="{h}" media-type="{m}"/>'.encode() for i, h, m in items
    )
    refs = b"".join(f'<itemref idref="{r}"/>'.encode() for r in spine)
    return (
        b'<?xml version="1.0"?>'
        b'<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        b"<metadata xmlns:dc='http://purl.org/dc/elements/1.1/'>"
        b"<dc:language>en</dc:language></metadata>"
        b"<manifest>"
        + its
        + b"</manifest><spine>"
        + refs
        + b"</spine>"
        + extra
        + b"</package>"
    )


def _book(members: dict[str, bytes], order: list[str] | None = None) -> EpubBook:
    return EpubBook(
        members=members,
        order=list(order) if order is not None else list(members),
        doc_paths=[],
        opf_path="",
        opf_dir="",
        ncx_path=None,
    )


# ---------------------------------------------------------------- check_epub


class TestCheckEpub:
    """``rights.check_epub``——返回面恰 ``{"ok","drm"}``、白名单纪律、绝不抛。"""

    @pytest.mark.parametrize(
        ("members", "want"),
        [
            ({}, "ok"),  # 空 zip 不是 DRM 声明
            ({"META-INF/rights.xml": b"<x/>"}, "drm"),
            ({"META-INF/license.lcpl": b"{}"}, "drm"),
            ({"META-INF/sinf.xml": b"x"}, "drm"),
            ({"META-INF/signatures.xml": b"<x/>"}, "ok"),  # 签名≠保护（刻意缺席）
            ({"meta-inf/rights.xml": b"<x/>"}, "ok"),  # 大小写精确（观察钉）
            ({"META-INF/rights.xml/": b"x"}, "ok"),  # 尾斜杠是另一名字（观察钉）
            ({_ENC: encdoc(ed(_FONT_OBF))}, "ok"),  # 纯字体混淆
            ({_ENC: encdoc(ed("http://ns.adobe.com/pdf/enc#RC"))}, "ok"),
            ({_ENC: encdoc(ed(_AES))}, "drm"),
            ({_ENC: encdoc(ed(_FONT_OBF) + ed(_AES))}, "drm"),  # 混排一票否决
            ({_ENC: encdoc(ed(None))}, "drm"),  # 不报算法
            ({_ENC: encdoc(ed(""))}, "drm"),  # 空算法
            (
                {_ENC: encdoc(ed("http://www.idpf.org/2008/Embedding"))},
                "drm",
            ),  # 大小写
            ({_ENC: encdoc(ed(_FONT_OBF + " "))}, "drm"),  # 尾随空白精确匹配
            ({_ENC: encdoc(b"<enc:EncryptionData/>")}, "drm"),  # 无 EncryptedData 组
            (
                {
                    _ENC: encdoc(
                        b"<enc:EncryptedData><enc:CipherData/></enc:EncryptedData>"
                    )
                },
                "drm",
            ),  # 无方法
            (
                {
                    _ENC: encdoc(
                        b"<enc:EncryptedData><enc:CipherData>"
                        b'<x:EncryptionMethod xmlns:x="u" Algorithm="'
                        + _AES.encode()
                        + b'"/></enc:CipherData></enc:EncryptedData>'
                    )
                },
                "drm",
            ),  # 藏在 CipherData 深处的方法不算声明
            ({_ENC: b""}, "drm"),  # 读不懂的声明按有害读
            ({_ENC: b"not xml <<<"}, "drm"),
            ({_ENC: b"\xef\xbb\xbf" + encdoc(ed(_FONT_OBF))}, "ok"),  # BOM 容忍
            ({_ENC: encdoc(ed(_FONT_OBF)) + b"GARBAGE"}, "drm"),  # 尾随垃圾
            ({_ENC: b"<r><x></r>"}, "drm"),
            (
                {
                    _ENC: b'<?xml version="1.0"?>'
                    b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                    b"<r>&x;</r>"
                },
                "drm",
            ),  # 实体攻击 → defusedxml 拦 → drm
            (
                {
                    _ENC: b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "xxxx">'
                    b'<!ENTITY b "&a;&a;&a;&a;">]><r>&b;</r>'
                },
                "drm",
            ),  # billion laughs 同拦
        ],
    )
    def test_pin_table(
        self, tmp_path: Path, members: dict[str, bytes], want: str
    ) -> None:
        assert check_epub(_wzip(tmp_path / "c.epub", members)) == want

    def test_not_zip_and_missing_ok(self, tmp_path: Path) -> None:
        """非 zip/不存在 → ``"ok"``（拒绝替读取器报错——docstring 契约）。"""
        p = tmp_path / "nz.epub"
        p.write_bytes(b"not a zip")
        assert check_epub(p) == "ok"
        assert check_epub(tmp_path / "missing.epub") == "ok"
        assert check_epub(str(tmp_path / "missing.epub")) == "ok"  # str 路径同形

    def test_dir_path_ok(self, tmp_path: Path) -> None:
        """目录路径 → ``"ok"``（OSError 族归 ok 臂）。"""
        assert check_epub(tmp_path) == "ok"

    def test_nul_path_ok(self, tmp_path: Path) -> None:
        """E0 已修：NUL 路径同其它不可读形态 → ``"ok"``（ValueError 入兜）。"""
        assert check_epub(tmp_path / "a\x00b.epub") == "ok"

    def test_fuzz_member_names_never_raises(self, tmp_path: Path) -> None:
        """随机成员名集 → 返回恒 ∈{ok,drm}；保护文件名命中即 drm。"""
        rng = fuzz_rng(_SEED_RIGHTS)
        name_soup = [
            "META-INF/rights.xml",
            "meta-inf/rights.xml",
            "META-INF/license.lcpl",
            "META-INF/sinf.xml",
            "META-INF/encryption.xml",
            "a.txt",
            "OEBPS/x.opf",
            "../evil",
            "a b",
            "a%20b",
            "",
            "mimetype",
        ]
        for i in range(200):
            names = [soup_pick(rng, name_soup) for _ in range(rng.randint(0, 6))]
            members = dict.fromkeys(names, b"x")
            out = check_epub(_wzip(tmp_path / f"f{i}.epub", members))
            assert out in ("ok", "drm")
            if set(names) & PROTECTION_FILES:
                assert out == "drm"

    def test_fuzz_encryption_xml_oracle(self, tmp_path: Path) -> None:
        """encryption.xml 随机结构 → 独立 spec oracle 对账判定结果。"""
        rng = fuzz_rng(_SEED_RIGHTS + 1)
        alg_soup = [_FONT_OBF, _AES, "", "http://x", _FONT_OBF + " ", "garbage"]
        frag_soup = [
            b"<enc:EncryptedData/>",
            b"",
            b"<enc:EncryptionMethod/>",
            b"</enc:EncryptedData>",
            b"<foo>",
            b"plain text",
        ]
        for i in range(200):
            r = rng.random()
            if r < 0.3:  # noqa: PLR2004 -- soup 概率档
                body = encdoc(
                    b"".join(
                        ed(soup_pick(rng, alg_soup)) for _ in range(rng.randint(0, 3))
                    )
                )
            elif r < 0.6:  # noqa: PLR2004
                body = encdoc(
                    b"".join(
                        soup_pick(rng, frag_soup) for _ in range(rng.randint(1, 4))
                    )
                )
            else:
                body = b"".join(
                    soup_pick(rng, frag_soup) for _ in range(rng.randint(1, 5))
                )
            out = check_epub(_wzip(tmp_path / f"e{i}.epub", {_ENC: body}))
            assert out in ("ok", "drm")
            assert out == _oracle_drm(body)


def _oracle_drm(body: bytes) -> str:
    """独立 spec 复述：每条 EncryptedData 直属方法全在 FONT_OBFUSCATION → ok。"""
    import xml.etree.ElementTree as ET  # noqa: PLC0415 -- oracle 刻意换解析器

    try:
        root = ET.fromstring(body)  # noqa: S314 -- oracle 复诵 spec 判定面，本地构造输入
    except ET.ParseError:
        return "drm"
    entries = [el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "EncryptedData"]
    if not entries:
        return "drm"
    for entry in entries:
        algs = [
            el.get("Algorithm")
            for el in entry
            if el.tag.rsplit("}", 1)[-1] == "EncryptionMethod"
        ]
        if not algs or any(a not in FONT_OBFUSCATION for a in algs):
            return "drm"
    return "ok"


# ---------------------------------------------------------------- load_epub


class TestLoadEpub:
    """``load_epub`` 敌意容器层——只许 ``ExportError`` 族逃逸。"""

    @pytest.mark.parametrize(
        ("members", "label"),
        [
            ({}, "empty zip"),
            ({"a.txt": b"x"}, "no container"),
            ({_CONTAINER: b"<<<"}, "container bad xml"),
            ({_CONTAINER: _container(None)}, "no rootfile"),
            (
                {
                    _CONTAINER: b'<?xml version="1.0"?>'
                    b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    b"<rootfiles><rootfile/></rootfiles></container>"
                },
                "rootfile no full-path",
            ),
            ({_CONTAINER: _container("OEBPS/x.opf")}, "opf not in members"),
            (
                {_CONTAINER: _container("o.opf"), "o.opf": b"<package<"},
                "opf bad xml",
            ),
            ({_CONTAINER: _container("o.opf"), "o.opf": _opf([], [])}, "no items"),
            (
                {
                    _CONTAINER: _container("o.opf"),
                    "o.opf": _opf([("a", "a.png", "image/png")], ["a"]),
                    "a.png": b"x",
                },
                "no xhtml",
            ),
            (
                {
                    _CONTAINER: _container("o.opf"),
                    "o.opf": _opf(
                        [("a", "a.xhtml", "application/xhtml+xml")],
                        ["a"],
                        extra=b'<meta xmlns="http://www.idpf.org/2007/opf" '
                        b'property="rendition:layout">pre-paginated</meta>',
                    ),
                    "a.xhtml": _XHTML,
                },
                "fixed layout",
            ),
        ],
    )
    def test_export_error_family(
        self, tmp_path: Path, members: dict[str, bytes], label: str
    ) -> None:
        with pytest.raises(ExportError):
            load_epub(_wzip(tmp_path / f"{label.replace(' ', '_')}.epub", members))

    def test_ok_minimal(self, tmp_path: Path) -> None:
        book = load_epub(
            _wzip(
                tmp_path / "ok.epub",
                {
                    _CONTAINER: _container("o.opf"),
                    "o.opf": _opf([("a", "a.xhtml", "application/xhtml+xml")], ["a"]),
                    "a.xhtml": _XHTML,
                },
            )
        )
        assert book.doc_paths == ["a.xhtml"]
        assert book.opf_path == "o.opf"
        assert book.members["a.xhtml"] == _XHTML

    def test_pre_paginated_case_variant_passes(self, tmp_path: Path) -> None:
        """观察钉：``Pre-Paginated`` 大小写变体不触发 FixedLayoutError。"""
        book = load_epub(
            _wzip(
                tmp_path / "flc.epub",
                {
                    _CONTAINER: _container("o.opf"),
                    "o.opf": _opf(
                        [("a", "a.xhtml", "application/xhtml+xml")],
                        ["a"],
                        extra=b'<opf:meta xmlns:opf="http://www.idpf.org/2007/opf" '
                        b'property="rendition:layout">Pre-Paginated</opf:meta>',
                    ),
                    "a.xhtml": _XHTML,
                },
            )
        )
        assert book.doc_paths == ["a.xhtml"]  # 放行照翻（定性留裁决）

    def test_member_path_unquote_first(self, tmp_path: Path) -> None:
        """``a%20b.xhtml`` href → 命中成员 ``a b.xhtml``（decode 优先序）。"""
        book = load_epub(
            _wzip(
                tmp_path / "pct.epub",
                {
                    _CONTAINER: _container("o.opf"),
                    "o.opf": _opf(
                        [("a", "a%20b.xhtml", "application/xhtml+xml")], ["a"]
                    ),
                    "a b.xhtml": _XHTML,
                },
            )
        )
        assert book.doc_paths == ["a b.xhtml"]

    def test_member_path_literal_pct_fallback(self, tmp_path: Path) -> None:
        """字面 ``%20`` 成员名 → unquote 缺席再试原样（畸形产物宽容）。"""
        book = load_epub(
            _wzip(
                tmp_path / "pctl.epub",
                {
                    _CONTAINER: _container("o.opf"),
                    "o.opf": _opf(
                        [("a", "a%20b.xhtml", "application/xhtml+xml")], ["a"]
                    ),
                    "a%20b.xhtml": _XHTML,
                },
            )
        )
        assert book.doc_paths == ["a%20b.xhtml"]

    def test_spine_bad_idref_manifest_tail(self, tmp_path: Path) -> None:
        """spine 引不存在 idref → 跳过；manifest 尾 xhtml 兜底进 doc_paths。"""
        book = load_epub(
            _wzip(
                tmp_path / "bi.epub",
                {
                    _CONTAINER: _container("o.opf"),
                    "o.opf": _opf([("a", "a.xhtml", "application/xhtml+xml")], ["zzz"]),
                    "a.xhtml": _XHTML,
                },
            )
        )
        assert book.doc_paths == ["a.xhtml"]

    def test_dup_member_first_wins(self, tmp_path: Path) -> None:
        """zip 重名成员首个胜出（infolist 序判定）。"""
        p = tmp_path / "dup.epub"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr(_CONTAINER, _container("o.opf"))
            z.writestr(
                "o.opf", _opf([("a", "a.xhtml", "application/xhtml+xml")], ["a"])
            )
            z.writestr("a.xhtml", b"<bad/>")
            z.writestr("a.xhtml", _XHTML)
        book = load_epub(p)
        assert book.members["a.xhtml"] == b"<bad/>"

    def test_dotdot_member_accepted(self, tmp_path: Path) -> None:
        """观察钉：``../evil`` 成员名原样收进 members（E2 出包侧已钉）。"""
        book = load_epub(
            _wzip(
                tmp_path / "dd.epub",
                {
                    _CONTAINER: _container("o.opf"),
                    "o.opf": _opf([("a", "a.xhtml", "application/xhtml+xml")], ["a"]),
                    "a.xhtml": _XHTML,
                    "../evil": b"E",
                },
            )
        )
        assert book.members["../evil"] == b"E"

    def test_nul_src_path_export_error(self, tmp_path: Path) -> None:
        """E0 衍生面：NUL 源路径 → ``ExportError`` 族，``ValueError`` 不裸逃。"""
        with pytest.raises(ExportError):
            load_epub(tmp_path / "a\x00b.epub")

    def test_nul_path_sniff_none(self, tmp_path: Path) -> None:
        """E0 同族面：``sniff_format`` 对 NUL 路径归 ``None``（无法识别）。"""
        assert sniff_format(tmp_path / "a\x00b.epub") is None

    def test_fuzz_member_sets_never_non_export_error(self, tmp_path: Path) -> None:
        """随机成员集+container 形态 → 逃逸型恒 ExportError 或 EpubBook。"""
        rng = fuzz_rng(_SEED_LOAD)
        cont_soup = [
            _container("o.opf"),
            _container(None),
            b"<<<",
            b"",
            _container("missing.opf"),
            _container(""),
        ]
        extra_names = ["a.xhtml", "o.opf", "META-INF/rights.xml", "big.bin", ""]
        for i in range(150):
            members: dict[str, bytes] = {}
            if rng.random() < 0.8:  # noqa: PLR2004
                members[_CONTAINER] = soup_pick(rng, cont_soup)
            for _ in range(rng.randint(0, 4)):
                members[soup_pick(rng, extra_names)] = (
                    _opf([("a", "a.xhtml", "application/xhtml+xml")], ["a"])
                    if rng.random() < 0.3  # noqa: PLR2004
                    else _XHTML
                )
            try:
                book = load_epub(_wzip(tmp_path / f"m{i}.epub", members))
            except ExportError:
                continue
            # 返回即自洽：doc_paths 非空且 ⊆ members
            assert book.doc_paths
            assert all(p in book.members for p in book.doc_paths)


# ---------------------------------------------------------------- save_epub


class TestSaveEpub:
    """``save_epub`` OCF 约束 + 敌意成员名面。"""

    def _names_of(self, path: Path) -> list[tuple[str, int]]:
        with zipfile.ZipFile(path) as z:
            return [(i.filename, i.compress_type) for i in z.infolist()]

    def test_mimetype_constraints(self, tmp_path: Path) -> None:
        """OCF：mimetype 首条 ZIP_STORED 且内容规范；其余 DEFLATED。"""
        book = _book({"a.xhtml": _XHTML, "OEBPS/o.opf": b"<p/>"})
        dst = tmp_path / "o.epub"
        save_epub(dst, book)
        infos = self._names_of(dst)
        assert infos[0] == ("mimetype", zipfile.ZIP_STORED)
        assert all(c == zipfile.ZIP_DEFLATED for _, c in infos[1:])
        with zipfile.ZipFile(dst) as z:
            assert z.read("mimetype") == b"application/epub+zip"

    def test_input_bad_mimetype_overwritten(self, tmp_path: Path) -> None:
        """输入坏 mimetype → 出包写规范值（不是照抄）。"""
        book = _book({"mimetype": b"garbage", "a.xhtml": _XHTML})
        dst = tmp_path / "m.epub"
        save_epub(dst, book)
        with zipfile.ZipFile(dst) as z:
            assert z.namelist().count("mimetype") == 1
            assert z.read("mimetype") == b"application/epub+zip"

    def test_nul_member_name_rejected(self, tmp_path: Path) -> None:
        """E1 已修：NUL 名显式拒绝——``zipfile`` 读写两侧都在 NUL 截断，
        「逐字节保留」不可实现，``ExportError`` 是唯一诚实契约。"""
        book = _book({"a\x00evil": b"EVIL", "a": b"REAL"})
        dst = tmp_path / "nul.epub"
        with pytest.raises(ExportError, match="成员名"):
            save_epub(dst, book)
        assert not dst.exists()  # 先于建包拒绝——不留半截包

    @pytest.mark.parametrize(
        "bad",
        [
            "../evil",
            "a/../b",
            "..",
            ".. ",
            "...",
            "/abs/name",
            "a\x01b",
            "a\\b",
            "C:/x",
            "",
        ],
        ids=[
            "dotdot",
            "mid_dotdot",
            "bare_dotdot",
            "dotdot_space",
            "dots3",
            "abs",
            "ctrl",
            "backslash",
            "drive",
            "empty",
        ],
    )
    def test_hostile_member_names_rejected(self, tmp_path: Path, bad: str) -> None:
        """E2 已修：``..`` 段（含 Windows 归一化变体）/绝对形/控制字符/
        ``\\``/``X:``/空名全拒。"""
        book = _book({bad: b"E", "ok": b"o"})
        dst = tmp_path / "h.epub"
        with pytest.raises(ExportError, match="成员名"):
            save_epub(dst, book)
        assert not dst.exists()

    def test_space_only_name_still_verbatim(self, tmp_path: Path) -> None:
        """观察钉（E2 修复后口径）：``"  "`` 非敌意形态仍原样进出包——
        门禁只拦遍历/绝对/控制字符，不替 OCF 做美学审查。"""
        dst = tmp_path / "v.epub"
        save_epub(dst, _book({"  ": b"S", "ok": b"o"}))
        with zipfile.ZipFile(dst) as z:
            assert "  " in z.namelist()
            assert "ok" in z.namelist()

    def test_order_members_desync_keyerror(self, tmp_path: Path) -> None:
        """观察钉：order 含 members 缺席名 → 裸 ``KeyError``（内部不变量面）。"""
        book = _book({"a": b"x"}, order=["ghost", "a"])
        with pytest.raises(KeyError):
            save_epub(tmp_path / "d.epub", book)

    def test_order_governs_sequence(self, tmp_path: Path) -> None:
        """order 序优先于 members 迭代序；缺席 order 的成员追在尾。"""
        book = _book({"a": b"1", "b": b"2", "c": b"3"}, order=["c", "a"])
        dst = tmp_path / "ord.epub"
        save_epub(dst, book)
        assert [n for n, _ in self._names_of(dst)] == ["mimetype", "c", "a", "b"]

    def test_fuzz_member_names_roundtrip(self, tmp_path: Path) -> None:
        """随机成员名汤 → save_epub 不抛 + 出包 mimetype 约束 + 确定性。"""
        rng = fuzz_rng(_SEED_MEMBER)
        name_soup = [
            "a",
            "b.xhtml",
            "dir/",
            "OEBPS/x",
            " ",
            ".",
            "..",
            "z" * 100,
            "é",
            "中",
            "-",
            "_",
        ]
        for i in range(150):
            members = dict.fromkeys(
                (soup_join(rng, name_soup, 1, 4) for _ in range(rng.randint(1, 6))),
                b"blob",
            )
            dst = tmp_path / f"f{i}.epub"

            def roundtrip(
                dst: Path = dst, members: dict[str, bytes] = members
            ) -> tuple:  # B023 默认参绑循环变量
                save_epub(dst, _book(members))
                with zipfile.ZipFile(dst) as z:
                    return tuple((e.filename, z.read(e.filename)) for e in z.infolist())

            try:
                first = assert_deterministic(roundtrip)
            except ExportError:
                # 敌意名（如 ``..`` 段）走拒绝臂——拒绝也须确定：同输入同拒
                with pytest.raises(ExportError):
                    save_epub(dst, _book(members))
                continue
            assert first[0] == ("mimetype", b"application/epub+zip"), short(members)


# ---------------------------------------------------------------- coerce_glossary


class TestCoerceGlossary:
    """``coerce_glossary`` 边角——文件形 ExportError / 类型外 TypeError。"""

    def test_missing_and_dir_and_nul(self, tmp_path: Path) -> None:
        for bad in (tmp_path / "none.yaml", tmp_path, "a\x00b.yaml"):
            with pytest.raises(ExportError):
                coerce_glossary(bad)

    def test_fifo_not_file(self, tmp_path: Path) -> None:
        fifo = tmp_path / "fifo"
        fifo.unlink(missing_ok=True)
        import os  # noqa: PLC0415 -- 单点用

        os.mkfifo(fifo)
        with pytest.raises(ExportError):  # is_file() False → 拒读（不悬挂）
            coerce_glossary(fifo)

    def test_bad_yaml_wrapped(self, tmp_path: Path) -> None:
        p = tmp_path / "b.yaml"
        p.write_text("[unclosed", encoding="utf-8")
        with pytest.raises(ExportError):
            coerce_glossary(p)

    def test_int_typeerror(self) -> None:
        """契约外类型 → ``TypeError``（非 ExportError——钉住防误读）。"""
        with pytest.raises(TypeError):
            coerce_glossary(42)  # type: ignore[arg-type]

    def test_mapping_str_coercion(self) -> None:
        """Mapping 键值 ``str()`` 归一——``None``→``"None"`` 进表（观察钉）。"""
        g = coerce_glossary({1: 2, None: None, " k ": "  "})
        assert g is not None
        assert g.terms["1"].zh == "2"
        assert g.terms["None"].zh == "None"
        assert g.terms["k"].zh == "k"  # 键 strip 收 "k"；全空白 zh 回落 en


# ---------------------------------------------------------------- marker_report


class TestMarkerReport:
    """``marker_report``——调和描述行；未覆盖面的直喂钉。"""

    @pytest.mark.parametrize(
        ("sent", "reply", "want_frag"),
        [
            ("s", "r", None),  # 无事 → None
            ("s [[A_1]]", "r", "missing"),  # 签发丢失
            ("s [[A_1]]", "r [[A_1]]", None),  # 一致 → None
            ("s", "r [[A_9]]", "invented"),  # 臆造
            ("s [[A_1]]", "r [[A_1]] [[B_2]]", "invented"),
            ("s", None, None),  # None 回复不炸
        ],
    )
    def test_pin_table(
        self, sent: str, reply: str | None, want_frag: str | None
    ) -> None:
        out = marker_report("u1", sent, reply)
        if want_frag is None:
            assert out is None
        else:
            assert out is not None
            assert want_frag in out
            assert out.startswith("u1:")

    def test_issued_dict_iterates_keys(self) -> None:
        """观察钉：issued 传 dict → 迭代键当 token（鸭子型）→ 误报 missing。"""
        out = marker_report("u", "s", "r", issued={"k": 1})
        assert out is not None
        assert "missing" in out
        assert "k" in out

    @pytest.mark.parametrize(
        ("sent", "reply"),
        [(5, "r"), ("s", b"r")],
        ids=["int_sent", "bytes_reply"],
    )
    def test_non_str_typeerror(self, sent: object, reply: object) -> None:
        """非-str sent/reply → ``TypeError`` 裸逃（调用方契约钉）。"""
        with pytest.raises(TypeError):
            marker_report("u", sent, reply)  # type: ignore[arg-type]

    def test_none_sent_tolerated(self) -> None:
        """观察钉：``sent=None`` 经 ``find_markers(str|None)`` 容忍返 None。"""
        assert marker_report("u", None, "r") is None  # type: ignore[arg-type]


# ---------------------------------------------------------------- drive_pipeline


class _BoomTranslator:
    """永抛 translator——管线内部降级面。

    签名须与 ``Translator`` 协议一致（kw-only，``_TripTranslator`` 注同款
    坑）——``translate(self, req)`` 形桩会让 ``TypeError`` 先于
    ``RuntimeError`` 爆出，钉的是契约违反而非调用内失败臂。
    """

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        del system, user, temperature, max_tokens, response_format
        msg = "translator boom"
        raise RuntimeError(msg)


class _TripTranslator:
    """``user`` 含 ``TRIPBASE`` 抛 ``exc``，余委托 MockTranslator——E3 钉用。

    签名必须与 ``Translator`` 协议一致（kw-only）——``translate(self, req)``
    形桩会让 ``TypeError`` 先于 ``exc`` 爆出，走 Exception 降级面钉个寂寞。
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self._mock = MockTranslator()

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        if "TRIPBASE" in user:
            raise self._exc
        return await self._mock.translate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )


class TestDrivePipeline:
    """``drive_pipeline`` 失败路径与半成品回放。"""

    def _store(self, tmp_path: Path, name: str) -> StateStore:
        return StateStore(tmp_path / name, model="m", pipeline_version="v")

    def test_empty_chunks(self, tmp_path: Path) -> None:
        results, counts = drive_pipeline(
            [],
            translator=MockTranslator(),
            store=self._store(tmp_path, "e"),
            glossary=None,
            on_result=None,
            apply_fn=lambda r: ApplyCounts(translated=len(r)),
            save_fn=lambda _n: None,
        )
        assert results == {}
        assert counts.translated == 0

    def test_dup_chunk_id_last_wins(self, tmp_path: Path) -> None:
        """观察钉：重复 ``chunk_id`` 后写胜——apply 只见去重表。"""
        chunks = [
            ChunkIn(chunk_id="dup", content="first words here ok", kind="para"),
            ChunkIn(chunk_id="dup", content="second words here ok", kind="para"),
            ChunkIn(chunk_id="solo", content="third words here ok", kind="para"),
        ]
        seen: list[dict] = []
        results, _ = drive_pipeline(
            chunks,
            translator=MockTranslator(),
            store=self._store(tmp_path, "d"),
            glossary=None,
            on_result=None,
            apply_fn=lambda r: (seen.append(dict(r)), ApplyCounts(translated=len(r)))[
                1
            ],
            save_fn=lambda _n: None,
        )
        assert len(results) == 2  # noqa: PLR2004 -- 3 chunks → 2 unique ids
        assert results["dup"].source == "second words here ok"

    def test_apply_raise_propagates_no_partial(self, tmp_path: Path) -> None:
        """apply_fn 抛 → 原样传播（回放路径只罩 asyncio.run 段）。"""
        saves: list[int] = []

        def boom(_r: object) -> ApplyCounts:
            msg = "apply boom"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="apply boom"):
            drive_pipeline(
                [ChunkIn(chunk_id="c", content="para words here ok", kind="para")],
                translator=MockTranslator(),
                store=self._store(tmp_path, "a"),
                glossary=None,
                on_result=None,
                apply_fn=boom,
                save_fn=saves.append,
            )
        assert saves == []  # apply 抛在回放保护外 → save 未被调

    def test_save_raise_propagates(self, tmp_path: Path) -> None:
        """save_fn 抛 → apply 已算后原样传播。"""
        applied: list[int] = []

        def boom_save(_n: int) -> None:
            msg = "save boom"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="save boom"):
            drive_pipeline(
                [ChunkIn(chunk_id="c", content="para words here ok", kind="para")],
                translator=MockTranslator(),
                store=self._store(tmp_path, "s"),
                glossary=None,
                on_result=None,
                apply_fn=lambda r: (
                    applied.append(len(r)),
                    ApplyCounts(translated=len(r)),
                )[1],
                save_fn=boom_save,
            )
        assert applied == [1]

    def test_translator_boom_degrades_internally(self, tmp_path: Path) -> None:
        """translator 永抛 → 管线降级完成（返回结果存在，不裸逃）。"""
        results, _counts = drive_pipeline(
            [ChunkIn(chunk_id="c", content="para words here ok", kind="para")],
            translator=_BoomTranslator(),
            store=self._store(tmp_path, "b"),
            glossary=None,
            on_result=None,
            apply_fn=lambda r: ApplyCounts(translated=len(r)),
            save_fn=lambda _n: None,
        )
        assert "c" in results

    @pytest.mark.parametrize(
        "exc",
        [KeyboardInterrupt(), SystemExit(3), GeneratorExit()],
        ids=["KeyboardInterrupt", "SystemExit", "GeneratorExit"],
    )
    def test_translate_baseexception_propagates(
        self, tmp_path: Path, exc: BaseException
    ) -> None:
        """契约钉：translate 内抛的 BaseException 穿透 drive_pipeline。

        E3 回归钉。12 块各异 kind → 各成 ``("single", …)`` 工作项 >
        默认 conc=10：warmup 消化首项后 worker 吃到 ``TRIPBASE`` 块挂
        ``fatal``，此刻队列剩余项多于存活 worker——「worker 带
        BaseException 死亡（sentinel 孤儿）」与「fatal 后吃一条即退
        （剩余项无人 task_done）」两种 join 死锁形都被罩住；修复后
        worker 只吃不做排空到 sentinel、``_drain`` 在 join 收敛后重抛。
        """
        prose = "word " * 80
        chunks = [
            ChunkIn(
                chunk_id=f"c{i}",
                content=prose + ("TRIPBASE" if i == 1 else ""),
                kind=f"k{i}",  # 异 kind 分组装箱——每块一个 single 工作项
            )
            for i in range(12)  # 工作项数须 > 默认 conc=10 才钉得住 drain 语义
        ]
        with pytest.raises(type(exc)):
            drive_pipeline(
                chunks,
                translator=_TripTranslator(exc),
                store=self._store(tmp_path, "x"),
                glossary=None,
                on_result=None,
                apply_fn=lambda r: ApplyCounts(translated=len(r)),
                save_fn=lambda _n: None,
            )

    def test_worker_baseexception_drains_queue(self) -> None:
        """E3 形态钉：``fatal`` 挂起后 worker 排空队列而非退场。

        conc=2 + 6 工作项——fatal 时剩余项 > 存活 worker 数：若 fatal
        后吃一条即退，残余项 ``task_done`` 无人发 → ``queue.join()``
        死锁、重抛永远到不了。直钉 ``XlatPipeline`` 层（``drive_pipeline``
        的 concurrency 不可配）。
        """
        prose = "word " * 80
        chunks = [
            ChunkIn(
                chunk_id=f"c{i}",
                content=prose + ("TRIPBASE" if i == 1 else ""),
                kind="para",
            )
            for i in range(6)
        ]
        pipe = XlatPipeline(
            _TripTranslator(GeneratorExit()),
            config=PipelineConfig(concurrency=2, batch_max_items=1),
        )
        with pytest.raises(GeneratorExit):
            asyncio.run(pipe.run(chunks))

    def test_dirty_store_tolerated_on_replay(self, tmp_path: Path) -> None:
        """脏态 ``chunks.jsonl`` → ``store.load()`` 回放面优雅空集。"""
        sdir = tmp_path / "dirty"
        sdir.mkdir()
        (sdir / "chunks.jsonl").write_bytes(b"\x00\x01 not json \xff\xfe\n")
        store = StateStore(sdir, model="m", pipeline_version="v")
        done, recs = store.load()
        assert done == set()
        assert recs == {}

    def test_pipeline_raise_replays_partial_then_reraises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``asyncio.run`` 段抛 → 回放已存译文 apply+save 后再抛（半成品语义）。

        translator 层异常被 ``XlatPipeline`` 内部降级吃掉——回放路径只在
        ``pipe.run`` 整体抛时触发，故直接 monkeypatch ``run`` 直控。
        """
        store = self._store(tmp_path, "r")
        drive_pipeline(
            [ChunkIn(chunk_id="c", content="para words here ok", kind="para")],
            translator=MockTranslator(),
            store=store,
            glossary=None,
            on_result=None,
            apply_fn=lambda r: ApplyCounts(translated=len(r)),
            save_fn=lambda _n: None,
        )

        async def boom_run(self: object, chunks: object) -> object:  # noqa: ARG001
            msg = "pipe-run-boom"
            raise RuntimeError(msg)

        monkeypatch.setattr(XlatPipeline, "run", boom_run)
        replayed: list[set[str]] = []
        saved: list[int] = []

        with pytest.raises(RuntimeError, match="pipe-run-boom"):
            drive_pipeline(
                [ChunkIn(chunk_id="c2", content="new para words here ok", kind="para")],
                translator=MockTranslator(),
                store=store,
                glossary=None,
                on_result=None,
                apply_fn=lambda r: (
                    replayed.append(set(r)),
                    ApplyCounts(translated=len(r)),
                )[1],
                save_fn=saved.append,
            )
        assert replayed == [{"c"}]  # 回放上一轮落盘的 c（c2 无译文不回放）
        assert saved == [1]


# ---------------------------------------------------------------- insert_after 敌意 language


class TestInsertAfterLang:
    """``insert_after`` 敌意 ``language``/``zh_text`` 钉（docx 臂）。"""

    @pytest.fixture
    def src_el(self):  # noqa: ANN201 -- fixture 返回 lxml 元素
        from docx import Document  # noqa: PLC0415 -- docx 重依赖延迟

        doc = Document()
        return doc.add_paragraph("Source para words here.")._p  # noqa: SLF001 -- 公开测试面即 oxmlel

    @pytest.mark.parametrize("lang", ["zh\x01", "zh\x00"], ids=["ctrl", "nul"])
    def test_hostile_language_valueerror(self, src_el: object, lang: str) -> None:
        """ctrl/NUL language → ``ValueError``（lxml XML 合法门禁，调用方契约）。"""
        with pytest.raises(ValueError, match="XML compatible"):
            insert_after(src_el, "译文", lang)

    @pytest.mark.parametrize("lang", ['zh" onclick="x', ""], ids=["quote", "empty"])
    def test_quote_empty_language_tolerated(self, src_el: object, lang: str) -> None:
        """观察钉：引号/空串 language 安静进 ``xml:lang``（序列化层转义）。"""
        insert_after(src_el, "译文", lang)
        assert src_el.getnext() is not None

    @pytest.mark.parametrize(
        "zh",
        ["a\x00b", "a\x01\x02b", "a\ud800b", "", "译" * 5000, "<b>&lt;x&gt;</b>"],
        ids=["nul", "ctrl", "surrogate", "empty", "huge", "xmlish"],
    )
    def test_hostile_zh_sanitized(self, src_el: object, zh: str) -> None:
        """敌意 zh → sanitize 剥除后插入；输出 part XML 仍合法。"""
        from lxml import etree  # noqa: PLC0415

        insert_after(src_el, zh, "zh-CN")
        nxt = src_el.getnext()
        assert nxt is not None
        etree.fromstring(etree.tostring(nxt))  # 输出仍 well-formed
        txt = "".join(nxt.itertext())
        assert "\x00" not in txt
        assert "\x01" not in txt
