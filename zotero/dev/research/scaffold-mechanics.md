# zotero-plugin-scaffold mechanics (0.8.2 / 0.8.8)

Evidence base: `tmp/zotero-dev/scout/package/` = unpacked `zotero-plugin-scaffold-0.8.2.tgz`; main logic bundled into `dist/shared/zotero-plugin-scaffold.DQYuTa0n.mjs` (4977 lines, readable, original comments preserved). Template pins `^0.8.2` → npm resolves to 0.8.8 (latest 0.8.x); spot-checked identical mechanics in `tmp/zotero-dev/scout/v088/package/dist/shared/scaffold-src-bWcaMVyt.mjs` (same args, same RDP flow, same env vars). 0.9.x exists (latest 0.9.2) but is outside the `^0.8.2` range.

CLI surface (`dist/cli.mjs:78-115`): `build [--dev] [--dist <dir>]`, `serve` (alias `dev`), `test [--abort-on-fail] [--exit-on-finish] [--no-watch]`, `release [version]`, `create` (unimplemented stub). Config loaded by c12 under name `zotero-plugin` with `dotenv: true` + `packageJson: true` (shared bundle:36-46) — so `zotero-plugin.config.ts` + `.env` + package.json all feed in.

## 1. `zotero-plugin serve` end-to-end

`Serve.run()` (bundle:4129-4159) constructs a `ZoteroRunner` and calls `runner.run()` → `setupProfile()` → `startZoteroInstance()` → `installTemporaryPlugins()` (unless asProxy) → `watch()`.

### Binary / profile resolution

- **Zotero binary: env var ONLY, no config field.** `zoteroBinPath` getter reads `process.env.ZOTERO_PLUGIN_ZOTERO_BIN_PATH` and throws if unset/nonexistent (bundle:4201-4208). Same for test (4934-4938).
- Profile path: env `ZOTERO_PLUGIN_PROFILE_PATH` (4209-4211); dataDir: env `ZOTERO_PLUGIN_DATA_DIR` (4212-4214).
- Runner defaults (3866-3883): `profile.path = "./.scaffold/profile"`, `createIfMissing: true`, `plugins.asProxy = false`. If no profile.path and no dataDir, dataDir defaults to `./.scaffold/data` (3892-3893).
- Kill command: env `ZOTERO_PLUGIN_KILL_COMMAND`, else `pkill -9 zotero` on Linux — **kills every zotero on the box, not just the spawned one** (4095-4117). `exit()` calls both `zotero.kill()` and `killZotero()`.

### Profile setup (`setupProfile`, 3912-3934)

- Missing profile dir → `ensureDir` (empty dir; Zotero populates it) when `createIfMissing` (default true).
- Writes `<profile>/prefs.js` via PrefsManager (`user_pref` lines): merges scaffold defaults → existing prefs.js → `server.prefs` customPrefs → force `extensions.lastAppBuildId/lastAppVersion = null`.
- Default prefs (3396-3492) include the debug channel enablers: `devtools.debugger.remote-enabled: true`, `devtools.debugger.remote-websocket: true`, `devtools.debugger.prompt-connection: false`, `devtools.chrome.enabled: true`, `xpinstall.signatures.required: false`, `extensions.enabledScopes: 5`, `extensions.autoDisableScopes` (10 common / 0 zotero), plus Zotero first-run skips and `extensions.zotero.httpServer.enabled: true` on port 23124 with localAPI.

### Launch (`startZoteroInstance`, 3944-3975)

Args verbatim (line 3945-3959):

```
--purgecaches  no-remote          # NOTE: "no-remote" has NO dashes — positional arg bug, see surprises
-profile <abs profile path>       # single dash
--dataDir <abs>                   # only if dataDir set
--jsdebugger                      # only if binary.devtools (server.devtools, default true)
<server.startArgs...>
-start-debugger-server <port>     # single dash; port = free TCP port via net.listen(0) (3853-3864)
```

Env adds `XPCOM_DEBUG_BREAK=stack`, `NS_TRACE_MALLOC_DISABLE_STACKS=1` (3961-3965). Spawns the binary, then connects RDP on the chosen port with up to 150 retries × 1s (3684-3685, 3722-3741).

### Plugin install — two modes

