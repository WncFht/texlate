"""Analysis verbs — index-reading subcommands of ``bench``.

A verb is a sibling module exposing:

  ``HELP``        one-line parser help
  ``add_args``    (optional) populate its subparser
  ``main``        ``(args) -> int`` exit code

Registration is name-only: cli.py builds parsers from REGISTRY so a verb
file landing is self-registering — no shared-file edits when a new verb
arrives. Verbs are NOT specs: they never enter the spec load path.

REGISTRY maps ``{verb_name: (module_name, help)}`` — module_name is the
``verbs.<module_name>`` import leaf (hyphenated verb names share one
module; ``main(args)`` reads ``args.cmd`` to pick the subflow).
"""

REGISTRY = {
    "triage": ("triage", "records 聚类分诊 → triage 票 + index events"),
    "rundiff": ("rundiff", "两 run 逐格终态迁移对比"),
    "gate": ("gate", "pick_final 跨 run 终判 + scorecard"),
    "dossier": ("dossier", "run 档案汇编（pick_run 按 run_seq）"),
    "xlat-report": ("xlat", "xlatbench eval_records → 模型榜"),
    "xlat-rejudge": ("xlat", "存 src/zh 本地重判（免网关）"),
    "qual-report": ("qual", "qualbench 评判汇总"),
}
