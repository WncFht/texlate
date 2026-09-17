# probe-fuzz — compile/probe.py 对抗性 property tests

> 2026-09-17 收口。交付 `tests/test_fuzz_probe.py`（~960 行，commit `a59fbb6`）：**11 passed + 8 xfailed(strict)**，ruff check/format 双净。全离线（注入 mini TlpdbIndex）；scratch `tmp/probe-fuzz/`。

## 覆盖矩阵

- **结构化树等值层**（seed 20260917，140 iters）：生成侧声明日志 + `visible_tex` 边界 offset 独立 oracle，全字段精确对拍（BFS inputs 序/deps 集/missing 多重集/tl_packages/prefer_engine/flags）。实测命中：多文件 BFS 82/140、missing 112/140、tl_pkg 81/140、xelatex 72/140、latex209 13/140、平均 5.85 deps/iter。覆盖 masked 声明、`\endinput`-先于-`\begin{document}`、no-doc、dead-tail、bare `\input`、cwd=main.parent 解析。
- **对抗永不抛层**（320 iters）：randbytes/截断/空文件/目录冒名 .tex/PDF 头垃圾 × main_rel 对抗池（`""`/`"."`/`".."`/`/etc/passwd`/missing）——恒不抛 + 逐字节确定 + 结构不变量。
- **deps_diff/dep_seen oracle 层**：2500 iters 路径汤对拍独立 `_o_norm`/`_o_match`；`dep_seen≡deps_diff([],rec).saw` 恒等；recorded=None 三值；superset 单调性 800 iters；generator-iterator 等价。
- **定点钉**：workdir 不存在/是文件、`TlpdbIndex.ensure` 炸→index_available=False+未证实 missing 仍录+note、逃逸 symlink→missing、optional tl_pkg 仍列、绝对 main_rel 在 root 内归一、signal 决策表（minted 裸用→-shell-escape/prefer None；+frozencache→tectonic/无 flag；叠 .eps→xelatex 压 tectonic；pstricks→xelatex；bbm→tectonic_risky note 不动 prefer）。

## 缺陷台账（6 项，8 个 strict xfail 钉）

| # | 缺陷 | 位置 | 影响 | 修法 |
|---|------|------|------|------|
| D1 | dedup 早退吞 missing | probe.py:178 | `\InputIfFileExists{g}`+`\input{g}` 同键 → 引擎将 missing_file 而 rep.missing 无 g.tex | 早退前仍记 missing（missing 与 dep 去重解耦） |
| D2 | `tex.read_bytes()` 无 OSError 兜底 | probe.py:213 | chmod-000 → PermissionError 穿透（route_project engine.py:1755 有守卫，probe 没有）→ fail-open 下全情报塌成 "probe crashed" | 读文件处 try/except OSError 跳过 |
| D3 | `resolve()` 遇 symlink 环抛 RuntimeError | probe.py:143/294 双可达 | input 名侧 + main_rel 侧 | resolve 边界捕 RuntimeError |
| D4 | `is_file` stat 的 ENAMETOOLONG(Errno36) 不在 ignore 表 | probe.py:143/294 | 300 字符名两侧穿透 | 文件探测边界广捕 OSError |
| D5 | main_rel 含 `\x00` → ValueError | probe.py:294 | resolve→realpath→lstat（input 侧 NUL 已被 _clean_name 滤，仅 main_rel 可达） | resolve 前 NUL 预检或捕 ValueError |
| D6 | 带点包名 suffix 启发式双向错 | probe.py:154 | `Path("weird.dotted").suffix` 当有后缀——LaTeX 实找 `weird.dotted.sty`：裸文件在场→假 local，.sty 在场→假 missing | package/class 恒补 .sty/.cls（已该后缀除外） |

## 未钉观察项

- **O1** dead-tail 非对称：`\endinput` 与 `\begin{document}` 间 pkg/class 声明仍被扫（preamble 边界是 begin{document}，dead-tail 只闸 inputs）——保守多报，符合 impl 意图。
- **O2** input 类 dep 名带信号名（`\input{style/minted.sty}`）按 dep.name 触包信号表——可辩护（代码确实载入）。
