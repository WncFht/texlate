"""存量任务离线重注锚 + 重编译：base/ 重扫 → 双侧 marked splice → 重编译 → pdf/DB/dual 更新。

- en 侧：``reconstruct(res, None, mark_seq0=seq0)`` identity 注锚（原文逐字节 + TLXC 纯锚）。
- zh 侧：chunks 表 delivered 译文重 splice（marks_on 口径 = ``mark_moving=True``）。
- parity 闸：重扫 chunk 流须与 dual.json chunks 全等（seq↔src_file↔en 前缀），
  不符即整任务跳过——seq 错位会腐蚀锚表，宁缺勿滥。
- 编译走任务 ``options_json.engine_resolved``（缺省 tectonic；xelatex 带
  halt_on_error=False + texmfhome=任务 _texmf 若有）。
- 产物原子替换 en.pdf/zh.pdf，files 表 bytes/sha256 同步，dual.json
  documents/alignment 重建（chunks 行原样保留——译文未变）。

用法：.venv/bin/python tools/remark_rebuild.py [task_id...]
      --en-only / --zh-only / --zh-min-rate 0.3（zh 标记率低于该值才重编）/ --force
"""

import contextlib
import json
import shutil
import sqlite3
import sys
import time
import zipfile
from hashlib import sha256
from pathlib import Path

from _env import DB, TASKS
from _seqpos_lib import _char_stream
from texlate.align import build_alignment
from texlate.compile.engine._route import engine_for
from texlate.compile.inject import prepare_chinese
from texlate.latex.api import scan_tex_tree
from texlate.latex.reconstruct import (
    reconstruct,
    seq_mark_issues,
    strip_seq_marks,
)
from texlate.pipecore import (
    delivered_db,
    fixloop_round,
    probe_report,
    ran_front_matter,
)
from texlate.server.upload import pdf_pages
from texlate.server.worker._common import chunk_db_id

COMPILE_TIMEOUT = 600.0


def _sha(p: Path) -> str:
    return sha256(p.read_bytes()).hexdigest()


def _task_meta(db: sqlite3.Connection, tid: str) -> dict | None:
    r = db.execute(
        "select main_tex, options_json from tasks where id=?", (tid,)
    ).fetchone()
    if not r:
        return None
    return {"main_tex": r[0], "options": json.loads(r[1] or "{}")}


def _engine(meta: dict, task_root: Path):
    name = meta["options"].get("engine_resolved") or "tectonic"
    kw = {"halt_on_error": False} if name == "xelatex" else {}
    eng = engine_for(name, **kw)
    texmf = task_root / "_texmf"
    if texmf.is_dir():
        eng.texmfhome = texmf
    return eng


def _parity(scans: dict, dual_chunks: list[dict]) -> str | None:
    """重扫 chunk 流对账 dual.json——错位返回原因串，全等返回 None。"""
    seq_rows = [c for c in dual_chunks if isinstance(c.get("seq"), int)]
    flat = [(rel, c) for rel, res in scans.items() for c in res.chunks]
    if len(flat) != len(seq_rows):
        return f"chunk 数漂移 rescan={len(flat)} dual={len(seq_rows)}"
    for seq, (rel, c) in enumerate(flat):
        row = seq_rows[seq]
        if row.get("seq") != seq:
            return f"seq {seq} 缺位（dual chunks 乱序/缺行）"
        if row.get("src_file") != rel:
            return f"seq {seq} 文件漂移 {row.get('src_file')}≠{rel}"
        en_row = (row.get("en") or "").strip()[:24]
        en_new = c.content.strip()[:24]
        if en_row and en_new and en_row[:16] != en_new[:16]:
            return f"seq {seq} 文本漂移 {en_row[:16]!r}≠{en_new[:16]!r}"
    return None


