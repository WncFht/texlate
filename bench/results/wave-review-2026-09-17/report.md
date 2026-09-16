# wave-review — 本波全部产品代码 delta 回归审查

> 2026-09-17 收口。只读终审：`tmp/wave-review/full.diff` 全 66 文件过完 + HEAD 对照 + `tmp/wave-review/` 探针实证（gitignored）。零代码改动。**整体判定：本波改动质量可放行——零确认回归。**

## 发现（全部低/info，无确认回归）

- F1 info｜src/texlate/arxiv/unpack.py:244 — corrupt-stream 检查只拦「成员界后非零块」；成员边界恰为全零 512 块的中途坏流仍静默截断。系文档明示的接受残留（9702009 真实包形态），非本波新引入风险。
- F2 low｜src/texlate/compile/engine.py:869 — `_rc_to_signal` 把 bwrap/sandbox-exec 下 rc∈(128,192] 一律解码成信号；进程若故意 `exit(141)` 会误记 SIGPIPE。但下游 `_salvage_driver_fatal`(engine.py:954) 只在 killed_signal 置位时把 stdout_tail 里真实 `fatal:` 行补进 errors——误报代价是归因噪声而非误判，POSIX 包裹层惯例下解码方向正确。
- F3 info｜src/texlate/latex/tables.py:694 — `looks_like_colspec` 漏 `*{n}{spec}` 纯 array-repeat 列型（组剥后只剩 `*`、无列字母 → 不判列参）。新启发的 miss 退回特性前行为，非回归。
- F4 low｜src/texlate/latex/macro_table.py:184 — env_end 尾匹配放宽后，`\def\foo{\begin{X}\end{X}}`（无文本平衡对）登记为 ENV_END：调用点只发 end 标签、begin 半被吞（探针实证：env 外调用产 stray_end，identity 不破）。真实文档极少定义纯对壳宏，前缀闸的设计意图（挡 `\begin{c}Hi\end{c}` 形）已验证生效。
- F5 info｜segmenter `\end\n\n{name}` 收集 — par 后 `{name}` 恒被当 env 名吃掉，即便原是文本组；探针两方向均 stray_end+identity OK，选择与本波测试意图一致。
- F6 info｜unpack.py:375 `_safe(ln)` — `TarInfo.linkname` 实际永为 str（默认 ""），`not ln` 分支内 `_safe` 无 None 暴露面。

## 净面（逐段确认等价/正确，机理+证据）

