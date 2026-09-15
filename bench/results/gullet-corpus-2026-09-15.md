# gullet corpus bench — M1 接线前实测门（2026-09-15）

`Gullet(tex, root_dir=extracted/)` 抽干展开流，corpus_v3 manifest 全量
1000 篇主文档（locate 定主）。脚本 `bench/py/gullet_bench.py`（未入库，
`uv run python` 可复跑），逐文件行 `gullet-corpus-2026-09-15/rows.jsonl`。

## 总量

- 995/1000 跑通；5 篇 locate 定不出主文件（hep-ph/9703202 等，
  `main=None`——语料缺陷非 gullet 面）。
- 耗时 p50 21ms / p95 71ms / max 657ms（0905.1757，1.08MB）。
  全量 1000 篇 ~30s。
- steps p50 22 / p95 405 / max 3039（2410.17998）——**BUDGET 余量巨大，
  expansion_overflow / gen_overflow 全库 0 触发**，三级限制从未真开火。
- 输出 token p50 ~33k/篇；`\input` 压栈多文件源正常（file_texts>1 普遍）。

## warnings 分布

| kind | 总次数 | 涉及文档 | 读法 |
|---|---|---|---|
| missing_input | 48 | 33 | 未随包 .bbl/.sty/图件 tex，正常 |
| def_parse_fail | 157 | 9 | **91% 集中一篇**（2410.17998×143）；余 8 篇 ≤6/篇 |
| if_unterminated | 1 | 1 | 个位数，真残缺 |
| expansion_overflow / gen_overflow | 0 | 0 | — |

ArgMismatch 回吐：**全库 1 次**（1 篇）——§3.5 回吐路径基本不触发，
spec 参数面在真语料上几乎总是匹配。

## `\if` 两档

- 涉 if 文档 149/995；触发 901 次：**可求值 300（33.3%）/ 界标 601（66.7%）**。
- 选中支分布：T 47 / F 253（ifcase 整档 0 命中——真语料 `\ifcase` 多在
  cls/sty 或宏定义体里，main 流少见）。
- 界标名分布（marker 文档源文）：`ifx` 305 / `ifthenelse` 138 / `iff` 111
  / `ifdefined` 88 / `ifnum` 74 / `ifmmode` 53 / `ifdim` 36 ……
  `\iff`（amsmath iff 缩写）与 `\ifthenelse` 走 `startswith("if")` 进
  界标档——**语义正确但值得接线时注意**：`\iff` 是数学命令非条件式。
- IfCond（`\newif` 旗标）全部走可求值档，含 ifCLASSOPTION* 类。

## 不动点验证（expand_all 输出整列重喂新 Gullet）

929/995 幂等（93.4%）。66 篇发散，**全部是 token 数净缩**（无逐枚不等），
机制分解：

- **65/66 界标 `\if` 重消化**：界标档 `\ifX` 本体交出但条件 token 已在
  pass1 消费；重喂时 `\ifX` 再进 `_do_if` → `_eval_if` 把**选中支头部**
  token 当条件再吃一轮 → 典型缩 6（ifnum 三件）至 26k（0707.2108，
  50 个界标，重判后 process_if 收走整段对侧支）。marker>0 的 123 篇
  里 65 篇发散（53%）；`\iff`/`\ifthenelse` 类无参界标重喂无害故
  另一半守住。
- **1/66 def_parse_fail 重处理**：2410.17998（143 次 dpf）——失败
  `\def` 透传进流，pass2 再当原语消费后续 token，−1694。

含义：M1 接线后分段器若二次过流，界标 `\if*` 与失败 `\def` 是仅有的
两类非不动点构造；单次管线不受影响（流只过一次）。

## 慢档 top8

| id | ms | bytes | steps |
|---|---|---|---|
| 0905.1757 | 657 | 1.08MB | 145 |
| 2410.17998 | 419 | 95KB | 2085 |
| 1511.06706 | 373 | 274KB | 65 |
| 1206.5202 | 303 | 371KB | 1017 |
| 2009.11053 | 264 | 39KB | 33 |
| 1404.2402 | 190 | 398KB | 23 |
| 1003.5534 | 189 | 337KB | 29 |
| 1206.2231 | 182 | 267KB | 158 |

耗时大头是字节量不是展开深度（steps 与 ms 不相关）；2410.17998 是
steps 异常点（2085，含 143 dpf）但耗时仅 419ms——无悬崖。

## 结论给 M1

gullet 在真语料上行为面干净：零爆栈、回吐近零、速度余量 10×。
两个接线注意项：(1) `\iff`/`\ifthenelse` 走界标档是按名兜底的
语义噪音；(2) 流不可重放——界标 if 与失败 def 会二次消化，分段器
须单遍消费不回头（与 scanner 铁律 1 同构）。
