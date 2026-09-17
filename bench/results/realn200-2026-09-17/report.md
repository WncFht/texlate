# realn200 真臂验收报告（n=200 四层分层 seed42，swe-2-medium，conc4→20）

> 2026-09-17 收官。Run：`bench/results/realn200-2026-09-17/`（records/results/matrix/summary/cases/manifest/ids/run_meta/run.log/scout-notes 全）。
> code stamp `snap-208f2ceaf514`（TEXLATE_SRC=repo tmp/texlate-src-realn200 冻结快照）。
> 谱系 = realpostfix2 n100 的规模验证续跑；选样见 scout-notes.md（200 格 = core 39/booster 7/hot 2/expand 152，剔 realpostfix2 校友 24 + 未 extracted 13 + >20MB 重件尾 75）。

## 0. 跑程实况

- **三次 harness 看门狗杀 + 一次 conc 重启**，全程 setsid 脱管 + records append 续跑，零格重付（断点语义有效）；watchdog 期烧掉的只是在飞格 chunk，已落账格无损。
- 10:22 起 Devin 账号级消息限流持续 429（retry_after 16-44s drip）——overseer 定论预期行为，retry 阶梯空转，全程零 contamination：降级臂免费集发现 404 → `_free_uids` memoize 为空永久停用，所有 chunk 均由 swe-2-medium 服务。
- conc4→20 切换（用户令，网关硬闸放到 20）：重启后实测 wall **90.0 s/格 ≈ 40-72 格/h**（小格 chunk 数填不满 20 worker，非线性提速）。sum cell seconds 22965 ≈ 6.4h 格工时，净墙钟 ~3.2h（conc20 段）。

## 1. 终态矩阵（end-state = fixloop 末条覆盖 pipe-xel）

| 口径 | realn200 (n=200) | realpostfix2 (n=100) | mock 臂同 200 格（stagerun-loop1） |
|---|---|---|---|
| pipe-xel clean | 150 (75.0%) | 76 | 153 |
| pipe-xel partial | 24 | 10 | 21 |
| pipe-xel fail | 24 | 14 | 24 |
| pipe-xel 无 verdict（route reject） | 2 | 0 | 2（同两格） |
| **union pdf** | **197/200 = 98.5%** | ~95%（76+19 救回推算） | **197/200 = 98.5%** |
| end clean | 173 (86.5%) | — | 171 |
| end partial | 24 | — | 26 |
| end fail | 1 | — | 1 |

**头号结论：真臂与 mock 臂打平**——raw pipe 分布几乎一致（clean 150 vs 153），
fixloop 后两臂收敛到同一 union pdf 197/200。mock 臂不虚报 pdf 率；
差异只在 clean/partial 构成与格级归属（下节）。

注意：records `status` 字段 = pipe-xel verdict（**不含 fixloop 覆盖**）——
单读它会漏掉 23 格 fixloop 救回，union pdf 必须按 end-state 口径算。

## 2. fixloop 救回（onfail，48 格池 = pipe 非clean）

| 来路 | clean | partial | fail |
|---|---|---|---|
| pipe-fail 24 格 | **16** | 7 | **1** |
| pipe-partial 24 格 | 7 | 17 | 0 |

救回率：fail→pdf **23/24 = 95.8%**（postfix2：19/24）；partial→clean 7。
唯一未救回 fail 格 + 2 格 route reject（cond-mat/0408247 latex209、
hep-th/9703073 plain_tex——mock 臂同位置同样无记录，wontfix 类非臂问题）。
账齐：197 pdf + 1 fail + 2 reject = 200。

## 3. 管线引入（pipe≠clean ∧ base=clean，onfail 48 格有 base）

**6 格**：0806.2915、0905.1119、1306.0099、1706.00183、1803.00181、2308.04246
（postfix2：2 格；量升主因样本换成 expand 老稿层 152/200）。

## 4. chunk 面（⚠️ skew 标注）

- ok **24089/24163 = 99.69%**；partial 25、fault 0、skipped 49；leftover_ph **0**（gate PASS）。
- **overseer caveat**：e2e_real `translate_tree` 零文件闸（.rtx.tex/.code.tex/
  file_has_prose 全漏）——real 臂把 REVTeX dump/support 件也送译，chunk 送译量
  与 ok 率相对 mock（`e2e._scan_tree` 有闸）口径不对等，体积类指标虚高。
  postfix2 同码故横向可比。
- **口径断点（2026-09-17，`a08dda3`）**：`translate_tree` 已收敛至
  `e2e._scan_tree` 四门——本 run 及更早 real 臂的 chunks/src_chars/ok 率等
  **体积类指标不可与修复后新 run 直接比**（送译集合含 support 件，虚高）；
  pdf/clean/fixloop 救场等终态指标不受影响。记录键同步改
  `fault_files`/`support_files`/`support_skipped`（原 `parse_fail` 废）。
- tr<full 格（fallback_orig 残 chunk）存在：如 1907.00273 tr 223/234。
  chunk 级非 ok 74 块 = partial 25 + skipped 49，无 fault。

## 5. 逐格分歧（end-state 口径，仅 10 格）

real 更优 6 格（mock partial→real clean）：0905.2110、1206.0279、1511.02747、
1706.00235、1907.03836（pipe=fail 被 fixloop 救到 clean）、2211.13048。
real 更差 4 格（mock clean→real partial）：0806.2915、1306.0099、
2410.17958、cond-mat/0408020——均为 partial 未坠 fail，fixloop 后仍在 pdf 面内。

## 6. 门槛判决

- splice leftover_ph=0 PASS；翻译执行 200/200 PASS；chunk ok 99.69% PASS（口径注记见 §4）。
- **union pdf 98.5%**（M2 门 ≥90% 裕度 +8.5pt）；真臂对 mock 臂零净回归。
- 残留池：end fail 1 格 + 无 verdict 2 格 + partial 24 格 + 引入格 6（交集另计）→ 攻坚面见 records。

## 7. 与 mock 结论的边界

mock↔real 打平的是**终态 pdf**，不代表译文质量等价——mock 臂翻译是占位回显，
real 臂产出真中文（cjk_chars 面在 verdict 内逐格可查）。本批证明的是
「真 LLM 译文不引入额外 compile 失败」，质量面口径属下游评审。
