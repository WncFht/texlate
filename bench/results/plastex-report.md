# plasTeX 3.1 评测报告

库: `plasTeX` (plastex/plastex) — Python 写的**真 TeX mouth/gullet 解释器**,宏展开、catcode、条件求值全实现。
评测数据: `results/plastex-parse.json`。定位:评估其作为**宏展开参考实现/校验 oracle** 的价值,而非直接当解析器。

## 1. 架构分析(源码层)

三段式,忠实复刻 TeX 的 mouth→gullet→stomach:

| 层 | 文件 | 机制 |
|---|---|---|
| mouth(分词) | `Tokenizer.py` | 逐字符读流,`context.whichCode(ch)` 查**动态 catcode 表**;S/M/N 三态空格折叠;`\n\n`→`\par` token;注释字符直接吞掉(不产生 token);`^^X` 转义;控制字 vs 控制符;`\let` 别名经 `context.get_let` |
| gullet(展开) | `TeX.py:__iter__` | 经典展开循环:token.`macroName`→`createElement`→`obj.invoke(tex)`→返回 token 列表 `pushTokens` 回流再展开。`\newcommand`/`\def` → `context.newcommand/newdef` 动态生成 `NewCommand`/`Definition` Python 子类注册进 Context(Context.py:1046/1134)|
| stomach(消化) | `TeX.py:parse` + `Macro.digest` | 展开后 token→DOM 节点树(`plasTeX.DOM`),环境 digest 子节点 |
| 宏表 | `Base/`(TeX/LaTeX 原语)+ `Packages/`(~90 个 Python 实现的包:article/amsmath/natbib/hyperref/…) | 找不到 Python 包时回退解析**真实 .sty/.cls**(kpsewhich+TEXINPUTS)|

**参数 DSL**:`args = '* name:cs [ nargs:int ] [ opt:nox ] definition:nox'` — 声明式签名,`readArgumentAndSource` 按类型 cast(cs/label/ref/dimen/number/nox…)。这是可直接抄进我们签名表的设计。

## 2. Corpus 解析(90 文件,原生配置)

| 指标 | 结果 |
|---|---|
| 名义成功 | **83/90 (92.2%)** |
| 其中**静默截断**(报 OK 但 DOM 只吃到序言) | **~8 个主文件** → 诚实成功率 **~75/90 (83%)** |
| 速度(成功文件) | 中位 29ms,p90 249ms,最大 518ms |
| 失败耗时 | 6ms – **30s**(AttributeError 6ms 快崩;RecursionError/超时 20–30s 慢死) |

### 失败与截断机制(全部实测定位)

**A. 真实 .sty/.cls 加载损坏输入栈 → 静默截断(最恶劣)**

`\usepackage[final]{neurips_2021}` / `\documentclass{IEEEtran}` / `\usepackage{natbib}`:
plasTeX 无对应 Python 包 → `loadPackage` 经 kpsewhich 找到**目录里的真 .sty** → `pushToken(flag)+input(f)` 压栈逐 token 展开整份 sty 源码 → flag/`\endinput`/EOF 路径不齐时 tokenizer 停留在已关闭文件上。
两种结局:
- **静默**:迭代提前耗尽 → `parse()` 正常返回但 DOM 截断(neurips_2021.tex 149KB→5 节点;textContent=1 字符)。**没有任何异常** — 比崩溃更危险。
- **有声**:`ValueError: I/O operation on closed file`(iclr2016 225ms / iclr2022 768ms)。
受害文件全是主文件(ms.tex、neurips_2019/2020/2021、2305/main、1810/main、1906/related 等)。

**B. 解释器深递归**:加载 `algpseudocode.sty` 真身 → RecursionError(tricky.tex 21s;默认 recursionlimit 下更快崩)。

