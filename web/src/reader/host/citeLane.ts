// host/citeLane —— 引用条目族 + 跳引用/重译/菜单卡 + cite-translate lane
// （cite.translate/cite.refsAll 两命令 + 顶栏「文献」钮 + RefsPanel 宿主）+
// refsLookup 远端增强。带走 taskStore/keptRefs 边的编排级触点。
//
// ctf.ct.setAuthHost 包装回放 pendingAuth 是闭包技巧——onNeedAuth 在面板
// 未开时暂存 retry，RefsPanel 挂载自登记 authHost 时回放进内联 key 框，
// 须与 refsOpen/pendingAuth 同搬。retxSeq 复用 HtmlPane [data-retx] DOM 钮
// 全链是架构妥协（pending/poll/repaint 都在 pane 内），勿重实现。

import { createEffect, createSignal, onCleanup } from "solid-js";
import { api, type KeptRef } from "../../api/client";
import { other, type DocId, type Pos } from "../logic/alignment";
import { capturePos } from "../logic/sync";
import type { PaneHandle } from "../pdf/pdfHandle";
import type { AnyHandle } from "../panes/PaneSlot";
import type { BibEntry, CiteIndex, RefMeta } from "../cite/citations";
import type { Registry } from "../cmd/cmdreg";
import type { CmdCtx } from "../cmd/commands";
import type { HitCtx } from "../cmd/hitctx";
import { registerCiteTranslate } from "../features/citetranslate";
import { taskStore } from "../../stores/tasks";
import { toast } from "../../stores/toastStore";
import { t } from "../../i18n";

