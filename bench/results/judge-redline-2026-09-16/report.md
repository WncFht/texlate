# judge-redline — invalid_utf8 红线限缩到工程文件源

> 2026-09-16。scope：texlog/engine/judge/l2/e2e/benchlib + 两测试文件。6 文件 +160/−35，定向测试 111 过，全仓残余 2 红均为别家在飞断面（argspec_dispatch、zzprobe_tmp）。

## 问题

`invalid_utf8` 警告此前一律计入 verdict 警告面 → partial 红线。但大量命中来自**系统 texmf 树**（fontspec/unicode-math 内核按字节扫高端码位），生产者是系统文件而非工程文件——用户论文被判脏是冤案。

## 改动

- `src/texlate/texlog.py`：新增 `is_project_file(token, root)` 原语 + `_SYS_TREE_RX`。系统树标记**先于** root 前缀判定——`wdir/_texmf` usertree 虽在 workdir 下仍属系统树；`/Tectonic/`（大小写敏感）与 workdir 小写 `tectonic/` 正确区分。
- `src/texlate/compile/engine.py`：`LogInfo.warnings_sys` + `CompRes.workdir` 字段；`parse_log(log_text, *, project_root=)` 按 file-stack 最内层帧归属 invalid_utf8——最内层落工程文件才计入 warnings，系统树降级进 `warnings_sys`。两引擎实编路径传 `project_root=res.workdir`。
- `src/texlate/compile/judge.py`：系统树命中不抬 verdict，记 `notes += sys_warn:invalid_utf8@<file>` 留痕。
- `src/texlate/validate/l2.py`：`WarningSummary.sys_hits` 字段；`parse_log_text`/`parse_log` 加 `project_root` kwarg 同款归属。
- `src/texlate/e2e.py`（1d 文件，2 行）：`_l2_parse` 透传 `project_root=res.workdir`——必要接线，已通报。
- `bench/py/benchlib.py`：`judge_dict` verdict 序列化补 `"notes"` 键，bench 侧可见 sys_warn 留痕。

## 测试

新增 8 例：engine 侧 `test_parse_log_utf8_sysfile_demoted`/`test_parse_log_utf8_project_file_redline`/`test_parse_log_utf8_bare_name_tectonic`/`test_judge_sys_utf8_clean_with_note`/`test_judge_project_utf8_still_partial`；l2 侧 `test_invalid_utf8_attributed_by_file`/`test_invalid_utf8_bare_name_no_root_conservative`（裸文件名无 root → 保守仍计 warning）/`test_invalid_utf8_usertree_under_root_is_sys`（root 下 usertree = 系统）。

## 语义边界

- 归属单位 = file-stack **最内层**帧（真正生产者），非首个出现文件。
- 无法定位生产者（裸文件名且无 root）→ 保守计入 warning，不放水。
- 系统树命中不消失——`warnings_sys`/`sys_hits`/`sys_warn:` note 三层留痕，可审计。
