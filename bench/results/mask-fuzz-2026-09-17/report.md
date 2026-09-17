# mask-fuzz — compile/mask.py 掩码边界对抗测试

> 2026-09-17 收口。交付 `tests/test_fuzz_mask.py`（708 行，commit `58d6230`）：**10 passed + 25 xfailed(strict, 0 xpass)**，ruff 净。scope：`visible_tex`/`mask_tex`/`mask_comments`/`group_end`/`apply_edits`。

## 覆盖

- **span 级 oracle**：独立事件流 + claim 状态机（按位排序的 `\begin`-env/`\verb`/`%` 事件、先到先得、claim 感知的反斜线奇偶活性判定）与 impl 逐字符 walk 字节级一致——2500 随机 token soup × 4 flag 组合（默认/mask_dead=F/keep_verbatim=T/两者）= 1 万次比对。
- **不变量**：等长、字符白名单（原字符|空格）、`\r\n` 位置钉死、确定性。
- **拼接对齐契约**：masked 视图上 regex 命中区间在原串同偏移处字节一致（normalize/probe 拼接地基）。
- **wrapper 映射**：`visible_tex`↔`mask_dead`、`without_comments≡mask_comments`。
- **group_end**：每个开符位显式栈 oracle（2500 soup × 全部 `{`/`[` 站点 + 随机位），边界不变量（pos≤ret≤len、ret<len ⇒ s[ret-1]==closer）、敌意字母表（NUL/`\r`/surrogate/孤 `\`、depth≤130 避开已钉 RecursionError）never-raise。
- **apply_edits**：前向单遍构造 oracle（impl 反向拼接之逆）、换行台账公式 out_nl−in_nl=Σmax(0,repl_nl−span_nl)、序无关、2000 轮。
- 17 敌意 payload × 全 6 函数 never-raise 矩阵；边界语义钉（未闭 env→EOF 掩、行中连续 `\end{verbatim}` 确终止——latex 实证、注释掉的 `\begin` 惰性、孤 `%`、`\verb` 残骸）。

## 缺陷台账（5 族 / 25 钉，全部 latex 实证 tmp/mask-fuzz/texprobe/）

| # | 位置 | repro | 影响 | 修法 |
|---|------|-------|------|------|
| MASK-1 | textutil.py:310 `_env_stop` `\\end\s*\{env\}` | `\end {verbatim}`/`\end\t`/`\end\n` 提前终掩但不终真 env（verbatim 族靠连续 token 序列任意位终止——t2 实证） | 欠掩：真 verbatim 体暴露给下游 regex 手术 | `\s*` 改 `[\ ]*` 或按真 TeX token 规则（12 钉：3 形态 × verbatim/Verbatim/lstlisting/minted） |
| MASK-2 | dead-env end 判定 | 行中 `x\end{comment}` 与 `\end {comment}` 不终止（comment.sty 逐行比对——latex 实证通体仍死）；impl 无锚子串搜提前终 | 欠掩 | end 判定行锚定（2 钉） |
| MASK-3 | textutil.py:327 `_inline_verb_end` isspace→None | 真 LaTeX 在 `\verb`/`\verb*` 定界符前跳 space token——`\verb \|x\|`≡`\verb\|x\|`（cmtt 实证）；`\verb\n` 以换行符本身为定界符→整下行 verbatim（t 实证） | 欠掩；更糟 `\verb \|\begin{verbatim}\|` 假开 env claim 到 EOF→`\begin{document}` 被掩→no_main_tex 级失败 | 定界符扫描按 TeX 空格跳过规则（6 钉） |
| MASK-4 | mask.py:57 `group_end` `%` 注释只 `find("\n")` | `\r`-only 输入（legacy Mac/裸 str 调用绕过 decode_tex）注释吞到 EOF→返 len(s) 非真闭→调用方 splice [pos,len) 删到 EOF | `[\r\n]` 防御在 mask_tex/mask_comments 已有、group_end 是洞；normalize.py:604 以裸文本调用它 | `find("\n")` 改 `[\r\n]` 类搜索（3 钉） |
| MASK-5 | mask_tex 非幂等 | `_LSTINLINE_OPT_RX` `\s*`（textutil.py:303 经 :325）把已掩空白当真空白——二遍定界符扫描跨掩区桥接另一 `\`→f(f(x))≠f(x) 全 4 组合复现。最小例 `\\lstinline %\n\\a\\b` | 违 test_fuzz_textutil 断言的幂等不变量（其字母表缺裸 `\lstinline`+定界符形态） | 已掩区 opt-skip 不可穿（2 钉） |

## 未钉观察

- group_end verb-blindness（`{\verb|}|x}` 早闭）——`\verb` 在命令参数本就非法，病态输入限定。
- group_end(pos>len) 原样返 pos——契约毛边。
- `\begin\n\n{env}`（空行=`\par` token，TeX 不开环境）被 `\s*` 匹配→过掩（安全方向）。
- apply_edits 对重叠/重复区间语义未定义——调用方契约保证不重叠。
- Registry 实测基线：verbatim 族=连续 `\end` 任意位；comment=行锚定。`\lstinline` 跳 space+newline 取定界符是 TeX 正确（t5）——MASK-5 是幂等交互缺陷而非跳过本身。

## Oracle 设计注记

span-oracle 对 impl 语义 bug-for-bug 镜像（同 `\\end\s*` 规格、同 isspace→None），故 property 层保持绿、专捕结构分歧（如旧 offset 过冲族）；TeX 保真缺口全部活在 xfail 钉。
