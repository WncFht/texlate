# modeb-verify — echo 守卫 × dirty 门闭环实证

> 2026-09-16。验证 `bb3ecc0`（l0 `_check_protocol_echo` + COMMENT 锚定）与 `29c196f`（harness dirty 计数+门）两层闭环。证据：`evidence.txt`；探针 `/tmp/modeb-probe-*.json`、运行记录 `/tmp/modeb-verify-*.json`。全部跑在 TEXLATE_SRC 快照 `/tmp/texlate-src-modeb-verify`（当时工作树含在飞改动），隔离工作目录 `/tmp/modeb-verify-work`。

## 主复现 2410.17957 pipeB-xel

- **dirty 3→0**（dirty_ids []），escaped 0→0，门 **PASS**（原 FAIL）。
- verdict **fail(early_eof, no_pdf) → clean**（main.pdf 产出，cjk_chars 1478）。
- 跑后树零回显签名命中；docs/2-introdution.tex caption 现闭合——`[[COMMENT_14]]` 独占行，`% …}` 留在注释内，`这是译文}` 正常终结 `\caption{`。

逐块结局（插桩探针，守卫 ON）：三个前 dirty 块全部经 slots 救援**干净交付**——2:3 在 whole×2 处 anchoring+echo fault，5:3/5:33 报 `协议字面 '占位符缺失:' ×1`，随后 slots（破坏免疫）救回 → partial，ph_match=true，dirty=[]。

## A/B 归因（同快照注释掉守卫调用，/tmp/texlate-src-modeb-noguard）

守卫 OFF 复现 dirty 交付（5:3、5:33 = ok + `占位符缺失:` 命中；2:3 仅靠 COMMENT 锚定已拦）。守卫 ON 恰把这两块转干净 slots 救援 partial——fault 总数净零变化。

**重要**：caught 41→7 / recovered 4→38 相对 modec-expand 的倒挂**不是守卫**（guard-off 同分布）——是 modec-expand 跑后兄弟改动（slots/repair 路径）的基线漂移。任何复跑对 n=80 记录都会见同款漂移，判读时注意。

## 负面对照（3 个曾有盘上残留的 id，全 pipeB-xel）

- 1003.0112：partial→clean，dirty 0，caught 55→0
- 0806.4149：clean→clean，dirty 0，caught 45→26
- 0806.2376：clean→clean，dirty 0，caught 17→3

无批量误伤（caught 一致**下降**=同源基线漂移）、零交付树残留、无 verdict 回归——一例改善。

## 结论

闭环确认：守卫在 L0 fault 回显 → 阶梯重救干净或回退 → harness dirty 读 0 → 门 PASS。
