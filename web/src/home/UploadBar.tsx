// UploadBar —— Home 上传进度条：upPct<0（无进度事件）或 ≥100（字节送完、
// 服务端建单中）回不定态扫条——防「卡 100%」错觉；aria progressbar 语义。

import { Show } from "solid-js";
import { t } from "../i18n";

export default function UploadBar(props: {
    uploading(): boolean;
    upPct(): number;
}) {
    // 不定态闸：<0（无进度事件）或 ≥100（字节送完、服务端建单中）→ 扫条
    const indet = () => props.upPct() < 0 || props.upPct() >= 100;
    return (
        <Show when={props.uploading()}>
            <div class="up-progress">
                <div
                    class="up-bar"
                    classList={{ indet: indet() }}
                    role="progressbar"
                    aria-label={t.home.upload}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={indet() ? undefined : props.upPct()}
                >
                    <i
                        style={{
                            width: indet() ? "35%" : `${props.upPct()}%`,
                        }}
                    />
                </div>
                <span class="up-label" aria-live="polite">
                    {/* 100% = 字节已送完、服务端建单中——回不定态防「卡 100%」错觉 */}
                    {props.upPct() >= 100
                        ? t.home.processing
                        : props.upPct() >= 0
                          ? t.home.uploadPct.replace(
                                "{n}",
                                String(props.upPct()),
                            )
                          : t.home.uploading}
                </span>
            </div>
        </Show>
    );
}
