# docs-fixloop-sync — docs vs HEAD fixloop taxonomy/rules 同步审计（只读）

> 2026-09-17 收口。基线 = tmp/docs-fixloop-sync/rules-head.yaml（HEAD extract）+ builtins.py/engine.py 工作树（gitStatus 无 builtins.py → 全量已提交，含 827674d 的 accent_mark_fix builtin）。

## 已核实基线数字

- warnings: 4 (invalid_utf8/missing_char/missing_graphic/tectonic_degrade) @ rules-head.yaml:142
- taxonomy: 46 pattern 条目 / 36 categories（35 ids + pdftex_prim 经 into:）@ :161
- rules: 62 条（2 gate + 2 precheck + 58 loop）@ :484。文件自头注释仍写 "36 条:2+2+32"——rules.yaml 自身陈旧
- TRANSFORM_FNS 22（committed，含 accent_mark_fix @builtins.py:2147）/ REWRITE_FNS 2（:144, px_to_bp/keep_latin_tokens）
- status 实际值：proposed×29, validated×5, verified×4（biblatex_bbx_rename/acro_v3_key_rename/ntheorem_style_undefine/already_def_undefine）, stub×1；多条仅 stats.fires 无 status
- env_mismatch、float_opt 有 taxonomy 条目但无消费规则 → 规则实消 34 cat

## docs/08-translate-compile.md — minor drift

1. §5.1 L251 计数链再陈旧：doc 最新勘误 "39 条目/32 category/59 rules (ff1a811)" vs committed 46/36/62。+7 taxonomy 条目、+2 categories（cannot_patch_macro、runaway_scan，均 9d9ebe5，各有消费规则 biblatex_bbx_rename:order161/detab_end_scanlines:order164，均 undocumented）、+3 rules（前两条已列名；第 3 条 unattributed——test 注释 "60+apjbbx/filemap" 暗示基线 60 本身比 doc 59 多 1，no-git 无法归属）
2. §5.1 L274 勘误 "TRANSFORM_FNS 21 + REWRITE_FNS 2, builtins.py:142/1844" → 实际 22+2，行号现为 :144/:2147。accent_mark_fix 已由 827674d 提交（builtins.py 不在 dirty 列表），committed-but-undocumented
3. §5.1 L359 status 枚举 stub/proposed/active/retired/validated — committed 用 verified×4（undocumented）；active/retired 零使用；另有 rules 无 status 键
4. §5.4 loop 伪代码未覆盖的已提交机制：warn-driven fix rounds（meta.warn_driven_fixes + scope:warnings 条目 warn_utf8/warn_missing_char + engine.py:1371 warn_cats 豁免）、best-effort salvage（engine.py:1402-1451 → best_effort_pdf）、floor_snap 入场 PDF 回退+floor_from 字段（engine.py:1273-1284/1456-1471）、per-round _sweep_bad_aux。（verdict 名 §6 本身一致）
5. §5.1 errata 把 "aux_scan_eof/split_glued_cs" 列为规则——前者是 category（规则名 aux_purge_regen），后者是 builtins 内部 helper `_split_glued_cs`（:1013）。标注错误
6. §5.1 "两层 YAML" 框架未提顶层 warnings: 段（4 warn_ids）
7. 疑似歧义待裁决：meta.loop.timeout_sec=120（fixloop 内部）vs §4.1 "timeout 240s"（消费方编译）——不同层，确认是否有意
8. 已核无漂移：§5.1 表内 16 条 spike 规则全在；§5.2 gate 表；phases(gate/precheck/loop)；7 action kinds；§6 verdict 全集 = engine.py:1223-1225

## docs/05-reproduction-plan.md — minor drift（决策史，dated counts 预期陈旧）

- L170 "taxonomy 23 行 → 16 规则" 为 E8 期快照，可接受
- 唯一实质：裁决22 仍写 pstricks_dvips_fallback——改名 preflight 的勘误只存在于 doc 08，doc 05 缺同名勘误
- L248 ctex_conflict 行为未来假设，OK

## docs/tools-runbook.md — in-sync（无 category/计数断言）

- 唯一行为陈旧：L109 "fixloop 只在 fail 上跑" 早于 floor 机制（doc 10 L120 勘误已记 _want_fix 改判 fail+misschar/error partial）

## docs/01/04/10 + HANDOFF-2026-09-16 — 历史计数，dated，无需动

## 旁证异常（超 doc scope，提请 lead 注意）

- tests/test_fixloop_yamlish.py:18 `assert len(data["rules"]) == 63`（committed）——既不匹配 committed 62 也不匹配 working 65，应是 peer 中间态（62+accent）时提交的，现应红
- rules.yaml 工作树在飞（+3 rules: abstract_frontmatter_hoist/order25.5、accent_mark_fix、cjk_font_fallback/order27；+2 taxonomy ids: env_undefined、pkg_obsolete；missing_char 条目改多行）——peer 仍在写，审计期间 3917→4132 行

## Verdict

docs/08 = minor drift（计数自勘误+verified 枚举+2 新 cat+若干 loop 机制未记，无实质错误）；docs/05 = minor/historical；runbook = in-sync。
