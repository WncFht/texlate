r"""prompt 臂离线重放：extract 树 → kind 装箱 → 臂注册表 system/user → 网关 → parse+member 审计链。

原型 replay_* 四驱动合并毕业；replay_batch 的 sqlite
直读形态不毕业（batch2 判例：extract 重扫恢复 ph_fragments 才全保真，
chunks 表无此列）。

用法: .venv/bin/python tools/replay_arm.py <extract_dir> <kind> <arm> <all|N|NxR>

selector——all=全部批；N=前 N 批；NxR=第 N 批重复 R 次（已炸批应力测试）；
``2,5,7x3`` 逗号列表同 v6 源件。装箱后成员数 ≤1 的批一律滤掉（四源同闸）。

臂口径（system / user 两侧配对；``*t`` 尾缀=温度应力标记，编码面同基臂，
配 ``--temperature 1.0`` 使用）：

    prod 现行产线（src 单源，随其漂移）：v6 ``[i] keep: ids | enc`` 行形 +
        ``Batch protocol`` 产线条款 + 产线解析器（keep-echo 内嵌剥除，
        不再计入 echo 列）。
    v4   EXPERIMENTAL——冻结件 _prompts_v4 组 system（``{ph: ph}`` 恒等表注入
         glossary）+ value_context 尾挂；编码面仅 replay_ab 单源可证，
         恒等表外与 v5 同构。
    v5   冻结件 _prompts_v5——manifest 末行点名 + value_context 尾挂。
    v5fv v5 + values 全量尾块（无 2000c 块帽；per-value 仍 200c 截断）。
    v5nv v5 裸 ``[n]`` 载荷——不挂任何 values 块。
    v5t  v5 同形（温度应力臂）。
    v6   实验时代两行编码 ``[i] keep: ids`` + ``values: id=val`` 独立行
         （v5 system 的 ``Batch protocol`` 条款整行换体、原编号保留），
         无尾挂——与产线 v6 单行 ``|`` 形不同代，勿混。
    v6b  v6 + keep 行只列 ``[[X_n]]`` 编号类 token。
    v6c  v6 + keep 行 ph id 带 ``×n`` 计数。
    v6t  v6 同形（温度应力臂）。

实验臂（v4/v5*/v6*）走冻结解析面 ``parse_members_exp``（v5 时代 batch.py
逐字移植，无 keep-echo 剥除——echo 计数交给 strip_meta 审计）；prod 臂走
现行 ``parse_batch_response``。v5 代 user 载荷由 ``encode_batch_members``
返回的干净成员编码重建 ``[i] enc`` 裸拼形——v6 产线返回的拼接 payload 已
带 keep 前缀，不可直用。

凭证——``--api-key-env``（缺省 ``TEXLATE_API_KEY``）所指环境变量非空才送
``Authorization: Bearer`` 头，脚本零明文 key；网关强制鉴权时先 export。

输出——``--out`` 缺省 ``tmp/replay_raw_<arm>_<kind>/``（gitignored），逐批
``batch{NN}[r{R}].txt`` 原始响应落盘；stdout 逐批打 member 级审计头行。
"""

import argparse
import collections
import concurrent.futures
import json
import os
import re
import time
import urllib.request
from pathlib import Path

import _env  # noqa: F401 -- src 登程须先于 texlate import
import _prompts_v4 as pv4
import _prompts_v5 as pv5
from texlate.pipecore import scan_tree
from texlate.xlat import placeholders
from texlate.xlat import prompts as pcur
from texlate.xlat.batch import encode_batch_members, pack_batches, parse_batch_response
from texlate.xlat.retry import assess_answer, bare_token_audit

ARMS = ("prod", "v4", "v5", "v5fv", "v5nv", "v5t", "v6", "v6b", "v6c", "v6t")
_V6_ARMS = frozenset({"v6", "v6b", "v6c", "v6t"})

# ---------------------------------------------------------------- v6 编码面（replay_v6 移植）

