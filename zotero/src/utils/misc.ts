/**
 * misc.ts — small shared helpers (async sleep, error→text, item field read).
 */

export function sleep(ms: number): Promise<void> {
  // Bare setTimeout is the real runtime function — Zotero.setTimeout is
  // declared in zotero.d.ts but absent in Zotero 9 (dev-verify caught it:
  // TypeError on the first poll sleep). Declared in typings/global.d.ts.
  return new Promise((r) => setTimeout(r, ms));
}

/** Error → single-line message for machine codes and logs. */
export function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * getField tolerant of non-regular items, plain objects, and odd values.
 * Returns "" for anything missing or throwing — callers that need to
 * distinguish absent from empty shouldn't use this.
 */
export function fieldText(item: Zotero.Item, name: string): string {
  try {
    if (typeof item.getField !== "function") return "";
    const v: unknown = item.getField(name as _ZoteroTypes.Item.ItemField);
    if (v === null || v === undefined) return "";
    return typeof v === "string" ? v : String(v);
  } catch {
    return "";
  }
}
