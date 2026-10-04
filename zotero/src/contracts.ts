/**
 * contracts.ts — shared types & function signatures for all texlate plugin modules.
 *
 * Single source of truth: module agents implement against these signatures.
 * Server API facts — routes live in src/texlate/server/routers/
 * ({meta,tasks,files}.py); the 202/error body shape in server/http.py
 * (_accepted/_json_error); the db_kind↔url_kind map + artifact_urls in
 * server/worker/_common.py (KIND_URL/URL_KIND):
 *   GET  /api/health                       → {ok, version?, ...}
 *   POST /api/arxiv/{id}/translate  {}     → 202 {task_id, status, events_url, reader_url?}
 *   GET  /api/task/{id}                    → snapshot (no SSE in plugin sandbox)
 *   GET  /api/files/{id}                   → {artifacts: {db_kind: {bytes,sha256,created_at,url}}}
 *   GET  /api/files/{id}/{url_kind}        → bytes (url_kind: zh.pdf, en.pdf, dual.pdf, ...)
 *   Reader SPA: {base}/#/reader/{taskId}
 */

// ---------------------------------------------------------------- status machine

export const ACTIVE_STATUSES = [
  "queued",
  "fetching",
  "parsing",
  "translating",
  "compiling",
] as const;
export const TERMINAL_STATUSES = [
  "done",
  "partial",
  "fault",
  "cancelled",
  "interrupted",
  "needs_auth",
] as const;

/**
 * Server RETRYABLE_FROM (server/store/_common.py): terminal states POST
 * /api/task/{id}/retry accepts. Matters because `interrupted` still counts
 * as active for translate dedup — a 409 can hand back a dead task_id.
 */
export const RETRYABLE_STATUSES = [
  "fault",
  "partial",
  "cancelled",
  "interrupted",
  "needs_auth",
] as const;

export type ActiveStatus = (typeof ACTIVE_STATUSES)[number];
export type TerminalStatus = (typeof TERMINAL_STATUSES)[number];
export type TaskStatus = ActiveStatus | TerminalStatus;

export function isActiveStatus(s: string): s is ActiveStatus {
  return (ACTIVE_STATUSES as readonly string[]).includes(s);
}
export function isTerminalStatus(s: string): s is TerminalStatus {
  return (TERMINAL_STATUSES as readonly string[]).includes(s);
}
export function isRetryableStatus(s: string): boolean {
  return (RETRYABLE_STATUSES as readonly string[]).includes(s);
}

/** Stage order for phase-label mapping (snapshot.stage ∈ STAGES). */
export const STAGES = [
  "fetching",
  "parsing",
  "translating",
  "compiling",
] as const;

// ---------------------------------------------------------------- server DTOs

export interface HealthResponse {
  ok: boolean;
  version?: string;
  commit?: string;
  compilers?: Record<string, boolean>;
  [k: string]: unknown;
}

export interface AcceptedResponse {
  task_id: string;
  status: string;
  events_url: string;
  reader_url?: string;
  [k: string]: unknown;
}

export interface TaskCounters {
  total: number;
  done: number;
  cached: number;
  failed: number;
  tokens: number;
}

export interface TaskSnapshot {
  task_id: string;
  kind: string;
  status: TaskStatus;
  progress: number;
  message: string;
  stage?: string;
  created_at: number;
  updated_at: number;
  counters: TaskCounters;
  /**
   * error_json 键面 = code/message/retryable + 审计 extras 平铺
   * （reject_at、fixloop/precheck/logfix/share/babeldoc——emit._fail/_reject 的
   * detail dict 经 err.update 并进顶层，wire 从不发 "detail" 键）。
   */
  error: {
    code?: string;
    message?: string;
    retryable?: boolean;
    [k: string]: unknown;
  } | null;
  warnings: unknown[];
  /** db kind → url path, e.g. {"zh_pdf": "/api/files/t_x/zh.pdf"} */
  artifacts: Record<string, string>;
  last_seq: number;
  title?: string;
  arxiv_id?: string;
  [k: string]: unknown;
}

export interface FileInfo {
  /** DB 列可空——缺失产物登记记 NULL（worker/emit.py _register 同旧口径） */
  bytes: number | null;
  sha256: string | null;
  created_at: number;
  url: string;
}

export interface FilesResponse {
  /** keyed by DB kind: zh_pdf, en_pdf, dual_pdf, zh_html, md_zip, ... */
  artifacts: Record<string, FileInfo>;
}

// ---------------------------------------------------------------- errors

