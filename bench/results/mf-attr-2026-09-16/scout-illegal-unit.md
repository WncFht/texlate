# illegal_unit 族归因（leader 批量归因 · scout-unit 复核待并入）

> 口径：compile.jsonl 末条 `verdict.category==illegal_unit` = **224 格**
> （票面 312 为 triage 抽样口径，含历史轮次）。另 12 格末态
> unfixable:illegal_unit 属 59-fail 集，归 scout-fail59。

## 方法

逐格取 splice 日志 `Illegal unit of measure` 错误行 + 上下文 200 字符，
统计错误行是否含 CJK（`[一-鿿]`）——**89.5% 含 CJK 直接坐实腐蚀**。

## 簇分解

| 簇 | 占比 | 机理 | 归属 |
|---|---|---|---|
| 错误行含 CJK | **89.5%** | 数字+单位被译文改写：`0.4cm`→`0.4这`、`-.25in`→`-.25这是译文`——数值域混入译文占位/正文。bug-B/腐蚀超簇成员 | fixer-slots + segmenter（`a6b58d4` gap-bytes 已掐断产生路径）+ L0 检查 |
| 真 TeX 伤 | ~5% | 稿自带非法单位（`pt inserted` 类遗留）、包版本 API 差异 | 上游/wontfix 候选 |
| shim 替身继发 | ~5% | shim 宏缺尺寸寄存器声明（`\iopams` 类 dimen 未 \newdimen → 下游赋值报 illegal_unit） | 同 ucs 族数据提案，shim body 扩列 |

## 与已落修复的交叠

89.5% CJK 腐蚀簇与 undefined_cs 融合簇同源——`a6b58d4` 段内 gap 独立 literal
run 后不再被吞，splice 融合链已断；加上 `.rtx` 排除（`aps.rtx`/`10pt.rtx`
makeatletter 域被当正文翻是 `-.25这是译文` 的实证源头，e2e/stagerun 两处
glob 已排）。**重跑/重翻即回收，规则面无新增条目。**

## 处置建议

1. **rerun 优先**：本族与 ucs 融合簇同批次重翻验证——realpostfix2
   （--recode 全量臂）自然覆盖，无需单独点火。
2. shim dimen 缺口随 ucs 族数据提案一并走 owner 评审。
3. 真 TeX 伤散格归逐格/wontfix，不立项规则。
