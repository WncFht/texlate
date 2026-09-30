"""kernel._cli_main — _DISPATCH + main 入口叶 (kernel.cli 拆分叶).

``_DISPATCH`` 是平顶动词表 (init/run/plan/status/derive/sweep/prune/
backup/doctor/fsck) + ``verbs.REGISTRY`` 自注册动词统一映
``_cmd_verb``; ``main`` 先解 argparse 树，vault/ledger/lake/cache/spec
五组嵌套子命令各查自己的子表，其余落 ``_DISPATCH[cmd]``。

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

from kernel._cli_cache import (
    _cmd_cache_evict,
    _cmd_cache_rebuild,
    _cmd_cache_status,
)
from kernel._cli_doctor import _cmd_doctor, _cmd_fsck
from kernel._cli_lake import (
    _cmd_lake_absorb,
    _cmd_lake_evict,
    _cmd_lake_evict_done,
    _cmd_lake_pin,
    _cmd_lake_register,
    _cmd_lake_status,
    _cmd_lake_unpin,
)
from kernel._cli_ledger import (
    _cmd_ledger_import,
    _cmd_ledger_ingest,
    _cmd_ledger_rebuild,
    _cmd_ledger_tail,
)
from kernel._cli_ops import (
    _cmd_backup,
    _cmd_derive,
    _cmd_prune,
    _cmd_sweep,
)
from kernel._cli_parser import _build_parser
from kernel._cli_runlike import _cmd_init, _cmd_plan, _cmd_run
from kernel._cli_spec import _cmd_spec_list
from kernel._cli_status import _cmd_status
from kernel._cli_vault import (
    _cmd_vault_adopt,
    _cmd_vault_cas_link,
    _cmd_vault_rekey,
    _cmd_vault_restore,
    _cmd_vault_seed,
    _cmd_vault_slim,
    _cmd_vault_tombstone,
    _cmd_vault_verify,
)
from kernel._cli_verbs import _cmd_verb, _verb_registry

_DISPATCH = {
    "init": _cmd_init,
    "run": _cmd_run,
    "plan": _cmd_plan,
    "status": _cmd_status,
    "derive": _cmd_derive,
    "sweep": _cmd_sweep,
    "prune": _cmd_prune,
    "backup": _cmd_backup,
    "doctor": _cmd_doctor,
    "fsck": _cmd_fsck,
}
# Verb names self-register via verbs.REGISTRY — parser and dispatch read the
# same table, so a new verb file needs no edits here.
_DISPATCH.update(dict.fromkeys(_verb_registry(), _cmd_verb))


def main(argv=None) -> int:
    """Entry point. Returns a process exit code (never raises SystemExit
    itself except through argparse usage errors)."""
    args = _build_parser().parse_args(argv)
    cmd = args.cmd

    # nested subcommand routing
    if cmd == "vault":
        return {
            "verify": _cmd_vault_verify,
            "restore": _cmd_vault_restore,
            "adopt": _cmd_vault_adopt,
            "tombstone": _cmd_vault_tombstone,
            "seed": _cmd_vault_seed,
            "slim": _cmd_vault_slim,
            "cas-link": _cmd_vault_cas_link,
            "rekey": _cmd_vault_rekey,
        }[args.vsub](args)
    if cmd == "ledger":
        return {
            "import": _cmd_ledger_import,
            "ingest": _cmd_ledger_ingest,
            "rebuild-index": _cmd_ledger_rebuild,
            "tail-ingest": _cmd_ledger_tail,
        }[args.lsub](args)
    if cmd == "lake":
        return {
            "status": _cmd_lake_status,
            "evict": _cmd_lake_evict,
            "evict-done": _cmd_lake_evict_done,
            "register": _cmd_lake_register,
            "absorb": _cmd_lake_absorb,
            "pin": _cmd_lake_pin,
            "unpin": _cmd_lake_unpin,
        }[args.ksub](args)
    if cmd == "cache":
        return {
            "status": _cmd_cache_status,
            "evict": _cmd_cache_evict,
            "rebuild": _cmd_cache_rebuild,
        }[args.csub](args)
    if cmd == "spec":
        return {"list": _cmd_spec_list}[args.ssub](args)
    return _DISPATCH[cmd](args)