- Default (`asProxy: false`): **temporary addon via RDP** — `installTemporaryAddon` request to the addons actor with `addonPath = resolve(dist/addon)` (3976-3985, 3791-3807). No xpi packing needed (serve builds with NODE_ENV=development → `buildInProduction` skipped, 826-829).
- `asProxy: true`: **extensions pointer file** — writes `<profile>/extensions/<addon-id>` containing the absolute path of `dist/addon` (the Zotero-documented dev layout), deletes stale `<id>.xpi`, and flips `active/userDisabled` in `extensions.json` (3986-4020).

### Reload on rebuild (`watch`/`reload`, 4164-4189)

chokidar watches `ctx.source` (template: `["src","addon"]`), ignoring dotfiles/.git/node_modules/`watchIgnore` (3327-3366). On change: `.ts/.tsx` → `builder.bundle()` (esbuild only); anything else → full `builder.run()`; then `reloadAllPlugins()`:

- temp-addon mode → RDP `reload` request on the addon actor (4021-4051, 3846-3851).
- proxy mode → spawns a SECOND zotero invocation `"<bin>" --purgecaches -profile "<path>" -url "zotero://ztoolkit-debug/?run=<urlencoded reload script>"` via execSync (4052-4075). The bare-`no-remote` bug is load-bearing here: the running instance still accepts remote commands. Comment in code: "Do not use this method if possible, as frequent execSync can cause Zotero to crash" (4076-4077). Requires the plugin to have toolkit's DebugBridge registered.

## 2. `zotero-plugin test` — mocha inside a real Zotero

Result transport is **HTTP POST, not RDP eval**. RDP is used only for addon lifecycle (install/reload), same as serve.

Flow (`Test.run`, 4833-4852):

1. `emptyDir` `.scaffold/test/{profile,data,resource}` (dirs at 4217-4224).
2. `builder.run()` — builds plugin to `dist/addon`.
3. `TestHttpReporter.start()` — node HTTP server on a free port, `POST /update` receives result events (4296-4403).
4. `TestBundler.generate()` (4718-4804) writes a **runtime-generated test-runner plugin** into `.scaffold/test/resource/`:
   - `manifest.json` — id `scaffold-test@northword.cn` (4553-4568).
   - `bootstrap.js` — `startup()` awaits `Zotero.initializationPromise`, registers chrome `zotero-plugin-scaffold-test-runner`, then `launchTests()`: waits `test.startupDelay` (default 1s), polls `test.waitForPlugin` via `eval` every 100ms up to 10s (template sets `() => Zotero.<instance>.data.initialized`), then `Services.ww.openWindow` opens a **real chrome window** `chrome://zotero-plugin-scaffold-test-runner/content/index.xhtml` (4410-4504).
   - `content/index.xhtml` — loads `chrome://zotero/content/include.js` (Zotero globals), `mocha.js`, `chai.js` (from local node_modules or CDN: jsdelivr mocha / chaijs.com, cached in `.scaffold/cache`, 4745-4777), mocha setup, then bundled test files, then `mocha.run()` (4507-4551).
   - `content/units/*.js` — user's `test.entries` glob `**/*.{spec,test}.[jt]s` esbuild-bundled, target `firefox115` (4778-4789).
5. Custom mocha `Reporter` POSTs each runner event (`start`/`suite`/`suite end`/`pending`/`pass`/`fail`/`end`/`debug`) as JSON to `http://localhost:<port>/update` via `Zotero.HTTP.request` (4570-4715). On `end`, if `exitOnFinish` (= `!test.watch`), `Zotero.Utilities.Internal.quit(0)` quits Zotero (4709-4712).
6. `startZotero()` (4889-4916): ZoteroRunner with profile `.scaffold/test/profile`, dataDir `.scaffold/test/data`, and **two** temporary plugins: `[{id: ctx.id, sourceDir: dist/addon}, {id: "scaffold-test@northword.cn", sourceDir: .scaffold/test/resource}]` — both installed via the same RDP `installTemporaryAddon`.
7. `onZoteroExit` → `process.exit(reporter.failed ? 1 : 0)` (4917-4924) — CI exit code derives from the POSTed `end` payload counts.

Watch mode (4853-4888): source change → rebuild + regen impacted tests (esbuild metafile input→output mapping, 4805-4817) + `reloadAllPlugins()`; test-file change → regen + reload only the test-runner addon. `isCI` (std-env) forces `headless: true` + `watch: false` (4828-4831). Headless path (4226-4294): apt-installs xvfb (ubuntu/debian only), wget's Zotero linux beta tarball if no `ZOTERO_PLUGIN_ZOTERO_BIN_PATH`.

## 3. Config surface (`zotero-plugin.config.ts`)

Full defaults at bundle:88-181. Fields:

