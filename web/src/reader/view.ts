// 阅读器视图判定（纯函数，vitest 直测）。
// server 以 reader.view==="html" 标记"登记了 md_zip"的任务（app.py §2.5），
// 但 HtmlPane 的真实数据源是 dual.json 的 chunks——登记了却拉不到 chunks
// 属坏数据：落 "empty" 出提示，不切空 HtmlPane。
//
// dual 三态：undefined = 未拉完 / null = 无文件或拉取失败 / DualJson = 已拿到。

import type { DualJson, ReaderInfo } from "../api/client";

export type ReaderViewState = "loading" | "pdf" | "html" | "empty";

export function resolveReaderView(
    info: Pick<ReaderInfo, "view"> | null | undefined,
    dual: Pick<DualJson, "chunks"> | null | undefined,
): ReaderViewState {
    if (!info) return "loading";
    if (info.view !== "html") return "pdf";
    if (dual === undefined) return "loading";
    return dual?.chunks?.length ? "html" : "empty";
}
