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

# Preference pane label (Zotero settings sidebar) + dialog window title.
prefs-title = TeXlate
prefs-dialog-title = TeXlate Settings

# Preferences dialog fields (modules/prefs.ts SettingsDialogHelper).
prefs-server-url = Server URL
prefs-api-key = API key (optional)
prefs-attach-zh = Attach Chinese PDF (zh.pdf)
prefs-attach-en = Attach English PDF (en.pdf)
prefs-attach-dual = Attach bilingual PDF (dual.pdf)
prefs-batch-delay = Delay between batch items (ms)
prefs-poll-interval = Poll interval (ms)
prefs-poll-timeout = Poll timeout (ms)
prefs-status = Connection
prefs-check = Check connection
prefs-checking = Checking…
prefs-health-ok = Connected — server version { $version }
prefs-health-bad = Unexpected response — is a TeXlate server at this URL?
prefs-health-down = Cannot reach the server — is `uvx texlate web` running?
prefs-save = Save
prefs-cancel = Cancel

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

# Translate flow (modules/flow.ts) — ProgressWindow lines.
flow-start = Translating { $id }…
flow-done = Translation finished — PDF attached to the item.
flow-partial-warn = Task finished partially — some segments may be untranslated.
flow-already-translated = Already translated — use "Open in Reader" to view it.
flow-needs-auth = The server requires sign-in — opening { $serverUrl } to authorize.
flow-attach-failed = Could not attach the translated PDF: { $detail }
flow-batch-summary = { $failed ->
    [0] Batch finished: all { $total } items translated.
   *[other] Batch finished: { $ok } of { $total } translated, { $failed } failed.
}

# Flow errors (ProgressWindow fail lines).
flow-error-not-regular = Only regular items can be translated.
flow-error-no-arxiv-id = No arXiv ID found on this item.
flow-error-inflight = This item already has a translation in progress.
flow-error-server-down = Cannot reach the TeXlate server at { $serverUrl } — start it with `uvx texlate web` or check the server URL in settings.
flow-error-server-unhealthy = The TeXlate server responded but reports unhealthy.
flow-error-invalid-arxiv-id = The server rejected this arXiv ID: { $detail }
flow-error-api = Server error { $status }: { $detail }
flow-error-poll-timeout = Timed out waiting for the translation to finish.
flow-error-task-fault = Translation failed: { $detail }
flow-error-task-cancelled = The translation task was cancelled.
flow-error-task-interrupted = The translation task was interrupted.
flow-error-unexpected = Unexpected error: { $message }
