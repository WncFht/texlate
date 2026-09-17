# recut 波：全量 zh 重切（texlate-2f）

> 链：`parse --rerun` 全量（5059，四层）→ `xlat --rerun --arm mock` →
> `compile --rerun --arm zh --xlat-arm mock` → `fixloop --on nonclean --xlat-arm mock`
> → YamlishError/RulesetError 双毒窗补救三批（809 = 425+384+321）+ 单格补 1。
> 时点：parse 段中止重跑过一次——首遍 06:08:20 收工差 45s 没带上 1d R1-R8
> （`54fc4a9`），按 overseer 令 abort xlat 后全量重切，单代际 zh 树。
> 动机：recode 波终核确认「陈树携带」是 F/E(a)/C 桶主残留（88/387 持续 F 格
> zh 树烙 `这是译文` 进结构位）——zh 树是 parse 时点快照，只有 recut 抽干。

## 0. 结果

| 口径 | recode 波终核 | recut 波终态 | Δ |
|---|---|---|---|
| union pdf | 4869/5012 = 97.15% | **4925/5059 = 97.35%** | +56（分母 +47 real 队列并入） |
| clean | 3454 = 68.91% | **4187 = 82.76%** | **+733** |
| excl-reject pdf | — | 97.62%（n=5045） | — |
| excl-reject clean | — | 82.99% | — |

end-state 分布（scorecard 末条口径，5059）：

```
3602  compile:clean      585  fixloop:clean
 738  fixloop:partial     65  compile:skip
  55  fixloop:fail        14  compile:reject
```

**clean +733 是本波主收益**——陈树结构位污染（`这是译文` 烙印、过期
normalize 臂缺席）随全量重切抽干，原 F/E(a) 格大批翻 clean。

## 1. 分段落账

| 段 | 结果 |
|---|---|
| parse | 4995 ok / 64 reject（plain_tex 28 + latex209 23 + garbage 10 + parse 3——wontfix 裁定面与 nopdf 波一致） |
| xlat mock | 4995/4995 ok（47 格 real-zh 队列被 mock 覆写并入主流，预期行为） |
| compile zh | clean 3612 / partial 630 / fail 738 / skip 65 / reject 14 |
| fixloop nonclean | 池 = compile{fail,partial} = 1368 格 |

compile:fail 签名以 missing_file 为绝对主力（aastex.cls 82 / psfig.sty 63 /
iopart.cls 44 / mn2e.cls 42 / aa.cls 33 / elsart.cls 25 / tcilatex.tex 23 /
tensor.sty 18 / espcrc2.sty 17 / llncs.cls 16 / JHEP3.cls 14 / eqsecnum.sty
14 / aaspp4.sty 12 / pst-node.sty 10…）——正是 fixloop install 规则射程。
skip 65 = 64 格 `zh/ missing or no .xlat-arm.json`（parse reject 下游断供）+
1 格 xlat=fail；reject 14 = inject latex209（ds_at 9 + no_target 5）。

## 2. fixloop 段与双毒窗补救

nonclean 1368 格终态：**clean 575 / partial 738 / fail 55**。
救回面：compile:fail → pdf **685 格**（其中 fail→clean 426）；
partial→clean 149 格。verdict 分布：clean 480 / acceptable_pdf 445 /
best_effort_pdf 391 / unfixable 45 / reject 2 / 其他 5。

**毒窗一（YamlishError）**：peer1 polyfill 批把非法转义 `.\hbox` 写进
rules.yaml，fixloop 逐格 Ruleset.load 在窗口期全炸——809 格末条 error 遮蔽
（overseer 清单 /tmp/yamlish-poisoned-ids.txt）。scorecard 对 error 末条
回落 compile 态，fixloop 上行全丢。

**毒窗二（RulesetError）**：补跑第二批中途，rules.yaml 再进写入窗口——
`rule accent_mark_fix: 未知 builtin_transform 'accent_mark_fix'`（规则引用
未实装 transform，校验期炸，非语法期炸）——321/384 格记 error。

补救链（三段 + 单格）：

| 批 | 格数 | 口径 | 结果 |
|---|---|---|---|
| 1 | 425 | `--on fail`（默认口径只覆盖 compile:fail 中毒格） | clean 249/partial 136/fail 40 |
| 2 | 384 | `--on nonclean`（compile:partial 中毒格） | 撞毒窗二，321 error |
| 3 | 321 | `--on nonclean`（yaml 恢复后重盖） | 大部落账 |
| 单格 | 1 | 2403.15072 残余 error 重跑 | clean |

终态：809 中毒格 **零 error 末条**（clean 348 / partial 419 / fail 42）。
教训已带话：append-only 纪律之外，**新规则引用的 builtin_transform 必须
先实装再落 yaml**——校验炸与语法炸同效。

## 3. dropped overrides 说明

scorecard 终报 `stale 745`（fixloop 记录 csb≠当前 compile 态——recut 后
compile 状态翻转使旧 fixloop 裁决自然失效，正确回落 compile）；
no_csb 在补救后清零。这是末条语义设计内行为，非缺陷。

## 4. scout-recut2-join（overseer recut2 manifest × 末态）

462 格 join 终版落 `bench/results/recut2-join-2026-09-17/`（join.json +
join.txt）。分布：

| (compile, fixloop) | 格数 | 处置（overseer 裁断） |
|---|---|---|
| clean × 无 fixloop | 241 | **保留入列**——key-arg/泄漏型静默质量伤，重切收益在质量不在 status，标 regression-watch |
| clean × partial | 59 | 同 watch 面 |
| NO_COMPILE | 58 | 照常入列 |
| partial/fail 各组合 | 104 | 照常入列 |

regression-watch 总计 309（全部 compile:clean 格）。

## 5. 残余与展望

- fixloop:fail 55 格 = 转 1d/peer1 攻坚池（missing_file 24 为主 +
  early_eof 7 / other 4 / syntax 4 / capacity 4 / undefined_cs 3…）。
- compile:skip 65 + reject 14 = wontfix/上游面不动。
- 裕度：97.35% 距门 +7.35pt；clean 82.76% 为 M3 口径留足带宽。
- 波中零 hang：2410.x 重件在 parse 段仍尾聚但全部落账。

## 6. 复验记录

- parse 单代际：全 5059 在 `54fc4a9` 后切出（abort-重切后 xlat/compile/fixloop
  全在同代 zh 上）。
- remediation 三批均 `--xlat-arm mock` pin；单格补跑同。
- 共仓写入：波中他线持续 append records，分段计数以本批末条差分计。