ANY_PH_RX = placeholders.ANY_PH_RX


_NUMBERED_RX = re.compile(r"^\[\[[A-Z]+_\d+\]\]$")


def _member_ids(text, counts=False, numbered_only=False):
    """段内 ph token 去重枚举；counts=True 时重复 token 带 ``×n`` 计数；
    numbered_only=True 时只列 ``[[X_n]]`` 编号类（``[[NBSP]]`` 等裸标记豁免）。"""
    seen, out = set(), []
    cnt = collections.Counter()
    for m in ANY_PH_RX.finditer(text):
        t = m.group(0)
        if numbered_only and not _NUMBERED_RX.match(t):
            continue
        cnt[t] += 1
        if t not in seen:
            seen.add(t)
            out.append(t)
    if counts:
        out = [f"{t}×{cnt[t]}" if cnt[t] > 1 else t for t in out]
    return out


def _short(v, n=120):
    v = " ".join(v.split())
    return v if len(v) <= n else v[:n] + "…"


def encode_v6(enc_list, members, *, counts=False, numbered_only=False):
    """``[n] keep: ids / values: id=val / 编码后源文``——无 ph 段不加元数据行。

    enc_list = ``encode_batch_members`` 的 per-member 编码结果——``~→[[NBSP]]``
    等转义必须在线上文本里完成，否则审计口径与发送口径不一致（假阳性）。
    """
    blocks = []
    for i, (enc_text, c) in enumerate(zip(enc_list, members, strict=True), 1):
        ids = _member_ids(enc_text, counts=counts, numbered_only=numbered_only)
        head = f"[{i}] keep: {' '.join(ids)}" if ids else f"[{i}]"
        lines = [head]
        if c.ph_fragments:
            vals = "; ".join(f"{k}={_short(v)}" for k, v in c.ph_fragments.items())
            lines.append(f"values: {vals}")
        lines.append(enc_text)
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


_META_LINE = re.compile(r"^(keep|values)\s*:")


def strip_meta(part):
    """剥掉译文开头误回显的元数据行；返回 ``(clean, stripped_n)``。

    全臂统一剥 + 计 echo（v6 源件口径）——v4/v5 臂 echo>0 即模型回显了
    manifest/协议行，本身是审计信号；中文译文行首以字面 ``keep:``/``values:``
    起头的概率可忽略，误食风险为零。
    """
    lines = part.split("\n")
    n = 0
    while lines and _META_LINE.match(lines[0]):
        lines.pop(0)
        n += 1
    return "\n".join(lines), n


# ------------------------------------------------------ 实验时代解析面（冻结 ba0fd945:batch.py）

#: 产线 ``parse_batch_response`` 自 v6 起内嵌 keep-echo 剥除——用它解析实验臂
#: 响应会把 echo 信号吞掉（strip_meta 计不到数）。以下逐字冻结 v5 时代口径，
#: 专供实验臂；prod 臂仍走产线解析器。
_EXP_NUM_RX = re.compile(r"^\s*\[(\d+)\]", re.MULTILINE)
_EXP_ATAT_LINE_RX = re.compile(r"^\s*@@\s*$", re.MULTILINE)
_EXP_ATAT_ONLY_RX = re.compile(r"\s*@@\s*")
_EXP_STUB_ONLY_RX = re.compile(r"\s*(?:\[\d+\]\s*)+")
_EXP_LEAKED_MARK_RX = re.compile(r"(?<!\[)\[(\d+)\](?!\])")


def _parse_numbered_exp(text, n):
    """v5 ``_parse_numbered`` 移植（``rx`` 形参内联为 ``_EXP_NUM_RX`` 单点）。"""
    matches = list(_EXP_NUM_RX.finditer(text))
    if not matches:
        return None
    idxs = [int(m.group(1)) for m in matches]
    if sorted(idxs) != list(range(1, n + 1)):
        return None
    out = [""] * n
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        seg = text[m.end() : end]
        seg = "\n".join(
            ln for ln in seg.split("\n") if not _EXP_ATAT_ONLY_RX.fullmatch(ln)
        )
        out[int(m.group(1)) - 1] = seg.strip()
    return out if all(out) else None


