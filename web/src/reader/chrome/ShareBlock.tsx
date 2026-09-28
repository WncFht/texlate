// ShareBlock —— §6 事后共享打包块：按钮 → 成功态（share_key + 共享目录提示）/
// 可读错误。自门控：when=false 时整块缺席。
// createSharePack 是状态工厂——busy/result/error 留在调用方作用域（Reader
// 需要在 retry 时 reset，状态不下沉组件内）；组件本体纯展示。

import { createSignal, Show } from "solid-js";
import {
    api,
    ApiError,
    errText,
    type SharePackResponse,
} from "../../api/client";
import { t } from "../../i18n";

export interface ShareError {
    code?: string;
    message: string;
}

const SHARE_ERR_TEXT: Record<string, string> = {
    share_pack_rejected: t.reader.shareErrRejected,
    share_pack_artifacts: t.reader.shareErrArtifacts,
    share_pack_failed: t.reader.shareErrFailed,
};

/** code → 可读文案；映射外的错回退服务端 detail */
const shareErrText = (ae: ApiError | null, e: unknown) => {
    const detail = ae?.detail ?? errText(e);
    const mapped =
        ae?.status === 409
            ? t.reader.shareErrState
            : SHARE_ERR_TEXT[ae?.code ?? ""];
    return mapped ? (detail ? `${mapped}（${detail}）` : mapped) : detail;
};

/** POST /task/{id}/share/pack 调用态：busy 闸 + 成功/错误结果；reset 供重试清场 */
export function createSharePack(taskId: () => string) {
    const [busy, setBusy] = createSignal(false);
    const [result, setResult] = createSignal<SharePackResponse | null>(null);
    const [error, setError] = createSignal<ShareError | null>(null);

    const pack = async () => {
        if (busy() || result()) return;
        setBusy(true);
        setError(null);
        try {
            setResult(await api.sharePack(taskId()));
        } catch (e) {
            const ae = e instanceof ApiError ? e : null;
            setError({ code: ae?.code, message: shareErrText(ae, e) });
        } finally {
            setBusy(false);
        }
    };

    const reset = () => {
        setResult(null);
        setError(null);
    };

    return { busy, result, error, pack, reset };
}

interface Props {
    /** 可分享门控（done/partial + 非 share 导入 + 有 arxiv 源）——调用方判定 */
    when: boolean;
    busy: boolean;
    result: SharePackResponse | null;
    error: ShareError | null;
    onPack(): void;
}

export default function ShareBlock(props: Props) {
    const [copied, setCopied] = createSignal(false);
    const copyKey = async () => {
        const key = props.result?.share_key;
        // 非安全上下文（http://LAN）无 clipboard——不写也不装已复制，
        // key 已在屏可手选
        if (!key || !navigator.clipboard) return;
        try {
            await navigator.clipboard.writeText(key);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
        } catch {
            /* 写入被拒（权限/失焦）——不装已复制 */
        }
    };
    return (
        <Show when={props.when}>
            <span class="share-pack">
                <Show
                    when={!props.result}
                    fallback={
                        <span class="share-ok">
                            {t.reader.shareOk}
                            <code class="share-key">
                                {props.result!.share_key}
                            </code>
                            <button
                                type="button"
                                class="tb-btn share-copy"
                                title={t.reader.shareCopy}
                                onClick={() => void copyKey()}
                            >
                                {copied() ? t.reader.copied : t.reader.copy}
                            </button>
                            <span class="muted">{t.reader.shareOkHint}</span>
                        </span>
                    }
                >
                    <button
                        type="button"
                        class="tb-btn share-btn"
                        disabled={props.busy}
                        title={t.reader.shareBtnTip}
                        onClick={() => props.onPack()}
                    >
                        {props.busy ? t.reader.shareBusy : t.reader.shareBtn}
                    </button>
                </Show>
                <Show when={props.error}>
                    {(e) => (
                        <span class="form-error share-err">
                            [{e().code ?? "share_pack"}] {e().message}
                        </span>
                    )}
                </Show>
            </span>
        </Show>
    );
}
