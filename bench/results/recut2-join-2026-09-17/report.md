# recut2-nonkeyarg 波：438 格定向重切（texlate-2f）

> 链：`parse --rerun → xlat --arm mock --rerun → compile --arm zh --xlat-arm mock --rerun → fixloop --on nonclean --rerun`，全 `--ids`（/tmp/recut2-nonkeyarg-ids.txt，overseer 切出；keyarg 24 格押后等 1d fixer-keyarg）。
> 全程 setsid 脱管（tmp/recut2-run.sh），jobs 8 压内存裕度；总耗时 ~16min。
> 时点备注：xlat 段（~09:21）先于 SENTINEL2 脏窗（placeholders.py 09:30 /
> state.py 09:34，`523941d` 落地）——**波产物零污染**；fixloop 段与脏窗
> 重叠但该路径不过 xlat 模块，安全。

## 0. 结果

| 段 | 结果 |
|---|---|
| parse | 438/438 ok |
| xlat mock | 437 ok + 1 partial |
| compile zh | clean 322 / partial 55 / fail 60 / reject 1 |
| fixloop nonclean | 末条口径 clean 53 / partial 119（含历史末条） / fail 6 |
| **end-state pdf** | **431/438 = 98.4%** |

end-state（scorecard 语义：fixloop 末条 csb 匹配即覆盖 compile）：
compile:clean 320 + fixloop:clean 48 + fixloop:partial 63 + fixloop:fail 6 +
compile:reject 1。非-pdf 残 7 = 6 fixloop:fail + 1 reject。

救回亮点：compile:fail→fixloop clean 30 + partial 24（54/60 翻盘）；
compile:partial→fixloop clean 16。

## 1. join 终版（join.json / join.txt，465 行）

| batch | 格数 | pdf | 处置 |
|---|---|---|---|
| nonkeyarg_ran | 438 | 431 | 本波已切 |
| keyarg_held | 24 | 17 | 等 fixer-keyarg 尾批（其中 7 格当前 nopdf，是重切真靶） |
| regression_addon | 3 | 1 | 波末观察名单（2105.03753/1706.07911 仍 nopdf，2211.04482 pdf） |

## 2. 全集 scorecard 位移

| 口径 | recut 波后 | recut2 后 |
|---|---|---|
| cells | 5059 | 5110（他线 +51 格入分母） |
| union pdf | 97.35% | **97.38%**（4976/5110） |
| clean | 82.76% | 82.72%（4227——分母涨、净增 +40） |

## 3. 待办

- keyarg 24 格尾批：1d fixer-keyarg 落地后跑同链（命令备好，ids 在
  /tmp/recut2-ids.txt 与 nonkeyarg 差集）。
- 7 格 nonkeyarg 终态 nopdf：6 fixloop:fail + 1 compile:reject，签名已随
  join.txt 供攻坚池。