/** HTTP error: server answered with non-2xx. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  /** Parsed JSON body when the server sent one — 409 carries `task_id`. */
  readonly payload?: Record<string, unknown>;
  constructor(status: number, body: string) {
    let code = "http_error";
    let detail = body;
    let payload: Record<string, unknown> | undefined;
    try {
      const j = JSON.parse(body) as Record<string, unknown>;
      code = String(j.code ?? j.error ?? code);
      detail = String(j.detail ?? j.message ?? body);
      payload = j;
    } catch {
      /* body wasn't JSON — keep raw */
    }
    super(`HTTP ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.payload = payload;
  }
}

/** Network-level failure: DNS, refused, reset — server unreachable. */
export class NetworkError extends Error {
  override readonly name = "NetworkError";
}

/** Caller deadline exceeded (poll timeout, request timeout). */
export class TimeoutError extends Error {
  override readonly name = "TimeoutError";
}

// ---------------------------------------------------------------- prefs

export interface TexlatePrefs {
  /** e.g. "http://127.0.0.1:8765" — no trailing slash (normalized on read). */
  serverUrl: string;
  /** X-Texlate-Key; empty for local unauthenticated instances. */
  apiKey: string;
  /** URL kinds to attach on completion, in order. Default ["zh.pdf"]. */
  attachKinds: string[];
  batchDelayMs: number;
  pollIntervalMs: number;
  pollTimeoutMs: number;
}

// ---------------------------------------------------------------- client

/**
 * HTTP transport for texlate server. Implemented by modules/client.ts.
 *
 * Concrete exports each module MUST provide (parallel-implementation seam):
 *   client.ts   export function createClient(prefs: TexlatePrefs): TexlateClient
 *   arxivId.ts  export function extractArxivId(item): string | null
 *               export function hasArxivId(item): boolean
 *   poller.ts   export function pollTask(client, taskId, opts): Promise<TaskSnapshot>
 *               export function phaseKey(snap: TaskSnapshot): string   // ftl suffix
 *   attach.ts   export function attachArtifacts(item, client, taskId, opts): Promise<AttachResult>
 *               export function getTexlateMark(item): string | null
 *               export function setTexlateMark(item, taskId): Promise<void>
 *   prefs.ts    export function loadPrefs(): TexlatePrefs
 *               export function openPrefsDialog(): void
 *               export function registerPrefsPane(): void
 *   menu.ts     export function registerMenus(win): void
 *               export function computeMenuState(items): MenuState
 *   flow.ts     export function translateItem(item, batch?): Promise<FlowResult>
 *               export function translateItems(items): Promise<FlowResult[]>
 *               export function openInReader(item): boolean   // launchURL'd
 *               export const FILES_GRACE_MS: number
 *   selftest.ts export function selftest(itemID: number): Promise<SelftestResult>
 *               export function selftestNonArxiv(itemID): Promise<SelftestResult>
 *               export function installSelftest(): void
 */
export interface TexlateClient {
  health(): Promise<HealthResponse>;
  createTask(arxivId: string): Promise<AcceptedResponse>;
  getTask(taskId: string): Promise<TaskSnapshot>;
  /** db-kind-keyed artifact map from /api/files/{id}. */
  listFiles(taskId: string): Promise<Record<string, FileInfo>>;
  /**
   * Download /api/files/{taskId}/{urlKind} to destPath (ASCII-safe temp path).
   * Verifies PDF magic for .pdf kinds when `expectPdf`. Returns observed bytes+sha256.
   */
  downloadFile(
    taskId: string,
    urlKind: string,
    destPath: string,
    opts?: { expectPdf?: boolean },
  ): Promise<{ bytes: number; sha256: string }>;
  /** `{serverUrl}/#/reader/{taskId}` — SPA reader link for Zotero.launchURL. */
  readerUrl(taskId: string): string;
}

// ---------------------------------------------------------------- arxivId (modules/arxivId.ts)

/**
 * Extract a raw arXiv id from a Zotero item, 4-level fallback:
 * DOI → url → archiveID → extra. Returns the raw matched string
 * (may carry version suffix / old-format slash prefix) — server normalizes.
 * null when no arXiv trace found.
 */
export type ExtractArxivId = (item: Zotero.Item) => string | null;

// ---------------------------------------------------------------- poller (modules/poller.ts)

export interface PollOptions {
  intervalMs: number;
  timeoutMs: number;
  onProgress?: (snap: TaskSnapshot) => void;
}

/**
 * Poll GET /api/task/{id} every intervalMs via setTimeout until terminal status
 * or timeoutMs. Throws TimeoutError on deadline; resolves with terminal snapshot.
 * Unknown status strings fail fast (they're a protocol bug, not a retry case).
 * NOTE: files-visibility grace (terminal reached but /api/files 404s, ~20s retry
 * window) is owned by flow.ts, not here — it's a files-endpoint concern.
 */
export type PollTask = (
  client: TexlateClient,
  taskId: string,
  opts: PollOptions,
) => Promise<TaskSnapshot>;

// ---------------------------------------------------------------- attach (modules/attach.ts)

export interface AttachedArtifact {
  /** url kind used, e.g. "zh.pdf" */
  kind: string;
  itemID: number;
  title: string;
  /** dedup-skip 臂原样转发 manifest bytes——wire 可 null（见 FileInfo） */
  bytes: number | null;
}

export interface AttachResult {
  attached: AttachedArtifact[];
  /** kinds requested but absent from artifacts listing */
  missing: string[];
  /** kinds present but failed download/import, with reason */
  failed: { kind: string; reason: string }[];
}

/**
 * Download requested kinds → ASCII temp files → Zotero.Attachments.importFromFile
 * as stored attachments on `item`; writes `texlate: {taskId}` Extra mark.
 */
export type AttachArtifacts = (
  item: Zotero.Item,
  client: TexlateClient,
  taskId: string,
  opts: { kinds: string[]; titleHint?: string },
) => Promise<AttachResult>;

/** Parse `texlate: {taskId}` from item Extra. null = never translated. */
export type GetTexlateMark = (item: Zotero.Item) => string | null;

// ---------------------------------------------------------------- menu (modules/menu.ts)

/** Register the two item-context-menu entries + onShowing visibility rules. */
export type RegisterMenus = (win: _ZoteroTypes.MainWindow) => void;

/** Menu visibility decision — pure function shared by the real onShowing
 *  handler and selftest/dev-verify assertions (menu greying must be
 *  assertable without opening a real popup). */
export interface MenuState {
  /** ≥1 selected regular item with extractable arXiv id and no texlate mark */
  translate: boolean;
  /** ≥1 selected item carrying a texlate mark */
  reader: boolean;
}
export type ComputeMenuState = (items: Zotero.Item[]) => MenuState;

// ---------------------------------------------------------------- flow (modules/flow.ts)

/** Files-visibility grace constant (owned by flow.ts): after terminal
 *  status, retry listFiles on empty/404 artifacts up to ~20s — server
 *  "done" races artifact visibility (pdf2zh COMPLETED_FILE_GRACE_MS). */
export interface FlowResult {
  itemID: number;
  ok: boolean;
  /** terminal status seen */
  status?: TerminalStatus;
  taskId?: string;
  attach?: AttachResult;
  /** user-facing error text when !ok */
  error?: string;
}

/**
 * The production translate flow for one item: health-check → extract id →
 * createTask → poll → attach artifacts → Extra mark. Returns a FlowResult
 * (never throws for expected failures — encodes them in `error`).
 */
export type TranslateItem = (item: Zotero.Item) => Promise<FlowResult>;

/** Batch: sequential await + batchDelayMs between items. */
export type TranslateItems = (items: Zotero.Item[]) => Promise<FlowResult[]>;

/** If item carries a texlate mark, launch reader URL; return whether it did. */
export type OpenInReader = (item: Zotero.Item) => boolean;

// ---------------------------------------------------------------- selftest (modules/selftest.ts)

export interface SelftestStep {
  name: string;
  ok: boolean;
  /** attributable evidence: "attached zh.pdf itemID=42 bytes=1234 sha256=ab.." */
  detail: string;
}

export interface SelftestResult {
  ok: boolean;
  itemID: number;
  steps: SelftestStep[];
  /** taskId if a task was created — lets dev-verify cross-check server side */
  taskId?: string;
  error?: string;
}

/**
 * `Zotero.texlate.selftest(itemID)` — runs the full chain against the live
 * server: health → extract arXiv id → createTask → poll → listFiles →
 * download → attach → read Extra mark → build reader URL. Returns the
 * structured result; each step records attributable evidence.
 * Gated: refuses with a `dev-gate` failure unless the global-branch pref
 * `extensions.zotero.texlate.devSelftest === true` (dev-verify writes it
 * via RDP; production xpi ships the code but stays inert without it).
 */
export type Selftest = (itemID: number) => Promise<SelftestResult>;
