# texlog-sweep — texlog.py 残余审计+小修

> 2026-09-17。scope：`src/texlate/texlog.py` + 新建 `tests/test_texlog.py`（此前模块级原语无专属测试，只有消费方覆盖）。已与 judge-redline 报告对齐——invalid_utf8 归属逻辑不重复动。

## 确凿修复（2 项）

**1. `Missing character` 字面括弧字形污染文件栈（真 bug，语料实证）**

真实 bench log 里存在 `Missing character: There is no ( in font nullfont!` / `no ) in font nullfont!`（nullfont 缺字符，数字样式/leader 构造常见）。字形 `)` 会**误弹真文件帧**，`(` 留幻影 None 吃掉后续真闭括弧——双向都能把 invalid_utf8 归属翻转（工程帧被弹→警告落到系统帧→红线误降；或系统帧滞留→工程产警告误判系统）。

修法：`_MISS_CHAR_RX` 位置级跳过字形——只认 `There is no X` 后跟空格/`(`/行尾的单字符形态；`(U+0029)`/`("0029)` 码位形态括号自带配对不受影响（专门测试防误吃）。不改配对语义、不整行跳过（真 `)` 与消息同行的情况不丢）。

**2. 无括弧行早退（perf）**

`if "(" not in ln and ")" not in ln: return`——大多数 log 行无括弧，substring 检查 C 速。4.3MB 合成 log 实测 0.143s→0.042s（~3.4x）；含 25% missing-char 行的极端混合仍 1.5x。零行为差（popped 语义也不受影响）。无 O(n²)——三消费方均单遍，`file_stack_at` 每次 parse 只回放一次。

## 改动文件

- `src/texlate/texlog.py`：+`_MISS_CHAR_RX` 常量、`update_file_stack` 早退 + skip 位置集
- `tests/test_texlog.py`：新建 16 例（missing-char 四形态、配对不变量、popped 顺序、引号路径降级、is_project_file 直测、looks_like_tex_file 边界）

## 测试 + lint

- `pytest tests/test_texlog.py`：16/16 过
- `pytest tests/ -k "texlog or engine or probe"`：150 过 1 skip
- 消费方回归（l2/logparse/fixloop_cases/worker_audit/engine_judge/engine_fp 合跑）：156 过 1 skip
- `ruff format --check` + `ruff check`：两文件全净

## 观察项（未修，按纪律列出）

- **fixloop/logparse 臂缺 l2 的 eof_file runaway 修法（#78 同源）**：`file_stack_at` 不暴露 popped，runaway 错（`File ended while scanning`）的 file_stack 报父文件非肇事件；下游 `llm_hook.py:163`/`fixloop/engine.py:829` 用它选修复目标文件 → 可能修错文件。texlog 侧给 `file_stack_at` 加 popped 捕获是平凡扩展，但消费改动属 fixloop 在飞方——建议 leader 路由。
- `l.N` 源文回显行可带不配对括弧（两个方向都有害），但真文件闭括弧常与回显同行——行级无法区分，留文档化近似。
- 引号路径 `("./dir with space/x.tex"` → token 截在空格落 None 占位（配对不破、归属降父级=保守）；本仓 workdir 无空格路径，罕见。
- 79 列折行劈文件名：前半带扩展名→幻影帧恰好一行（还进 popped，留下窄 eof-culprit 误归因窗）；无扩展名→None。行级扫描固有。
- 折行劈进 `There is no ` 内部的 missing-char 仍漏一个字形括弧——需跨行状态，超本模块单行契约。
- 相对 `./_texmf/`、`rel/texmf-x/` token 先于 sys 检查归工程——生产 texmf 路径皆绝对，近乎不可达。
- engine `_ERR_FILELINE_RE`（`^\S+?:\d+: \S`）无 tex 扩展名闸，l2 有 `looks_like_tex_file` 闸——错误计数口径微差；engine 是只读消费方，未动。
- 死代码核查：无。`__all__` 全被消费（file_stack_at→logparse；update_file_stack/is_project_file→l2+engine；looks_like_tex_file→l2；TEX_FILE_EXTS 内部自用兼公共常量导出）。
- 静默路径：l2 `parse_log` 缺失/OSError→`log_missing=True`、logparse 缺失→空 ErrReport，均文档化设计；texlog.py 本身纯函数无吞错。
