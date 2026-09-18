# zotero-texlate

Zotero 7 plugin for [TeXlate](https://hjfy.top): right-click an arXiv item → **TeXlate: Translate to Chinese** → the texlate server fetches the paper's LaTeX source, translates it paragraph-level, and recompiles a Chinese PDF; the plugin polls the task to completion, attaches the generated `zh.pdf` to the item, and stamps a `texlate: <taskId>` mark into the item's Extra field. Translated items get a second entry — **TeXlate: Open in Reader** — which opens the live bilingual reader at `{serverUrl}/#/reader/{taskId}`.

The plugin is a thin client: fetching, parsing, translating, and compiling all happen on the server. No LLM keys, no TeX engine, no Python inside Zotero.

## Requirements

- **Zotero 7.0+** (`strict_min_version` 7.0, `strict_max_version` 10.*)
- **A running texlate server**, local or remote:

```bash
uvx texlate web          # → http://127.0.0.1:8765 (in this repo: uv run texlate web)
```

The server owns translator credentials (BYOK in its web Settings page, or `TEXLATE_*` env vars) — the plugin posts `POST /api/arxiv/{id}/translate` with an empty body; model, target language, and keys all come from server settings.

## Install

```bash
npm ci
npx zotero-plugin build   # → .scaffold/build/texlate.xpi
```

Then in Zotero: **Tools → Plugins → gear icon → Install Add-on From File…** → pick `.scaffold/build/texlate.xpi`.

For the isolated-profile dev loop (mock server + fixtures + RDP-verified orchestration), see `dev/README.md`.

## Configuration

Zotero → Settings → **TeXlate** → "Open TeXlate Settings" opens the dialog. All preferences live under the `extensions.zotero.texlate` prefix (`addon/prefs.js`):

| Pref | Default | Meaning |
| --- | --- | --- |
| `serverUrl` | `http://127.0.0.1:8765` | texlate server base URL |
| `apiKey` | _(empty)_ | `X-Texlate-Key` header — only needed for remote `TEXLATE_MODE=server` instances; local loopback needs none |
| `attachZhPdf` | `true` | attach `zh.pdf` on completion |
| `attachEnPdf` | `false` | attach `en.pdf` |
| `attachDualPdf` | `false` | attach `dual.pdf` (bilingual side-by-side) |
| `batchDelayMs` | `1000` | delay between items in a multi-select batch |
| `pollIntervalMs` | `2000` | task-status poll interval |
| `pollTimeoutMs` | `10800000` | give up polling after 3 h |

"Check connection" pings `GET /api/health` with the dialog's current values before saving.

The API key is stored **plaintext** in Zotero preferences — same as every Zotero plugin pref.

## Behavior notes

- **arXiv id extraction** — 4-level fallback `DOI → url → archiveID → extra` (`src/modules/arxivId.ts`). The raw id is passed through untouched — version suffix `v3` and old-format `hep-th/9901001` included; the server's `normalize_arxiv_id` owns parsing. An item with no arXiv trace can't be translated.
- **Menu greying** — `computeMenuState(items)` (`src/modules/menu.ts`): *Translate* shows when ≥1 selected regular item has an extractable arXiv id AND no `texlate:` mark; *Open in Reader* shows when ≥1 selected item carries the mark; the submenu hides as a whole when neither applies. Multi-select translates every eligible item sequentially, `batchDelayMs` apart.
- **Idempotent mark** — a `texlate: t_xxx` line in Extra is the single source of truth: re-translating a marked item short-circuits to "already translated" and the menu flips to the reader entry. Only our mark line is rewritten; other Extra lines are kept byte-for-byte.
- **Attachments** — artifacts are downloaded to ASCII-only temp files, sha256-verified against the `/api/files` listing, `%PDF`-magic-checked, and imported as stored attachments titled `TeXlate {中文|英文原文|双语对照} - {short title}`. A task ending `partial` still attaches what exists and adds a warning line; `needs_auth` opens `{serverUrl}/#/settings` for BYOK sign-in.
- **Progress** — the plugin sandbox has no EventSource/ReadableStream, so progress is `setTimeout` polling of `GET /api/task/{id}` mapped onto the 11-state machine (queued → fetching → parsing → translating → compiling → done / partial / fault / cancelled / interrupted / needs_auth). Transport failures retry up to 5 consecutive times — the server may restart mid-task; HTTP 4xx and unknown statuses fail fast.

## Dev API

Exposed on `Zotero.texlate` for the `dev/` verification toolchain (driven over RDP eval — see `dev/README.md`):

```js
await Zotero.texlate.selftest(itemID)          // full chain → SelftestResult {ok, steps[], taskId}
await Zotero.texlate.selftestNonArxiv(itemID)  // negative path: extract→null + mark→none
Zotero.texlate.api.computeMenuState(items)     // pure menu-visibility predicate → {translate, reader}
```

`selftest` walks resolve-item → prefs → health → extract → already-marked → create → poll → files → download+attach → mark → attachments-verify → reader-url, recording attributable evidence per step; it never throws — failures land in `steps[i].detail` with `error` naming the first failed step.

## Development

```bash
npm install     # toolchain
npm run build   # zotero-plugin build + tsc --noEmit → .scaffold/build/
npm start       # scaffold serve (needs .env — see .env.example)
npm test        # mocha inside a real Zotero
```

## Layout

- `addon/` — static assets: manifest (Zotero 7.0–10.\*), bootstrap, prefs defaults, locales (en-US/zh-CN), preferences.xhtml
- `src/` — `hooks.ts` only dispatches; logic lives in `src/modules/` (client / arxivId / poller / attach / prefs / menu / flow / selftest); shared signatures in `src/contracts.ts`
- `typings/` — scaffold-generated d.ts
- `dev/` — verification toolchain + research notes (`dev/README.md`)

## 中文速览

右键 arXiv 条目 →「TeXlate：翻译为中文」→ texlate 服务器取 LaTeX 源码、段落级翻译、重编译中文 PDF → 插件轮询任务完成后把 `zh.pdf` 挂为条目附件，并在 Extra 写入 `texlate: <taskId>` 幂等标记。已译条目菜单变为「TeXlate：在阅读器打开」，打开 `{serverUrl}/#/reader/{taskId}` 双语对照阅读器。

需要 Zotero 7.0+ 和一个跑起来的 texlate 服务（`uvx texlate web`，默认 `http://127.0.0.1:8765`；BYOK/模型在服务端 Settings 配置，插件不碰 LLM 配置）。设置面板在 Zotero 设置 → TeXlate；无 arXiv 痕迹的条目菜单自动置灰。开发验证链见 `dev/README.md`。

## License

Apache-2.0. Built on the [windingwind/zotero-plugin-template](https://github.com/windingwind/zotero-plugin-template) scaffold.
