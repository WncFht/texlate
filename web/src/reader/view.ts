// 阅读器视图判定（纯函数，vitest 直测）。
// server 以 reader.view==="html" 标记"登记了 md_zip"的任务（app.py §2.5），
// 但 HtmlPane 的真实数据源是 dual.json 的 chunks——登记了却拉不到 chunks
// 属坏数据：落 "empty" 出提示，不切空 HtmlPane。
// view==="dom"（arxiv_html 链）的渲染源是 documents.*.url 指向的序列化 DOM
// 产物——登记了 dom 却两侧 url 全缺同属坏数据 → "empty"。
//
// dual 三态：undefined = 未拉完 / null = 无文件或拉取失败 / DualJson = 已拿到。
// readerGone：/task/{id}/reader 404——doc 类任务（docx/epub 插译）根本无
// dual.json，属设计如此；此时阅读器无意义，落 "files" 出产物下载面板。

import type { DualJson, ReaderInfo } from "../api/client";

export type ReaderViewState = "loading" | "pdf" | "html" | "dom" | "files" | "empty";

export function resolveReaderView(
    // "dom" 判定需要 documents（html artifact url 载体）——Partial 放宽到
    // view/documents 均可缺；调用点传的 info() 本就是全量
    info: Partial<Pick<ReaderInfo, "view" | "documents">> | null | undefined,
    dual: Pick<DualJson, "chunks"> | null | undefined,
    readerGone = false,
): ReaderViewState {
    if (!info) return readerGone ? "files" : "loading";
    if (info.view === "dom") {
        const hasDoc = !!(
            info.documents?.original?.url || info.documents?.translated?.url
        );
        return hasDoc ? "dom" : "empty";
    }
    if (info.view !== "html") return "pdf";
    if (dual === undefined) return "loading";
    return dual?.chunks?.length ? "html" : "empty";
}
