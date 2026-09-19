/**
 * arxivId.ts — extract a raw arXiv id from a Zotero item.
 *
 * 4-level fallback: DOI → url → archiveID → extra. Returns the RAW id
 * (version suffix `v2` and old-format `hep-th/9901001` kept) — the server's
 * `normalize_arxiv_id` owns parsing; we only find the candidate.
 * null = no arXiv trace (menu greys out).
 */
import { fieldText } from "../utils/misc";

/**
 * Cheap sanity check, NOT normalization:
 *   new-style `YYMM.NNNNN` (4-or-5 digit seq) or old-style `archive/YYMMNNN`
 *   (`hep-th/9901001`, `math.AG/0601001`), each with optional `vN` suffix.
 */
const ARXIV_ID_RE =
  /^(?:[a-z-]+(?:\.[A-Z]{2})?\/\d{7}|\d{4}\.\d{4,5})(v\d+)?$/i;

const DOI_RE = /arxiv\.(.+)$/i;
const URL_RE = /arxiv\.org\/(abs|pdf)\/([^?#\s]+)/i;
const EXTRA_RE = /^\s*arXiv\s*[:：]\s*(\S+)/im;

/** Field read tolerant of non-regular items; "" = absent (fails valid()). */
function field(item: Zotero.Item, name: string): string {
  return fieldText(item, name).trim();
}

function valid(candidate: string | null): string | null {
  if (candidate === null) return null;
  // Captures run to end-of-token — real fields trail punctuation
  // ("arXiv: 2101.12345,", "abs/1706.03762/"). Trailing-only strip:
  // old-format ids keep their inner slash.
  const id = candidate.trim().replace(/[.,;)\]/]+$/, "");
  return ARXIV_ID_RE.test(id) ? id : null;
}

/**
 * Level 1 — DOI `10.48550/arXiv.{id}`: most canonical when present.
 *   `10.48550/arXiv.1706.03762`   → `1706.03762`
 *   `10.48550/arXiv.hep-th/9901001` → `hep-th/9901001`
 *   `10.48550/arXiv.1706.03762v3` → `1706.03762v3`
 */
function fromDOI(item: Zotero.Item): string | null {
  const m = field(item, "DOI")?.match(DOI_RE);
  return valid(m?.[1] ?? null);
}

/**
 * Level 2 — url field `arxiv.org/abs|pdf/{id}`:
 *   `https://arxiv.org/abs/hep-th/9901001`   → `hep-th/9901001`
 *   `https://arxiv.org/pdf/2305.10601v2.pdf` → `2305.10601v2`
 */
function fromUrl(item: Zotero.Item): string | null {
  const m = field(item, "url")?.match(URL_RE);
  if (!m?.[2]) return null;
  return valid(m[2].replace(/\.pdf$/i, ""));
}

/**
 * Level 3 — archiveID (Zotero 7 preprint item): bare `2201.00001`
 * or `arXiv:2201.00001` — strip the prefix, keep the rest.
 */
function fromArchiveID(item: Zotero.Item): string | null {
  const v = field(item, "archiveID");
  if (v === "") return null;
  return valid(v.replace(/^\s*arXiv\s*:\s*/i, ""));
}

/**
 * Level 4 — extra field, colon form only (`arXiv: 2101.12345`,
 * `arXiv:hep-th/9901001`, full-width `arXiv：…`) — the shape Zotero
 * translators actually write.
 */
function fromExtra(item: Zotero.Item): string | null {
  const m = field(item, "extra")?.match(EXTRA_RE);
  return valid(m?.[1] ?? null);
}

/**
 * Extract a raw arXiv id, or null when the item carries no arXiv trace.
 * A level whose candidate fails {@link ARXIV_ID_RE} falls through to the
 * next level rather than returning garbage.
 */
export function extractArxivId(item: Zotero.Item): string | null {
  if (!item || typeof item !== "object") return null;
  return (
    fromDOI(item) ?? fromUrl(item) ?? fromArchiveID(item) ?? fromExtra(item)
  );
}

/** Menu visibility helper — greys out entries without an arXiv id. */
export function hasArxivId(item: Zotero.Item): boolean {
  return extractArxivId(item) !== null;
}
