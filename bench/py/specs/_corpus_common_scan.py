"""_corpus_common TarDirs/扫描叶——层工作区布局 / 月带归并 / 成员扫描批 / offset 簿 / blob 回取。"""

from __future__ import annotations

import json
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, NamedTuple

from specs._benchlite import append_jsonl, iter_jsonl
from specs._corpus_common_features import blob_features, member_id
from specs._corpus_common_io import log
from specs._corpus_common_net import download_item, item_url, open_url

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------- TarDirs / 扫描
class TarDirs(NamedTuple):
    """IA tar 管线的层工作区——下载/扫描各目录一束。

    每层注入 ``corpus-build/{layer}/`` 下同构目录——同一套 .part 续传/
    成员级断点机器，只是落点不同。
    """

    workdir: Path  # scan_log 等层记录落点
    features: Path
    members: Path
    tars: Path
    meta: Path

    @classmethod
    def from_workdir(cls, workdir: Path) -> TarDirs:
        """标准布局：{features,members,tars,meta} 全在 workdir 下."""
        return cls(
            workdir,
            workdir / "features",
            workdir / "members",
            workdir / "tars",
            workdir / "meta",
        )


def band_of_yymm(yymm: str) -> str:
    """'9910'→'a_pre2007' … '2105'→'e_2021_25'（成员月即 item 月）."""
    yy = int(yymm[:2])
    year = 1900 + yy if yy >= 91 else 2000 + yy
    ym = year * 100 + int(yymm[2:])
    if ym < 200701:
        return "a_pre2007"
    if ym < 201201:
        return "b_2007_11"
    if ym < 201701:
        return "c_2012_16"
    if ym < 202101:
        return "d_2017_20"
    return "e_2021_25"


def member_yymm(member: str) -> str:
    return member.split("/", 1)[0]


def scan_item(it: dict, dirs: TarDirs) -> str:
    """单 item: 下载→流扫 (成员级断点)→.done→删 tar."""
    item = it["item"]
    done_f = dirs.features / f"{item}.done"
    if done_f.exists():
        return "done-skip"
    dirs.features.mkdir(parents=True, exist_ok=True)
    dirs.members.mkdir(parents=True, exist_ok=True)
    fjsonl = dirs.features / f"{item}.jsonl"
    mjsonl = dirs.members / f"{item}.jsonl"
    done_members = (
        {r["member"] for r in iter_jsonl(fjsonl) if r.get("member")}
        if fjsonl.exists()
        else set()
    )
    tar_path = download_item(it, dirs.tars, dirs.meta)
    n = len(done_members)
    t0 = time.time()
    with (
        tarfile.open(tar_path, "r|") as tar,
        open(fjsonl, "a") as fw,
        open(mjsonl, "a") as mw,
    ):
        for m in tar:
            if not m.isreg():
                continue
            if m.name in done_members:
                continue  # 流式跳过已扫成员（读穿不处理）
            bf = tar.extractfile(m)
            blob = bf.read() if bf else b""
            try:
                rec = blob_features(m.name, blob)
            except Exception as e:  # 成员级异常不阻断
                rec = {
                    "member": m.name,
                    "id": member_id(m.name),
                    "member_bytes": m.size,
                    "format": "error",
                    "error": f"{type(e).__name__}: {e}",
                }
            rec.pop("_texts", None)  # 扩库不留 staging
            rec["item"] = item
            rec["channel"] = it["channel"]
            rec["band"] = band_of_yymm(it["yymm"])
            mw.write(
                json.dumps({"name": m.name, "size": m.size, "offset": m.offset_data})
                + "\n"
            )
            mw.flush()
            fw.write(json.dumps(rec) + "\n")
            fw.flush()
            n += 1
            if n % 1000 == 0:
                log(f"  {item}: {n} members {time.time() - t0:.0f}s")
    done_f.write_text(f"{n} members\n")
    tar_path.unlink(missing_ok=True)
    (dirs.tars / f"{item}.tar.part").unlink(missing_ok=True)
    return f"scanned {n}"


def scan_batch(items: list[dict], dirs: TarDirs, jobs: int, tag: str = "") -> list[str]:
    """ThreadPool 批量 scan_item + scan_log 落账（expand 与分层构建器共用）。

    返回失败 item 名单（调用方据此定 ok/partial 终态）。"""
    todo = [it for it in items if not (dirs.features / f"{it['item']}.done").exists()]
    log(f"scan{tag}: {len(todo)}/{len(items)} items pending")
    errs = []
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(scan_item, it, dirs): it for it in todo}
        for fut in as_completed(futs):
            it = futs[fut]
            state = "done"
            try:
                st = fut.result()
                log(f"ok {it['item']} ({it['size'] / 1e6:.0f}MB {it['channel']}): {st}")
            except Exception as e:
                errs.append(it["item"])
                state = "failed"
                log(f"FAIL {it['item']}: {type(e).__name__}: {e}")
            append_jsonl(
                dirs.workdir / "scan_log.jsonl",
                {"item": it["item"], "state": state, "ts": time.strftime("%FT%T")},
            )
    log(f"scan pass done, {len(errs)} failed: {errs or '-'}")
    return errs


def offsets_for(
    item: str,
    members_dir: Path,
    tag_of_item: dict[str, str] | None = None,
    fallback_members_dir: Path | None = None,
) -> dict[str, tuple[int, int]]:
    """item → {member: (offset, size)}; members_dir 下 {item}.jsonl 直读，
    缺档且给了 tag/fallback 时回退旧池 {fallback_members_dir}/{tag}.jsonl."""
    out = {}
    p = members_dir / f"{item}.jsonl"
    if not p.exists() and tag_of_item and fallback_members_dir and item in tag_of_item:
        p = fallback_members_dir / f"{tag_of_item[item]}.jsonl"
    if p.exists():
        for r in iter_jsonl(p):
            off = r.get("offset", r.get("offset_data"))
            if off is None:
                continue  # 缺 offset 记录留给「无 offset」过滤统一报
            out[r["name"]] = (off, r["size"])
    return out


def fetch_blob(rec: dict, old_tars: dict[str, Path], offs: dict[str, dict]) -> bytes:
    """成员 blob: 旧池本地 tar 随机读; 新池 tar URL Range GET（重试 3 轮）."""
    item, member = rec["item"], rec["member"]
    off, size = offs[item][member]
    if item in old_tars:
        with open(old_tars[item], "rb") as f:
            f.seek(off)
            data = f.read(size)
        if len(data) != size:
            msg = f"local short read {len(data)}/{size}"
            raise OSError(msg)
        return data
    url = item_url(rec["channel"], item)
    last = ""
    for attempt in range(3):
        try:
            r = open_url(
                url,
                headers={"Range": f"bytes={off}-{off + size - 1}"},
                timeout=120,
            )
            try:
                # size+1 封顶：服务端不理会 Range 时不至于把整 tar 读进内存
                data = r.read(size + 1)
            finally:
                r.close()
            if len(data) == size:
                return data
            last = f"read {len(data)}/{size}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(3 * (attempt + 1))
    err = f"{item}/{member}: {last}"
    raise OSError(err)
