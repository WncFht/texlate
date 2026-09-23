// features/citetranslate —— cite-translate lane 的命令注册面 + 整合桥。
// 用法（整合期，ReaderView 内）：
//   const ctf = registerCiteTranslate(reg, {
//       citeIndex: () => citeIndex(),
//       citeMeta:  (k) => citeMeta(k),
//       task:      () => task(),                    // 当前 reader 任务行
//       openRefsPanel: () => setRefsOpen(true),     // RefsPanel 挂载信号
//       onNeedAuth: (retry) => …,                   // 内联 key 面板宿主
//   });
//   <Toolbar refsTotal={ctf.refsTotal()} refsCount={ctf.refsCount()}
//            onRefs={ctf.openPanel} …/>
//   <Show when={refsOpen()}><RefsPanel {...ctf.panelProps()}
//            onClose={() => setRefsOpen(false)} /></Show>
//   CiteCardBody 加 onTranslate={() => ctf.translateEntry(entry)}（卡脚钮）
//
// 命令面（reg 注册 2 项，幂等重挂）：
//   cite.translate  when=cite.targetKind=='bib' && cite.arxivId —— 右键菜单
//                   「翻译此文」，走 ct.submit 七态分派。
//   cite.refsAll    when=cite.targetKind=='bib' —— 「全部文献」次入口开面板。
//
// refsCount = 可译条数（entry.arxivId ?? citeMeta(key).arxivId 存在）——
// DOI-only 条目经 S2 externalIds.ArXiv 反补后自动计入；refsTotal =
// citeIndex.size（显隐闸——无条目不出钮）。

import type { Command, Registry } from "../cmd/cmdreg";
import type { CmdCtx } from "../cmd/commands";
import type {
    ByokHeaders,
    TaskSnapshot,
    TranslateOptions,
    TranslateResponse,
} from "../../api/client";
import { settingsStore } from "../../stores/settings";
import type { ToastAction } from "../../stores/toastStore";
import type { BibEntry, CiteIndex, RefMeta } from "../citations";
import {
    createCiteTranslate,
    ctText,
    type CiteSubmitOutcome,
    type CiteTranslate,
    type RefItem,
} from "../citeTranslate";

export interface CiteTranslateOpts {
    /** 文献索引活访问器（buildCiteIndex(dual) memo——dual 晚到时自动重算） */
    citeIndex(): CiteIndex;
    /** L2 元数据回调（meta().arxivId 是 DOI-only 条目的升级链） */
    citeMeta?(key: string): RefMeta | undefined;
    /** 翻译体透传源——当前 reader 任务行；缺省空 options 提交 */
    task?(): TaskSnapshot | null | undefined;
    /** 凭证门判据（缺省 settingsStore.settings()?.has_api_key） */
    hasApiKey?(): boolean | undefined;
    /** per-request BYOK 基底（一般缺省——key 走内联面板收） */
    byok?(): ByokHeaders | undefined;
    /** 「文献」钮/cite.refsAll 的面板开信号（ReaderView 挂 RefsPanel） */
    openRefsPanel?(): void;
    /** 内联 key 面板宿主（缺省工厂内 err toast 指设置页） */
    onNeedAuth?(retry: (apiKey: string) => Promise<void>): void;
    nav?(to: string): void;
    /** 测试缝——工厂依赖注入直透 */
    listTasks?(): Promise<TaskSnapshot[]>;
    postTranslate?(
        arxivId: string,
        body: TranslateOptions,
        byok?: ByokHeaders,
    ): Promise<TranslateResponse>;
    toastOk?(text: string, action?: ToastAction): void;
    toastErr?(text: string): void;
    track?(taskId: string, arxivId: string): void;
}

export interface CiteTranslateFeature {
    /** 编排工厂（RefTaskChip onTranslate / RefsPanel ct prop 的注入源） */
    ct: CiteTranslate;
    /** citeIndex.size——「文献」钮显隐闸 */
    refsTotal(): number;
    /** 可译条数——「文献」钮角标（L1 arxivId + L2 meta.arxivId 反补） */
    refsCount(): number;
    /** 可译条目集（RefsPanel items / 批灌队输入的同一份口径） */
    translatable(): RefItem[];
    /** CiteCard 脚钮回调注册点——宿主传 entry（或裸 arxivId 串） */
    translateEntry(
        entry: Pick<BibEntry, "arxivId"> & { key?: string },
    ): Promise<CiteSubmitOutcome | undefined>;
    /** RefsPanel props 打包——整合期一行挂上 */
    panelProps(): {
        entries: BibEntry[];
        meta?: (key: string) => RefMeta | undefined;
        ct: CiteTranslate;
    };
    openPanel(): void;
    dispose(): void;
}

export function registerCiteTranslate(
    reg: Registry<CmdCtx>,
    opts: CiteTranslateOpts,
): CiteTranslateFeature {
    const ct = createCiteTranslate({
        // M10 口径：当前任务 model/target_lang/glossary/options 全量透传，
        // idempotency_key 摘除在工厂 buildBody 内做
        body: () => {
            const s = opts.task?.();
            if (!s) return undefined;
            return {
                model: s.model,
                target_lang: s.target_lang,
                glossary: s.glossary,
                options: { ...(s.options ?? {}) },
            };
        },
        byok: opts.byok,
        hasApiKey:
            opts.hasApiKey ??
            (() => settingsStore.settings()?.has_api_key),
        onNeedAuth: opts.onNeedAuth,
        nav: opts.nav,
        toastOk: opts.toastOk,
        toastErr: opts.toastErr,
        track: opts.track,
        listTasks: opts.listTasks,
        postTranslate: opts.postTranslate,
    });

    const entries = () => opts.citeIndex().entries();
    const meta = opts.citeMeta;

    /** 可译条目——L1 arxivId 或 L2 meta().arxivId 反补（DOI-only 升级链） */
    const translatable = (): RefItem[] =>
        entries().flatMap((entry) => {
            const id = entry.arxivId ?? meta?.(entry.key)?.arxivId;
            return id ? [{ arxivId: id, entry }] : [];
        });

    const openPanel = () => opts.openRefsPanel?.();

    const translateEntry: CiteTranslateFeature["translateEntry"] = (e) => {
        const id = e.arxivId ?? (e.key ? meta?.(e.key)?.arxivId : undefined);
        if (!id) return Promise.resolve(undefined);
        return ct.submit(id);
    };

    const cmds: Command<CmdCtx>[] = [
        {
            id: "cite.translate",
            title: "menu.cite.translate",
            sec: "cite",
            when: "cite.targetKind == 'bib' && cite.arxivId",
            run: (c) => {
                const id = c.hit.cite.arxivId;
                if (id) return ct.submit(id).then(() => undefined);
                return undefined;
            },
        },
        {
            id: "cite.refsAll",
            title: "menu.cite.refsAll",
            sec: "cite",
            when: "cite.targetKind == 'bib'",
            run: () => openPanel(),
        },
    ];
    for (const cmd of cmds) {
        if (reg.get(cmd.id)) reg.unregister(cmd.id); // 幂等重挂
        reg.register(cmd);
    }

    return {
        ct,
        refsTotal: () => opts.citeIndex().size,
        refsCount: () => translatable().length,
        translatable,
        translateEntry,
        panelProps: () => ({ entries: entries(), meta, ct }),
        openPanel,
        dispose() {
            for (const cmd of cmds) reg.unregister(cmd.id);
        },
    };
}

// i18n 键（menu.<id> 段文案）：menu.cite.translate=翻译此文/Translate；
// menu.cite.refsAll=全部文献/All references——整合期随 citeTran 组合入。
export { ctText };
