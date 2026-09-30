"""export 包共享件：错误族 + 统一报告 + ``glossary`` 入参归一 + 双驱骨架。"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import yaml

from texlate.export.markers import reconcile_markers
from texlate.xlat.glossary import Glossary, TermEntry
from texlate.xlat.pipeline import ChunkIn, ChunkResult, XlatPipeline
from texlate.xlat.placeholders import diff as _ph_diff
from texlate.xlat.state import StateStore

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from texlate.xlat.pipeline import Translator

log = logging.getLogger(__name__)


class ExportError(Exception):
    """导出管线基错。"""


class UnsupportedFormatError(ExportError):
    """输入不是可识别的 epub/docx。"""


class DrmError(ExportError):
    """EPUB 声明了技术保护措施（``rights.check_epub`` 判定）。"""


class FixedLayoutError(ExportError):
    """``rendition:layout=pre-paginated`` 的书插译必破版式——检测后拒翻。"""


class MalformedEpubError(ExportError):
    """zip/container/OPF 结构不合法。"""


@dataclass
class ExportReport:
    """EPUB/DOCX 导出统一报告。

    ``units`` = 送编排层的单元数（占位/纯装饰段不列入）；``translated`` =
    实际插译段数；``unchanged`` = 译文逐字同原文（echo/回退，不重复插入）；
    ``skipped``/``fault`` = 编排层三振回退原文/真失败。
    """

    src: Path
    dst: Path
    format: str
    units: int
    translated: int
    unchanged: int
    skipped: int
    fault: int
    documents: int
    warnings: list[str] = field(default_factory=list)


#: ``export_*``/``translate_*`` 的 ``glossary`` 入参并集——归一处 ``coerce_glossary``。
GlossaryArg = Glossary | Mapping[str, str] | str | Path

#: ``target_lang`` 写回面的白名单形态（BCP47 子集）。``_restamp_opf`` 是正则
#: 文本替换——不校验会把 ``zh<x="1">`` 这类值原样写进 OPF 造成 XML 注入。
_LANG_SAFE_RE = re.compile(r"[\w-]+")


def safe_language(language: str | None) -> str | None:
    """``target_lang`` → 可安全写入 XML 的语言码；非 BCP47 形态返回 ``None``。

    ``None`` 语义 = 不写任何语言章/语言元素——比把畸形值塞进 OPF 再把
    整本书变成非法 XML 诚实得多。
    """
    return language if language and _LANG_SAFE_RE.fullmatch(language) else None


def coerce_glossary(glossary: GlossaryArg | None) -> Glossary | None:
    """``glossary`` 便利入参 → ``Glossary | None``（``XlatPipeline`` 契约形）。

    - ``None``/``Glossary`` → 原样（``None`` = 无术语层，行为同旧版）；
    - ``Mapping`` → 逐条成 ``user`` 层 ``TermEntry``——内存输入不隐式叠
      文件层（``~/.texlate/glossary.yaml``/``default.csv`` 不混入），空 zh
      同文件层语义落保原语；
    - ``str``/``Path`` → ``Glossary.load(user_path=…)``——与 tex 主链
      ``worker._make_glossary`` 同形（user 表叠内建 default 层；``~`` 展开）；
    - 路径缺席/不可读/格式非法 → ``ExportError``：``Glossary.load`` 对缺席
      ``user_path`` 静默跳过（分层 API 语义），公开入口先验存在——
      否则用户表又是静默丢弃。
    """
    if glossary is None or isinstance(glossary, Glossary):
        return glossary
    if isinstance(glossary, Mapping):
        return Glossary(
            terms={
                en: TermEntry(en, str(zh).strip() or en, "user")
                for k, zh in glossary.items()
                if (en := str(k).strip())
            }
        )
    path = Path(glossary).expanduser()
    if not path.is_file():
        msg = f"glossary 文件不可读: {path}"
        raise ExportError(msg)
    try:
        return Glossary.load(user_path=path)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as e:
        msg = f"glossary 加载失败: {path} ({e})"
        raise ExportError(msg) from e


# ---------------------------------------------------------------- 双驱骨架


@dataclass
class ApplyCounts:
    """``apply_fn`` 计数包：插译成功/逐字同原文/真失败 + 插译警告。"""

    translated: int = 0
    unchanged: int = 0
    fault: int = 0
    warnings: list[str] = field(default_factory=list)


#: 批量 ``[n]`` 协议的退化残留：回复只剩序号桩 = 实质空译。
#: ``parse_batch_response`` 序号路径会把裸 ``[1]``（单块批的"空槽"回复）
#: 原样当译文留下——插出去是根号渣，按空译判 unchanged。
STUB_ONLY_RE = re.compile(r"\s*(?:\[\d+\]\s*)+")


class _ApplyUnit(Protocol):
    """``apply_translations`` 对单元的最低面：结果键 ``job_id`` + echo 比对 ``text``。"""

    job_id: str
    text: str


def _all_units(_unit: _ApplyUnit) -> bool:
    return True


def apply_translations[U: _ApplyUnit](
    units: Iterable[U],
    results: Mapping[str, ChunkResult],
    *,
    preview_zh: Callable[[U, ChunkResult], str],
    insert: Callable[[U, ChunkResult, str], str | None],
    counts_unchanged: Callable[[U], bool] = _all_units,
) -> ApplyCounts:
    """``_apply`` 公共骨架——EPUB/DOCX 两臂的回放 - 预判 - 插译 - 计数全同构。

    差异三点经参数面注入：

    - ``preview_zh``: 与各自 insert 同口径的"净化后译文"预判（DOCX 只
      ``sanitize_xml_text``；EPUB 先 ``reconcile_markers`` 再 sanitize）；
    - ``counts_unchanged``: 该单元是否参与 unchanged 预判——EPUB 的 ncx
      单元无条件写回故除外；缺省全参与；
    - ``insert``: 真插译，收 preview 已净化的 ``zh`` 免双算，返回警告行
      （无警告 ``None``——DOCX ``insert_after`` 本无返回，lambda 包一层即
      ``None``）。

    unchanged 三判据（空译/纯 ``[n]`` 序号桩/echo 原文）与两侧 insert 内部
    的跳过判据同口径：预判不过即不会真插，计 ``unchanged``——插了也只是
    无字空壳段，``translated`` 计数不变量会破。
    """
    counts = ApplyCounts()
    for u in units:
        r = results.get(u.job_id)
        if r is None:
            continue
        if r.status in ("skipped", "fault"):
            if r.status == "fault":
                counts.fault += 1
            continue
        zh = preview_zh(u, r)
        if counts_unchanged(u) and (
            not zh.strip() or STUB_ONLY_RE.fullmatch(zh) or zh.strip() == u.text.strip()
        ):
            counts.unchanged += 1
            continue
        warn = insert(u, r, zh)
        if warn:
            counts.warnings.append(warn)
        counts.translated += 1
    return counts


def _export_validator(src: str, zh: str) -> str:
    """``XlatPipeline`` 校验臂的 export 变体：marker 差异先调和再对账。

    EPUB 单元签发的 ``[[TAG_n]]`` marker 由 ``reconcile_markers`` 宽容调和
    （markers.py pinned 规则：绝不因 marker 重试——丢的句尾补回、臆造剥掉）。
    默认 ``diff`` 直判会把丢/臆造 marker 当校验失败，白烧阶梯重试、三振后
    整段回退原文。``issued=None`` 调和把 sent 内全部 marker 形 token 视同
    签发（含书内字面同形 token——单现的丢字不再追责，多重集差仍抓），diff
    随之对 marker 差异免疫；非 marker 校验口径与默认件一致。
    """
    return _ph_diff(src, reconcile_markers(src, zh)).describe()


def drive_pipeline(  # noqa: PLR0913 -- 骨架即双驱共享参数面（chunks/翻译/断点/回调/apply/save 七件）
    chunks: list[ChunkIn],
    *,
    translator: Translator,
    store: StateStore,
    glossary: GlossaryArg | None,
    on_result: Callable[[ChunkResult], None] | None,
    apply_fn: Callable[[Mapping[str, ChunkResult]], ApplyCounts],
    save_fn: Callable[[int], None],
) -> tuple[dict[str, ChunkResult], ApplyCounts]:
    """``XlatPipeline`` 全编排 + 半成品落盘——EPUB/DOCX 两驱动共用骨架。

    ``apply_fn`` 把结果表插进文档模型返回计数；``save_fn`` 按插译成功数出包。
    Ctrl-C/异常按 ``store`` 已落盘译文回放 apply+save 后再抛（bbm
    ``_save_temp_book`` 语义——半成品双语件总比没有强）。返回
    ``(结果表，计数)`` 供调用方组 ``ExportReport``。
    """
    g = coerce_glossary(glossary)
    pipe = XlatPipeline(
        translator,
        state=store,
        glossary=g,
        validator=_export_validator,
        on_result=on_result,
    )

    async def _run() -> list[ChunkResult]:
        try:
            return await pipe.run(chunks)
        finally:
            # loop 绑定 client（worker._PerCallTranslator）的回收——
            # aclose 须在本 ephemeral loop 存活时于其内 await
            aclose = getattr(translator, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    log.debug("translator aclose failed", exc_info=True)

    try:
        results = {r.chunk_id: r for r in asyncio.run(_run())}
    except BaseException:
        _completed, recs = store.load()
        partial = {cid: ChunkResult.from_record(rec) for cid, rec in recs.items()}
        try:
            save_fn(apply_fn(partial).translated)
        except Exception as e:
            # salvage 失败给用户一行 warning 就够；traceback 细节留 DEBUG
            # （CLI stderr 面不再接受裸 traceback——_clean oracle 钉死）
            log.warning("partial export save failed: %s", e)
            log.debug("partial export save detail", exc_info=True)
        raise
    counts = apply_fn(results)
    save_fn(counts.translated)
    return results, counts


def run_export(  # noqa: PLR0913 -- 双驱共享参数面（drive_pipeline 先例）
    src: Path,
    dst: Path,
    translator: Translator,
    *,
    lang: str | None,  # noqa: ARG001 -- preamble 上收预留槽，与 EPUB 臂签名对齐（本尾不读）
    state_dir: Path | None,
    glossary: GlossaryArg | None,
    on_result: Callable[[ChunkResult], None] | None,
    chunks: list[ChunkIn],
    apply_fn: Callable[[Mapping[str, ChunkResult]], ApplyCounts],
    save_fn: Callable[[int], None],
    err_cls: type[ExportError],
    fmt: str,
    documents: int,
    pipeline_version: str,
) -> ExportReport:
    """枚举后段公共尾：``StateStore`` → ``drive_pipeline`` → 清理 → ``ExportReport``。

    DOCX/EPUB 两驱动的枚举后段逐行同构（``state_dir`` 缺省、嵌套护栏、
    state 清理、skipped 计数、报告装配）——``epub.driver.translate_epub``
    直接复用本件；``err_cls``/``fmt``/``documents`` 是仅存的差异
    参数面。``lang`` 属驱动侧闭包词法语境，本尾不读——签名留槽与 EPUB 臂
    对齐（preamble 上收变体的挂点）。
    """
    state_dir = state_dir or dst.with_name(dst.name + ".state")
    store = StateStore(state_dir, model="export", pipeline_version=pipeline_version)
    try:
        results, counts = drive_pipeline(
            chunks,
            translator=translator,
            store=store,
            glossary=glossary,
            on_result=on_result,
            apply_fn=apply_fn,
            save_fn=save_fn,
        )
    except RecursionError as e:
        # 超深 ``w:p`` 子树在 ``insert_after`` 的 deepcopy/序列化路径同样
        # 撞 RecursionError——折进 ExportError 族，裸内置异常不许逃逸
        msg = f"{fmt.upper()} 文档嵌套过深，无法翻译: {src.name}"
        raise err_cls(msg) from e

    if state_dir.exists():
        shutil.rmtree(state_dir, ignore_errors=True)
    n_skipped = sum(1 for r in results.values() if r.status == "skipped")
    return ExportReport(
        src=src,
        dst=dst,
        format=fmt,
        units=len(chunks),
        translated=counts.translated,
        unchanged=counts.unchanged,
        skipped=n_skipped,
        fault=counts.fault,
        documents=documents,
        warnings=counts.warnings,
    )