- **benchlib/stagerun/parsebench 本段净**：`iter_jsonl` 跳过坏行容忍截尾、`load_records` last-wins、`atomic_write_text` tmp+replace 语义等价；`is_done`/`load_latest` 同 `(pid,arm,upstream)` 三键、recode 比 `code==_code_stamp()`、`xlat_ts↔marker.ts` 带 `mts is None` 保守回落（stagerun.py:183-207,1165-1181）；`base_rec` 含 `metrics:{}`；`aggregate` recon 键集 {strict,normalized,diverged} ≡ `classify_recon` 全部产出词表，无静默丢档。
- **arxiv 段本段净**：`_NEW_ID_RE`/`_OLD_ID_RE` 锚定与 app 旧拷贝逐字节同；`_unique_rename`≡`_zip_unique`；`_MEMBER_ERRNOS`{ENAMETOOLONG,ELOOP,EEXIST,ENOTDIR} 只把成员级 IO 病态降级 reject_io、全局错仍上抛；`_dir_member` pending-hardlink drop 序经推演等价；`_claim` casefold/dup_member_overwrite 分流正确。
- **xlat/client 段本段净**：`_LOOPBACK_HOSTS`/`_TAILNET_V4` 与删除拷贝逐字同；`DEFAULT_MODEL` 派生链 intact；FreeModel 四处构造全显式 kwargs，删 `max_output_tokens` 无 `**stored` 反序列化面（旧 `int(m.get(...))` 缺键本就炸）；ratelimit `report()` 实测 429+406 同计 strike（ratelimit.py:242）。
- **server 段本段净**：worker `_flush_translate` 全 2 调用点同步（1963/2025）；`_log_text_of` .log→stdout_tail 回落与 e2e 同款；`_share_pool` 污染守卫 + `index_lookup` 实抛面仅 OSError/UnicodeDecodeError → ShareError except 删除正确；`_probe_target` 在 copytree(zh_dir 已注入) 后跑 = e2e `_probe_flags_of`(post-`prepare_chinese`) 同序（worker.py:3176-3178 vs e2e.py:994-1006）；babeldoc `_Feed.errors` deque 全部消费点（`in`/append/`[-1]`/`isinstance(msg,str)`）deque 兼容；app.py 全部 body 读取走 `_read_body`/`_parse_multipart` 且 `_cap_request_body` 双闸，`request.stream()` 绕过面为零。
- **share.py 段本段净**：`_key_parts`/`share_key` 逐组分 `.strip()` + version 走 `_norm_version` 全对齐（share.py:105-177）；pack_share 单读消 TOCTOU + `.tmp`+rename 原子发布；`writestr` 仅 mtime 元数据差（消费端按 manifest sha256 校验，无契约影响）。
- **compile 段本段净**：`_ERR_FILELINE_RE` 逐字同 logparse 旧拷贝；`RouteDecision.reject` 字段保留默认 None（engine.py:1697），e2e:1073/worker:1769 死检查仍是预留消费点；`missing_char_fix` char_table 合并 `e["id"]` 键 + `_mc_hit` 全 `.get` 面与 rules.yaml:3428 条目（id+cps hex+replace）完全兼容；`prepare_legacy_latin_fonts` 判定正则与注入定位正则逐字同一形（normalize.py:576/602）。
- **latex/segmenter 段本段净**（探针实证）：`tmp/wave-review/probe_seam.py` 20/20 identity OK——`_rappend` 接缝 `" "` 注入在 csname 合成/乱序 token + 空格/换行/注释/tab/par 五种 gap 下全部不破 reconstruct（注入只在真实分隔字节已入 ident 轨时触发）；`probe_r18.py` 覆盖 `\end\n\n{name}` par-then-name、`\input \cs` 动态名吞并（无 chunk 泄漏）、裸 `\tikz …;` 保护、未注册 env colspec 启发，全绿；`_handle_input_cs` cs 分支 `fname` 先于分支绑定（3685 行初始化）无 NameError；`Tok.pos`=(fid,start,end)，`_eat_env_args` colspec peek 切片 `x.pos[2]:closer.pos[1]` 恰为花括号间内容；`_grp_find_env_end` csname 臂 `collected[:-(len(ctoks)+2)]` 簿记精确、`str(Tok)` 名拼接与 gullet `_read_csname` 同约（空格 token 两侧同贡献 `" "`，镜像忠实）。
- **e2e 段本段净**：`_scan_tree` 四元组 rel-posix 口径、`_l2_parse` 文本优先修 0 字节 log、`_run_fixloop` 新 kwargs + `judge(log_text=)` 接线签名全对；`_repair_chain` 更新序等价。
- **e2e_mock 本段净**：`translate_tree` 复用 `e2e._scan_tree`/`_env_judge_pass`/`_TreeRun`/`_split_cid`/`_delivered` 原件，签名全部对位。
- **删除符号面净**：`HIDDEN_PROMPT_TOKENS`/`max_output_tokens`/`source_type`/`ensure_deps` 全仓零活读者（仅测试 fixture payload 与 docstring 提及）。
- **测试钉定面**：本波新测试（test_fuzz_* oracle、segmenter R 系列、worker/app 边界）钉的是新行为而非仅存量——覆盖率合格。

## 在飞面注记

F1/F3/F4 落在 unpack/tables/macro_table——后两文件属 latex/** 在飞 lane，但三处发现均对当前 HEAD 实证成立、非 workspace 中间态幻觉；texlog.py hunks 审计时按在飞对待、未见冲突。F2/F4 是文档化的语义取舍，F1/F3 是新特性的已知残留缺口（miss 均退化为特性前行为）。
