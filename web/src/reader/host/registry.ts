// host/registry —— sel-system 命令注册表基座：menu-spec 18 命令 +
// find-usages lane 自注册。reg 被 copylatex/sentalign/citetranslate lanes
// 与 FloatBar/ctxm/键位面共用——须早于一切 lane hook 实例化。

import type { DocId } from "../logic/alignment";
import type { AnyHandle } from "../panes/PaneSlot";
import { Registry } from "../cmd/cmdreg";
import { registerCommands, type CmdCtx } from "../cmd/commands";
import type { HitCtx } from "../cmd/hitctx";
import { registerFindUsages } from "../features/findusages";

export function createCmdRegistry(deps: {
    handles(): Partial<Record<DocId, AnyHandle>>;
    sideOfHit(hit: HitCtx): DocId;
}) {
    const { handles, sideOfHit } = deps;

    /** menu-spec 18 命令注册表——deps 不进 registerCommands（run 读
        ctx.deps），逐命中经 makeCmdCtx 注入 */
    const reg = new Registry<CmdCtx>();
    registerCommands(reg, {});
    // find-usages lane 自注册（menu-spec 外项）——open 按 hit 解命中侧
    // handle 直开 usages 卡；无 openUsagesFor 的 pane 静默 no-op
    registerFindUsages(reg, {
        open: (c) => {
            const h = handles()[sideOfHit(c.hit)];
            if (h && "openUsagesFor" in h)
                h.openUsagesFor?.(
                    c.hit.cite.targetEl ?? c.hit.cite.targetId,
                    c.hit.cite.anchorEl,
                );
        },
    });

    return { reg };
}