def _splice_marked(
    scans: dict, work: Path, trans_by_rel: dict[str, dict[int, str]] | None
) -> tuple[int, int]:
    """逐文件 marked splice 写回 work——``trans_by_rel=None`` 即 en identity 臂。

    返回 (写文件数，注锚 chunk 数)。zh 臂无译文文件保持 base 原样
    （与 worker ``_build_zh`` 同规）；en 臂全量注。
    """
    seq0 = 0
    n_files = 0
    n_marks = 0
    for rel, res in scans.items():
        cur0 = seq0
        seq0 += len(res.chunks)  # 无条件累计——与 zh 侧同序保 seq 对位
        if not res.chunks:
            continue
        by_int = trans_by_rel.get(rel) if trans_by_rel is not None else None
        if trans_by_rel is not None and not by_int:
            continue  # zh 臂：无译文文件不重写
        try:
            out = reconstruct(res, by_int, mark_seq0=cur0, mark_moving=True)
        except Exception as e:  # noqa: BLE001 -- 注锚失败=原样编译
            print(f"    remark {rel} 注锚异常 ({type(e).__name__}: {e})——原样")
            continue
        if issues := seq_mark_issues(out):
            print(f"    remark {rel} 失衡 ({'; '.join(issues)})——剥锚降级")
            out = strip_seq_marks(out)
        tgt = work / rel
        tgt.parent.mkdir(parents=True, exist_ok=True)
        tgt.write_text(out, encoding="utf-8")
        n_files += 1
        n_marks += out.count("/TLXC <</MCID")
    return n_files, n_marks


def _zh_trans(
    db: sqlite3.Connection, tid: str, scans: dict
) -> dict[str, dict[int, str]]:
    """chunks 表 delivered 译文 → ``{rel: {c.id: 译文}}``（worker _build_zh 同口径）。"""
    rows = db.execute(
        "select chunk_id, status, translation from chunks where task_id=?", (tid,)
    ).fetchall()
    trans = {
        r[0]: r[2] for r in rows if delivered_db(r[1], r[2]) and isinstance(r[2], str)
    }
    out: dict[str, dict[int, str]] = {}
    for rel, res in scans.items():
        by_int = {}
        for c in res.chunks:
            zh = trans.get(chunk_db_id(rel, c.span.start, c.span.end))
            if zh is not None:
                by_int[c.id] = zh
        if by_int:
            out[rel] = by_int
    return out


def _compile(eng, work: Path, main_rel: str, log_tag: str, eng_name: str):
    """单发编译；败则走 ``fixloop_round`` 修复环兜底（worker 同路）。

    生产 zh 臂本就过 fixloop——option_clash_merge 这类规则会把
    todonotes→xcolor 早载撞 ``\\usepackage[table]{xcolor}`` 之类的伤
    修平；重注锚只跑单发等于把修复面砍掉，固定失败档须补回。"""
    rep = probe_report(work, main_rel, deps_index=None)
    res = eng.compile(
        work,
        main_rel,
        timeout=COMPILE_TIMEOUT,
        sandbox=True,
        flags=rep.flags if rep else None,
    )
    print(
        f"    {log_tag} compile: has_pdf={res.has_pdf} err={res.log.first_error or '-'}"
    )
    if not res.has_pdf:
        try:
            cell, last = fixloop_round(
                work,
                eng,
                engine_name=eng_name,
                main_rel=main_rel,
                compile_timeout=COMPILE_TIMEOUT,
            )
        except Exception as e:  # noqa: BLE001 -- 修复环自身异常不留空档
            print(f"    {log_tag} fixloop crash: {type(e).__name__}: {e}")
            return res
        n_act = len(cell.get("actions") or [])
        ok = bool(last is not None and last.has_pdf and last.pdf is not None)
        print(f"    {log_tag} fixloop: {n_act} actions → has_pdf={ok}")
        if ok:
            res = last
    return res


