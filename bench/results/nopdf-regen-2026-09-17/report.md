# no-pdf 池全量 stale-zh 再生成（texlate-2f）

> 链：`parse --rerun`（两遍）→ `xlat --arm mock --rerun` →
> `compile --arm zh --rerun` → `fixloop --on fail --rerun`（2049ad3 规则批 +
> 树上 revtex4_legacy_class_rewrite 生效中）+ `fixloop --on all` 定点刷新。
> scope：scorecard 口径 no-pdf 全集 **117 格**（fixloop:fail 38 + compile:skip 80，
> 建表时点快照；期间共仓他线漂移 ±1）。
> 时点：跨 1d 连续落地——`7a78b66`（.TEX 大小写）/`91d142e`（bd-via-input 闭包）/
> `e840ab0`（EOL 注释 mask）/`9a44100`（catcode scope）/`2049ad3`（fixloop 规则批）。

## 0. 结果：**M2 门 PASS**

| 口径 | 前 | 后 |
|---|---|---|
| union pdf | 4527（89.48%，差 +28） | **4554（90.02%）PASS** |
| clean | 2905 | 2930（57.92%） |
| 池内 pdf | 0/117 | **26/117** |
| fixloop:fail | 38 | 26 |
| compile:skip | 80 | 65 |

池内 26 格出 pdf：compile 直出 12（clean 11 + partial 1）+ fixloop 收 14
（clean 13 + partial 1，含 `bbl_regen` 他线 2009.11064 压线格与共仓
fixloop 落地 3 格）。

## 1. 回收明细（26 格）

| 源 | 格数 | id / 说明 |
|---|---|---|
| P-A .TEX 大小写 | 6 | 0806.0433 0806.2109 0806.3179 1109.2086 1706.00193 physics/0104031——`7a78b66` 落地即全收；physics/0104031 过 parse 后撞 revtex4b4.cls 缺件，由树上未提交 revtex4_legacy_class_rewrite 经 fixloop 收 clean |
| P-C EOL 注释 mask | 2 | 1608.02631 gr-qc/0605005——`e840ab0` 落地即全收 |
| P-B bd-via-input 闭包 | 2 | 2105.00092 cs/0408015——`91d142e`（`\input` 闭包内 bd 收候选）全收；**dc 经 input 供给的反向未覆盖**：0905.2435/0905.4369 仍 reject（deckblatt 供 dc 形态），剩此 2 格待 dc-via-closure 方向 |
| .TEX 隐性件（归因修正） | 1 | 0707.2108——nmt 报告归 upstream「仅 .pstex 无正文」实误：`pmeyerxi.TEX` 被大小写敏感枚举遮蔽，P-A 后 parse ok → compile clean |
| BPP 瞬时池崩 | 4 | 0806.2953 2410.00035 2410.17952 2410.17973——全量重跑链归位（0806.2953 fixloop best_effort，余 compile 直出） |
| fixloop 规则批（2049ad3 + revtex4_legacy） | 9 | 0806.1415 1012.1830 1109.2144 1109.2205 1109.5313 1206.2111 hep-ph/0605134 physics/0104031（revtex4_legacy 靶 6 格全收：1012.1830/1109.2144/2205/5313/hep-ph/0605134/physics/0104031）+ 1706.00193 |
| 共仓同期他线 | 3 | 1003.0476 1206.0148 2009.11064（bbl_regen 收，过门压线格）+ 2403.00139 末条刷新（`--on all` 惯例） |

## 2. 残余 91 格分解

| 桶 | 格数 | 内容 |
|---|---|---|
| compile:skip（wontfix 正确拒绝） | 63 | plain-TeX 28 + latex209 22 + 上游垃圾 13——no_main_tex 报告裁定不变 |
| compile:skip（待 dc-via-input） | 2 | 0905.2435 0905.4369——P-B 反向缺口，提案已交 1d |
| fixloop:fail | 26 | early_eof ×8 / capacity ×6 / other ×6 / syntax ×2 / undefined_cs ×2 / illegal_unit ×1 / timeout ×1（2211.13028 真挂 242s，与 overseer OOM 裁定一致）/ no_errors_no_pdf ×1（1803.00012 SIGSEGV 票）/ best_effort-verdict-status-mismatch ×1（见 §3） |

fail 池 26 格签名分布 = 转 1d/peer1 攻坚清单（overseer 收）。

## 3. 异常/待办

- **1511.06744 status/verdict 不一致**：fixloop 跑满 366s，
  `metrics.fixloop_verdict=best_effort_pdf` 且 `splice/lrpaper.pdf` 实物在盘，
  但顶层 `status=fail`——scorecard 按 status 计 fail。**verdict→status 映射
  疑似漏 best_effort_pdf 一类**，若属映射 bug 修正即 +1 裕度。报 1d 核。
- YamlishError 未发作（revtex4_legacy 写窗口未撞本波）。

## 4. 复验记录

- parse 两遍：首遍跨 1d 落地窗口（worker 持启动时快照码，记录 code-stamp
  随 HEAD 漂移 b9b574d→a950eb0）；二遍统一 `90f9fd2` 码重盖全 117 格 zh。
  两遍均 69 reject / 48 ok——A/C/B(body) 10 格检测面回收与 wontfix 63 拒绝
  在两版代码下裁定一致，无虚报。
- xlat mock 53/53 ok（含 0-chunk physics/0104031），ph=0。
- compile 117：clean 14 / partial 1 / fail 37 / skip 65。
- fixloop `--on fail` 37 格：clean 9 + best_effort 1 + fail 27（其中
  1511.06744 verdict-status 不符另计）。
- `fixloop --on all --ids 2403.00139` 末条刷新惯例执行（compile 回愈格
  旧 unfixable 末条不刷会少计 pdf——runbook 已收）。

## 5. 过门算术

117 池 → +26 pdf：检测面（P-A 6 + P-C 2 + P-B 2 + .TEX 隐性 1 = 11）+
瞬时伤归位 4 + fixloop 规则批 9 + 他线 2 ≈ 全收。no_main_tex 提案侧
剩余量 = dc-via-input 2 格（P-B 反向）+ wontfix 63 不动。
**union pdf 4554/5059 = 90.02%，M2 门 PASS。**