**C. 真 bug**:
- `Base/LaTeX/Math.py:536` — `self.attributes['char']` 为 None 时 `.textContent` → AttributeError(10-Calculus/13-Derivatives 两篇,6–16ms 快崩,与包加载无关);
- `TypeError: sequence item 12: expected str instance, @enumctr found`(custom.tex,20.5s)— 展开产出的非 str token 漏进 `str.join`,同样是输入栈被 .sty 污染后的下游症状;
- `ord() expected a character, but string of length 8 found`(2501.14787/main,`^^` 序列边缘);
- `residual_v1` 原生 30s 超时。

### 决定性实验:屏蔽真实宏包加载

```python
def selective(self, name):
    if name.endswith(('.sty','.cls','.def','.clo','.cfg')):
        raise FileNotFoundError(name)
    return orig_kpsewhich(self, name)
TeX.kpsewhich = selective
```

结果:**此前全部失败/截断文件 → ~89/90,且每个 <0.5s**。
neurips_2021 从 5 节点→5280 节点/113K 文本;tricky.tex 全文 495ms 过(algpseudocode/xparse/subcaption 变 UnrecognizedMacro 兜底);`\input` 仍工作(只挡 .sty/.cls 不挡 .tex)。**架构含义:Context 对未识别命令有 `UnrecognizedMacro` 动态类兜底(Context.py:643)——挡住"真解析"这条慢死路径后,兜底路径又快又稳。**
剩余唯一失败:10/13 两篇的 Math.py:536 AttributeError(真代码 bug)。

## 3. Fixtures(变体上 DOM 断言;tricky.tex 原生需去 3 个 .sty)

| ID | 结果 | 实测行为(与 TexSoup 的本质区别) |
|---|---|---|
| T01 `\be..\ee` | **PASS** | **真展开**:DOM 里就是 `equation` 节点,`\wt`→`widetilde` 节点。eq.source=`\begin{equation} \widetilde{A} = \Tr (M^2) \end{equation}` |
| T02 `\dR` | **PASS** | →`mathbb` 节点;textContent 呈 `R`(文本中 `\dR{}` 也展开) |
| T03 `\def` | PASS | `Definition` 类注册进 Context;`\Tr` 调用点展开 |
| T04 natbib+ref 族 | PASS | 全部成节点(natbib.py Python 包实现),按 tag 过滤即可 |
| T05 section[Short]{Long} | 半PASS | harness 的 textContent 断言 FAIL;实际标题在 `attributes['title']`(TeXFragment)— DOM 语义化、参数已归位,断言口径修正后算过 |
| T06/T07 verbatim/lst/verb/url | PASS | verbatim catcode 切换(`setVerbatimCatcodes`),单行 `%` 无恙 |
| T08 注释/`\%` | PASS | tokenizer 直接吞注释(不会出现在 DOM,也不译) |
| T09/T11/T12/T18/T20/T22/T23/T24/T29 | PASS | |
| T13 `\ifdraft` | **PASS(真求值)** | `\newif`+`\drafttrue`→`processIfContent` 选分支:**draft 支进 DOM,final 支消失**(textContent 验证:draft=True, final=False) |
| T14 `\input` | 半 PASS | `\input{sub/intro}` 展开成功(kpsewhich+TEXINPUTS=文件目录);注释掉的 `\input` 正确忽略;**但 methods.tex 里再 `\input{sub/nested}` 失败** — `kpsewhich()` 每次以"当前文件目录"重建 TEXINPUTS 且用后还原(TeX.py:1336-1352),嵌套 include 的相对路径按主文件目录解析会错位 |
| T16 xparse | 原生 FAIL | `\usepackage{xparse}`→真 expl3 源码→崩;屏蔽 .sty 后整个文件 495ms 过(`\vect` 不展开但不崩) |
| T25 `\@ifnextchar` 区 | **PASS** | 真 catcode 切换 + 真条件宏 — TexSoup 崩溃处,plasTeX 无事 |
| T26/T27/T19/T17 | PASS | |
| round-trip | **FAIL(设计如此)** | doc.source 3012B vs 源 4346B:注释消失、空白折叠、命令名后统一补空格(`\Tr (M^2)`)— **重建式 source,非源文本映射** |

