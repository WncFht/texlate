/**
 * bootstrap.ts — plugin self-start of the local texlate server.
 *
 * Trigger contract (healthOrBootstrap): health() NetworkError + loopback
 * serverUrl + prefs.autoStart → ensureServer() → one health retry. The only
 * external prerequisite is `uv`: uvx texlate web resolves Python + deps, and
 * texlate auto-installs its tectonic toolchain on first compile — so when no
 * uv/uvx is on PATH we download the pinned standalone binary once into
 * ~/.texlate/bin/ (sha256-verified, same discipline as compile/toolchain.py).
 *
 * The server is spawned DETACHED: `sh -c 'nohup … &'` (or PowerShell
 * Start-Process on Windows) so the sh exits immediately and the grandchild
 * server survives Zotero quitting and any Subprocess child reaping. Output
 * goes to ~/.texlate/bootstrap-server.log — failure details point there.
 * texlate's own <data_dir>/service.lock makes a second instance exit early,
 * so double-spawn is harmless — but a lock held by a server on ANOTHER port
 * means ours exits too; that surfaces as a health timeout whose detail says
 * to check the log.
 */

import {
  BootstrapError,
  NetworkError,
  type HealthResponse,
  type TexlateClient,
  type TexlatePrefs,
} from "../contracts";
import { createClient } from "./client";
import { t } from "../utils/locale";
import { errText, sleep } from "../utils/misc";

export const BOOTSTRAP_TIMEOUT_MS = 300_000;
const HEALTH_POLL_MS = 1500;
const DOWNLOAD_TIMEOUT_MS = 300_000;
const UV_VERSION = "0.12.23";

interface SubprocessProc {
  wait(): Promise<{ exitCode: number }>;
}
interface SubprocessApi {
  call(opts: {
    command: string;
    arguments: string[];
    stdout?: string;
    stderr?: string;
  }): Promise<SubprocessProc>;
  pathSearch(name: string): Promise<string>;
}

let _subprocess: SubprocessApi | null = null;
function subprocess(): SubprocessApi {
  if (!_subprocess) {
    _subprocess = (
      ChromeUtils.importESModule(
        "resource://gre/modules/Subprocess.sys.mjs",
      ) as { Subprocess: SubprocessApi }
    ).Subprocess;
  }
  return _subprocess;
}

/** `{cmd, args}` — uvx runs `texlate web` directly; uv needs `tool run`. */
export interface UvCommand {
  cmd: string;
  args: string[];
}

/** hostname ∈ {localhost, ::1, 127.*} — remote servers never get spawned. */
export function isLoopbackUrl(serverUrl: string): boolean {
  try {
    // URL.hostname keeps the IPv6 brackets: "[::1]" — strip before compare.
    const host = new URL(serverUrl).hostname.toLowerCase();
    return (
      host === "localhost" || host === "[::1]" || host.startsWith("127.")
    );
  } catch {
    return false;
  }
}

function homeDir(): string {
  return (Services.dirsvc.get("Home", Ci.nsIFile) as nsIFile).path;
}

function managedBinDir(): string {
  return PathUtils.join(homeDir(), ".texlate", "bin");
}

function exe(name: string): string {
  return Zotero.isWin ? `${name}.exe` : name;
}

/** `cmd --version` sanity probe — exec waits for exit, which is what we want.
 * Probes the base binary only: appending the `tool run` args prefix would turn
 * `uv --version` into the invalid `uv tool run --version`. */
async function runnable(cmd: string): Promise<boolean> {
  try {
    const r = await Zotero.Utilities.Internal.exec(cmd, ["--version"]);
    return r === true;
  } catch {
    return false;
  }
}

async function uvFromDir(dir: string): Promise<UvCommand | null> {
  const uvx = PathUtils.join(dir, exe("uvx"));
  if (await IOUtils.exists(uvx)) return { cmd: uvx, args: [] };
  const uv = PathUtils.join(dir, exe("uv"));
  if (await IOUtils.exists(uv)) return { cmd: uv, args: ["tool", "run"] };
  return null;
}

