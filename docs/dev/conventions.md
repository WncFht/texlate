# 代码注释与命名规约

贡献者写注释、起新名、改旧名都先读这里。词汇登记表（冻结名/域词/撞名表）在 `../spec/glossary.md`——本文件管规则，那文件管名册。

## 1. 注释引用纪律

- **禁引 `tmp/` 路径作证据源**。`tmp/` 是 gitignored 临时区，清仓即断链——「见 `tmp/x/y.json`」式引用全是定时化石。持久证据指针用 `git show <sha>:<path>`（挂 commit）或已入库仓相对路径。
- **跨文件锚写「模块 + 符号名」**（`kernel.ledger.emit`、`Ctx.emit_case`），不写裸行号。`file:L###` 行号只在「当时取证」语境允许，且必须带 commit 锚（`foo.py@abc1234:L123`）——否则拆包即漂。
- spec 节锚（`docs/spec/x.md §N`）允许且推荐——spec 名不带日期、天然稳定。
- 「当前/现行/现在」状态句带日期戳（`（2026-09 时点）`），不给读者猜时效。
- 战役/波次代号（`Wave-F`、`第N波`、`soak-N`）不进新注释——用日期或 run 名。史注（描述当日做过什么）保留原词无妨。

## 2. 命名纪律

- **新数据键 / epoch / run slug / 产物目录名一律日期戳**：`@YYYY-MM-DD`、`-YYYY-MM-DD` 后缀、`<date>/<slug>` run 形态。禁编号代号作新标识符。
- **版本语义用功能 slug**：名字自说明用途（`patchseams`/`in_env_args`/`armedId`），不靠代数后缀（`v5`/`l2`/`tier3` 承载语义即埋雷）。数字只在即协议号处合法（HTTP/2、LaTeX2e、Python 3.12 这类外部定名）。
- **同名新规**：跨包/跨域同名文件必须 (a) 两侧 docstring 互辨、(b) 登记 `spec/glossary.md` §3——2026-09 普查已存三缝组（`patchseams`/`worker/seams`/`_docseams`）与 `decls.py` 双件等实例。
- **域词不挪用**：`arm`/`格`/`波`/`缝`/`zone`/`tier`/`clean` 等已有约定义项的词（`glossary.md` §2）不另起新义；新语义起新名。

## 3. 冻结面

改任何名前查 `glossary.md` §1：ledger/events 键、`payload` token（`sentry:` 等）、metrics 键、vault 拼写、数据目录名、`spec_hash`/`fp` 材料全部冻结——只能加读侧兼容别名。疑似落盘键先沿产出路径追到落盘点再动；测试断言到的键同样按冻结处理（断言跟着 wire 格式走）。

## 4. 注释写法基线

- docstring 写契约与 why：不变量、隐藏约束、绕过后果、跨件协作关系。不复述代码已自明的 what——好名字替代注释。
- 引用 wire 名（ledger 键/字段/token）用 `` `backtick` `` 包裹——表明是字面量而非比喻词。
- 退役系统名（`corpus_daily`/`daily_arxiv`/`errsweep`/`gwcap`）只许出现在退役注记语境；不得以现役口吻引用其路径/接口。
- `# noqa`/`# type: ignore` 豁免须同行注明理由（仓现行约定，`ruff select=ALL` 配套纪律）。
- 测试名/夹具名同属标识符面：自说明域语义（`test_dossier_selftest`），不带批次编号。
