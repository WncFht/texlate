# TeXlate addon strings (en-US).
#
# Key convention: zotero-plugin-scaffold prefixes every message id with the
# addonRef at build (`<key>` -> `texlate-<key>`) and renames this file to
# `texlate-addon.ftl`. This is the ONLY file getString() resolves against
# (initLocale loads `texlate-addon.ftl`), so every programmatic string lives
# here; declarative window l10n lives in mainWindow.ftl, the prefs pane in
# preferences.ftl.

# Item context-menu labels — mirrored in mainWindow.ftl; kept here so
# getString() callers can resolve them too.
translate = TeXlate: Translate to Chinese
open-reader = TeXlate: Open in Reader

# Preference pane label (Zotero settings sidebar). Field/button labels are
# DOM l10n in preferences.ftl; only the runtime t() strings live here.
prefs-title = TeXlate
prefs-checking = Checking…
prefs-health-ok = Connected — server version { $version }
prefs-health-bad = Unexpected response — is a TeXlate server at this URL?
prefs-health-down = Cannot reach the server — is `uvx texlate web` running?
prefs-probing = Probing the translation endpoint…
prefs-probe-ok = Translation endpoint usable: { $detail }
prefs-probe-bad = Translation endpoint failed: { $detail }
prefs-probe-none = No endpoint profile on the server to probe.
prefs-probe-forbidden = The server runs in deploy mode — the endpoint archive is managed by the operator, so probing is unavailable.

# Progress phases — modules/poller.ts phaseKey() picks the suffix from the
# task stage (fetching…compiling) or status (queued + terminal states);
# modules/flow.ts renders "{phase} {progress}%".
phase-queued = Queued
phase-fetching = Fetching source
phase-parsing = Parsing LaTeX
phase-translating = Translating
phase-compiling = Compiling PDF
phase-done = Done
phase-partial = Partially completed
phase-fault = Failed
phase-cancelled = Cancelled
phase-interrupted = Interrupted
phase-needs_auth = Authorization needed

# Item-pane task section (modules/taskpane.ts) — empty state + header count.
taskpane-empty = No translation tasks yet.
taskpane-running-count = { $count } running

# Translate flow (modules/flow.ts) — task pane lines + completion toast.
flow-done = Translation finished — PDF attached to the item.
flow-done-missing = Translation finished — PDF attached; not produced: { $kinds }
flow-partial-warn = Task finished partially — some segments may be untranslated.
flow-already-translated = Already translated — use "Open in Reader" to view it.
flow-needs-auth = The server requires sign-in — opening { $serverUrl } to authorize.
flow-attach-failed = Could not attach the translated PDF: { $detail }
flow-batch-summary = { $failed ->
    [0] Batch finished: all { $total } items translated.
   *[other] Batch finished: { $ok } of { $total } translated, { $failed } failed.
}

# Flow errors (task pane / toast fail lines).
flow-error-not-regular = Only regular items can be translated.
flow-error-no-arxiv-id = No arXiv ID found on this item.
flow-error-inflight = This item already has a translation in progress.
flow-error-server-down = Cannot reach the TeXlate server at { $serverUrl } — start it with `uvx texlate web` or check the server URL in settings.
flow-error-server-unhealthy = The TeXlate server responded but reports unhealthy.
flow-boot-prepare = Setting up the local server — downloading tools on first run, this can take a few minutes.
flow-boot-wait = Starting the local server… { $s }s
flow-error-bootstrap = Could not start the local TeXlate server: { $detail }
flow-error-invalid-arxiv-id = The server rejected this arXiv ID: { $detail }
flow-error-api = Server error { $status }: { $detail }
flow-error-poll-timeout = Timed out waiting for the translation to finish.
flow-error-task-fault = Translation failed: { $detail }
flow-error-task-cancelled = The translation task was cancelled.
flow-error-task-interrupted = The translation task was interrupted.
flow-error-unexpected = Unexpected error: { $message }