def _scrub_tree_marks(work: Path) -> int:
    """work 树内 .tex 锚失衡回扫——fixloop 改写可能拆散 BDC/EMC 对。

    worker ``_seq_mark_scrub`` 同规：失衡文件剥全锚（丢锚不丢镜像干净度）。
    未跑 fixloop 时恒空转（splice 出口已过 ``seq_mark_issues`` 闸）。"""
    n = 0
    for f in work.rglob("*.tex"):
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "TLXC" not in t or not seq_mark_issues(t):
            continue
        f.write_text(strip_seq_marks(t), encoding="utf-8")
        n += 1
    return n


def _writable_tree(dst: Path) -> None:
    """zh/ 既有树文件随 base 源 444 只读——copytree 覆盖前先 chmod 放开。"""
    if not dst.exists():
        return
    dst.chmod(0o755)
    for p in dst.rglob("*"):
        with contextlib.suppress(OSError):
            p.chmod(0o755 if p.is_dir() else 0o644)


def _zip_zh(work: Path, out_zip: Path) -> None:
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(work.rglob("*")):
            if f.is_file() and not f.name.startswith(".splice-done"):
                zf.write(f, f.relative_to(work).as_posix())


def _register_file(
    db: sqlite3.Connection, tid: str, kind: str, path: Path, rel: str
) -> None:
    # upsert 而非裸 update——无行任务（原始构建缺 en_pdf）写 0 行会让产物
    # 永远「未登记」，slim sweep 下拍即当孤儿字节删（t_32fc/t_f748 实证）。
    db.execute(
        "insert into files(task_id,kind,path,bytes,sha256,created_at)"
        " values(?,?,?,?,?,?)"
        " on conflict(task_id,kind) do update set"
        " bytes=excluded.bytes, sha256=excluded.sha256,"
        " created_at=excluded.created_at",
        (tid, kind, rel, path.stat().st_size, _sha(path), time.time()),
    )
    db.commit()


def _rebuild_dual(db: sqlite3.Connection, tid: str, tdir: Path) -> None:
    dual_p = tdir / "dual.json"
    doc = json.loads(dual_p.read_text(encoding="utf-8"))
    for side, pdf in (
        ("original", "en.pdf"),
        ("translated", "zh.pdf"),
    ):
        p = tdir / pdf
        if p.is_file():
            doc["documents"][side] = {
                "version": _sha(p),
                "pages": pdf_pages(p),
            }
    en_p, zh_p = tdir / "en.pdf", tdir / "zh.pdf"
    if en_p.is_file() and zh_p.is_file():
        doc["alignment"] = build_alignment(en_p, zh_p)
    dual_p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _register_file(db, tid, "dual_json", dual_p, "dual.json")


def _mark_count(pdf: Path) -> int:
    if not pdf.is_file():
        return -1
    try:
        _, _, m = _char_stream(pdf, collect_marks=True)
        return len(m)
    except Exception:
        return -1


