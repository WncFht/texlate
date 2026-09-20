// PurgeDialog —— 「删除已结束任务」确认框。自 TaskList.tsx 拆出。

import { createSignal, onCleanup, onMount } from "solid-js";
import { t } from "../i18n";

/**
 * 「删除已结束任务」确认框——docker prune 式：明说删什么、可选范围、
 * 显式确认，替代旧的工具行两击臂（按钮文案当确认太隐晦）。
 * 焦点默认落取消钮防 Enter 误触；busy 期禁取消（删除已在飞）。
 */
export default function PurgeDialog(props: {
    doneCount: number;
    failedCount: number;
    busy: boolean;
    onCancel(): void;
    onConfirm(sel: { done: boolean; failed: boolean }): void;
}) {
    const [selDone, setSelDone] = createSignal(true);
    const [selFailed, setSelFailed] = createSignal(true);
    const n = () =>
        (selDone() ? props.doneCount : 0) +
        (selFailed() ? props.failedCount : 0);
    let cancelBtn: HTMLButtonElement | undefined;
    onMount(() => {
        cancelBtn?.focus();
        const esc = (e: KeyboardEvent) => {
            if (e.key === "Escape" && !props.busy) props.onCancel();
        };
        document.addEventListener("keydown", esc);
        onCleanup(() => document.removeEventListener("keydown", esc));
    });
    return (
        <div
            class="purge-veil"
            onClick={(e) => {
                if (e.target === e.currentTarget && !props.busy) {
                    props.onCancel();
                }
            }}
        >
            <div
                class="purge-box"
                role="alertdialog"
                aria-modal="true"
                aria-label={t.home.purgeTitle}
            >
                <h2 class="purge-title">{t.home.purgeTitle}</h2>
                <p class="purge-desc">{t.home.purgeDesc}</p>
                <div class="purge-opts">
                    <label class="purge-opt">
                        <input
                            type="checkbox"
                            checked={selDone()}
                            disabled={props.busy || props.doneCount === 0}
                            onChange={(e) =>
                                setSelDone(e.currentTarget.checked)
                            }
                        />
                        {t.home.purgeScopeDone.replace(
                            "{n}",
                            String(props.doneCount),
                        )}
                    </label>
                    <label class="purge-opt">
                        <input
                            type="checkbox"
                            checked={selFailed()}
                            disabled={props.busy || props.failedCount === 0}
                            onChange={(e) =>
                                setSelFailed(e.currentTarget.checked)
                            }
                        />
                        {t.home.purgeScopeFailed.replace(
                            "{n}",
                            String(props.failedCount),
                        )}
                    </label>
                </div>
                <div class="purge-foot">
                    <button
                        type="button"
                        class="btn-ghost purge-cancel"
                        ref={(el) => (cancelBtn = el)}
                        disabled={props.busy}
                        onClick={() => props.onCancel()}
                    >
                        {t.home.cancel}
                    </button>
                    <button
                        type="button"
                        class="btn-primary purge-confirm"
                        disabled={props.busy || n() === 0}
                        onClick={() =>
                            props.onConfirm({
                                done: selDone(),
                                failed: selFailed(),
                            })
                        }
                    >
                        {props.busy
                            ? t.home.purgeBusy
                            : t.home.purgeDo.replace("{n}", String(n()))}
                    </button>
                </div>
            </div>
        </div>
    );
}