/**
 * Resolve a runnable uv: managed dir → PATH (uvx then uv). The winner gets a
 * `--version` probe so a corrupt managed copy falls through to re-download.
 */
export async function findUv(): Promise<UvCommand | null> {
  const managed = await uvFromDir(managedBinDir());
  if (managed && (await runnable(managed.cmd))) return managed;
  for (const name of [exe("uvx"), exe("uv")]) {
    try {
      const found = await subprocess().pathSearch(name);
      if (!found) continue;
      const cand: UvCommand =
        name === exe("uvx")
          ? { cmd: found, args: [] }
          : { cmd: found, args: ["tool", "run"] };
      if (await runnable(cand.cmd)) return cand;
    } catch {
      /* not on PATH — try next */
    }
  }
  return null;
}

// ------------------------------------------------------------------ download

/** platform target triple → {file, sha256} for the pinned uv release. */
const UV_ASSETS: Record<string, { file: string; sha256: string }> = {
  "x86_64-apple-darwin": {
    file: "uv-x86_64-apple-darwin.tar.gz",
    sha256:
      "960da44cb4b73685206ddd250b19e0a117fa41095710c1038f081f5cb613efb4",
  },
  "aarch64-apple-darwin": {
    file: "uv-aarch64-apple-darwin.tar.gz",
    sha256:
      "50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544",
  },
  "x86_64-unknown-linux-gnu": {
    file: "uv-x86_64-unknown-linux-gnu.tar.gz",
    sha256:
      "9167d72b3319674b6303c4cbe071854bba13ebdf3d76b1a7cbdc175471fb66d6",
  },
  "aarch64-unknown-linux-gnu": {
    file: "uv-aarch64-unknown-linux-gnu.tar.gz",
    sha256:
      "6524bd338177ed50d035d39354e12545e993bbeba2ecbddf0480c5b3a81d313f",
  },
  "x86_64-pc-windows-msvc": {
    file: "uv-x86_64-pc-windows-msvc.zip",
    sha256:
      "75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90",
  },
  "aarch64-pc-windows-msvc": {
    file: "uv-aarch64-pc-windows-msvc.zip",
    sha256:
      "13294e232ececbe709c06b74e6ced06f2a225ea5591476685362f22be56a50d5",
  },
  "i686-pc-windows-msvc": {
    file: "uv-i686-pc-windows-msvc.zip",
    sha256:
      "22a92f4374e4716c2848acaa0392f2f8e4a13b0ff65d080e2a5ade167bce96a8",
  },
};

function uvTarget(): { file: string; sha256: string; target: string } {
  const os =
    Services.appinfo.OS === "Darwin"
      ? "apple-darwin"
      : Services.appinfo.OS === "WINNT"
        ? "pc-windows-msvc"
        : "unknown-linux-gnu";
  let arch = Services.appinfo.XPCOMABI.split("-")[0];
  if (arch === "x86" || arch === "i386") arch = "i686";
  const target = `${arch}-${os}`;
  const asset = UV_ASSETS[target];
  if (!asset) throw new BootstrapError(`unsupported-platform: ${target}`);
  return { ...asset, target };
}

function sha256Hex(buf: ArrayBuffer): Promise<string> {
  return crypto.subtle.digest("SHA-256", buf).then((d) =>
    Array.from(new Uint8Array(d))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join(""),
  );
}

async function extractArchive(tar: string, archive: string, dest: string) {
  const proc = await subprocess().call({
    command: tar,
    arguments: ["-xzf", archive, "-C", dest],
    stderr: "pipe",
  });
  const { exitCode } = await proc.wait();
  if (exitCode !== 0) {
    throw new BootstrapError(`tar exited ${exitCode} extracting ${archive}`);
  }
}

/**
 * uv tarballs nest binaries under `uv-<target>/`; the Windows zip is flat.
 * Flatten the nested dir into binDir so the managed layout is uniform.
 */