- top: `source` ("src"), `dist` (".scaffold/build"), `watchIgnore`, `name`, `id`, `namespace`, `xpiName`, `updateURL`, `xpiDownloadLink` (templated `{{owner}}/{{repo}}/{{version}}/{{xpiName}}/{{buildTime}}/{{updateJson}}`, 60-71), `logLevel`.
- `build`: `assets` (`"addon/**/*.*"`), `define`, `fluent{prefixFluentMessages,prefixLocaleFiles,ignore,dts}`, `prefs{prefix,prefixPrefKeys,dts}`, `esbuildOptions[]`, `makeManifest{enable,template}`, `makeUpdateJson{updates,hash}`, `hooks`.
- `server`: `devtools` (true→`--jsdebugger`), `startArgs[]`, `prefs{}`, `asProxy` (false), `prebuild` (true), `createProfileIfMissing` (true), `hooks`. **No profile/dataDir/binary fields — env vars only.**
- `test`: `entries` ("test"), `prefs{}`, `mocha.timeout` (10s), `abortOnFail`, `headless`, `startupDelay` (1s), `waitForPlugin` (JS expr string, default `"() => true"`), `watch` (true), `hooks`.
- `release`: `bumpp{release,preid,confirm,commit:"chore(publish): release v%s",tag:"v%s",...}`, `github{enable:"ci",repository,updater,releaseNote}`, `changelog`, `hooks`.
- Hooks (`hookable`): `serve:init/prebuild/ready/onChanged/onReloaded/exit`, `test:init/prebuild/bundleTests/run/exit`, `build:init/mkdir/copyAssets/makeManifest/fluent/bundle/pack/makeUpdateJSON/done`.

Env vars (all via `.env` or real env): `ZOTERO_PLUGIN_ZOTERO_BIN_PATH` (required), `ZOTERO_PLUGIN_PROFILE_PATH`, `ZOTERO_PLUGIN_DATA_DIR`, `ZOTERO_PLUGIN_KILL_COMMAND`, `GITHUB_TOKEN` (release), `NODE_ENV`.

## 4. `zotero-plugin build` outputs

`dist` default `.scaffold/build`. `prepareAssets` empties dist, copies `build.assets` into `dist/addon/`, applies `define` substitutions, generates `manifest.json`, fluent locale files, `prefs.js` (816-848). `bundle()` runs esbuildOptions (849-853). Only when `NODE_ENV=production` (i.e. `zotero-plugin build` without `--dev`; serve/test never pack): `pack()` zips `dist/addon/` → `dist/<xpiName>.xpi` (800-804), plus `dist/update-beta.json` always and `dist/update.json` for non-prerelease versions (762-798, 854-859).

## 5. The RDP channel (vendored web-ext client, bundle:3494-3852)

Wire format: `<decimal byte length>:<JSON>` in both directions (write:3599, parse:3505-3533). TCP to `127.0.0.1:<port>`; on connect the server sends a greeting `from:"root"` (expected via `expectReply("root")`, 3556). Replies matched by `from` actor; unsolicited event types are swallowed (3494-3504, 3650-3666).

