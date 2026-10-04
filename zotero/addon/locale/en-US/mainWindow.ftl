# TeXlate main-window strings (en-US).
# Loaded into each Zotero main window via insertFTLIfNeeded in hooks.ts —
# MenuManager menuitem `l10nID`s resolve against the window's DOM l10n.
# Mirrored in addon.ftl so getString() callers resolve the same labels.
# Menu labels MUST use `.label` attribute form — a bare value lands in
# textContent, which XUL menu/menuitem never renders (label stays empty).
# Same convention as zotero.ftl's menu-* messages.

menu =
    .label = TeXlate
translate =
    .label = TeXlate: Translate to Chinese
open-reader =
    .label = TeXlate: Open in Reader

# Item-pane task section — collapsible-section header takes `.label`,
# the sidenav rail toolbarbutton takes `.tooltiptext` (bare values land
# in textContent and never render, same convention as menu-*).
taskpane =
    .label = TeXlate Tasks
taskpane-sidenav =
    .tooltiptext = TeXlate Tasks