def parse_members_exp(text, n):
    """v5 时代 ``parse_batch_response`` 逐字移植（安全侧裁定注释见原件）。

    主协议 ``[n]`` 行首锚定 + ``@@`` 独占行兜底；歧义一律 ``None`` 退单翻。
    """
    text = placeholders.EOL_RX.sub("\n", text).strip()
    if not text or n <= 0:
        return None
    out = _parse_numbered_exp(text, n)
    if out is not None:
        return out
    parts = [p.strip() for p in _EXP_ATAT_LINE_RX.split(text)]
    parts = [p for p in parts if p and not _EXP_STUB_ONLY_RX.fullmatch(p)]
    if len(parts) != n:
        return None
    for part in parts:
        if any(1 <= int(m.group(1)) <= n for m in _EXP_LEAKED_MARK_RX.finditer(part)):
            return None
    return parts


# ---------------------------------------------------------------- 臂注册表

#: v5 ``Batch protocol`` 条款行锚——编号随 kind/batch 漂移（caption=11、
#: abstract=13、其余=12），按锚名正则定位、整行换体保留原编号。
_BATCH_RX = re.compile(r"^(\d+)\. \*\*Batch protocol\.\*\*.*$", re.MULTILINE)

#: v6 条款体（去编号前缀——前缀由被换行原编号回填）
_V6_BATCH_BODY = (
    "The input is a numbered list of independent fragments ([1], [2], "
    '...). After a fragment\'s number, a "keep:" header lists the '
    "placeholders that fragment must preserve verbatim in its "
    'translation, and a "values:" line shows what each placeholder '
    "stands for — both are protocol metadata, not source text; never "
    "repeat them in your output. Translate each fragment independently "
    "and return one [n] section per input fragment in the same order — "
    "no merging, no omissions. If you cannot keep the numbering, "
    "separate the translations with @@ on its own line instead."
)


def _swap_batch_clause(system):
    """v5 system 的 ``Batch protocol`` 条款整行换 v6 体（原编号保留）。

    assert 语义=锚名在场（措辞漂移不拦截——整行覆盖本就不读旧措辞）。
    """
    new, n = _BATCH_RX.subn(
        lambda m: f"{m.group(1)}. **Batch protocol.** {_V6_BATCH_BODY}", system
    )
    assert n == 1, "Batch protocol anchor missing — v5 rules block drifted"
    return new


def build_system(arm, kind, doc_ph, paper_ctx, manifest):
    """臂 → system prompt。

    冻结件分工：v4→``_prompts_v4``（恒等表注入）；v5/v6 实验族→``_prompts_v5``
    （v6 族在其上换 ``Batch protocol`` 条款）；prod→现行 src（随其漂移）。
    """
    if arm == "v4":
        ident = {
            ph: ph for ph in sorted(doc_ph, key=lambda p: (placeholders.sort_key(p), p))
        }
        return pv4.build_system_prompt(
            kind,
            src_lang="English",
            tgt_lang="Chinese",
            glossary_terms=ident,
            batch=True,
            paper_context=paper_ctx or None,
        )
    if arm == "prod":
        return pcur.build_system_prompt(
            kind,
            src_lang="English",
            tgt_lang="Chinese",
            glossary_terms={},
            batch=True,
            paper_context=paper_ctx or None,
            placeholder_manifest=manifest or None,
        )
    system = pv5.build_system_prompt(
        kind,
        src_lang="English",
        tgt_lang="Chinese",
        glossary_terms={},
        batch=True,
        paper_context=paper_ctx or None,
        placeholder_manifest=manifest or None,
    )
    if arm in _V6_ARMS:
        system = _swap_batch_clause(system)
    return system


def _merged_frags(members):
    """批内成员 ``ph_fragments`` 合并（同 token 后写覆盖前写——四源同口径）。"""
    merged = {}
    for c in members:
        if c.ph_fragments:
            merged.update(c.ph_fragments)
    return merged


