// upload —— Home 上传编排：客户端预检（80MB 上限 + 扩展名白名单，早于
// XHR 失败给出本地错）→ 单件/批量顺序提交（.share.zip 是社区缓存包走
// share/import 自描述包，其余 api.upload）→ XHR 进度回调喂 upPct。
// 自 pages/Home.tsx 拆出；批量不抢路由——结案由调用方 refresh。

import { createSignal } from "solid-js";
import {
    api,
    type TranslateResponse,
    type UploadProgress,
} from "../api/client";
import { t } from "../i18n";
import type { HomeOptions, UploadFields } from "./options";

/** 上传客户端预检（U14）：80MB 上限 + 扩展名白名单——早于 XHR 失败给出本地错 */
export const MAX_UPLOAD_BYTES = 80 * 1024 * 1024;
const UPLOAD_EXT = /\.(pdf|tex|tar|gz|tgz|zip|docx|epub)$/i;

/** 客户端预检——返回错误文案或 null 放行（.share.zip 走 .zip 白名单） */
export function precheckUpload(f: File): string | null {
    if (f.size > MAX_UPLOAD_BYTES) return t.home.uploadTooBig;
    if (!UPLOAD_EXT.test(f.name)) return t.home.uploadBadExt;
    return null;
}

/** runOne 结案形：成功 ``{res}`` / 失败 ``{err}`` 文案（单件路 setError、批路汇总） */
type RunResult = { res: TranslateResponse } | { err: string };

export function createHomeUpload(deps: {
    busy(): boolean;
    setBusy(v: boolean): void;
    setError(v: string): void;
    /** 卸载闸——在飞请求落地不得再动状态/劫持路由 */
    alive(): boolean;
    options: HomeOptions;
    /** 单件成功落地（reader_url 缺席回任务详情面） */
    onResult(res: TranslateResponse): void;
    /** 批量结案——refresh 让新任务行自己冒出来 */
    onBatchDone(): void;
}) {
    // 上传进度：uploading=文件提交在飞（区别于 translate 的 busy）；
    // upPct=-1 哨兵 = 尚无进度事件（lengthComputable=false 时恒如此）→ 不定态
    const [uploading, setUploading] = createSignal(false);
    const [upPct, setUpPct] = createSignal(-1);

    const onUpProgress: UploadProgress = (loaded, total) =>
        setUpPct(Math.min(100, Math.round((loaded / total) * 100)));

    /** 单文件提交：.share.zip 是社区缓存包走 share/import（包内 manifest
     *  自描述），其余走 api.upload（main 指定主文件） */
    const uploadOne = (
        f: File,
        snap: UploadFields,
        onProgress: UploadProgress,
    ) => {
        const { o, upOpts } = snap;
        if (f.name.toLowerCase().endsWith(".share.zip")) {
            return api.shareImport(
                f,
                Object.keys(upOpts).length ? upOpts : undefined,
                deps.options.byok(),
                onProgress,
            );
        }
        const main = deps.options.optMain().trim();
        const fields =
            o || main
                ? {
                      model: o?.model,
                      target_lang: o?.target_lang,
                      main: main || undefined,
                      options: upOpts,
                  }
                : undefined;
        return api.upload(f, fields, deps.options.byok(), onProgress);
    };

    /** 单件执行体：precheck + 状态翻转 + uploadOne——upload/uploadBatch 共用。
     *  成功回 ``{res}``，失败回 ``{err}`` 文案（单件路 setError、批路汇总）。 */
    const runOne = async (
        f: File,
        snap: UploadFields,
    ): Promise<RunResult> => {
        const bad = precheckUpload(f);
        if (bad) return { err: `${f.name}：${bad}` };
        deps.setError("");
        deps.setBusy(true);
        setUploading(true);
        setUpPct(-1);
        try {
            return { res: await uploadOne(f, snap, onUpProgress) };
        } catch (e) {
            return {
                err: `${f.name}：${e instanceof Error ? e.message : String(e)}`,
            };
        } finally {
            deps.setBusy(false);
            setUploading(false);
        }
    };

    const upload = async (file: File, land = true) => {
        if (deps.busy()) return;
        const r = await runOne(file, deps.options.uploadFields());
        if (!deps.alive()) return;
        if ("err" in r) {
            deps.setError(r.err);
            return;
        }
        deps.options.clearKey();
        if (land) deps.onResult(r.res);
    };

    /**
     * 多文件批传（U14）：顺序提交不并发——单文件落地阅读器照旧，
     * 批量模式不抢路由，全跑完 refresh 让新任务行自己冒出来。
     * 单文件失败不阻断后续；错误汇总到 error 行。
     */
    const uploadBatch = async (files: File[]) => {
        if (files.length === 1) {
            await upload(files[0]);
            return;
        }
        const errs: string[] = [];
        // 与单文件路同一套 multipart 字段——整批一次快照（中途改选项不影响在飞批）
        const snap = deps.options.uploadFields();
        for (const f of files) {
            const r = await runOne(f, snap);
            if ("err" in r) errs.push(r.err);
            if (!deps.alive()) return;
        }
        deps.options.clearKey();
        if (errs.length) deps.setError(errs.join("；"));
        deps.onBatchDone();
    };

    return { uploading, upPct, upload, uploadBatch };
}

export type HomeUpload = ReturnType<typeof createHomeUpload>;
