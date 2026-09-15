// pdfjs worker 接线 —— @pdfslick/core 的 dist 里 vendor 了一份旧版
// pdf.worker（它内部 new URL('pdfjs-dist/…', import.meta.url) 解析到自带副本），
// 与顶层 pdfjs-dist API 版本不一致会炸 "Worker version does not match"。
// 模块级覆盖会被 core 的模块初始化盖掉（import graph 里 core 更晚执行），
// 所以必须在组件挂载期调用——见 PdfPane。

import { GlobalWorkerOptions } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

export function ensurePdfjsWorker() {
    GlobalWorkerOptions.workerSrc = workerUrl;
}
