# l2 合成边界缺口侦察（2026-09-17）

派工口径：validate/l2 合成边界用例缺口的可补面。**只产报告，src/git/tests 未动**。

## 结论先行

l2 判定面的**错误计数双格式**覆盖已扎实（入库 fixture 12 件 + 合成 + 三层 agree fuzz），裸奔集中在 **warning 分类侧的三个零覆盖分支**——其中两个是红线相关：(a) `file_not_found` 红线类（missing_graphic canonical）**全仓零正向断言**；(b) `file:line:` 前缀 Warning 的 l2 侧排除（只在 fixloop 层有测，l2 是平行 regex，生产 `-file-line-error` log 此形态海量，回归即 n_errors 膨胀全判 dirty）；(c) `rerun` 类零正向。另有 7 个小面可顺手补。

## l2 判定面全景（parse_log_text 单遍扫描）

| 域 | 分支 | 位置 |
|---|---|---|
| 错误计数 | `^!` 经典行 | `_BANG_RX` → `_match_error_line` |
| | `file:line:` 行（任意扩展名、`:`/空白/`(`/`)` 排除） | `_FILE_LINE_RX` |
| | `file:line:` 豁免（msg 锚定 `(LaTeX\|Package\|Class)…Warning` 或 `==>`） | `_NONERR_FILELINE_RX` |
| | 消息面严判（`: ` + `\S`；空消息/无空格/tab 拒收） | `_FILE_LINE_RX` 组 3 |
| 首错定位 | ctx ≤8 行 / `l.NNN` 提行号 / file_stack 快照 | 主循环 + `_tex_line_from_ctx` |
| | `eof_file` runaway 归因（pop ≤16 行窗） | `_eof_culprit` + `_EOF_POP_WINDOW` |
| | `_MAX_STORED_ERRORS`=200（n_errors 仍精确） | 主循环 |
| warning 分类 | 预筛（`Warning:` 标记 / markerless 硬 warning 形） | `_ANY_WARNING_RX` + `_MARKERLESS_WARN_RX` |
| | 10 类：invalid_utf8/missing_glyph_nullfont/missing_glyph/citation/reference/rerun/font_subst/file_not_found/overfull/generic | `_WARNING_RULES` 有序首中 |
| | missing_glyph 码点细分：U+FFFD→fffd_glyph、CJK→missing_glyph_cjk+cjk_missing | `_MISSING_CHAR_RX`（`("HEX)`/`(U+HEX)` 双形） |
| | 红线打标：invalid_utf8 按栈归因（sys/dos-eps/usertree 降 sys_hits），其余类全量入 redlines | `_mark_redline` |
| | samples 每类 ≤5 / by_class·total 精确 / redlines·sys_hits 去重 | `_classify_warning` |
| verdict | ok=n_errors==0 / log_missing（不存在+OSError）/ engine 签名 / tail 30 | `L2Verdict` / `parse_log` |

## 现有覆盖对账

| 分支 | 覆盖 | 证据 |
|---|---|---|
| `^!` 计数 + l.N 提行 | ✅ | fixture×2 + 合成 + bench 门控真 log |
| `file:line:` 计数（含非 tex 扩展名） | ✅ | 合成 + fileline-only/非扩展名 fixture |
| 双格式混合不双计 / `==>` 豁免 | ✅ | dedicated + fixture |
| **`file:line:` Warning 豁免（l2 侧）** | ❌ **裸奔** | 仅 fixloop 层有测；l2 `_NONERR_FILELINE_RX` 是平行实现无断言；三层 agree 集只含真错侧变体 |
| 消息面严判拒收 / 锚定豁免不误伤 | ✅ 旁证 | `_ERRLINES_AGREED` 三层一致断言钉住 l2 值 |
| ctx≤8 / tail30 / cap200 / engine 三态 / log_missing（不存在） | ✅ | fixture+dedicated+fuzz |
| eof_file runaway | ✅ happy path only | 窗界/非 EOF 相邻 pop 裸奔 |
| citation/reference/font_subst/overfull(Over)/missing_glyph/nullfont/cjk（双形）/fffd（双形） | ✅ | 合成 + manifest |
| **file_not_found 类（红线）** | ❌ **零正向** | fixture 里的 `File 'x' not found` 全是 `!` 错走 error 路径；warning 形态无一断言 |
| **rerun 类** | ❌ **零正向** | 仅 rerunfilecheck Info 负向 |
| invalid_utf8 归因四态 | ✅ | 4 个 dedicated tmp_path 用例 |
| error-ctx 帮助文本豁免（`type 'I\font…'` 旧坑） | ❌ 裸奔 | 注释记录的 regression 无 pin |
| Underfull 正向 / samples≤5 / 去重 / OSError→log_missing / 畸形码点 / eof 窗界 | ❌ 小面 | — |
| texlog 栈/归因件 | ✅ | test_texlog + fuzz 厚覆盖 |

## 真实世界高频未覆盖形态

stagerun-loop1 6573 格：missing_graphic 全轮 28 cat + warnings 面 **186 次**——warning 形态在生产语料实存。更关键：bench 语料不带 `-file-line-error`（l2 docstring 自证），而**生产引擎按 docs/08 §4.1 带旗标**——生产 log 里 `./x.tex:N: LaTeX Warning: …` 海量存在，该豁免是**每编译必走**分支，l2 零断言意味着 regex 回归即全判 dirty 且无测试报警。风险权重最高的洞。

## 可补清单（按优先级）

| # | 缺口 | 合成构造法 | 预期判定 | 量 |
|---|---|---|---|---|
| 1 | file:line Warning 豁免（l2 侧） | `parse_log_text("./main.tex:12: LaTeX Warning: Reference …\n./sub.sty:3: Package foo Warning: bar\n! real\nl.1 x\n")` | n_errors==1；Warning 行归入 by_class 不计错 | 小 |
| 2 | file_not_found 红线类正向 | `Package pdftex.def Warning: File 'fig.pdf' not found on input line 9.` + `LaTeX Warning: File 'x.png' not found …` | by_class file_not_found==2 + redlines 各一条 | 小 |
| 3 | file_not_found 变体 | `cannot open file for reading` / `Could not locate …` | 同类归入（pattern 后两备选） | 小 |
| 4 | rerun 类正向 | `LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.` | by_class rerun==1 非红线 | 小 |
| 5 | error-ctx 帮助文本豁免 | `! Undefined control sequence.\nl.5 \\x\ntype 'I\font<same font id>…'` | warnings.total==0（旧 font_subst 误吃坑 pin） | 小 |
| 6 | eof_file 窗界+非 EOF | pop>16 行才出 File ended→None；相邻 pop+普通错→None | 防过归因/窗漂移 | 中 |
| 7 | Underfull 正向 + 裸 Warning: generic | `Underfull \vbox…` / `Foo Warning: bar` | overfull+1 / generic+1 | 小 |
| 8 | samples≤5 上限 | 7 条同类 warning | samples len==5、by_class==7 | 小 |
| 9 | sys_hits/redlines 同件去重 | 同文件 invalid_utf8 ×2 | sys_hits 单条 | 小 |
| 10 | OSError→log_missing | `parse_log(目录)` | log_missing 不抛 | 小 |
| 11 | 畸形码点留 missing_glyph | `("12)` 3 位 hex 不中 regex | 仍 missing_glyph 红线 | 小 |

备注：全部用 `parse_log_text` 内联合成即可；若要真实样本，production `-file-line-error` log 是现成来源。

30min 内交付。侦察：l2-scout（sid8 代写落盘）。