async function flattenNestedTargetDir(
  binDir: string,
  target: string,
): Promise<void> {
  const nested = PathUtils.join(binDir, `uv-${target}`);
  if (!(await IOUtils.exists(nested))) return;
  for (const name of [exe("uv"), exe("uvx")]) {
    const src = PathUtils.join(nested, name);
    if (await IOUtils.exists(src)) {
      await IOUtils.move(src, PathUtils.join(binDir, name));
    }
  }
  await IOUtils.remove(nested, { recursive: true, ignoreAbsent: true });
}

/**
 * Download + verify + extract the pinned uv release into ~/.texlate/bin.
 * XHR bytes → IOUtils.write carry no macOS quarantine xattr, so the binary
 * runs without Gatekeeper friction. bsdtar reads .zip too (Win10+ ships
 * System32\tar.exe), so one extractor covers all platforms.
 */
export async function downloadUv(): Promise<UvCommand> {
  const asset = uvTarget();
  const url =
    `https://github.com/astral-sh/uv/releases/download/` +
    `${UV_VERSION}/${asset.file}`;
  const binDir = managedBinDir();
  await IOUtils.makeDirectory(binDir, { createAncestors: true });

  const xhr = await Zotero.HTTP.request("GET", url, {
    responseType: "arraybuffer",
    timeout: DOWNLOAD_TIMEOUT_MS,
    successCodes: false,
  });
  if (xhr.status !== 200) {
    throw new BootstrapError(`uv download HTTP ${xhr.status} — ${url}`);
  }
  const bytes = new Uint8Array(xhr.response as ArrayBuffer);
  if ((await sha256Hex(bytes.buffer as ArrayBuffer)) !== asset.sha256) {
    throw new BootstrapError(`uv sha256 mismatch — refusing to install`);
  }

  const archive = PathUtils.join(binDir, asset.file);
  await IOUtils.write(archive, bytes);
  const tar = Zotero.isWin
    ? "C:\\Windows\\System32\\tar.exe"
    : await subprocess()
        .pathSearch("tar")
        .catch(() => "/usr/bin/tar");
  try {
    await extractArchive(tar, archive, binDir);
  } finally {
    await IOUtils.remove(archive, { ignoreAbsent: true });
  }
  await flattenNestedTargetDir(binDir, asset.target);

  const uv = await uvFromDir(binDir);
  if (!uv) throw new BootstrapError(`uv archive missing binaries — ${binDir}`);
  if (!Zotero.isWin) {
    for (const name of ["uv", "uvx"]) {
      const p = PathUtils.join(binDir, name);
      if (await IOUtils.exists(p)) await IOUtils.setPermissions(p, 0o755);
    }
  }
  if (!(await runnable(uv.cmd))) {
    throw new BootstrapError(`installed uv fails --version — ${uv.cmd}`);
  }
  return uv;
}

// --------------------------------------------------------------------- spawn

function shQuote(s: string): string {
  return `'${s.replace(/'/g, `'\\''`)}'`;
}

function psQuote(s: string): string {
  return `'${s.replace(/'/g, "''")}'`;
}

export function bootstrapLogPath(): string {
  return PathUtils.join(homeDir(), ".texlate", "bootstrap-server.log");
}

interface ServerArgs {
  host: string;
  port: string;
  dataDir: string;
}

function serverArgs(serverUrl: string, dataDir: string): ServerArgs {
  let host = "127.0.0.1";
  let port = "8765";
  try {
    const u = new URL(serverUrl);
    host = u.hostname.replace(/^\[|\]$/g, "") || host;
    port = u.port || port;
  } catch {
    /* malformed — fall back to defaults */
  }
  return { host, port, dataDir };
}

/** uvx/uv 实参序列：args 前缀 + texlate web + 可选 --data-dir。 */
function texlateArgv(uv: UvCommand, a: ServerArgs): string[] {
  const argv = [
    ...uv.args,
    "texlate",
    "web",
    "--host",
    a.host,
    "--port",
    a.port,
  ];
  if (a.dataDir) argv.push("--data-dir", a.dataDir);
  return argv;
}

