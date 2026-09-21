"""share 公共件——篡改包构造器 ``repack``、manifest 读出 ``bundle_manifest``、
双 app 脚手架 ``mk_share_apps`` 与 canonical ``key_parts`` 骨架 ``share_parts``。

- ``repack``/``bundle_manifest``：从 ``test_share``/``test_fuzz_share`` 抽取的
  字节级共享件——两文件的 ``_repack`` 实现逐字节一致（zip 直写
  ``MANIFEST_NAME`` + payloads 成员循环），``bundle_manifest`` 即
  ``test_share._bundle_manifest``（读包内 manifest.json）。
- ``mk_share_apps``/``share_parts``：从 ``test_share_apply`` 上提——生产/消费
  双 app（独立 data_dir + SourceCache + 各自 FakeFetcher 载荷）与
  ``key_parts`` 骨架（PROMPT/PIPELINE 版本常量单点化），
  ``test_share_wire``/``test_share_cli`` 共用。

配套的「读产物成员」助手刻意缺席——``test_share._payloads`` 按固定
``ARTIFACT_NAMES`` 迭代（partial 包缺 zh.pdf 会 KeyError），而
``test_fuzz_share._base_bundle`` 按 ``zf.namelist()`` 驱动——两者口径不同，
不统一上提。
"""

from __future__ import annotations

import json
import zipfile
from typing import TYPE_CHECKING

from conftest import MINI_TEX, FakeEngine, FakeFetcher, make_app, make_targz

from texlate.arxiv.cache import SourceCache
from texlate.server.worker import PIPELINE_VERSION
from texlate.share import MANIFEST_NAME
from texlate.xlat.pipeline import MockTranslator
from texlate.xlat.prompts import PROMPT_VERSION

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from fastapi import FastAPI


def repack(
    out: Path, manifest: Mapping[str, object], payloads: Mapping[str, bytes]
) -> Path:
    """按给定 manifest/payload 直写 bundle——篡改用例的构造器（不走 pack_share）。"""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False))
        for name, blob in payloads.items():
            zf.writestr(name, blob)
    return out


def bundle_manifest(bundle: Path) -> dict[str, object]:
    """读出包内 manifest.json。"""
    with zipfile.ZipFile(bundle) as zf:
        doc = json.loads(zf.read(MANIFEST_NAME))
    assert isinstance(doc, dict)
    return doc


def mk_share_apps(
    tmp_path: Path,
    *,
    cons_mock: MockTranslator | None = None,
    cons_engine: object | None = None,
    prod_tex: str = MINI_TEX,
    cons_tex: str = MINI_TEX,
) -> tuple[FastAPI, FastAPI, Path, Path]:
    """生产/消费双 app——独立 data_dir + SourceCache，各自 FakeFetcher 载荷。

    ``cons_mock``/``cons_engine`` 覆盖消费端 translator/engine 实例；
    ``prod_tex``/``cons_tex`` 换两侧 ``main.tex`` 供源。返回
    ``(prod, cons, prod_data_dir, cons_data_dir)``。
    """
    prod_engine = FakeEngine()
    cons_eng = cons_engine or FakeEngine()
    prod = make_app(
        tmp_path / "pa",
        start_worker=True,
        translator_factory=lambda _ctx: MockTranslator(),
        engine_factory=lambda _name: prod_engine,
        fetcher=FakeFetcher(make_targz({"main.tex": prod_tex})),
        source_cache=SourceCache(tmp_path / "pa" / "src-cache"),
    )
    imp = make_app(
        tmp_path / "pb",
        start_worker=True,
        translator_factory=lambda _ctx: cons_mock or MockTranslator(),
        engine_factory=lambda _name: cons_eng,
        fetcher=FakeFetcher(make_targz({"main.tex": cons_tex})),
        source_cache=SourceCache(tmp_path / "pb" / "src-cache"),
    )
    return prod, imp, tmp_path / "pa" / "data", tmp_path / "pb" / "data"


def share_parts(
    *,
    arxiv_id: str,
    version: str,
    model: str,
    target_lang: str,
    front_matter: str = "abstract,title",
) -> dict[str, str]:
    """canonical ``key_parts`` 骨架——PROMPT/PIPELINE 版本常量单点化。

    ``front_matter`` 传 falsy 时省键（∅ 集口径，对齐 ``_key_parts`` 的
    ``parts.get("front_matter") or ""`` 缺省路径）；调用侧再
    ``parts.update(overrides)`` 打覆盖。
    """
    parts = {
        "arxiv_id": arxiv_id,
        "version": version,
        "model": model,
        "prompt_ver": PROMPT_VERSION,
        "target_lang": target_lang,
        "glossary_hash": "",
        "pipeline_ver": PIPELINE_VERSION,
    }
    if front_matter:
        parts["front_matter"] = front_matter
    return parts
