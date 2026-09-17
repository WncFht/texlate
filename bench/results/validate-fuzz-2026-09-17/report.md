# validate-fuzz — L0/L1 校验层对抗性 property tests

> 2026-09-17 收口。交付 `tests/test_fuzz_validate.py`（1819 行，commit `0521793`）：**43 passed + 12 xfailed(strict, 0 xpass)**，ruff check/format 双净。全离线（l1 用 fake proc+monkeypatch 传输层），种子 20260930-20261022，全套 1.9s。

## 覆盖面

**l0**（oracle 全部独立代码路径，与实现零共享）：`_lex` 连续覆盖/pos/kind 不变量；`validate_pair` 任意对恒不抛 + Issue/Report 字段形态（rule 注册表、pos 界、to_dict JSON、by_rule 划分恒等、feedback=error 拼接、双跑确定性）；恒等对 `(x,x)` 零 error；placeholder 全量签名 oracle（missing/extra/typo/cmtfab/order/bibitem 行首锚/COMMENT 行锚+尾段/src_literal 净差豁免——独立 parity 遮盖器+四臂模糊扫描器重放）；brace/math/env/cs_names/key/item_glue/macro/length/echo 逐规则 oracle；bare_cs/ph_in_cs 存在性谓词。oracle↔impl 等价性已论证（KEY_CMD_RX fullmatch-最长名 run≡finditer、`\d`≡isdecimal、`\\.` 不吃 `\n` 对长度规则计数中性）。

**l1**：TsBaseline/TsResult round-trip+verdict_ok；`_one` id 配对丢乱序/迟到/重复行、EOF 哨兵即死、非 JSON→L1Error；`validate_batch` 退出码/行数/非 JSON/spawn 故障矩阵；`available()` 三因子 16 组合矩阵；env 优先级；_pump 恒投哨兵；open/close 幂等；_drain_lines；死进程批处理降级；sign/validate 记录成形。

## 缺陷台账（3 族/12 xfail）

| # | 缺陷 | 位置 | 影响 | 修法 |
|---|------|------|------|------|
| 1 | key 规则族缺口 | l0.py:99-107 `KEY_CMD_RX` | `\Cite`/`\Citet`/`\parenCite`（regex `cite` 字面小写）、`\zlabel`（label 精确词无前缀模式）、`\addglobalbib`（bib 族漏列）丢 key 全静默；`\cites{a}{b}` 只抓第 1 参、第 2 参丢失不报——**译文丢引用不过 L0 主阀**。6 参数 xfail | `cite`→`[Cc]ite`、`label`→`[a-zA-Z@]*label`、bib 族补 `addglobalbib`、`*cites` 多参抓取 |
| 2 | 占位符拼错贪心次优 | l0.py:334-368（xlat/placeholders.py:270-285 同款） | `[[AAAA]] [[AABB]]` vs `[[AAAB]] [[CCAA]]` → 1 typo+1 missing+1 extra；最大匹配可得 2 枚修复建议——可自动修复的拼错被降级误报。1 xfail | 二分图增广匹配替代逐缺失贪心 |
| 3 | L1 schema 违例泄非 L1Error | l1.py:254-262 + 367-371（根因 `TsResult.from_dict` l1.py:122-135 字段零防御） | `{"parse_errors":5}`→TypeError、`[1,2]`→AttributeError、`{"unclosed_math":"abc"}`→ValueError、裸串→AttributeError，两通道只兜 JSONDecodeError——越过「协议错误统一 L1Error」契约。4+1 参数 xfail | from_dict 外兜 (TypeError,ValueError,AttributeError)→L1Error |

## 观察项（characterization 钉档，非 xfail）

恒等对误差只发生在畸形 src：(a) 行中 `[[COMMENT_n]]`+行尾文本（尾段为绝对判据）；(b) 同 `[[BIBITEM_k]]` 一处行首一处行中（锚定按 token 类型、检查逐出现）。真实 src 不产此形（COMMENT 恒行尾、BIBITEM 恒行首唯一 n）——两枚 characterization 测试钉档。
