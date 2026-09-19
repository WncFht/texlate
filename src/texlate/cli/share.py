"""``share pack/unpack`` 子命令簇：任务产物 ↔ ``.share.zip`` 社区共享包。"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from urllib.parse import quote

import typer

from texlate.arxiv.fetch import normalize_arxiv_id
from texlate.cli._common import _CLI_FILE, _CLI_PATH, _is_dir, _is_file, app
from texlate.server.store import row_json
from texlate.share import (
    KEY_PART_FIELDS,
    ShareError,
    glossary_content_hash,
    pack_share,
    unpack_share,
)
from texlate.textutil import data_root

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

share_app = typer.Typer(
    help="社区共享译文缓存包（设计 docs/research/product/shared-cache.md）。",
    no_args_is_help=True,
)
app.add_typer(share_app, name="share")


def _share_data_root(data_dir: Path | None) -> Path:
    """数据根：``--data-dir`` > ``TEXLATE_DATA_DIR`` > ``~/.texlate``。

    与 ``settings.data_dir()`` 同序但**不 mkdir**——pack 是只读定位，
    找不到库由调用方报错，不为查询副作用建目录。
    """
    if data_dir is not None:
        return data_dir.expanduser()
    return data_root()


def _share_task_dir(arg: str, data_dir: Path | None) -> Path:
    """Pack 参数分流：已存在目录直接用；``t_*`` 形按任务 id 到数据根 ``tasks/`` 下找。"""
    p = Path(arg).expanduser()
    if _is_dir(p):
        return p
    if arg.startswith("t_"):
        tasks_root = _share_data_root(data_dir) / "tasks"
        cand = tasks_root / arg
        # arg 是任务 id 定位键不是路径段——resolve 后必须落 tasks/ 直子级，
        # 否则 t_x/../../x 形态借 is_dir 解析穿出仓
        if _is_dir(cand) and cand.resolve().parent == tasks_root.resolve():
            return cand
        typer.echo(f"任务目录不存在: {cand}", err=True)
        raise typer.Exit(1)
    typer.echo(f"share pack: 既不是已存在目录也不像任务 id: {arg!r}", err=True)
    raise typer.Exit(1)


def _share_db(task_dir: Path, data_dir: Path | None) -> Path | None:
    """定位 ``texlate.db``：``--data-dir`` > 任务目录上跳（``tasks/t_*`` 形态）> 默认数据根。"""
    cands = [
        task_dir.parent.parent / "texlate.db",
        task_dir.parent / "texlate.db",
    ]
    if data_dir is not None:
        cands.insert(0, data_dir.expanduser() / "texlate.db")
    cands.append(_share_data_root(data_dir) / "texlate.db")
    for cand in cands:
        if _is_file(cand):
            return cand
    return None


def _share_row(db: Path, task_id: str) -> dict[str, Any] | None:
    """只读开库取任务行——不走 ``Store.open()``（它有 DDL/迁移写副作用）。

    库文件在场但非 sqlite/缺 tasks 表 → ``sqlite3.Error`` 归一干净报错
    （不抛 traceback）。
    """
    try:
        conn = sqlite3.connect(f"file:{quote(str(db), safe='/')}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        typer.echo(f"任务库不可读 {db}: {e}", err=True)
        raise typer.Exit(1) from None
    return dict(row) if row is not None else None


def _share_fields(row: Mapping[str, Any]) -> tuple[str, int | None, str, str]:
    """任务行 → ``(arxiv_base, resolved_ver, model, target_lang)``；取不到显式报错。"""
    status = str(row.get("status") or "")
    if status not in ("done", "partial"):
        typer.echo(f"任务状态 {status!r} 不可打包（需 done|partial）", err=True)
        raise typer.Exit(1)
    raw_id = str(row.get("arxiv_id") or "")
    if not raw_id:
        typer.echo("任务行无 arxiv_id（upload/文档任务不参与共享寻址）", err=True)
        raise typer.Exit(1)
    base, ver = normalize_arxiv_id(raw_id)
    model = str(row.get("model") or "")
    lang = str(row.get("target_lang") or "")
    if not model or not lang:
        typer.echo("任务行 model/target_lang 为空，无法派生 share key", err=True)
        raise typer.Exit(1)
    return base, ver, model, lang


def _share_verify_pipeline(  # noqa: PLR0913, PLR0917 -- 键材料组与 manifest 同面
    row: Mapping[str, Any],
    base: str,
    ver: int | None,
    model: str,
    lang: str,
    options: Mapping[str, Any],
) -> None:
    """``cache_key`` 重算交叉验证——证明产物确实出自当前 ``PIPELINE_VERSION``。

    任务行 ``arxiv_id`` 存的是 resolved 钉版，而 ``cache_key_for`` 进键的是
    **请求时**版本（钉版请求 → ver、latest 请求 → None），两种形态都试。
    ``TEXLATE_CACHE_SCOPE=per_key`` 时材料含凭证指纹，无 key 无法重算 →
    降级为 stderr 告警（不阻断）。``options`` = 任务 options_json 反序列化
    ——``front_matter`` 是键成分（``|fm:``），重算必须同料。
    """
    from texlate.pipecore import ran_front_matter  # noqa: PLC0415
    from texlate.server.settings import cache_scope  # noqa: PLC0415
    from texlate.server.worker import cache_key_for  # noqa: PLC0415

    stored = str(row.get("cache_key") or "")
    if not stored:
        return
    if cache_scope() == "per_key":
        typer.echo(
            "per_key 分桶：cache_key 含凭证指纹无法重算校验 pipeline_ver"
            "——按当前版本记账",
            err=True,
        )
        return
    # 实跑集还原（缺席 = pre-feature 行 ∅）——与 enqueue 侧进键同料
    fm = ran_front_matter(options)
    expect = {
        cache_key_for(
            arxiv_id=base,
            version=v,
            model=model,
            target_lang=lang,
            front_matter=fm,
        )
        for v in (ver, None)
    }
    if stored not in expect:
        typer.echo(
            "cache_key 与当前 PIPELINE_VERSION 重算不符——产物出自不同版本"
            "管线，按现版本打包会错标 share key，拒绝",
            err=True,
        )
        raise typer.Exit(1)


def _share_glossary_hash(
    task_dir: Path, cfg: Mapping[str, Any], options: Mapping[str, Any]
) -> str:
    """``glossary_hash`` 组分：无自定义术语表层 → ``""``；有层则各层文件 sha256 复合。

    内置/分类默认层随 ``pipeline_ver`` 走不进指纹；自定义层 = 配置的
    glossary 路径（缺省 ``~/.texlate/glossary.yaml`` 若存在）+ 论文级
    ``base/glossary.local.yaml``。配置路径已死 → ShareError——宁缺不
    串桶，错标 ``""`` 会把自定义译文混进默认池。指纹口径（层序/复合/
    读失败策略）单源在 ``share.glossary_content_hash``——本臂只保留
    CLI 侧解析策略（``expanduser`` 直收绝对/相对路径、死径即拒）。
    """
    from texlate.xlat.glossary import (  # noqa: PLC0415 -- share 子命令局部依赖
        LOCAL_GLOSSARY_NAME,
        USER_GLOSSARY_PATH,
    )

    gpath = str(cfg.get("glossary") or options.get("glossary") or "")
    gfile: Path | None = None
    if gpath:
        gfile = Path(gpath).expanduser()
        if not _is_file(gfile):
            msg = f"任务配置了 glossary 但文件不可读: {gpath}"
            raise ShareError(msg)
    return glossary_content_hash(
        user_layer=gfile,
        local_layer=task_dir / "base" / LOCAL_GLOSSARY_NAME,
        fallback_user=USER_GLOSSARY_PATH,
        strict_layers=frozenset({gfile}) if gfile is not None else frozenset(),
    )


def _share_out_is_file(out: Path) -> bool:
    """``-o`` 形态判定：已存在目录 → 目录；带后缀路径 → 文件；无后缀 → 目录。"""
    return not _is_dir(out) and bool(out.suffix)


def _share_final_move(bundle: Path, out: Path) -> Path:
    """``-o`` 文件形落盘：同设备 rename，跨设备退化 copy+unlink。"""
    try:
        shutil.move(bundle, out)
    except OSError as e:
        typer.echo(f"share pack: 无法写入 {out}: {e}", err=True)
        raise typer.Exit(1) from None
    return out


def _share_warn_no_pdf(task_dir: Path) -> None:
    """zh.pdf 缺席 → 提示按 partial 包打包（合法，manifest 不登记该成员）。"""
    if _is_file(task_dir / "zh.pdf"):
        return
    typer.echo(
        "zh.pdf 不在场——按 partial 包打包（manifest 不登记该成员，"
        "消费端只依赖 dual.json 重跑全链）",
        err=True,
    )


@share_app.command("pack")
def share_pack(
    task: Annotated[
        str,
        typer.Argument(help="任务目录（<data>/tasks/t_*）或任务 id（t_*）"),
    ],
    *,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            help="输出路径——目录/无后缀路径则其下落 {share_key}.share.zip；"
            "带后缀路径按给定名落盘；缺省 cwd",
            click_type=_CLI_PATH,
        ),
    ] = None,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="任务库目录（缺省 TEXLATE_DATA_DIR 或 ~/.texlate）",
            click_type=_CLI_PATH,
        ),
    ] = None,
    contributor: Annotated[
        str | None,
        typer.Option("--contributor", help="manifest 贡献者标识（缺省匿名 c-<16hex>）"),
    ] = None,
) -> None:
    """本地任务产物 → ``{share_key}.share.zip``（opt-in 分享到社区缓存的第一步）。

    key_parts 七组分来源：``arxiv_id``/``version`` 取任务行钉版形
    （worker fetch 后落 ``{id}v{N}``）、``model``/``target_lang`` 取任务行、
    ``prompt_ver``/``pipeline_ver`` 取本装管线常量、``glossary_hash`` 由
    自定义术语表层内容派生——取不到一律显式报错，不编造进键。
    """
    from texlate.pipecore import ran_front_matter  # noqa: PLC0415
    from texlate.server.worker import PIPELINE_VERSION  # noqa: PLC0415
    from texlate.xlat.prompts import PROMPT_VERSION  # noqa: PLC0415

    task_dir = _share_task_dir(task, data_dir)
    db = _share_db(task_dir, data_dir)
    if db is None:
        typer.echo(
            "定位不到 texlate.db——任务目录需位于 <data>/tasks/ 下，"
            "或用 --data-dir 指数据根",
            err=True,
        )
        raise typer.Exit(1)
    row = _share_row(db, task_dir.name)
    if row is None:
        typer.echo(f"任务行不在库中: {task_dir.name} @ {db}", err=True)
        raise typer.Exit(1)
    base, ver, model, lang = _share_fields(row)
    opts = row_json(row, "options_json")
    # options 解析先于 verify——``front_matter`` 是 cache_key 组分，重算同料
    _share_verify_pipeline(row, base, ver, model, lang, opts)
    cfg = row_json(row, "config_json")
    try:
        manifest: dict[str, object] = {
            "arxiv_id": base,
            "version": f"v{ver}" if ver is not None else "",
            "model": model,
            "prompt_ver": PROMPT_VERSION,
            "target_lang": lang,
            "glossary_hash": _share_glossary_hash(task_dir, cfg, opts),
            # 前置发射集进 key_parts——不同 fm 的任务产物不同包（∅ 记 ""
            # 兼容旧包重算；与 worker share_pack_manifest 同口径）。
            # 实跑集还原：done 行经 parse 写回恒带显式 dict；缺席 =
            # pre-feature 行（实跑 ∅）不标缺省
            "front_matter": ",".join(sorted(ran_front_matter(opts))),
            "pipeline_ver": PIPELINE_VERSION,
        }
        if contributor:
            manifest["contributor"] = contributor
        out_dir = (
            Path.cwd()
            if out is None
            else (out.parent if _share_out_is_file(out) else out)
        )
        _share_warn_no_pdf(task_dir)
        bundle = pack_share(task_dir, manifest, out_dir=out_dir)
    except (ShareError, OSError) as e:
        typer.echo(f"share pack: {e}", err=True)
        raise typer.Exit(1) from None
    final = bundle
    if out is not None and _share_out_is_file(out) and bundle != out:
        final = _share_final_move(bundle, out)
    typer.echo(
        json.dumps(
            {
                "share_key": bundle.name.removesuffix(".share.zip"),
                "path": str(final),
                "task_id": task_dir.name,
                "key_parts": {
                    k: manifest[k] for k in (*KEY_PART_FIELDS, "front_matter")
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@share_app.command("unpack")
def share_unpack(
    bundle: Annotated[
        Path,
        typer.Argument(help=".share.zip 包路径", click_type=_CLI_FILE),
    ],
    *,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            help="解包目录（缺省 cwd/{包名去后缀}）",
            click_type=_CLI_PATH,
        ),
    ] = None,
) -> None:
    """``.share.zip`` → 校验解包 + 打印 manifest 摘要。

    只机械校验格式/share_key 自洽/逐产物 sha256 对账——译文可信度由
    消费端重跑 splice/validate/compile 保证（shared-cache.md §5 信任
    模型），本命令不解语义无信任。
    """
    stem = bundle.name.removesuffix(".share.zip")
    if not stem or stem == bundle.name:
        stem = bundle.stem
    # 包文件名来自外部——剥出的目录名必须扁平：``..``/``.``/分隔符回退固定名
    # （``...share.zip`` 剥出 ``..`` 会向父目录写产物）
    if not stem or stem in (".", "..") or "/" in stem or "\\" in stem:
        stem = "share-unpacked"
    dest = out.expanduser() if out else Path.cwd() / stem
    try:
        mf = unpack_share(bundle, dest)
    except (ShareError, OSError) as e:
        typer.echo(f"share unpack: {e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        json.dumps(
            {
                "share_key": mf.share_key,
                "format": mf.fmt,
                "key_parts": mf.key_parts,
                "artifacts": {
                    name: {"sha256": a.sha256, "bytes": a.size}
                    for name, a in mf.artifacts.items()
                },
                "contributor": mf.contributor,
                "created_at": mf.created_at,
                "dest": str(dest),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
