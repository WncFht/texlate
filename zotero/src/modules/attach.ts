/**
 * attach.ts — download task artifacts → ASCII temp files →
 * Zotero.Attachments.importFromFile stored attachments on `item`,
 * then stamp `texlate: {taskId}` into the Extra field.
 *
 * Pits: temp leaf ASCII-only (Windows
 * NS_ERROR_FILE_UNRECOGNIZED_PATH); importFromFile takes parentItemID XOR
 * collections (we pass only parentItemID); storage leaf goes through
 * Zotero.File.getValidFileName; `extra` is a shared overflow field — only
 * our `texlate:` line is rewritten, other lines kept byte-for-byte.
 */
import type { AttachResult, TexlateClient } from "../contracts";
import { errText, fieldText } from "../utils/misc";

/** `texlate: t_xxx` mark line in Extra (full-width colon tolerated). */
const MARK_RE = /^texlate\s*[:：]\s*(t_[a-z0-9]+)\s*$/im;
const MARK_LINE_RE = /^texlate\s*[:：]/i;

const KIND_LABELS: Record<string, string> = {
  "zh.pdf": "中文",
  "en.pdf": "英文原文",
  "dual.pdf": "双语对照",
};

function readExtra(item: Zotero.Item): string {
  return fieldText(item, "extra");
}

function shortTitle(item: Zotero.Item, titleHint?: string): string {
  const st =
    fieldText(item, "shortTitle") ||
    // code-point slice — a raw .slice(40) can leave a lone surrogate
    Array.from(fieldText(item, "title")).slice(0, 40).join("");
  return st || titleHint || "untitled";
}

/** `TeXlate {label} - {shortTitle}`; label from KIND_LABELS, fallback = kind. */
function attachTitle(
  item: Zotero.Item,
  urlKind: string,
  titleHint?: string,
): string {
  return `TeXlate ${KIND_LABELS[urlKind] ?? urlKind} - ${shortTitle(item, titleHint)}`;
}

/** Title → itemID of the item's existing attachments; missing ids = absent. */
function existingAttachByTitle(item: Zotero.Item): Map<string, number> {
  const byTitle = new Map<string, number>();
  let ids: number[];
  try {
    ids = item.getAttachments();
  } catch {
    return byTitle;
  }
  for (const id of ids) {
    try {
      const att = Zotero.Items.get(id);
      if (!att) continue;
      const t = att.getField("title") || att.getDisplayTitle();
      if (t) byTitle.set(t, id);
    } catch {
      /* absent */
    }
  }
  return byTitle;
}

export async function attachArtifacts(
  item: Zotero.Item,
  client: TexlateClient,
  taskId: string,
  opts: { kinds: string[]; titleHint?: string },
): Promise<AttachResult> {
  const result: AttachResult = { attached: [], missing: [], failed: [] };
  const artifacts = await client.listFiles(taskId);
  const seen = existingAttachByTitle(item);
  const temps: string[] = [];
  try {
    for (const urlKind of opts.kinds) {
      // artifacts is keyed by db kind (zh_pdf); the url↔db map lives server-
      // side (worker/_common.py KIND_URL). Don't mirror it — a `.`→`_`
      // regex gets hyphenated kinds wrong (zh-src.zip → zh_src_zip ≠
      // "zh-src_zip"). Match the FileInfo.url tail instead: the server
      // builds it as `/api/files/{id}/{urlKind}`.
      const info = Object.values(artifacts).find((f) =>
        f.url.endsWith(`/${urlKind}`),
      );
      if (!info) {
        result.missing.push(urlKind);
        continue;
      }
      const title = attachTitle(item, urlKind, opts.titleHint);
      const dup = seen.get(title);
      if (dup !== undefined) {
        ztoolkit.log(`attach: already attached, skip ${urlKind} "${title}"`);
        result.attached.push({
          kind: urlKind,
          itemID: dup,
          title,
          bytes: info.bytes,
        });
        continue;
      }
      // item.id in the leaf: two items on one server-deduped task would
      // otherwise race the same temp path (torn write → corrupt attachment).
      const tmpLeaf = `texlate_${item.id}_${taskId}_${urlKind}`.replace(
        /[^a-zA-Z0-9._-]/g,
        "_",
      );
      const tmpPath = PathUtils.join(PathUtils.tempDir, tmpLeaf);
      temps.push(tmpPath);
      try {
        const got = await client.downloadFile(taskId, urlKind, tmpPath, {
          expectPdf: urlKind.endsWith(".pdf"),
        });
        // NULL sha256（登记时产物缺席——worker/emit.py _register 记 NULL）
        // = 无校验基线，与 server `?version=` 的 `rec.get("sha256")` 空判
        // 同口径：跳过比对放行；真缺件早在 downloadFile 的 404 落网。
        if (
          info.sha256 != null &&
          got.sha256.toLowerCase() !== info.sha256.toLowerCase()
        ) {
          result.failed.push({
            kind: urlKind,
            reason: `sha256 mismatch expected ${info.sha256} got ${got.sha256}`,
          });
          continue;
        }
        const dot = urlKind.lastIndexOf(".");
        const ext = dot >= 0 ? urlKind.slice(dot) : "";
        const leaf =
          Zotero.File.getValidFileName(title + ext) || `texlate${ext}`;
        const base = leaf.toLowerCase().endsWith(ext.toLowerCase())
          ? leaf.slice(0, leaf.length - ext.length)
          : leaf;
        const att = await Zotero.Attachments.importFromFile({
          file: tmpPath,
          parentItemID: item.id,
          libraryID: item.libraryID,
          title,
          fileBaseName: base,
        });
        if (!att?.id) throw new Error("importFromFile returned no attachment");
        seen.set(title, att.id);
        result.attached.push({
          kind: urlKind,
          itemID: att.id,
          title,
          bytes: got.bytes,
        });
      } catch (e) {
        result.failed.push({ kind: urlKind, reason: errText(e) });
      }
    }
    // Mark withheld while any kind failed — a marked item short-circuits
    // future translates (getTexlateMark → flow-already-translated), which
    // would strand the failed kinds with no retry path. Missing kinds don't
    // block: the translation exists and the reader link is valid.
    if (result.failed.length === 0) {
      await setTexlateMark(item, taskId);
    } else {
      ztoolkit.log(
        `attach: ${result.failed.length} kind(s) failed, mark withheld for retry`,
      );
    }
  } finally {
    for (const t of temps) {
      try {
        await IOUtils.remove(t, { ignoreAbsent: true });
      } catch (e) {
        ztoolkit.log(`attach: temp cleanup failed ${t}: ${errText(e)}`);
      }
    }
  }
  return result;
}

/** Parse `texlate: {taskId}` from item Extra. null = never translated. */
export function getTexlateMark(item: Zotero.Item): string | null {
  return readExtra(item).match(MARK_RE)?.[1] ?? null;
}

/**
 * Write `texlate: {taskId}` into Extra: replace our mark line if present,
 * else append it on its own line at the end. Other lines kept byte-for-byte.
 */
export async function setTexlateMark(
  item: Zotero.Item,
  taskId: string,
): Promise<void> {
  const line = `texlate: ${taskId}`;
  const extra = readExtra(item);
  const lines = extra === "" ? [] : extra.split("\n");
  const idx = lines.findIndex((l) => MARK_LINE_RE.test(l));
  if (idx >= 0) lines[idx] = line;
  else if (lines.length > 0 && lines[lines.length - 1] === "")
    lines.splice(-1, 0, line);
  else lines.push(line);
  item.setField("extra", lines.join("\n"));
  await item.saveTx();
}
