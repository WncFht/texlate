# texlog-popped — popped 捕获链路补通到数据模型层

> 2026-09-17。scope：texlog.py + fixloop/logparse.py + compile/engine.py（仅 file_stack/popped 行）+ 三测试文件。433 测试绿、ruff 净。

## 消费端接口契约（fixloop 消费侧按此对齐）

**`ErrReport.popped_files: list[str]`**（`src/texlate/compile/fixloop/logparse.py:71`）与 **`LogInfo.popped_files: list[str]`**（`src/texlate/compile/engine.py:118`）——同名字段同语义：

- 类型：`list[str]`，默认 `[]`；dataclass 字段，`slots`/`__init__` 兼容（无位置构造方，加字段零破坏）。
- 语义：**首错行位之前已弹出的文件名，按 pop 序**——与 `file_stack`（首错时仍打开）同位快照，互为补集语义：一个仍开、一个已关。`popped_files[-1]` = 错误报告前最近关闭的文件 = runaway/EOF 类错误的肇事候选（#78：`File ended while scanning` 报位在父文件续行，`)` 先于错误行打印）。
- `None` 非文件配对帧**已滤除**（字段只含文件名 token，保留 `./` 前缀，与 `file_stack` 元素同形态——消费端按 endswith/路径判定用）。
- 无错误或首错前无弹栈 → `[]`；首错**之后**的弹栈不入列（前缀语义，测试已钉）。

## 原语层（消费端如需自驱重放）

`file_stack_at(lines, stop, popped=None)`（`src/texlate/texlog.py:124`）新增可选 out-param：传 list 则重放全程弹栈按序追加，**含 `None` 配对帧原样透传**（滤除是消费端职责——原语层与 `update_file_stack` 同口径）。不传 → 行为与旧签名完全一致，现有调用面（logparse/l2/tests）零影响。

## 改动文件

- `src/texlate/texlog.py` — `file_stack_at` 加 `popped` out-param（`update_file_stack` 本体未动）。
- `src/texlate/compile/fixloop/logparse.py` — `ErrReport.popped_files` 字段 + `parse_text` 接线（`file_stack_at(lines, first_i, popped)` → 滤 None）。
- `src/texlate/compile/engine.py` — `LogInfo.popped_files` 字段 + `_scan_error_lines` 接线（popped 全程累计，首错捕获点与 `file_stack` 同位快照滤 None）。仅动 file_stack/popped 相关行。
- `tests/test_texlog.py` — +3 用例（runaway 捕获、None 透传、默认签名回归）。
- `tests/test_fixloop_logparse.py` — +3 用例（runaway popped_files、None 过滤、无错为空）。
- `tests/test_compile_engine_judge.py` — +2 用例（runaway + 首错后弹栈不入列的前缀语义钉桩、None 过滤）。

## 验证

- `uv run pytest tests/ -k "texlog or logparse or fixloop or l2 or engine_judge"`：**433 passed, 1 skipped**。
- `ruff format --check` + `ruff check`（select=ALL）× 6 文件：**全净**。

## 消费侧提示（给 项目体验方式）

`llm_hook._resolve_err_file` 类 runaway 场景可在 `file_stack` 顶→底遍历未果/为空时，改试 `reversed(rep.popped_files)` 找最近关闭的工程文件。`engine.py:829 _requester_paths` 的 `file_stack[-2:]` 兜底段同理可并 popped 尾段。

## leader 复核备注

- diff 逐 hunk 对账：三源文件全为 popped 相关行，无夹带（compile/engine.py 此前 dirty 的别家改动已在更早 commit 落库，当前未提交 diff 仅此特性）。
- popped 全程累计（engine）vs 前缀快照（logparse）语义一致——engine 在首错捕获点落快照，logparse 在 first_i 停重放，两字段同为「首错前弹出」。
