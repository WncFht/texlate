// BYOK 设置 store —— GET 永不回 key 本体，只回 has_api_key（§2.5）。

import { createSignal } from "solid-js";
import { api, type Provider, type Settings } from "../api/client";

const [settings, setSettings] = createSignal<Settings | null>(null);
const [providers, setProviders] = createSignal<Provider[]>([]);
const [loaded, setLoaded] = createSignal(false);

export const settingsStore = {
    settings,
    providers,
    loaded,

    async refresh() {
        const [s, p] = await Promise.all([
            api.getSettings(),
            api.providers().catch(() => [] as Provider[] | { providers: Provider[] }),
        ]);
        setSettings(s);
        setProviders(Array.isArray(p) ? p : (p.providers ?? []));
        setLoaded(true);
    },

    async save(patch: Settings) {
        const next = await api.putSettings(patch);
        setSettings((cur) => ({ ...cur, ...next }));
        return next;
    },

    test: () => api.testSettings(),
};
