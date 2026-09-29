// DocInfo —— 文档信息弹层（pdf.js documentProperties 对等件）。
// 数据源 = pdfSlickStore 元数据（PDFSlick._parseDocumentInfo 落定）；
// 响应式直读 store 字段，文档加载完自然填齐。

import { For, onCleanup, onMount } from "solid-js";
import type { PDFSlickState } from "@pdfslick/solid";
import { t } from "../../i18n";
import { fmtBytes } from "../../taskFiles";
import { fmtDate, pageSizeText } from "../logic/paneUtils";

interface Props {
    store: PDFSlickState;
    onClose(): void;
}

export default function DocInfo(props: Props) {
    // 与 FindBar/下载菜单同口径：Escape 关弹层
    onMount(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") props.onClose();
        };
        document.addEventListener("keydown", onKey);
        onCleanup(() => document.removeEventListener("keydown", onKey));
    });

    const rows = (): [string, string][] => {
        const s = props.store;
        return (
            (
                [
                    [t.pane.fFilename, s.filename],
                    [t.pane.fTitle, s.title],
                    [t.pane.fAuthor, s.author],
                    [t.pane.fSubject, s.subject],
                    [
                        t.pane.fKeywords,
                        typeof s.keywords === "string" ? s.keywords : undefined,
                    ],
                    [t.pane.fCreator, s.creator],
                    [t.pane.fProducer, s.producer],
                    [t.pane.fVersion, s.version],
                    [
                        t.pane.fPages,
                        s.numPages ? String(s.numPages) : undefined,
                    ],
                    [
                        t.pane.fPageSize,
                        // 与兄弟行同口径：缺席 → undefined 整行不渲，不留「—」
                        s.pageSize
                            ? pageSizeText(s.pageSize, {
                                  portrait: t.pane.portrait,
                                  landscape: t.pane.landscape,
                              })
                            : undefined,
                    ],
                    [
                        t.pane.fSize,
                        s.filesize != null ? fmtBytes(s.filesize) : undefined,
                    ],
                    [
                        t.pane.fLinearized,
                        s.isLinearized == null
                            ? undefined
                            : s.isLinearized
                              ? t.pane.yes
                              : t.pane.no,
                    ],
                    [
                        t.pane.fCreated,
                        s.creationDate ? fmtDate(s.creationDate) : undefined,
                    ],
                    [
                        t.pane.fModified,
                        s.modificationDate
                            ? fmtDate(s.modificationDate)
                            : undefined,
                    ],
                ] as [string, string | undefined][]
            )
                // 空字段整行不渲染——多数 PDF 元数据稀，一屏「—」比少几行更乱
                .filter(([, v]) => !!v) as [string, string][]
        );
    };

    return (
        <div class="docinfo" role="dialog" aria-label={t.pane.info}>
            <div class="docinfo-head">
                <h3>{t.pane.info}</h3>
                <button
                    type="button"
                    class="fb-btn"
                    title={t.pane.close}
                    aria-label={t.pane.close}
                    onClick={() => props.onClose()}
                >
                    ✕
                </button>
            </div>
            <dl class="docinfo-grid">
                <For each={rows()}>
                    {([k, v]) => (
                        <>
                            <dt>{k}</dt>
                            <dd>{v}</dd>
                        </>
                    )}
                </For>
            </dl>
        </div>
    );
}