def build_user(arm, members, enc_list, payload_prod):
    """臂 → user payload。

    ``payload_prod`` = 产线 ``encode_batch_members`` 拼接形（v6 起成员行带
    ``keep:`` 前缀）——只有 prod 臂直用；实验臂一律由 ``enc_list``（干净
    成员编码）重建 v5 时代 ``[i] enc`` 裸拼形，再按臂改装。

    v4 臂全链走冻结件——``_prompts_v4.render_value_context`` 虽与 pv5 逐字节
    相同，冻结臂语义纯度优先。v5fv 尾块不走 ``render_value_context``——
    全量口径无 2000c 块帽（v6 源件字面移植）。
    """
    if arm == "prod":
        return payload_prod + pcur.render_value_context(_merged_frags(members))
    payload = "\n".join(f"[{i}] {e}" for i, e in enumerate(enc_list, 1))
    if arm in _V6_ARMS:
        return encode_v6(
            enc_list,
            members,
            counts=(arm == "v6c"),
            numbered_only=(arm == "v6b"),
        )
    if arm == "v5nv":
        return payload
    merged = _merged_frags(members)
    if arm == "v4":
        return payload + pv4.render_value_context(merged)
    if arm == "v5fv":
        lines = [
            f"- {k}: {v[:200] + '…' if len(v) > 200 else v}" for k, v in merged.items()
        ]
        return payload + "\n\n" + pv5.VALUE_CONTEXT_HEADER + "\n" + "\n".join(lines)
    return payload + pv5.render_value_context(merged)