Verbatim message sequence for install+reload (scaffold's actual usage):

```
S→C  {"from":"root","applicationType":"firefox","traits":{...}}          # greeting
C→S  {"to":"root","type":"getRoot"}                                     # 3760
S→C  {"from":"root","addonsActor":"server0.conn0.addonsN", ...}         # fallback: {"to":"root","type":"listTabs"} (3773)
C→S  {"to":"<addonsActor>","type":"installTemporaryAddon","addonPath":"/abs/.scaffold/build/addon"}   # 3794-3798
S→C  {"from":"<addonsActor>","addon":{"id":"x@y","actor":"<addonActor>",...}}
C→S  {"to":"root","type":"listAddons"}                                  # 3810 → {addons:[{id,actor},...]}
C→S  {"to":"<addonActor>","type":"requestTypes"}                        # 3833 → {requestTypes:[..."reload"...]}
C→S  {"to":"<addonActor>","type":"reload"}                              # 3849
```

### Arbitrary JS eval — for our `rdp` tool

Scaffold never evals JS over RDP (addon lifecycle only). Verified recipe on Firefox ESR140 (our Zotero 140.10.0esr base), from mozilla-esr140 actor specs:

```
C→S  {"to":"root","type":"getProcess","id":0}
S→C  {"from":"root","processDescriptor":{"actor":"...processDescriptorN","parent":true,...}}
     # alternative: {"to":"root","type":"listProcesses"} → {"processes":[{actor,...}]}
C→S  {"to":"<processDescriptor>","type":"getTarget"}
S→C  {"from":"<processDescriptor>","process":{"actor":"...parentProcessTargetN",
      "consoleActor":"...consoleN","threadActor":"...","targetType":"parentProcess",...}}
     # form carries consoleActor+threadActor directly — no separate attach needed
C→S  {"to":"<consoleActor>","type":"evaluateJS","text":"Zotero.getMainWindow().document.title"}
S→C  {"from":"<consoleActor>","type":"evaluationResult","input":"...","result":<grip>,
      "hasException":false,"exceptionMessage":...}
```

- `evaluateJS` is gone from the ESR140 spec file but the handler still exists in `WebConsoleActor` (devtools/server/actors/webconsole.js) — sync eval, reply is the result.
- `evaluateJSAsync` (the only specced form): request `{text, eager, ...}` → immediate `{resultID}` reply, then the result arrives as an unsolicited `{"type":"evaluationResult","resultID":...,"result":<grip>,...}` event — must correlate by resultID.
- Object results return grips (`{type:"object",class,actor}`) — wrap expressions in `JSON.stringify(...)` for scalar transport, or `{"to":"<gripActor>","type":"release"}` to free.
- Eval runs with parent-process system principal: `Zotero`, `Services`, `ChromeUtils`, `Cc`, `Ci`, `Zotero.getMainWindow()` all reachable.
- Requires `-start-debugger-server <port>` at launch + prefs `devtools.debugger.remote-enabled`, `prompt-connection:false`, `devtools.chrome.enabled:true` — scaffold writes all of these into the dev profile already. See `zotero/dev/research/rdp.md` for the live-verified spike.

### Alternate eval channel: toolkit DebugBridge

`zotero://ztoolkit-debug/?run=<urlencoded JS>&app=<name>[&password=<pw>]` (also `?file=file:///abs.js`) → inside Zotero runs `new AsyncFunction("Zotero","window",run)(Zotero, mainWindow)` — fire-and-forget, no return value; errors go to `Zotero.debug`. Registered **by the plugin itself** via `Services.io.getProtocolHandler("zotero").wrappedJSObject._extensions["zotero://ztoolkit-debug"]` (toolkit `dist/index.js:26-95`). Auth: `disableDebugBridgePassword` flag, else pref `extensions.zotero.debug-bridge.password` match, else interactive `window.confirm`. Marked `@deprecated` upstream ("scaffold no longer needs this"). Scaffold uses it only for asProxy reload (4052-4075).

## 6. Toolkit surface (zotero-plugin-toolkit 5.1.0-beta.13)

`new ZoteroToolkit()` (`dist/index.js:4372-4400`) exposes: `UI` (UITool), `Reader` (ReaderTool), `ExtraField`, `FieldHooks`, `Keyboard` (KeyboardManager), `Prompt`, `Menu` (MenuManager — menu/popup/item registration), `Clipboard`, `FilePicker`, `Patch`, `ProgressWindow`, `VirtualizedTable`, `Dialog` (DialogHelper), `LargePrefObject` (LargePrefHelper — large pref-pane binding), `Guide`; `unregisterAll()` cleans everything. For our prefs UI: `SettingsDialogHelper`/`LargePrefHelper`; menu items: `MenuManager`.

## Surprises / sharp edges

- **`"no-remote"` lacks dashes** (3945; still in 0.8.8:3641) — a positional arg Zotero likely treats as a file to open. Side effect: the instance stays remote-command capable, which is exactly what the asProxy `-url` reload hack relies on. For our own launcher use `-no-remote` deliberately or omit knowingly.
- **`exit()` runs `pkill -9 zotero`** on Linux (4104-4105) — kills the user's real Zotero too. `ZOTERO_PLUGIN_KILL_COMMAND` env overrides.
- **Test results never cross RDP** — in-Zotero mocha window POSTs to a node-side HTTP server; exit code comes from POSTed counts, so a Zotero crash mid-run = hang, not failure.
- **Binary path is env-only** — `ZOTERO_PLUGIN_ZOTERO_BIN_PATH`; no config field exists. Template `.env.example` confirms.
- **Test window is a real opened chrome window** (`chrome,centerscreen,resizable=yes`, 4481-4487) — needs a display; headless only via apt+xvfb on ubuntu/debian.
- **`evaluateJS` removed from spec, still implemented** on ESR140 — sync eval works, but `evaluateJSAsync`+resultID is the forward-compatible path.