/**
 * Spawn `uvx texlate web` detached, stdout/stderr → bootstrap log. Unix goes
 * through `sh -c 'nohup … &'` so the immediate child exits at once and the
 * server is orphaned (survives Zotero quit); Windows uses PowerShell
 * Start-Process for the same detach semantics.
 */
async function spawnServer(uv: UvCommand, prefs: TexlatePrefs): Promise<void> {
  const a = serverArgs(prefs.serverUrl, prefs.bootstrapDataDir);
  const log = bootstrapLogPath();
  await IOUtils.makeDirectory(PathUtils.parent(log) ?? homeDir(), {
    createAncestors: true,
  });
  const argv = texlateArgv(uv, a);
  try {
    if (Zotero.isWin) {
      const argList = argv.map((s) => `'${s.replace(/'/g, "''")}'`).join(",");
      const ps =
        `Start-Process -WindowStyle Hidden -FilePath ${psQuote(uv.cmd)} ` +
        `-ArgumentList ${argList} ` +
        `-RedirectStandardOutput ${psQuote(log)} ` +
        `-RedirectStandardError ${psQuote(log + ".err")}`;
      const proc = await subprocess().call({
        command: "powershell",
        arguments: ["-NoProfile", "-Command", ps],
      });
      await proc.wait();
    } else {
      const cmd =
        `nohup ${shQuote(uv.cmd)} ${argv.map(shQuote).join(" ")} ` +
        `>>${shQuote(log)} 2>&1 </dev/null &`;
      const proc = await subprocess().call({
        command: "/bin/sh",
        arguments: ["-c", cmd],
      });
      await proc.wait();
    }
  } catch (e) {
    throw new BootstrapError(`spawn failed: ${errText(e)}`);
  }
}

// -------------------------------------------------------------------- ensure

let inflight: Promise<void> | null = null;

async function doEnsureServer(
  prefs: TexlatePrefs,
  onPhase?: (text: string) => void,
): Promise<void> {
  let uv = await findUv();
  if (!uv) {
    onPhase?.(t("flow-boot-prepare"));
    uv = await downloadUv();
  }
  await spawnServer(uv, prefs);
  const client = createClient(prefs);
  const deadline = Date.now() + BOOTSTRAP_TIMEOUT_MS;
  const t0 = Date.now();
  while (Date.now() < deadline) {
    try {
      const h = await client.health();
      if (h.ok) return;
    } catch {
      /* not up yet — keep polling */
    }
    onPhase?.(
      t("flow-boot-wait", { s: Math.floor((Date.now() - t0) / 1000) }),
    );
    await sleep(HEALTH_POLL_MS);
  }
  throw new BootstrapError(
    `server not healthy within ${BOOTSTRAP_TIMEOUT_MS / 1000}s — ` +
      `see ${bootstrapLogPath()}`,
  );
}

/** Batch dedupe: N concurrent callers share one spawn attempt. */
export function ensureServer(
  prefs: TexlatePrefs,
  onPhase?: (text: string) => void,
): Promise<void> {
  inflight ??= doEnsureServer(prefs, onPhase).finally(() => {
    inflight = null;
  });
  return inflight;
}

/**
 * health() with a local bootstrap arm: NetworkError + loopback + autoStart →
 * ensureServer → one retry. Everything else rethrows untouched so upstream
 * attribution (sabotage, error rows) keeps its original shape.
 */
export async function healthOrBootstrap(
  client: TexlateClient,
  prefs: TexlatePrefs,
  onPhase?: (text: string) => void,
): Promise<HealthResponse> {
  try {
    return await client.health();
  } catch (e) {
    if (
      !(e instanceof NetworkError) ||
      !prefs.autoStart ||
      !isLoopbackUrl(prefs.serverUrl)
    ) {
      throw e;
    }
    await ensureServer(prefs, onPhase);
    return await client.health();
  }
}

/** Wire onto addon.api — `Zotero.texlate.api.bootstrap.*` for RDP/dev-verify. */
export function installBootstrap(): void {
  Object.assign(addon.api, {
    bootstrap: {
      isLoopbackUrl,
      findUv,
      downloadUv,
      ensureServer,
    },
  });
}