def rebuild_task(
    db: sqlite3.Connection,
    tid: str,
    *,
    en: bool,
    zh: bool,
    zh_min_rate: float,
    force: bool,
) -> str:
    tdir = TASKS / tid
    meta = _task_meta(db, tid)
    if meta is None or not meta["main_tex"]:
        return "skip: 无任务行/main_tex"
    if not (tdir / "base").is_dir():
        return "skip: 无 base/"
    dual_p = tdir / "dual.json"
    dual = json.loads(dual_p.read_text(encoding="utf-8")) if dual_p.is_file() else {}
    fm = ran_front_matter(meta["options"])
    tree = scan_tex_tree(tdir / "base", front_matter=fm)
    scans = {rel: res for _f, rel, res in tree.parsed}
    why = _parity(scans, dual.get("chunks") or [])
    if why:
        return f"skip: parity {why}"

    eng = _engine(meta, tdir)
    eng_name = meta["options"].get("engine_resolved") or "tectonic"
    did: list[str] = []

    en_marks_now = _mark_count(tdir / "en.pdf")
    if en and (force or en_marks_now <= 0):
        work = tdir / "remark-en"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(tdir / "base", work)
        nf, nm = _splice_marked(scans, work, None)
        print(f"  en remark: {nf} files ~{nm} anchors")
        res = _compile(eng, work, meta["main_tex"], "en", eng_name)
        if res.has_pdf and res.pdf is not None:
            dst = tdir / "en.pdf"
            tmp = tdir / "en.pdf.new"
            shutil.copyfile(res.pdf, tmp)
            tmp.replace(dst)
            _register_file(db, tid, "en_pdf", dst, "en.pdf")
            did.append(f"en(marks {_mark_count(dst)})")
        else:
            did.append("en(FAILED 留旧)")
        shutil.rmtree(work, ignore_errors=True)

    if zh and (tdir / "zh.pdf").is_file():
        n_seq = sum(len(res.chunks) for res in scans.values())
        zh_marks_now = _mark_count(tdir / "zh.pdf")
        rate = zh_marks_now / max(1, n_seq)
        if force or zh_marks_now <= 0 or rate < zh_min_rate:
            work = tdir / "remark-zh"
            if work.exists():
                shutil.rmtree(work)
            shutil.copytree(tdir / "base", work)
            trans = _zh_trans(db, tid, scans)
            nf, nm = _splice_marked(scans, work, trans)
            print(f"  zh remark: {nf} files ~{nm} anchors (was {zh_marks_now})")
            try:
                info = prepare_chinese(work, meta["main_tex"])
                print(f"  inject: {info}")
            except Exception as e:  # noqa: BLE001
                print(f"  zh inject failed: {e}——弃 zh 臂")
                shutil.rmtree(work, ignore_errors=True)
                return "; ".join(did) + "; zh(inject fail)"
            res = _compile(eng, work, meta["main_tex"], "zh", eng_name)
            if res.has_pdf and res.pdf is not None:
                dst = tdir / "zh.pdf"
                tmp = tdir / "zh.pdf.new"
                shutil.copyfile(res.pdf, tmp)
                tmp.replace(dst)
                _register_file(db, tid, "zh_pdf", dst, "zh.pdf")
                n_scrub = _scrub_tree_marks(work)
                if n_scrub:
                    print(f"    zh mirror scrub: {n_scrub} files 剥失衡锚")
                _zip_zh(work, tdir / "zh-src.zip")
                _register_file(db, tid, "zh_src_zip", tdir / "zh-src.zip", "zh-src.zip")
                _writable_tree(tdir / "zh")
                shutil.copytree(work, tdir / "zh", dirs_exist_ok=True)
                did.append(f"zh(marks {_mark_count(dst)})")
            else:
                did.append("zh(FAILED 留旧)")
            shutil.rmtree(work, ignore_errors=True)

    if did:
        try:
            _rebuild_dual(db, tid, tdir)
            did.append("dual")
        except Exception as e:  # noqa: BLE001
            did.append(f"dual(fail {e})")
    return "; ".join(did) or "skip: 双侧标记已足"


def main() -> None:
    args = sys.argv[1:]
    en = "--zh-only" not in args
    zh = "--en-only" not in args
    force = "--force" in args
    zh_min_rate = 0.3
    for i, a in enumerate(args):
        if a == "--zh-min-rate" and i + 1 < len(args):
            zh_min_rate = float(args[i + 1])
    tids = [a for a in args if not a.startswith("--") and a != str(zh_min_rate)]
    if not tids:
        tids = [
            d.name
            for d in sorted(TASKS.iterdir())
            if (d / "dual.json").is_file() and (d / "base").is_dir()
        ]
    db = sqlite3.connect(str(DB))
    for tid in tids:
        t0 = time.time()
        try:
            r = rebuild_task(
                db, tid, en=en, zh=zh, zh_min_rate=zh_min_rate, force=force
            )
        except Exception as e:  # noqa: BLE001
            r = f"CRASH {type(e).__name__}: {e}"
        print(f"{tid}: {r} [{time.time() - t0:.0f}s]", flush=True)
    db.close()


if __name__ == "__main__":
    main()