def call(user, system, args):
    """单次非流式 ``chat/completions`` POST；env key 非空才送 Bearer 头。"""
    headers = {"Content-Type": "application/json"}
    key = os.environ.get(args.api_key_env, "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        f"{args.base_url}/v1/chat/completions",
        data=json.dumps(
            {
                "model": args.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": args.temperature,
                "max_tokens": args.max_tokens,
                "stream": False,
            }
        ).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=args.timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def expand_selector(sel, n_batches):
    """``all|N|NxR|逗号列表`` → ``[(bi, rep)]``；越界/畸形批下标 ValueError。"""
    if sel == "all":
        return [(i, 0) for i in range(n_batches)]
    if "," in sel:
        lst, _, r = sel.partition("x")
        reps = int(r) if r else 1
        out = [(int(t), rep) for t in lst.split(",") for rep in range(reps)]
    elif "x" in sel:
        k, _, r = sel.partition("x")
        out = [(int(k), rep) for rep in range(int(r))]
    else:
        return [(i, 0) for i in range(min(int(sel), n_batches))]
    bad = [i for i, _ in out if not 0 <= i < n_batches]
    if bad:
        msg = f"批下标越界 {bad}（共 {n_batches} 批）"
        raise ValueError(msg)
    return out


def main():
    ap = argparse.ArgumentParser(
        description="prompt 臂离线重放：extract 树 → 臂 system/user → 网关 → 审计",
        epilog="selector: all=全部批; N=前N批; NxR=第N批重复R次; 亦支持 2,5,7x3 逗号列表",
    )
    ap.add_argument("extract_dir", type=Path, help="cache extract 树（scan_tree 根）")
    ap.add_argument(
        "kind",
        help="chunk kind（para/caption/section_title/abstract/table_text/env_text）",
    )
    ap.add_argument("arm", choices=ARMS)
    ap.add_argument("selector", help="all|N|NxR|N,N,NxR")
    ap.add_argument("--base-url", default="http://127.0.0.1:3033")
    ap.add_argument("--model", default="swe-2-medium")
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument(
        "--api-key-env",
        default="TEXLATE_API_KEY",
        help="Authorization Bearer 值读此环境变量；缺省不设头",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="raw 落盘目录（缺省 tmp/replay_raw_<arm>_<kind>/）",
    )
    ap.add_argument(
        "--jobs", type=int, default=3, help="并发线程数（兼 pack_batches workers）"
    )
    ap.add_argument(
        "--max-chars", type=int, default=12000, help="pack_batches payload 硬顶"
    )
    ap.add_argument("--min-chars", type=int, default=2500, help="pack_batches 批下限")
    ap.add_argument("--max-items", type=int, default=32, help="pack_batches 批成员硬顶")
    args = ap.parse_args()

    scans, chunks, fault, support = scan_tree(
        args.extract_dir, front_matter=frozenset({"abstract", "title"})
    )
    by_kind = collections.OrderedDict()
    for c in chunks:
        by_kind.setdefault(c.kind, []).append(c)
    if args.kind not in by_kind:
        ap.error(
            f"kind {args.kind!r} 不在树内——可用: {', '.join(by_kind) or '(无 chunk)'}"
        )
    grp = by_kind[args.kind]

    doc_ph = placeholders.collect_doc_placeholders(c.content for c in chunks)
    paper_ctx = next((c.content[:6000] for c in chunks if c.kind == "abstract"), "")
    manifest = placeholders.render_placeholder_manifest(doc_ph)
    system = build_system(args.arm, args.kind, doc_ph, paper_ctx, manifest)

    batches = [
        g
        for g in pack_batches(
            [c.content for c in grp],
            max_chars=args.max_chars,
            max_items=args.max_items,
            min_chars=args.min_chars,
            workers=args.jobs,
        )
        if len(g) > 1
    ]
    print(
        f"ARM={args.arm} system={len(system)}c chunks={len(grp)} batches={len(batches)}",
        flush=True,
    )

    out = args.out or (_env.REPO / "tmp" / f"replay_raw_{args.arm}_{args.kind}")
    out.mkdir(parents=True, exist_ok=True)

    try:
        jobs = [
            (i, batches[i], rep)
            for i, rep in expand_selector(args.selector, len(batches))
        ]
    except ValueError as e:
        ap.error(f"selector {args.selector!r}: {e}")

    def work(bi, g, rep=0):
        members = [grp[j] for j in g]
        payload_prod, enc = encode_batch_members([c.content for c in members])
        payload = build_user(args.arm, members, enc, payload_prod)
        tag = f"batch{bi:02d}" + (f"r{rep}" if rep else "")
        t0 = time.time()
        try:
            raw = call(payload, system, args)
        except Exception as e:
            return f"{tag} n={len(members):2d} HTTP-ERR {e}"
        (out / f"{tag}.txt").write_text(raw, encoding="utf-8")
        parts = (parse_batch_response if args.arm == "prod" else parse_members_exp)(
            raw, len(members)
        )
        if parts is None:
            return (
                f"{tag} n={len(members):2d} PARSE-FAIL raw={len(raw)}c\n"
                f"  HEAD: {raw[:200]!r}\n  TAIL: {raw[-200:]!r}"
            )
        bad, echoes = [], 0
        for k, (c, part_in) in enumerate(zip(members, parts, strict=True)):
            part, st = strip_meta(part_in)
            echoes += st
            zh, err, w = assess_answer(
                c.content,
                placeholders.decode_newlines(part),
                audit_err=bare_token_audit(enc[k], part),
                repair_fn=None,
                validate_fn=lambda _s, _z: "",
            )
            if err:
                bad.append(f"  m{k} [{c.chunk_id[:8]}] {err} | out[{part[:70]!r}]")
        head = (
            f"{tag} n={len(members):2d} ok bad={len(bad)} echo={echoes} "
            f"raw={len(raw)}c {time.time() - t0:.0f}s"
        )
        return head + ("\n" + "\n".join(bad) if bad else "")

    with concurrent.futures.ThreadPoolExecutor(args.jobs) as ex:
        futs = [ex.submit(work, *j) for j in jobs]
        for f in concurrent.futures.as_completed(futs):
            print(f.result(), flush=True)


if __name__ == "__main__":
    main()