tricky-209(LaTeX2.09):**OK**,`\beq..\eeq`→equation 展开;`\documentstyle` 变未识别宏无碍。
tricky-multi:`\input`/`include` 一级展开成功,注释行正确排除,嵌套层失败(见 T14)。

## 4. 提取与泄漏(DOM 层面)

document 后代按 tag 过滤数学/verbatim/cite 族后提取:**77 块,0 泄漏** — 但这是" trivially clean":DOM 已是展开后语义树,数学被节点类型隔离,textContent 本身丢数学内容(equation 的 textContent=`A = (M2)`,`^`/`_`/分数线全丢)。**plasTeX 输出不能直接当翻译文本**(数学保真差、无 source 映射),它的块干净是因为信息已经丢完了。

## 5. 对我们管线的可复用性评估

**不能直接当解析器/半解析器用**,三条硬伤:
1. **无源码 position**:token/节点只有 `lineNumber`,无字符偏移 — 区间重建无从谈起。
2. **round-trip 失真 by design**:注释丢、空白折叠、`\cmd ` 补空格 — 做不了占位符回写。
3. **脆性在真实文件路径**:.sty 加载静默截断(无声丢 95% 文档)比异常更危险;嵌套 `\input` 路径错位;成功文件快但失败路径 21-46s 慢死。

**但作为"宏展开参考实现"价值极高**,可抄的设计点:
1. **mouth/gullet 分离是唯一正解**:我们的半解析器若加宏层,必须是"token 流上可回压(pushTokens)再展开"的 gullet 模型,而不是在字符串上替换 — TexSoup 缺的就是这一层。
2. **动态 catcode**:Tokenizer 每字符 `context.whichCode` 查表 → `\makeatletter`/verbatim 区天然正确。我们至少要 catcode 切换点(\makeatletter/@verbatim)支持。
3. **展开=token 列表替换**:`NewCommand{definition-token-list}` + `Definition{args-profile+definition}` 两类型足够覆盖 `\newcommand`/`\def`;`\def` 的参数模板(token 序列匹配)是带分隔符宏的样板。
4. **条件求值 `processIfContent`**:`if/else/or/fi` 嵌套扫描分 case 回压(TeX.py:531-585),`\newif` 真定义 — 我们 `\if` 处理可照抄这个 case-scan。
5. **args spec DSL**:`'[ opt:nox ] definition:nox'` 声明式参数签名 + 类型 cast(cs/label/nox/expanded)——比我们手写命令表优雅。
6. **UnrecognizedMacro 兜底**(Context.py:643):未识别命令动态建类、按默认 spec 继续 — 容错哲学与 TexSoup 相反但互补,证明"不展开≠不解析"。
7. **当 oracle**:在 corpus 上跑 plasTeX(屏蔽 .sty),拿它的 DOM 校验我们自己的宏展开器 — `\be`→equation、`\ifdraft`→draft 支、`\dR`→mathbb 这些 ground truth 它都能给。

改造提示(若要把 plasTeX 当展开 oracle 产品化):`TeX.kpsewhich` 一行 patch 屏蔽 .sty/.cls 是必要条件(89/90、单文件 <0.5s);`\input` 的 TEXINPUTS 嵌套 bug 需再 patch;Math.py:536 的 None-char 是已知会踩的雷。

## 附:数据文件
- `results/plastex-parse.json` — 90 行 {file, ok, error, ms, nodes, equations, textlen}
- 复现脚本: `bench/py/plastex_bench.py`, `scratch/plastex_probe*.py`, `scratch/plastex_dom.py`, `scratch/plastex_nokpse.py`, `scratch/plastex_timing.py`
