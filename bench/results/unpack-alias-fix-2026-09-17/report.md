# unpack-alias-fix — mtree 别名谎报修复交付

> 2026-09-17 收口。落地 `6fe2feb`（unpack.py +52/-1，test_fuzz_unpack.py 摘 xfail + 对账 oracle 强化）。探针 `tmp/unpack-alias-fix/repro.py`（gitignored）。

## 修法（选 a 变体：落点对账，非拒写/非删条目）

pinned 用例要求 `d/x.tex` 成员仍存在且 sha==盘上实况(B)，排除了「resolved rel 去重删条目」与「拒绝写穿」两路。实现为解包末尾一遍 `_reconcile_aliases`（src/texlate/arxiv/unpack.py:202-235，挂在 `_TarWalker.run()` 的 `_finish_links()` 之后）：

- 逐成员算物理落点 `_member_loc`（= 测试 oracle `_real_loc` 同式：父级 resolve + 末段名；父级遇 symlink 环 RuntimeError 时按未解析路径当独立落点，不崩）。
- 同 loc 多成员 → 最末写序为赢家；先到条目改记赢家实况：size/sha256 恒换；kind/link_target 仅当任一侧为 symlink 时换（lstat 类已变；file↔hardlink 保留先到者自身的声明 provenance）；stub 保留（成员声明属性非盘上属性）。
- 记录实际变化的条目记 `dup_member_overwrite:<先到rel>`（与字面重名同语义：声明载荷被后到覆盖）；dir/dir 等记录本就一致的别名静默不告警。

## 实证（tmp/unpack-alias-fix/repro.py）

缺陷原样复现：`d/x.tex` 记 sha(A) 而盘上为 B。修后：记 sha(B) + `dup_member_overwrite:d/x.tex`；另验三向别名、loser=symlink→winner=file（kind 换记）、symlink 重定向自环（不崩）。

## 测试改动（tests/test_fuzz_unpack.py）

- 摘 `xfail(strict)`；用例转为正常通过并加 `dup_member_overwrite:d/x.tex` 断言。
- `_check_disk` 强化为**逐成员全验**（先到条目改记后亦为实况，不再 skip loser）。
- `extracted_bytes >= Σ member sizes` 从 `_check_views` 挪至 `_check_disk` 改按各落点赢家求和——别名条目与赢家同记一份内容字段后，按字面成员求和会重复计同一 inode。

## 自验

- `pytest tests/test_fuzz_unpack.py tests/test_arxiv_unpack.py tests/test_ctan_hardening.py`：214 全绿（含 500 随机成员流、字节变异、截断扫描在新强化 oracle 下全过）。
- 全量 tests/：2970 passed；8 个失败全部在在飞面（test_app_endpoints CSRF×3、bench_regression w73×3、segmenter_semantics×2——server/app.py 与 latex/** 在飞改动），与本 scope 无关。
- `ruff check` + `ruff format --check` 两文件净。

## 遗留/建议（不在 scope，未动）

- docs/06 §2.2 可补一行勘误：经 kept symlink 祖先写穿的别名成员，mtree 内容字段以落点赢家实况记账 + `dup_member_overwrite`。
- 残余角落（pre-existing，非本次引入）：成员写后其父级 symlink 被重定向（如 d→e 后 d→d 自环），端到端 resolve 已变化——该流的 oracle `_real_loc` 本身会 RuntimeError，seeded fuzz 未生成；真要根治需禁重定向或记录写时 loc，属另一缺陷量级。