export function createCiteLane(deps: {
    reg: Registry<CmdCtx>;
    citeIndex(): CiteIndex;
    handles(): Partial<Record<DocId, AnyHandle>>;
    sideOfHit(hit: HitCtx): DocId;
    bodyOf(side: DocId): HTMLElement | null;
    taskId(): string;
    onNavBegin(): void;
    onDestJump(side: DocId, dest: unknown, pre: Pos, post: Pos): void;
}) {
    const {
        reg,
        citeIndex,
        handles,
        sideOfHit,
        bodyOf,
        taskId,
        onNavBegin,
        onDestJump,
    } = deps;

    /** 菜单级引用卡（右键 cite.card / 'c' 键路开卡）——锚 rect + 命中快照 */
    const [menuCard, setMenuCard] = createSignal<{
        rect: DOMRect;
        hit: HitCtx;
    } | null>(null);

    /** cite → BibEntry：citeIndex 三形命中（hitctx 同口径）→ 合成兜底
        （entryText/arxiv/doi 来自 hitctx 已抽字段） */
    const citeLookup = (bibkey: string | null): BibEntry | undefined =>
        !bibkey
            ? undefined
            : (citeIndex().lookup(bibkey) ??
              citeIndex().lookup(bibkey.replace(/^bib\./, "")) ??
              citeIndex().lookup(`cite.${bibkey}`));
    const citeEntryOf = (
        cite: HitCtx["cite"],
    ): Pick<BibEntry, "label" | "text" | "arxivId" | "doi"> => {
        const e = citeLookup(cite.bibkey);
        return (
            e ?? {
                label: "",
                text: cite.entryText ?? "",
                arxivId: cite.arxivId ?? undefined,
                doi: cite.doi ?? undefined,
            }
        );
    };
    /** kept/meta 键——与 PdfPane citeKey 同口径（entry.key ?? bibkey） */
    const citeKeyOf = (cite: HitCtx["cite"]): string =>
        citeLookup(cite.bibkey)?.key ?? cite.bibkey ?? cite.targetId ?? "";
    const citeKeepPayload = (cite: HitCtx["cite"]): KeptRef => {
        const e = citeEntryOf(cite);
        return {
            label: e.label || undefined,
            text: e.text || undefined,
            arxivId: e.arxivId,
            doi: e.doi,
            meta: citeMeta(citeKeyOf(cite)),
        };
    };

    /** 跳至引用目标——dom 走 jumpAnchor（record=true：onNavBegin+
        onDestJump 全链）；pdf 走包装版 goToDestination（navChain 串行+
        死链预检+压栈+镜像）；html 兜底 scrollIntoView + 同口径记账 */
    const jumpToCite = (hit: HitCtx) => {
        const side = sideOfHit(hit);
        const h = handles()[side];
        const id = hit.cite.targetId;
        if (!h || !id) return;
        if ("jumpAnchor" in h && typeof h.jumpAnchor === "function") {
            h.jumpAnchor(id);
            return;
        }
        const ls = (h as PaneHandle).slick?.linkService;
        if (ls) {
            void ls.goToDestination(id);
            return;
        }
        const tel = hit.cite.targetEl;
        if (tel instanceof HTMLElement) {
            onNavBegin();
            const pre = capturePos(h);
            tel.scrollIntoView({ block: "start" });
            onDestJump(side, id, pre, capturePos(h));
        }
    };

    /** 单段重译——复用 HtmlPane [data-retx] 钮全链（pending/poll/repaint
        都在 pane 内）；命中侧优先，对侧兜底 */
    const retxSeq = (seq: number, hit: HitCtx) => {
        for (const s of [sideOfHit(hit), other(sideOfHit(hit))]) {
            const btn = bodyOf(s)?.querySelector<HTMLButtonElement>(
                `button.chunk-retx[data-retx="${seq}"]`,
            );
            if (btn && !btn.disabled) {
                btn.click();
                return;
            }
        }
        toast.err(t.live.retxFail);
    };

    const openMenuCard = (hit: HitCtx) => {
        const a = hit.cite.anchorEl;
        if (!a) return;
        const rect = a.getClientRects()[0] ?? a.getBoundingClientRect();
        setMenuCard({ rect, hit });
    };

    const [refMeta, setRefMeta] = createSignal<Record<string, RefMeta>>({});
    const citeMeta = (key: string) => refMeta()[key];

    // cite-translate lane：cite.translate/cite.refsAll 两命令 + 顶栏
    // 「文献」钮 + RefsPanel 宿主。onNeedAuth 在面板未开时暂存 retry——
    // RefsPanel 挂载自登记 authHost 时由下方包装回放进内联 key 框
    const [refsOpen, setRefsOpen] = createSignal(false);
    let pendingAuth: ((apiKey: string) => Promise<void>) | undefined;
    const ctf = registerCiteTranslate(reg, {
        citeIndex: () => citeIndex(),
        citeMeta,
        task: () => taskStore.task(taskId()),
        openRefsPanel: () => setRefsOpen(true),
        onNeedAuth: (retry) => {
            pendingAuth = retry;
            setRefsOpen(true);
        },
    });
    const innerSetAuthHost = ctf.ct.setAuthHost.bind(ctf.ct);
    ctf.ct.setAuthHost = (host) => {
        innerSetAuthHost(host);
        if (host && pendingAuth) {
            const r = pendingAuth;
            pendingAuth = undefined;
            host(r);
        }
    };

    // 远端增强：文档打开即批量查（S2 scholarphi「打开即批拉、hover 零
    // 等待」同款）——有 arXiv/DOI 线索的条目才送上游；失败静默降级
    createEffect(() => {
        const idx = citeIndex();
        setRefMeta({});
        const refs = idx
            .entries()
            .filter((e) => e.arxivId || e.doi)
            .map((e) => ({ key: e.key, arxivId: e.arxivId, doi: e.doi }));
        if (!refs.length) return;
        void api
            .refsLookup(refs)
            // .then 投递期读 citeIndex() 判迟到是有意的
            .then((res) => {
                if (citeIndex() !== idx) return; // 文档已换——丢弃迟到回包
                setRefMeta(res.meta ?? {});
            })
            .catch(() => undefined);
    });

    onCleanup(() => ctf.dispose());

    return {
        citeMeta,
        citeEntryOf,
        citeKeyOf,
        citeKeepPayload,
        menuCard,
        setMenuCard,
        openMenuCard,
        jumpToCite,
        retxSeq,
        refsOpen,
        setRefsOpen,
        ctf,
    };
}
