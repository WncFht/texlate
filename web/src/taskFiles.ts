// 任务产物下载项（纯函数，vitest 直测）——TaskList 行内直链与 Reader
// 下载清单共用同一排序/标签/直链规则。
//
// doc 类任务（docx/epub 插译路，worker._run_doc）只产 src_tar + zh_docx/
// zh_epub，无 dual.json → reader 端点 404、无对照阅读器，产物直链是唯一
// 出口。upload_pdf 走 babeldoc 但 _finish_pdf 会 _build_dual 产 dual.json，
// 阅读器可用——不在 DOC_KINDS 内。

import { DB_TO_URL_KIND, type FileKind, type TaskKind } from "./api/client";
import { t } from "./i18n/zh";

/** 无对照阅读器、走产物直链下载的任务 kind */
const DOC_KINDS: ReadonlySet<string> = new Set(["docx", "epub"]);

export const isDocKind = (kind: TaskKind): boolean => DOC_KINDS.has(kind);

export interface TaskDownload {
    kind: FileKind;
    label: string;
    url: string;
}

/** 下载清单排序：译文优先，工程包/日志/原文档殿后 */
const ORDER: FileKind[] = [
    "zh.pdf",
    "en.pdf",
    "dual.pdf",
    "dual.json",
    "zh.docx",
    "zh.epub",
    "zh-src.zip",
    "compile.log",
    "md",
    "src.tar",
];

/**
 * artifacts（db kind → 下载路径——snapshot.artifacts / done.artifacts /
 * files manifest 归一成同形状后）→ 有序下载项。未知 db kind 原样透出
 * 并排尾；url 补 ?download=1 让服务端落 Content-Disposition。
 */
export function downloadItems(artifacts: Record<string, string>): TaskDownload[] {
    const ord = (k: FileKind) => {
        const i = ORDER.indexOf(k);
        return i < 0 ? ORDER.length : i;
    };
    return Object.entries(artifacts)
        .map(([dbKind, url]) => {
            const kind = DB_TO_URL_KIND[dbKind] ?? dbKind;
            return { kind, label: t.files[kind] ?? kind, url: `${url}?download=1` };
        })
        .sort((a, b) => ord(a.kind) - ord(b.kind));
}
